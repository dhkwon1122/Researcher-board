"""조직 분석 2026-10-13: Staff 조직(하위 포함) 제외, 그래프 조직코드 순·노드 툴팁, 과제 목록 매칭/누락 과제."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))

from services import collab_graph as cg  # noqa: E402
from services import similarity_map as sm  # noqa: E402


def test_staff_org_codes_includes_descendants(monkeypatch):
    rows = [
        {'dep_id': '1', 'upper_dep_id': '', 'work_type': 'Staff', 'org_name_wd': ''},
        {'dep_id': '2', 'upper_dep_id': '1', 'work_type': 'R&D', 'org_name_wd': '경영지원파트'},
        {'dep_id': '3', 'upper_dep_id': '', 'work_type': 'R&D', 'org_name_wd': ''},
        {'dep_id': '4', 'upper_dep_id': '3', 'work_type': 'staff', 'org_name_wd': '기획파트'},
        {'dep_id': '5', 'upper_dep_id': '3', 'work_type': 'R&D', 'org_name_wd': '소재파트'},
    ]
    monkeypatch.setattr(sm, 'read_team_refer', lambda *a, **k: rows)
    assert sm.staff_org_codes() == {'경영지원파트', '기획파트'}


def test_graph_order_and_hover():
    pairs = {('B', 'C'): 3, ('A', 'B'): 1, ('A', 'C'): 5}
    heat = cg.heatmap_figure(pairs, order=['C', 'A', 'B'])
    import re as _re
    labels = [_re.sub(r'<[^>]+>', '', t) for t in heat.layout.xaxis.ticktext]   # 축 라벨은 부서 색 글씨(2026-10-14)
    assert labels == ['C', 'A', 'B'] and list(heat.layout.yaxis.ticktext) == list(heat.layout.xaxis.ticktext)
    net = cg.network_figure(pairs, order=['C', 'A', 'B'])
    node = net.data[-1]
    assert [c[0] for c in node.customdata] == ['C', 'A', 'B']
    c_row = node.customdata[0]
    assert c_row[1] == 8 and 'A: 5건' in c_row[2] and 'B: 3건' in c_row[2]


def test_project_level_matching_by_3rd_name_and_members(monkeypatch):
    import dash
    dash.Dash(__name__)
    from components import org_analysis_tab as o
    rows = [{'org_name_wd': 'ORG-77', 'dep_3rd_name': '발광소재개발', 'dep_1st_name': 'P'}]
    monkeypatch.setattr(sm, 'org_rows_for_levels', lambda *a, **k: rows)
    items = [{'project_name': '[연구]발광소재개발', 'competencies': []},
             {'project_name': '다른이름과제', 'competencies': [{'members': [{'researcher_id': '1'}, {'researcher_id': '2'}]}]},
             {'project_name': '무관과제', 'competencies': [{'members': [{'researcher_id': '3'}]}]}]
    monkeypatch.setattr(o, '_gap_items', lambda: items)
    monkeypatch.setattr(o, '_org_map', lambda: {'1': 'ORG-77', '2': 'X', '3': 'Y'})
    assert [x['value'] for x in o._project_options('P', None)] == ['[연구]발광소재개발', '다른이름과제']


def test_missing_projects_reasons(monkeypatch):
    import dash
    import pandas as pd
    dash.Dash(__name__)
    from components import org_analysis_tab as o
    import services.data_store as ds
    monkeypatch.setattr(o, 'read_processed', lambda name: pd.DataFrame(
        [{'project_name': 'A', 'dep_name': 'D'}, {'project_name': 'B', 'dep_name': 'D'}, {'project_name': 'C', 'dep_name': 'D'}]))
    monkeypatch.setattr(o, '_gap_items', lambda: [{'project_name': 'A'}])
    monkeypatch.setattr(ds, 'read_project_expertise_analysis', lambda: [{'project_name': 'A'}, {'project_name': 'B'}])
    rows = o._missing_projects(None, None)
    assert [r[0] for r in rows] == ['B', 'C']
    assert '필요 역량' in rows[0][2] and '문서 분석 실패' in rows[1][2]


def test_current_levels_excludes_staff(monkeypatch):
    import pandas as pd
    from pipeline import process_expertise_metrics as pm
    monkeypatch.setattr(sm, 'staff_org_codes', lambda: {'STAFF-ORG'})
    monkeypatch.setattr(sm, 'org_code_level_names', lambda code: ('P1', 'G', 'T-' + code))
    r = pd.DataFrame({'researcher_id': ['1', '2'], 'org_code': ['STAFF-ORG', 'RND'], 'is_current': ['Y', 'Y']})
    assert pm.current_levels(r) == {'2': ('P1', 'T-RND')}


def test_aggregate_excludes_sait_level1():
    """1단계 부서명 SAIT가 한쪽이라도 끼면 협업 쌍에서 제외(2026-10-14)."""
    import pandas as pd
    from services.collab_graph import aggregate
    edges = pd.DataFrame([
        dict(level1_a='A플랫폼', level1_b='B플랫폼', level3_a='a', level3_b='b', recent_count='3'),
        dict(level1_a='SAIT', level1_b='B플랫폼', level3_a='s', level3_b='b', recent_count='5'),
        dict(level1_a='A플랫폼', level1_b='sait', level3_a='a', level3_b='s2', recent_count='2'),
    ])
    assert aggregate(edges, 'level1') == {('A플랫폼', 'B플랫폼'): 3}
    assert aggregate(edges, 'level3') == {('a', 'b'): 3}


def test_project_graph_groups_by_department_with_outer_ring():
    """과제 기준: 같은 부서 과제끼리 붙여 배치, 같은 부서 계열 색, 바깥 부서 띠·히트맵 위 부서명(2026-10-14)."""
    import re as _re
    pairs = {('p1', 'q1'): 3, ('p2', 'q1'): 2, ('p1', 'p2'): 1}
    group_of = {'p1': '부서P', 'p2': '부서P', 'q1': '부서Q'}
    net = cg.network_figure(pairs, order=['p1', 'q1', 'p2'], group_of=group_of)
    node = net.data[-1]
    assert [c[0] for c in node.customdata] == ['p1', 'p2', 'q1']
    colors = list(node.marker.color)
    assert colors[0] != colors[1] and colors[0][:3] != colors[2][:3] or colors[0] != colors[2]
    assert {a.text for a in net.layout.annotations} == {'<b>부서P</b>', '<b>부서Q</b>'}
    heat = cg.heatmap_figure(pairs, order=['p1', 'q1', 'p2'], group_of=group_of)
    assert [_re.sub(r'<[^>]+>', '', t) for t in heat.layout.xaxis.ticktext] == ['p1', 'p2', 'q1']
    assert {a.text for a in heat.layout.annotations} == {'<b>부서P</b>', '<b>부서Q</b>'}
    assert cg.is_excluded_level1(' ideation factory T/F (SAIT) ') and cg.is_excluded_level1('sait')
