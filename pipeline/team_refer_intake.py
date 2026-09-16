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
"""
from __future__ import annotations

import pandas as pd

# 원본에서 찾을 헤더 — 이 3개가 전부 있으면 "인력현황 원본"(변환 필요)으로
# 판정한다(process_team_refer.py의 is_raw_format() 참고).
_SRC_LEVEL1 = '1단계부서명'
_SRC_LEVEL2 = '현소속부서명'
_SRC_LEVEL3 = '비공식소속부서명'
_SRC_HEADERS = [_SRC_LEVEL1, _SRC_LEVEL2, _SRC_LEVEL3]

# process_team_refer._COL_MAP 키와 정확히 동일한 순서/이름.
_INTAKE_COLUMNS = [
    '비공식소속부서명', '구분', '1단계부서명', '2단계부서명', '3단계부서명',
    '조직코드', '사번', '성명', '직책',
]

_ROOT_MARKERS_DIRECT = {'대표이사', '삼성전자'}
_ROOT_MARKERS_LOOKUP = {'종합기술원', 'SAIT'}
_ALL_ROOT_MARKERS = _ROOT_MARKERS_DIRECT | _ROOT_MARKERS_LOOKUP


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
    로직을 파일 I/O 없이 그대로 옮긴 것 — 결과는 동일하다."""
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

    rows = []
    seen = set()
    for a, b, c in intermediate:
        a = _backfill_blank_level1(a, b, level2_lookup)
        key = (a, b, c)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            '비공식소속부서명': c, '구분': '', '1단계부서명': a, '2단계부서명': b,
            '3단계부서명': c, '조직코드': '', '사번': '', '성명': '', '직책': '',
        })

    rows.sort(key=lambda r: (r['3단계부서명'], r['2단계부서명'], r['1단계부서명']))
    return pd.DataFrame(rows, columns=_INTAKE_COLUMNS)
