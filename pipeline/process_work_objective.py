"""
업무목표 전처리

원천: source_reader.read_source('work_objective_24'/'_25'/'_26')
  → DB work_objective_{yy}_stg 테이블 또는 data/raw_csv/work_objective_{yy}.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/업무목표24.xlsx, 업무목표25.xlsx,
   업무목표26.xlsx를 DRM 제거해 만든 사본)
Output       : data/processed/work_objective.csv

각 연도 파일은 컬럼이 많아 header_row='auto'로 실제 헤더 행을 자동 인식한 뒤,
그 안에서 COL_ID/COL_NAME/COL_DETAIL(사번/목표명/상세설명) 컬럼명을 찾아 사용한다.
한 연구원이 한 해에 목표를 여러 개(여러 행) 작성할 수 있어, 같은 행의
목표명·상세설명을 "- 목표명 - 상세설명"으로 이어붙이고, 같은 연구원의 여러
행은 줄바꿈으로 이어 그 해의 컬럼 하나(work_objective{year})에 담는다.
3개 연도 결과를 researcher_id 기준 outer-merge해 연구원 1명당 1행으로 만든다
(어느 해에 데이터가 없으면 그 해 컬럼만 빈 문자열).

컬럼 매핑:
  사번    → researcher_id (8자리 제로패딩)
  목표명 · 상세설명 → work_objective24 / work_objective25 / work_objective26
                    (같은 행끼리 묶어 "- 목표명 - 상세설명" 줄 단위로 저장)

Output 컬럼(4개): researcher_id, work_objective24, work_objective25, work_objective26

※ 이 모듈은 사내 LLM을 호출하지 않는다(순수 엑셀 추출/정리).
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source

# 원본 컬럼 이름 (파일에 없으면 아래 값을 실제 헤더명으로 수정)
COL_ID = '사번'
COL_NAME = '목표명'
COL_DETAIL = '상세설명'

# 연도 → 원천 파일명 / 출력 컬럼명
YEAR_FILES = {
    24: '업무목표24.xlsx',
    25: '업무목표25.xlsx',
    26: '업무목표26.xlsx',
}


def _combine_row(name, detail) -> str:
    name = clean_str(name)
    detail = clean_str(detail)
    if name and detail:
        return f'- {name} - {detail}'
    if name or detail:
        return f'- {name or detail}'
    return ''


def _read_year_file(year: int, filename: str, raw_dir: str) -> pd.DataFrame:
    """한 연도 파일을 읽어 (researcher_id, work_objective{year}) DataFrame으로 반환.
    파일이 없거나 비어 있으면 빈 DataFrame(같은 컬럼 구조)을 반환한다."""
    col = f'work_objective{year}'
    empty = pd.DataFrame(columns=['researcher_id', col])
    source_name = f'work_objective_{year}'

    if raw_dir == RAW_DIR:
        df = read_source(source_name)
        if df is None:
            print(f'[SKIP] {source_name} 원천 데이터 없음 '
                  f'(DB {source_name}_stg 또는 data/raw_csv/{source_name}.csv)')
            return empty
    else:
        path = os.path.join(raw_dir, filename)
        if not os.path.exists(path):
            print(f'[SKIP] {path} 파일 없음')
            return empty

        df = read_xlsx(path, header_row='auto')
        if df.empty:
            print(f'[SKIP] {filename} 읽기 결과가 비어 있습니다.')
            return empty

    missing = [c for c in (COL_ID, COL_NAME, COL_DETAIL) if c not in df.columns]
    if missing:
        sample = ', '.join(f'"{c}"' for c in list(df.columns)[:20])
        raise ValueError(
            f'\n[오류] {filename}에 다음 컬럼을 찾지 못했습니다: {missing}\n'
            f'파일의 컬럼(앞 20개): {sample}\n'
            f'→ process_work_objective.py 상단의 COL_ID/COL_NAME/COL_DETAIL을 '
            f'실제 컬럼명으로 수정하세요.'
        )

    df = df.copy()
    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != '']

    df['_line'] = df.apply(lambda r: _combine_row(r.get(COL_NAME), r.get(COL_DETAIL)), axis=1)
    df = df[df['_line'] != '']
    if df.empty:
        return empty

    grouped = (
        df.groupby('researcher_id')['_line']
        .apply(lambda lines: '\n'.join(lines))
        .reset_index()
        .rename(columns={'_line': col})
    )
    print(f'[OK]   {filename} → {len(grouped)}명 (목표 {len(df)}행)')
    return grouped


def process(raw_dir: str = RAW_DIR) -> bool:
    year_dfs = [_read_year_file(year, filename, raw_dir) for year, filename in YEAR_FILES.items()]
    if all(d.empty for d in year_dfs):
        print('[SKIP] 업무목표 파일을 하나도 찾지 못했습니다.')
        return False

    merged = None
    for d in year_dfs:
        if d.empty:
            continue
        merged = d if merged is None else merged.merge(d, on='researcher_id', how='outer')

    for year in YEAR_FILES:
        col = f'work_objective{year}'
        if col not in merged.columns:
            merged[col] = ''
    merged = merged.fillna('')

    out_cols = ['researcher_id'] + [f'work_objective{year}' for year in YEAR_FILES]
    merged = merged[out_cols].sort_values('researcher_id').reset_index(drop=True)

    out_path = os.path.join(OUT_DIR, 'work_objective.csv')
    final = write_merged(out_path, merged, TABLE_KEYS['work_objective'])
    print(f'[OK]   work_objective.csv 저장 (총 {len(final)}명, 이번 파일 {len(merged)}명 반영)')
    return True


if __name__ == '__main__':
    process()
