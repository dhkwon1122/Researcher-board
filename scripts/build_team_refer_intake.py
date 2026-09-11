"""
인력현황 원본 엑셀(YYYYMM_That Month Headcount_*.xlsx / YYYYMM_End of Month
Headcount_*.xlsx 등, 사람이 직접 조직 계층을 정리해 넣지 않은 raw 파일)에서
"1단계부서명"/"현소속부서명"/"비공식소속부서명" 3개 헤더 컬럼만 뽑아
team_refer 인텔이크 형식(pipeline/process_team_refer.py의 _COL_MAP과 동일한
9개 컬럼)으로 변환하는 전처리 스크립트(2026-09-11 신설).

── 배경 ────────────────────────────────────────────────────────────────────
2026-09-11에 team_refer.csv를 1/2/3단계 부서명 3단 체계로 개편하면서, 그
인텔이크(팀참조시트.xlsx)는 "사람이 조직 계층을 이미 정리해 넣은 데이터"라는
전제였다. 그런데 실제로 필요한 건 "인력현황 원본(raw headcount)을 넣으면
자동으로 팀참조시트 형태를 만들어주는" 전처리 단계였다 — 이 스크립트가
그 역할을 한다. `scripts/build_past_team_refer.py`(월별 조직 개편 이력을
사람이 비교해 보는 감사용 리포트, 2026-08-31~09-02 확정)와는 목적이 달라
완전히 별도 스크립트로 분리했다(사용자 확정) — 스키마도 다르고
(build_past_team_refer.py의 출력은 team_refer.csv와 호환되지 않음), 서로
다른 목적의 도구가 한 파일에 섞이면 나중에 헷갈릴 위험이 있다는 판단.

── 헤더 매핑(사용자 확정) ───────────────────────────────────────────────────
인력현황 원본의 "비공식소속부서명"은 두 가지 역할을 동시에 한다 —
(1) researchers.csv의 org_code와 매칭되는 조직 단위 키(org_name_wd)이자,
(2) 그 조직의 3단계(리프) 부서명 그 자체(dep_3rd_name)다. 팀참조시트.xlsx
(사람이 직접 입력하는 현재 데이터)에서는 이 둘이 서로 다른 컬럼(비공식소속
부서명=org_name_wd, 3단계부서명=dep_3rd_name)으로 분리돼 있지만, 인력현황
원본에는 3단계 부서명을 별도로 정리한 컬럼이 없어(org_code 매칭키 하나뿐)
같은 값을 두 인텔이크 컬럼(비공식소속부서명/3단계부서명)에 그대로 복제해
넣는다(2026-09-11 사용자 확정 — "org_name_wd : 현재/과거 동일하게 유지").

나머지 컬럼:
  1단계부서명 → 그대로(원본 헤더가 비어 있으면 아래 백필 단계로 채움)
  2단계부서명 ← 원본의 "현소속부서명" — 단, 1단계부서명이 "대표이사"면
    2단계부서명도 "대표이사"로 동일하게 맞춘다(2026-09-11 추가 사용자
    확정 — 대표이사 직속은 그 자체로 최상위 단위라 원본의 2단계 값과
    무관하게 1/2단계를 통일). _MIRROR_TO_LEVEL2 참고.
  구분/조직코드/사번/성명/직책 → 전부 빈 값(사용자 확정 — 인력현황
    원본에서 이 값들을 자동으로 뽑아내기 어렵고, 뽑아낸다 해도 "이 사람이
    이 조직의 대표 책임자"라는 판단은 별도 정보가 필요해 이 스크립트
    범위 밖). 빈 값은 team_hierarchy.derive_hierarchy()가 각각 work_type=
    'R&D' 기본값/처음 등장한 순서 기준 dep_code로 채운다(process_team_refer.py
    참고) — "조직코드 : 과거는 추출된 데이터 순으로 나열"이라는 확정 사항과
    일치.

── 이 스크립트가 만드는 것은 "중간 산출물"이다(사용자 확정) ───────────────────
결과 CSV는 그대로 team_refer.csv에 반영되지 않는다 — 사람이 열어서 검토·
보정(특히 조직코드는 사내 규정에 맞게 사람이 조정해야 하는 값)한 뒤, 관리자
화면 "팀/리더 참조" 탭의 업로드 섹션에 그대로(CSV 그대로, xlsx로 옮겨 담을
필요 없음 — pipeline/process_team_refer.py가 CSV도 직접 읽도록 함께
확장했다) 올리면 된다.

── 적용 대상(사용자 확정) ───────────────────────────────────────────────────
과거 데이터 일괄 백필뿐 아니라 매달 새로 올라오는 최신 인력현황 파일에도
그대로 쓸 수 있다 — 한 번에 여러 달치 파일을 넣으면 파일별로 각각의
산출물을 만든다(파일마다 그 시점의 조직 스냅샷 1개).

읽기 방식은 scripts/build_past_team_refer.py와 동일: 사내 DRM이 걸린
xlsx는 xlwings(Excel COM)로, 이미 DRM이 제거된 .csv는 그대로 pandas로
읽는다(같은 진단 이력 — docs/CLAUDE.md 2026-09-02 참고). .xlsx는 2번째
행이 헤더(1번째 행 무시), .csv는 1번째 행이 헤더.

사용법:
  python scripts/build_team_refer_intake.py
  python scripts/build_team_refer_intake.py "C:\\경로\\인력현황파일.xlsx"
  python scripts/build_team_refer_intake.py "C:\\경로\\원본이_정상적으로_열리는_폴더"
"""
import csv
import glob
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.excel_reader import clean_str, read_xlsx  # noqa: E402

RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'team_refer_intake_source')
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed', 'team_refer_intake')

# 원본에서 찾을 헤더(1단계부서명/현소속부서명/비공식소속부서명) — 순서는
# 아래 인텔이크 출력 컬럼(_INTAKE_COLUMNS)과 다르므로 별도로 유지.
_SRC_LEVEL1 = '1단계부서명'
_SRC_LEVEL2 = '현소속부서명'
_SRC_LEVEL3 = '비공식소속부서명'
_SRC_HEADERS = [_SRC_LEVEL1, _SRC_LEVEL2, _SRC_LEVEL3]

# pipeline/process_team_refer.py의 _COL_MAP 키와 정확히 동일한 순서/이름 —
# 이 순서 그대로 저장해야 process_team_refer.py가 헤더 텍스트로 컬럼을
# 찾는 방식과 어긋나지 않는다(위치가 아니라 이름으로 찾으므로 순서 자체는
# 필수는 아니지만, 그대로 맞춰 헷갈림을 없앤다).
_INTAKE_COLUMNS = [
    '비공식소속부서명', '구분', '1단계부서명', '2단계부서명', '3단계부서명',
    '조직코드', '사번', '성명', '직책',
]

# "이미 최상위" 마커 — build_past_team_refer.py의 ROOT_MARKERS와 동일 개념.
_ROOT_MARKERS_B = {'종합기술원', 'SAIT'}
_ROOT_MARKERS_DIRECT = {'대표이사', '삼성전자'}
_ROOT_MARKERS_ORG = {'종합기술원', 'SAIT'}

# 1단계부서명이 이 값이면 같은 행의 2단계부서명도 동일한 값으로 맞춘다
# (2026-09-11 사용자 확정) — "대표이사"는 그 자체로 이미 조직 전체를 대표하는
# 최상위 단위라, 원본의 2단계부서명(현소속부서명)에 뭐가 적혀 있든 무시하고
# 1단계와 2단계를 같은 값으로 통일한다. _ROOT_MARKERS_DIRECT(대표이사/삼성전자
# 둘 다 대상)와 달리 이 규칙은 "대표이사"에만 적용 — "삼성전자"는 기존
# _fill_upper_level() 규칙(a를 b로 교체) 그대로 유지.
_MIRROR_TO_LEVEL2 = {'대표이사'}

_OUTPUT_SUFFIX = '_team_refer_intake.csv'


def _list_source_files(raw_dir: str) -> list:
    """raw_dir 안의 모든 .xlsx/.csv — 임시 잠금 파일("~$")과 이 스크립트
    자신의 출력 파일은 제외."""
    candidates = glob.glob(os.path.join(raw_dir, '*.xlsx')) + glob.glob(os.path.join(raw_dir, '*.csv'))
    return sorted(
        p for p in candidates
        if not os.path.basename(p).startswith('~$') and not p.endswith(_OUTPUT_SUFFIX)
    )


def _read_source(path: str):
    """.xlsx는 read_xlsx()(xlwings, DRM 파일용, 2번째 행 헤더)로, 이미 DRM이
    제거된 .csv는 xlwings/Excel 없이 그대로 pandas로 읽는다(1번째 행 헤더)."""
    if path.lower().endswith('.csv'):
        return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    return read_xlsx(path, header_row=1)


def _build_upper_level_lookup(df: pd.DataFrame) -> dict | None:
    """원본에서 "1단계부서명"/"현소속부서명" 2개 헤더로 보조 매핑표(2단계→
    1단계)를 만든다 — 1단계부서명이 비어 있는 행의 백필용. 둘 중 하나라도
    없으면 None(백필 단계 자체를 건너뜀)."""
    if any(h not in df.columns for h in (_SRC_LEVEL1, _SRC_LEVEL2)):
        return None
    lookup: dict = {}
    for _, row in df[[_SRC_LEVEL1, _SRC_LEVEL2]].iterrows():
        a = clean_str(row[_SRC_LEVEL1])
        b = clean_str(row[_SRC_LEVEL2])
        if a and b:
            lookup.setdefault(b, a)
    return lookup


def _fill_upper_level(a: str, b: str, upper_lookup: dict) -> str:
    """1단계부서명(a)이 비어 있으면 2단계부서명(b)으로 보조 매핑표를 조회해
    채운다. build_past_team_refer.py의 _fill_upper_level()과 동일한 규칙
    (d~g, 2026-09-02 정정본)을 그대로 따른다."""
    if not a:
        if b in _ROOT_MARKERS_B:
            a = b
        else:
            a = upper_lookup.get(b, b)
    if a in _ROOT_MARKERS_DIRECT:
        a = b
    elif a in _ROOT_MARKERS_ORG:
        a = upper_lookup.get(b, b)
    return a


def process_file(path: str) -> tuple:
    """한 원본 파일을 처리해 (성공 여부, 출력 경로 또는 None, 행 수, 에러
    메시지) 반환."""
    try:
        df = _read_source(path)
    except Exception as exc:
        return False, None, 0, f'파일 읽기 실패: {exc}'

    df.columns = [str(c).strip() for c in df.columns]

    missing = [h for h in _SRC_HEADERS if h not in df.columns]
    if missing:
        return False, None, 0, f'헤더 없음: {", ".join(missing)}'

    upper_lookup = _build_upper_level_lookup(df)

    rows = []
    seen = set()
    for _, row in df[_SRC_HEADERS].iterrows():
        a = clean_str(row[_SRC_LEVEL1])
        b = clean_str(row[_SRC_LEVEL2])
        c = clean_str(row[_SRC_LEVEL3])
        if not any((a, b, c)):
            continue
        if a in _MIRROR_TO_LEVEL2:
            # 1단계부서명이 "대표이사"면 2단계부서명도 동일한 값으로 맞춘다
            # (2026-09-11 추가 사용자 확정) — 아래 _fill_upper_level()의
            # "대표이사면 b로 교체" 규칙(g-1)보다 먼저 적용해, 이 값이 b로
            # 다시 덮이는(a=b가 되면서 원래 b값으로 바뀌는) 일이 없게 한다.
            b = a
        if upper_lookup is not None:
            a = _fill_upper_level(a, b, upper_lookup)
        key = (a, b, c)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            '비공식소속부서명': c, '구분': '', '1단계부서명': a, '2단계부서명': b,
            '3단계부서명': c, '조직코드': '', '사번': '', '성명': '', '직책': '',
        })

    # 조직 위계상 큰 단위부터 눈에 잘 띄도록 1단계→2단계→3단계 오름차순
    # 정렬(build_past_team_refer.py와 동일한 관례) — 사람이 검토할 때
    # 보기 편하게 하려는 것일 뿐, 조직코드(사내 정렬 규정)는 사람이 검토
    # 후 직접 채우는 값이라 이 정렬과 무관하다.
    rows.sort(key=lambda r: (r['1단계부서명'], r['2단계부서명'], r['3단계부서명']))

    os.makedirs(OUT_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(OUT_DIR, f'{base}{_OUTPUT_SUFFIX}')

    out_df = pd.DataFrame(rows, columns=_INTAKE_COLUMNS)
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    return True, out_path, len(rows), None


def main(raw_arg: str = RAW_DIR):
    """raw_arg가 파일이면 그 파일 하나만, 폴더면 폴더 안 전체를 처리한다."""
    if os.path.isfile(raw_arg):
        files = [raw_arg]
    else:
        raw_dir = raw_arg
        if not os.path.isdir(raw_dir) or not _list_source_files(raw_dir):
            os.makedirs(raw_dir, exist_ok=True)
            print(f'[안내] {raw_dir} 에 인력현황 원본 파일을 먼저 넣어주세요.')
            return
        files = _list_source_files(raw_dir)

    success = 0
    fail = 0
    for path in files:
        name = os.path.basename(path)
        ok, out_path, n_rows, err = process_file(path)
        if ok:
            success += 1
            print(f'[OK]   {name} → {os.path.basename(out_path)} ({n_rows}개 조직 단위)')
        else:
            fail += 1
            print(f'[실패] {name}: {err}', file=sys.stderr)

    print(f'\n총 {len(files)}개 중 성공 {success}개, 실패 {fail}개')
    if success:
        print(
            f'\n산출물은 {OUT_DIR} 에 저장됐습니다 — 열어서 검토·보정(특히 조직코드) 후 '
            f'관리자 화면 "팀/리더 참조" 탭 업로드 섹션에 CSV 그대로 올리면 됩니다.'
        )


if __name__ == '__main__':
    # 파일 하나 또는 폴더를 인자로 넘길 수 있다(scripts/build_past_team_refer.py와
    # 동일한 관례 — 원본이 저장소 data/ 폴더에서 DRM 때문에 안 열리면, 실제로
    # 열리는 다른 폴더를 지정).
    #   python scripts/build_team_refer_intake.py
    #   python scripts/build_team_refer_intake.py "C:\경로\인력현황.xlsx"
    #   python scripts/build_team_refer_intake.py "C:\경로\원본폴더"
    main(sys.argv[1] if len(sys.argv) > 1 else RAW_DIR)
