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


# 테이블 의미(한국어) — 프롬프트에 붙여 모델이 어떤 표인지 알게 한다.
TABLE_HINTS = {
    'researchers': '연구원 기본정보(이름 name, 부서 department, 직급 position, 성별 gender, 생년 birth_year 등)',
    'evaluations': '연도별 인사평가 등급(year, grade)',
    'education': '학력/학위(degree 등)',
    'incentive_selection': '인센티브 선정(year, selected, category)',
    'leadership': '리더십 진단 점수(차원별 점수, overall_score, evaluator_group)',
    'transfers': '인사이동 이력',
    'tasks': '수행 과제',
    'nurturing': '육성 이력',
    'awards': '수상 이력',
    'comments': '평가 코멘트(commenter_type, comment_raw, comment_summary)',
    'publications': '논문(pub_year, impact_factor, citation_count 등)',
    'patents': '특허(status 예: 출원/등록)',
    'technology_transfer': '기술이전',
    'certifications': '자격/어학(cert_name 예: TOEIC, score, date_obtained)',
    'succession': '승계 계획',
}

# 값 예시를 뽑지 않을(자유텍스트/식별자) 컬럼 이름 패턴
_SKIP_SAMPLE = re.compile(
    r'(_id$|^id$|name|title|raw|summary|strengths|improvements|knox|date|url|path)',
    re.IGNORECASE,
)

_schema_cache: str | None = None


def _sample_values(conn, table: str, col: str, cap: int = 15):
    """저低카디널리티 컬럼의 실제 값 목록(<=cap)을 반환. 아니면 None."""
    from sqlalchemy import text
    try:
        rows = conn.execute(text(
            f'SELECT DISTINCT "{col}" FROM "{table}" '
            f'WHERE "{col}" IS NOT NULL AND "{col}" <> \'\' LIMIT {cap + 1}'
        )).fetchall()
    except Exception:
        return None
    vals = [str(r[0]) for r in rows]
    if not vals or len(vals) > cap:
        return None
    return vals


def build_schema_prompt(engine, *, use_cache: bool = True) -> str:
    """실제 테이블·컬럼 + 값 예시 + 테이블 설명으로 풍부한 스키마 프롬프트 생성(세션 캐시)."""
    global _schema_cache
    if use_cache and _schema_cache is not None:
        return _schema_cache

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

        blocks = []
        for t, cols in tables.items():
            hint = TABLE_HINTS.get(t)
            header = f'{t}({", ".join(cols)})'
            if hint:
                header += f'  -- {hint}'
            lines = [header]
            # 저카디널리티 컬럼의 실제 값 예시 (필터 정확도에 큰 도움)
            for c in cols:
                if _SKIP_SAMPLE.search(c):
                    continue
                vals = _sample_values(conn, t, c)
                if vals:
                    shown = ', '.join(vals[:15])
                    lines.append(f'    {c} 값 예: {shown}')
            blocks.append('\n'.join(lines))

    prompt = '\n'.join(blocks)
    _schema_cache = prompt
    return prompt


def _extract_sql(raw: str) -> str:
    """LLM 응답에서 코드펜스/설명을 걷어내고 SELECT/WITH 이후만 취한다."""
    txt = re.sub(r'```(?:sql)?', '', raw, flags=re.IGNORECASE).replace('```', '').strip()
    m = re.search(r'\b(with|select)\b', txt, flags=re.IGNORECASE)
    if m:
        txt = txt[m.start():]
    return txt.strip().rstrip(';').strip()


def _system_prompt(schema: str) -> str:
    return (
        'You are a PostgreSQL expert for a Korean HR/researcher database. '
        'Convert the user question into ONE read-only SQL SELECT query.\n'
        'Rules:\n'
        '- Use ONLY the given tables and columns. Do NOT invent columns.\n'
        '- Output ONLY the SQL. No explanation, no markdown fences, no comments.\n'
        '- Single statement, must start with SELECT or WITH.\n'
        '- Never write/modify data (no INSERT/UPDATE/DELETE/DDL).\n'
        '- EVERY column is stored as TEXT. Cast before numeric/date comparison or '
        'aggregation: CAST(col AS INTEGER), CAST(col AS FLOAT).\n'
        '- All tables join on researcher_id.\n'
        "- For filters, use the exact literal values shown in '값 예' hints.\n"
        '- UNLESS the user explicitly restricts the columns, ALWAYS include '
        'researchers.researcher_id AS researcher_id and researchers.name AS name '
        'as the FIRST two selected columns for any query that lists individual '
        'researchers (join researchers if needed). For pure aggregates that do not '
        'list individuals (e.g. counts grouped by department), this does not apply.\n'
        f'\nSchema (all columns are TEXT):\n{schema}'
    )


# few-shot: 조인/캐스팅/값 형식을 모델에 학습시킨다
_FEWSHOT = [
    ('AI 부서 연구원 알려줘',
     "SELECT researcher_id, name FROM researchers WHERE department = 'AI'"),
    ('논문이 가장 많은 연구원 5명',
     'SELECT r.researcher_id, r.name, COUNT(*) AS pub_count FROM researchers r '
     'JOIN publications p ON r.researcher_id = p.researcher_id '
     'GROUP BY r.researcher_id, r.name ORDER BY pub_count DESC LIMIT 5'),
    ("2024년 평가등급이 '가'인 연구원",
     "SELECT r.researcher_id, r.name FROM researchers r JOIN evaluations e "
     "ON r.researcher_id = e.researcher_id "
     "WHERE e.year = '2024' AND e.grade = '가'"),
    ('부서별 평균 논문 수',
     'SELECT r.department, AVG(CAST(cnt AS FLOAT)) AS avg_pubs FROM ('
     'SELECT researcher_id, COUNT(*) AS cnt FROM publications GROUP BY researcher_id'
     ') p JOIN researchers r ON r.researcher_id = p.researcher_id '
     'GROUP BY r.department'),
]


def _messages(schema: str, question: str):
    msgs = [{'role': 'system', 'content': _system_prompt(schema)}]
    for q, a in _FEWSHOT:
        msgs.append({'role': 'user', 'content': q})
        msgs.append({'role': 'assistant', 'content': a})
    msgs.append({'role': 'user', 'content': question})
    return msgs


def generate_sql(question: str, schema: str) -> str:
    """스키마 + few-shot + 질문 → LLM → SQL 문자열."""
    raw = chat(_messages(schema, question), temperature=0.0, max_tokens=512)
    sql = _extract_sql(raw)
    if not sql:
        raise Text2SQLError('LLM 이 SQL 을 생성하지 못했습니다. 질문을 더 구체적으로 적어보세요.')
    return sql


def repair_sql(question: str, schema: str, bad_sql: str, error: str) -> str:
    """실행 실패한 SQL 과 에러를 모델에 주고 한 번 고치게 한다."""
    msgs = _messages(schema, question)
    msgs.append({'role': 'assistant', 'content': bad_sql})
    msgs.append({'role': 'user', 'content':
                 f'That SQL failed with error:\n{error}\n'
                 'Return a corrected single SELECT query only.'})
    raw = chat(msgs, temperature=0.0, max_tokens=512)
    sql = _extract_sql(raw)
    if not sql:
        raise Text2SQLError('SQL 재생성 실패.')
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

    # 2) 검증 + 실행 (실패 시 에러를 모델에 주고 1회 재시도)
    last_err = None
    for attempt in range(2):
        try:
            safe_sql = sanitize_sql(raw_sql)
        except Text2SQLError as exc:
            last_err = str(exc)
        else:
            try:
                columns, rows = _execute(engine, safe_sql)
                return {'sql': safe_sql, 'columns': columns, 'rows': rows, 'error': None}
            except Exception as exc:  # noqa: BLE001
                last_err = f'쿼리 실행 오류: {str(getattr(exc, "orig", exc))[:300]}'

        # 마지막 시도였으면 종료
        if attempt == 1:
            break
        # 재생성(self-repair)
        try:
            raw_sql = repair_sql(q, schema, raw_sql, last_err)
        except (LLMError, Text2SQLError):
            break

    return {'sql': raw_sql, 'columns': [], 'rows': [], 'error': last_err}


def _execute(engine, safe_sql: str):
    """read-only 트랜잭션 + statement_timeout 로 실행. (columns, rows) 반환."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text('SET TRANSACTION READ ONLY'))
        conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))
        result = conn.execute(text(safe_sql))
        return list(result.keys()), [list(r) for r in result.fetchall()]
