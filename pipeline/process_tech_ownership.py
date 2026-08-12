"""
보유기술 처리 모듈

원천 파일: data/raw/보유기술.xlsx
출력 파일: data/processed/tech_ownership.csv

읽는 컬럼:
  사원번호, 전문분야(1)~전문분야(5), 레벨(1)~레벨(5), 보유율(1)~보유율(5), E직군여부

출력 스키마:
  researcher_id, tech_1, lv_1, portion_1, tech_2, lv_2, portion_2, ...,
  tech_5, lv_5, portion_5, E_support

portion_N: 원본 보유율(N)이 0.1/0.2 같은 비율로 들어오므로 100을 곱해 10/20으로
저장한다(화면에는 뒤에 %만 붙여 10%/20%로 표시).
E_support: 원본 값이 'E'면 'E', 그 외(빈 값 포함)에는 모두 'R'로 통일.

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import os
import sys

import pandas as pd

TECH_OWNERSHIP_FILE = '보유기술.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID = '사원번호'
COL_E_SUPPORT = 'E직군여부'
N_SLOTS = 5


def _slot_cols(i):
    return f'전문분야({i})', f'레벨({i})', f'보유율({i})'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import is_blank, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged


def _normalize_e_support(val) -> str:
    """E직군이면 'E', 그 외(빈 값 포함)에는 모두 'R'."""
    return 'E' if str(val).strip().upper() == 'E' else 'R'


def _clean_num(val) -> str:
    """Excel에서 숫자로 읽혀 '3.0'처럼 붙는 불필요한 소수점 제거(정수값인 경우만)."""
    s = str(val).strip()
    if is_blank(s):
        return ''
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except (ValueError, OverflowError):
        return s


def _scale_portion(val) -> str:
    """보유율(N)은 원본이 0.1/0.2 같은 비율로 들어오므로 100을 곱해 10/20(%)로 변환."""
    s = str(val).strip()
    if is_blank(s):
        return ''
    try:
        f = float(s) * 100
        return str(int(f)) if f == int(f) else str(round(f, 1))
    except (ValueError, OverflowError):
        return s


def process(raw_dir: str = RAW_DIR) -> bool:
    raw_path = os.path.join(raw_dir, TECH_OWNERSHIP_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {TECH_OWNERSHIP_FILE} 파일 없음 — tech_ownership_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_tech_ownership.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
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

    out = {'researcher_id': df['researcher_id']}
    out_cols = ['researcher_id']
    for i in range(1, N_SLOTS + 1):
        field_col, lv_col, portion_col = _slot_cols(i)
        out[f'tech_{i}']    = _col(field_col)
        out[f'lv_{i}']      = _col(lv_col).apply(_clean_num)
        out[f'portion_{i}'] = _col(portion_col).apply(_scale_portion)
        out_cols += [f'tech_{i}', f'lv_{i}', f'portion_{i}']

    out['E_support'] = _col(COL_E_SUPPORT).apply(_normalize_e_support) if COL_E_SUPPORT in df.columns \
        else pd.Series('R', index=df.index)
    out_cols.append('E_support')

    result = pd.DataFrame(out, columns=out_cols)
    result = result.replace({'nan': '', 'None': ''})
    result = result.sort_values(['researcher_id']).reset_index(drop=True)

    out_path = os.path.join(OUT_DIR, 'tech_ownership.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['tech_ownership'])

    n = merged['researcher_id'].nunique()
    print(f'[OK]   tech_ownership.csv 저장 (총 {len(merged)}행, {n}명, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
