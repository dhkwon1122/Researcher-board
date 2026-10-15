"""과제 개요(목표·마일스톤·주요 업무) + 인력현황(researchers.csv, 휴직 제외) — 2026-10-15."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))

from pipeline import process_project_competency_gap as gap  # noqa: E402
from services import project_staffing as ps  # noqa: E402

RES = pd.DataFrame([
    {'researcher_id': '00000001', 'org_code': '발광소재개발', 'position': 'CL3', 'job_function': '소재', 'employment_status': '재직', 'is_current': 'Y'},
    {'researcher_id': '00000002', 'org_code': '발광소재개발', 'position': 'CL4', 'job_function': '소재', 'employment_status': '휴직', 'is_current': 'Y'},
    {'researcher_id': '00000003', 'org_code': '발광소재개발', 'position': 'CL2', 'job_function': '공정', 'employment_status': '재직', 'is_current': 'N'},
    {'researcher_id': '00000004', 'org_code': 'ORG-9', 'position': 'CL4', 'job_function': '공정', 'employment_status': '재직', 'is_current': 'Y'},
    {'researcher_id': '00000005', 'org_code': '다른과제', 'position': 'CL2', 'job_function': '소재', 'employment_status': '재직', 'is_current': 'Y'},
])


def test_staff_members_excludes_leave_and_past_and_uses_level3():
    l3 = {'ORG-9': '발광 소재 개발'}.get
    assert ps.staff_members(RES, '[연구] 발광소재 개발', {}, l3) == ['00000001', '00000004']
    assert ps.staff_members(RES, '[연구] 발광소재 개발', {}) == ['00000001']


def test_project_staffing_counts(monkeypatch):
    edu = pd.DataFrame([{'researcher_id': '00000001', 'degree': '박사'}, {'researcher_id': '00000001', 'degree': '석사'},
                        {'researcher_id': '00000004', 'degree': '석사'}])
    data = {'researchers': RES, 'education': edu, 'project_confl_address': pd.DataFrame()}
    monkeypatch.setattr(ps, 'read_processed', lambda name, **k: data.get(name, pd.DataFrame()))
    monkeypatch.setattr(ps, '_level3_lookup', lambda: {'ORG-9': '발광소재개발'}.get)
    st = ps.project_staffing('[연구] 발광소재 개발')
    assert st['total'] == 2
    assert st['by_cl'] == [('CL4', 1), ('CL3', 1)]
    assert st['doctor'] == 1 and st['master'] == 1


def test_cl_sort_key_order():
    labels = ['CL2', '상무', 'CL4', '기타', 'CL3']
    assert sorted(labels, key=ps.cl_sort_key) == ['상무', 'CL4', 'CL3', 'CL2', '기타']


def test_overview_llm_cached_and_fallback(monkeypatch):
    calls = []

    def fake_llm(prompt, system, **k):
        calls.append(prompt)
        assert '과제 개요' in system or 'goals' in system
        return '{"goals": ["- 고효율 발광소재 확보"], "milestones": ["2027 시제품"], "tasks": ["소재 합성", "평가"]}'
    monkeypatch.setattr(gap, 'call_llm', fake_llm)
    proj = {'project_name': 'P', 'core_tech': '소재 합성. 소자 평가.', 'deliverable': '발광소재.', 'milestones': ['2027 시제품']}
    cache = {}
    results = [{'project_name': 'P'}]
    assert gap.attach_overview(results, [proj], cache) == 1
    assert results[0]['overview']['goals'] == ['고효율 발광소재 확보']
    gap.attach_overview([{'project_name': 'P'}], [proj], cache)
    assert len(calls) == 1   # 캐시

    monkeypatch.setattr(gap, 'call_llm', lambda *a, **k: '')
    r2 = [{'project_name': 'P'}]
    gap.attach_overview(r2, [proj], {})
    assert r2[0]['overview']['milestones'] == ['2027 시제품']
    assert r2[0]['overview']['tasks'] == ['소재 합성.', '소자 평가.']
