"""
인력현황 원본(raw headcount, "1단계부서명"/"현소속부서명"/"비공식소속부서명"
3개 헤더만 있는 파일)을 team_refer 인텔이크 형식(process_team_refer._COL_MAP과
동일한 9개 컬럼) DataFrame으로 변환하는 순수 로직.

scripts/build_team_refer_intake.py(로컬에서 사람이 직접 실행하는 CLI, 파일
읽기/쓰기 담당)와 pipeline/process_team_refer.py(웹 업로드 경로에서 원본을
자동 감지해 이 모듈을 직접 호출) 양쪽이 공유한다(2026-09-16 분리 — 원래
scripts/build_team_refer_intake.py 안에 있던 로직을 그대로 옮겨온 것이라
변환 결과는 동일하다). scripts/ 쪽 CLI 사용법·헤더 매핑 규칙(대표이사/
삼성전자/종합기술원/SAIT 처리 등)의 자세한 배경 설명은 그 파일 docstring
참고 — 로직 자체를 옮기며 설명까지 중복해서 옮기지는 않았다.

── 사번/성명/직책 자동 채움(2026-09-17 추가) ─────────────────────────────────
기존에는 구분/조직코드/사번/성명/직책 5개 컬럼을 전부 빈 값으로 뒀는데,
이 중 사번/성명/직책은 원본에서 그 조직의 "책임자"를 판단할 수 있는
경우가 있어 자동으로 채운다(구분/조직코드는 여전히 빈 값 — 사용자 확정).

직책 판단(_compute_title(), 사용자 확정 2026-09-17, 우선순위 순):
  1. "직책명" 헤더 값이 있으면 그 값.
  2. (1이 없을 때) "글로벌직책명" 헤더 값이 있으면 그 값 — 단 "고문"이라는
     단어가 포함돼 있으면 그 사람은 이 조직의 책임자 후보에서 완전히
     제외한다(3번 "(M)" 체크로도 넘어가지 않고 바로 직책 없음 처리).
  3. (1·2가 전부 없을 때) "직무프로필명" 헤더 값에 "(M)"이라는 문자열이
     포함돼 있으면(부분 일치 — "연구위원(M)"도 해당) "PM".
  4. 셋 다 해당 안 되면 직책 없음(이 사람은 책임자 후보가 아님).
  "직책명"과 "글로벌직책명"은 실데이터에서 한 행에 동시에 값이 있는
  경우가 없다고 사용자가 확인함(2026-09-17) — 위 우선순위는 그 전제
  위에서 안전하다.

매핑(_build_leader_lookup()): 직책이 계산된 행만 대상으로, 그 행의
"비공식소속부서명"(=org_name_wd, 조직 단위 키)을 키 삼아 원본 "사원번호"/
"성명"/계산된 직책을 모아둔다. 같은 org_name_wd에 책임자 후보가 여러 명
있는 경우는 실데이터에 없다고 사용자가 확인함(2026-09-17) — 있더라도
마지막에 나온 값이 채택된다(안전망일 뿐, 정상 데이터에서는 발생하지
않는 경로). 이 조회표를 transform()이 만드는 조직 단위별 1행(rows)에
org_name_wd로 매칭해 사번/성명/직책 칸을 채우고, 매칭되는 책임자 후보가
없는 조직은 기존과 동일하게 빈 값으로 남긴다(사용자 확정).

이 5개 헤더("직무프로필명"/"직책명"/"글로벌직책명"/"사원번호"/"성명")는
`is_raw_format()`의 "원본 판정" 기준에는 포함하지 않는다(기존 3개 헤더
그대로) — 원본에 이 5개 중 하나라도 없으면 사번/성명/직책 자동 채움만
건너뛰고(전부 빈 값, 기존과 동일 동작) 나머지 변환은 그대로 진행한다."""
from __future__ import annotations

import pandas as pd

# 원본에서 찾을 헤더 — 이 3개가 전부 있으면 "인력현황 원본"(변환 필요)으로
# 판정한다(process_team_refer.py의 is_raw_format() 참고).
_SRC_LEVEL1 = '1단계부서명'
_SRC_LEVEL2 = '현소속부서명'
_SRC_LEVEL3 = '비공식소속부서명'
_SRC_HEADERS = [_SRC_LEVEL1, _SRC_LEVEL2, _SRC_LEVEL3]

# 사번/성명/직책 자동 채움 전용 헤더(2026-09-17 추가) — 없어도 원본 판정
# 자체에는 영향 없고, 이 채움 단계만 건너뛴다.
_SRC_JOB_PROFILE = '직무프로필명'
_SRC_TITLE = '직책명'
_SRC_GLOBAL_TITLE = '글로벌직책명'
_SRC_EMP_NO = '사원번호'
_SRC_NAME = '성명'
_LEADER_SRC_HEADERS = (_SRC_JOB_PROFILE, _SRC_TITLE, _SRC_GLOBAL_TITLE, _SRC_EMP_NO, _SRC_NAME)

_ADVISOR_MARKER = '고문'
_PM_MARKER = '(M)'
_PM_TITLE = 'PM'

# process_team_refer._COL_MAP 키와 정확히 동일한 순서/이름.
_INTAKE_COLUMNS = [
    '비공식소속부서명', '구분', '1단계부서명', '2단계부서명', '3단계부서명',
    '조직코드', '사번', '성명', '직책',
]

_ROOT_MARKERS_DIRECT = {'대표이사', '삼성전자'}
_ROOT_MARKERS_LOOKUP = {'종합기술원', 'SAIT'}
_ALL_ROOT_MARKERS = _ROOT_MARKERS_DIRECT | _ROOT_MARKERS_LOOKUP


def _compute_title(row) -> str:
    """한 행(직원 1명)의 "직책" 값을 계산한다 — 우선순위: 직책명 >
    글로벌직책명(단 "고문" 포함 시 완전 제외) > 직무프로필명의 "(M)"
    (→"PM"). 셋 다 해당 안 되면 빈 문자열(책임자 후보 아님)."""
    title_name = _clean_str(row.get(_SRC_TITLE, ''))
    if title_name:
        return title_name
    global_title = _clean_str(row.get(_SRC_GLOBAL_TITLE, ''))
    if global_title:
        return '' if _ADVISOR_MARKER in global_title else global_title
    job_profile = _clean_str(row.get(_SRC_JOB_PROFILE, ''))
    return _PM_TITLE if _PM_MARKER in job_profile else ''


def _build_leader_lookup(df: pd.DataFrame) -> dict:
    """비공식소속부서명(org_name_wd)별 {사번, 성명, 직책} 조회표를 만든다
    — _compute_title()로 직책이 계산된 행만 대상. 필요한 5개 헤더 중
    하나라도 없으면 빈 dict(호출부가 사번/성명/직책 채움 자체를
    건너뛴다)."""
    if any(h not in df.columns for h in _LEADER_SRC_HEADERS):
        return {}
    lookup: dict = {}
    for _, row in df.iterrows():
        org = _clean_str(row.get(_SRC_LEVEL3, ''))
        if not org:
            continue
        title = _compute_title(row)
        if not title:
            continue
        lookup[org] = {
            '사번': _clean_str(row.get(_SRC_EMP_NO, '')),
            '성명': _clean_str(row.get(_SRC_NAME, '')),
            '직책': title,
        }
    return lookup


def _clean_str(val) -> str:
    if val is None:
        return ''
    s = str(val).strip()
    return '' if s.lower() in ('nan', 'none', '') else s


def is_raw_format(df: pd.DataFrame) -> bool:
    """df가 (인텔이크가 아니라) "인력현황 원본" 형식인지 판정한다 —
    `_SRC_HEADERS`(1단계부서명/현소속부서명/비공식소속부서명) 3개 헤더가
    전부 있으면 원본으로 본다. "현소속부서명"은 원본에만 있는 헤더라
    이 컬럼 하나만으로도 사실상 판정 가능하지만, 명확성을 위해 3개를
    모두 확인한다."""
    return all(h in df.columns for h in _SRC_HEADERS)


def _build_upper_level_lookup(df: pd.DataFrame) -> dict | None:
    """원본에서 "1단계부서명"/"현소속부서명" 2개 헤더로 보조 매핑표(현소속
    부서명→1단계부서명)를 만든다. 둘 중 하나라도 헤더 자체가 없으면
    None(_ROOT_MARKERS_LOOKUP 조회 단계 자체를 건너뜀)."""
    if any(h not in df.columns for h in (_SRC_LEVEL1, _SRC_LEVEL2)):
        return None
    seen_pairs = set()
    lookup: dict = {}
    for _, row in df[[_SRC_LEVEL1, _SRC_LEVEL2]].iterrows():
        a = _clean_str(row[_SRC_LEVEL1])
        b = _clean_str(row[_SRC_LEVEL2])
        if not a or not b:
            continue
        if (a, b) in seen_pairs:
            continue
        seen_pairs.add((a, b))
        if a in _ALL_ROOT_MARKERS:
            continue
        lookup.setdefault(b, a)
    return lookup


def _fill_upper_level(a: str, b: str, upper_lookup: dict) -> str:
    """1단계부서명(a)이 _ROOT_MARKERS_DIRECT(대표이사/삼성전자)면 무조건
    2단계부서명(b) 값으로 교체하고, _ROOT_MARKERS_LOOKUP(종합기술원/SAIT)면
    보조 매핑표에서 b로 조회한 값으로 교체(못 찾으면 b로 폴백)한다. 그 외
    (4개 marker가 아닌 값, 빈 값 포함)는 원본 a를 그대로 반환한다."""
    if a in _ROOT_MARKERS_DIRECT:
        a = b
    elif a in _ROOT_MARKERS_LOOKUP:
        a = upper_lookup.get(b, b)
    return a


def _build_level2_lookup(triples: list) -> dict:
    """마커 치환(_fill_upper_level)까지 끝낸 (1단계, 2단계, 3단계) 중간
    결과에서 보조 매핑표2(2단계→1단계)를 만든다."""
    lookup: dict = {}
    seen_pairs: set = set()
    for a, b, _c in triples:
        if not a or not b:
            continue
        if (a, b) in seen_pairs:
            continue
        seen_pairs.add((a, b))
        lookup.setdefault(b, a)
    return lookup


def _backfill_blank_level1(a: str, b: str, level2_lookup: dict) -> str:
    """마커 치환까지 끝난 뒤에도 1단계부서명(a)이 비어 있으면 2단계부서명
    (b)으로 보조 매핑표2를 조회해 채운다. 매핑되는 값이 없으면 2단계부서명
    (b) 값을 그대로 채운다. a가 이미 채워져 있으면 그대로 반환한다."""
    if a:
        return a
    return level2_lookup.get(b, b)


def transform(df: pd.DataFrame) -> pd.DataFrame:
    """인력현황 원본 DataFrame(컬럼명 정리 완료, `_SRC_HEADERS` 포함)을
    team_refer 인텔이크 형식(9개 컬럼) DataFrame으로 변환한다.
    `_SRC_HEADERS` 중 하나라도 없으면 ValueError.

    scripts/build_team_refer_intake.py의 process_file()에 있던 변환
    로직을 파일 I/O 없이 그대로 옮긴 것 — 결과는 동일하다.

    사번/성명/직책은 _build_leader_lookup()/_compute_title()로 자동
    채운다(2026-09-17 추가, 모듈 docstring 참고) — 대상 헤더가 없으면
    빈 dict가 반환돼 기존과 동일하게 전부 빈 값으로 남는다."""
    missing = [h for h in _SRC_HEADERS if h not in df.columns]
    if missing:
        raise ValueError(f'헤더 없음: {", ".join(missing)}')

    upper_lookup = _build_upper_level_lookup(df)

    intermediate = []
    for _, row in df[_SRC_HEADERS].iterrows():
        a = _clean_str(row[_SRC_LEVEL1])
        b = _clean_str(row[_SRC_LEVEL2])
        c = _clean_str(row[_SRC_LEVEL3])
        if not any((a, b, c)):
            continue
        if upper_lookup is not None:
            a = _fill_upper_level(a, b, upper_lookup)
        intermediate.append((a, b, c))

    level2_lookup = _build_level2_lookup(intermediate)
    leader_lookup = _build_leader_lookup(df)

    rows = []
    seen = set()
    for a, b, c in intermediate:
        a = _backfill_blank_level1(a, b, level2_lookup)
        key = (a, b, c)
        if key in seen:
            continue
        seen.add(key)
        leader = leader_lookup.get(c, {})
        rows.append({
            '비공식소속부서명': c, '구분': '', '1단계부서명': a, '2단계부서명': b,
            '3단계부서명': c, '조직코드': '',
            '사번': leader.get('사번', ''), '성명': leader.get('성명', ''),
            '직책': leader.get('직책', ''),
        })

    rows.sort(key=lambda r: (r['3단계부서명'], r['2단계부서명'], r['1단계부서명']))
    return pd.DataFrame(rows, columns=_INTAKE_COLUMNS)
