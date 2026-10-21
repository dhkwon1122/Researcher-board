"""
직무 스킬셋 정규화(2026-10-21, 직무 스킬 분석 1차) — 로컬 PowerShell 분석(scripts/analyze_job_skills.py)이 사용.

원천(앞에서부터 있는 것): --input으로 지정한 파일(xlsx/csv) → data/raw/스킬셋.xlsx → data/raw_csv/job_skill_set.csv
  - xlsx: DRM이면 Windows Excel(xlwings)로만 읽힌다. 리눅스 서버에서는 DRM 해제본(다른 이름으로 저장)이나
    로컬에서 변환한 data/raw_csv/job_skill_set.csv를 써야 한다.
  - data/raw/스킬셋.xlsx를 읽으면 data/raw_csv/job_skill_set.csv(원본 헤더 그대로, sources.py 'job_skill_set')도
    갱신한다(쓰기 권한이 없으면 건너뜀).
  → <출력 폴더>/job_skill_set.csv (영문 헤더로 정규화, 기본 data/analysis — 앱이 쓰는 data/processed는 건드리지 않음:
    서버 호스트에서 직접 실행해도 컨테이너(uid 10001) 소유 파일을 바꾸지 않도록, 2026-10-21)

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
from paths import BASE_DIR, RAW_DIR  # noqa: E402

SOURCE_NAME = 'job_skill_set'
SOURCE_FILE = '스킬셋.xlsx'
RAW_CSV_DIR = os.path.join(BASE_DIR, 'data', 'raw_csv')
RAW_CSV_PATH = os.path.join(RAW_CSV_DIR, f'{SOURCE_NAME}.csv')
ANALYSIS_DIR = os.path.join(BASE_DIR, 'data', 'analysis')

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


def _read_excel(path: str) -> pd.DataFrame:
    from excel_reader import read_xlsx
    try:
        df = read_xlsx(path, header_row=0)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f'{path}을 읽지 못했습니다({type(exc).__name__}: {exc}). DRM이 걸린 파일은 Windows Excel에서만 '
                         f'열립니다 — 서버에서는 "다른 이름으로 저장"한 DRM 해제본이나 로컬에서 변환한 '
                         f'data/raw_csv/{SOURCE_NAME}.csv를 쓰세요.') from exc
    if df.empty:
        raise ValueError(f'{path}을 읽은 결과가 비어 있습니다(DRM 파일이면 위 안내 참고).')
    return df.astype(object).where(df.notna(), '')


def load_raw(input_path: str | None = None, force_convert: bool = False) -> tuple[pd.DataFrame, str]:
    """원본 DataFrame과 실제로 읽은 경로. data/raw/스킬셋.xlsx를 읽었으면 raw_csv 사본도 갱신(권한 없으면 건너뜀)."""
    if input_path:
        if not os.path.exists(input_path):
            raise FileNotFoundError(f'{input_path} 파일이 없습니다.')
        if input_path.lower().endswith('.csv'):
            return pd.read_csv(input_path, encoding='utf-8-sig', dtype=str).fillna(''), input_path
        return _read_excel(input_path), input_path
    src = os.path.join(RAW_DIR, SOURCE_FILE)
    if os.path.exists(src) and (force_convert or not os.path.exists(RAW_CSV_PATH)
                                or os.path.getmtime(src) > os.path.getmtime(RAW_CSV_PATH)):
        df = _read_excel(src)
        try:
            from raw_archive import archive_raw_file
            archive_raw_file(src, category=SOURCE_NAME)
            os.makedirs(RAW_CSV_DIR, exist_ok=True)
            df.to_csv(RAW_CSV_PATH, index=False, encoding='utf-8-sig')
        except OSError as exc:
            print(f'  [WARN] raw_csv 사본 저장 생략(권한 등): {exc}')
        return df, src
    if os.path.exists(RAW_CSV_PATH):
        return pd.read_csv(RAW_CSV_PATH, encoding='utf-8-sig', dtype=str).fillna(''), RAW_CSV_PATH
    raise FileNotFoundError(f'{src} 또는 {RAW_CSV_PATH}가 없습니다(--input으로 파일을 직접 지정할 수 있습니다).')


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


def run(input_path: str | None = None, out_dir: str | None = None,
        force_convert: bool = False) -> tuple[pd.DataFrame, dict]:
    """원본 읽기 → 정규화 → <out_dir>/job_skill_set.csv 저장. 반환: (DataFrame, 정보)."""
    raw, source = load_raw(input_path, force_convert)
    df, info = normalize(raw)
    out_dir = out_dir or ANALYSIS_DIR
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f'{SOURCE_NAME}.csv')
    df.to_csv(out_path, index=False, encoding='utf-8-sig')
    info.update({'source': source, 'out_path': out_path})
    return df, info


if __name__ == '__main__':
    frame, meta = run(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else None,
                      force_convert='--force' in sys.argv)
    print(f"[OK] {meta['out_path']} ({meta['rows']}행, 병합 셀 보정 {meta['filled_cells']}칸)")
