"""
핵심기술 처리 모듈

원천 파일: data/raw/핵심기술.xlsx
출력 파일: data/processed/core_technology.csv

읽는 컬럼:
  사원번호, 기술 분야, 핵심기술, 등급

출력 스키마:
  researcher_id, tech_field, tech_name, tech_grade

등급(tech_grade) 값이 없으면 '-'로 표기합니다.

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import csv
import os
import sys

import pandas as pd

CORE_TECH_FILE = '핵심기술.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID    = '사원번호'
COL_FIELD = '기술 분야'
COL_NAME  = '핵심기술'
COL_GRADE = '등급'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import read_xlsx, norm_id


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, CORE_TECH_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {CORE_TECH_FILE} 파일 없음 — core_technology_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_core_technology.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    def _col(name):
        if name not in df.columns:
            return pd.Series('', index=df.index)
        s = df[name]
        return s.where(~s.isna(), '').astype(str).str.strip()

    result = pd.DataFrame({
        'researcher_id': df['researcher_id'],
        'tech_field':    _col(COL_FIELD),
        'tech_name':     _col(COL_NAME),
        'tech_grade':    _col(COL_GRADE),
    })
    result = result.replace({'nan': '', 'None': ''})
    result.loc[result['tech_grade'] == '', 'tech_grade'] = '-'
    result = result.sort_values(['researcher_id']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'core_technology.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n = result['researcher_id'].nunique()
    print(f'[OK]   core_technology.csv 저장 ({len(result)}행, {n}명)')
    return True


if __name__ == '__main__':
    process()
