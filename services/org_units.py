"""조직 분석 공용 — 현재 재직 연구원의 부서(1단계)/과제(3단계) 소속(2026-10-15).

협업(플랫폼/과제)·논문,특허(플랫폼/과제) 탭이 같은 기준을 쓰도록 한 곳에 모았다:
  - 현재 재직자만(researchers.is_current != 'N')
  - 팀/리더 참조 구분이 "Staff"인 조직(하위 포함) 소속 제외(similarity_map.staff_org_codes)
  - 1단계부서명이 "SAIT"·"Ideation Factory T/F(SAIT)"인 조직(하위 포함) 소속 제외(collab_graph.EXCLUDED_LEVEL1)
pipeline/process_expertise_metrics.current_levels()와 같은 규칙이다(파이프라인은 그쪽, 화면은 이쪽).
"""
from collections import Counter

from services.data_store import filter_current, read_processed

_IDX = {'level1': 0, 'level3': 2}


def unit_members(level: str = 'level1') -> dict:
    """researcher_id -> 단위명(1단계 또는 3단계부서명). 제외 대상·매칭 안 되는 사람은 없음."""
    from services import similarity_map as sm
    from services.collab_graph import is_excluded_level1
    res = filter_current(read_processed('researchers'))
    if res.empty or 'org_code' not in res.columns:
        return {}
    try:
        staff = sm.staff_org_codes()
    except Exception:
        staff = set()
    idx = _IDX.get(level, 0)
    cache: dict = {}
    out = {}
    for rid, org in zip(res['researcher_id'], res['org_code'].astype(str).str.strip()):
        if not org or org in staff:
            continue
        if org not in cache:
            cache[org] = sm.org_code_level_names(org)
        names = cache[org]
        if is_excluded_level1(names[0]) or not names[idx]:
            continue
        out[rid] = names[idx]
    return out


def unit_sizes(level: str = 'level1') -> Counter:
    """단위명 -> 현재 구성원 수(제외 대상 빼고)."""
    return Counter(unit_members(level).values())
