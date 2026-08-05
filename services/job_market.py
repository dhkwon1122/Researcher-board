"""
"JOB Market" 탭 핵심 로직 — 과제가 종료된다고 가정했을 때, 그 과제원들이
보유 전문성 기준으로 어떤 다른 과제에 재배치될 수 있는지 추천한다.

흐름:
  1) 종료 예정 과제(과제 단위) 또는 연구원 1명(개인별 검색)을 고른다.
     과제 단위면 jd_reconciliation.get_project_members()로 실제 배정 인원을
     가져오고(과제 직무/대상자 검증과 동일한 org_code 정규화 기준 재사용),
     researcher_profile_export.person_base_table()로 명단(사번/성명/부서/과제/
     CL·년차/학력·전공/나이)을 만든다.
  2) 후보 과제 풀 = project_confl_address.csv에 등록된 전체 과제 중 본인이
     지금 속한 과제(자동 제외)와 사용자가 지정한 제외 부서/과제를 뺀 나머지
     (사용자 확정: 제외 부서를 고르면 그 부서의 모든 과제가, 제외 과제를
     고르면 그 과제 하나만 빠짐 — 둘 다 지정 가능).
  3) 각 후보 과제에 대해 서로 독립적인 두 근거로 유사도를 각각 계산한다
     (사용자 확정: 둘 다 보여주되 구분 표기, 데이터 없는 쪽만 개별 제외):
       A) 과제 분석 기반 — project_expertise_analysis.json(컨플루언스 요약,
          process_project_expertise.py)의 텍스트를 임베딩해 이 사람의
          전문성 프로필 임베딩과 비교.
       B) 과제원 전문성 기반 — 그 과제에 현재 배정된 사람들의 보유 전문성
          프로필을 각각 임베딩해, 이 사람과 가장 가까운 한 명(대표값)과
          비교.
     A/B 둘 다 없는 과제는 후보에서 제외한다(비교할 근거가 아예 없으므로).
  4) A/B 중 더 높은 점수로 상위 후보를 추려(임베딩, 결정적) LLM에게 넘기고,
     LLM이 최종 0~3개만 추리며 사유를 쓴다(구조화 출력 강제 — 순위 자체는
     이미 Python이 계산해 둔 후보 중에서만 고르게 해 할루시네이션 방지).
  5) 개인별 검색도 같은 recommend_for_researcher()를 그대로 재사용한다
     (본인이 현재 속한 과제는 항상 자동 제외 — 사용자 확정).

PII: LLM 프롬프트에는 researcher_id/이름을 절대 포함하지 않는다(이 프로젝트
전체 원칙) — 대상자 본인도, B 근거로 쓰는 과제원 대표 인물도 프로필 텍스트만
전달한다.

Source:
  data/processed/project_confl_address.csv     (후보 과제 전체 목록 — dep_name/project_name)
  data/processed/researchers.csv               (과제 배정 인원 — org_code 기준)
  data/processed/education.csv                 (roster의 학력/전공)
  data/processed/project_expertise_analysis.json (근거 A — process_project_expertise.py)
  data/processed/연구원 보유 전문성 분석.json   (근거 B/대상자 프로필)
"""

import os
import re
import sys
from datetime import datetime

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import llm_client  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services import data_store  # noqa: E402
from services import jd_reconciliation as jd  # noqa: E402
from services import researcher_profile_export as export  # noqa: E402
from services.llm import LLMError  # noqa: E402

TOP_K_CANDIDATES = 8  # 임베딩으로 추려 LLM에 넘길 상위 후보 수(최종 0~3개는 LLM이 고름)
MAX_RECOMMENDATIONS = 3


# ─── 과제/부서 목록 (드롭다운, 결정적) ───────────────────────────────────────

def list_departments() -> list:
    """드롭다운용 부서(플랫폼/팀) 목록 — project_confl_address.csv의 dep_name."""
    projects_df = data_store.read_processed('project_confl_address')
    if projects_df.empty or 'dep_name' not in projects_df.columns:
        return []
    return sorted({str(v).strip() for v in projects_df['dep_name'] if str(v).strip()})


def list_projects(department=None) -> list:
    """드롭다운용 과제 목록 — project_confl_address.csv의 project_name.
    department가 있으면 그 dep_name(문자열 1개 또는 복수 선택 시 리스트)인
    과제만."""
    projects_df = data_store.read_processed('project_confl_address')
    if projects_df.empty or 'project_name' not in projects_df.columns:
        return []
    if department:
        depts = {department.strip()} if isinstance(department, str) else {str(d).strip() for d in department}
        projects_df = projects_df[projects_df['dep_name'].astype(str).str.strip().isin(depts)]
    return sorted({str(v).strip() for v in projects_df['project_name'] if str(v).strip()})


# ─── 과제원 명단(roster) — researcher_profile_export의 표시용 컬럼 재사용 ─────

def build_roster(researcher_ids: list) -> list:
    """researcher_id 목록으로 명단(사번/성명/부서/과제/CL·년차/학력·전공/나이)을
    만든다. researcher_profile_export.person_base_table()이 이미 이 7개
    컬럼(및 정확히 같은 "CL/년차"·"학력/전공" 표기)을 계산해 두고 있어 그대로
    재사용한다."""
    base = export.person_base_table(researcher_ids)
    keys = ['researcher_id', 'name', 'department', 'org_code', 'position_year', 'degree_major', 'age']
    return [dict(zip(keys, base.get(rid, [rid, '-', '-', '-', '-', '-', '-']))) for rid in researcher_ids]


# ─── 후보 과제 풀 + 근거 A/B 임베딩 준비 ──────────────────────────────────────

def _dedup_candidate_rows(projects_df) -> list:
    """project_confl_address.csv를 정규화된 project_name(=org_code) 기준으로
    묶어 대표 행 하나씩만 남긴다 — org_code/project_name 표기 형식이 달라도
    (대괄호 태그/띄어쓰기) 같은 과제를 서로 다른 후보로 중복 추천하지 않기
    위함(get_project_members()가 쓰는 것과 동일한 fit.normalize_org_code() 기준)."""
    seen = {}
    for _, row in projects_df.iterrows():
        name = str(row.get('project_name') or '').strip()
        if not name:
            continue
        key = fit.normalize_org_code(name)
        if key not in seen:
            seen[key] = {'project_name': name, 'dep_name': str(row.get('dep_name') or '').strip(), 'norm': key}
    return list(seen.values())


def _expand_excluded_projects(excluded_departments: set, excluded_org_codes: set,
                               all_rows: list) -> set:
    """제외 부서(dep_name)를 그 부서의 모든 과제로 펼치고, 제외 과제(project_name)와
    합쳐 정규화된 제외 집합을 만든다."""
    excluded_norm = {fit.normalize_org_code(p) for p in excluded_org_codes}
    if excluded_departments:
        for row in all_rows:
            if row['dep_name'] in excluded_departments:
                excluded_norm.add(row['norm'])
    return excluded_norm


def _build_candidate_pool(excluded_norm: set, expertise_profiles: dict) -> dict:
    """후보 과제별로 근거 A(과제 분석 텍스트)/B(현재 배정 인력 프로필 목록)를
    준비한다. 임베딩은 fit.cached_embed()로 한꺼번에 계산해(텍스트 해시 캐시
    재사용) 후보 수·인원 수가 늘어도 반복 호출을 피한다.

    반환: {project_name(대표 표기): {'dep_name', 'a_text', 'a_embedding'(or None),
                                      'b_members': [(embedding, profile_text), ...]}}
    A/B 둘 다 없는 과제는 이 dict에 아예 포함하지 않는다(비교 근거 없음)."""
    projects_df = data_store.read_processed('project_confl_address')
    if projects_df.empty:
        return {}
    all_rows = _dedup_candidate_rows(projects_df)
    candidates = [row for row in all_rows if row['norm'] not in excluded_norm]
    if not candidates:
        return {}

    # 근거 A 텍스트 준비 (없으면 빈 문자열 — 임베딩 대상에서 제외)
    a_texts_by_project = {}
    for row in candidates:
        entry = jd.read_confluence_summary(row['project_name'])
        text = jd.confluence_context_text(entry)
        if text:
            a_texts_by_project[row['project_name']] = text

    # 근거 B: 후보별 현재 배정 인력의 전문성 프로필 텍스트 (있는 사람만)
    b_texts_by_project = {}
    for row in candidates:
        members = jd.get_project_members(row['project_name'])
        texts = []
        for m in members:
            profile = expertise_profiles.get(m['researcher_id'])
            if profile:
                texts.append(fit.researcher_profile_text(profile))
        if texts:
            b_texts_by_project[row['project_name']] = texts

    # 임베딩은 한 번에 계산(캐시 재사용) — 실패하면 그대로 위로 전파(호출부가 처리)
    all_a_texts = list(a_texts_by_project.values())
    all_b_texts = [t for texts in b_texts_by_project.values() for t in texts]
    a_embeds = fit.cached_embed(all_a_texts) if all_a_texts else None
    b_embeds = fit.cached_embed(all_b_texts) if all_b_texts else None

    a_embed_by_project = {}
    if a_embeds is not None:
        for project_name, vec in zip(a_texts_by_project.keys(), a_embeds):
            a_embed_by_project[project_name] = vec

    b_embed_by_project = {}
    if b_embeds is not None:
        it = iter(b_embeds)
        for project_name, texts in b_texts_by_project.items():
            b_embed_by_project[project_name] = [(next(it), t) for t in texts]

    pool = {}
    for row in candidates:
        project_name = row['project_name']
        a_embedding = a_embed_by_project.get(project_name)
        b_members = b_embed_by_project.get(project_name) or []
        if a_embedding is None and not b_members:
            continue
        pool[project_name] = {
            'dep_name': row['dep_name'],
            'a_text': a_texts_by_project.get(project_name, ''),
            'a_embedding': a_embedding,
            'b_members': b_members,
        }
    return pool


def _cosine(a, b) -> float:
    import numpy as np
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


def _score_candidates(profile_embedding, candidate_pool: dict) -> list:
    """후보 과제별 A/B 점수를 계산해 결합 점수(둘 중 높은 쪽) 기준 내림차순
    정렬한 리스트로 반환한다."""
    scored = []
    for project_name, cand in candidate_pool.items():
        score_a = _cosine(profile_embedding, cand['a_embedding']) if cand['a_embedding'] is not None else None
        score_b, b_text = None, None
        if cand['b_members']:
            sims = [(_cosine(profile_embedding, emb), text) for emb, text in cand['b_members']]
            score_b, b_text = max(sims, key=lambda x: x[0])
        combined = max(v for v in (score_a, score_b) if v is not None)
        scored.append({
            'project_name': project_name, 'dep_name': cand['dep_name'],
            'score_a': score_a, 'score_b': score_b,
            'a_text': cand['a_text'], 'b_text': b_text or '',
            'combined': combined,
        })
    scored.sort(key=lambda x: -x['combined'])
    return scored


# ─── LLM 최종 판정 (임베딩 상위 후보 중 0~3개만, 사유 포함) ──────────────────

_RECOMMEND_SYSTEM_PROMPT = """# Role
당신은 R&D 인력 재배치를 돕는 "과제 매칭 도우미"입니다. 과제가 종료되어
다른 과제로 옮겨야 하는 연구원 한 명의 보유 전문성과, 여러 후보 과제의
정보를 비교해 실제로 참여 가능성이 높은 과제를 추립니다.

# Goal
주어진 연구원의 전문성 프로필과, 각 후보 과제에 대해 주어지는 근거(A: 과제
자체의 기술 분석 내용, B: 그 과제에 이미 배정된 인력 중 이 사람과 가장 가까운
인력의 전문성 프로필 — 후보마다 A/B 중 하나만 있을 수도, 둘 다 있을 수도
있습니다)를 비교해, 실제로 참여 가능성이 높은 과제를 최대 3개까지 고릅니다.

# Guidelines & Constraints
1. 반드시 입력으로 주어진 후보 과제 중에서만 선택하세요(새로 만들어내지 마세요).
2. 근거가 뚜렷한 순서대로 최대 3개까지만 고르세요. 뚜렷한 연관성이 없으면
   억지로 채우지 말고 빈 리스트를 반환하세요.
3. reason은 왜 이 과제가 맞는지 1~2문장으로 구체적으로 쓰세요. A/B 중 어떤
   근거를 주로 참고했는지 자연스럽게 드러나도록 쓰세요.
4. 반드시 아래 JSON 형식으로만 출력하세요.

# Output Format (JSON)
{"recommendations": [{"project_name": "후보 목록의 과제명 그대로", "reason": "1~2문장 사유"}]}
"""


def _candidate_block(item: dict) -> str:
    a = item['a_text'] or '(과제 분석 데이터 없음)'
    b = item['b_text'] or '(비교 가능한 배정 인력 없음)'
    return f"[{item['project_name']}] 소속: {item['dep_name']}\nA) 과제 분석 기반: {a}\nB) 유사 인력 기반: {b}"


def _judge_recommendations(profile_text: str, shortlist: list) -> list:
    """임베딩 상위 후보(shortlist)를 LLM에 보여주고 0~3개만 사유와 함께 고르게
    한다. 실패/파싱 오류 시 빈 리스트(추천 없음으로 안전하게 처리)."""
    if not shortlist:
        return []
    candidate_block = '\n\n'.join(_candidate_block(c) for c in shortlist)
    prompt = (
        f'[연구원 전문성 프로필]\n{profile_text}\n\n[후보 과제 목록]\n{candidate_block}\n\n'
        '위 연구원이 실제로 참여 가능성이 높은 과제를 최대 3개까지 골라주세요.'
    )
    raw = llm_client.call_llm(prompt, _RECOMMEND_SYSTEM_PROMPT, temperature=0.0, max_tokens=1200)
    if not raw:
        return []
    import json
    try:
        parsed = json.loads(llm_client.extract_json(raw))
    except json.JSONDecodeError:
        return []

    by_name = {c['project_name']: c for c in shortlist}
    results = []
    for r in (parsed.get('recommendations') or [])[:MAX_RECOMMENDATIONS]:
        name = str(r.get('project_name') or '').strip()
        cand = by_name.get(name)
        if not cand:
            continue  # 후보 목록에 없는 이름은 할루시네이션으로 간주하고 버림
        results.append({
            'project_name': name, 'dep_name': cand['dep_name'],
            'reason': str(r.get('reason') or '').strip(),
            'score_a': cand['score_a'], 'score_b': cand['score_b'],
        })
    return results


# ─── 전체 실행 ───────────────────────────────────────────────────────────────

def recommend_for_researcher(researcher_id: str, expertise_profiles: dict, candidate_pool: dict) -> dict:
    """한 사람에 대한 추천 결과. candidate_pool은 여러 사람에 걸쳐 재사용
    가능(과제 단위 검색이 배정 인원 전체를 순회할 때 매번 새로 만들지 않도록
    호출부가 미리 만들어 넘긴다)."""
    profile = expertise_profiles.get(researcher_id)
    if not profile:
        return {'recommendations': [], 'note': '전문성 분석 데이터가 없어 추천할 수 없습니다.'}
    if not candidate_pool:
        return {'recommendations': [], 'note': '비교 가능한 후보 과제가 없습니다.'}

    profile_text = fit.researcher_profile_text(profile)
    try:
        profile_embedding = fit.cached_embed([profile_text])[0]
    except LLMError as exc:
        return {'recommendations': [], 'note': f'임베딩 계산 실패: {exc}'}

    scored = _score_candidates(profile_embedding, candidate_pool)
    shortlist = scored[:TOP_K_CANDIDATES]
    recommendations = _judge_recommendations(profile_text, shortlist)
    return {'recommendations': recommendations, 'note': ''}


def _own_org_code(researcher_id: str, researchers_df) -> str:
    rows = researchers_df[researchers_df['researcher_id'] == researcher_id]
    if rows.empty:
        return ''
    return str(rows.iloc[0].get('org_code') or '').strip()


def run_project_search(project_names: list, excluded_departments: list, excluded_org_codes: list) -> dict:
    """'종료 예정 과제' 단위 검색 — 복수 선택 가능. 선택한 과제 전체의 배정
    인원(중복 인원은 한 번만)에 대해 추천을 반복하고, 선택한 과제들은 전부
    (본인이 속한 과제뿐 아니라 함께 종료되는 다른 선택 과제들도) 후보에서
    제외한다 — 같이 끝나는 과제로 서로 재추천되지 않도록."""
    project_names = [p for p in (project_names or []) if p]
    if not project_names:
        return {'error': '종료 예정 과제를 선택해주세요.'}

    researcher_ids = []
    seen_rid = set()
    for project_name in project_names:
        for m in jd.get_project_members(project_name):
            if m['researcher_id'] not in seen_rid:
                seen_rid.add(m['researcher_id'])
                researcher_ids.append(m['researcher_id'])
    if not researcher_ids:
        return {'error': f'선택한 과제({", ".join(project_names)})에 배정된 인원이 없습니다.'}
    roster = build_roster(researcher_ids)

    projects_df = data_store.read_processed('project_confl_address')
    all_rows = _dedup_candidate_rows(projects_df) if not projects_df.empty else []
    excluded_norm = _expand_excluded_projects(set(excluded_departments), set(excluded_org_codes), all_rows)
    excluded_norm |= {fit.normalize_org_code(p) for p in project_names}  # 종료 예정 과제 전체는 항상 제외

    expertise_profiles = data_store.read_expertise_profiles()
    try:
        candidate_pool = _build_candidate_pool(excluded_norm, expertise_profiles)
    except LLMError as exc:
        return {'error': f'후보 과제 임베딩 계산 실패: {exc}'}

    workers = llm_client.max_concurrency()
    tasks = [(lambda rid=rid: recommend_for_researcher(rid, expertise_profiles, candidate_pool))
              for rid in researcher_ids]
    task_results = llm_client.run_concurrent(tasks, max_workers=workers) if tasks else []

    results = {}
    for rid, (result, error) in zip(researcher_ids, task_results):
        results[rid] = result if error is None and result else {'recommendations': [], 'note': f'처리 중 오류: {error}'}

    return {
        'mode': 'project', 'project_names': project_names,
        'run_at': datetime.now().isoformat(timespec='seconds'),
        'roster': roster, 'results': results,
        'candidates_considered': len(candidate_pool),
    }


def _resolve_researcher_query(query: str, researchers_df) -> list:
    """이름 또는 사번으로 researcher_id 후보를 찾는다(동명이인이면 복수 반환)."""
    if researchers_df.empty:
        return []
    q = str(query or '').strip()
    if not q:
        return []
    qz = q.zfill(8) if q.isdigit() else q
    by_id = researchers_df[researchers_df['researcher_id'] == qz]
    if not by_id.empty:
        return by_id['researcher_id'].tolist()
    by_name = researchers_df[researchers_df['name'].astype(str).str.strip() == q]
    if not by_name.empty:
        return by_name['researcher_id'].tolist()
    contains = researchers_df[researchers_df['name'].astype(str).str.contains(re.escape(q), na=False)]
    return contains['researcher_id'].tolist()


def run_individual_search(researcher_query: str, excluded_departments: list, excluded_org_codes: list) -> dict:
    """개인별 검색 — 이름/사번 1건으로 후보 과제를 추천한다. 본인이 현재
    속한 과제는 항상 자동으로 제외한다."""
    researchers_df = data_store.read_processed('researchers')
    candidates = _resolve_researcher_query(researcher_query, researchers_df)
    if not candidates:
        return {'error': f'"{researcher_query}"에 해당하는 연구원을 찾지 못했습니다.'}
    if len(candidates) > 1:
        return {'error': f'"{researcher_query}"에 해당하는 연구원이 {len(candidates)}명입니다. 사번으로 다시 검색해주세요.'}

    researcher_id = candidates[0]
    roster = build_roster([researcher_id])

    projects_df = data_store.read_processed('project_confl_address')
    all_rows = _dedup_candidate_rows(projects_df) if not projects_df.empty else []
    excluded_norm = _expand_excluded_projects(set(excluded_departments), set(excluded_org_codes), all_rows)
    own_org_code = _own_org_code(researcher_id, researchers_df)
    if own_org_code:
        excluded_norm.add(fit.normalize_org_code(own_org_code))

    expertise_profiles = data_store.read_expertise_profiles()
    try:
        candidate_pool = _build_candidate_pool(excluded_norm, expertise_profiles)
    except LLMError as exc:
        return {'error': f'후보 과제 임베딩 계산 실패: {exc}'}

    result = recommend_for_researcher(researcher_id, expertise_profiles, candidate_pool)
    return {
        'mode': 'individual', 'researcher_id': researcher_id,
        'run_at': datetime.now().isoformat(timespec='seconds'),
        'roster': roster, 'results': {researcher_id: result},
        'candidates_considered': len(candidate_pool),
    }
