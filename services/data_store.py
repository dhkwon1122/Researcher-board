import json
import os

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'processed')
RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw')
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')


def processed_path(name: str) -> str:
    return os.path.join(DATA_DIR, f'{name}.csv')


def raw_path(filename: str) -> str:
    return os.path.join(RAW_DIR, filename)


def _read_from_db(name: str) -> pd.DataFrame | None:
    """DB가 설정돼 있으면 테이블을 읽어 반환. 미설정·오류 시 None (→ CSV 폴백)."""
    from services.db import get_engine

    engine = get_engine()
    if engine is None:
        return None
    try:
        # 모든 컬럼을 문자열로 읽어 CSV(dtype=str) 동작과 일치시킴
        df = pd.read_sql_query(f'SELECT * FROM {name}', engine, dtype=str)
        return df.fillna('')
    except Exception:
        # 테이블이 없거나 조회 실패 → CSV 폴백
        return None


def read_processed(name: str, *, dtype: dict | str | None = None) -> pd.DataFrame:
    df = _read_from_db(name)
    if df is None:
        path = processed_path(name)
        if not os.path.exists(path):
            return pd.DataFrame()
        read_dtype = dtype if dtype is not None else {'researcher_id': str}
        try:
            df = pd.read_csv(path, encoding='utf-8-sig', dtype=read_dtype)
        except Exception:
            return pd.DataFrame()
    if 'researcher_id' in df.columns:
        df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def read_expertise_profiles() -> dict[str, dict]:
    """researcher_id -> 연구원 보유 전문성 분석.json 항목(dict) 매핑. 파일이
    없으면(파이프라인 미실행) 빈 dict — 호출부가 '분석 데이터 없음'으로 처리한다."""
    path = os.path.join(DATA_DIR, '연구원 보유 전문성 분석.json')
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        profiles = json.load(f)
    return {p.get('researcher_id', ''): p for p in profiles}


def read_similar_researchers() -> dict[str, dict]:
    """researcher_id -> researcher_similarity.json 항목(dict, 'similar' 리스트
    포함) 매핑. 파일이 없으면(process_researcher_similarity.py 미실행) 빈 dict."""
    path = os.path.join(DATA_DIR, 'researcher_similarity.json')
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        results = json.load(f)
    return {item.get('researcher_id', ''): item for item in results}


def read_profile_tables() -> dict[str, pd.DataFrame]:
    names = [
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
        'hr_orders',
        'core_technology',
        'tech_ownership',
        'job_profile',
    ]
    return {name: read_processed(name) for name in names}
