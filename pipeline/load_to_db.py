"""
data/processed/*.csv + 전문성 관련 JSON → PostgreSQL 적재 스크립트.

사용법:
  export DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/researcher_board
  python pipeline/load_to_db.py

동작:
  1) 각 CSV를 읽어 to_sql(if_exists='replace', 전 컬럼 TEXT)로 적재
     → 테이블이 매번 실제 CSV 컬럼에 맞춰 재생성됨 (스키마 드리프트 방지).
  2) JSON_TABLES에 등록된 JSON 파생 산출물(연구원 보유 전문성 분석.json 등)을
     (키 컬럼 TEXT, data JSONB) 2컬럼 테이블로 적재 — 리스트 필드 등 원본
     구조를 그대로 보존한다(services/data_store.py가 DB 우선/파일 폴백으로
     읽음). strength_taxonomy*.json(사람이 직접 수정하는 파일)과
     researcher_pair_judgment.json/embedding_cache.json(순수 성능 캐시)은
     화면이 직접 조회/검색하는 대상이 아니라서 이관 대상에서 제외했다.
  3) 적재 후 pipeline/schema.sql 실행 (인덱스 + comments 유니크 인덱스).
     replace 가 테이블을 drop 하므로 인덱스는 반드시 적재 '뒤'에 적용.

DATABASE_URL 미설정 시 아무 것도 하지 않고 안내만 출력.
"""

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.db import get_engine  # noqa: E402
from paths import OUT_DIR as DATA_DIR  # noqa: E402

SCHEMA_SQL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')

# read_processed / read_profile_tables 에서 다루는 테이블 전체
TABLES = [
    'researchers',
    'evaluations',
    'education',
    'incentive_selection',
    'leadership',
    'transfers',
    'tasks',
    'tasks_information',
    'nurturing',
    'awards',
    'comments',
    'publications',
    'patents',
    'technology_transfer',
    'certifications',
    'succession',
    'hr_orders',
    'core_technology',
    'tech_ownership',
    'job_profile',
    'project_confl_address',
]

# (테이블명, data/processed/ 안의 JSON 파일명, 각 항목에서 키로 쓸 필드명).
# 파일은 [{...}, {...}, ...] 형태(항목별 dict 리스트)를 가정 — 다른 형식이면
# 건너뛴다. key_field 값이 비어 있는 항목은 제외한다.
JSON_TABLES = [
    ('expertise_profiles', '연구원 보유 전문성 분석.json', 'researcher_id'),
    ('researcher_similarity', 'researcher_similarity.json', 'researcher_id'),
    ('project_expertise_analysis', 'project_expertise_analysis.json', 'project_name'),
]


def _lock_down_file(path: str, name: str) -> None:
    """이 데이터가 DB에도 안전하게 들어갔으니, 서버에 계정이 있는 다른
    사람이 파일을 그냥 열어보지 못하도록 소유자 전용으로 권한을 좁힌다
    (역할별 접근 제어는 화면을 거칠 때만 적용되는 애플리케이션 레벨이라
    파일 자체는 보호하지 않음 — scripts/secure_data_permissions.sh 참고).
    pandas to_csv()/json.dump()의 기본 umask 권한(보통 644)을 여기서 즉시
    덮어써 배포 스크립트 실행을 깜빡해도 최소한의 보호가 남게 한다."""
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        print(f'[load_to_db] 권한 변경 실패(무시하고 계속) {name}: {exc}')


def _load_csv_tables(engine) -> int:
    from sqlalchemy import Text
    loaded = 0
    for name in TABLES:
        path = os.path.join(DATA_DIR, f'{name}.csv')
        if not os.path.exists(path):
            print(f'[load_to_db] CSV 없음, 건너뜀: {name}')
            continue
        try:
            df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
        except Exception as exc:
            print(f'[load_to_db] 읽기 실패 {name}: {exc}')
            continue

        # 전 컬럼 TEXT로 테이블 재생성 → 실제 CSV 컬럼 구성에 자동으로 맞춤
        df.to_sql(name, engine, if_exists='replace', index=False,
                  dtype={col: Text() for col in df.columns})
        print(f'[load_to_db] {name}: {len(df)}행 적재 ({len(df.columns)}컬럼)')
        loaded += 1
        _lock_down_file(path, name)
    return loaded


def _load_json_tables(engine) -> int:
    """JSON_TABLES에 등록된 파일을 (키 컬럼 TEXT, data JSONB) 2컬럼 테이블로
    적재한다 — 리스트 필드 등 원본 구조를 문자열로 뭉개지 않고 그대로 보존."""
    from sqlalchemy import Text
    from sqlalchemy.dialects.postgresql import JSONB

    loaded = 0
    for name, filename, key_field in JSON_TABLES:
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            print(f'[load_to_db] JSON 없음, 건너뜀: {name} ({filename})')
            continue
        try:
            with open(path, encoding='utf-8') as f:
                items = json.load(f)
        except Exception as exc:
            print(f'[load_to_db] 읽기 실패 {name}: {exc}')
            continue
        if not isinstance(items, list):
            print(f'[load_to_db] 예상치 못한 형식(리스트가 아님), 건너뜀: {name}')
            continue

        df = pd.DataFrame({
            key_field: [str(item.get(key_field, '')).strip() for item in items],
            'data': items,
        })
        df = df[df[key_field] != ''].reset_index(drop=True)

        df.to_sql(name, engine, if_exists='replace', index=False,
                  dtype={key_field: Text(), 'data': JSONB()})
        print(f'[load_to_db] {name}: {len(df)}행 적재 (JSONB, 원본 {len(items)}건)')
        loaded += 1
        _lock_down_file(path, name)
    return loaded


def _apply_post_load_ddl(engine):
    """적재 후 인덱스/유니크 인덱스 적용 (schema.sql). 테이블이 이미 존재해야 함."""
    from sqlalchemy import text
    if not os.path.exists(SCHEMA_SQL):
        print(f'[load_to_db] schema.sql 없음, 인덱스 생략: {SCHEMA_SQL}')
        return
    with open(SCHEMA_SQL, encoding='utf-8') as f:
        ddl = f.read()
    # 주석 줄(--)을 먼저 제거 후 ; 로 분할 (주석이 문 앞에 와도 건너뛰지 않도록)
    ddl_clean = '\n'.join(
        ln for ln in ddl.splitlines() if not ln.strip().startswith('--')
    )
    with engine.begin() as conn:
        for stmt in (s.strip() for s in ddl_clean.split(';')):
            if not stmt:
                continue
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                # 인덱스 대상 테이블/컬럼이 없을 수도 있음 → 경고 후 계속
                print(f'[load_to_db] DDL 건너뜀: {exc}')
    print('[load_to_db] 인덱스/유니크 적용 완료')


def load():
    engine = get_engine()
    if engine is None:
        from services.db import ENV_PATH
        url_set = bool(os.environ.get('DATABASE_URL', '').strip())
        print('[load_to_db] DATABASE_URL 미설정 — 적재 건너뜀.')
        print(f'  · .env 경로 확인: {ENV_PATH} '
              f'(존재: {os.path.exists(ENV_PATH)})')
        print(f'  · DATABASE_URL 인식됨: {url_set}')
        print('  점검: 1) 파일명이 정확히 ".env" 인지 (메모장이 ".env.txt"로 '
              '저장하지 않았는지)  2) 파일이 프로젝트 루트에 있는지  '
              '3) pip install -r requirements.txt 실행했는지')
        return

    loaded = _load_csv_tables(engine)
    loaded += _load_json_tables(engine)

    _apply_post_load_ddl(engine)
    print(f'[load_to_db] 완료 — {loaded}개 테이블 적재')


if __name__ == '__main__':
    load()
