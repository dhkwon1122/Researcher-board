"""
직무 스킬셋 정규화(2026-10-21, 직무 스킬 분석 1차) — 로컬 PowerShell 분석(scripts/analyze_job_skills.py)이 사용.

원천: data/raw/스킬셋.xlsx (헤더 1행, DRM이면 Windows Excel(xlwings)로 읽음 — excel_reader.read_xlsx)
  → data/raw_csv/job_skill_set.csv   (원본 헤더 그대로, pipeline/sources.py 'job_skill_set'과 같은 이름)
  → data/processed/job_skill_set.csv (영문 헤더로 정규화)

헤더 매핑(공백·대소문자 무시):
  스킬명 → skill_name, 부서 → department, 직무 → job_function, 스킬 정의 → definition_skill,
  Level1~3 → skill_level_1~3, 스킬구성요소 → components_skill

정리:
  - 앞뒤 공백·줄바꿈 정리, 스킬명이 빈 행은 버림.
  - 부서·직무 칸이 비어 있으면 바로 위 행 값으로 채움(엑셀 병합 셀은 첫 칸에만 값이 있어서) — 채운 칸 수는
    결과의 filled_cells로 돌려주고 분석 리포트 "요약"에 표시한다.
  - skill_key: 스킬명 비교용 키(공백 제거·소문자·전각→반각) — "Python 프로그래밍"과 "Python프로그래밍"을 같은 스킬로 본다.
    표기가 갈린 경우는 리포트 "데이터 점검"에 따로 나온다.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, OUT_DIR, RAW_DIR  # noqa: E402

SOURCE_NAME = 'job_skill_set'
SOURCE_FILE = '스킬셋.xlsx'
RAW_CSV_DIR = os.path.join(BASE_DIR, 'data', 'raw_csv')
RAW_CSV_PATH = os.path.join(RAW_CSV_DIR, f'{SOURCE_NAME}.csv')
OUT_PATH = os.path.join(OUT_DIR, f'{SOURCE_NAME}.csv')

# 원본 헤더(공백 제거·소문자) → 영문 컬럼
HEADER_MAP = {
    '스킬명': 'skill_name',
    '부서': 'department',
    '직무': 'job_function',
    '스킬정의': 'definition_skill',
    'level1': 'skill_level_1',
    'level2': 'skill_level_2',
    'level3': 'skill_level_3',
    '스킬구성요소': 'components_skill',
}
COLUMNS = ['job_function', 'department', 'skill_name', 'definition_skill',
           'skill_level_1', 'skill_level_2', 'skill_level_3', 'components_skill']
REQUIRED = ['skill_name', 'department', 'job_function']
FILL_DOWN = ['job_function', 'department']


def _header_key(text) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text))).lower()


def _clean(val) -> str:
    if val is None:
        return ''
    s = str(val)
    if s.strip().lower() in ('nan', 'none', 'nat'):
        return ''
    s = unicodedata.normalize('NFKC', s).replace('\r\n', '\n').replace('\r', '\n')
    lines = [re.sub(r'[ \t ]+', ' ', ln).strip() for ln in s.split('\n')]
    return '\n'.join(ln for ln in lines if ln)


def skill_key(name: str) -> str:
    """스킬명 비교 키 — 공백·구두점 차이와 영문 대소문자를 무시."""
    s = unicodedata.normalize('NFKC', str(name or '')).lower()
    return re.sub(r'[\s\-_·•.,/()\[\]{}"\'`]+', '', s)


def convert_xlsx(force: bool = False) -> str | None:
    """data/raw/스킬셋.xlsx → data/raw_csv/job_skill_set.csv(원본 헤더 그대로). xlsx가 raw_csv보다 새로울 때만
    (또는 force). 반환: 변환했으면 xlsx 경로, 아니면 None."""
    src = os.path.join(RAW_DIR, SOURCE_FILE)
    if not os.path.exists(src):
        return None
    if not force and os.path.exists(RAW_CSV_PATH) and os.path.getmtime(RAW_CSV_PATH) >= os.path.getmtime(src):
        return None
    from excel_reader import read_xlsx
    try:
        from raw_archive import archive_raw_file
        archive_raw_file(src, category=SOURCE_NAME)
    except Exception as exc:  # noqa: BLE001 — 아카이브 실패가 변환을 막지 않게
        print(f'  [WARN] 원본 아카이브 실패(무시하고 계속): {exc}')
    df = read_xlsx(src, header_row=0)
    if df.empty:
        raise ValueError(f'{SOURCE_FILE}을 읽은 결과가 비어 있습니다.')
    os.makedirs(RAW_CSV_DIR, exist_ok=True)
    df.to_csv(RAW_CSV_PATH, index=False, encoding='utf-8-sig')
    return src


def normalize(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """원본 DataFrame → (정규화 DataFrame, 정리 정보). 필요한 헤더가 없으면 ValueError(현재 헤더 안내)."""
    rename = {}
    for col in raw.columns:
        key = _header_key(col)
        if key in HEADER_MAP and HEADER_MAP[key] not in rename.values():
            rename[col] = HEADER_MAP[key]
    missing = [c for c in COLUMNS if c not in rename.values()]
    if missing:
        raise ValueError(f'스킬셋 헤더를 찾지 못했습니다: {missing}\n  현재 파일 헤더: {list(raw.columns)}\n'
                         f'  (pipeline/process_job_skill_set.py의 HEADER_MAP을 확인하세요)')
    df = raw.rename(columns=rename)[COLUMNS].copy()
    for c in COLUMNS:
        df[c] = df[c].map(_clean)
    raw_rows = len(df)
    df = df[~(df[COLUMNS] == '').all(axis=1)]            # 완전히 빈 행
    filled = 0
    for c in FILL_DOWN:                                   # 병합 셀(첫 칸에만 값) 보정
        blank = df[c] == ''
        filled += int((blank & (df['skill_name'] != '')).sum())
        df[c] = df[c].replace('', pd.NA).ffill().fillna('')
    no_name = int((df['skill_name'] == '').sum())
    df = df[df['skill_name'] != ''].reset_index(drop=True)
    df['skill_key'] = df['skill_name'].map(skill_key)
    df['row_no'] = range(1, len(df) + 1)
    info = {'raw_rows': raw_rows, 'rows': len(df), 'filled_cells': filled, 'dropped_no_name': no_name}
    return df, info


def run(force_convert: bool = False) -> tuple[pd.DataFrame, dict]:
    """xlsx 변환(필요 시) → 정규화 → data/processed/job_skill_set.csv 저장. 반환: (DataFrame, 정보)."""
    converted = convert_xlsx(force=force_convert)
    if not os.path.exists(RAW_CSV_PATH):
        raise FileNotFoundError(f'{os.path.join(RAW_DIR, SOURCE_FILE)} 또는 {RAW_CSV_PATH}가 없습니다.')
    raw = pd.read_csv(RAW_CSV_PATH, encoding='utf-8-sig', dtype=str).fillna('')
    df, info = normalize(raw)
    info['source'] = converted or RAW_CSV_PATH
    info['converted'] = bool(converted)
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, encoding='utf-8-sig')
    info['out_path'] = OUT_PATH
    return df, info


if __name__ == '__main__':
    frame, meta = run('--force' in sys.argv)
    print(f"[OK] {meta['out_path']} ({meta['rows']}행, 병합 셀 보정 {meta['filled_cells']}칸)")
