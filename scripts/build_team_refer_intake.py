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

나머지 컬럼(2026-09-11 (5) 추가 — 마커 치환 후에도 남는 빈 1단계부서명
백필 단계 신설):
  1단계부서명 → ① 원본 값이 "대표이사"/"삼성전자"면 무조건 2단계부서명
    (현소속부서명) 값으로 교체(_ROOT_MARKERS_DIRECT). "종합기술원"/"SAIT"
    면 보조 매핑표1(원본 값 기준)에서 2단계부서명으로 조회한 1단계부서명
    값으로 교체하고, 못 찾으면 2단계부서명 값으로 교체(_ROOT_MARKERS_LOOKUP).
    ② 그 외(4개 marker가 아닌 값)는 원본 값을 그대로 둔다.
    ③ ①②를 다 거치고도 1단계부서명이 비어 있으면(실사용 중 발견 — 원본
    자체에 1단계가 공란인 행이 있을 수 있음), 보조 매핑표2(마커 치환까지
    끝난 "최종" 값 기준, ①②의 결과를 재료로 새로 만든 2단계→1단계
    매핑표)에서 2단계부서명으로 조회한 값을 채우고, 그마저 없으면
    2단계부서명 값을 그대로 채운다(사용자 확정).
  2단계부서명 ← 원본의 "현소속부서명" 그대로(1단계 교체/백필과 무관하게
    항상 원본 값 유지).
  구분/조직코드 → 전부 빈 값(사용자 확정 — 조직코드는 사내 규정에 맞게
    사람이 조정해야 하는 값이라 이 스크립트 범위 밖). 빈 값은
    team_hierarchy.derive_hierarchy()가 각각 work_type='R&D' 기본값/
    처음 등장한 순서 기준 dep_code로 채운다(process_team_refer.py 참고)
    — "조직코드 : 과거는 추출된 데이터 순으로 나열"이라는 확정 사항과
    일치.
  사번/성명/직책 → 원본의 "직책명"/"글로벌직책명"/"직무프로필명"/
    "사원번호"/"성명" 헤더로 그 조직의 책임자를 판단해 자동으로 채운다
    (2026-09-17 추가, 같은 날 2차 수정, pipeline/team_refer_intake.py
    모듈 docstring의 _compute_title()/_build_leader_lookup() 설명 참고
    — 직책명("고문"/"자문" 포함 시 완전 제외) > 글로벌직책명("고문"/
    "회장" 포함 시 완전 제외) > 직무프로필명의 "(M)"→"PM" 순으로 판단,
    같은 조직에 후보가 여러 명 있는 경우는 실데이터에 없다고 사용자가
    확인). "(D) 과제명"/"(E) 과제명"처럼 "(알파벳 한 글자) 과제명"
    형식으로 같은 과제명을 공유하는 org_name_wd 변형 중 하나에서만
    책임자를 찾아도 나머지 변형에 그대로 전파한다(_propagate_project_
    variant_leaders(), 2026-09-17 2차 추가). 이 5개 헤더 중 하나라도
    원본에 없으면 이 채움 단계만 건너뛰고(전부 빈 값) 나머지 변환은
    그대로 진행한다.

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

from pipeline.excel_reader import read_xlsx  # noqa: E402
from pipeline.team_refer_intake import (  # noqa: E402
    _INTAKE_COLUMNS, _SRC_HEADERS, transform,
)

RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'team_refer_intake_source')
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed', 'team_refer_intake')

# 원본→인텔이크 변환 로직(헤더 매핑 규칙, 대표이사/삼성전자/종합기술원/SAIT
# 처리 등)은 전부 pipeline/team_refer_intake.py로 옮겼다(2026-09-16) —
# pipeline/process_team_refer.py의 웹 업로드 경로가 원본을 자동 감지해
# 그 모듈을 직접 재사용할 수 있게 하기 위함(사용자 요청: "원본을 넣으면
# intake.py 모듈을 거쳐서 들어갈 수 있도록"). 이 파일은 그 로직을 그대로
# 가져다 쓰는 CLI 래퍼로 남았다 — 사용법·헤더 매핑 배경 설명은 이 파일
# docstring에 그대로 유지.

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


def process_file(path: str) -> tuple:
    """한 원본 파일을 처리해 (성공 여부, 출력 경로 또는 None, 행 수, 에러
    메시지) 반환. 실제 변환 로직은 pipeline/team_refer_intake.py의
    transform()에 있다(2026-09-16 분리) — 이 함수는 파일 읽기/쓰기만
    담당한다."""
    try:
        df = _read_source(path)
    except Exception as exc:
        return False, None, 0, f'파일 읽기 실패: {exc}'

    df.columns = [str(c).strip() for c in df.columns]

    try:
        out_df = transform(df)
    except ValueError as exc:
        return False, None, 0, str(exc)

    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(OUT_DIR, f'{base}{_OUTPUT_SUFFIX}')
        out_df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    except OSError as exc:
        # 읽기 단계와 달리 저장 단계는 원래 예외 보호가 없어, 한 파일의 저장
        # 실패(예: Windows 260자 경로 길이 제한 — 원본 파일명이 길면
        # "<원본파일명>_team_refer_intake.csv" 전체 경로가 한도를 넘어
        # FileNotFoundError로 나타남)가 전체 배치 실행을 통째로 중단시켰다
        # (2026-09-11 실사용 중 발견). 이제 그 파일만 실패로 기록하고 나머지
        # 파일은 계속 처리한다.
        return False, None, 0, f'출력 파일 저장 실패: {exc}'

    return True, out_path, len(out_df), None


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
