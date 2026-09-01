"""
로컬 PC에서 원본→전처리→LLM 분석→임베딩까지 전부 끝낸 뒤 data/processed/를
서버로 수동 이관하고 나서, 서버에서 실행해 "제대로 다 옮겨졌는지"를 점검하는
스크립트(2026-09-01 추가, 사용자 요청 — 로컬 DB와 서버 DB가 분리돼 있어
파일을 통째로 옮기는 방식이라 이관 실수를 잡아낼 도구가 필요했음).

점검 항목(파일별):
  1) 존재 여부 — pipeline/load_to_db.py가 다루는 CSV 테이블(TABLES)/JSON
     산출물(JSON_TABLES) 목록 기준(그 목록과 항상 같은 것을 본다 — 따로
     파일 목록을 여기 다시 적지 않음, 어긋나면 곤란하므로).
  2) 빈 파일 여부 — 0행이면 경고(이관 중 옛 빈 파일을 실수로 올렸을 가능성).
  3) 자연키 컬럼 존재 여부 — pipeline/merge_utils.py의 TABLE_KEYS/
     GROUP_REPLACE_KEYS에 등록된 키 컬럼이 실제로 있는지(없으면 구버전
     스키마이거나 엉뚱한 파일).
  4) 수정 시각 — 가장 최근 파일 기준으로 하루 이상 오래된 파일은 "이번
     이관에서 빠졌을 가능성"으로 별도 경고.
  5) (DATABASE_URL이 서버에 설정돼 있으면) DB 반영 여부 — 파일 행수와 DB
     테이블 행수를 비교해 "파일은 옮겼는데 DB 반영(load_to_db.py 실행/
     "DB 반영" 버튼)을 깜빡함"을 잡아낸다. 안 잡혀 있으면 이 항목은 생략
     (파일 폴백만으로도 화면은 정상 동작하므로 실패로 취급하지 않음).

사용법:
  python pipeline/verify_transfer.py

종료 코드: 문제(FAIL) 없으면 0, 하나라도 있으면 1.
"""

import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
from merge_utils import GROUP_REPLACE_KEYS, TABLE_KEYS  # noqa: E402
from load_to_db import JSON_TABLES, TABLES  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.db import get_engine  # noqa: E402

_STALE_HOURS = 24  # 가장 최근 파일보다 이만큼(시간) 이상 오래되면 경고


class Result:
    def __init__(self, name: str, status: str, detail: str, mtime: float | None = None):
        self.name = name
        self.status = status   # 'ok' | 'warn' | 'fail'
        self.detail = detail
        self.mtime = mtime


def _fmt_mtime(mtime: float | None) -> str:
    if mtime is None:
        return '-'
    return datetime.fromtimestamp(mtime).strftime('%m-%d %H:%M')


def _check_csv(name: str) -> Result:
    path = os.path.join(OUT_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return Result(name, 'fail', '파일 없음')

    mtime = os.path.getmtime(path)
    try:
        df = pd.read_csv(path, encoding='utf-8-sig', dtype=str)
    except Exception as exc:
        return Result(name, 'fail', f'읽기 실패: {exc}', mtime)

    if df.empty:
        return Result(name, 'warn', '0행(비어 있음)', mtime)

    keys = TABLE_KEYS.get(name) or GROUP_REPLACE_KEYS.get(name)
    if keys:
        missing_keys = [k for k in keys if k not in df.columns]
        if missing_keys:
            return Result(name, 'warn',
                           f'{len(df)}행, 자연키 컬럼 없음: {", ".join(missing_keys)}', mtime)

    return Result(name, 'ok', f'{len(df):,}행 · {len(df.columns)}컬럼', mtime)


def _check_json(name: str, filename: str, key_field: str) -> Result:
    path = os.path.join(OUT_DIR, filename)
    if not os.path.exists(path):
        return Result(name, 'fail', f'파일 없음 ({filename})')

    mtime = os.path.getmtime(path)
    try:
        with open(path, encoding='utf-8') as f:
            items = json.load(f)
    except Exception as exc:
        return Result(name, 'fail', f'읽기 실패: {exc}', mtime)

    if not isinstance(items, list):
        return Result(name, 'fail', '리스트 형식이 아님', mtime)
    if not items:
        return Result(name, 'warn', '0건(비어 있음)', mtime)

    missing_key_count = sum(1 for item in items if not str(item.get(key_field, '')).strip())
    if missing_key_count:
        return Result(name, 'warn',
                       f'{len(items)}건, {key_field} 없는 항목 {missing_key_count}건', mtime)

    return Result(name, 'ok', f'{len(items):,}건', mtime)


def _check_db_row_counts(csv_results: list[Result]) -> list[Result] | None:
    engine = get_engine()
    if engine is None:
        return None

    from sqlalchemy import text
    out = []
    for r in csv_results:
        if r.status == 'fail':
            continue
        path = os.path.join(OUT_DIR, f'{r.name}.csv')
        try:
            file_rows = len(pd.read_csv(path, encoding='utf-8-sig', dtype=str))
        except Exception:
            continue
        try:
            with engine.connect() as conn:
                db_rows = conn.execute(text(f'SELECT COUNT(*) FROM {r.name}')).scalar()
        except Exception as exc:
            out.append(Result(r.name, 'warn', f'DB 조회 실패({exc}) — 테이블이 아직 없을 수 있음'))
            continue
        if db_rows == file_rows:
            out.append(Result(r.name, 'ok', f'파일 {file_rows:,}행 = DB {db_rows:,}행'))
        else:
            out.append(Result(
                r.name, 'warn',
                f'파일 {file_rows:,}행 ≠ DB {db_rows:,}행 — DB 반영을 다시 해야 할 수 있습니다',
            ))
    return out


def _print_section(title: str, results: list[Result]) -> None:
    print(f'\n── {title} ──')
    icon = {'ok': '[OK]  ', 'warn': '[WARN]', 'fail': '[FAIL]'}
    for r in results:
        mtime_str = f'  ({_fmt_mtime(r.mtime)})' if r.mtime else ''
        print(f'{icon[r.status]} {r.name:<28} {r.detail}{mtime_str}')


def _print_staleness_warning(results: list[Result]) -> None:
    mtimes = [(r.name, r.mtime) for r in results if r.mtime is not None]
    if len(mtimes) < 2:
        return
    newest = max(m for _, m in mtimes)
    stale = [(name, m) for name, m in mtimes if newest - m > _STALE_HOURS * 3600]
    if not stale:
        return
    print(f'\n── 이번 이관에서 빠졌을 가능성(다른 파일보다 {_STALE_HOURS}시간 이상 오래됨) ──')
    for name, m in sorted(stale, key=lambda x: x[1]):
        print(f'  · {name} ({_fmt_mtime(m)})')


def main() -> int:
    print(f'점검 대상 디렉터리: {OUT_DIR}')

    csv_results = [_check_csv(name) for name in TABLES]
    json_results = [_check_json(name, filename, key_field)
                     for name, filename, key_field in JSON_TABLES]

    _print_section('CSV 테이블', csv_results)
    _print_section('LLM/임베딩 JSON 산출물', json_results)
    _print_staleness_warning(csv_results + json_results)

    db_results = _check_db_row_counts(csv_results)
    if db_results is None:
        print('\n── DB 반영 상태 ──\nDATABASE_URL 미설정 — DB 비교 생략(파일 폴백으로 동작).')
    else:
        _print_section('DB 반영 상태(파일 행수 vs DB 행수)', db_results)

    all_results = csv_results + json_results + (db_results or [])
    n_fail = sum(1 for r in all_results if r.status == 'fail')
    n_warn = sum(1 for r in all_results if r.status == 'warn')
    print(f'\n요약: 실패 {n_fail}건 · 경고 {n_warn}건 · 정상 '
          f'{len(all_results) - n_fail - n_warn}건')

    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
