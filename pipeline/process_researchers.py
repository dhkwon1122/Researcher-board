"""
연구원 기본 정보 처리 모듈

원천 파일: data/raw/인력현황.xlsx
출력 파일: data/processed/researchers.csv

읽는 컬럼:
  사원번호, 성명, 현소속부서명, CL, 비공식소속부서명, 직무,
  국적, 근속기준일_그룹입사일, 법적생년월일성별, 성별,
  승격산정기준일자, Knox ID

계산 항목:
  birth_year    : 법적생년월일성별 앞 4자리
  age           : 올해연도 - birth_year  (표시 전용, CSV에는 저장 안 함)
  hire_date     : 근속기준일_그룹입사일 (YYYY-MM-DD)
  tenure        : (오늘 - hire_date).days / 365, 소수 첫째자리 (표시 전용)
  promotion_date: 승격산정기준일자 (YYYY-MM-DD)
  position_year : ceil((2027-03-01 - promotion_date).days / 365) (표시 전용)

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import csv
import math
import os
import sys
from datetime import date, datetime

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

RESEARCHERS_FILE = '인력현황.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID         = '사원번호'
COL_NAME       = '성명'
COL_DEPT       = '현소속부서명'
COL_POSITION   = 'CL'
COL_ORG        = '비공식소속부서명'
COL_JOB        = '직무'
COL_NATION     = '국적'
COL_HIRE_DATE  = '근속기준일_그룹입사일'
COL_BIRTH_SEX  = '법적생년월일성별'
COL_GENDER     = '성별'
COL_PROMO_DATE = '승격산정기준일자'
COL_KNOX       = 'Knox ID'
# 직급연차 기준일 (2027-03-01)
POSITION_YEAR_REF = date(2027, 3, 1)
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id


def _parse_date(val) -> date | None:
    """날짜 셀을 date 객체로 변환. 실패 시 None."""
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    s = str(val).strip()
    if s in ('', 'nan', 'None', 'NaT'):
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _date_str(d: date | None) -> str:
    return d.strftime('%Y-%m-%d') if d else ''


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, RESEARCHERS_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {RESEARCHERS_FILE} 파일 없음 — researchers_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    # 컬럼명 좌우 공백 제거 (탭 포함)
    df.columns = [str(c).strip() for c in df.columns]

    required = [COL_ID, COL_NAME]
    for col in required:
        if col not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{col}]\n'
                f'  process_researchers.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    today = date.today()
    rows = []
    for _, row in df.iterrows():
        rid = norm_id(row.get(COL_ID))
        if not rid:
            continue

        # 생년 & 성별: 앞 두 자리가 연도 (26 이상 → 1900+, 26 미만 → 2000+)
        birth_sex = str(row.get(COL_BIRTH_SEX, '')).strip()
        birth_year = ''
        if len(birth_sex) >= 2:
            try:
                yy = int(birth_sex[:2])
                birth_year = (1900 + yy) if yy >= 26 else (2000 + yy)
            except ValueError:
                pass

        # 입사일 (근속기준일)
        hire_dt = _parse_date(row.get(COL_HIRE_DATE))

        # 승격산정기준일
        promo_dt = _parse_date(row.get(COL_PROMO_DATE))

        rows.append({
            'researcher_id':   rid,
            'name':            str(row.get(COL_NAME, '')).strip(),
            'department':      str(row.get(COL_DEPT, '')).strip(),
            'org_code':        str(row.get(COL_ORG, '')).strip(),
            'position':        str(row.get(COL_POSITION, '')).strip(),
            'job_function':    str(row.get(COL_JOB, '')).strip(),
            'nationality':     str(row.get(COL_NATION, '')).strip(),
            'gender':          str(row.get(COL_GENDER, '')).strip(),
            'birth_year':      birth_year,
            'hire_date':       _date_str(hire_dt),
            'promotion_date':  _date_str(promo_dt),
            'knox_id':         str(row.get(COL_KNOX, '')).strip(),
        })

    result = pd.DataFrame(rows)
    result = result[result['researcher_id'] != ''].reset_index(drop=True)
    result = result.sort_values('researcher_id').reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'researchers.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    print(f'[OK]   researchers.csv 저장 ({len(result)}명)')
    return True


if __name__ == '__main__':
    process()
