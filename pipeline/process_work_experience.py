"""
근무 경력 처리 모듈

원천: source_reader.read_source('work_experience')
  → DB work_experience_stg 테이블 또는 data/raw_csv/work_experience.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/임직원 근무경력 *.xlsx를 DRM 제거해
  만든 사본)
출력 파일: data/processed/work_experience.csv

읽는 컬럼:
  사번, 회사, 시작일, 종료일, 직무명

출력 스키마(long, 한 사람이 여러 회사 경력을 가질 수 있어 사람당 여러 행):
  researcher_id, company_name, work_start_date, work_end_date, role_name
  (work_start_date/work_end_date는 'YYYY-MM-DD'로 정규화, 종료일이 원본에
  없으면 빈 문자열 그대로 — "현재"로 채우지 않는다, 사용자 확정)

── 누적 방식: researcher_id 단위 그룹 교체(사용자 확정, 2026-08-29) ──────────
한 사람이 여러 회사 경력(여러 행)을 가질 수 있어, 개별 행을 자연키(예:
회사명+시작일)로 upsert하면 원본에서 삭제되거나 고쳐진 옛 경력 행이 계속
남는 문제가 있다. 그래서 다른 대부분의 이력형 테이블(자연키 upsert)과 달리,
"이번 업로드에 그 사람의 행이 하나라도 있으면 그 사람의 기존 행 전체를
지우고 이번 업로드 내용으로 완전히 교체"하는 방식(merge_utils.
group_replace_merge(), leadership_comments.csv와 동일한 인프라)을 쓴다.
이번 업로드에 없는 사람은 기존 행이 그대로 보존된다. valid_year/valid_month
시점 보호나 _history.csv는 두지 않는다(사용자가 이 방식으로 확정).

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import os
import sys

import pandas as pd

PATTERN = '임직원 근무경력 *.xlsx'
_HEADER_ROW = 5  # 사용자 확인(2026-08-29) — 실제 헤더는 6번째 행(1~5행 무시)

COL_ID      = '사번'
COL_COMPANY = '회사'
COL_START   = '시작일'
COL_END     = '종료일'
COL_ROLE    = '직무명'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import norm_id, parse_flexible_date, read_xlsx  # noqa: E402
from merge_utils import GROUP_REPLACE_KEYS, write_merged  # noqa: E402
from source_files import find_latest  # noqa: E402
from source_reader import read_source  # noqa: E402


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('work_experience')
        if df is None:
            print('[SKIP] work_experience 원천 데이터 없음 '
                  '(DB work_experience_stg 또는 data/raw_csv/work_experience.csv)')
    else:
        raw_path = find_latest(raw_dir, PATTERN)
        if raw_path is not None:
            df = read_xlsx(raw_path, header_row=_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {PATTERN} 파일 없음({raw_dir})')

    if df is None:
        return False
    if df.empty:
        print('[SKIP] 파일 읽기 결과가 비어 있습니다.')
        return False

    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        sample = ', '.join(f'"{c}"' for c in list(df.columns)[:15])
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  파일의 컬럼(앞 15개): {sample}\n'
            f'  process_work_experience.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.'
        )
        return False

    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    result = pd.DataFrame({
        'researcher_id':    df[COL_ID].apply(norm_id),
        'company_name':     _col(COL_COMPANY),
        'work_start_date':  df[COL_START].apply(parse_flexible_date) if COL_START in df.columns
                             else pd.Series('', index=df.index),
        'work_end_date':    df[COL_END].apply(parse_flexible_date) if COL_END in df.columns
                             else pd.Series('', index=df.index),
        'role_name':        _col(COL_ROLE),
    })
    result = result[result['researcher_id'] != ''].copy()  # 사번 없는 행 제외(사용자 확정)
    result = result.sort_values(
        ['researcher_id', 'work_start_date'], ascending=[True, False]).reset_index(drop=True)

    out_path = os.path.join(OUT_DIR, 'work_experience.csv')
    merged = write_merged(out_path, result, GROUP_REPLACE_KEYS['work_experience'], group_replace=True)

    n = result['researcher_id'].nunique() if not result.empty else 0
    print(f'[OK]   work_experience.csv 저장 (이번 업로드 {len(result)}행, {n}명 교체 / 누적 총 {len(merged)}행)')
    return True


if __name__ == '__main__':
    process()
