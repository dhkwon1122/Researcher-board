"""
3단계 — 후처리(process_*.py)가 원천 데이터를 읽는 단일 진입점.

조회 우선순위:
  0) (2026-10-15) 관리자 화면 "데이터 업데이트"로 올린 파일(data/web_updates/<name>/)이 1단계 원천 사본
     (data/raw_csv/<name>.csv — DB `{name}_stg`도 이 사본을 적재한 것)보다 새것이면 그 파일.
     원천 사본은 화면 업로드로 갱신되지 않아, run_integration/run_expertise가 옛 사본을 읽고 화면 업로드로
     맞게 만든 processed 데이터를 같은 키로 되돌려 쓰던 문제(과제 '진행중' 재발, JOB Market 옛 과제 등)를
     모든 원천에 공통으로 막는다. 파일 선택·헤더 행은 sources.py 매니페스트(1단계와 동일 규칙).
  1) PostgreSQL 스테이징 테이블 `{name}_stg` (DATABASE_URL 설정 시,
     load_raw_to_db.py가 적재한 테이블)
  2) 로컬 raw CSV data/raw_csv/{name}.csv (1단계 xlsx_to_raw_csv.py 산출물)

둘 다 없으면 None을 반환한다 — 호출부(process_*.py)는 기존과 동일하게
`{name}_raw.xlsx/csv` 폴백 또는 [SKIP] 처리를 이어간다.

xlsx를 직접 열지 않으므로(xlwings 불필요) 리눅스 서버에서도 그대로 동작한다.
반환되는 DataFrame은 전 컬럼 문자열(dtype=str)이며 빈 값은 빈 문자열('')이다.
"""

import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_CSV_DIR = os.path.join(BASE_DIR, 'data', 'raw_csv')

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _read_from_db(name: str) -> pd.DataFrame | None:
    from services.db import get_engine

    engine = get_engine()
    if engine is None:
        return None
    try:
        df = pd.read_sql_query(f'SELECT * FROM {name}_stg', engine, dtype=str)
        return df.fillna('')
    except Exception:
        return None


WEB_UPDATES_DIR = os.path.join(BASE_DIR, 'data', 'web_updates')
_EXCEL_EXTS = ('.xlsx', '.xlsb', '.xls')


def _source_entry(name: str):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sources import SOURCES
    for entry in SOURCES:
        if entry[0] == name:
            return entry
    return None


def _web_dirs(name: str) -> list:
    """이 원천의 화면 업로드 폴더 후보. 업무목표는 화면 키가 슬롯(work_objective_1~3)이라 전부 본다."""
    dirs = [os.path.join(WEB_UPDATES_DIR, name)]
    if name.startswith('work_objective_'):
        import glob
        dirs += sorted(glob.glob(os.path.join(WEB_UPDATES_DIR, 'work_objective_*')))
    return [d for d in dirs if os.path.isdir(d)]


def newer_web_upload_files(name: str) -> list:
    """화면 업로드 파일 중 이 원천에 해당하고 원천 사본(raw_csv)보다 새 파일 목록(없으면 []).
    파일 선택: sources.py 패턴에 맞는 파일(multi가 아니면 최신 1개). 패턴에 맞는 게 없고 폴더에
    엑셀 파일이 딱 하나면 그 파일(원본 파일명을 유지하는 wildcard 업로드 대비 — process_tasks와 같은 규칙)."""
    entry = _source_entry(name)
    if entry is None:
        return []
    from source_files import find_matches
    pattern, multi = entry[1], (entry[3] if len(entry) > 3 else False)
    files = []
    for d in _web_dirs(name):
        found = [p for p in find_matches(d, pattern) if not os.path.basename(p).startswith('~$')]
        if not found and d == os.path.join(WEB_UPDATES_DIR, name):
            excel = [os.path.join(d, f) for f in os.listdir(d)
                     if f.lower().endswith(_EXCEL_EXTS) and not f.startswith('~$')]
            found = excel if len(excel) == 1 else []
        files += found
    if not files:
        return []
    files = sorted(set(files), key=os.path.getmtime)
    if not multi:
        files = files[-1:]
    raw_csv = os.path.join(RAW_CSV_DIR, f'{name}.csv')
    if os.path.exists(raw_csv) and os.path.getmtime(raw_csv) >= max(os.path.getmtime(f) for f in files):
        return []
    return files


VALID_DATE_FILE = '.valid_date.json'   # services/web_pipeline_runner.run_one이 기록: {"files": [...], "valid_date": "YYYY-MM-DD"}
_LAST_WEB_FILES: dict = {}             # 이번 프로세스에서 read_source(name)이 화면 업로드를 읽었으면 그 파일 목록


def web_valid_date(*names: str):
    """직전 read_source(name)이 화면 업로드 파일을 읽었다면, 그 업로드를 화면에서 실행할 때 지정한 기준 연/월
    (date). 시점보호 항목(평가·핵심기술·직무이력·업무목표)이 분석 실행 때 기준월을 '오늘'로 바꾸지 않게 한다.
    기록이 없거나 다른 파일에 대한 기록이면 None."""
    import json
    from datetime import date
    for name in names:
        files = _LAST_WEB_FILES.get(name)
        if not files:
            continue
        path = os.path.join(os.path.dirname(files[-1]), VALID_DATE_FILE)
        try:
            with open(path, encoding='utf-8') as f:
                rec = json.load(f)
            if set(rec.get('files') or []) >= {os.path.basename(x) for x in files}:
                return date.fromisoformat(rec['valid_date'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _read_web_upload(name: str) -> pd.DataFrame | None:
    _LAST_WEB_FILES.pop(name, None)
    files = newer_web_upload_files(name)
    if not files:
        return None
    from excel_reader import read_xlsx
    header_row = _source_entry(name)[2]
    try:
        dfs = [read_xlsx(f, header_row=header_row) for f in files]
    except Exception as exc:
        print(f'  [WARN] 화면 업로드 파일 읽기 실패({name}) — 원천 사본 사용: {exc}')
        return None
    dfs = [d for d in dfs if d is not None and not d.empty]
    if not dfs:
        return None
    df = pd.concat(dfs, ignore_index=True, sort=False) if len(dfs) > 1 else dfs[0]
    _LAST_WEB_FILES[name] = files
    print(f'  [READ] {name}: 관리자 화면에서 올린 최신 파일 사용(원천 사본보다 새 파일) — '
          f'{", ".join(os.path.basename(f) for f in files)}')
    return df.fillna('').astype(str)


def read_source(name: str) -> pd.DataFrame | None:
    """원천 데이터를 DataFrame으로 반환. 없으면 None. 화면 업로드가 더 새로우면 그 파일(모듈 docstring 0)."""
    df = _read_web_upload(name)
    if df is not None:
        return df
    df = _read_from_db(name)
    if df is not None:
        return df

    path = os.path.join(RAW_CSV_DIR, f'{name}.csv')
    if os.path.exists(path):
        try:
            return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
        except Exception:
            return None

    return None
