"""
연구 대상("기술" 또는 사내 "과제")과 연구원 간 적합도 매칭 공용 로직.

process_project_researcher_fit.py(사내 과제 ↔ 연구원)가 이 로직을 사용한다.

연구원/직무가 많아지면 전수 비교(LLM 호출)가 비현실적이므로, 먼저 사내
임베딩(services/llm.embed, BGE-M3)으로 코사인 유사도 상위 후보만 추린 뒤,
그 후보에 대해서만 "R&D Talent Matching Agent"(R&D Project Specialist Agent와
동일한 팩트 기반 철학을 계승) 역할의 사내 LLM이 최종 적합도와 근거를 판단한다.

※ LLM 프롬프트에는 researcher_id/이름을 절대 포함하지 않는다. 후보를
  "후보자 A/B/C..."로 익명 라벨링해 전달하고, 결과는 호출부에서 다시
  researcher_id로 매핑한다.

임베딩은 텍스트 내용 해시 기준으로 캐시(cached_embed, embedding_cache.json)해
재사용한다 — process_project_researcher_fit.py(과제↔연구원)와
process_researcher_similarity.py(연구원↔연구원)가 같은 연구원 프로필
텍스트(researcher_profile_text)를 각자 다시 임베딩하지 않고 캐시를 공유한다.
캐시 키가 텍스트 내용 자체의 해시라, 연구원 전문성 분석이 갱신돼 텍스트가
바뀌면 자동으로 새 항목으로 취급돼 별도 새로고침 옵션 없이도 항상 최신
텍스트에 맞는 임베딩을 쓴다.
"""

import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, OUT_DIR  # noqa: E402
sys.path.insert(0, BASE_DIR)
from llm_client import call_llm, extract_json, max_concurrency, run_concurrent  # noqa: E402
from services.llm import LLMError, embed  # noqa: E402,F401 (embed/LLMError는 호출부에서도 사용)

TOP_K = 5

_EMBED_CACHE_PATH = os.path.join(OUT_DIR, 'embedding_cache.json')

FIT_VARIANT = {'상': 'good', '중': 'warn', '하': 'low'}

_HARD_SKILL_LABELS = [
    ('languages_frameworks', '개발 언어 및 프레임워크'),
    ('hardware_equipment_control', '하드웨어 및 장비 제어'),
    ('analysis_simulation_tools', '분석 및 시뮬레이션 툴'),
]
_DOMAIN_LABELS = [
    ('academic_theoretical_background', '학술적/이론적 배경'),
    ('industry_standards', '산업/기술 표준 및 규격'),
    ('patent_trend_understanding', '특허 및 트렌드 이해도'),
]

SYSTEM_PROMPT_BY_TARGET = """# Role
당신은 R&D 인재 배치 전문가인 "R&D Talent Matching Agent"입니다. "R&D Project
Specialist Agent"와 동일하게 오직 팩트(Fact) 기반으로 분석하되, 이번에는 기술/
과제의 직무 요구사항을 정의하는 대신, 그 요구사항에 후보자들이 얼마나 부합하는지
비교·판단하는 역할을 수행합니다.

# Goal
R&D 부서장이 이 직무에 어떤 인력을 배치할지 객관적으로 판단할 수 있도록,
후보자별 적합도(상/중/하)와 그 판단 근거를 제공합니다.

# Guidelines & Constraints
1. 철저한 팩트 기반: 후보자 프로필에 명시되지 않은 역량을 임의로 추정해서
   적합하다고 판단하지 마세요.
2. 직무 요구사항(R&D Task, Hard Skills, Domain Knowledge, 역량 레벨 등)과
   후보자 프로필의 구체적 항목을 근거로 비교하세요.
3. 근거가 부족해 판단이 애매하면 fit_score를 "중" 또는 "하"로 낮추고 이유를
   reason에 명시하세요.
4. 반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.

# Output Format (JSON)
{
  "rankings": [
    {"candidate": "후보자 라벨", "fit_score": "상|중|하", "reason": "팩트 기반 판단 근거"}
  ]
}
※ rankings는 적합도 높은 순으로 정렬하고, 전달된 후보자 전원에 대해 판단하세요.
"""

SYSTEM_PROMPT_BY_RESEARCHER = """# Role
당신은 R&D 인재 배치 전문가인 "R&D Talent Matching Agent"입니다. "R&D Project
Specialist Agent"와 동일하게 오직 팩트(Fact) 기반으로 분석하되, 이번에는 한
연구원의 보유 전문성 프로필과 여러 후보 직무의 요구사항을 비교해 어떤 직무가
이 연구원에게 가장 적합한지 판단하는 역할을 수행합니다.

# Goal
HR 담당자가 이 연구원을 어떤 프로젝트/직무에 배치하면 좋을지 객관적으로 판단할
수 있도록, 후보 직무별 적합도(상/중/하)와 그 판단 근거를 제공합니다.

# Guidelines & Constraints
1. 철저한 팩트 기반: 연구원 프로필에 명시되지 않은 역량이 그 직무에 있다고
   임의로 추정하지 마세요.
2. 각 후보 직무의 요구사항(R&D Task, Hard Skills, Domain Knowledge 등)과
   연구원 프로필의 구체적 항목을 근거로 비교하세요.
3. 근거가 부족해 판단이 애매하면 fit_score를 "중" 또는 "하"로 낮추고 이유를
   reason에 명시하세요.
4. 반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.

# Output Format (JSON)
{
  "matches": [
    {"candidate": "후보 직무 라벨", "fit_score": "상|중|하", "reason": "팩트 기반 판단 근거"}
  ]
}
※ matches는 적합도 높은 순으로 정렬하고, 전달된 후보 직무 전원에 대해 판단하세요.
"""


def read_json(out_dir: str, name: str) -> list:
    path = os.path.join(out_dir, f'{name}.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def read_researchers(out_dir: str) -> pd.DataFrame:
    path = os.path.join(out_dir, 'researchers.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def researcher_profile_text(profile: dict) -> str:
    parts = []
    if profile.get('strength_fields'):
        parts.append('강점 분야: ' + ', '.join(profile['strength_fields']))
    if profile.get('strength_keywords'):
        parts.append('강점 키워드: ' + ', '.join(profile['strength_keywords']))
    hard_skills = profile.get('hard_skills', {})
    for key, label in _HARD_SKILL_LABELS:
        if hard_skills.get(key):
            parts.append(f'{label}: {hard_skills[key]}')
    domain_knowledge = profile.get('domain_knowledge', {})
    for key, label in _DOMAIN_LABELS:
        if domain_knowledge.get(key):
            parts.append(f'{label}: {domain_knowledge[key]}')
    return '\n'.join(parts) if parts else '(전문성 데이터 없음)'


def job_text(job: dict) -> str:
    """job: {'target_name', 'title', 'body_raw', ...}"""
    return f"[{job['target_name']}] {job['title']}\n{job['body_raw']}".strip()


def cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return a_norm @ b_norm.T


def top_k_idx(sims_row: np.ndarray, k: int) -> list:
    order = np.argsort(-sims_row)
    return order[:k].tolist()


def _label_of(i: int) -> str:
    return chr(65 + i) if i < 26 else f'X{i}'


def run_matching_llm(system_prompt: str, subject_block: str, candidate_texts: list,
                      label_prefix: str, result_key: str) -> list:
    """익명 라벨(예: 후보자 A/B/C)로 후보들을 제시하고 LLM 판정을 받아
    [{'idx', 'fit_score', 'reason'}, ...] 형태로 반환(라벨→인덱스로 역매핑)."""
    labels = [f'{label_prefix} {_label_of(i)}' for i in range(len(candidate_texts))]
    cand_block = '\n\n'.join(f'[{lbl}]\n{txt}' for lbl, txt in zip(labels, candidate_texts))
    prompt = f'{subject_block}\n\n[후보 목록]\n{cand_block}\n\n위 정보를 바탕으로 각 후보의 적합도를 판단해 주세요.'

    # 추론형 모델의 사고 과정 토큰 소모를 감안해 여유 있게 잡는다(finish_reason=length 방지).
    raw = call_llm(prompt, system_prompt, temperature=0.2, max_tokens=3000)
    if not raw:
        return []
    try:
        result = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return []

    label_to_idx = {lbl: i for i, lbl in enumerate(labels)}
    out = []
    for item in result.get(result_key, []):
        idx = label_to_idx.get(str(item.get('candidate', '')).strip())
        if idx is None:
            continue
        out.append({'idx': idx, 'fit_score': item.get('fit_score', ''), 'reason': item.get('reason', '')})
    return out


def check_embed_server():
    """본격적인 작업(JSON 로딩, 직무/연구원 텍스트 구성 등) 전에 BGE-M3 임베딩
    서버가 응답하는지 가볍게 먼저 확인한다. 실패 시 LLMError를 그대로 전파한다
    (호출부가 잡아서 '서버가 기동 중인지 확인하세요' 안내 후 즉시 종료할 수 있도록)."""
    embed(['ping'])


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _load_embed_cache() -> dict:
    if not os.path.exists(_EMBED_CACHE_PATH):
        return {}
    with open(_EMBED_CACHE_PATH, encoding='utf-8') as f:
        return json.load(f)


def _save_embed_cache(cache: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_EMBED_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f)


def cached_embed(texts: list) -> np.ndarray:
    """embed()를 텍스트 내용 해시 기준으로 캐시해 재사용한다. 임베딩은 profile과
    무관하게 항상 같은 BGE-M3 결과이므로, process_project_researcher_fit.py와
    process_researcher_similarity.py가 같은 연구원 프로필 텍스트를 각자 다시
    임베딩하지 않고 이 캐시(embedding_cache.json)를 공유한다. 캐시에 없는
    텍스트만 모아 한 번에 embed() 호출하고(실패 시 LLMError 그대로 전파),
    결과를 캐시에 채운 뒤 저장한다."""
    cache = _load_embed_cache()
    hashes = [_text_hash(t) for t in texts]
    missing_idx = [i for i, h in enumerate(hashes) if h not in cache]
    if missing_idx:
        new_vectors = embed([texts[i] for i in missing_idx])
        for i, vec in zip(missing_idx, new_vectors):
            cache[hashes[i]] = vec
        _save_embed_cache(cache)
    return np.array([cache[h] for h in hashes], dtype=np.float32)


def compute_embeddings(job_texts: list, researcher_texts: list):
    """실패 시 LLMError를 그대로 전파한다(호출부가 잡아서 처리). cached_embed로
    텍스트 해시 기준 캐시를 사용한다."""
    job_emb = cached_embed(job_texts)
    researcher_emb = cached_embed(researcher_texts)
    return job_emb, researcher_emb


def match_by_target(jobs: list, researcher_ids: list, researcher_texts: list,
                     job_texts: list, sims: np.ndarray, log_prefix: str = '') -> list:
    """직무별 상위 K명 연구원을 추출한 뒤 LLM 판단. 후보 추출(로컬 계산)은 순차로
    준비하고, 실제 LLM 판단 호출은 동시 호출 허용치만큼 스레드풀로 동시에
    실행한다(journal_authority.py/process_researcher_expertise.py와 동일한
    패턴) — 개별 직무 판단 중 예기치 못한 예외가 나도 다른 직무 판단은 계속
    진행하고, 실패한 직무만 에러와 함께 로그로 남긴다(판단 결과 없음으로 처리).
    반환: [{'target_id','target_name','job_title','rankings':[{'researcher_id','fit_score','reason'}]}]"""
    prepared = []
    for j_idx, job in enumerate(jobs):
        top_idx = top_k_idx(sims[:, j_idx], min(TOP_K, len(researcher_ids)))
        candidate_texts = [researcher_texts[i] for i in top_idx]
        subject_block = f'[직무 요구사항]\n{job_texts[j_idx]}'
        prepared.append((job, top_idx, subject_block, candidate_texts))

    workers = max_concurrency()
    total = len(prepared)
    print(f'{log_prefix}과제 기준 매칭 {total}건 판단 시작 (동시 {workers}건)...')
    completed = 0

    def _on_complete(_i, _result, _error):
        nonlocal completed
        completed += 1
        if completed % 5 == 0 or completed == total:
            print(f'{log_prefix}    (진행: {completed}/{total} 완료)')

    tasks = [
        (lambda sb=subject_block, ct=candidate_texts: run_matching_llm(
            SYSTEM_PROMPT_BY_TARGET, sb, ct, '후보자', 'rankings'))
        for _, _, subject_block, candidate_texts in prepared
    ]
    task_results = run_concurrent(tasks, max_workers=workers, on_complete=_on_complete)

    results = []
    for (job, top_idx, _, _), (judged, error) in zip(prepared, task_results):
        if error is not None:
            print(f"{log_prefix}[{job['target_name']} / {job['title']}] 판단 오류: "
                  f"{type(error).__name__}: {error}")
            judged = []
        rankings = [
            {'researcher_id': researcher_ids[top_idx[r['idx']]], 'fit_score': r['fit_score'], 'reason': r['reason']}
            for r in judged
        ]
        results.append({
            'target_id': job['target_id'], 'target_name': job['target_name'], 'job_title': job['title'],
            'rankings': rankings,
        })
        print(f"{log_prefix}[{job['target_name']} / {job['title']}] 후보 {len(top_idx)}명 중 {len(rankings)}명 판단")
    return results


def match_by_researcher(jobs: list, researcher_ids: list, researcher_texts: list,
                         job_texts: list, sims: np.ndarray, log_prefix: str = '') -> list:
    """연구원별 상위 K건 직무를 추출한 뒤 LLM 판단. match_by_target과 동일하게
    후보 추출은 순차 준비, 실제 LLM 판단은 동시 실행한다.
    반환: [{'researcher_id','matches':[{'target_id','target_name','job_title','fit_score','reason'}]}]"""
    prepared = []
    for r_idx, rid in enumerate(researcher_ids):
        top_idx = top_k_idx(sims[r_idx, :], min(TOP_K, len(jobs)))
        candidate_jobs = [jobs[i] for i in top_idx]
        candidate_texts = [job_texts[i] for i in top_idx]
        subject_block = f'[연구원 전문성 프로필]\n{researcher_texts[r_idx]}'
        prepared.append((rid, candidate_jobs, subject_block, candidate_texts))

    workers = max_concurrency()
    total = len(prepared)
    print(f'{log_prefix}인별 기준 매칭 {total}건 판단 시작 (동시 {workers}건)...')
    completed = 0

    def _on_complete(_i, _result, _error):
        nonlocal completed
        completed += 1
        if completed % 5 == 0 or completed == total:
            print(f'{log_prefix}    (진행: {completed}/{total} 완료)')

    tasks = [
        (lambda sb=subject_block, ct=candidate_texts: run_matching_llm(
            SYSTEM_PROMPT_BY_RESEARCHER, sb, ct, '후보 직무', 'matches'))
        for _, _, subject_block, candidate_texts in prepared
    ]
    task_results = run_concurrent(tasks, max_workers=workers, on_complete=_on_complete)

    results = []
    for (rid, candidate_jobs, _, _), (judged, error) in zip(prepared, task_results):
        if error is not None:
            print(f'{log_prefix}[{rid}] 판단 오류: {type(error).__name__}: {error}')
            judged = []
        matches = [
            {
                'target_id': candidate_jobs[m['idx']]['target_id'],
                'target_name': candidate_jobs[m['idx']]['target_name'],
                'job_title': candidate_jobs[m['idx']]['title'],
                'fit_score': m['fit_score'],
                'reason': m['reason'],
            }
            for m in judged
        ]
        results.append({'researcher_id': rid, 'matches': matches})
        print(f'{log_prefix}[{rid}] 후보 {len(candidate_jobs)}건 중 {len(matches)}건 판단')
    return results


def _fit_pill_html(score: str) -> str:
    variant = FIT_VARIANT.get(score, 'low')
    return f'<span class="pill {variant}">적합도 {score or "-"}</span>'


def build_fit_html(by_target: list, by_researcher: list, researchers_df: pd.DataFrame, *,
                    page_title: str, target_tab_label: str, researcher_tab_label: str,
                    target_header, target_card_subtitle: str, researcher_card_subtitle: str,
                    target_dep_map: dict | None = None) -> str:
    """콘솔형 리포트(사이드바 + 요약 통계 + CSS 전용 라디오 탭 "과제 기준"/"인별
    기준" + 표 형태 적합도 목록)로 렌더링한다.
    target_header(item) -> str: by_target 카드 제목을 렌더링하는 콜백
    (예: 과제는 '부서 · 과제명 — 직무명').
    target_dep_map: {target_name: dep_name} — 조직도(team_refer.csv)가 있으면
    end_name==dep_name(부서명 텍스트 일치)으로 과제·직무를 해당 조직 노드
    밑에 붙인다. 없으면(None) 과제 기준 사이드바는 조직도 없이 평면 목록으로."""
    import html
    import re
    import rd_specialist_markdown as mmd

    name_map, org_map = {}, {}
    if not researchers_df.empty:
        indexed = researchers_df.set_index('researcher_id')
        name_map = indexed['name'].to_dict()
        org_map = indexed['org_code'].to_dict()
    target_dep_map = target_dep_map or {}

    def _slug(text: str) -> str:
        return re.sub(r'[^0-9A-Za-z가-힣]+', '-', text or '').strip('-') or 'x'

    anchor_t, seen_t = {}, {}
    for i, item in enumerate(by_target):
        base = f"t-{_slug(item['target_name'])}-{_slug(item['job_title'])}"
        seen_t[base] = seen_t.get(base, 0) + 1
        anchor_t[i] = base if seen_t[base] == 1 else f'{base}-{seen_t[base]}'
    anchor_r = {i: f'r-{item["researcher_id"]}' for i, item in enumerate(by_researcher)}

    org_tree = mmd.build_org_tree(mmd.read_team_refer(OUT_DIR))
    if org_tree:
        targets_by_dep: dict = {}
        for i, item in enumerate(by_target):
            dep = target_dep_map.get(item['target_name'], '')
            targets_by_dep.setdefault(dep, []).append(
                (f'#{anchor_t[i]}', f"{item['target_name']} — {item['job_title']}", None)
            )
        researchers_by_org: dict = {}
        for i, item in enumerate(by_researcher):
            rid = item['researcher_id']
            researchers_by_org.setdefault(org_map.get(rid, ''), []).append(
                (f'#{anchor_r[i]}', name_map.get(rid, rid), len(item['matches']))
            )

        nav_target = mmd.org_tree_html(
            org_tree, lambda node: mmd.nav_items_html(targets_by_dep.get(node.get('end_name', ''), [])))
        nav_researcher = mmd.org_tree_html(
            org_tree, lambda node: mmd.nav_items_html(researchers_by_org.get(node.get('project_name', ''), [])))
    else:
        nav_target = ''.join(
            f'<a class="nav-item" href="#{anchor_t[i]}">{html.escape(target_header(item))}</a>'
            for i, item in enumerate(by_target)
        )
        nav_researcher = ''.join(
            f'<a class="nav-item" href="#{anchor_r[i]}">'
            f'{html.escape(item["researcher_id"])} {html.escape(name_map.get(item["researcher_id"], ""))}</a>'
            for i, item in enumerate(by_researcher)
        )
    sidebar = (
        f'<h1>{page_title}</h1>'
        '<p class="tagline">임베딩 1차 후보 + 사내 LLM 최종 판단 (R&amp;D Talent Matching Agent)</p>'
        f'<div class="nav-group"><div class="nav-group-label">{target_tab_label}</div>{nav_target}</div>'
        f'<div class="nav-group"><div class="nav-group-label">{researcher_tab_label}</div>{nav_researcher}</div>'
    )

    total_targets = len(by_target)
    total_candidates = sum(len(t['rankings']) for t in by_target)
    high_fit = sum(1 for t in by_target for r in t['rankings'] if r['fit_score'] == '상')
    stats = mmd.stat_row_html([
        (total_targets, f'매칭 대상 {target_tab_label}'),
        (total_candidates, '총 후보 판단 건수'),
        (high_fit, '적합도 "상" 건수'),
    ])

    target_sections = []
    for i, item in enumerate(by_target):
        rows = ''.join(
            f'''<tr>
  <td class="m-name">{html.escape(r['researcher_id'])} {html.escape(name_map.get(r['researcher_id'], ''))}</td>
  <td>{_fit_pill_html(r['fit_score'])}</td>
  <td><p class="m-ev-text">{html.escape(r['reason'])}</p></td>
</tr>'''
            for r in item['rankings']
        ) or '<tr><td colspan="3" class="empty">판단 결과 없음</td></tr>'
        target_sections.append(f'''<div class="card" id="{anchor_t[i]}">
  <div class="card-top"><h3>{html.escape(target_header(item))}</h3></div>
  <p class="card-sub">{html.escape(target_card_subtitle)}</p>
  <div class="table-wrap"><table class="match-table">
    <thead><tr><th>연구원</th><th>적합도</th><th>판단 근거</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>''')

    researcher_sections = []
    for i, item in enumerate(by_researcher):
        rid = item['researcher_id']
        rows = ''.join(
            f'''<tr>
  <td class="m-name">{html.escape(m['target_name'])} — {html.escape(m['job_title'])}</td>
  <td>{_fit_pill_html(m['fit_score'])}</td>
  <td><p class="m-ev-text">{html.escape(m['reason'])}</p></td>
</tr>'''
            for m in item['matches']
        ) or '<tr><td colspan="3" class="empty">판단 결과 없음</td></tr>'
        researcher_sections.append(f'''<div class="card" id="{anchor_r[i]}">
  <div class="card-top"><h3>{html.escape(rid)} {html.escape(name_map.get(rid, ''))}</h3>{mmd.map_link_html(rid)}</div>
  <p class="card-sub">{html.escape(researcher_card_subtitle)}</p>
  <div class="table-wrap"><table class="match-table">
    <thead><tr><th>과제 · 직무</th><th>적합도</th><th>판단 근거</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>''')

    body = f'''<div class="tabs">
  <input type="radio" name="tab" id="tab-a" checked>
  <input type="radio" name="tab" id="tab-b">
  {stats}
  <div class="tab-bar">
    <label for="tab-a">{target_tab_label}</label>
    <label for="tab-b">{researcher_tab_label}</label>
  </div>
  <div class="panel-a">{"".join(target_sections)}</div>
  <div class="panel-b">{"".join(researcher_sections)}</div>
</div>'''

    return mmd.console_page(page_title, sidebar, body)
