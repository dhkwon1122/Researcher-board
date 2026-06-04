"""
T&P 기본 인사 정보 파일에서 연봉등급(평가) 데이터를 추출하여 evaluations.csv 생성

원천 파일 위치: data/raw/T&P_기본_인사_정보.xlsx
필수 컬럼:
  - [ID_COL]       : 연구원 식별자 컬럼 (기본값: '사번', 아래에서 변경 가능)
  - 2024 연봉등급   : 가/나/다/라/마
  - 2025 연봉등급   : 가/나/다/라/마
  - 2026 연봉등급   : 가/나/다/라/마

등급 체계: 가(최우수) > 나 > 다 > 라 > 마(최하)
"""

import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

# ── 설정 (사내 파일 구조에 맞게 수정) ────────────────────────────────────────

# T&P 파일에서 연구원을 식별할 컬럼명
# 예) '사번', '직원번호', 'EMP_ID', '이름' 등 실제 컬럼명으로 변경하세요.
ID_COL = '사번'

# 연도별 연봉등급 컬럼명 (파일의 실제 컬럼명과 정확히 일치해야 합니다)
GRADE_COLS = {
    2024: '2024 연봉등급',
    2025: '2025 연봉등급',
    2026: '2026 연봉등급',
}

# 등급 → 점수 환산 (대시보드 수치 표현용, 필요 시 조정 가능)
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


def process():
    raw_path = os.path.join(RAW_DIR, TP_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {raw_path} 파일 없음')
        return False

    print(f'[READ] {TP_FILE} (xlwings)')
    df = read_xlsx(raw_path)

    if df.empty:
        print('[SKIP] 파일 읽기 결과가 비어 있습니다.')
        return False

    # ID 컬럼 존재 확인
    if ID_COL not in df.columns:
        sample = ', '.join(f'"{c}"' for c in list(df.columns)[:15])
        raise ValueError(
            f"\n[오류] ID_COL='{ID_COL}' 컬럼이 파일에 없습니다.\n"
            f"파일의 컬럼(앞 15개): {sample}\n"
            f"→ process_tp_evaluation.py 상단의 ID_COL 변수를 실제 컬럼명으로 수정하세요."
        )

    rows = []
    for year, col_name in GRADE_COLS.items():
        if col_name not in df.columns:
            print(f'  [WARN] "{col_name}" 컬럼 없음 — {year}년 데이터 건너뜀')
            continue

        year_df = df[[ID_COL, col_name]].copy()
        year_df.columns = ['researcher_id', 'grade']
        year_df['researcher_id'] = year_df['researcher_id'].astype(str).str.strip()
        year_df['grade'] = year_df['grade'].astype(str).str.strip()

        # 유효 등급만 남기기
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
        return False

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

    return True


if __name__ == '__main__':
    process()
