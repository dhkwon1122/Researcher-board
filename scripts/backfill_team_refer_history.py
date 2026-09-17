"""
과거 여러 달치 인력현황 원본(raw headcount)을 한 번에 team_refer.csv에
소급 반영하는 일회성 스크립트(2026-09-17, 사용자 요청 — "과거 시점의
인력현황 원본을 대량으로 넣고 싶어(예: 2018년 05월~2026년 08월까지)").

각 원본 파일 안의 "인원실적년도"/"인원실적월" 헤더 값을 읽어 그 달
**말일**을 그 파일의 유효 날짜(valid_date)로 삼는다(예: 인원실적년도=
"2020", 인원실적월="03" → 2020-03-31자 팀/리더참조로 반영) — 파일명이
아니라 파일 "내용"으로 시점을 정하므로 파일명 규칙을 신경 쓸 필요가
없다. 나머지 처리(인력현황 원본 → team_refer 인텔이크 변환, 사번/성명/
직책 자동 채움 등)는 관리자 화면 "엑셀 파일로 한번에 반영"과 완전히
동일한 pipeline.process_team_refer.process()를 그대로 재사용한다.

── 왜 process()에 skip_tombstone=True를 쓰는가 ────────────────────────────────
process()는 기본적으로 "현재(전체 파일 기준 가장 최근 날짜) 살아있는
dep_id인데 이번 실행 결과에 없으면 사라진 것"으로 보고 톰스톤(deleted='Y')
처리한다. 그런데 이미 더 미래 시점(예: 2026-09, 실제 "현재" 데이터)이
team_refer.csv에 쌓여 있는 상태에서 그보다 과거 시점(예: 2020-03)을
나중에 소급 반영하면, 미래에만 존재하는 조직이 전부 "2020-03에 사라짐"
으로 잘못 톰스톤 처리된다 — "현재" 조직도 자체는 안 깨지지만(dep_id별
가장 최근 날짜를 고르므로), 기간 지정 조회(특정 시점 기준 조직도
재구성)가 그 잘못된 톰스톤을 "2020-03 시점의 실제 상태"로 오인해 과거
조직도가 깨진다. 그래서 이 스크립트는 process(skip_tombstone=True)로
호출해 이 문제를 피한다(process_team_refer.py의 process() docstring
참고).

── 처리 순서 ──────────────────────────────────────────────────────────────
1. 소스 폴더 안의 모든 xlsx/csv를 열어 필수 헤더(1단계부서명/현소속
   부서명/비공식소속부서명 — team_refer_intake.is_raw_format() 판정 기준
   + 인원실적년도/인원실적월 — 이 스크립트가 시점을 정하는 데 필요)가
   전부 있는지 먼저 확인한다(사용자 확정 — "처음에 필요한 헤더들이
   있는지 확인해주는 작업을 삽입"). 하나라도 없으면 그 파일은 처리
   대상에서 제외하고 사유와 함께 보고한다.
2. 통과한 파일들을 "인원실적년도/인원실적월"로 구한 날짜 기준 오름차순
   (오래된 시점부터)으로 자동 정렬한다(사용자 확정 — "내용을 읽어서
   자동정렬해서 진행"). 파일명은 정렬에 전혀 관여하지 않는다.
3. 같은 연/월(=같은 valid_date)로 정렬된 파일이 여러 개면, 정렬 후
   나열 순서상 나중 파일이 최종값이 된다(사용자 확정 — "마지막에
   처리된 걸 최종값으로") — write_merged()의 자연키((dep_id, valid_year,
   valid_month, valid_day)) upsert가 같은 날짜의 값을 나중 것으로
   덮어쓰므로 별도 로직 없이 자동으로 성립한다. 동일 (연,월) 파일들의
   나열 순서 자체는 안정 정렬(stable sort) 특성상 글롭(glob) 결과의
   알파벳 순서를 그대로 따른다.
4. 오름차순으로 하나씩 process(raw_dir=<그 파일 하나만 담은 임시 폴더>,
   valid_date=<계산된 말일>, skip_tombstone=True)를 호출한다 —
   services/web_pipeline_runner.py의 _run_backfill_batch()와 동일한
   "파일 1개당 임시 폴더 1개" 패턴. 원본이 인력현황 원본 형식이면
   process() 내부에서 team_refer_intake.transform()이 자동으로 적용돼
   사번/성명/직책 자동 채움(직책명/글로벌직책명/직무프로필명/사원번호/
   성명 기반)도 그대로 함께 반영된다(사용자 확정 — "책임자 정보 자동
   채움으로 해줘"). 이 5개 헤더는 필수 헤더 확인 대상이 아니다(없어도
   채움 단계만 건너뛰고 나머지는 정상 진행 — team_refer_intake.py의
   기존 동작 그대로).

── 전제(사용자 확정) ──────────────────────────────────────────────────────────
- 모든 원본 파일이 동일한 헤더 체계를 쓴다(연도별로 헤더가 달라지지
  않음).
- 원본은 이미 DRM이 풀린 상태로 이 폴더에 들어온다 — xlwings/Excel이
  전혀 필요 없어(pipeline/excel_reader.read_xlsx()가 DRM 파일이 아니면
  자동으로 pandas/openpyxl 폴백) 이 스크립트는 Linux 서버(Docker
  컨테이너)에서도 그대로 동작한다.

사용법:
  python scripts/backfill_team_refer_history.py                (미리보기: 파일별 계산된 시점/순서/제외 사유만 보여줌)
  python scripts/backfill_team_refer_history.py --apply         (실제로 team_refer.csv에 순서대로 반영)
  python scripts/backfill_team_refer_history.py "C:\\경로\\원본폴더" --apply  (다른 폴더 지정)

이 스크립트는 일회성 소급 반영 전용이라 작업이 끝나면 파일 자체를
삭제해도 무방하다(사용자 확정 — "임시로 생성, 이번 작업 후 폐지 예정").
"""
import argparse
import glob
import os
import shutil
import sys
import tempfile
from calendar import monthrange
from datetime import date

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'pipeline'))

from excel_reader import clean_str, read_xlsx  # noqa: E402
import process_team_refer as ptr  # noqa: E402
from team_refer_intake import _SRC_HEADERS  # noqa: E402

RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'team_refer_backfill_source')

_YEAR_COL = '인원실적년도'
_MONTH_COL = '인원실적월'
# team_refer_intake.is_raw_format()이 요구하는 3개 + 이 스크립트가 시점을
# 정하는 데 필요한 2개 — 하나라도 없으면 그 파일은 처리하지 않는다.
_REQUIRED_HEADERS = list(_SRC_HEADERS) + [_YEAR_COL, _MONTH_COL]


def _list_source_files(raw_dir: str) -> list:
    candidates = glob.glob(os.path.join(raw_dir, '*.xlsx')) + glob.glob(os.path.join(raw_dir, '*.csv'))
    return sorted(p for p in candidates if not os.path.basename(p).startswith('~$'))


def _read_source(path: str) -> pd.DataFrame:
    """DRM이 이미 풀린 원본을 읽는다 — .xlsx는 read_xlsx(header_row='auto')
    (원본마다 헤더 물리적 위치가 다를 수 있어 자동 인식, xlwings/Excel이
    없어도 pandas로 폴백), .csv는 1번째 행 헤더로 그대로 읽는다."""
    if path.lower().endswith('.csv'):
        return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    return read_xlsx(path, header_row='auto')


def _clean_numeric_str(val) -> str:
    """엑셀에서 숫자로 읽힌 값(예: 2020.0, 3.0)도 정수 문자열로 정리한다."""
    s = clean_str(val)
    if s.endswith('.0') and s[:-2].lstrip('-').isdigit():
        s = s[:-2]
    return s


def _extract_year_month(df: pd.DataFrame, filename: str) -> tuple[int, int] | None:
    """인원실적년도/인원실적월 컬럼에서 (연,월) 정수 쌍을 뽑는다. 파일
    안에 서로 다른 (연,월) 조합이 섞여 있으면(정상이라면 발생하지 않음)
    경고를 남기고 가장 많이 등장한 조합을 채택한다."""
    combos: dict[tuple[str, str], int] = {}
    for _, row in df[[_YEAR_COL, _MONTH_COL]].iterrows():
        y = _clean_numeric_str(row[_YEAR_COL])
        m = _clean_numeric_str(row[_MONTH_COL])
        if not y or not m:
            continue
        combos[(y, m)] = combos.get((y, m), 0) + 1
    if not combos:
        return None
    if len(combos) > 1:
        print(f'[WARN] {filename}: 인원실적년도/인원실적월 값이 여러 조합으로 섞여 있습니다 '
              f'{sorted(combos.keys())} — 가장 많이 등장한 조합을 사용합니다.')
    (y, m), _count = max(combos.items(), key=lambda kv: kv[1])
    try:
        year, month = int(y), int(m)
    except ValueError:
        return None
    if not (1 <= month <= 12):
        return None
    return year, month


def _last_day_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def plan(raw_dir: str) -> tuple[list[tuple[str, date]], list[tuple[str, str]]]:
    """반환: (처리 대상 [(경로, 유효날짜), ...] — 유효날짜 오름차순),
    (제외된 파일 [(파일명, 사유), ...])."""
    planned = []
    skipped = []
    for path in _list_source_files(raw_dir):
        name = os.path.basename(path)
        try:
            df = _read_source(path)
        except Exception as exc:
            skipped.append((name, f'파일 읽기 실패: {exc}'))
            continue
        df.columns = [str(c).strip() for c in df.columns]

        missing = [h for h in _REQUIRED_HEADERS if h not in df.columns]
        if missing:
            skipped.append((name, f'필수 헤더 없음: {missing}'))
            continue

        ym = _extract_year_month(df, name)
        if ym is None:
            skipped.append((name, f'{_YEAR_COL}/{_MONTH_COL} 값을 찾을 수 없음'))
            continue

        planned.append((path, _last_day_of_month(*ym)))

    planned.sort(key=lambda t: t[1])
    return planned, skipped


def run(raw_dir: str, apply: bool) -> None:
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir, exist_ok=True)
        print(f'[안내] {raw_dir} 에 과거 인력현황 원본 파일을 먼저 넣어주세요.')
        return

    planned, skipped = plan(raw_dir)

    print(f'처리 대상 {len(planned)}개, 제외 {len(skipped)}개 (전체 {len(planned) + len(skipped)}개)\n')
    print('=== 처리 순서(오래된 시점부터) ===')
    for path, valid_date in planned:
        print(f'  {valid_date.isoformat()}  {os.path.basename(path)}')
    if skipped:
        print('\n=== 제외된 파일 ===')
        for name, reason in skipped:
            print(f'  [제외] {name}: {reason}')

    if not apply:
        print('\n[미리보기 모드] 실제로 반영하지 않았습니다. 반영하려면 --apply를 붙여 다시 실행하세요.')
        return

    if not planned:
        print('\n반영할 파일이 없습니다.')
        return

    print('\n=== 반영 시작 ===')
    success = 0
    fail = 0
    for path, valid_date in planned:
        name = os.path.basename(path)
        tmp_dir = tempfile.mkdtemp(prefix='team_refer_backfill_')
        try:
            shutil.copy2(path, os.path.join(tmp_dir, name))
            ok = ptr.process(raw_dir=tmp_dir, valid_date=valid_date, skip_tombstone=True)
            if ok:
                success += 1
                print(f'[OK]   {valid_date.isoformat()}  {name}')
            else:
                fail += 1
                print(f'[실패] {valid_date.isoformat()}  {name}')
        except Exception as exc:
            fail += 1
            print(f'[실패] {valid_date.isoformat()}  {name}: {exc}')
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f'\n총 {len(planned)}개 중 성공 {success}개, 실패 {fail}개')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('raw_dir', nargs='?', default=RAW_DIR, help='원본 파일 폴더(기본값: data/raw/team_refer_backfill_source)')
    parser.add_argument('--apply', action='store_true', help='실제로 반영(기본값은 미리보기만)')
    args = parser.parse_args()
    run(args.raw_dir, args.apply)
