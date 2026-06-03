"""
전체 데이터 파이프라인 실행 스크립트

사용법:
  python pipeline/run_pipeline.py

data/raw/ 폴더에 아래 파일들을 위치시킨 후 실행하세요.

필수 파일 (xlsx 또는 csv):
  - researchers_raw     : researcher_id, name, department, org_code, position, hire_year, birth_year
  - evaluations_raw     : researcher_id, year, score, grade
  - incentive_raw       : researcher_id, year, selected, category, note
  - publications_raw    : researcher_id, title, journal, pub_year, impact_factor, citation_count, is_corresponding
  - patents_raw         : researcher_id, title, application_no, application_date,
                          registration_no, registration_date, country, status
  - technology_transfer_raw : researcher_id, transfer_date, tech_name, recipient, amount, transfer_type
  - leadership_raw      : researcher_id, year, overall_score, vision, communication,
                          execution, collaboration, development
  - certifications_raw  : researcher_id, cert_type, cert_name, score, grade, date_obtained
  - education_raw       : researcher_id, degree, major, school, graduation_year
  - comments_raw        : researcher_id, year, comment_raw
                          (선택: comment_summary, strengths, improvements)

출력 위치: data/processed/
"""

import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

TABLES = [
    'researchers',
    'evaluations',
    'incentive_selection',
    'publications',
    'patents',
    'technology_transfer',
    'leadership',
    'certifications',
    'education',
]


def _read_raw(name: str) -> pd.DataFrame:
    """xlsx 우선, 없으면 csv 시도."""
    for ext in ('xlsx', 'csv'):
        path = os.path.join(RAW_DIR, f'{name}_raw.{ext}')
        if os.path.exists(path):
            if ext == 'xlsx':
                return pd.read_excel(path)
            return pd.read_csv(path, encoding='utf-8-sig')
    return None


def run():
    os.makedirs(OUT_DIR, exist_ok=True)
    missing = []

    for table in TABLES:
        df = _read_raw(table)
        if df is None:
            missing.append(table)
            print(f'  [SKIP] {table}_raw 파일 없음')
            continue
        out_path = os.path.join(OUT_DIR, f'{table}.csv')
        df.to_csv(out_path, index=False, encoding='utf-8-sig')
        print(f'  [OK]   {table}.csv ({len(df)}행)')

    # 코멘트는 별도 처리 (LLM 요약 포함)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from process_comments import process as process_comments
    process_comments(use_llm=False)

    if missing:
        print(f'\n누락된 원천 파일: {missing}')
        print('개발용 더미 데이터를 사용하려면:  python pipeline/generate_sample_data.py')
    else:
        print('\n파이프라인 완료 — data/processed/ 를 확인하세요.')


if __name__ == '__main__':
    run()
