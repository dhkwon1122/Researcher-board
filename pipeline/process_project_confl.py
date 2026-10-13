"""
과제별 컨플루언스 주소 처리 모듈

원천: source_reader.read_source('project_confl_address')
  → DB project_confl_address_stg 테이블 또는 data/raw_csv/project_confl_address.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/과제별컨플.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/project_confl_address.csv

읽는 컬럼:
  소속, 과제명, 컨플 주소, (선택) 비공식소속부서명
  is_current(2026-10-13): 누적 저장은 그대로 두되, 이번(가장 최근) 업로드 파일에 있는 (소속, 과제명) 행은 Y,
  예전 업로드에만 있던 행은 N으로 매번 다시 표시한다(인력현황 researchers.csv의 is_current와 같은 방식).
  드롭다운·과제 문서 분석·JOB Market 후보 등 "현재 과제"가 필요한 곳은 Y만 쓴다(researcher_fit.current_rows).
  비공식소속부서명(2026-10-13): 과제명과 연구원 인력현황의 소속(org_code) 표기가 달라 "이 과제 사람"
  매칭이 안 되는 과제만 채운다. 값이 있으면 과제원 매칭에 과제명 대신 이 값을 쓰고, 화면 표시·컨플/PDF
  조회·자동 반영은 계속 과제명을 쓴다(researcher_fit.project_member_key 참고). 열이 없거나 비어 있으면 기존과 동일.

처리:
  - xlsx를 CSV로 변환합니다(추가 가공 없음).

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, RAW_DIR, OUT_DIR  # noqa: E402
from source_files import resolve_excel  # noqa: E402
from excel_reader import clean_str as _clean, read_xlsx
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source

SOURCE_FILE = '과제별컨플.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_DEP = '소속'
COL_PROJECT = '과제명'
COL_CONFL = '컨플 주소'
COL_ORG = '비공식소속부서명'   # 선택 열
# ─────────────────────────────────────────────────────────────────────────────


def _clean_confl_address(val) -> str:
    """컨플 주소 셀 정리 — 페이지 ID만 숫자로 적힌 셀이 엑셀에서 실수로 읽혀
    '3957970224.0'이 되면 소수부(.0)를 떼어 '3957970224'로 저장한다(전체 URL은 그대로)."""
    s = _clean(val)
    if re.fullmatch(r'\d+\.0+', s):
        return s.split('.')[0]
    return s


def _mark_current(merged: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    """이번 업로드(latest)에 있는 (dep_name, project_name)은 Y, 나머지는 N."""
    keys = TABLE_KEYS['project_confl_address']
    current = set(zip(*(latest[k].astype(str) for k in keys)))
    merged = merged.copy().fillna('')
    merged['is_current'] = ['Y' if tuple(row) in current else 'N'
                            for row in zip(*(merged[k].astype(str) for k in keys))]
    return merged


WEB_UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'web_updates', 'project_confl_address')
RAW_CSV_PATH = os.path.join(BASE_DIR, 'data', 'raw_csv', 'project_confl_address.csv')


def _newer_web_upload() -> str | None:
    """관리자 화면(데이터 업데이트)에 올린 과제별컨플.xlsx가 1단계 원천 사본(data/raw_csv)보다 새것이면
    그 경로(2026-10-13 버그 수정). run_integration/run_expertise는 원천 사본(DB _stg 또는 raw_csv)을 읽는데,
    이 사본은 화면 업로드로 갱신되지 않는다 — 그대로 읽으면 옛 파일이 "이번 업로드"로 취급돼 is_current가
    뒤집혀(옛 과제=Y, 새 과제=N) JOB Market 등 드롭다운에 과거 과제만 보였다."""
    path = resolve_excel(WEB_UPLOAD_DIR, SOURCE_FILE)
    if not os.path.exists(path):
        return None
    if os.path.exists(RAW_CSV_PATH) and os.path.getmtime(RAW_CSV_PATH) > os.path.getmtime(path):
        return None
    return path


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR and _newer_web_upload():
        raw_dir = WEB_UPLOAD_DIR
        print(f'  [READ] 관리자 화면에서 올린 최신 {SOURCE_FILE} 사용(원천 사본보다 새 파일)')
    if raw_dir == RAW_DIR:
        df = read_source('project_confl_address')
        if df is None:
            print('[SKIP] project_confl_address 원천 데이터 없음 '
                  '(DB project_confl_address_stg 또는 data/raw_csv/project_confl_address.csv)')
            return False
    else:
        raw_path = resolve_excel(raw_dir, SOURCE_FILE)
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
        'confl_address': df[COL_CONFL].apply(_clean_confl_address),
        'org_code': df[COL_ORG].apply(_clean) if COL_ORG in df.columns else '',
    })
    result = result[result['project_name'] != ''].reset_index(drop=True)

    out_path = os.path.join(OUT_DIR, 'project_confl_address.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['project_confl_address'])
    merged = _mark_current(merged, result)
    import csv as _csv
    merged.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=_csv.QUOTE_NONNUMERIC)
    n_old = int((merged['is_current'] == 'N').sum())
    if n_old:
        print(f'  최신 파일에 없는 과거 과제 {n_old}행은 is_current=N(드롭다운·분석 대상에서 제외, 기록은 보존)')

    print(f'[OK]   project_confl_address.csv 저장 (총 {len(merged)}행, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
