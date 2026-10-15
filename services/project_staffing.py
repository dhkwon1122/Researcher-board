"""과제 인력현황 — 보유 전문성 > 조직(플랫폼/과제) > 필요 역량(과제)의 "과제 개요" 카드(2026-10-15).

과제별컨플(과제 문서)의 담당자 목록은 쓰지 않고, 실제 인력현황(researchers.csv)의 가장 최근 시점만 본다:
  - 현재 재직자(is_current != 'N') 중 재직상태(employment_status)가 휴직인 사람 제외
  - 소속(org_code = 비공식소속부서명)이 과제와 같은 사람
    (pipeline/researcher_fit.project_member_key — 과제별컨플의 비공식소속부서명 매핑 반영),
    또는 그 소속의 팀/리더 참조 3단계부서명이 과제명과 같은 사람
pipeline/process_project_competency_gap.py의 과제원 판별(staff_members)과 같은 규칙이다.
"""
import re
from collections import Counter

from services.data_store import filter_current, read_processed

_EXEC_ORDER = ['사장', '부사장', '상무', '고문']


def is_on_leave(status) -> bool:
    return '휴직' in str(status or '')


def cl_sort_key(label: str):
    """임원(사장>부사장>상무>고문) → CL 숫자 큰 순 → 그 외 가나다."""
    s = str(label or '').strip()
    if s in _EXEC_ORDER:
        return (0, _EXEC_ORDER.index(s), s)
    m = re.search(r'CL\s*(\d+)', s, re.I)
    if m:
        return (1, -int(m.group(1)), s)
    return (2, 0, s)


def staff_members(researchers, project_name: str, overrides: dict | None = None,
                  level3_of=None, include_on_leave: bool = False) -> list:
    """이 과제의 현재 인력(휴직 제외) researcher_id 목록. level3_of: org_code -> 3단계부서명(선택).
    include_on_leave=True면 휴직자도 포함(JOB Market 대상자 명단에 "휴직" 표시용, 2026-10-15)."""
    from pipeline.researcher_fit import normalize_org_code, project_member_key
    df = filter_current(researchers)
    if df.empty or 'org_code' not in df.columns:
        return []
    key = project_member_key(project_name, overrides)
    name_key = normalize_org_code(project_name)
    out = []
    for r in df.fillna('').to_dict('records'):
        if not include_on_leave and is_on_leave(r.get('employment_status')):
            continue
        org = str(r.get('org_code') or '').strip()
        if not org:
            continue
        if normalize_org_code(org) == key:
            out.append(r['researcher_id'])
        elif level3_of is not None:
            l3 = normalize_org_code(level3_of(org) or '')
            if l3 and l3 in (key, name_key):
                out.append(r['researcher_id'])
    return out


def _level3_lookup():
    try:
        from services import similarity_map as sm
    except Exception:
        return None
    cache: dict = {}

    def _l3(org):
        if org not in cache:
            try:
                cache[org] = sm.org_code_level_names(org)[2]
            except Exception:
                cache[org] = ''
        return cache[org]
    return _l3


def project_staffing(project_name: str) -> dict:
    """{'total', 'by_cl': [(라벨, 수)], 'by_job': [(직무, 수)], 'doctor', 'master'}."""
    from pipeline.researcher_fit import current_rows, project_org_overrides
    res = read_processed('researchers')
    overrides = project_org_overrides(current_rows(read_processed('project_confl_address')))
    rids = staff_members(res, project_name, overrides, _level3_lookup())
    out = {'total': len(rids), 'by_cl': [], 'by_job': [], 'doctor': 0, 'master': 0}
    if not rids:
        return out
    sub = res[res['researcher_id'].isin(set(rids))].drop_duplicates('researcher_id').fillna('')
    cl = Counter(str(v).strip() or '(미기재)' for v in sub.get('position', []))
    out['by_cl'] = sorted(cl.items(), key=lambda kv: cl_sort_key(kv[0]))
    job = Counter(str(v).strip() or '(미기재)' for v in sub.get('job_function', []))
    out['by_job'] = sorted(job.items(), key=lambda kv: (-kv[1], kv[0]))
    edu = read_processed('education')
    if not edu.empty and 'degree' in edu.columns:
        degs = edu[edu['researcher_id'].isin(set(rids))].groupby('researcher_id')['degree'].apply(set)
        out['doctor'] = int(sum(1 for d in degs if '박사' in d))
        out['master'] = int(sum(1 for d in degs if '박사' not in d and '석사' in d))
    return out
