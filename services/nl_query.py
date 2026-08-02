"""
"보유 전문성" 탭 자연어 질문 기능 — 핵심 로직

자연어 질문(예: "로봇 제어 전문가 찾아줘", "이 과제에 적합한 사람 찾아줘",
"이 연구원이 현재 과제 말고 어떤 과제에 적합해?")을 아래 2단계로 처리한다.

  1) 질의 변환(사내 LLM, 구조화 출력 강제) — 자유 텍스트 질문을 아래 스키마의
     JSON으로 바꾼다. LLM은 "답을 만드는" 역할이 아니라 "질문을 분류하고
     검색에 필요한 핵심 개체(전문성 키워드/과제명/연구원명 등)만 뽑아내는"
     역할만 한다 — 실제 판단/랭킹은 이미 배치로 계산해 둔 산출물에서 그대로
     조회한다(자유 생성이 아니므로 환각 위험이 낮음).
  2) 조회(intent별로 이미 있는 배치 산출물을 필터/조회, 필요할 때만 실시간
     임베딩 매칭으로 보완) — 대부분 새 LLM 호출 없이 응답 가능.

지원 intent(사용자 표현은 매우 다양할 수 있으므로, 아래 3가지로 분류가 안 되는
질문은 전부 "unsupported"로 안내만 반환하고 추측 답변을 만들지 않는다):
  - find_researchers_by_expertise : 특정 전문성/키워드 보유 연구원 찾기
  - find_researchers_for_project  : 특정 과제(등록된 과제 또는 새 과제 설명)에
    적합한 연구원 찾기
  - find_projects_for_researcher  : 특정 연구원에게 적합한 사내 과제 찾기
    (현재 수행 중인 과제는 기본적으로 제외)

Source:
  data/processed/연구원 보유 전문성 분석.json      (services.data_store.read_expertise_profiles)
  data/processed/researchers.csv                    (이름/부서)
  data/processed/tasks.csv                          (연구원의 현재 수행 과제 판단)
  data/processed/project_fit_by_project.json/project_fit_by_researcher.json
    (process_project_researcher_fit.py가 이미 계산해 둔 배치 매칭 결과)
  data/processed/strength_taxonomy.json             (build_strength_taxonomy.py 2단계
    확정 표준 목록 — 있으면 동의어 확장에 사용, 없으면 원문 그대로만 매칭)
  data/processed/embedding_cache.json               (BGE-M3 임베딩 캐시, researcher_fit.cached_embed 재사용)

동시성: 이 모듈의 실시간 LLM 호출(질의 변환)은 llm_config.LLM2_QUERY_MAX_WAIT_SECONDS
(기본 15초) 안에 동시 호출 슬롯을 못 얻으면 빈 응답으로 빠르게 실패한다 —
배치 파이프라인이 슬롯을 다 쓰고 있어도 사용자가 화면에서 무한정 기다리지
않게 하기 위함(llm_client.call_llm의 max_wait 파라미터, 세마포어는 배치와
공유 — 전체 동시 호출 수는 항상 LLM2_MAX_CONCURRENT를 넘지 않는다).
"""

import json
import os
import re
import sys

import pandas as pd

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import llm_client  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402
from services import data_store  # noqa: E402

try:
    import llm_config as _llm_cfg
except ModuleNotFoundError:
    _llm_cfg = None

MAX_TOP_K = 20
DEFAULT_TOP_K = 5
_EMBEDDING_MATCH_THRESHOLD = 0.75
_FIT_RANK = {'상': 0, '중': 1, '하': 2}

_KNOWN_INTENTS = {
    'find_researchers_by_expertise',
    'find_researchers_for_project',
    'find_projects_for_researcher',
}

QUERY_SYSTEM_PROMPT = """# Role
당신은 사내 연구원 전문성/과제 매칭 데이터베이스에 대한 자연어 질문을 구조화된
검색 조건으로 바꾸는 "R&D Query Router"입니다. 직접 답을 만들지 않습니다 —
질문을 분류하고 검색에 필요한 핵심 개체만 뽑아냅니다.

# 지원하는 질문 유형(intent) — 반드시 이 4가지 중 하나로만 분류하세요
1. find_researchers_by_expertise : 특정 전문성/기술/키워드를 가진 연구원을 찾는 질문
   예) "로봇 제어 전문가 찾아줘", "센서 데이터 처리 할 줄 아는 사람 있어?"
2. find_researchers_for_project : 특정 과제(사내에 이미 등록된 과제명, 또는
   새로 설명하는 과제)에 적합한 연구원을 찾는 질문
   예) "차세대로봇제어 과제에 적합한 사람 찾아줘", "자율주행 센서 퓨전 하는 신규 과제에 맞는 사람은?"
3. find_projects_for_researcher : 특정 연구원에게 어떤 과제가 적합한지 찾는 질문.
   "현재 하고 있는 과제 말고", "지금 과제 제외하고" 같은 표현이 있으면
   exclude_current_project=true, 명시가 없어도 기본값은 true로 두세요.
   예) "정재원 연구원은 지금 과제 말고 어떤 과제에 적합해?"
4. unsupported : 위 3가지에 해당하지 않는 모든 질문(잡담, 개인정보 요청,
   이 시스템이 다루지 않는 질문 등) — 억지로 끼워 맞추지 말고 이 값으로
   분류하고 reason_if_unsupported에 짧게 이유를 적으세요.

# Output Format (JSON만 출력하고 그 외 텍스트는 절대 출력하지 마세요)
{
  "intent": "find_researchers_by_expertise" | "find_researchers_for_project" | "find_projects_for_researcher" | "unsupported",
  "expertise_terms": ["..."],
  "project_name": "",
  "project_description": "",
  "researcher_query": "",
  "exclude_current_project": true,
  "department_filter": "",
  "top_k": 5,
  "reason_if_unsupported": ""
}
※ 해당 intent와 무관한 필드는 빈 문자열/빈 리스트로 두세요.
※ department_filter/top_k는 질문에 명시적으로 언급된 경우에만 채우고, 그 외에는
  기본값(department_filter="", top_k=5)을 유지하세요.
"""


def _norm(s: str) -> str:
    return re.sub(r'\s+', '', str(s or '')).strip().lower()


def _substring_match(term: str, candidates: set) -> set:
    nt = _norm(term)
    if not nt:
        return set()
    return {c for c in candidates if nt in _norm(c) or _norm(c) in nt}


def _taxonomy_lookup(term: str, entries: list) -> set | None:
    """entries: [{'standard_name','synonyms':[...]}, ...]. 매치되는 entry가
    있으면 그 entry의 동의어 집합(=원문 strength_fields/keywords 값 후보)을
    반환, 없으면 None."""
    for entry in entries or []:
        pool = {entry.get('standard_name', '')} | set(entry.get('synonyms') or [])
        if _substring_match(term, pool):
            return set(entry.get('synonyms') or [entry.get('standard_name', '')])
    return None


def _embedding_match(term: str, raw_pool: set, threshold: float = _EMBEDDING_MATCH_THRESHOLD, top_n: int = 3) -> set:
    if not raw_pool:
        return set()
    pool_list = sorted(raw_pool)
    vectors = fit.cached_embed([term] + pool_list)
    term_vec, pool_vecs = vectors[:1], vectors[1:]
    sims = fit.cosine_sim_matrix(term_vec, pool_vecs)[0]
    ranked = sorted(range(len(pool_list)), key=lambda i: -sims[i])[:top_n]
    return {pool_list[i] for i in ranked if sims[i] >= threshold}


def expand_term(term: str, taxonomy: dict, raw_pool: set) -> tuple:
    """질의어 term에 대응하는 strength_fields/keywords 원문 값 집합을 찾는다.
    표준 목록(taxonomy) 매칭 → 원문 직접 substring 매칭 → (그래도 못 찾으면)
    BGE-M3 임베딩 유사도 매칭 순으로 시도한다. 반환: (매칭된 원문 값 집합,
    어떤 방식으로 찾았는지 — 'taxonomy'|'substring'|'embedding'|'none')."""
    hit = (
        _taxonomy_lookup(term, (taxonomy or {}).get('fields'))
        or _taxonomy_lookup(term, (taxonomy or {}).get('keywords'))
    )
    if hit:
        return hit, 'taxonomy'

    direct = _substring_match(term, raw_pool)
    if direct:
        return direct, 'substring'

    try:
        matched = _embedding_match(term, raw_pool)
    except LLMError:
        return set(), 'none'
    if matched:
        return matched, 'embedding'
    return set(), 'none'


def find_researchers_by_expertise(terms: list, department_filter: str = '', top_k: int = DEFAULT_TOP_K) -> dict:
    terms = [str(t).strip() for t in (terms or []) if str(t).strip()]
    if not terms:
        return {'intent': 'find_researchers_by_expertise', 'items': [],
                'note': '질문에서 찾을 전문성 키워드를 확인하지 못했습니다.'}

    profiles = data_store.read_expertise_profiles()
    if not profiles:
        return {'intent': 'find_researchers_by_expertise', 'items': [],
                'note': '연구원 보유 전문성 분석.json이 없습니다(process_researcher_expertise.py 먼저 실행).'}

    researchers_df = data_store.read_processed('researchers')
    name_map, dept_map = {}, {}
    if not researchers_df.empty:
        indexed = researchers_df.set_index('researcher_id')
        name_map = indexed['name'].to_dict()
        dept_map = indexed['department'].to_dict()

    taxonomy = data_store.read_strength_taxonomy()
    raw_pool: set = set()
    for p in profiles.values():
        raw_pool.update(p.get('strength_fields') or [])
        raw_pool.update(p.get('strength_keywords') or [])

    notes = []
    expanded_terms = []
    for term in terms:
        matched_values, method = expand_term(term, taxonomy, raw_pool)
        expanded_terms.append(matched_values)
        if method == 'none':
            notes.append(f'"{term}"에 해당하는 표기를 찾지 못했습니다.')
        elif method == 'embedding':
            notes.append(f'"{term}"는 정확히 일치하는 표기가 없어 의미가 비슷한 표기로 찾았습니다.')

    dept_filter = (department_filter or '').strip().lower()
    scored = []
    for rid, profile in profiles.items():
        if dept_filter and dept_filter not in str(dept_map.get(rid, '')).lower():
            continue
        rvals = set(profile.get('strength_fields') or []) | set(profile.get('strength_keywords') or [])
        hit_count = sum(1 for mv in expanded_terms if mv & rvals)
        if hit_count > 0:
            scored.append((hit_count, rid))
    scored.sort(key=lambda x: (-x[0], x[1]))

    top_k = min(top_k or DEFAULT_TOP_K, MAX_TOP_K)
    items = [
        {
            'researcher_id': rid,
            'name': name_map.get(rid, rid),
            'department': dept_map.get(rid, ''),
            'strength_fields': profiles[rid].get('strength_fields') or [],
            'strength_keywords': profiles[rid].get('strength_keywords') or [],
            'matched_term_count': hit_count,
        }
        for hit_count, rid in scored[:top_k]
    ]
    return {
        'intent': 'find_researchers_by_expertise',
        'items': items,
        'total_matched': len(scored),
        'note': ' '.join(notes),
    }


def _fit_rank_key(m: dict) -> int:
    return _FIT_RANK.get(m.get('fit_score', ''), 3)


def _match_project_entries(project_query: str, by_project: list) -> list:
    nq = _norm(project_query)
    if not nq:
        return []
    exact = [e for e in by_project if _norm(e.get('project_name', '')) == nq]
    if exact:
        return exact
    return [e for e in by_project if nq in _norm(e.get('project_name', '')) or _norm(e.get('project_name', '')) in nq]


def find_researchers_for_project(project_name: str = '', project_description: str = '',
                                  top_k: int = DEFAULT_TOP_K) -> dict:
    top_k = min(top_k or DEFAULT_TOP_K, MAX_TOP_K)
    by_project = data_store.read_project_fit_by_project()
    query = (project_name or '').strip()

    if query and by_project:
        matches = _match_project_entries(query, by_project)
        if matches:
            researchers_df = data_store.read_processed('researchers')
            name_map = researchers_df.set_index('researcher_id')['name'].to_dict() if not researchers_df.empty else {}
            items, seen = [], set()
            for entry in matches:
                rankings = sorted(entry.get('rankings') or [], key=_fit_rank_key)[:top_k]
                for r in rankings:
                    key = (entry.get('project_name', ''), entry.get('job_title', ''), r.get('researcher_id', ''))
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append({
                        'project_name': entry.get('project_name', ''),
                        'job_title': entry.get('job_title', ''),
                        'researcher_id': r.get('researcher_id', ''),
                        'name': name_map.get(r.get('researcher_id', ''), r.get('researcher_id', '')),
                        'fit_score': r.get('fit_score', ''),
                        'reason': r.get('reason', ''),
                    })
            return {
                'intent': 'find_researchers_for_project',
                'items': items,
                'source': 'batch',
                'note': '',
            }

    # 등록된 과제에서 못 찾았고 설명이 있으면, 임베딩만으로 1차 후보를 실시간 계산한다
    # (사내 LLM 정성 판정은 배치 process_project_researcher_fit.py만 수행하므로,
    # 이 경로의 결과는 "1차 후보"일 뿐 확정 배치 결과와 신뢰도가 다르다).
    description = (project_description or query).strip()
    if not description:
        return {'intent': 'find_researchers_for_project', 'items': [],
                'note': '과제명이나 과제 설명을 확인하지 못했습니다.'}

    profiles = data_store.read_expertise_profiles()
    if not profiles:
        return {'intent': 'find_researchers_for_project', 'items': [],
                'note': '연구원 보유 전문성 분석.json이 없어 매칭할 수 없습니다.'}

    researcher_ids = list(profiles.keys())
    researcher_texts = [fit.researcher_profile_text(profiles[rid]) for rid in researcher_ids]
    try:
        vectors = fit.cached_embed([description] + researcher_texts)
    except LLMError as exc:
        return {'intent': 'find_researchers_for_project', 'items': [], 'note': f'임베딩 서버 오류: {exc}'}

    desc_vec, researcher_vecs = vectors[:1], vectors[1:]
    sims = fit.cosine_sim_matrix(desc_vec, researcher_vecs)[0]
    ranked_idx = sorted(range(len(researcher_ids)), key=lambda i: -sims[i])[:top_k]

    researchers_df = data_store.read_processed('researchers')
    name_map = researchers_df.set_index('researcher_id')['name'].to_dict() if not researchers_df.empty else {}
    items = [
        {
            'project_name': description[:40], 'job_title': '',
            'researcher_id': researcher_ids[i], 'name': name_map.get(researcher_ids[i], researcher_ids[i]),
            'fit_score': '', 'reason': '', 'score': round(float(sims[i]), 4),
        }
        for i in ranked_idx
    ]
    return {
        'intent': 'find_researchers_for_project',
        'items': items,
        'source': 'embedding_only',
        'note': ('등록된 과제 목록에 없어 임베딩 유사도로 1차 후보만 계산했습니다 — '
                 '사내 LLM 정성 판정(근거·적합도 상/중/하)은 아직 거치지 않았습니다.'),
    }


def _resolve_researcher(query: str, researchers_df: pd.DataFrame) -> list:
    """이름 또는 사번으로 researcher_id 후보를 찾는다(동명이인이면 복수 반환)."""
    if researchers_df.empty:
        return []
    q = str(query).strip()
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


def _current_project_names(researcher_id: str, tasks_df: pd.DataFrame) -> set:
    """이 연구원이 '현재' 수행 중인 과제명 집합. end_date가 비어 있으면
    진행중(components/timeline_data.py의 기존 관례와 동일), 있으면 오늘
    이후인 경우도 진행중으로 취급한다."""
    if tasks_df.empty:
        return set()
    rows = tasks_df[tasks_df['researcher_id'] == researcher_id]
    if rows.empty:
        return set()
    today = pd.Timestamp.now().normalize()
    current = set()
    for _, row in rows.iterrows():
        end_raw = str(row.get('end_date', '') or '').strip()
        if not end_raw:
            current.add(str(row.get('task_name', '')).strip())
            continue
        end_ts = pd.to_datetime(end_raw, errors='coerce')
        if pd.isna(end_ts) or end_ts >= today:
            current.add(str(row.get('task_name', '')).strip())
    return current


def find_projects_for_researcher(researcher_query: str, exclude_current: bool = True,
                                  top_k: int = DEFAULT_TOP_K) -> dict:
    top_k = min(top_k or DEFAULT_TOP_K, MAX_TOP_K)
    researchers_df = data_store.read_processed('researchers')
    candidates = _resolve_researcher(researcher_query, researchers_df)
    if not candidates:
        return {'intent': 'find_projects_for_researcher', 'items': [],
                'note': f'"{researcher_query}"에 해당하는 연구원을 찾지 못했습니다.'}
    if len(candidates) > 1:
        name_map = researchers_df.set_index('researcher_id')['name'].to_dict()
        cand_desc = ', '.join(f'{name_map.get(rid, rid)}({rid})' for rid in candidates[:10])
        return {'intent': 'find_projects_for_researcher', 'items': [],
                'note': f'동명이인 등으로 {len(candidates)}명이 검색됩니다: {cand_desc}. 사번으로 다시 질문해주세요.'}

    rid = candidates[0]
    by_researcher = data_store.read_project_fit_by_researcher()
    entry = by_researcher.get(rid)
    if not entry:
        return {'intent': 'find_projects_for_researcher', 'items': [],
                'note': '이 연구원에 대한 과제 적합도 매칭 데이터가 없습니다'
                        '(process_project_researcher_fit.py 실행 필요).'}

    matches = list(entry.get('matches') or [])
    excluded_note = ''
    if exclude_current:
        tasks_df = data_store.read_processed('tasks')
        current_names = _current_project_names(rid, tasks_df)
        before = len(matches)
        matches = [m for m in matches if m.get('project_name', '') not in current_names]
        if current_names and before != len(matches):
            excluded_note = f'현재 수행 중인 과제({", ".join(sorted(current_names))})는 제외했습니다.'

    matches.sort(key=_fit_rank_key)
    name_map = researchers_df.set_index('researcher_id')['name'].to_dict()
    items = [
        {
            'researcher_id': rid, 'name': name_map.get(rid, rid),
            'project_name': m.get('project_name', ''), 'job_title': m.get('job_title', ''),
            'dep_name': m.get('dep_name', ''), 'fit_score': m.get('fit_score', ''), 'reason': m.get('reason', ''),
        }
        for m in matches[:top_k]
    ]
    return {'intent': 'find_projects_for_researcher', 'items': items, 'note': excluded_note}


def parse_question(question: str) -> dict:
    """자연어 질문을 구조화된 쿼리 dict로 변환(사내 LLM 1회 호출). 실패
    유형별로 다른 intent('error'|'unsupported')를 돌려줘 호출부가 구분해서
    안내할 수 있게 한다."""
    question = (question or '').strip()
    if not question:
        return {'intent': 'unsupported', 'reason_if_unsupported': '빈 질문입니다.'}

    max_wait = getattr(_llm_cfg, 'LLM2_QUERY_MAX_WAIT_SECONDS', 15) if _llm_cfg else 15
    raw = llm_client.call_llm(question, QUERY_SYSTEM_PROMPT, temperature=0.0, max_tokens=400, max_wait=max_wait)
    if not raw:
        return {'intent': 'error',
                'message': '지금 요청이 많아 응답을 만들지 못했습니다. 잠시 후 다시 시도해주세요.'}

    try:
        parsed = json.loads(llm_client.extract_json(raw))
    except json.JSONDecodeError:
        return {'intent': 'error', 'message': '질문을 이해하지 못했습니다. 다르게 표현해 다시 질문해주세요.'}

    intent = parsed.get('intent')
    if intent not in _KNOWN_INTENTS:
        return {'intent': 'unsupported', 'reason_if_unsupported': parsed.get('reason_if_unsupported', '')}

    try:
        top_k = int(parsed.get('top_k') or DEFAULT_TOP_K)
    except (TypeError, ValueError):
        top_k = DEFAULT_TOP_K

    return {
        'intent': intent,
        'expertise_terms': parsed.get('expertise_terms') or [],
        'project_name': parsed.get('project_name') or '',
        'project_description': parsed.get('project_description') or '',
        'researcher_query': parsed.get('researcher_query') or '',
        'exclude_current_project': bool(parsed.get('exclude_current_project', True)),
        'department_filter': parsed.get('department_filter') or '',
        'top_k': top_k,
    }


def execute_query(parsed: dict) -> dict:
    """parse_question()의 결과를 실제 데이터 조회로 실행한다."""
    intent = parsed.get('intent')
    if intent == 'error':
        return {'intent': 'error', 'items': [], 'note': parsed.get('message', '알 수 없는 오류가 발생했습니다.')}

    if intent == 'unsupported':
        reason = parsed.get('reason_if_unsupported') or ''
        note = '죄송합니다, 이 질문에는 아직 답변할 수 없습니다.'
        if reason:
            note += f' ({reason})'
        note += (' "특정 전문성 보유자 찾기", "과제에 적합한 사람 찾기", '
                 '"연구원에게 맞는 과제 찾기" 형태로 질문해 주세요.')
        return {'intent': 'unsupported', 'items': [], 'note': note}

    top_k = parsed.get('top_k') or DEFAULT_TOP_K
    if intent == 'find_researchers_by_expertise':
        return find_researchers_by_expertise(
            parsed.get('expertise_terms') or [], parsed.get('department_filter', ''), top_k)
    if intent == 'find_researchers_for_project':
        return find_researchers_for_project(
            parsed.get('project_name', ''), parsed.get('project_description', ''), top_k)
    if intent == 'find_projects_for_researcher':
        return find_projects_for_researcher(
            parsed.get('researcher_query', ''), parsed.get('exclude_current_project', True), top_k)

    return {'intent': 'unsupported', 'items': [], 'note': '알 수 없는 질문 유형입니다.'}


def answer_question(question: str) -> dict:
    """질문 → (질의 변환 → 조회) 전체 파이프라인의 단일 진입점."""
    return execute_query(parse_question(question))
