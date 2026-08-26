"""
data/raw/ 안의 원본 파일명을 와일드카드 패턴으로 찾는 공용 유틸리티.

사내 시스템에서 다운로드한 파일은 다운로드 시각이 파일명에 그대로 찍혀
나오므로(예: "T&P 기본 인사 정보 2026-08-26 11_22 GMT+9.xlsx") 매번 이름이
달라진다. sources.py는 이제 정확한 파일명 대신 이런 패턴("T&P 기본 인사
정보 *.xlsx")을 등록해 두고, 이 모듈이 data/raw/ 를 스캔해 실제로 존재하는
파일을 찾는다.

정책(여러 개가 동시에 매칭될 때):
  - find_latest(): 가장 최근에 수정된(mtime) 파일 하나만 선택한다 — 스냅샷
    성격의 파일(T&P/시상/학력/인사발령/직무이력 원본)은 "가장 최근 다운받은
    것이 최신"으로 보면 충분하다.
  - find_matches(): mtime 오름차순으로 전부 반환한다 — 인력현황처럼 여러
    다운로드 파일을 모두 합쳐 누적해야 하는 경우(각 파일 내부의
    인원실적년도/인원실적월/사원번호로 최신 여부를 가리므로, 파일 자체는
    버리지 않고 전부 읽어들인다) 사용한다. 오름차순으로 반환해 두면 뒤에서
    합칠 때 "나중 파일이 우선"이라는 자연스러운 순서를 그대로 쓸 수 있다.

패턴에 '*'가 없으면(기존 방식과 동일하게) 정확히 그 이름의 파일만 찾는다.
exclude를 주면 파일명에 그 문자열이 포함된 항목은 후보에서 제외한다 —
예: "내 리포트 *.xlsx" 패턴이 이 모듈이 만든 산출물 "..._병합.xlsx"를
다음 실행에서 다시 입력으로 집어먹지 않도록.
"""

import fnmatch
import os

PatternLike = str | list[str] | tuple[str, ...]


def _as_pattern_list(pattern: PatternLike) -> list[str]:
    if isinstance(pattern, (list, tuple)):
        return list(pattern)
    return [pattern]


def find_matches(directory: str, pattern: PatternLike, exclude: str | None = None) -> list[str]:
    """directory 안에서 pattern(문자열 또는 문자열 리스트)에 맞는 파일의 전체
    경로를, 수정시각(mtime) 오름차순으로 반환한다. 디렉터리가 없으면 빈 리스트."""
    if not os.path.isdir(directory):
        return []
    patterns = _as_pattern_list(pattern)
    matched = []
    for name in os.listdir(directory):
        if exclude and exclude in name:
            continue
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        if any(fnmatch.fnmatch(name, pat) for pat in patterns):
            matched.append(full)
    matched.sort(key=lambda p: os.path.getmtime(p))
    return matched


def find_latest(directory: str, pattern: PatternLike, exclude: str | None = None) -> str | None:
    """find_matches() 결과 중 가장 최근에 수정된 파일 하나. 없으면 None."""
    matches = find_matches(directory, pattern, exclude=exclude)
    return matches[-1] if matches else None


def is_wildcard(pattern: PatternLike) -> bool:
    return any('*' in p or '?' in p for p in _as_pattern_list(pattern))
