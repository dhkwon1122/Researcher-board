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


def _read_json_table_from_db(table: str) -> list[dict] | None:
    """DB가 설정돼 있으면 pipeline/load_to_db.py의 JSON_TABLES가 만든
    (키 TEXT, data JSONB) 테이블에서 data 컬럼 전체를 리스트로 반환.
    미설정·오류·테이블 없음이면 None(→ JSON 파일 폴백) — _read_from_db()와
    동일한 CSV/DB 폴백 원칙을 JSON 파생 테이블에도 그대로 적용한다."""
    from services.db import get_engine

    engine = get_engine()
    if engine is None:
        return None
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(text(f'SELECT data FROM {table}')).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return None


def _read_json_records(table: str, filename: str) -> list:
    """table(DB, JSON_TABLES 산출물) 우선, 없으면 data/processed/filename
    (JSON 배열)을 읽어 항목 리스트로 반환. 둘 다 없으면 빈 리스트."""
    items = _read_json_table_from_db(table)
    if items is not None:
        return items
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def read_expertise_profiles() -> dict[str, dict]:
    """researcher_id -> 연구원 보유 전문성 분석 항목(dict) 매핑. DB(테이블
    expertise_profiles)가 있으면 그걸, 없으면 연구원 보유 전문성 분석.json을
    읽는다. 둘 다 없으면(파이프라인 미실행) 빈 dict — 호출부가 '분석 데이터
    없음'으로 처리한다."""
    profiles = _read_json_records('expertise_profiles', '연구원 보유 전문성 분석.json')
    return {p.get('researcher_id', ''): p for p in profiles}


def read_similar_researchers() -> dict[str, dict]:
    """researcher_id -> researcher_similarity 항목(dict, 'similar' 리스트
    포함) 매핑. DB(테이블 researcher_similarity)가 있으면 그걸, 없으면
    researcher_similarity.json을 읽는다. 둘 다 없으면(process_researcher_
    similarity.py 미실행) 빈 dict."""
    results = _read_json_records('researcher_similarity', 'researcher_similarity.json')
    return {item.get('researcher_id', ''): item for item in results}


def read_project_expertise_analysis() -> list[dict]:
    """과제별 컨플루언스 분석 항목 리스트(project_name 키). DB(테이블
    project_expertise_analysis)가 있으면 그걸, 없으면 project_expertise_
    analysis.json을 읽는다. services.jd_reconciliation.read_confluence_
    summary()가 project_name으로 조회할 때 재사용."""
    return _read_json_records('project_expertise_analysis', 'project_expertise_analysis.json')


def read_strength_taxonomy() -> dict:
    """strength_taxonomy.json(build_strength_taxonomy.py의 2단계 확정 표준
    목록) 그대로 반환. 파일이 없으면(아직 build_strength_taxonomy.py를
    실행/검토하지 않았으면) 빈 dict — 호출부는 표준 목록 없이 원문 매칭만
    수행하는 것으로 폴백해야 한다."""
    path = os.path.join(DATA_DIR, 'strength_taxonomy.json')
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def filter_current(df: pd.DataFrame, current_only: bool = True) -> pd.DataFrame:
    """researchers.csv(또는 이를 기반으로 만든 DataFrame)에서 "현재 소속자만"
    볼지 "누적(한 번이라도 등록된 적 있는 전체 인원)"으로 볼지를 결정한다.

    researchers.csv는 업서트로 적재되어(pipeline/process_researchers.py)
    전배·퇴사 등으로 최신 원본 파일에서 빠진 사람도 삭제되지 않고 남아있다
    — is_current 컬럼이 그 사람이 가장 최근 인원실적월 기준으로도 소속돼
    있었는지(Y) 아닌지(N)를 나타낸다. current_only=True면 is_current=='Y'
    행만, False면 전체(과거에 한 번이라도 있었던 사람 포함)를 반환한다.
    is_current 컬럼이 없으면(구버전 데이터/원본에 인원실적년월 컬럼이 없는
    경우) 판단 근거가 없으므로 필터 없이 그대로 반환한다."""
    if not current_only or 'is_current' not in df.columns or df.empty:
        return df
    return df[df['is_current'] != 'N'].reset_index(drop=True)


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
