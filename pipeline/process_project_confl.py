"""
과제별 컨플루언스 주소 처리 모듈

원천: source_reader.read_source('project_confl_address')
  → DB project_confl_address_stg 테이블 또는 data/raw_csv/project_confl_address.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/과제별컨플.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/project_confl_address.csv

읽는 컬럼:
  소속, 과제명, 컨플 주소

처리:
  - xlsx를 CSV로 변환합니다(추가 가공 없음).

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, read_xlsx
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source

SOURCE_FILE = '과제별컨플.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_DEP = '소속'
COL_PROJECT = '과제명'
COL_CONFL = '컨플 주소'
# ─────────────────────────────────────────────────────────────────────────────


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('project_confl_address')
        if df is None:
            print('[SKIP] project_confl_address 원천 데이터 없음 '
                  '(DB project_confl_address_stg 또는 data/raw_csv/project_confl_address.csv)')
            return False
    else:
        raw_path = os.path.join(raw_dir, SOURCE_FILE)
        if not os.path.exists(raw_path):
            print(f'[SKIP] {SOURCE_FILE} 파일 없음')
            return False
        df = read_xlsx(raw_path)

    df.columns = [str(c).strip() for c in df.columns]

    for col in (COL_DEP, COL_PROJECT, COL_CONFL):
        if col not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{col}]\n'
                f'  process_project_confl.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    result = pd.DataFrame({
        'dep_name': df[COL_DEP].apply(_clean),
        'project_name': df[COL_PROJECT].apply(_clean),
        'confl_address': df[COL_CONFL].apply(_clean),
    })
    result = result[result['project_name'] != ''].reset_index(drop=True)

    out_path = os.path.join(OUT_DIR, 'project_confl_address.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['project_confl_address'])

    print(f'[OK]   project_confl_address.csv 저장 (총 {len(merged)}행, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
