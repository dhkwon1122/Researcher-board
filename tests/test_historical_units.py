"""협업: 논문·특허 작성 당시 같은 단위였던 협업 제외(2026-10-15)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import historical_units as hu  # noqa: E402
import process_expertise_metrics as pem  # noqa: E402

# 1·2: 2023년엔 같은 과제(t1), 2025년부터 2는 t2로 이동(같은 부서 P). 3: 늘 다른 부서 Q.
HIST = pd.DataFrame([
    {'researcher_id': '00000001', 'org_code': 'o1', 'valid_year': '2023', 'valid_month': '01'},
    {'researcher_id': '00000002', 'org_code': 'o1', 'valid_year': '2023', 'valid_month': '01'},
    {'researcher_id': '00000001', 'org_code': 'o1', 'valid_year': '2025', 'valid_month': '01'},
    {'researcher_id': '00000002', 'org_code': 'o2', 'valid_year': '2025', 'valid_month': '01'},
    {'researcher_id': '00000003', 'org_code': 'o3', 'valid_year': '2025', 'valid_month': '03'},
])
NAMES = {'o1': ('P', '', 't1'), 'o2': ('P', '', 't2'), 'o3': ('Q', '', 't3')}


def _hist():
    return hu.UnitHistory(HIST, current_names=lambda org: NAMES.get(org, ('', '', '')))


def test_snapshot_rules():
    h = _hist()
    assert h.units_at('00000002', '2024-06-10') == ('P', 't1')        # 이전 가장 가까운 달(2023-01)
    assert h.units_at('00000002', '2025-02-01') == ('P', 't2')
    assert h.units_at('00000003', '2025-01-15') == ('Q', 't3')        # 이전 없음 → 3개월 이내 이후(2025-03)
    assert h.units_at('00000003', '2024-10-01') is None               # 3개월 넘음 → 판정 불가
    assert h.same_at('00000001', '00000002', '2024-06-10') == (True, True)
    assert h.same_at('00000001', '00000002', '2025-06-01') == (True, False)
    assert h.same_at('00000001', '00000003', '2024-01-01') == (False, False)   # 3 판정 불가 → 포함


def test_doc_date_priority():
    assert hu.doc_date({'pub_date': '2024-03-01', 'announce_date': '2023-01-01'}, 'paper') == '2024-03-01'
    assert hu.doc_date({'pub_date': '', 'announce_date': '2023-01-01'}, 'paper') == '2023-01-01'
    assert hu.doc_date({'application_date': ''}, 'patent') == ''


def test_edges_exclude_same_unit_then():
    r = pd.DataFrame({'researcher_id': ['00000001', '00000002', '00000003'], 'department': ['a', 'b', 'c']})
    pubs = pd.DataFrame({'researcher_id': ['00000001', '00000002', '00000001', '00000002', '00000001', '00000003'],
                         'title': ['old', 'old', 'new', 'new', 'x', 'x'],
                         'pub_date': ['2024-06-01'] * 2 + ['2025-06-01'] * 2 + ['2025-06-01'] * 2,
                         'pub_year': ['2024'] * 2 + ['2025'] * 4})
    lv = {'00000001': ('P', 't1'), '00000002': ('P', 't2'), '00000003': ('Q', 't3')}
    e, _ = pem.compute_collaboration(r, pubs, pd.DataFrame(), lv, today_year=2026, history=_hist())
    row = e[(e['researcher_a'] == '00000001') & (e['researcher_b'] == '00000002')].iloc[0]
    assert row['recent_count'] == 2 and row['recent_count_level3'] == 1 and row['excluded_level3'] == 1
    from services import collab_graph as cg
    assert cg.aggregate(e, 'level3') == {('t1', 't2'): 1, ('t1', 't3'): 1}
    assert cg.excluded_same_unit(e, 'level3') == 1 and cg.excluded_same_unit(e, 'level1') == 0


def test_collab_summary_excludes_same_unit_then():
    import process_collab_summary as pcs
    docs = [{'kind': '논문', 'title': 'old', 'year': 2024, 'grade': '', 'members': ['00000001', '00000002'], 'date': '2024-06-01'},
            {'kind': '논문', 'title': 'new', 'year': 2025, 'grade': '', 'members': ['00000001', '00000002'], 'date': '2025-06-01'}]
    h = _hist()
    s = pcs.summarize_level(docs, {'00000001': 't1', '00000002': 't2'}, {}, ['t1', 't2'], 2026,
                            lambda x, y, d: h.same_at(x, y, d)[1])
    assert s['same_unit_excluded'] == 1 and s['top_pairs'][0]['total'] == 1
