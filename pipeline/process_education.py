"""
학력 처리 모듈

원천 파일: data/raw/임직원_학력.xlsx
출력 파일: data/processed/education.csv

읽는 컬럼:
  사번, 학력, 학교명, 전공, 학위 취득 연도, 졸업일

학위 구분 (다양한 표기를 아래 5가지로 통일):
  박사  : 박사, Doctoral, PhD, Doctor 등
  석사  : 석사, Master, M.S., MBA 등
  학사  : 학사, Bachelor, B.S. 등
  전문대: 전문대, 전문학사, Associate 등
  고교  : 고교, 고등학교, High School 등

※ 연구원별 학사·석사·박사 학력이 있으면 고교·전문대는 제외

컬럼명 설정은 파일 상단의 COL_* 상수에서 수정하세요.
"""

import csv
import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

EDUCATION_FILE = '임직원_학력.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID        = '사번'
COL_DEGREE    = '학력'
COL_SCHOOL    = '학교명'
COL_MAJOR     = '전공'
COL_GRAD_YEAR = '학위 취득 연도'
COL_GRAD_DATE = '졸업일'
# ─────────────────────────────────────────────────────────────────────────────

# 학위 통일 매핑: (소문자 포함 키워드 목록, 표준 학위명) 순서 중요 — 박사를 먼저 검사
DEGREE_MAP = [
    (['박사', 'doctoral', 'phd', 'ph.d', 'doctor', 'd.sc', 'dsc', '공학박사', '이학박사', '문학박사'], '박사'),
    (['석사', 'master', 'm.s', 'm.a', 'm.eng', 'm.sc', 'msc', 'mba', '공학석사', '이학석사'], '석사'),
    (['학사', 'bachelor', 'b.s', 'b.a', 'b.eng', 'b.sc', 'bsc', '공학학사', '이학학사'], '학사'),
    (['전문대', '전문학사', 'associate', '전문'], '전문대'),
    (['고교', '고등학교', '고졸', 'high school', 'highschool', '고등학교졸업'], '고교'),
]

HIGHER_DEGREES = {'박사', '석사', '학사'}
DEG_ORDER = {'박사': 0, '석사': 1, '학사': 2, '전문대': 3, '고교': 4}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id


def _normalize_degree(val: str) -> str:
    v = str(val).strip().lower()
    for keywords, standard in DEGREE_MAP:
        for kw in keywords:
            if kw in v:
                return standard
    return str(val).strip()


def _extract_year(year_val, date_val) -> str:
    """학위 취득 연도 우선, 없으면 졸업일에서 연도 추출."""
    for v in (year_val, date_val):
        s = str(v).strip()
        if s in ('', 'nan', 'None', 'NaT', 'NaN'):
            continue
        try:
            y = int(float(s))
            if 1900 <= y <= 2100:
                return str(y)
        except (ValueError, OverflowError):
            pass
        try:
            return pd.to_datetime(s).strftime('%Y')
        except Exception:
            pass
    return ''


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, EDUCATION_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {EDUCATION_FILE} 파일 없음 — education_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_education.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    df['_degree_std'] = _col(COL_DEGREE).apply(_normalize_degree)

    yr_series   = df[COL_GRAD_YEAR] if COL_GRAD_YEAR in df.columns else pd.Series('', index=df.index)
    date_series = df[COL_GRAD_DATE] if COL_GRAD_DATE in df.columns else pd.Series('', index=df.index)
    df['_grad_year'] = [_extract_year(y, d) for y, d in zip(yr_series, date_series)]

    rows = []
    for rid, grp in df.groupby('researcher_id'):
        has_higher    = grp['_degree_std'].isin(HIGHER_DEGREES).any()
        has_associate = (grp['_degree_std'] == '전문대').any()
        for _, row in grp.iterrows():
            deg = row['_degree_std']
            # 학사 이상이 있으면 전문대·고교 제외
            if has_higher and deg in ('고교', '전문대'):
                continue
            # 전문대가 있으면 고교 제외 (전문대가 최종학력인 경우에만 전문대 표시)
            if has_associate and deg == '고교':
                continue
            school = str(row.get(COL_SCHOOL, '')).strip() if COL_SCHOOL in df.columns else ''
            major  = str(row.get(COL_MAJOR,  '')).strip() if COL_MAJOR  in df.columns else ''
            rows.append({
                'researcher_id':   rid,
                'degree':          deg,
                'school':          school if school not in ('nan', 'None') else '',
                'major':           major  if major  not in ('nan', 'None') else '',
                'graduation_year': row['_grad_year'],
            })

    result = pd.DataFrame(rows, columns=['researcher_id', 'degree', 'school', 'major', 'graduation_year'])
    result['_ord'] = result['degree'].map(DEG_ORDER).fillna(5)
    result = (result
              .sort_values(['researcher_id', '_ord'])
              .drop(columns=['_ord'])
              .reset_index(drop=True))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'education.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n = result['researcher_id'].nunique()
    print(f'[OK]   education.csv 저장 ({len(result)}행, {n}명)')
    return True


if __name__ == '__main__':
    process()
