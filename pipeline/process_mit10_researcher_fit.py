"""
MIT 10대 기술 ↔ 연구원 적합도 매칭 모듈

2026MITTech10.json의 기술별 직무 딥다이브 매핑("R&D 필수 전문성 및 직무
딥다이브 매핑" 섹션)과 연구원 보유 전문성 분석.json을 서로 비교해, 두 방향으로
적합도를 판단한다.
  1) 기술 기준: 각 기술의 각 직무에 어떤 연구원이 적합한지
  2) 인별 기준: 각 연구원이 MIT10 어떤 기술의 어떤 직무와 맞는지

연구원/직무가 많아지면 전수 비교(LLM 호출)가 비현실적이므로, 먼저 사내
임베딩(services/llm.embed, BGE-M3)으로 코사인 유사도 상위 후보만 추린 뒤,
그 후보에 대해서만 "R&D Talent Matching Agent"(R&D Project Specialist Agent와
동일한 팩트 기반 철학을 계승) 역할의 사내 LLM이 최종 적합도와 근거를 판단한다.

Source:
  data/processed/2026MITTech10.json           (process_mit10.py --llm 로 생성)
  data/processed/연구원 보유 전문성 분석.json   (process_researcher_expertise.py)
  data/processed/researchers.csv               (HTML에 이름 표시용)

Output:
  data/processed/mit10_fit_by_tech.json
  data/processed/mit10_fit_by_researcher.json
  data/processed/mit10_researcher_fit.html     (두 방향을 한 페이지에 함께 시각화)

※ LLM 프롬프트에는 researcher_id/이름을 절대 포함하지 않는다. 후보를
  "후보자 A/B/C..."로 익명 라벨링해 전달하고, 결과는 호출부에서 다시
  researcher_id로 매핑한다.

사용법:
  python pipeline/process_mit10_researcher_fit.py
"""

import json
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import mit_markdown as mmd  # noqa: E402
from llm_client import call_llm, extract_json  # noqa: E402
from services.llm import LLMError, embed  # noqa: E402

TOP_K = 5

_FIT_BADGE = {'상': 'text-bg-success', '중': 'text-bg-warning', '하': 'text-bg-danger'}

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

_SYSTEM_PROMPT_BY_TECH = """# Role
당신은 R&D 인재 배치 전문가인 "R&D Talent Matching Agent"입니다. "R&D Project
Specialist Agent"와 동일하게 오직 팩트(Fact) 기반으로 분석하되, 이번에는 기술의
직무 요구사항을 정의하는 대신, 그 요구사항에 후보자들이 얼마나 부합하는지
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

_SYSTEM_PROMPT_BY_RESEARCHER = """# Role
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


def _read_json(name: str) -> list:
    path = os.path.join(OUT_DIR, f'{name}.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _read_researchers() -> pd.DataFrame:
    path = os.path.join(OUT_DIR, 'researchers.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def _researcher_profile_text(profile: dict) -> str:
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


def _job_text(job: dict) -> str:
    return f"[{job['tech_name']}] {job['title']}\n{job['body_raw']}".strip()


def _cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return a_norm @ b_norm.T


def _top_k_idx(sims_row: np.ndarray, k: int) -> list:
    order = np.argsort(-sims_row)
    return order[:k].tolist()


def _label_of(i: int) -> str:
    return chr(65 + i) if i < 26 else f'X{i}'


def _run_matching_llm(system_prompt: str, subject_block: str, candidate_texts: list,
                       label_prefix: str, result_key: str) -> list:
    """익명 라벨(예: 후보자 A/B/C)로 후보들을 제시하고 LLM 판정을 받아
    [{'idx', 'fit_score', 'reason'}, ...] 형태로 반환(라벨→인덱스로 역매핑)."""
    labels = [f'{label_prefix} {_label_of(i)}' for i in range(len(candidate_texts))]
    cand_block = '\n\n'.join(f'[{lbl}]\n{txt}' for lbl, txt in zip(labels, candidate_texts))
    prompt = f'{subject_block}\n\n[후보 목록]\n{cand_block}\n\n위 정보를 바탕으로 각 후보의 적합도를 판단해 주세요.'

    raw = call_llm(prompt, system_prompt, temperature=0.2, max_tokens=2000)
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


def process() -> bool:
    mit10 = _read_json('2026MITTech10')
    if not mit10:
        print('[process_mit10_researcher_fit] 2026MITTech10.json 없음 — 종료 (process_mit10.py 먼저 실행)')
        return False

    researcher_profiles = _read_json('연구원 보유 전문성 분석')
    if not researcher_profiles:
        print('[process_mit10_researcher_fit] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
        return False

    jobs = []
    for tech in mit10:
        for job in mmd.deepdive_jobs(tech.get('expertise_analysis', '')):
            jobs.append({
                'tech_rank': tech.get('rank'),
                'tech_name': tech.get('name'),
                'title': job['title'],
                'body_raw': job['body_raw'],
            })
    if not jobs:
        print('[process_mit10_researcher_fit] MIT10 직무 딥다이브 데이터 없음 — 종료 '
              '(python pipeline/process_mit10.py --llm 실행 필요)')
        return False

    job_texts = [_job_text(j) for j in jobs]
    researcher_ids = [p['researcher_id'] for p in researcher_profiles]
    researcher_texts = [_researcher_profile_text(p) for p in researcher_profiles]

    print(f'[process_mit10_researcher_fit] 직무 {len(jobs)}건, 연구원 {len(researcher_ids)}명 임베딩 계산 중...')
    try:
        job_emb = np.array(embed(job_texts), dtype=np.float32)
        researcher_emb = np.array(embed(researcher_texts), dtype=np.float32)
    except LLMError as exc:
        print(f'[process_mit10_researcher_fit] 임베딩 실패 — 종료: {exc}')
        return False

    sims = _cosine_sim_matrix(researcher_emb, job_emb)  # (n_researchers, n_jobs)

    # ── 기술 기준: 직무별 상위 K명 연구원 추출 후 LLM 판단 ──────────────────
    by_tech_results = []
    print('[process_mit10_researcher_fit] 기술 기준 매칭 중...')
    for j_idx, job in enumerate(jobs):
        top_idx = _top_k_idx(sims[:, j_idx], min(TOP_K, len(researcher_ids)))
        candidate_texts = [researcher_texts[i] for i in top_idx]
        subject_block = f'[직무 요구사항]\n{job_texts[j_idx]}'
        judged = _run_matching_llm(_SYSTEM_PROMPT_BY_TECH, subject_block, candidate_texts, '후보자', 'rankings')
        rankings = [
            {
                'researcher_id': researcher_ids[top_idx[r['idx']]],
                'fit_score': r['fit_score'],
                'reason': r['reason'],
            }
            for r in judged
        ]
        by_tech_results.append({
            'tech_rank': job['tech_rank'], 'tech_name': job['tech_name'], 'job_title': job['title'],
            'rankings': rankings,
        })
        print(f"    [{job['tech_name']} / {job['title']}] 후보 {len(top_idx)}명 중 {len(rankings)}명 판단")

    # ── 인별 기준: 연구원별 상위 K건 직무 추출 후 LLM 판단 ──────────────────
    by_researcher_results = []
    print('[process_mit10_researcher_fit] 인별 기준 매칭 중...')
    for r_idx, rid in enumerate(researcher_ids):
        top_idx = _top_k_idx(sims[r_idx, :], min(TOP_K, len(jobs)))
        candidate_jobs = [jobs[i] for i in top_idx]
        candidate_texts = [job_texts[i] for i in top_idx]
        subject_block = f'[연구원 전문성 프로필]\n{researcher_texts[r_idx]}'
        judged = _run_matching_llm(_SYSTEM_PROMPT_BY_RESEARCHER, subject_block, candidate_texts, '후보 직무', 'matches')
        matches = [
            {
                'tech_rank': candidate_jobs[m['idx']]['tech_rank'],
                'tech_name': candidate_jobs[m['idx']]['tech_name'],
                'job_title': candidate_jobs[m['idx']]['title'],
                'fit_score': m['fit_score'],
                'reason': m['reason'],
            }
            for m in judged
        ]
        by_researcher_results.append({'researcher_id': rid, 'matches': matches})
        print(f'    [{rid}] 후보 {len(top_idx)}건 중 {len(matches)}건 판단')

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, 'mit10_fit_by_tech.json'), 'w', encoding='utf-8') as f:
        json.dump(by_tech_results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   mit10_fit_by_tech.json 저장 ({len(by_tech_results)}건)')

    with open(os.path.join(OUT_DIR, 'mit10_fit_by_researcher.json'), 'w', encoding='utf-8') as f:
        json.dump(by_researcher_results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   mit10_fit_by_researcher.json 저장 ({len(by_researcher_results)}건)')

    html_out = _build_html(by_tech_results, by_researcher_results, _read_researchers())
    html_path = os.path.join(OUT_DIR, 'mit10_researcher_fit.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print('[OK]   mit10_researcher_fit.html 저장')

    return True


_EXTRA_STYLE = """
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


def _fit_badge(score: str) -> str:
    css = _FIT_BADGE.get(score, 'text-bg-secondary')
    return f'<span class="badge rounded-pill {css}">적합도 {score or "-"}</span>'


def _build_html(by_tech: list, by_researcher: list, researchers_df: pd.DataFrame) -> str:
    name_map = {}
    if not researchers_df.empty:
        name_map = researchers_df.set_index('researcher_id')['name'].to_dict()

    tech_cards = []
    for item in by_tech:
        rows = ''.join(
            f'''<div class="rank-row d-flex justify-content-between align-items-start gap-2">
  <div>
    <div class="name">{r['researcher_id']} {name_map.get(r['researcher_id'], '')}</div>
    <div class="reason">{r['reason']}</div>
  </div>
  {_fit_badge(r['fit_score'])}
</div>'''
            for r in item['rankings']
        ) or '<p class="empty">판단 결과 없음</p>'
        tech_cards.append(f'''<div class="fit-card card">
  <div class="card-body">
    <h3>#{item['tech_rank']} {item['tech_name']} — {item['job_title']}</h3>
    <p class="subtitle">이 직무에 적합한 연구원 (적합도 순)</p>
    {rows}
  </div>
</div>''')

    researcher_cards = []
    for item in by_researcher:
        rid = item['researcher_id']
        rows = ''.join(
            f'''<div class="rank-row d-flex justify-content-between align-items-start gap-2">
  <div>
    <div class="name">#{m['tech_rank']} {m['tech_name']} — {m['job_title']}</div>
    <div class="reason">{m['reason']}</div>
  </div>
  {_fit_badge(m['fit_score'])}
</div>'''
            for m in item['matches']
        ) or '<p class="empty">판단 결과 없음</p>'
        researcher_cards.append(f'''<div class="fit-card card">
  <div class="card-body">
    <h3>{rid} {name_map.get(rid, '')}</h3>
    <p class="subtitle">이 연구원에게 적합한 MIT10 기술 직무 (적합도 순)</p>
    {rows}
  </div>
</div>''')

    body_html = f'''<ul class="nav nav-tabs justify-content-center mb-4" id="fit-tabs" role="tablist">
  <li class="nav-item" role="presentation">
    <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#by-tech" type="button">기술 기준</button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#by-researcher" type="button">인별 기준</button>
  </li>
</ul>
<div class="tab-content">
  <div class="tab-pane fade show active" id="by-tech">{''.join(tech_cards)}</div>
  <div class="tab-pane fade" id="by-researcher">{''.join(researcher_cards)}</div>
</div>'''

    return mmd.html_page(
        title='MIT10 ↔ 연구원 적합도 매칭',
        heading='2026 MIT 10대 기술 ↔ 연구원 적합도 매칭',
        subtitle='기술 기준 / 인별 기준 매칭 결과 (R&D Talent Matching Agent, 임베딩 1차 후보 + 사내 LLM 판단)',
        body_html=body_html,
        extra_style=_EXTRA_STYLE,
    )


if __name__ == '__main__':
    process()
