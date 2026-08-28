"""
임직원 직무이력(job_profile) 원천 두 파일을 하나로 합치는 전처리 단계.

배경: 예전엔 data/raw/임직원_직무이력.xlsx 한 파일이었지만, 지금은 사내
시스템이 "내 리포트 *.xlsx"(예: "내 리포트 2026-08-26 11_15 GMT+9.xlsx",
6번째 행이 헤더)로 최신 데이터만 내려주고, 2018년 5월 이전 이력은 별도
구버전 파일 임직원_직무이력('18.5월_이전).xlsx(2번째 행이 헤더)에만 남아있다.
process_job_profile.py가 읽을 하나의 파일을 만들기 위해 이 둘을 합친다.

규칙(사용자 확정):
  1) 구버전 파일: 직종/직군/주직무여부 컬럼 삭제, "직무 프로필"→"직무" 컬럼명 변경.
  2) 신규 파일("내 리포트 *.xlsx", "_병합"이 이름에 든 파일은 이미 산출물이므로
     후보에서 제외): ID 컬럼 삭제.
  3) 컬럼 정합성은 사용자가 이미 실데이터로 확인했지만(완전히 동일), 안전을
     위해 신규 파일(2번)의 컬럼명을 기준으로 구버전 데이터(1번)를 맞춰서
     붙인다(reindex — 신규에 없는 구버전 컬럼은 버리고, 신규에만 있는 컬럼은
     빈 값으로 채움).
  4) 신규 파일 데이터 다음에 구버전 데이터를 이어붙이고, "사번" 오름차순으로
     정렬한다.
  5) 원본을 덮어쓰지 않고 새 파일 "내 리포트 *_병합.xlsx"로 저장한다 — 신규
     파일의 6번째 행(헤더) 앞 5개 안내 행은 그대로 보존해, sources.py가
     이 산출물도 기존과 동일하게 "6번째 행이 헤더"로 읽을 수 있게 한다.

이 스크립트는 xlsx_to_raw_csv.py가 매 실행 시작 시 자동으로 호출한다(사용자가
따로 실행할 필요 없음). "내 리포트 *.xlsx"가 하나도 없으면 조용히 건너뛴다.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR  # noqa: E402
from excel_reader import read_xlsx, read_xlsx_matrix  # noqa: E402
from source_files import find_latest  # noqa: E402

LEGACY_FILE = "임직원_직무이력('18.5월_이전).xlsx"
LEGACY_HEADER_ROW = 1   # 2번째 행

NEW_PATTERN = '내 리포트 *.xlsx'
NEW_HEADER_ROW = 5      # 6번째 행
MERGED_SUFFIX = '_병합'

LEGACY_DROP_COLS = ['직종', '직군', '주직무여부']
LEGACY_RENAME = {'직무 프로필': '직무'}
NEW_DROP_COLS = ['ID']

SORT_COL = '사번'


def _merged_path(new_path: str) -> str:
    base, ext = os.path.splitext(new_path)
    return f'{base}{MERGED_SUFFIX}{ext}'


def run(raw_dir: str = RAW_DIR) -> str | None:
    """병합을 수행하고 결과 파일 경로를 반환한다. 신규 파일이 없으면 None."""
    new_path = find_latest(raw_dir, NEW_PATTERN, exclude=MERGED_SUFFIX)
    if new_path is None:
        print(f'  [SKIP] {NEW_PATTERN} 없음({raw_dir}) — job_profile 병합 건너뜀')
        return None

    out_path = _merged_path(new_path)

    new_df = read_xlsx(new_path, header_row=NEW_HEADER_ROW)
    if new_df.empty:
        print(f'  [WARN] {os.path.basename(new_path)} 읽은 결과가 비어 있습니다 — 병합 건너뜀')
        return None
    new_df.columns = [str(c).strip() for c in new_df.columns]
    new_df = new_df.drop(columns=[c for c in NEW_DROP_COLS if c in new_df.columns])

    legacy_path = os.path.join(raw_dir, LEGACY_FILE)
    if os.path.exists(legacy_path):
        legacy_df = read_xlsx(legacy_path, header_row=LEGACY_HEADER_ROW)
        legacy_df.columns = [str(c).strip() for c in legacy_df.columns]
        legacy_df = legacy_df.drop(columns=[c for c in LEGACY_DROP_COLS if c in legacy_df.columns])
        legacy_df = legacy_df.rename(columns=LEGACY_RENAME)

        # 안전 조치: 신규 파일(2번)의 컬럼명 기준으로 구버전 데이터(1번)를 맞춘다.
        missing_in_legacy = [c for c in new_df.columns if c not in legacy_df.columns]
        extra_in_legacy = [c for c in legacy_df.columns if c not in new_df.columns]
        if missing_in_legacy or extra_in_legacy:
            print(f'  [WARN] {LEGACY_FILE} 컬럼이 신규 파일과 다릅니다 — '
                  f'신규 기준으로 맞춥니다(부족: {missing_in_legacy}, 초과(버림): {extra_in_legacy})')
        legacy_aligned = legacy_df.reindex(columns=new_df.columns, fill_value='')

        combined = pd.concat([new_df, legacy_aligned], ignore_index=True)
        print(f'  [OK]   {LEGACY_FILE} {len(legacy_df)}행을 신규 데이터 뒤에 이어붙임')
    else:
        combined = new_df
        print(f'  [INFO] {LEGACY_FILE} 없음({raw_dir}) — 신규 파일만으로 병합 산출물 생성')

    if SORT_COL in combined.columns:
        combined = combined.sort_values(SORT_COL, kind='stable').reset_index(drop=True)
    else:
        print(f'  [WARN] "{SORT_COL}" 컬럼을 찾지 못해 정렬을 건너뜁니다.')

    # 신규 파일의 앞쪽 안내 행(1~5행)을 그대로 보존해 병합 산출물도 "6번째
    # 행이 헤더"가 되도록 만든다 — sources.py의 job_profile header_row와 맞춰야 함.
    preamble = read_xlsx_matrix(new_path)[:NEW_HEADER_ROW]
    _write_with_preamble(out_path, preamble, list(combined.columns), combined)

    print(f'  [OK]   {os.path.basename(out_path)} 저장 (총 {len(combined)}행)')
    return out_path


def _write_with_preamble(out_path: str, preamble: list[list], header: list[str], df: pd.DataFrame) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in preamble:
        ws.append(list(row))
    ws.append(header)
    for row in df.itertuples(index=False, name=None):
        ws.append(list(row))
    wb.save(out_path)


if __name__ == '__main__':
    run()
