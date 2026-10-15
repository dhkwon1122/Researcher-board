"""JOB Market — 과제원 판정을 필요 역량 탭과 통일(휴직자 표시·제외), 강점 분야 표준화본 우선(2026-10-15)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))

RES = pd.DataFrame([
    {'researcher_id': '00000001', 'name': '갑', 'department': 'd', 'org_code': '발광소재개발', 'employment_status': '재직', 'is_current': 'Y'},
    {'researcher_id': '00000002', 'name': '을', 'department': 'd', 'org_code': '발광소재개발', 'employment_status': '휴직', 'is_current': 'Y'},
    {'researcher_id': '00000003', 'name': '병', 'department': 'd', 'org_code': 'ORG-9', 'employment_status': '재직', 'is_current': 'Y'},
    {'researcher_id': '00000004', 'name': '정', 'department': 'd', 'org_code': '발광소재개발', 'employment_status': '재직', 'is_current': 'N'},
])


def test_get_project_members_same_rule_as_staffing(monkeypatch):
    from services import data_store as ds
    from services import jd_reconciliation as jd
    from services import project_staffing as ps
    monkeypatch.setattr(ds, 'read_processed', lambda name, **k: {'researchers': RES}.get(name, pd.DataFrame()))
    monkeypatch.setattr(ps, '_level3_lookup', lambda: {'ORG-9': '발광 소재 개발'}.get)
    jd._ORG_OVERRIDE_CACHE['ts'] = 0.0
    assert [m['researcher_id'] for m in jd.get_project_members('[연구] 발광소재 개발')] == ['00000001', '00000003']
    allm = jd.get_project_members('[연구] 발광소재 개발', include_on_leave=True)
    assert [(m['researcher_id'], m['on_leave']) for m in allm] == [('00000001', False), ('00000002', True), ('00000003', False)]


def test_plan_assignment_skips_on_leave():
    from services import job_market_insights as jmi
    results = {'00000001': {'shortlist': [{'project_name': 'P', 'adjusted': 0.9}]},
               '00000002': {'on_leave': True, 'recommendations': []}}
    plan = jmi.plan_assignment(results)
    assert [a['researcher_id'] for a in plan['assigned']] == ['00000001'] and plan['unassigned'] == []


def test_profile_text_prefers_std_fields():
    import researcher_fit as fit
    p = {'strength_fields': ['컴퓨터 비전 알고리즘'], 'strength_fields_std': ['비전']}
    assert '강점 분야: 비전' in fit.researcher_profile_text(p)
    assert '강점 분야: 컴퓨터 비전 알고리즘' in fit.researcher_profile_text({'strength_fields': ['컴퓨터 비전 알고리즘']})


def test_read_expertise_profiles_std(monkeypatch):
    from services import data_store as ds
    monkeypatch.setattr(ds, 'read_expertise_profiles', lambda: {'00000001': {'strength_fields': ['a']}, '00000002': {}})
    monkeypatch.setattr(ds, '_read_json_records', lambda t, f: [{'researcher_id': '1', 'strength_fields_std': ['A']}])
    out = ds.read_expertise_profiles_std()
    assert out['00000001']['strength_fields_std'] == ['A'] and 'strength_fields_std' not in out['00000002']
