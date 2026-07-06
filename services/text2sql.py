"""
Text2SQL: 자연어 질문 → 로컬 LLM 이 PostgreSQL SELECT 생성 → 안전 검증 후 실행.

보안 (LLM 이 만든 SQL 을 DB 에 실행하므로 다층 방어):
  1) 화이트리스트: SELECT / WITH 로 시작하는 단일 문장만
  2) 블랙리스트: 쓰기/DDL/권한/시스템 함수 키워드 차단 (문자열 리터럴 제외 후 스캔)
  3) 다중 문장(;)·SQL 주석(--,/*) 차단
  4) LIMIT 자동 부착 + statement_timeout + read-only 트랜잭션
권장: DB 에 SELECT 전용 read-only 롤을 부여(문서 참고).
"""

import re

from services.db import get_engine
from services.llm import chat, LLMError

DEFAULT_LIMIT = 200
STATEMENT_TIMEOUT_MS = 10_000

# 문자열 리터럴 제거 후 스캔할 금지 토큰 (쓰기/DDL/권한/세션/시스템 함수)
_FORBIDDEN = re.compile(
    r'\b('
    r'insert|update|delete|drop|alter|truncate|create|grant|revoke|merge|'
    r'call|copy|vacuum|analyze|reindex|cluster|comment|security|lock|listen|'
    r'notify|prepare|execute|set|reset|begin|commit|rollback|savepoint|into|'
    r'nextval|setval|currval|dblink|current_setting|set_config|'
    r'information_schema'
    r')\b'
    r'|pg_[a-z_]+'
    r'|lo_[a-z]+',
    re.IGNORECASE,
)

# 문자열 리터럴 '...' ('' 이스케이프 포함) 을 제거하는 패턴
_STRLIT = re.compile(r"'(?:[^']|'')*'")


class Text2SQLError(RuntimeError):
    """검증 실패 등 사용자에게 안내할 오류."""


def build_schema_prompt(engine) -> str:
    """information_schema 로 public 스키마의 실제 테이블·컬럼을 읽어 프롬프트 텍스트 생성."""
    from sqlalchemy import text

    q = text(
        "SELECT table_name, column_name "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position"
    )
    tables: dict[str, list[str]] = {}
    with engine.connect() as conn:
        for tname, cname in conn.execute(q):
            tables.setdefault(tname, []).append(cname)

    lines = [f'{t}({", ".join(cols)})' for t, cols in tables.items()]
    return '\n'.join(lines)


def _extract_sql(raw: str) -> str:
    """LLM 응답에서 코드펜스/설명을 걷어내고 SELECT/WITH 이후만 취한다."""
    txt = re.sub(r'```(?:sql)?', '', raw, flags=re.IGNORECASE).replace('```', '').strip()
    m = re.search(r'\b(with|select)\b', txt, flags=re.IGNORECASE)
    if m:
        txt = txt[m.start():]
    return txt.strip().rstrip(';').strip()


def generate_sql(question: str, schema: str) -> str:
    """스키마 + 질문 → LLM → SQL 문자열."""
    system = (
        'You are a PostgreSQL expert. Convert the user question into ONE read-only '
        'SQL SELECT query. Rules:\n'
        '- Use ONLY the given tables and columns.\n'
        '- Output ONLY the SQL, no explanation, no markdown fences.\n'
        '- Single statement, must start with SELECT or WITH.\n'
        '- Never write/modify data (no INSERT/UPDATE/DELETE/DDL).\n'
        '- IMPORTANT: every column is stored as TEXT. Cast before numeric/date '
        'comparison or aggregation, e.g. CAST(col AS INTEGER), CAST(col AS FLOAT).\n'
        '- Join tables on researcher_id when combining data.\n'
        f'\nSchema (all columns are text):\n{schema}'
    )
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': question},
    ]
    raw = chat(messages, temperature=0.0, max_tokens=512)
    sql = _extract_sql(raw)
    if not sql:
        raise Text2SQLError('LLM 이 SQL 을 생성하지 못했습니다. 질문을 더 구체적으로 적어보세요.')
    return sql


def sanitize_sql(sql: str) -> str:
    """검증 통과 시 실행 가능한 SQL(문자열) 반환, 아니면 Text2SQLError."""
    work = sql.strip().rstrip(';').strip()
    if not work:
        raise Text2SQLError('빈 SQL 입니다.')

    # SQL 주석 차단(주석을 이용한 우회 방지)
    if '--' in work or '/*' in work:
        raise Text2SQLError('SQL 주석은 허용되지 않습니다.')

    # 다중 문장 차단 (문자열 리터럴 제거 후 세미콜론 검사)
    scan = _STRLIT.sub("''", work)
    if ';' in scan:
        raise Text2SQLError('여러 개의 SQL 문장은 허용되지 않습니다.')

    # SELECT / WITH 로 시작만 허용
    if not re.match(r'^(select|with)\b', scan, flags=re.IGNORECASE):
        raise Text2SQLError('SELECT 조회 쿼리만 실행할 수 있습니다.')

    # 금지 키워드/시스템 함수 차단
    m = _FORBIDDEN.search(scan)
    if m:
        raise Text2SQLError(f'허용되지 않는 키워드가 포함돼 있습니다: {m.group(0)}')

    # LIMIT 자동 부착
    if not re.search(r'\blimit\b', scan, flags=re.IGNORECASE):
        work = f'{work} LIMIT {DEFAULT_LIMIT}'

    return work


def run_query(question: str) -> dict:
    """
    자연어 질문 → 결과 dict:
      {'sql': str|None, 'columns': list, 'rows': list[list], 'error': str|None}
    """
    from sqlalchemy import text

    engine = get_engine()
    if engine is None:
        return {'sql': None, 'columns': [], 'rows': [],
                'error': '이 기능은 PostgreSQL 연결이 필요합니다. DATABASE_URL 을 설정하세요.'}

    q = (question or '').strip()
    if not q:
        return {'sql': None, 'columns': [], 'rows': [], 'error': '질문을 입력하세요.'}

    # 1) 스키마 + LLM 으로 SQL 생성
    try:
        schema = build_schema_prompt(engine)
    except Exception as exc:  # noqa: BLE001
        return {'sql': None, 'columns': [], 'rows': [],
                'error': f'스키마 조회 실패: {exc}'}
    try:
        raw_sql = generate_sql(q, schema)
    except LLMError as exc:
        return {'sql': None, 'columns': [], 'rows': [], 'error': str(exc)}
    except Text2SQLError as exc:
        return {'sql': None, 'columns': [], 'rows': [], 'error': str(exc)}

    # 2) 안전 검증
    try:
        safe_sql = sanitize_sql(raw_sql)
    except Text2SQLError as exc:
        return {'sql': raw_sql, 'columns': [], 'rows': [], 'error': str(exc)}

    # 3) read-only 트랜잭션 + timeout 실행
    try:
        with engine.begin() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))
            result = conn.execute(text(safe_sql))
            columns = list(result.keys())
            rows = [list(r) for r in result.fetchall()]
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'orig', exc))
        return {'sql': safe_sql, 'columns': [], 'rows': [],
                'error': f'쿼리 실행 오류: {msg[:300]}'}

    return {'sql': safe_sql, 'columns': columns, 'rows': rows, 'error': None}
