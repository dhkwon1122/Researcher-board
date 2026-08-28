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
     researcher_similarity.json도 평탄화해 함께 등록한다.
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

동시성: SQL 생성 호출은 pipeline/llm_client.call_llm()을 max_wait과 함께
사용해, nl_query.py의 나머지 intent와 동일하게 동시 호출 슬롯을 못 얻으면
무한 대기 대신 빠르게 실패한다(text2sql.py에는 이 보호가 없음).

self-repair: 생성된 SQL이 안전 검증(sanitize_sql)에 걸리거나 DuckDB 실행
자체가 에러(문법 오류 등)로 실패하면, 그 에러 메시지를 LLM에 다시 주고 한
번만 재생성을 시도한다(_generate_sql_repair). 기존 "0건이면 의미 기반
재시도"(_semantic_fallback)는 SQL 자체는 정상 실행됐지만 결과가 없는
경우를 보완하는 것이고, 이 재시도는 SQL이 애초에 실행 불가능했던 경우를
보완하는 것이라 서로 겹치지 않는다.
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
from services import auth  # noqa: E402
from services import data_labels  # noqa: E402
from services import data_store  # noqa: E402
from services import query_settings  # noqa: E402
from services import researcher_profile_export as rpe  # noqa: E402
from services import text2sql  # noqa: E402
from services.llm import LLMError  # noqa: E402

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
{current_only_rule}
- Also propose ONE fallback for semantic retry, in case the SQL finds nothing:
  pick the single most likely (table, column, search term) where a loose,
  meaning-based match (not an exact keyword) might succeed instead of the SQL's
  literal LIKE condition — e.g. a technology area that might be phrased
  differently in the data. Leave these three fields as empty strings if you
  can't think of a reasonable fallback.

Examples (showing the JOIN/CAST/LIKE patterns above — table and column names
here may not exist in the actual schema below, treat them only as pattern
references, not as real tables to query):

Q: 부서별 재직 인원수
A: {{"sql": "SELECT department, COUNT(*) AS cnt FROM researchers WHERE is_current = 'Y' GROUP BY department", "fallback_table": "", "fallback_column": "", "fallback_term": ""}}

Q: AI 관련 전문성을 가진 연구원
A: {{"sql": "SELECT researcher_id, strength_fields FROM expertise_profiles WHERE strength_fields LIKE '%AI%'", "fallback_table": "expertise_profiles", "fallback_column": "strength_fields", "fallback_term": "인공지능"}}

Q: 논문을 가장 많이 쓴 연구원 5명
A: {{"sql": "SELECT p.researcher_id, COUNT(*) AS pub_count FROM publications p JOIN researchers r ON r.researcher_id = p.researcher_id WHERE r.is_current = 'Y' GROUP BY p.researcher_id ORDER BY pub_count DESC LIMIT 5", "fallback_table": "", "fallback_column": "", "fallback_term": ""}}

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

_REPAIR_SYSTEM_SUFFIX = """

Your previous answer's SQL failed when run:
Previous SQL:
{bad_sql}

Error:
{error}

Fix it and return the same JSON format as before (a corrected "sql", plus
"fallback_table"/"fallback_column"/"fallback_term"). Output ONLY the JSON
object, no explanation."""


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


def _researcher_similarity_table() -> pd.DataFrame:
    similarity_map = data_store.read_similar_researchers()
    rows = [
        {
            'researcher_id': rid,
            'similar_researcher_id': s.get('researcher_id', ''),
            'score': s.get('score', ''),
            'level': s.get('level', ''),
            'evidence': '; '.join(s.get('evidence') or []) if isinstance(s.get('evidence'), list) else s.get('evidence', ''),
        }
        for rid, entry in similarity_map.items()
        for s in entry.get('similar') or []
    ]
    return pd.DataFrame(rows)


def _discover_json_tables() -> dict:
    """연구원 보유 전문성 분석.json/researcher_similarity.json을 평탄화해 CSV
    테이블과 동일한 창구(SQL)로 조회할 수 있게 등록. 한글 파일명은 SQL
    식별자로 쓰기 번거로워 영문 별칭을 붙인다."""
    tables = {}
    for name, builder in (
        ('expertise_profiles', _expertise_profiles_table),
        ('researcher_similarity', _researcher_similarity_table),
    ):
        df = builder()
        if not df.empty:
            tables[name] = df
    return tables


def _schema_prompt(tables: dict) -> str:
    return '\n'.join(f'{name}({", ".join(str(c) for c in df.columns)})' for name, df in tables.items())


_CURRENT_ONLY_RULE = (
    "- The researchers table has an is_current column ('Y' if this person is "
    "in the latest headcount snapshot, 'N' if they've since transferred out or "
    "left and are no longer active — the row is kept for history, not deleted). "
    "Unless the question explicitly asks about people who left/transferred/are "
    "no longer active, or asks for historical/all-time/cumulative data, ALWAYS "
    "add a condition restricting to is_current = 'Y' (directly if the query "
    "selects from researchers, or via a join/subquery filter on researcher_id "
    "otherwise)."
)
_CUMULATIVE_RULE = (
    "- Do NOT filter by the researchers table's is_current column — the user "
    "explicitly asked for cumulative/all-time results, which should include "
    "people who have since transferred out or left."
)
# 명단 화면의 "누적기준 + 기간 지정"(2026-08-28)과 동일한 개념을 AI 검색에도
# 그대로 적용한다 — *_history 테이블(researcher_id, valid_year, valid_month가
# 자연키, 한 사람당 여러 스냅샷 행)에서 지정한 기간 안의 스냅샷만 골라, 그
# 기간 안에서 가장 최근 것 1건만 그 사람의 대표값으로 쓰라고 LLM에게 지시한다.
_PERIOD_RULE_TEMPLATE = (
    "- The user has specified a specific historical period: {start} to {end} "
    "(inclusive, by year-month; format YYYY-MM). For this query, do NOT use "
    "current-state tables (researchers, evaluations, tech_ownership, "
    "job_profile, core_technology) or the is_current column — use their "
    "*_history counterparts instead (e.g. researchers_history, "
    "evaluations_history, tech_ownership_history, job_profile_history, "
    "core_technology_history), each of which has one row per "
    "(researcher_id, valid_year, valid_month) snapshot. First filter snapshot "
    "rows to those whose (CAST(valid_year AS INTEGER), CAST(valid_month AS "
    "INTEGER)) falls within the given period, then keep only each "
    "researcher_id's single most recent snapshot inside that period — e.g. "
    "using QUALIFY ROW_NUMBER() OVER (PARTITION BY researcher_id ORDER BY "
    "CAST(valid_year AS INTEGER) DESC, CAST(valid_month AS INTEGER) DESC) = 1 "
    "after the period filter, or an equivalent subquery. If a *_history table "
    "for the needed field doesn't exist, fall back to the current-state table "
    "for that field only, but still restrict the overall person set using a "
    "*_history table where possible."
)


def _parse_gen_response(raw: str) -> dict | None:
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


def _period_or_current_rule(current_only: bool, period: tuple[str, str] | None) -> str:
    if period:
        return _PERIOD_RULE_TEMPLATE.format(start=period[0], end=period[1])
    return _CURRENT_ONLY_RULE if current_only else _CUMULATIVE_RULE


def _generate_sql(question: str, schema: str, max_wait, current_only: bool = True,
                   period: tuple[str, str] | None = None) -> dict | None:
    rule = _period_or_current_rule(current_only, period)
    system = query_settings.apply(_SQL_GEN_SYSTEM_TEMPLATE.format(schema=schema, current_only_rule=rule))
    raw = llm_client.call_llm(question, system, temperature=0.0, max_tokens=700, max_wait=max_wait)
    return _parse_gen_response(raw)


def _generate_sql_repair(question: str, schema: str, max_wait, current_only: bool,
                          bad_sql: str, error: str, period: tuple[str, str] | None = None) -> dict | None:
    """실패한 SQL과 에러 메시지를 시스템 프롬프트 뒤에 덧붙여 한 번만 재생성
    시도(self-repair). call_llm이 단일 system/user 메시지쌍만 지원하므로,
    "이전 시도 → 에러" 대화를 시스템 프롬프트 안에 그대로 이어붙이는 방식으로
    같은 효과를 낸다."""
    rule = _period_or_current_rule(current_only, period)
    base = _SQL_GEN_SYSTEM_TEMPLATE.format(schema=schema, current_only_rule=rule)
    system = query_settings.apply(base) + _REPAIR_SYSTEM_SUFFIX.format(bad_sql=bad_sql, error=error[:500])
    raw = llm_client.call_llm(question, system, temperature=0.0, max_tokens=700, max_wait=max_wait)
    return _parse_gen_response(raw)


def _cap_limit(sql: str, cap: int = DISPLAY_LIMIT) -> str:
    """LLM이 큰 LIMIT을 넣어도 결과 행 수가 cap을 넘지 않도록 바깥에서 제한."""
    work = sql.strip().rstrip(';').strip()
    return f'SELECT * FROM ({work}) AS _bounded_result LIMIT {int(cap)}'


def _execute(con, sql: str, params: list | None = None) -> tuple:
    result = con.execute(sql, params) if params is not None else con.execute(sql)
    columns = [d[0] for d in result.description]
    rows = [list(r) for r in result.fetchmany(DISPLAY_LIMIT + 1)]
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
    identifier = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
    if not identifier.fullmatch(table) or not identifier.fullmatch(column):
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


def answer(question: str, current_only: bool = True, period: tuple[str, str] | None = None) -> dict:
    """질문 → {intent, sql, columns, rows(최대 50건), total_rows, source, note}.
    current_only=False(누적기준)면 SQL 생성 지시문에서 is_current 필터를
    빼서 전배·퇴사 등으로 최신 인력현황에 없는 사람도 조회 대상에 포함한다.
    period=(시작 YYYY-MM, 종료 YYYY-MM)이 주어지면(누적기준에서 기간까지
    지정한 경우, 2026-08-28) current_only는 무시하고 *_history 테이블에서
    그 기간 안의 마지막 스냅샷을 쓰도록 지시한다 — 명단 화면의 기간 지정
    조회와 동일한 개념(data/processed/CLAUDE.md 참고)."""
    question = (question or '').strip()
    if not question:
        return {'intent': 'open_data_query', 'columns': [], 'rows': [], 'note': '질문을 입력해주세요.'}

    tables = _discover_csv_tables()
    tables.update(_discover_json_tables())
    # 화면 UI(pages/*.py)가 역할별로 가리는 평가등급/인센티브/코멘트/리더십·
    # 승계 데이터를, 이 개방형 SQL 질의로 우회 조회하지 못하도록 현재 사용자
    # 권한에 없는 테이블은 아예 스키마/조회 대상에서 제외한다 — LLM은 이
    # 테이블이 있다는 것 자체를 모르게 된다.
    tables = auth.filter_permitted_tables(tables)
    if not tables:
        return {'intent': 'open_data_query', 'columns': [], 'rows': [],
                'note': '조회할 데이터가 없습니다(data/processed/에 CSV가 없음).'}

    schema = _schema_prompt(tables)
    max_wait = llm_client.query_max_wait()
    gen = _generate_sql(question, schema, max_wait, current_only=current_only, period=period)
    if gen is None:
        return {'intent': 'open_data_query', 'columns': [], 'rows': [],
                'note': '지금 요청이 많거나 질문을 조회문으로 바꾸지 못했습니다. '
                        '잠시 후 다시 시도하거나 다르게 질문해주세요.'}

    import duckdb

    # enable_external_access=False: text2sql.sanitize_sql()은 PostgreSQL 방언
    # 기준으로 만들어져 read_csv/read_parquet/glob/ATTACH/PRAGMA/INSTALL 같은
    # DuckDB 전용 파일시스템·네트워크 접근 함수를 막지 못한다(예:
    # "SELECT * FROM read_csv('/etc/passwd')"가 그대로 통과함) — LLM이 생성한
    # SQL을 그대로 실행하는 구조라, 질문(프롬프트 인젝션 포함)을 통해 이 함수들이
    # 유도될 경우 임의 로컬 파일 읽기로 이어질 수 있어 DuckDB 레벨에서 외부
    # 접근 자체를 차단한다.
    con = duckdb.connect(':memory:', config={'enable_external_access': False})
    try:
        con.execute(f"SET memory_limit='{int(os.environ.get('DUCKDB_MEMORY_LIMIT_MB', '512'))}MB'")
        con.execute(f"SET threads={int(os.environ.get('DUCKDB_THREADS', '2'))}")
        for name, df in tables.items():
            con.register(name, df)

        columns, rows = None, None
        safe_sql, last_error = None, None
        for attempt in range(2):
            try:
                safe_sql = text2sql.sanitize_sql(_cap_limit(gen['sql']))
            except text2sql.Text2SQLError as exc:
                safe_sql = None
                last_error = f'생성된 조회문이 허용되지 않습니다: {exc}'
            else:
                try:
                    columns, rows = _execute(con, safe_sql)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = f'조회 중 오류가 발생했습니다: {str(exc)[:200]}'

            if attempt == 1:
                break
            # self-repair: 실패한 SQL과 에러를 LLM에 주고 한 번만 재생성
            repaired = _generate_sql_repair(
                question, schema, max_wait, current_only, gen['sql'], last_error, period=period,
            )
            if repaired is None:
                break
            gen = repaired

        if rows is None:
            return {'intent': 'open_data_query', 'columns': [], 'rows': [],
                    'sql': safe_sql or gen['sql'], 'note': last_error}

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
