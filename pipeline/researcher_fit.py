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

두 사내 LLM 비교(profile 인자): match_by_target/match_by_researcher/
run_matching_llm은 profile을 받아 최종 판단 LLM 호출에만 반영한다.
compute_embeddings(BGE-M3 임베딩)는 두 profile이 항상 공유하며 profile
인자를 받지 않는다(임베딩 모델은 비교 대상이 아님).
"""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR  # noqa: E402
sys.path.insert(0, BASE_DIR)
from llm_client import call_llm, extract_json, max_concurrency, run_concurrent  # noqa: E402
from services.llm import LLMError, embed  # noqa: E402,F401 (embed/LLMError는 호출부에서도 사용)

TOP_K = 5

FIT_BADGE = {'상': 'text-bg-success', '중': 'text-bg-warning', '하': 'text-bg-danger'}

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
                      label_prefix: str, result_key: str, profile: str = 'default') -> list:
    """익명 라벨(예: 후보자 A/B/C)로 후보들을 제시하고 LLM 판정을 받아
    [{'idx', 'fit_score', 'reason'}, ...] 형태로 반환(라벨→인덱스로 역매핑)."""
    labels = [f'{label_prefix} {_label_of(i)}' for i in range(len(candidate_texts))]
    cand_block = '\n\n'.join(f'[{lbl}]\n{txt}' for lbl, txt in zip(labels, candidate_texts))
    prompt = f'{subject_block}\n\n[후보 목록]\n{cand_block}\n\n위 정보를 바탕으로 각 후보의 적합도를 판단해 주세요.'

    raw = call_llm(prompt, system_prompt, temperature=0.2, max_tokens=2000, profile=profile)
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


def compute_embeddings(job_texts: list, researcher_texts: list):
    """실패 시 LLMError를 그대로 전파한다(호출부가 잡아서 처리)."""
    job_emb = np.array(embed(job_texts), dtype=np.float32)
    researcher_emb = np.array(embed(researcher_texts), dtype=np.float32)
    return job_emb, researcher_emb


def match_by_target(jobs: list, researcher_ids: list, researcher_texts: list,
                     job_texts: list, sims: np.ndarray, log_prefix: str = '',
                     profile: str = 'default') -> list:
    """직무별 상위 K명 연구원을 추출한 뒤 LLM 판단. 후보 추출(로컬 계산)은 순차로
    준비하고, 실제 LLM 판단 호출은 profile의 동시 호출 허용치만큼 스레드풀로
    동시에 실행한다(journal_authority.py/process_researcher_expertise.py와 동일한
    패턴) — 개별 직무 판단 중 예기치 못한 예외가 나도 다른 직무 판단은 계속
    진행하고, 실패한 직무만 에러와 함께 로그로 남긴다(판단 결과 없음으로 처리).
    반환: [{'target_id','target_name','job_title','rankings':[{'researcher_id','fit_score','reason'}]}]"""
    prepared = []
    for j_idx, job in enumerate(jobs):
        top_idx = top_k_idx(sims[:, j_idx], min(TOP_K, len(researcher_ids)))
        candidate_texts = [researcher_texts[i] for i in top_idx]
        subject_block = f'[직무 요구사항]\n{job_texts[j_idx]}'
        prepared.append((job, top_idx, subject_block, candidate_texts))

    workers = max_concurrency(profile)
    total = len(prepared)
    print(f'{log_prefix}과제 기준 매칭 {total}건 판단 시작 (동시 {workers}건, profile={profile})...')
    completed = 0

    def _on_complete(_i, _result, _error):
        nonlocal completed
        completed += 1
        if completed % 5 == 0 or completed == total:
            print(f'{log_prefix}    (진행: {completed}/{total} 완료)')

    tasks = [
        (lambda sb=subject_block, ct=candidate_texts: run_matching_llm(
            SYSTEM_PROMPT_BY_TARGET, sb, ct, '후보자', 'rankings', profile=profile))
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
                         job_texts: list, sims: np.ndarray, log_prefix: str = '',
                         profile: str = 'default') -> list:
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

    workers = max_concurrency(profile)
    total = len(prepared)
    print(f'{log_prefix}인별 기준 매칭 {total}건 판단 시작 (동시 {workers}건, profile={profile})...')
    completed = 0

    def _on_complete(_i, _result, _error):
        nonlocal completed
        completed += 1
        if completed % 5 == 0 or completed == total:
            print(f'{log_prefix}    (진행: {completed}/{total} 완료)')

    tasks = [
        (lambda sb=subject_block, ct=candidate_texts: run_matching_llm(
            SYSTEM_PROMPT_BY_RESEARCHER, sb, ct, '후보 직무', 'matches', profile=profile))
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


EXTRA_STYLE = """
  .fit-card {
    max-width: 960px; margin: 0 auto 24px; border: 1px solid var(--gs-border);
    border-radius: 16px; background: var(--gs-surface); box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .fit-card .card-body { padding: 22px 26px; }
  .fit-card h3 { font-size: 1rem; font-weight: 700; margin: 0 0 2px; }
  .fit-card .subtitle { color: var(--gs-muted); font-size: 0.78rem; margin: 0 0 14px; }
  .rank-row {
    border: 1px solid var(--gs-border); border-radius: 10px; padding: 10px 14px; margin-bottom: 8px;
    background: #fafafa;
  }
  .rank-row:last-child { margin-bottom: 0; }
  .rank-row .name { font-weight: 700; font-size: 0.86rem; }
  .rank-row .reason { font-size: 0.78rem; color: #444; margin-top: 3px; }
  .nav-tabs .nav-link { font-weight: 600; color: var(--gs-muted); }
  .nav-tabs .nav-link.active { color: var(--gs-text); }
"""


def fit_badge(score: str) -> str:
    css = FIT_BADGE.get(score, 'text-bg-secondary')
    return f'<span class="badge rounded-pill {css}">적합도 {score or "-"}</span>'


def build_fit_html(by_target: list, by_researcher: list, researchers_df: pd.DataFrame, *,
                    page_title: str, heading: str, subtitle: str,
                    target_tab_label: str, target_header, target_card_subtitle: str,
                    researcher_card_subtitle: str) -> str:
    """target_header(item) -> str: by_target 카드 제목을 렌더링하는 콜백
    (예: 과제는 '부서 · 과제명 — 직무명')."""
    import rd_specialist_markdown as mmd

    name_map = {}
    if not researchers_df.empty:
        name_map = researchers_df.set_index('researcher_id')['name'].to_dict()

    target_cards = []
    for item in by_target:
        rows = ''.join(
            f'''<div class="rank-row d-flex justify-content-between align-items-start gap-2">
  <div>
    <div class="name">{r['researcher_id']} {name_map.get(r['researcher_id'], '')}</div>
    <div class="reason">{r['reason']}</div>
  </div>
  {fit_badge(r['fit_score'])}
</div>'''
            for r in item['rankings']
        ) or '<p class="empty">판단 결과 없음</p>'
        target_cards.append(f'''<div class="fit-card card">
  <div class="card-body">
    <h3>{target_header(item)}</h3>
    <p class="subtitle">{target_card_subtitle}</p>
    {rows}
  </div>
</div>''')

    researcher_cards = []
    for item in by_researcher:
        rid = item['researcher_id']
        rows = ''.join(
            f'''<div class="rank-row d-flex justify-content-between align-items-start gap-2">
  <div>
    <div class="name">{m['target_name']} — {m['job_title']}</div>
    <div class="reason">{m['reason']}</div>
  </div>
  {fit_badge(m['fit_score'])}
</div>'''
            for m in item['matches']
        ) or '<p class="empty">판단 결과 없음</p>'
        researcher_cards.append(f'''<div class="fit-card card">
  <div class="card-body">
    <h3>{rid} {name_map.get(rid, '')}</h3>
    <p class="subtitle">{researcher_card_subtitle}</p>
    {rows}
  </div>
</div>''')

    body_html = f'''<ul class="nav nav-tabs justify-content-center mb-4" id="fit-tabs" role="tablist">
  <li class="nav-item" role="presentation">
    <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#by-target" type="button">{target_tab_label}</button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#by-researcher" type="button">인별 기준</button>
  </li>
</ul>
<div class="tab-content">
  <div class="tab-pane fade show active" id="by-target">{''.join(target_cards)}</div>
  <div class="tab-pane fade" id="by-researcher">{''.join(researcher_cards)}</div>
</div>'''

    return mmd.html_page(
        title=page_title, heading=heading, subtitle=subtitle,
        body_html=body_html, extra_style=EXTRA_STYLE,
    )
