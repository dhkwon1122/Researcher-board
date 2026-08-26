"""
T&P 기본 인사 정보 파일에서 연봉등급/상·하반기업적(평가)·이름·성별·생년월일을 추출

원천: source_reader.read_source('evaluations')
  → DB evaluations_stg 테이블 또는 data/raw_csv/evaluations.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/T&P_기본_인사_정보.xlsx를 DRM 제거해 만든 사본)

추출 항목:
  - evaluations.csv : researcher_id당 1행(wide) — 연봉등급 3개년 +
                      상/하반기업적 3개년(services.evaluations.evaluation_years()가
                      정한 회계연도 기준, 매년 3월 시작). 점수 환산은 하지 않는다
                      (사용자 확정 — 원본 등급 문자만 저장).
  - researchers     : 이름, 성별, 생년월일(출생연도) → 반환 DataFrame으로 제공
                      (호출자가 기존 researchers DataFrame에 병합)

등급 체계: 연봉등급 가(최우수) > 나 > 다 > 라 > 마(최하) / 상·하반기업적 EM·ES·MT
(services.evaluations.SALARY_GRADES/HALF_GRADES 참고 — 어느 값도 순위/점수를
매기지 않고 유효값 체크에만 쓴다).
"""

import os
import sys

import pandas as pd

# ── 설정 (사내 파일 구조에 맞게 수정) ────────────────────────────────────────

# 연구원 식별 컬럼 (사번, 직원번호, EMP_ID 등)
ID_COL = '사번'

# 기본 인사 정보 컬럼 — 파일에 없으면 해당 필드만 건너뜀
NAME_COL   = '이름'
GENDER_COL = '성별'
BIRTH_COL  = '생년월일'   # YYYYMMDD, YYYY-MM-DD, datetime 모두 지원

# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import is_blank, read_xlsx, norm_id  # noqa: E402
from merge_utils import TABLE_KEYS, write_merged  # noqa: E402
from source_files import find_latest  # noqa: E402
from source_reader import read_source  # noqa: E402

sys.path.insert(0, BASE_DIR)
from services.evaluations import (  # noqa: E402
    HALF_GRADES, SALARY_GRADES, evaluation_years,
    first_half_column, salary_grade_column, second_half_column,
)

TP_PATTERN = 'T&P 기본 인사 정보 *.xlsx'
_TP_HEADER_ROW = 8  # sources.py 매니페스트 기준 (9번째 행)


def _parse_birth_year(val) -> int | None:
    """생년월일 값에서 출생연도(int)를 추출합니다."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    val_str = str(val).strip()
    if is_blank(val_str):
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


def process(raw_dir: str = RAW_DIR):
    """
    T&P 파일을 읽어 evaluations.csv를 저장하고,
    이름·성별·생년월일 정보를 담은 DataFrame을 반환합니다.

    Returns:
        (success: bool, researcher_updates: pd.DataFrame | None)
        researcher_updates 컬럼: researcher_id, name, gender, birth_year
        (추출되지 않은 컬럼은 포함되지 않을 수 있음)
    """
    if raw_dir == RAW_DIR:
        df = read_source('evaluations')
        if df is None:
            print('[SKIP] evaluations 원천 데이터 없음 '
                  '(DB evaluations_stg 또는 data/raw_csv/evaluations.csv)')
    else:
        raw_path = find_latest(raw_dir, TP_PATTERN)
        if raw_path is not None:
            df = read_xlsx(raw_path, header_row=_TP_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {TP_PATTERN} 파일 없음({raw_dir})')

    if df is None:
        return False, None

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

    # 연구원 ID → 8자리 텍스트로 정규화 (excel_reader.norm_id 공통 함수 사용)
    df['_rid'] = df[ID_COL].apply(norm_id)
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

    # ── 2. 연봉등급/상·하반기업적(평가) 추출 — researcher_id당 1행(wide) ──────
    # 회계연도(매년 3월 시작) 기준 최근 3개년. 연봉등급은 [FY,FY-1,FY-2],
    # 상/하반기업적은 그보다 항상 1년 이른 [FY-1,FY-2,FY-3](services.evaluations
    # 참고 — 두 로직이 늘 어긋나지 않도록 그 모듈의 evaluation_years() 하나만 쓴다).
    salary_years, half_years = evaluation_years()

    result = pd.DataFrame({'researcher_id': df['_rid']})
    filled_cols = []

    def _extract(col_name: str, out_col: str, valid_values: tuple, label: str):
        if col_name not in df.columns:
            print(f'  [WARN] "{col_name}" 컬럼 없음 — {out_col} 비워둠')
            result[out_col] = ''
            return
        values = df[col_name].astype(str).str.strip()
        values = values.where(values != 'nan', '')
        valid = values.isin(valid_values) | (values == '')
        skipped = (~valid).sum()
        if skipped:
            print(f'  [WARN] "{col_name}" — 유효하지 않은 {label} {skipped}건 제외 '
                  f'(허용값: {list(valid_values)})')
        result[out_col] = values.where(valid, '')
        filled_cols.append(out_col)

    for year in salary_years:
        _extract(f'{year} 연봉등급', salary_grade_column(year), SALARY_GRADES, '연봉등급')
    for year in half_years:
        _extract(f'{year} 상반기업적', first_half_column(year), HALF_GRADES, '상반기업적')
        _extract(f'{year} 하반기업적', second_half_column(year), HALF_GRADES, '하반기업적')

    if not filled_cols:
        print('[SKIP] 추출된 평가 데이터가 없습니다.')
        return False, res_update

    out_path = os.path.join(OUT_DIR, 'evaluations.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['evaluations'])

    print(f'[OK]   evaluations.csv 저장 (총 {len(merged)}행, 이번 파일 {len(result)}행 반영, 컬럼: {", ".join(filled_cols)})')
    for col in filled_cols:
        dist = result.loc[result[col] != '', col].value_counts().sort_index().to_dict()
        print(f'         {col} 분포(이번 파일 기준): {dist}')

    return True, res_update


if __name__ == '__main__':
    process()
