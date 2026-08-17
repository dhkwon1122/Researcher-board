"""
SQL 안전 검증 유틸리티.

원래는 "연구원 목록" 탭의 자체 AI 검색(자연어 → 로컬 LLM이 PostgreSQL SELECT
생성 → 여기서 안전 검증 → 실행) 전용 모듈이었다. 그 페이지 전용 기능은 전
탭 공용 자연어 질문 바(components/nl_query_bar.py, services/nl_query.py)로
대체되며 삭제됐고(data/processed/CLAUDE.md 참고), 지금은 그때 만든 SQL 안전
검증 로직(sanitize_sql, DB 방언과 무관한 순수 문자열 검증)만
services/open_data_query.py(DuckDB 기반 개방형 질의)가 재사용한다.

보안 (LLM 이 만든 SQL 을 실행하므로 다층 방어):
  1) 화이트리스트: SELECT / WITH 로 시작하는 단일 문장만
  2) 블랙리스트: 쓰기/DDL/권한/시스템 함수 키워드 차단 (문자열 리터럴 제외 후 스캔)
  3) 다중 문장(;)·SQL 주석(--,/*) 차단
  4) LIMIT 자동 부착
이 검증은 PostgreSQL 방언 기준으로 만들어졌다 — DuckDB에서 재사용하는 쪽
(open_data_query.py)은 DuckDB 전용 파일시스템/네트워크 접근 함수(read_csv 등)까지
막기 위해 duckdb.connect(config={'enable_external_access': False})를 추가로 적용한다.
"""

import re

DEFAULT_LIMIT = 200

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
