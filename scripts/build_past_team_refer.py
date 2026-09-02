"""
과거 조직 원본 엑셀에서 "1단계부서명"/"현소속부서명"/"비공식소속부서명" 3개
헤더 컬럼만 그대로 뽑아 <원본파일명>_team_refer.csv로 저장하는 스크립트
(2026-09-02, 사용자 확정 — 이 파일의 이전 버전을 완전히 대체).

이전 버전과의 차이(1차): 이전 버전은 "End of Month Headcount" 162컬럼 고정
포맷을 전제로 BF/S/EV/ES 등 고정 열 위치 + VLOOKUP 방식 상위부서명 계산 +
월별 team_change.csv 비교까지 했다. 이번 버전은 그런 계산이 전혀 없다 —
헤더 텍스트로 3개 컬럼을 찾아 있는 그대로 복사하고, 중복 제거·정렬만 한다
(원본 파일마다 열 위치가 달라도 헤더 텍스트만 맞으면 동작).

이전 버전과의 차이(2차, 이번 수정) — 출력 형식을 xlsx → csv로 재전환:
이 스크립트는 원래 2026-08-31 세션에서 xlsx로 출력했다가 openpyxl로 새로 쓴
xlsx의 내부 XML 메타데이터(예: <dimension> 태그가 실제 셀 범위와 어긋남)
때문에 Excel이 "손상됨"으로 인식해 못 여는 문제를 겪고, 그때 이미 csv로
바꿔서 해결한 이력이 있다(data/processed/CLAUDE.md 2026-08-31 참고). 그런데
직후 세션에서 "신규 엑셀파일 생성"이라는 요청을 문자 그대로 받아 다시 xlsx
출력(openpyxl)으로 되돌렸고, 그 결과 사용자가 "지난번과 마찬가지 사유"로
또 실패했다고 보고 — 바로 이 xlsx 출력 자체의 구조적 손상 위험이 재발한
것으로 판단해 다시 csv로 되돌린다. researchers.csv를 만드는
pipeline/process_researchers.py(→ pipeline/merge_utils.write_merged_with_
valid_period() → `df.to_csv(out_path, index=False, encoding='utf-8-sig',
quoting=csv.QUOTE_NONNUMERIC)`)와 정확히 동일한 저장 방식을 그대로 쓴다
(사용자 요청 "researchers.csv 파일과 동일하게") — CSV는 순수 텍스트라
OOXML/zip 구조 자체가 없어 이런 손상이 구조적으로 발생할 수 없다.
이에 맞춰 "1행은 비우고 2행에 헤더"라는 이전 xlsx 전용 스펙도 버렸다 —
researchers.csv를 비롯한 이 저장소의 다른 모든 csv 산출물은 헤더가 1행에
바로 있으므로, "동일하게"라는 요청에 맞춰 이 스크립트의 출력도 1행 헤더로
통일한다.

읽기 쪽 비교 — pipeline/process_researchers.py와 호출 파라미터는 동일(그대로
유지): researchers.csv는 평소엔 원본 xlsx를 직접 안 읽고 사전에 DRM을
제거해 둔 data/raw_csv/researchers.csv(또는 DB)를 읽지만, 관리자 웹 업로드로
원본 xlsx를 직접 받을 때는 `find_latest()`로 파일을 찾은 뒤
`read_xlsx(path, header_row=_RESEARCHERS_HEADER_ROW)`로 읽고 바로 이어서
`df.columns = [str(c).strip() for c in df.columns]`로 컬럼명을 한 번 더
정리한다 — 이 스크립트도 header_row/컬럼 재-strip은 정확히 이 방식과 같다.

이전 버전과의 차이(3차) — visible=True 시도했으나 동일 실패, 되돌림:
"researchers.csv 처리방식과 동일하게" 요청에 맞춰 위와 같이 호출 파라미터를
전부 대조했지만 차이가 없었는데도, 실제로 "Excel file format cannot be
determined, you must specify an engine manually"(pandas 폴백 실패)와
"(-2147352567, '예외가 발생했습니다.', (0, 'Microsoft Excel', ...)"(xlwings
COM 자동화 자체의 실패)가 보고됐다. pipeline/excel_reader.read_xlsx()에
`visible` 매개변수를 추가해 Excel 창을 화면에 띄운 채로 열어봤지만(2026-09-02
1차 수정) 사용자가 로컬에서 재현한 결과 여전히 동일한 에러 — 즉 창이
보이는지 여부와 무관하게 xlwings의 `app.books.open()` 호출 자체가 이
파일들에 대해 곧바로 실패한다. 이는 (팝업이 안 떠서가 아니라) xlwings/COM
자동화가 이 DRM 파일의 셸(탐색기/더블클릭) 기반 복호화 후킹을 아예 거치지
못해서일 가능성이 높다 — 이 경우 코드로는 해결할 수 없고, 파일을 먼저
수동으로(탐색기에서 열어 DRM 복호화 → 다른 이름으로 저장) 평문으로 만들어야
한다.

이전 버전과의 차이(4차, 이번 수정) — 이미 복호화된 .csv도 입력으로 허용:
위 진단에 따라, 사용자가 각 원본을 Excel에서 수동으로 열어(DRM 복호화)
"다른 이름으로 저장"으로 .csv로 저장해 두면 이 스크립트가 xlwings/read_xlsx()
를 아예 거치지 않고 그 .csv를 바로 읽도록 지원을 추가했다 —
`pipeline/source_reader.read_source()`가 (DB 다음으로) raw_csv를 읽는 방식과
정확히 동일하게 `pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')`
로 읽는다(이 경로는 xlwings/Excel/COM이 전혀 필요 없어 DRM 자동화 문제와
무관 — "researchers.csv 처리방식과 동일하게"에 가장 가깝게 맞춘 부분).
.xlsx는 기존처럼 read_xlsx()로 시도하되 visible 인자는 빼서(효과가 없었으므로)
xlsx_to_raw_csv.py의 실제 호출과 다시 완전히 동일하게 맞췄다.

입력: data/raw/past_team_refer/ 안의 모든 .xlsx 또는 .csv (Excel이 파일을
열어 두었을 때 생기는 임시 잠금 파일 "~$*.xlsx"와 이 스크립트 자신이 만든
출력 파일 패턴 "*_team_refer.csv"는 제외). .xlsx는 2번째 행이 헤더이고
1번째 행은 무시, 시트는 항상 첫 번째 시트만 쓴다. 이미 DRM이 제거된 .csv는
1번째 행을 헤더로 그대로 읽는다(엑셀에서 "다른 이름으로 저장"한 결과는
보통 헤더가 그대로 1행에 있다 — 만약 원본처럼 2행에 헤더가 있는 형태로
저장했다면 이 스크립트가 헤더를 못 찾아 실패 처리되니 1행 헤더로 저장해야
한다).

출력: data/processed/past_team_refer/<원본파일명>_team_refer.csv (utf-8-sig,
researchers.csv와 동일한 pandas to_csv 저장 방식)
  - 1열 = 1단계부서명(dep_name), 2열 = 현소속부서명(middle_dep_name),
    3열 = 비공식소속부서명(pjt_part_name) — 헤더 텍스트는 원본 그대로 유지,
    1행에 바로 위치(researchers.csv 등과 동일한 관례).
  - A~C 조합 기준 중복 제거(먼저 나온 행 유지), A~C가 전부 빈 행은 제외하되
    일부만 빈 행은 그대로 유지한다(사용자 확정).
  - 정렬: 안정 정렬을 C→B→A 순서로 연쇄 적용해, 최종적으로 A(1단계부서명)가
    1순위, B(현소속부서명)가 2순위, C(비공식소속부서명)가 3순위인 오름차순이
    되도록 한다(조직 위계상 큰 단위부터 정렬하는 게 자연스럽다는 해석 —
    사용자가 원래 "C→B→A 오름차순 정렬"이라고 표현한 것을 이 순서로 구현).

읽기: 사내 DRM이 걸린 xlsx는 xlwings(Excel COM)로만 열 수 있어
pipeline/excel_reader.read_xlsx()를 그대로 쓴다 — Windows PC에 Excel이
설치돼 있어야 하고, 없으면 자동으로 pandas 방식으로 폴백한다(그 경우 원본이
실제 DRM 파일이면 다시 같은 에러가 난다). 이 스크립트 자체는 xlwings/Excel이
없는 환경(리눅스 개발 서버 등)에서도 비DRM 파일로 로직 검증은 가능하다.

헤더 일부만 있는 파일 처리: 3개 헤더 중 하나라도 없으면 그 파일은 실패
처리하고 다음 파일로 넘어간다(부분 헤더로 어설프게 만들지 않음, 사용자
확정). 마지막에 총 파일 수/성공/실패 개수를 요약해 출력한다.

이전 버전과의 차이(5차, 이번 수정) — 원본 폴더를 인자로 지정 가능:
탐색기에서 직접 더블클릭해도 안 열리는 것까지 확인했는데(2026-09-02),
"다른 폴더에서는 동일한 파일이 잘 열린다"는 것도 함께 확인됨 — 파일
내용이 아니라 **경로 자체**를 DRM/보안 프로그램이 신뢰 여부 판단에 쓰는
정책일 가능성이 높다(이 git 저장소의 data/ 폴더가 신뢰 목록에 없을 수
있음). 이 경우 저장소 data/ 폴더가 승인될 때까지 기다릴 필요 없이, 파일이
실제로 열리는 그 폴더를 그대로 원본 위치로 지정해 실행할 수 있도록
RAW_DIR을 CLI 인자로 오버라이드할 수 있게 했다 — 출력은 항상 저장소 안
OUT_DIR(data/processed/past_team_refer/)로 저장된다(원본 폴더 위치와 무관).

이전 버전과의 차이(6차, 이번 수정) — 저장 후 A열(1단계부서명) 백필 단계 추가:
같은 원본 파일에서 "1단계부서명"/"2단계부서명" 2개 헤더로 보조 매핑표("을":
2단계부서명 → 1단계부서명, `_build_upper_level_lookup()`)를 하나 더 만들고,
이미 정렬·저장 대상으로 확정된 3열 데이터("갑")의 빈 A열을 채운다
(`_fill_upper_level()`, 사용자 확정 2026-09-02):
  - A가 비어 있고 B(현소속부서명)가 "종합기술원"/"SAIT"(이전 버전의
    ROOT_MARKERS와 동일 개념 — 이미 최상위)면 을 조회 없이 바로 A=B.
  - 그 외 A가 비어 있으면 을에서 B(현소속부서명)로 2단계부서명을 찾아,
    일치하면 그 1단계부서명을 A로, 못 찾으면 A=B(현소속부서명 그대로).
  - (원래부터 A가 채워져 있던 행 포함, 모든 행 대상) A가 "대표이사" 또는
    "삼성전자"(_ROOT_MARKERS_DIRECT, "삼성전자"는 2026-09-02 추가로 "대표
    이사"와 동일하게 취급)면 B 값으로 그대로 교체하고, "종합기술원"/"SAIT"
    면(2026-09-02 정정 — 처음엔 이 값들도 무조건 B로 교체했으나, 이 둘은
    무조건 B로 덮지 않고) 갑의 B를 을에서 한 번 더 조회해(d와 동일 방식)
    더 정밀한 1단계부서명으로 교체한다(못 찾으면 e와 동일하게 A=B로 폴백,
    사용자 확정) — 예를 들어 을에 "종합기술원"의 상위가 "SAIT"라는 행이
    있으면 A가 "종합기술원"에서 한 단계 더 정밀한 "SAIT"로 바뀔 수 있다.
"2단계부서명" 헤더가 원본에 없어 을을 못 만들면 이 백필 단계만 건너뛰고
3열 추출·저장(기존 흐름)은 그대로 진행한다(사용자 확정) — 이 경우 결과
줄에 "A열 백필 생략" 비고가 함께 출력된다. 을 자체는 파일로 저장하지
않고(사용자 확정) 조회용으로만 잠깐 만들어 쓴다. 백필로 A 값이 바뀌면
최종 정렬(A 1순위/B 2순위/C 3순위)이 깨지지 않도록 재정렬하고, 두 행이
백필 후 완전히 같아졌을 수 있어 중복도 다시 제거한 뒤 저장한다(기존
<원본파일명>_team_refer.csv를 그대로 덮어씀, 사용자 확정 — 별도 파일 안 만듦).

사용법:
  python scripts/build_past_team_refer.py
  python scripts/build_past_team_refer.py "C:\\경로\\원본이_정상적으로_열리는_폴더"
"""
import csv
import glob
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# xlwings(실제 Excel COM 자동화) 기반 리더 — 이 프로젝트의 다른 모든 원천
# 처리기와 동일하게, 사내 DRM이 걸린 xlsx는 plain pandas/openpyxl로 못 열고
# ("Excel file format cannot be determined" 에러) xlwings로 실제 Excel을
# 띄워서 읽어야 한다(pipeline/excel_reader.py 독스트링 참고).
from pipeline.excel_reader import clean_str, read_xlsx  # noqa: E402

RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'past_team_refer')
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed', 'past_team_refer')

# (원본 헤더 텍스트, 의미상 영문 이름) — 순서 그대로 출력 컬럼 순서가 된다.
HEADERS = [
    ('1단계부서명', 'dep_name'),
    ('현소속부서명', 'middle_dep_name'),
    ('비공식소속부서명', 'pjt_part_name'),
]
HEADER_TEXTS = [h for h, _ in HEADERS]

# 저장(6) 이후 A열(1단계부서명) 백필 단계(사용자 확정 2026-09-02)에서 쓰는
# 보조 매핑표("을")의 원본 헤더 — 같은 원본 파일에서 위 HEADER_TEXTS와는
# 다른 헤더 쌍을 한 번 더 찾는다.
UPPER_HEADERS = ['1단계부서명', '2단계부서명']

# "이미 최상위" 마커(이전 버전 스크립트의 ROOT_MARKERS와 동일 개념).
# f) 갑의 B(현소속부서명)가 이 값이면 을 조회 없이 바로 A=B.
_ROOT_MARKERS_B = {'종합기술원', 'SAIT'}
# g) 갑의 A(1단계부서명)가 이 값이면(원래부터 채워져 있던 행 포함, 모든 행
# 대상) 처리 — 2026-09-02 정정: "대표이사"/"삼성전자"는 을 조회 없이 그대로
# B 값으로 교체하지만("삼성전자" 2026-09-02 추가, "대표이사"와 동일 취급),
# "종합기술원"/"SAIT"는 무조건 B로 덮지 않고 갑의 B를 을에서 한 번 더
# 조회해(d와 동일 방식) 더 정밀한 상위부서명으로 교체한다(조회 실패 시
# 사용자 확정으로 e와 동일하게 A=B로 폴백).
_ROOT_MARKERS_DIRECT = {'대표이사', '삼성전자'}
_ROOT_MARKERS_ORG = {'종합기술원', 'SAIT'}


_OUTPUT_SUFFIX = '_team_refer.csv'


def _list_source_files(raw_dir: str = RAW_DIR) -> list:
    """raw_dir 안의 모든 .xlsx/.csv — Excel이 파일을 열어 둔 동안 생기는 임시
    잠금 파일("~$"로 시작)과 이 스크립트 자신이 만든 출력 파일(재실행 시
    자기 출력을 다시 원본으로 잘못 집어먹지 않도록)은 제외한다."""
    candidates = glob.glob(os.path.join(raw_dir, '*.xlsx')) + glob.glob(os.path.join(raw_dir, '*.csv'))
    return sorted(
        p for p in candidates
        if not os.path.basename(p).startswith('~$') and not p.endswith(_OUTPUT_SUFFIX)
    )


def _read_source(path: str):
    """.xlsx는 read_xlsx()(xlwings, DRM 파일용)로, 이미 DRM이 제거된 .csv는
    xlwings/Excel 없이 pipeline/source_reader.read_source()와 정확히 동일한
    방식(`pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')`)으로
    읽는다 — csv 경로는 DRM 자동화 문제와 아예 무관하다."""
    if path.lower().endswith('.csv'):
        return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    # xlsx_to_raw_csv.py의 실제 호출(`read_xlsx(src_path, header_row=header_row)`)과
    # 정확히 동일 — sheet 인자도 생략해 기본값(0)을 그대로 쓴다.
    return read_xlsx(path, header_row=1)


def _build_upper_level_lookup(path: str) -> dict | None:
    """같은 원본 파일에서 "1단계부서명"/"2단계부서명" 2개 헤더로 보조 매핑표
    ("을": 2단계부서명 → 1단계부서명)를 만든다(사용자 확정 2026-09-02, a~c).
    두 헤더 중 하나라도 없으면 None을 반환 — 호출부(process_file)가 이
    경우 백필 단계 자체를 건너뛴다(3열 추출/저장은 정상 진행, 사용자 확정).
    "을" 자체는 파일로 저장하지 않고 이 함수 안에서만 만들어 조회용 dict로
    돌려준다(사용자 확정)."""
    try:
        df = _read_source(path)
    except Exception:
        return None
    df.columns = [str(c).strip() for c in df.columns]
    if any(h not in df.columns for h in UPPER_HEADERS):
        return None

    rows = []
    seen = set()
    for _, row in df[UPPER_HEADERS].iterrows():
        vals = tuple(clean_str(row[h]) for h in UPPER_HEADERS)
        if not any(vals):          # A+B 전부 빈 행은 제외(일부만 빈 행은 유지, b)
            continue
        if vals in seen:           # A+B 조합 중복 제거(먼저 나온 행 유지, b)
            continue
        seen.add(vals)
        rows.append(vals)

    # 안정 정렬을 B→A 순으로 연쇄 적용 → 최종 A 1순위/B 2순위 오름차순(c).
    rows.sort(key=lambda r: r[1])
    rows.sort(key=lambda r: r[0])

    # 조회용 dict(2단계부서명 → 1단계부서명) — 같은 B가 서로 다른 A에 걸려
    # 있는 드문 경우, 위에서 A 오름차순으로 정렬해뒀으므로 사전식으로 가장
    # 앞선(작은) A가 우선 채택된다(setdefault로 첫 값만 유지).
    lookup: dict = {}
    for a, b in rows:
        lookup.setdefault(b, a)
    return lookup


def _fill_upper_level(rows: list, upper_lookup: dict) -> list:
    """갑(A=1단계부서명, B=현소속부서명, C=비공식소속부서명)의 빈 A열을
    upper_lookup("을": 2단계부서명 → 1단계부서명)으로 채운다(사용자 확정
    2026-09-02, d~g — g는 같은 날 정정).
      f) A가 비어 있고 B가 이미 최상위 마커(_ROOT_MARKERS_B)면 을 조회 없이
         바로 A=B(을 조회보다 먼저 체크).
      d) A가 비어 있고 위 f에 해당하지 않으면 을에서 B를 찾아 있으면 그
         1단계부서명(을의 A)을 갑의 A로.
      e) 을에서도 못 찾으면 A=B(현소속부서명 그대로).
      g) (원래부터 A가 채워져 있던 행 포함, 모든 행 대상) A가:
         - "대표이사"/"삼성전자"(_ROOT_MARKERS_DIRECT, "삼성전자"는
           2026-09-02 추가)면 B 값으로 그대로 교체.
         - "종합기술원"/"SAIT"(_ROOT_MARKERS_ORG)면 무조건 B로 덮지 않고,
           d와 동일하게 갑의 B를 을에서 한 번 더 조회해 더 정밀한
           1단계부서명으로 교체(예: 을에 "종합기술원"의 상위가 "SAIT"라는
           행이 있으면 A가 "종합기술원"→"SAIT"로 한 단계 더 정밀해짐).
           을에서 못 찾으면 e와 동일하게 A=B로 폴백(사용자 확정)."""
    filled = []
    for a, b, c in rows:
        if not a:
            if b in _ROOT_MARKERS_B:
                a = b                          # f
            else:
                a = upper_lookup.get(b, b)     # d(찾음) / e(못 찾음 → B 그대로)
        if a in _ROOT_MARKERS_DIRECT:
            a = b                              # g-1) 대표이사/삼성전자 → B 그대로
        elif a in _ROOT_MARKERS_ORG:
            a = upper_lookup.get(b, b)         # g-2) 종합기술원/SAIT → 을 재조회(찾음/e 폴백)
        filled.append((a, b, c))
    return filled


def process_file(path: str) -> tuple:
    """한 원본 파일을 처리해 (성공 여부, 출력 경로 또는 None, 행 수, 에러 메시지,
    비고) 반환. read_xlsx()의 header_row는 0-based이므로 1을 넘기면 물리적
    2번째 행이 헤더가 된다(1번째 행은 자동으로 무시).
    pipeline/process_researchers.py가 원본 xlsx를 직접 읽는 경로와 동일하게
    읽은 직후 컬럼명을 한 번 더 strip한다."""
    try:
        df = _read_source(path)
    except Exception as exc:
        return False, None, 0, f'파일 읽기 실패: {exc}', None

    df.columns = [str(c).strip() for c in df.columns]

    missing = [h for h in HEADER_TEXTS if h not in df.columns]
    if missing:
        return False, None, 0, f'헤더 없음: {", ".join(missing)}', None

    # 3개 컬럼 값을 그대로 뽑는다(가공 없음) — clean_str()으로 None/NaN류만
    # 빈 문자열로 통일(excel_reader.py 공통 관례).
    rows = []
    seen = set()
    for _, row in df[HEADER_TEXTS].iterrows():
        vals = tuple(clean_str(row[h]) for h in HEADER_TEXTS)
        if not any(vals):          # A~C 전부 빈 행은 제외(일부만 빈 행은 유지)
            continue
        if vals in seen:           # A+B+C 조합 중복 제거(먼저 나온 행 유지)
            continue
        seen.add(vals)
        rows.append(vals)

    # 안정 정렬을 C→B→A 순으로 연쇄 적용 → 최종 A 1순위/B 2순위/C 3순위 오름차순.
    rows.sort(key=lambda r: r[2])
    rows.sort(key=lambda r: r[1])
    rows.sort(key=lambda r: r[0])

    # 저장(6) 이후 A열(1단계부서명) 백필 단계(사용자 확정 2026-09-02, d~g) —
    # "2단계부서명" 헤더가 없어 을을 못 만들면 이 단계만 건너뛰고 3열 결과는
    # 그대로 저장한다(사용자 확정).
    note = None
    upper_lookup = _build_upper_level_lookup(path)
    if upper_lookup is None:
        note = 'A열 백필 생략("2단계부서명" 헤더 없음)'
    else:
        rows = _fill_upper_level(rows, upper_lookup)
        # 백필로 A값이 바뀐 행이 있으므로 최종 오름차순(A 1순위/B 2순위/C
        # 3순위)이 깨지지 않도록 다시 정렬하고, 백필 후 (A,B,C)가 서로
        # 겹치게 된 행이 생겼을 수 있어 중복도 다시 제거한다.
        rows.sort(key=lambda r: r[2])
        rows.sort(key=lambda r: r[1])
        rows.sort(key=lambda r: r[0])
        dedup_rows = []
        seen = set()
        for r in rows:
            if r in seen:
                continue
            seen.add(r)
            dedup_rows.append(r)
        rows = dedup_rows

    os.makedirs(OUT_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(OUT_DIR, f'{base}_team_refer.csv')

    # researchers.csv와 정확히 동일한 저장 방식(pipeline/merge_utils.py
    # write_merged_with_valid_period() 참고) — CSV는 순수 텍스트라 xlsx
    # 저장 때 겪은 OOXML 구조 손상이 애초에 발생할 수 없다.
    out_df = pd.DataFrame(rows, columns=HEADER_TEXTS)
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    return True, out_path, len(rows), None, note


def main(raw_dir: str = RAW_DIR):
    if not os.path.isdir(raw_dir) or not _list_source_files(raw_dir):
        os.makedirs(raw_dir, exist_ok=True)
        print(f'[안내] {raw_dir} 에 원본 엑셀 파일을 먼저 넣어주세요.')
        return

    files = _list_source_files(raw_dir)
    success = 0
    fail = 0
    for path in files:
        name = os.path.basename(path)
        ok, out_path, n_rows, err, note = process_file(path)
        if ok:
            success += 1
            suffix = f' — {note}' if note else ''
            print(f'[OK]   {name} → {os.path.basename(out_path)} ({n_rows}행){suffix}')
        else:
            fail += 1
            print(f'[실패] {name}: {err}', file=sys.stderr)

    print(f'\n총 {len(files)}개 중 성공 {success}개, 실패 {fail}개')


if __name__ == '__main__':
    # 원본 폴더를 CLI 인자로 넘길 수 있다(2026-09-02 추가) — 사용자가 같은
    # 파일을 data/raw/past_team_refer/에 두면 열기 자체가 안 되고(탐색기
    # 더블클릭도 실패), 다른 폴더에 두면 정상적으로 열린다고 확인 — DRM/보안
    # 프로그램(NASCA 등)이 파일 내용이 아니라 "신뢰된 경로" 여부로 복호화를
    # 판단하는 정책일 가능성이 높다(이 git 저장소의 data/ 폴더는 그런 신뢰
    # 목록에 없을 수 있음). 이 경우 저장소 data/ 폴더의 IT 승인을 기다리는
    # 대신, 파일이 실제로 열리는 그 폴더를 그대로 원본 위치로 지정해 쓰면
    # 된다 — 출력은 항상 OUT_DIR(data/processed/past_team_refer/, 저장소 안)
    # 로 저장된다.
    #   python scripts/build_past_team_refer.py                 (기본: data/raw/past_team_refer/)
    #   python scripts/build_past_team_refer.py "C:\경로\원본폴더"  (다른 폴더 지정)
    main(sys.argv[1] if len(sys.argv) > 1 else RAW_DIR)
