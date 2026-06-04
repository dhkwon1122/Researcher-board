"""
T&P 기본 인사 정보 파일에서 연봉등급(평가)·이름·성별·생년월일을 추출

원천 파일 위치: data/raw/T&P_기본_인사_정보.xlsx

추출 항목:
  - evaluations.csv : 2024/2025/2026 연봉등급 → 가/나/다/라/마 + 환산 점수
  - researchers     : 이름, 성별, 생년월일(출생연도) → 반환 DataFrame으로 제공
                      (호출자가 기존 researchers DataFrame에 병합)

등급 체계: 가(최우수) > 나 > 다 > 라 > 마(최하)
"""

import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

# ── 설정 (사내 파일 구조에 맞게 수정) ────────────────────────────────────────

# 연구원 식별 컬럼 (사번, 직원번호, EMP_ID 등)
ID_COL = '사번'

# 기본 인사 정보 컬럼 — 파일에 없으면 해당 필드만 건너뜀
NAME_COL   = '이름'
GENDER_COL = '성별'
BIRTH_COL  = '생년월일'   # YYYYMMDD, YYYY-MM-DD, datetime 모두 지원

# 연도별 연봉등급 컬럼명
GRADE_COLS = {
    2024: '2024 연봉등급',
    2025: '2025 연봉등급',
    2026: '2026 연봉등급',
}

# 등급 → 점수 환산 (대시보드 수치 표현용)
GRADE_TO_SCORE = {
    '가': 95,
    '나': 85,
    '다': 75,
    '라': 65,
    '마': 55,
}

# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx

TP_FILE = 'T&P_기본_인사_정보.xlsx'


def _parse_birth_year(val) -> int | None:
    """생년월일 값에서 출생연도(int)를 추출합니다."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    val_str = str(val).strip()
    if val_str in ('', 'nan', 'None', 'NaT'):
        return None
    # YYYYMMDD 또는 YYYY-MM-DD 형식: 앞 4자리가 숫자이면 연도
    if len(val_str) >= 4 and val_str[:4].isdigit():
        year = int(val_str[:4])
        if 1900 < year <= 2010:   # 합리적인 출생연도 범위
            return year
    # pandas datetime 파싱 시도
    try:
        return int(pd.to_datetime(val_str).year)
    except Exception:
        return None


def process():
    """
    T&P 파일을 읽어 evaluations.csv를 저장하고,
    이름·성별·생년월일 정보를 담은 DataFrame을 반환합니다.

    Returns:
        (success: bool, researcher_updates: pd.DataFrame | None)
        researcher_updates 컬럼: researcher_id, name, gender, birth_year
        (추출되지 않은 컬럼은 포함되지 않을 수 있음)
    """
    raw_path = os.path.join(RAW_DIR, TP_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {raw_path} 파일 없음')
        return False, None

    print(f'[READ] {TP_FILE} (xlwings)')
    df = read_xlsx(raw_path)

    if df.empty:
        print('[SKIP] 파일 읽기 결과가 비어 있습니다.')
        return False, None

    # ID 컬럼 존재 확인
    if ID_COL not in df.columns:
        sample = ', '.join(f'"{c}"' for c in list(df.columns)[:15])
        raise ValueError(
            f"\n[오류] ID_COL='{ID_COL}' 컬럼이 파일에 없습니다.\n"
            f"파일의 컬럼(앞 15개): {sample}\n"
            f"→ process_tp_evaluation.py 상단의 ID_COL 변수를 실제 컬럼명으로 수정하세요."
        )

    # 연구원 ID → 8자리 텍스트로 정규화
    # Excel이 사번을 숫자로 읽으면 12345.0 형태가 되므로 int 변환 후 zfill 처리
    def _norm_id(val):
        s = str(val).strip()
        if s in ('', 'nan', 'None', 'NaT'):
            return ''
        try:
            return str(int(float(s))).zfill(8)
        except (ValueError, OverflowError):
            return s.zfill(8)

    df['_rid'] = df[ID_COL].apply(_norm_id)
    df = df[df['_rid'] != '']   # 빈 ID 행 제거

    # ── 1. 기본 인사 정보 추출 ────────────────────────────────────────────────
    res_update = pd.DataFrame({'researcher_id': df['_rid']})
    extracted_fields = []

    if NAME_COL in df.columns:
        res_update['name'] = df[NAME_COL].astype(str).str.strip()
        extracted_fields.append('이름')

    if GENDER_COL in df.columns:
        res_update['gender'] = df[GENDER_COL].astype(str).str.strip()
        extracted_fields.append('성별')

    if BIRTH_COL in df.columns:
        res_update['birth_year'] = df[BIRTH_COL].apply(_parse_birth_year)
        extracted_fields.append('생년월일→출생연도')

    if extracted_fields:
        print(f'[OK]   기본 인사 정보 추출: {", ".join(extracted_fields)} ({len(res_update)}명)')
    else:
        print('  [INFO] 이름/성별/생년월일 컬럼을 찾지 못했습니다.')
        res_update = None

    # ── 2. 연봉등급(평가) 추출 ───────────────────────────────────────────────
    rows = []
    for year, col_name in GRADE_COLS.items():
        if col_name not in df.columns:
            print(f'  [WARN] "{col_name}" 컬럼 없음 — {year}년 데이터 건너뜀')
            continue

        year_df = df[['_rid', col_name]].copy()
        year_df.columns = ['researcher_id', 'grade']
        year_df['grade'] = year_df['grade'].astype(str).str.strip()

        valid = year_df['grade'].isin(GRADE_TO_SCORE)
        skipped = (~valid & year_df['grade'].notna() & (year_df['grade'] != 'nan')).sum()
        if skipped:
            print(f'  [WARN] {year}년 — 유효하지 않은 등급 {skipped}건 제외 '
                  f'(허용값: {list(GRADE_TO_SCORE)})')

        year_df = year_df[valid].copy()
        year_df['year'] = year
        year_df['score'] = year_df['grade'].map(GRADE_TO_SCORE)
        rows.append(year_df[['researcher_id', 'year', 'grade', 'score']])

    if not rows:
        print('[SKIP] 추출된 평가 데이터가 없습니다.')
        return False, res_update

    result = pd.concat(rows, ignore_index=True)
    result = result.sort_values(['researcher_id', 'year']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'evaluations.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig')

    total_researchers = result['researcher_id'].nunique()
    print(f'[OK]   evaluations.csv 저장 ({len(result)}행, {total_researchers}명)')
    for year, grp in result.groupby('year'):
        dist = grp['grade'].value_counts().sort_index().to_dict()
        print(f'         {year}년 등급 분포: {dist}')

    return True, res_update


if __name__ == '__main__':
    process()
