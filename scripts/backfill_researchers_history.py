"""
과거 여러 달치 인력현황 원본(raw headcount)을 한 번에 researchers.csv/
researchers_history.csv에 소급 반영하는 일회성 스크립트(2026-09-18, 사용자
요청 — team_refer 백필 때와 동일한 원본 폴더를 인력현황(researchers)에도
반영하고 싶어함, "201805~202608 데이터 넣으려고 해").

scripts/backfill_team_refer_history.py와 원본 폴더/처리 방식(파일 내용의
인원실적년도/인원실적월로 자동 정렬, 필수 헤더 사전 검증, 실패해도 나머지
계속 진행)은 동일하지만, 대상 모듈이 pipeline.process_researchers라서
아래 두 가지가 다르다.

── team_refer 백필과 다른 점 ────────────────────────────────────────────────
1. valid_date를 직접 넘기지 않는다. process_researchers.process()는
   team_refer와 달리 관리자가 지정한 기준일이 아니라, 원본 파일 자체의
   "인원실적년도"/"인원실적월" 컬럼을 행마다 그대로 읽어 valid_year/
   valid_month로 쓴다(process_researchers.py 상단 docstring 참고) — 이
   스크립트는 그 값을 오직 "어떤 순서로 처리할지" 정렬하는 데만 쓴다.
2. 톰스톤(deleted 플래그) 개념 자체가 없다. researchers.csv는 researcher_id
   업서트 + "기존 저장값보다 과거 시점이면 건너뜀" 시점 보호만 있고
   (merge_utils.write_merged_with_valid_period), 건너뛴 데이터도
   researchers_history.csv에는 예외 없이 전부 쌓인다 — 그래서 team_refer의
   skip_tombstone 같은 옵션도, 처리 순서 자체도 결과에 영향이 없다(어떤
   순서로 넣어도 각 사람은 항상 자기 인생에서 가장 최근 시점 값이
   researchers.csv에 남고, 모든 시점이 history에 남는다). 그래도 로그를
   시간순으로 보기 좋게 오름차순 정렬은 그대로 유지한다.
3. process_researchers.process(raw_dir=...)는 raw_dir이 RAW_DIR(기본값)이
   아니면 내부적으로 find_latest(raw_dir, RESEARCHERS_PATTERNS)로 파일을
   찾는데, RESEARCHERS_PATTERNS(`*That Month Headcount*.xlsx`,
   `*End of Month Headcount*.xlsx`)에 맞는 **.xlsx 파일명**만 인식한다
   (process_researchers.py 참고). 원본 파일명이 이 패턴과 다를 수 있어(예:
   team_refer 백필 때 쓰던 임의의 파일명), 임시 폴더에 복사할 때 반드시
   이 중 한 패턴에 맞는 이름으로 다시 저장한다 — 원본 파일명은 이 스크립트
   출력(로그)에서만 그대로 보여준다. .csv 원본은 이 경로로 처리할 수 없어
   (패턴이 .xlsx 전용) 발견되면 헤더 검증 자체는 하되 반영 단계에서
   실패로 보고한다.

── 처리 순서 ──────────────────────────────────────────────────────────────
1. 소스 폴더 안의 모든 xlsx/csv를 열어 필수 헤더(사원번호/성명 —
   process_researchers.py가 실제로 요구하는 최소 헤더 + 인원실적년도/
   인원실적월 — 이 스크립트가 처리 순서를 정하는 데 필요)가 전부 있는지
   먼저 확인한다. 하나라도 없으면 그 파일은 처리 대상에서 제외한다.
2. 통과한 파일들을 "인원실적년도/인원실적월"로 구한 (연,월) 기준 오름차순
   (오래된 시점부터)으로 정렬한다. 파일명은 정렬에 관여하지 않는다.
3. 하나씩 process_researchers.process(raw_dir=<그 파일 하나만 담은 임시
   폴더, RESEARCHERS_PATTERNS에 맞는 이름으로 저장>)를 호출한다 —
   services/web_pipeline_runner.py의 _run_backfill_batch()/
   backfill_team_refer_history.py와 동일한 "파일 1개당 임시 폴더 1개" 패턴.

사용법:
  python scripts/backfill_researchers_history.py                (미리보기: 파일별 계산된 시점/순서/제외 사유만 보여줌)
  python scripts/backfill_researchers_history.py --apply         (실제로 researchers.csv/researchers_history.csv에 순서대로 반영)
  python scripts/backfill_researchers_history.py "C:\\경로\\원본폴더" --apply  (다른 폴더 지정, 기본값은 team_refer 백필 때와 동일한 폴더)

일회성 소급 반영 전용이라 작업이 끝나면 파일 자체는 삭제해도 무방하다.
"""
import argparse
import glob
import os
import shutil
import sys
import tempfile

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'pipeline'))

from excel_reader import clean_str, read_xlsx  # noqa: E402
import process_researchers as pr  # noqa: E402

# team_refer 백필 때와 동일한 원본 폴더를 기본값으로 쓴다(사용자 확정 —
# "동일한 폴더야").
RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'team_refer_backfill_source')

_YEAR_COL = pr.COL_VALID_YEAR
_MONTH_COL = pr.COL_VALID_MONTH
# process_researchers.py가 실제로 요구하는 최소 헤더(사원번호/성명) + 이
# 스크립트가 처리 순서를 정하는 데 필요한 2개 — 하나라도 없으면 그 파일은
# 처리하지 않는다.
_REQUIRED_HEADERS = [pr.COL_ID, pr.COL_NAME, _YEAR_COL, _MONTH_COL]

# process_researchers.process(raw_dir=...)가 raw_dir override 시 찾는 파일명
# 패턴(RESEARCHERS_PATTERNS) 중 하나로, 임시 폴더에 복사할 때 이 이름을 쓴다.
_BACKFILL_DEST_NAME = 'backfill_That Month Headcount.xlsx'


def _list_source_files(raw_dir: str) -> list:
    candidates = glob.glob(os.path.join(raw_dir, '*.xlsx')) + glob.glob(os.path.join(raw_dir, '*.csv'))
    return sorted(p for p in candidates if not os.path.basename(p).startswith('~$'))


def _read_source(path: str) -> pd.DataFrame:
    """DRM이 이미 풀린 원본을 읽는다 — .xlsx는 process_researchers.py와 동일한
    고정 헤더 행(_RESEARCHERS_HEADER_ROW, 인력현황 원본 관례상 2번째 행)으로
    읽는다. .csv는 1번째 행 헤더로 그대로 읽는다."""
    if path.lower().endswith('.csv'):
        return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    return read_xlsx(path, header_row=pr._RESEARCHERS_HEADER_ROW)


def _clean_numeric_str(val) -> str:
    """엑셀에서 숫자로 읽힌 값(예: 2020.0, 3.0)도 정수 문자열로 정리한다."""
    s = clean_str(val)
    if s.endswith('.0') and s[:-2].lstrip('-').isdigit():
        s = s[:-2]
    return s


def _extract_year_month(df: pd.DataFrame, filename: str) -> tuple[int, int] | None:
    """인원실적년도/인원실적월 컬럼에서 (연,월) 정수 쌍을 뽑는다. 파일
    안에 서로 다른 (연,월) 조합이 섞여 있으면 경고를 남기고 가장 많이
    등장한 조합을 채택한다(처리 순서 정렬용일 뿐 — 실제 반영 시점은
    process_researchers.py가 행마다 그대로 다시 읽으므로 이 값과 무관)."""
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


def plan(raw_dir: str) -> tuple[list[tuple[str, tuple[int, int]]], list[tuple[str, str]]]:
    """반환: (처리 대상 [(경로, (연,월)), ...] — (연,월) 오름차순),
    (제외된 파일 [(파일명, 사유), ...])."""
    files = _list_source_files(raw_dir)
    planned = []
    skipped = []
    for i, path in enumerate(files, start=1):
        name = os.path.basename(path)
        print(f'[{i}/{len(files)}] 읽는 중: {name}', flush=True)
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

        planned.append((path, ym))

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
    for path, (y, m) in planned:
        print(f'  {y:04d}-{m:02d}  {os.path.basename(path)}')
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
    for path, (y, m) in planned:
        name = os.path.basename(path)
        period = f'{y:04d}-{m:02d}'

        if not path.lower().endswith('.xlsx'):
            fail += 1
            print(f'[실패] {period}  {name}: process_researchers.py는 raw_dir 지정 시 '
                  f'.xlsx만 인식합니다(csv 미지원) — 엑셀로 변환 후 다시 시도하세요.')
            continue

        tmp_dir = tempfile.mkdtemp(prefix='researchers_backfill_')
        try:
            # process_researchers.process(raw_dir=...)는 find_latest(raw_dir,
            # RESEARCHERS_PATTERNS)로 파일을 찾으므로, 원본 파일명이 그 패턴과
            # 달라도 항상 인식되도록 고정된 규격 이름으로 복사해 둔다.
            shutil.copy2(path, os.path.join(tmp_dir, _BACKFILL_DEST_NAME))
            ok = pr.process(raw_dir=tmp_dir)
            if ok:
                success += 1
                print(f'[OK]   {period}  {name}')
            else:
                fail += 1
                print(f'[실패] {period}  {name}')
        except Exception as exc:
            fail += 1
            print(f'[실패] {period}  {name}: {exc}')
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f'\n총 {len(planned)}개 중 성공 {success}개, 실패 {fail}개')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('raw_dir', nargs='?', default=RAW_DIR,
                         help='원본 파일 폴더(기본값: data/raw/team_refer_backfill_source — team_refer 백필과 동일 폴더)')
    parser.add_argument('--apply', action='store_true', help='실제로 반영(기본값은 미리보기만)')
    args = parser.parse_args()
    run(args.raw_dir, args.apply)
