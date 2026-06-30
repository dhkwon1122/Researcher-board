"""
data/processed/*.csv → PostgreSQL 적재 스크립트.

사용법:
  export DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/researcher_board
  python pipeline/load_to_db.py

동작:
  1) pipeline/schema.sql 실행 (테이블·제약·인덱스 생성, IF NOT EXISTS)
  2) 각 테이블 TRUNCATE 후 해당 CSV를 to_sql(append)로 적재
     (replace 대신 truncate+append → schema.sql 의 제약/인덱스 보존)

DATABASE_URL 미설정 시 아무 것도 하지 않고 안내만 출력.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import get_engine  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'processed')
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
    'nurturing',
    'awards',
    'comments',
    'publications',
    'patents',
    'technology_transfer',
    'certifications',
    'succession',
]


def _apply_schema(engine):
    from sqlalchemy import text
    if not os.path.exists(SCHEMA_SQL):
        print(f'[load_to_db] schema.sql 없음: {SCHEMA_SQL}')
        return
    with open(SCHEMA_SQL, encoding='utf-8') as f:
        ddl = f.read()
    with engine.begin() as conn:
        for stmt in (s.strip() for s in ddl.split(';')):
            if stmt:
                conn.execute(text(stmt))
    print('[load_to_db] schema.sql 적용 완료')


def load():
    engine = get_engine()
    if engine is None:
        print('[load_to_db] DATABASE_URL 미설정 — 적재 건너뜀. '
              '환경변수를 설정하세요.')
        return

    _apply_schema(engine)

    from sqlalchemy import text
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

        with engine.begin() as conn:
            conn.execute(text(f'TRUNCATE TABLE {name}'))
            df.to_sql(name, conn, if_exists='append', index=False)
        print(f'[load_to_db] {name}: {len(df)}행 적재')
        loaded += 1

    print(f'[load_to_db] 완료 — {loaded}개 테이블 적재')


if __name__ == '__main__':
    load()
