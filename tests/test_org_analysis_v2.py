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
    assert list(heat.data[0].x) == ['C', 'A', 'B'] and list(heat.data[0].y) == ['C', 'A', 'B']
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
