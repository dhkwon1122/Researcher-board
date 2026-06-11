import os

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'processed')
RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw')


def processed_path(name: str) -> str:
    return os.path.join(DATA_DIR, f'{name}.csv')


def raw_path(filename: str) -> str:
    return os.path.join(RAW_DIR, filename)


def read_processed(name: str, *, dtype: dict | str | None = None) -> pd.DataFrame:
    path = processed_path(name)
    if not os.path.exists(path):
        return pd.DataFrame()
    read_dtype = dtype if dtype is not None else {'researcher_id': str}
    try:
        df = pd.read_csv(path, encoding='utf-8-sig', dtype=read_dtype)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if 'researcher_id' in df.columns:
        df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def read_profile_tables() -> dict[str, pd.DataFrame]:
    names = [
        'researchers',
        'evaluations',
        'education',
        'incentive_selection',
        'leadership',
        'transfers',
        'nurturing',
        'awards',
        'comments',
        'publications',
        'patents',
        'technology_transfer',
    ]
    return {name: read_processed(name) for name in names}
