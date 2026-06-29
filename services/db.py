"""
PostgreSQL 접속 계층.

DATABASE_URL 환경변수가 설정돼 있으면 SQLAlchemy Engine을 만들어 반환하고,
없으면 None을 반환한다. 호출부(data_store, comments)는 None이면 CSV로 폴백한다.

예) DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/researcher_board
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import Engine
except Exception:  # sqlalchemy 미설치 환경
    create_engine = None
    Engine = None

_engine = None
_initialized = False


def get_engine():
    """DATABASE_URL이 있으면 SQLAlchemy Engine을, 없으면 None을 반환 (싱글턴)."""
    global _engine, _initialized
    if _initialized:
        return _engine
    _initialized = True

    url = os.environ.get('DATABASE_URL', '').strip()
    if not url or create_engine is None:
        _engine = None
        return None
    try:
        _engine = create_engine(url, pool_pre_ping=True, future=True)
    except Exception as exc:  # 잘못된 URL 등
        print(f'[db] Engine 생성 실패, CSV로 폴백: {exc}')
        _engine = None
    return _engine


def db_enabled() -> bool:
    """DB 백엔드 사용 가능 여부."""
    return get_engine() is not None
