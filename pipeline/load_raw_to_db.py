"""
2단계 — raw CSV(DRM 제거된 원본 사본) → PostgreSQL 스테이징 테이블 적재.

1단계(xlsx_to_raw_csv.py, Windows)에서 만든 data/raw_csv/*.csv 를 리눅스 서버로
옮긴 뒤 이 스크립트로 Postgres에 적재한다. 전 컬럼 TEXT, 원본 헤더명 그대로
`{name}_stg` 테이블에 저장한다(가공 없이 원본 스키마 보존 — 매번 replace 하므로
스키마 드리프트 걱정 없이 반복 실행 가능).

사용법:
  export DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/researcher_board
  python pipeline/load_raw_to_db.py

DATABASE_URL 미설정 시 아무 것도 하지 않고 안내만 출력한다 — 이 경우
3단계(process_*.py)는 source_reader.read_source()를 통해 data/raw_csv/*.csv를
직접 읽으므로 DB 없이도 그대로 동작한다.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import SOURCES  # noqa: E402
from services.db import get_engine  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_CSV_DIR = os.path.join(BASE_DIR, 'data', 'raw_csv')


def load():
    engine = get_engine()
    if engine is None:
        print('[load_raw_to_db] DATABASE_URL 미설정 — 적재 건너뜀.')
        print('  process_*.py는 data/raw_csv/*.csv를 직접 읽습니다 (DB 없이도 동작).')
        return

    from sqlalchemy import Text

    loaded = 0
    for name, _filename, _header_row in SOURCES:
        path = os.path.join(RAW_CSV_DIR, f'{name}.csv')
        if not os.path.exists(path):
            print(f'[load_raw_to_db] CSV 없음, 건너뜀: {name}')
            continue
        try:
            df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
        except Exception as exc:
            print(f'[load_raw_to_db] 읽기 실패 {name}: {exc}')
            continue

        table = f'{name}_stg'
        df.to_sql(table, engine, if_exists='replace', index=False,
                  dtype={col: Text() for col in df.columns})
        print(f'[load_raw_to_db] {table}: {len(df)}행 적재 ({len(df.columns)}컬럼)')
        loaded += 1

    print(f'[load_raw_to_db] 완료 — {loaded}개 스테이징 테이블 적재')


if __name__ == '__main__':
    load()
