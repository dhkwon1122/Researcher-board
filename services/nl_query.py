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

지원 intent(사용자 표현은 매우 다양할 수 있으므로, 아래로 분류가 안 되는
질문은 "unsupported"로 안내만 반환하고 추측 답변을 만들지 않는다):
  - find_researchers_by_expertise : 이미 요약된 강점 분야/키워드 태그로 연구원 찾기
  - find_similar_researchers      : 특정 연구원과 전문성이 유사한 다른 연구원
    찾기(연구원↔연구원 유사도, pipeline/process_researcher_similarity.py가
    이미 배치로 계산해 둔 결과를 그대로 조회 — LLM 근거 판정까지 끝난 값)
  - open_data_query : 위 2가지가 다루는 "이미 계산된 결과"로는 답할 수 없는,
    원천 데이터(학력/전공, 과제 수행 이력, 논문/특허, 평가/인사 이력 등)의
    특정 항목을 근거로 찾는 개방형 질문. 예) "물리학 전공한 사람 찾아줘",
    "양자컴 과제 수행 중인 연구원 보여줘", "특허 등록 3건 이상인 연구원".
    services/open_data_query.py가 자연어 → SQL로 그 자리에서 조회한다.

(예전에는 find_researchers_for_project/find_projects_for_researcher 2개
intent가 더 있었지만, 그 기반이 되던 과제↔연구원 매칭 기능 자체가 제거되면서
함께 삭제됐다 — data/processed/CLAUDE.md 참고.)

Source:
  data/processed/연구원 보유 전문성 분석.json      (services.data_store.read_expertise_profiles)
  data/processed/researchers.csv                    (이름/부서)
  data/processed/researcher_similarity.json         (process_researcher_similarity.py가
    이미 계산해 둔 연구원↔연구원 유사도 + LLM 근거 판정, services.data_store.read_similar_researchers)
  data/processed/strength_taxonomy.json             (build_strength_taxonomy.py 2단계
    확정 표준 목록 — 있으면 동의어 확장에 사용, 없으면 원문 그대로만 매칭)
  data/processed/embedding_cache.json               (BGE-M3 임베딩 캐시, researcher_fit.cached_embed 재사용)
  data/processed/*.csv 전체                          (open_data_query intent, services.open_data_query 참고)

동시성: 이 모듈의 실시간 LLM 호출(질의 변환)은 llm_client.query_max_wait()
(환경변수 LLM2_QUERY_MAX_WAIT_SECONDS, 기본 15초) 안에 동시 호출 슬롯을 못
얻으면 빈 응답으로 빠르게 실패한다 —
배치 파이프라인이 슬롯을 다 쓰고 있어도 사용자가 화면에서 무한정 기다리지
않게 하기 위함(llm_client.call_llm의 max_wait 파라미터, 세마포어는 배치와
공유 — 전체 동시 호출 수는 항상 LLM2_MAX_CONCURRENT를 넘지 않는다).
"""

import json
import os
import re
import sys
from datetime import datetime

import pandas as pd

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import llm_client  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402
from services import auth  # noqa: E402
from services import data_labels  # noqa: E402
from services import data_store  # noqa: E402
from services import open_data_query  # noqa: E402
from services import query_settings  # noqa: E402
from services.evaluations import evaluation_years, salary_grade_column  # noqa: E402
from services.researcher_profile_export import highest_degree_row  # noqa: E402

MAX_TOP_K = 20
DEFAULT_TOP_K = 5
_EMBEDDING_MATCH_THRESHOLD = 0.75
_FIT_RANK = {'상': 0, '중': 1, '하': 2}

_KNOWN_INTENTS = {
    'find_researchers_by_expertise',
    'find_similar_researchers',
    'find_researchers_by_criteria',
    'open_data_query',
}

QUERY_SYSTEM_PROMPT = """# Role
당신은 사내 연구원 전문성 데이터베이스에 대한 자연어 질문을 구조화된
검색 조건으로 바꾸는 "R&D Query Router"입니다. 직접 답을 만들지 않습니다 —
질문을 분류하고 검색에 필요한 핵심 개체만 뽑아냅니다.

# 지원하는 질문 유형(intent) — 반드시 이 5가지 중 하나로만 분류하세요
1. find_researchers_by_expertise : 이미 요약된 "강점 분야/키워드" 태그로 연구원을
   찾는 질문(태그 자체를 묻는 것이지, 학력·과제이력 같은 원천 데이터 항목이 아님)
   예) "로봇 제어 전문가 찾아줘", "센서 데이터 처리 할 줄 아는 사람 있어?"
2. find_similar_researchers : 특정 연구원(이름 또는 사번)과 전문성/역량이
   비슷한 "다른 연구원"을 찾는 질문 — researcher_query에 그 연구원의
   이름/사번을 넣으세요(전문성 키워드가 아니라 사람 자체를 기준으로 찾는
   질문이면 이 intent입니다. find_researchers_by_expertise와 헷갈리지
   마세요 — expertise_terms가 아니라 사람 이름이 기준이면 항상 이 intent).
   예) "홍길동 연구원과 전문성이 비슷한 사람 찾아줘",
   "정재원이랑 유사한 역량 가진 연구원 있어?", "홍길동과 비슷한 연구원은 누구야"
3. find_researchers_by_criteria : 연령대/최종학력/최근 N개년 평가등급 조합 중
   하나 이상을 조건으로 연구원을 찾는 질문 — 특히 평가등급 조건은 반드시 이
   intent로 분류하세요(open_data_query로 보내면 등급 순서·조합 비교를 틀리기
   쉽습니다). 등급 체계는 가(최우수)=5점 > 나=4점 > 다=3점 > 라=2점 > 마=1점
   (최하)이고, "OOO 이상/이하"는 등급을 자리별(연도별)로 짝짓는 게 아니라
   각 등급을 점수로 바꿔 N개년 "합계"끼리 비교하는 뜻입니다(예: "나나나 이상"
   = 3개년 점수 합이 나나나(4+4+4=12점) 이상이면 해당 — 나나나/나나가/나가나/
   가나나/가가나/가나가/가가가뿐 아니라, 다가 섞여도 다른 해에 가로 상쇄돼
   합계가 12점 이상이면 포함되는 가나다(5+4+3=12점)/나다가/가다나 등도 포함,
   합계가 12점에 못 미치는 다다다(3+3+3=9점)는 제외). grade_threshold에는
   등급 글자를 하나씩 리스트로 넣으세요(예: "나나가" → ["나","나","가"], 글자
   수 = 비교할 개년 수). grade_comparison은 "이상"(기본값)/"이하"/"초과"/
   "미만"/"동일" 중 하나("동일"도 등급 조합이 완전히 같아야 하는 게 아니라
   점수 합이 같으면 해당).
   예) "연령 30대, 최종학력 박사, 최근 3년 평가 나나가 이상 찾아줘",
   "최근 2년 평가 나나 이상인 석사 이상 연구원", "40대이면서 최근 3년 다다다 이하인 사람"
4. open_data_query : 위 세 가지가 다루는 "이미 계산된 요약 결과"나 "연령/학력/
   평가등급 조합"이 아니라, 원천 데이터의 다른 구체적 항목(전공명 자체, 실제
   과제 수행 이력, 논문/특허 실적, 부서별 집계 등)을 조건으로 찾거나 집계하는 질문
   예) "물리학 전공한 사람 찾아줘", "양자컴퓨팅 과제 수행 중인 연구원 보여줘",
   "특허 등록 3건 이상인 연구원", "부서별 평균 논문 수"
5. unsupported : 위 네 가지에 해당하지 않는 모든 질문(잡담, 이 시스템이 다루지
   않는 질문 등) — 억지로 끼워 맞추지 말고 이 값으로 분류하고
   reason_if_unsupported에 짧게 이유를 적으세요.

# Output Format (JSON만 출력하고 그 외 텍스트는 절대 출력하지 마세요)
{
  "intent": "find_researchers_by_expertise" | "find_similar_researchers" | "find_researchers_by_criteria" | "open_data_query" | "unsupported",
  "expertise_terms": ["..."],
  "project_name": "",
  "project_description": "",
  "researcher_query": "",
  "exclude_current_project": true,
  "department_filter": "",
  "age_min": null,
  "age_max": null,
  "degree": "",
  "grade_threshold": [],
  "grade_comparison": "이상",
  "top_k": 5,
  "reason_if_unsupported": ""
}
※ 해당 intent와 무관한 필드는 빈 문자열/빈 리스트/null로 두세요.
※ department_filter/top_k는 질문에 명시적으로 언급된 경우에만 채우고, 그 외에는
  기본값(department_filter="", top_k=5)을 유지하세요.
※ age_min/age_max: "30대"→age_min=30,age_max=39. "40대 이상"→age_min=40,age_max=null.
  "35세 이상"→age_min=35,age_max=null.
※ degree는 "박사"/"석사"/"학사"/"전문대"/"고교" 중 하나(최종학력 기준)만 넣으세요.
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


def _empty_table_result(intent: str, note: str) -> dict:
    return {'intent': intent, 'columns': [], 'labels': [], 'rows': [], 'total_rows': 0, 'note': note}


def _build_table_result(intent: str, items: list, column_order: list, note: str = '') -> dict:
    """구조화 2-intent(find_researchers_by_expertise/find_similar_researchers)의
    결과(item dict 목록)를 open_data_query와 동일한 columns/rows 표 형태로
    변환한다 — researcher_id가 있으면 사번/성명/부서/과제/CL/학력·전공/나이
    7개 기본 컬럼이 자동으로 앞에 붙어서(inject_person_columns), 화면은 3개
    intent 전부 같은 표 렌더러 하나로 보여줄 수 있다."""
    columns = list(column_order)
    rows = []
    for it in items:
        row = []
        for c in columns:
            v = it.get(c)
            if isinstance(v, list):
                v = '; '.join(str(x) for x in v)
            row.append(v)
        rows.append(row)
    columns, rows = open_data_query.inject_person_columns(columns, rows)
    return {
        'intent': intent,
        'columns': columns,
        'labels': data_labels.label_columns(columns),
        'rows': rows,
        'total_rows': len(rows),
        'note': note,
    }


def find_researchers_by_expertise(terms: list, department_filter: str = '', top_k: int = DEFAULT_TOP_K,
                                   current_only: bool = True) -> dict:
    terms = [str(t).strip() for t in (terms or []) if str(t).strip()]
    if not terms:
        return _empty_table_result('find_researchers_by_expertise', '질문에서 찾을 전문성 키워드를 확인하지 못했습니다.')

    profiles = data_store.read_expertise_profiles()
    if not profiles:
        return _empty_table_result(
            'find_researchers_by_expertise',
            '연구원 보유 전문성 분석.json이 없습니다(process_researcher_expertise.py 먼저 실행).')

    researchers_df = data_store.read_processed('researchers')
    name_map, dept_map = {}, {}
    if not researchers_df.empty:
        indexed = researchers_df.set_index('researcher_id')
        name_map = indexed['name'].to_dict()
        dept_map = indexed['department'].to_dict()
    # AI 검색 기본은 현재 소속자만(최신기준) — 누적기준을 고르면 전배·퇴사
    # 등으로 최신 인력현황에 없는 사람도 후보에 포함한다.
    allowed_ids = set(data_store.filter_current(researchers_df, current_only)['researcher_id']) \
        if not researchers_df.empty else None

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
        if allowed_ids is not None and rid not in allowed_ids:
            continue
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
    note = ' '.join(notes)
    if len(scored) > top_k:
        note = f'{note} 조건에 맞는 {len(scored)}명 중 상위 {top_k}명을 표시합니다.'.strip()
    return _build_table_result(
        'find_researchers_by_expertise', items,
        ['researcher_id', 'name', 'department', 'strength_fields', 'strength_keywords', 'matched_term_count'],
        note,
    )


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


def find_similar_researchers(researcher_query: str, top_k: int = DEFAULT_TOP_K,
                              current_only: bool = True) -> dict:
    """특정 연구원과 전문성이 유사한 다른 연구원을 찾는다. LLM 판정까지 이미
    끝난 pipeline/process_researcher_similarity.py의 배치 결과
    (researcher_similarity.json)를 그대로 조회할 뿐, 여기서 새로 유사도를
    계산하지 않는다.

    current_only=False(누적기준)면 조회 대상(researcher_query가 가리키는
    사람)은 전배·퇴사자도 찾을 수 있다 — 다만 추천되는 유사 연구원 후보는
    실제로 협업 가능한 사람이어야 하므로 이 값과 무관하게 항상 현재
    소속자로만 제한한다(JOB Market과 같은 원칙)."""
    top_k = min(top_k or DEFAULT_TOP_K, MAX_TOP_K)
    researchers_df = data_store.read_processed('researchers')
    resolve_pool = data_store.filter_current(researchers_df, current_only)
    candidates = _resolve_researcher(researcher_query, resolve_pool)
    if not candidates:
        return _empty_table_result(
            'find_similar_researchers', f'"{researcher_query}"에 해당하는 연구원을 찾지 못했습니다.')
    if len(candidates) > 1:
        name_map = researchers_df.set_index('researcher_id')['name'].to_dict()
        cand_desc = ', '.join(f'{name_map.get(rid, rid)}({rid})' for rid in candidates[:10])
        return _empty_table_result(
            'find_similar_researchers',
            f'동명이인 등으로 {len(candidates)}명이 검색됩니다: {cand_desc}. 사번으로 다시 질문해주세요.')

    rid = candidates[0]
    similarity_map = data_store.read_similar_researchers()
    entry = similarity_map.get(rid)
    if not entry:
        return _empty_table_result(
            'find_similar_researchers',
            '이 연구원에 대한 연구원↔연구원 유사도 데이터가 없습니다'
            '(pipeline/process_researcher_similarity.py 실행 필요).')

    name_map = researchers_df.set_index('researcher_id')['name'].to_dict()
    dept_map = researchers_df.set_index('researcher_id')['department'].to_dict()
    current_ids = set(data_store.filter_current(researchers_df, True)['researcher_id'])
    similar = [s for s in (entry.get('similar') or []) if s.get('researcher_id') in current_ids][:top_k]
    items = [
        {
            'researcher_id': s.get('researcher_id', ''),
            'name': name_map.get(s.get('researcher_id', ''), s.get('researcher_id', '')),
            'department': dept_map.get(s.get('researcher_id', ''), ''),
            'level': s.get('level', ''),
            'score': s.get('score', ''),
            'evidence': s.get('evidence', ''),
        }
        for s in similar
    ]
    note = ''
    base_name = name_map.get(rid, rid)
    if not items:
        note = f'{base_name}({rid})과 유사도 근거가 확인된 연구원이 없습니다.'
    return _build_table_result(
        'find_similar_researchers', items,
        ['researcher_id', 'name', 'department', 'level', 'score', 'evidence'],
        note,
    )


# 등급 1개당 점수. 가(최우수)=5 ~ 마(최하)=1 — 등간(1점 간격)이라 몇 점씩
# 주든(예: 55/65/75/85/95) N개년 합계 비교 결과는 동일하다.
_GRADE_SCORE = {'가': 5, '나': 4, '다': 3, '라': 2, '마': 1}


def _grade_threshold_pass(candidate_grades: list, threshold_grades: list, comparison: str) -> bool | None:
    """candidate_grades(한 사람의 N개년 등급)가 threshold_grades 기준으로
    comparison 조건을 만족하는지. 등급 글자가 가/나/다/라/마가 아니면(빈 값 등)
    판단 불가로 None을 반환 — 호출부는 이 경우 "데이터 없음"으로 제외 처리한다.

    "OOO 이상/이하"는 등급을 자리별(연도별)로 짝지어 비교하는 게 아니라,
    등급 하나하나를 점수(_GRADE_SCORE)로 바꿔 N개년 합계끼리 비교한다
    (사용자 확정: "나나나 이상"이면 나나나(12점)뿐 아니라 가나다(5+4+3=12점)
    처럼 낮은 등급이 섞여도 다른 해에 더 높은 등급으로 상쇄돼 합계가 같거나
    높으면 포함 — 등급을 원래 순서 그대로 짝짓지 않으므로 "어느 해에 어떤
    등급을 받았는지" 순서도 결과에 영향을 주지 않는다)."""
    try:
        cand_sum = sum(_GRADE_SCORE[g] for g in candidate_grades)
        thr_sum = sum(_GRADE_SCORE[g] for g in threshold_grades)
    except KeyError:
        return None
    if comparison == '이하':
        return cand_sum <= thr_sum
    if comparison == '초과':
        return cand_sum > thr_sum
    if comparison == '미만':
        return cand_sum < thr_sum
    if comparison in ('동일', '정확히'):
        return cand_sum == thr_sum
    return cand_sum >= thr_sum  # 기본값: 이상


def find_researchers_by_criteria(age_min: int | None = None, age_max: int | None = None,
                                  degree: str = '', grade_threshold: list | None = None,
                                  grade_comparison: str = '이상', department_filter: str = '',
                                  top_k: int = DEFAULT_TOP_K, current_only: bool = True) -> dict:
    """연령대/최종학력/최근 N개년 평가등급 조합을 AND 조건으로 걸러 찾는다.
    평가등급 조건("나나가 이상"처럼 순서 무관 다개년 조합 비교)은 LLM에게 SQL로
    생성시키면(open_data_query) 등급 순서(가>나>다>라>마)와 조합 비교 규칙을
    매번 다시 추론해야 해 틀리기 쉬워서, 여기서는 파이썬으로 결정적으로
    계산한다 — find_researchers_by_expertise/find_similar_researchers와 같은
    설계 원칙(판단은 이미 계산됐거나 규칙이 고정된 로직으로, LLM은 질문
    파싱만)."""
    researchers_df = data_store.read_processed('researchers')
    if researchers_df.empty:
        return _empty_table_result('find_researchers_by_criteria', '연구원 데이터가 없습니다.')
    researchers_df = data_store.filter_current(researchers_df, current_only)

    candidates = researchers_df.copy()

    if department_filter:
        dept_l = department_filter.strip().lower()
        candidates = candidates[candidates['department'].astype(str).str.lower().str.contains(dept_l, na=False)]

    current_year = datetime.now().year
    if age_min is not None or age_max is not None:
        def _age(birth_year):
            s = str(birth_year).strip()
            return current_year - int(s) if s.isdigit() else None
        ages = candidates['birth_year'].apply(_age)
        if age_min is not None:
            candidates = candidates[ages.apply(lambda a: a is not None and a >= age_min)]
            ages = ages[candidates.index]
        if age_max is not None:
            candidates = candidates[ages.apply(lambda a: a is not None and a <= age_max)]

    if degree:
        education_df = data_store.read_processed('education')
        edu_by_rid: dict = {}
        if not education_df.empty:
            for rid, grp in education_df.groupby('researcher_id'):
                edu_by_rid[rid] = grp.to_dict('records')

        def _matches_degree(rid):
            row = highest_degree_row(edu_by_rid.get(rid, []))
            return bool(row) and str(row.get('degree', '')).strip() == degree

        candidates = candidates[candidates['researcher_id'].apply(_matches_degree)]

    grade_note = ''
    if grade_threshold:
        # 화면 UI(pages/*.py)가 view_evaluation 권한 없는 역할에는 평가등급을
        # 아예 안 보여주는 것과 동일한 기준 — 여기서도 evaluations.csv를 조건으로
        # 걸기 전에 확인해, 권한 없는 역할이 자연어 질문으로 평가등급 조건 검색을
        # 우회하지 못하게 한다. 권한 이름을 직접 하드코딩하지 않고
        # auth.can_table()로 TABLE_PERMISSIONS(config/auth_config.py)을 거쳐
        # 조회 — open_data_query.py의 filter_permitted_tables()와 같은 매핑을 쓴다.
        if not auth.can_table('evaluations'):
            return _empty_table_result(
                'find_researchers_by_criteria',
                '평가등급 조건으로 검색할 권한이 없습니다.')
        n = len(grade_threshold)
        years = evaluation_years()[0][:n]
        if len(years) < n:
            return _empty_table_result(
                'find_researchers_by_criteria',
                f'최근 {n}개년 평가등급을 비교하기엔 확인 가능한 회계연도가 부족합니다.')
        cols = [salary_grade_column(y) for y in years]
        evaluations_df = data_store.read_processed('evaluations')
        missing_cols = [c for c in cols if evaluations_df.empty or c not in evaluations_df.columns]
        if missing_cols:
            return _empty_table_result(
                'find_researchers_by_criteria',
                f'평가등급 컬럼을 찾을 수 없습니다: {missing_cols} (evaluations.csv 확인 필요).')

        eval_by_rid = evaluations_df.set_index('researcher_id')[cols].to_dict('index')
        grade_evidence: dict = {}
        keep_ids = []
        excluded_missing = 0
        for rid in candidates['researcher_id']:
            row = eval_by_rid.get(rid)
            grades = [str(row.get(c, '')).strip() for c in cols] if row else []
            passed = _grade_threshold_pass(grades, grade_threshold, grade_comparison)
            if passed is None:
                excluded_missing += 1
                continue
            if passed:
                keep_ids.append(rid)
                grade_evidence[rid] = ' / '.join(f"'{str(y)[-2:]}:{g}" for y, g in zip(years, grades))
        candidates = candidates[candidates['researcher_id'].isin(keep_ids)]
        if excluded_missing:
            grade_note = f'최근 {n}개년 평가등급이 모두 확인되지 않는 {excluded_missing}명은 판단할 수 없어 제외했습니다.'

    top_k = min(top_k or DEFAULT_TOP_K, MAX_TOP_K)
    total = len(candidates)
    candidates = candidates.head(top_k)

    items = []
    for _, r in candidates.iterrows():
        rid = r['researcher_id']
        item = {'researcher_id': rid}
        if grade_threshold:
            item['grade_evidence'] = grade_evidence.get(rid, '')
        items.append(item)

    notes = []
    if total > top_k:
        notes.append(f'조건에 맞는 {total}명 중 상위 {top_k}명을 표시합니다.')
    if grade_note:
        notes.append(grade_note)
    if not items:
        notes.append('조건에 맞는 연구원을 찾지 못했습니다.')

    column_order = ['researcher_id'] + (['grade_evidence'] if grade_threshold else [])
    return _build_table_result('find_researchers_by_criteria', items, column_order, ' '.join(notes))


_GRADE_COMBO_RE = re.compile(r'([가나다라마]{2,})(?:\s*등급)?\s*(이상|이하|초과|미만|동일)')


def _regex_grade_criteria(question: str) -> dict | None:
    """"가가나 이상"/"나나가 이하"처럼 문법이 고정된 다개년 평가등급 조합
    표현은 LLM 파싱에 맡기지 않고 정규식으로 직접 뽑는다. QUERY_SYSTEM_PROMPT가
    이 표현의 의미(순서 무관 비교)를 예시까지 들어 설명해도, intent 분류나
    등급 글자 추출을 매번 LLM에 맡기면 질문 표현에 따라 틀릴 수 있다 —
    _grade_threshold_pass의 실제 판정 로직처럼, 문법이 고정된 부분은 파싱도
    결정적으로 처리해 LLM이 틀릴 여지를 없앤다. 매치되면
    {'grade_threshold': [...], 'grade_comparison': '...'}, 아니면 None."""
    m = _GRADE_COMBO_RE.search(question)
    if not m:
        return None
    return {'grade_threshold': list(m.group(1)), 'grade_comparison': m.group(2)}


def parse_question(question: str) -> dict:
    """자연어 질문을 구조화된 쿼리 dict로 변환(사내 LLM 1회 호출). 실패
    유형별로 다른 intent('error'|'unsupported')를 돌려줘 호출부가 구분해서
    안내할 수 있게 한다."""
    question = (question or '').strip()
    if not question:
        return {'intent': 'unsupported', 'reason_if_unsupported': '빈 질문입니다.'}

    grade_override = _regex_grade_criteria(question)

    max_wait = llm_client.query_max_wait()
    system_prompt = query_settings.apply(QUERY_SYSTEM_PROMPT)
    raw = llm_client.call_llm(question, system_prompt, temperature=0.0, max_tokens=400, max_wait=max_wait)
    if not raw:
        if grade_override:
            return {'intent': 'find_researchers_by_criteria', 'question': question,
                     'expertise_terms': [], 'researcher_query': '', 'department_filter': '',
                     'age_min': None, 'age_max': None, 'degree': '', 'top_k': DEFAULT_TOP_K,
                     **grade_override}
        return {'intent': 'error',
                'message': '지금 요청이 많아 응답을 만들지 못했습니다. 잠시 후 다시 시도해주세요.'}

    try:
        parsed = json.loads(llm_client.extract_json(raw))
    except json.JSONDecodeError:
        if grade_override:
            return {'intent': 'find_researchers_by_criteria', 'question': question,
                     'expertise_terms': [], 'researcher_query': '', 'department_filter': '',
                     'age_min': None, 'age_max': None, 'degree': '', 'top_k': DEFAULT_TOP_K,
                     **grade_override}
        return {'intent': 'error', 'message': '질문을 이해하지 못했습니다. 다르게 표현해 다시 질문해주세요.'}

    intent = parsed.get('intent')
    if intent not in _KNOWN_INTENTS:
        if grade_override:
            intent = 'find_researchers_by_criteria'
        else:
            return {'intent': 'unsupported', 'question': question,
                    'reason_if_unsupported': parsed.get('reason_if_unsupported', '')}

    try:
        top_k = int(parsed.get('top_k') or DEFAULT_TOP_K)
    except (TypeError, ValueError):
        top_k = DEFAULT_TOP_K

    def _to_int_or_none(v):
        try:
            return int(v) if v is not None and str(v).strip() != '' else None
        except (TypeError, ValueError):
            return None

    if grade_override:
        # 등급 조합 표현이 질문에 있으면, LLM이 intent/등급을 다르게 판단했더라도
        # 이 두 필드는 정규식 추출 결과로 강제한다(그 외 나이/학력/부서 등은
        # LLM 파싱 결과를 그대로 쓴다 — 그 부분은 문법이 고정돼 있지 않아서다).
        intent = 'find_researchers_by_criteria'
        grade_threshold = grade_override['grade_threshold']
        grade_comparison = grade_override['grade_comparison']
    else:
        grade_threshold = parsed.get('grade_threshold') or []
        if isinstance(grade_threshold, str):
            # LLM이 리스트 대신 "나나가" 같은 문자열을 줬을 때도 안전하게 받는다.
            grade_threshold = list(grade_threshold.strip())
        grade_threshold = [str(g).strip() for g in grade_threshold if str(g).strip()]
        grade_comparison = str(parsed.get('grade_comparison') or '이상').strip()

    return {
        'intent': intent,
        'question': question,
        'expertise_terms': parsed.get('expertise_terms') or [],
        'researcher_query': parsed.get('researcher_query') or '',
        'department_filter': parsed.get('department_filter') or '',
        'age_min': _to_int_or_none(parsed.get('age_min')),
        'age_max': _to_int_or_none(parsed.get('age_max')),
        'degree': str(parsed.get('degree') or '').strip(),
        'grade_threshold': grade_threshold,
        'grade_comparison': grade_comparison,
        'top_k': top_k,
    }


def execute_query(parsed: dict, current_only: bool = True) -> dict:
    """parse_question()의 결과를 실제 데이터 조회로 실행한다.
    current_only=False(누적기준)면 전배·퇴사 등으로 최신 인력현황에 없는
    사람도 조회 대상에 포함한다(AI 검색 전역 토글, components/nl_query_bar.py)."""
    intent = parsed.get('intent')
    if intent == 'error':
        return _empty_table_result('error', parsed.get('message', '알 수 없는 오류가 발생했습니다.'))

    if intent == 'unsupported':
        # 3개 intent 어디에도 안 걸렸다고 바로 포기하지 않고, 마지막 수단으로
        # 개방형 SQL 질의를 한 번 더 시도한다 — data/processed/ 전체(CSV +
        # LLM 파생 JSON)를 대상으로 하므로 라우터 프롬프트가 놓친 질문도
        # 여기서 답이 나올 때가 있다. 그래도 결과가 없으면 기존 안내 문구로 폴백.
        question = parsed.get('question') or ''
        if question:
            fallback = open_data_query.answer(question, current_only=current_only)
            if fallback.get('rows'):
                return fallback

        reason = parsed.get('reason_if_unsupported') or ''
        note = '죄송합니다, 이 질문에는 아직 답변할 수 없습니다.'
        if reason:
            note += f' ({reason})'
        note += (' "특정 전문성 보유자 찾기", "연구원과 유사한 연구원 찾기", '
                 '또는 학력·과제이력 등 원천 데이터에 대한 질문 형태로 질문해 주세요.')
        return _empty_table_result('unsupported', note)

    if intent == 'open_data_query':
        return open_data_query.answer(parsed.get('question') or '', current_only=current_only)

    top_k = parsed.get('top_k') or DEFAULT_TOP_K
    if intent == 'find_researchers_by_expertise':
        return find_researchers_by_expertise(
            parsed.get('expertise_terms') or [], parsed.get('department_filter', ''), top_k,
            current_only=current_only)
    if intent == 'find_similar_researchers':
        return find_similar_researchers(parsed.get('researcher_query', ''), top_k, current_only=current_only)
    if intent == 'find_researchers_by_criteria':
        return find_researchers_by_criteria(
            age_min=parsed.get('age_min'), age_max=parsed.get('age_max'),
            degree=parsed.get('degree', ''), grade_threshold=parsed.get('grade_threshold') or [],
            grade_comparison=parsed.get('grade_comparison', '이상'),
            department_filter=parsed.get('department_filter', ''), top_k=top_k,
            current_only=current_only)

    return _empty_table_result('unsupported', '알 수 없는 질문 유형입니다.')


_ANSWER_SYSTEM_PROMPT = """# Role
당신은 사내 연구원 검색 결과를 사용자에게 설명해주는 "결과 설명 도우미"입니다.

# Goal
사용자의 질문과, 이미 검색으로 찾아낸 결과 표(라벨과 값)를 보고 "왜 이런
결과가 나왔는지"를 짧은 한국어 설명으로 답합니다.

# Guidelines & Constraints
1. 반드시 주어진 표 데이터에 실제로 있는 내용만 근거로 쓰세요 — 표에 없는
   사실을 새로 만들어내거나 추측하지 마세요(당신은 새로 판단하는 역할이
   아니라, 이미 나온 결과를 설명하는 역할입니다).
2. 인물을 한 명씩 전부 나열하지 말고, 전체적으로 어떤 공통 기준으로
   찾아졌는지 2~4문장으로 요약하세요.
3. 표에 이미 판정 근거(예: evidence, matched_term_count 같은 컬럼)가
   있으면 그 내용을 활용해 설명하세요.
4. 결과가 일부 조건과 정확히 안 맞을 수 있다면(예: 의미가 비슷한 표기로
   대체 검색된 경우) 그 점도 정직하게 언급하세요.
5. 순수 텍스트로만 답하세요(JSON도, 마크다운 기호도 쓰지 마세요).
"""

_ANSWER_MAX_ROWS = 20


def _answer_prompt(question: str, result: dict) -> str:
    labels = result.get('labels') or result.get('columns') or []
    rows = (result.get('rows') or [])[:_ANSWER_MAX_ROWS]
    lines = [', '.join(str(v) if v is not None else '' for v in row) for row in rows]
    table_text = f"{' | '.join(labels)}\n" + '\n'.join(lines)
    extra = ''
    total_rows = result.get('total_rows') or len(result.get('rows') or [])
    if total_rows > len(rows):
        extra = f'\n(표에는 총 {total_rows}건 중 {len(rows)}건만 보여줬습니다.)'
    return f'[질문]\n{question}\n\n[검색 결과 표]\n{table_text}{extra}\n\n위 결과에 대해 설명해주세요.'


def _generate_answer_summary(question: str, result: dict) -> str:
    """검색 결과 표를 근거로, "왜 이렇게 찾았는지" 설명을 LLM에게 한 번 더
    요청한다(구조화 변환 1회 호출과는 별개). 이미 조회로 확정된 표 데이터
    설명에 그치도록 프롬프트에서 강하게 제약해 새 판단/환각을 막는다.
    실패/시간초과 시 빈 문자열로 안전하게 처리 — 답변 텍스트가 없어도 표
    자체는 그대로 보여준다."""
    if not result.get('rows'):
        return ''
    max_wait = llm_client.query_max_wait()
    prompt = _answer_prompt(question, result)
    raw = llm_client.call_llm(prompt, _ANSWER_SYSTEM_PROMPT, temperature=0.2, max_tokens=500, max_wait=max_wait)
    return raw.strip() if raw else ''


def answer_question(question: str, current_only: bool = True) -> dict:
    """질문 → (질의 변환 → 조회 → 결과 설명) 전체 파이프라인의 단일
    진입점. 결과 설명(answer)은 error/unsupported이거나 결과가 없으면
    비워둔다. current_only=False(누적기준)면 전배·퇴사 등으로 최신
    인력현황에 없는 사람도 조회 대상에 포함한다."""
    result = execute_query(parse_question(question), current_only=current_only)
    if result.get('intent') not in ('error', 'unsupported'):
        result['answer'] = _generate_answer_summary(question, result)
    return result
