"""
"보유 전문성" 자연어 질문 기능의 개방형 질의 폴백 — services/nl_query.py의
3개 구조화 intent 밖 질문("물리학 전공한 사람 찾아줘", "양자컴 과제 수행 중인
연구원 보여줘")을 처리한다.

기존 services/text2sql.py("연구원 목록" 탭 AI 검색)와 철학은 같지만
(자연어 → LLM이 SQL 생성 → 안전 검증 → 실행), 그 모듈은 PostgreSQL 필수라
CSV만 쓰는 환경에서는 동작하지 않는다. 이 모듈은 DuckDB로 data/processed/의
CSV(및 LLM 파생 JSON 산출물)를 그 자리에서 SQL로 조회한다 — 별도 DB 서버 불필요.

흐름:
  1) data/processed/*.csv를 매 호출 시점에 동적으로 스캔해 테이블로 등록하고
     (DB가 나중에 생기면 services.data_store.read_processed()가 자동으로 DB를
     읽으므로 이 스캔도 자동으로 DB 기준이 된다), 연구원 보유 전문성 분석.json/
     project_fit_by_project.json/project_fit_by_researcher.json도 평탄화해
     함께 등록한다.
  2) LLM에게 스키마(테이블/컬럼명만, 실제 행 데이터는 절대 전달하지 않음)와
     질문을 주고 {sql, fallback_table, fallback_column, fallback_term} JSON을
     받는다 — services.text2sql.generate_sql()과 같은 발상이지만, "SQL이 0건일
     때 의미 기반으로 재시도할 후보"까지 한 번에 받아 재호출을 줄인다.
  3) services.text2sql.sanitize_sql()을 그대로 재사용해 안전 검증(쓰기/DDL
     차단, 다중 문장·주석 차단, LIMIT 자동 부착)한 뒤 DuckDB에서 실행.
  4) 결과가 0건이면 fallback_table/column/term으로 BGE-M3 임베딩 유사도 매칭을
     시도한다(services.nl_query.expand_term()과 같은 폴백 철학).
  5) 응답은 항상 최대 DISPLAY_LIMIT(1000)건으로 자른다(SQL 자체의 LIMIT과
     무관하게 후처리로 강제) — 화면(pages/researcher_similarity_map.py)은
     그중 기본 30건만 보여주고 "전체 보기"로 펼친다.
  6) 결과에 researcher_id 컬럼이 있으면(=사람에 대한 데이터) 사번/성명/부서/
     과제/CL/학력·전공(최종 학력만)/나이 7개 기본 컬럼을 앞에 붙인다
     (inject_person_columns — services.researcher_profile_export.person_base_table
     재사용, 엑셀 다운로드와 표기 동일). 컬럼명은 services.data_labels로
     한글 라벨을 붙여 함께 반환한다('columns'는 원본명 유지 — 정렬/필터용,
     'labels'는 화면 표시용).

동시성: SQL 생성 호출은 services.llm.chat()이 아니라 pipeline/llm_client.call_llm()
을 max_wait과 함께 사용해, nl_query.py의 나머지 intent와 동일하게 동시 호출
슬롯을 못 얻으면 무한 대기 대신 빠르게 실패한다(text2sql.py에는 이 보호가 없음).
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
from services import data_labels  # noqa: E402
from services import data_store  # noqa: E402
from services import researcher_profile_export as rpe  # noqa: E402
from services import text2sql  # noqa: E402
from services.llm import LLMError  # noqa: E402

try:
    import llm_config as _llm_cfg
except ModuleNotFoundError:
    _llm_cfg = None

DISPLAY_LIMIT = 1000
_EMBEDDING_MATCH_THRESHOLD = 0.75
_DISTINCT_VALUES_CAP = 2000

# 결과에 researcher_id가 있으면 항상 맨 앞에 rpe.PERSON_BASE_COLUMNS 7개를
# 붙인다(services.researcher_profile_export 참고) — 원래 SQL 결과에 이
# 개념과 겹치는 원본 컬럼이 있으면(예: department, major) 중복 표시하지
# 않도록 제외한다.
_PERSON_DEDUPE_RAW_COLUMNS = {'name', 'department', 'org_code', 'position', 'degree', 'major', 'birth_year'}

_SQL_GEN_SYSTEM_TEMPLATE = """You are a DuckDB SQL expert helping route natural-language HR/R&D
questions into a single read-only SQL query, run against an in-memory DuckDB database.

Rules:
- Use ONLY the given tables and columns below.
- Output ONLY a single JSON object, no explanation, no markdown fences.
- The SQL must be a single statement starting with SELECT or WITH.
- Never write/modify data (no INSERT/UPDATE/DELETE/DDL).
- Every column is stored as TEXT. Cast before numeric/date comparison or
  aggregation, e.g. CAST(col AS INTEGER), CAST(col AS DOUBLE), CAST(col AS DATE).
- Join tables on researcher_id when combining data across tables.
- If the question is about people/researchers (the result is naturally one row
  per researcher, or filters/ranks researchers), ALWAYS include researcher_id
  in the SELECT list even if the user didn't explicitly ask for it — the
  application uses it to attach standard identity columns to the result.
- ALWAYS include, in the SELECT list, the column(s) that justify why a row
  matches the question (whatever you used in a WHERE/LIKE/JOIN condition to
  decide relevance) — not just in the WHERE clause. This is the evidence the
  user actually asked for, e.g. for "미생물 관련 연구이력이 있는 사람" you
  filter tasks.task_name LIKE '%미생물%', so also SELECT tasks.task_name.
  Include at most 3 such evidence columns (pick the most directly relevant
  ones if more conditions are involved).
- strength_fields/strength_keywords/key_responsibilities/domain_knowledge_skill
  in the expertise_profiles table are semicolon("; ")-joined lists stored as a
  single text value — use LIKE '%...%' against them, not exact equality.
- If the question implies ranking/ordering (e.g. "가장 많은", "우수한"), include
  an ORDER BY. Otherwise omit ORDER BY.
- Also propose ONE fallback for semantic retry, in case the SQL finds nothing:
  pick the single most likely (table, column, search term) where a loose,
  meaning-based match (not an exact keyword) might succeed instead of the SQL's
  literal LIKE condition — e.g. a technology area that might be phrased
  differently in the data. Leave these three fields as empty strings if you
  can't think of a reasonable fallback.

Output format (JSON only):
{{
  "sql": "SELECT ...",
  "fallback_table": "table_name or empty string",
  "fallback_column": "column_name or empty string",
  "fallback_term": "search term or empty string"
}}

Schema (all columns are TEXT):
{schema}
"""


def _safe_table_name(stem: str) -> str:
    name = re.sub(r'[^0-9a-zA-Z_]', '_', stem).strip('_').lower()
    return name


def _discover_csv_tables() -> dict:
    """data/processed/*.csv를 동적으로 스캔해 {테이블명: DataFrame}으로 반환.
    수동으로 목록을 유지하지 않아 새 CSV가 추가돼도 재배포 없이 바로 조회
    대상이 된다. services.data_store.read_processed()를 거치므로 DB가 설정된
    환경에서는 자동으로 DB에서 읽는다."""
    tables = {}
    if not os.path.isdir(data_store.DATA_DIR):
        return tables
    for fname in sorted(os.listdir(data_store.DATA_DIR)):
        if not fname.endswith('.csv'):
            continue
        stem = fname[:-4]
        table_name = _safe_table_name(stem)
        if not table_name:
            continue
        df = data_store.read_processed(stem)
        if not df.empty:
            tables[table_name] = df
    return tables


def _expertise_profiles_table() -> pd.DataFrame:
    profiles = data_store.read_expertise_profiles()
    rows = [
        {
            'researcher_id': rid,
            'strength_fields': '; '.join(p.get('strength_fields') or []),
            'strength_keywords': '; '.join(p.get('strength_keywords') or []),
            'key_responsibilities': '; '.join(p.get('key_responsibilities') or []),
            'domain_knowledge_skill': '; '.join(p.get('domain_knowledge_skill') or []),
        }
        for rid, p in profiles.items()
    ]
    return pd.DataFrame(rows)


def _project_fit_by_project_table() -> pd.DataFrame:
    entries = data_store.read_project_fit_by_project()
    rows = [
        {
            'dep_name': e.get('dep_name', ''), 'project_name': e.get('project_name', ''),
            'job_title': e.get('job_title', ''), 'researcher_id': r.get('researcher_id', ''),
            'fit_score': r.get('fit_score', ''), 'reason': r.get('reason', ''),
        }
        for e in entries
        for r in e.get('rankings') or []
    ]
    return pd.DataFrame(rows)


def _project_fit_by_researcher_table() -> pd.DataFrame:
    by_researcher = data_store.read_project_fit_by_researcher()
    rows = [
        {
            'researcher_id': rid, 'dep_name': m.get('dep_name', ''),
            'project_name': m.get('project_name', ''), 'job_title': m.get('job_title', ''),
            'fit_score': m.get('fit_score', ''), 'reason': m.get('reason', ''),
        }
        for rid, entry in by_researcher.items()
        for m in entry.get('matches') or []
    ]
    return pd.DataFrame(rows)


def _discover_json_tables() -> dict:
    """연구원 보유 전문성 분석.json/project_fit_by_*.json을 평탄화해 CSV 테이블과
    동일한 창구(SQL)로 조회할 수 있게 등록. 한글 파일명은 SQL 식별자로 쓰기
    번거로워 영문 별칭을 붙인다."""
    tables = {}
    for name, builder in (
        ('expertise_profiles', _expertise_profiles_table),
        ('project_fit_by_project', _project_fit_by_project_table),
        ('project_fit_by_researcher', _project_fit_by_researcher_table),
    ):
        df = builder()
        if not df.empty:
            tables[name] = df
    return tables


def _schema_prompt(tables: dict) -> str:
    return '\n'.join(f'{name}({", ".join(str(c) for c in df.columns)})' for name, df in tables.items())


def _generate_sql(question: str, schema: str, max_wait) -> dict | None:
    system = _SQL_GEN_SYSTEM_TEMPLATE.format(schema=schema)
    raw = llm_client.call_llm(question, system, temperature=0.0, max_tokens=700, max_wait=max_wait)
    if not raw:
        return None
    try:
        parsed = json.loads(llm_client.extract_json(raw))
    except json.JSONDecodeError:
        return None
    sql = str(parsed.get('sql') or '').strip()
    if not sql:
        return None
    return {
        'sql': sql,
        'fallback_table': str(parsed.get('fallback_table') or '').strip(),
        'fallback_column': str(parsed.get('fallback_column') or '').strip(),
        'fallback_term': str(parsed.get('fallback_term') or '').strip(),
    }


def _cap_limit(sql: str, cap: int = DISPLAY_LIMIT) -> str:
    """SQL에 LIMIT이 없으면 붙여 준다(있으면 그대로 둠 — 어차피 실행 결과는
    아래에서 항상 DISPLAY_LIMIT으로 다시 자르므로, 여기서는 완전히 무제한인
    조회만 막아 두는 정도의 역할)."""
    if not re.search(r'\blimit\b', sql, re.IGNORECASE):
        return f'{sql} LIMIT {cap}'
    return sql


def _execute(con, sql: str, params: list | None = None) -> tuple:
    result = con.execute(sql, params) if params is not None else con.execute(sql)
    columns = [d[0] for d in result.description]
    rows = [list(r) for r in result.fetchall()]
    return columns, rows


def inject_person_columns(columns: list, rows: list) -> tuple:
    """결과에 researcher_id가 있으면(=사람 데이터로 판단) 앞쪽에
    rpe.PERSON_BASE_COLUMNS 7개를 붙이고, 겹치는 원본 컬럼은 제거한다.
    researcher_id가 없으면 그대로 반환. nl_query.py의 정형 3-intent 결과도
    이 함수를 거쳐 개방형 질의와 동일한 표 형태로 통일된다."""
    if 'researcher_id' not in columns:
        return columns, rows
    rid_idx = columns.index('researcher_id')

    researcher_ids = []
    seen = set()
    for row in rows:
        raw = row[rid_idx] if rid_idx < len(row) else None
        if raw is None:
            continue
        rid = str(raw).strip().zfill(8)
        if rid and rid not in seen:
            seen.add(rid)
            researcher_ids.append(rid)
    base_table = rpe.person_base_table(researcher_ids)

    extra_idx = [i for i, c in enumerate(columns) if i != rid_idx and c not in _PERSON_DEDUPE_RAW_COLUMNS]
    new_columns = list(rpe.PERSON_BASE_COLUMNS) + [columns[i] for i in extra_idx]

    new_rows = []
    for row in rows:
        raw = row[rid_idx] if rid_idx < len(row) else None
        rid = str(raw).strip().zfill(8) if raw is not None else ''
        base_vals = base_table.get(rid) or [rid, '-', '-', '-', '-', '-', '-']
        extra_vals = [row[i] if i < len(row) else None for i in extra_idx]
        new_rows.append(list(base_vals) + extra_vals)
    return new_columns, new_rows


def _embedding_match(term: str, candidates: set, threshold: float = _EMBEDDING_MATCH_THRESHOLD, top_n: int = 5) -> set:
    """services.nl_query.expand_term()의 임베딩 폴백과 동일한 방식 — 여기서는
    strength_fields 같은 고정 어휘집이 아니라 임의 컬럼의 고유값 집합을 대상으로
    한다는 점만 다르다."""
    if not candidates:
        return set()
    pool = sorted(candidates)
    vectors = fit.cached_embed([term] + pool)
    term_vec, pool_vecs = vectors[:1], vectors[1:]
    sims = fit.cosine_sim_matrix(term_vec, pool_vecs)[0]
    ranked = sorted(range(len(pool)), key=lambda i: -sims[i])[:top_n]
    return {pool[i] for i in ranked if sims[i] >= threshold}


def _semantic_fallback(con, table: str, column: str, term: str) -> tuple | None:
    if not (table and column and term):
        return None
    try:
        _, distinct_rows = _execute(
            con,
            f'SELECT DISTINCT "{column}" FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL AND "{column}" != \'\' LIMIT {_DISTINCT_VALUES_CAP}',
        )
    except Exception:
        return None
    values = {r[0] for r in distinct_rows if r[0]}
    if not values:
        return None

    try:
        matched = _embedding_match(term, values)
    except LLMError:
        return None
    if not matched:
        return None

    matched_list = sorted(matched)
    placeholders = ', '.join('?' for _ in matched_list)
    select_sql = f'SELECT * FROM "{table}" WHERE "{column}" IN ({placeholders}) LIMIT {DISPLAY_LIMIT}'
    try:
        columns, rows = _execute(con, select_sql, matched_list)
    except Exception:
        return None
    return select_sql, columns, rows


def answer(question: str) -> dict:
    """질문 → {intent, sql, columns, rows(최대 50건), total_rows, source, note}."""
    question = (question or '').strip()
    if not question:
        return {'intent': 'open_data_query', 'columns': [], 'rows': [], 'note': '질문을 입력해주세요.'}

    tables = _discover_csv_tables()
    tables.update(_discover_json_tables())
    if not tables:
        return {'intent': 'open_data_query', 'columns': [], 'rows': [],
                'note': '조회할 데이터가 없습니다(data/processed/에 CSV가 없음).'}

    schema = _schema_prompt(tables)
    max_wait = getattr(_llm_cfg, 'LLM2_QUERY_MAX_WAIT_SECONDS', 15) if _llm_cfg else 15
    gen = _generate_sql(question, schema, max_wait)
    if gen is None:
        return {'intent': 'open_data_query', 'columns': [], 'rows': [],
                'note': '지금 요청이 많거나 질문을 조회문으로 바꾸지 못했습니다. '
                        '잠시 후 다시 시도하거나 다르게 질문해주세요.'}

    import duckdb

    con = duckdb.connect(':memory:')
    try:
        for name, df in tables.items():
            con.register(name, df)

        try:
            safe_sql = text2sql.sanitize_sql(_cap_limit(gen['sql']))
        except text2sql.Text2SQLError as exc:
            return {'intent': 'open_data_query', 'columns': [], 'rows': [], 'sql': gen['sql'],
                    'note': f'생성된 조회문이 허용되지 않습니다: {exc}'}

        try:
            columns, rows = _execute(con, safe_sql)
        except Exception as exc:  # noqa: BLE001
            return {'intent': 'open_data_query', 'columns': [], 'rows': [], 'sql': safe_sql,
                    'note': f'조회 중 오류가 발생했습니다: {str(exc)[:200]}'}

        used_sql, source = safe_sql, 'sql'
        if not rows:
            fb = _semantic_fallback(con, gen['fallback_table'], gen['fallback_column'], gen['fallback_term'])
            if fb:
                used_sql, columns, rows = fb
                source = 'semantic_fallback'
    finally:
        con.close()

    total_fetched = len(rows)
    shown = rows[:DISPLAY_LIMIT]
    columns, shown = inject_person_columns(columns, shown)

    if source == 'semantic_fallback':
        note = f'정확히 일치하는 결과가 없어 "{gen["fallback_term"]}"과(와) 의미가 비슷한 값으로 다시 찾았습니다.'
    elif total_fetched == 0:
        note = '조건에 맞는 결과를 찾지 못했습니다.'
    else:
        note = ''

    return {
        'intent': 'open_data_query',
        'sql': used_sql,
        'columns': columns,
        'labels': data_labels.label_columns(columns),
        'rows': shown,
        'total_rows': total_fetched,
        'source': source,
        'note': note,
    }
