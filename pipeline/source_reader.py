"""
3단계 — 후처리(process_*.py)가 원천 데이터를 읽는 단일 진입점.

조회 우선순위:
  1) PostgreSQL 스테이징 테이블 `{name}_stg` (DATABASE_URL 설정 시,
     load_raw_to_db.py가 적재한 테이블)
  2) 로컬 raw CSV data/raw_csv/{name}.csv (1단계 xlsx_to_raw_csv.py 산출물)

둘 다 없으면 None을 반환한다 — 호출부(process_*.py)는 기존과 동일하게
`{name}_raw.xlsx/csv` 폴백 또는 [SKIP] 처리를 이어간다.

xlsx를 직접 열지 않으므로(xlwings 불필요) 리눅스 서버에서도 그대로 동작한다.
반환되는 DataFrame은 전 컬럼 문자열(dtype=str)이며 빈 값은 빈 문자열('')이다.
"""

import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_CSV_DIR = os.path.join(BASE_DIR, 'data', 'raw_csv')

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _read_from_db(name: str) -> pd.DataFrame | None:
    from services.db import get_engine

    engine = get_engine()
    if engine is None:
        return None
    try:
        df = pd.read_sql_query(f'SELECT * FROM {name}_stg', engine, dtype=str)
        return df.fillna('')
    except Exception:
        return None


def read_source(name: str) -> pd.DataFrame | None:
    """원천 스테이징 데이터를 DataFrame으로 반환. 없으면 None."""
    df = _read_from_db(name)
    if df is not None:
        return df

    path = os.path.join(RAW_CSV_DIR, f'{name}.csv')
    if os.path.exists(path):
        try:
            return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
        except Exception:
            return None

    return None
