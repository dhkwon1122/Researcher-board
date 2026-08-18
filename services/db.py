"""
PostgreSQL 접속 계층.

DATABASE_URL 환경변수(또는 프로젝트 루트의 .env 파일)가 설정돼 있으면
SQLAlchemy Engine을 만들어 반환하고, 없으면 None을 반환한다.
호출부(data_store, comments)는 None이면 CSV로 폴백한다.

예) DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/researcher_board
"""

import os

# 프로젝트 루트 = 이 파일(services/db.py)의 상위 디렉터리
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, '.env')


def load_env_file():
    """
    프로젝트 루트의 .env 를 환경변수로 로드한다. DATABASE_URL 뿐 아니라
    LLM2_*/CONFLUENCE_TOKEN 등(원래 pipeline/llm_config.py라는 별도 파일에
    있던 설정)도 이제 전부 .env 하나로 모여 있어, pipeline/llm_client.py·
    pipeline/confluence_client.py·pipeline/run_ready.py도 이 함수를 그대로
    재사용한다.
    - python-dotenv 가 있으면 그것으로 로드(경로 명시 → 실행 위치 무관).
    - 그와 별개로 최소 파서로도 한 번 더 읽어(패키지 미설치여도 동작하게).
    이미 OS 환경변수로 설정된 값은 덮어쓰지 않는다. 여러 번 호출해도
    안전하다(이미 설정된 키는 다시 안 건드림).
    """
    # 1) python-dotenv 우선
    try:
        from dotenv import load_dotenv
        if os.path.exists(ENV_PATH):
            load_dotenv(ENV_PATH)
        else:
            load_dotenv()  # 혹시 다른 위치에 있으면 탐색
    except Exception:
        pass

    # 2) .env 수동 파싱 (dotenv 미설치 대비 — 이미 설정된 키는 건드리지
    #    않으므로 위 dotenv 로드와 중복 실행해도 안전하다)
    if not os.path.exists(ENV_PATH):
        return
    try:
        with open(ENV_PATH, encoding='utf-8-sig') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


load_env_file()

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
    if not url:
        _engine = None
        return None
    if create_engine is None:
        print('[db] sqlalchemy 미설치 — CSV로 폴백. '
              'pip install -r requirements.txt 를 실행하세요.')
        _engine = None
        return None
    try:
        _engine = create_engine(url, pool_pre_ping=True, future=True,
                                connect_args={'connect_timeout': 5})
    except Exception as exc:  # 잘못된 URL 등
        print(f'[db] Engine 생성 실패, CSV로 폴백: {exc}')
        _engine = None
    return _engine


def db_enabled() -> bool:
    """DB 백엔드 사용 가능 여부."""
    return get_engine() is not None
