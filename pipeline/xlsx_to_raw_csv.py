"""
1단계 — DRM 제거: data/raw/ 의 DRM xlsx 원본을 있는 그대로(전 컬럼) DRM-free CSV로 변환.

Windows + Microsoft Excel 설치 PC에서 실행한다(xlwings가 Excel COM으로 DRM 파일을
연다). 컬럼 선택이나 가공은 전혀 하지 않는다 — 시트를 원본 헤더 그대로 CSV로
떠내는 것이 이 단계의 유일한 역할이다. 실제 가공(사번 정규화, 날짜 파싱, 등급
환산 등)은 이후 3단계(process_*.py, source_reader.read_source)에서 수행한다.

원천 목록은 pipeline/sources.py 에서 관리한다.

사용법 (Windows):
  python pipeline\\xlsx_to_raw_csv.py

출력: data/raw_csv/<name>.csv (utf-8-sig, 원본 헤더 그대로, 전 컬럼)

다음 단계: data/raw_csv/ 디렉터리를 리눅스 서버로 옮긴 뒤
  python pipeline/load_raw_to_db.py
로 PostgreSQL 스테이징 테이블에 적재한다.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx
from source_files import find_matches, is_wildcard
from sources import SOURCES

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw')
RAW_CSV_DIR = os.path.join(BASE_DIR, 'data', 'raw_csv')


def _resolve(raw_dir: str, pattern) -> list[str]:
    """와일드카드 패턴(예: 인력현황 다운로드 파일들)이 있으면 매칭되는 파일을
    전부 찾아 mtime 오름차순으로 반환한다. 패턴이 아니면(고정 파일명) 그
    파일이 있을 때만 [경로] 하나를 반환한다."""
    if is_wildcard(pattern):
        return find_matches(raw_dir, pattern)
    single = os.path.join(raw_dir, pattern)
    return [single] if os.path.exists(single) else []


def run():
    os.makedirs(RAW_CSV_DIR, exist_ok=True)
    converted, missing = [], []

    print('── job_profile 원천 사전 병합 ──')
    from merge_job_profile_source import run as merge_job_profile
    merge_job_profile(RAW_DIR)

    for entry in SOURCES:
        name, pattern, header_row = entry[0], entry[1], entry[2]
        multi = entry[3] if len(entry) > 3 else False

        src_paths = _resolve(RAW_DIR, pattern)
        if not src_paths:
            print(f'  [SKIP] {pattern} 없음')
            missing.append(pattern)
            continue
        if not multi and len(src_paths) > 1:
            chosen = src_paths[-1]
            print(f'  [INFO] {pattern} 후보 {len(src_paths)}개 중 최신 파일 선택: '
                  f'{os.path.basename(chosen)}')
            src_paths = [chosen]

        if len(src_paths) == 1:
            print(f'  [READ] {os.path.basename(src_paths[0])} (header_row={header_row})')
            df = read_xlsx(src_paths[0], header_row=header_row)
        else:
            print(f'  [READ] {pattern} — {len(src_paths)}개 파일 합침(mtime 오름차순): '
                  f'{[os.path.basename(p) for p in src_paths]}')
            dfs = [read_xlsx(p, header_row=header_row) for p in src_paths]
            df = pd.concat([d for d in dfs if not d.empty], ignore_index=True, sort=False)

        if df.empty:
            print(f'  [WARN] {pattern} 읽은 결과가 비어 있습니다 — 건너뜀')
            continue

        out_path = os.path.join(RAW_CSV_DIR, f'{name}.csv')
        df.to_csv(out_path, index=False, encoding='utf-8-sig')
        print(f'  [OK]   {name}.csv 저장 ({len(df)}행, {len(df.columns)}컬럼)')
        converted.append(name)

    print(f'\n변환 완료: {len(converted)}개 → {RAW_CSV_DIR}')
    if missing:
        print(f'누락된 원본 파일: {missing}')
    print('\n다음 단계: data/raw_csv/ 를 리눅스 서버로 옮긴 뒤 '
          'python pipeline/load_raw_to_db.py 실행')


if __name__ == '__main__':
    run()
