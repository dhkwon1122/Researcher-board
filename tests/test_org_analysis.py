"""조직 분석 개편(2026-10-09): 기술명 통합, 과제별 필요 역량 근거, 부서/과제간 협업 집계."""
import hashlib
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))

from pipeline import process_expertise_metrics as pm  # noqa: E402
from pipeline import process_project_competency_gap as gap  # noqa: E402
from pipeline import tech_canonical as tc  # noqa: E402
from services import collab_graph as cg  # noqa: E402


def test_tech_canonical_merges_only_when_llm_confirms(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, 'OUT_DIR', str(tmp_path))
    names = ['A 기반 LiDAR', 'A 및 LiDAR', '배터리']
    emb = lambda ns: np.array([[1, 0.01 * i, 0] if 'LiDAR' in n else [0, 0, 1] for i, n in enumerate(ns)], float)
    ok = '{"groups":[{"name":"A 기반 LiDAR","idx":[0,1]}]}'
    m = tc.build_canonical_map(names, embed_fn=emb, call_llm=lambda *a, **k: ok, extract_json=lambda x: x)
    assert m == {'A 기반 LiDAR': 'A 기반 LiDAR', 'A 및 LiDAR': 'A 기반 LiDAR'}
    monkeypatch.setattr(tc, 'OUT_DIR', str(tmp_path / 'other'))
    assert tc.build_canonical_map(names, embed_fn=emb, call_llm=lambda *a, **k: '', extract_json=lambda x: x) == {}


def test_holders_merge_aliases():
    core = pd.DataFrame([{'researcher_id': '1', 'tech_name': 'X 기반', 'tech_grade': 'A', 'tech_field': ''},
                         {'researcher_id': '2', 'tech_name': 'X 및', 'tech_grade': 'B', 'tech_field': ''}])
    r = pd.DataFrame({'researcher_id': ['1', '2'], 'department': ['a', 'b']})
    df = pm.compute_technology_holders(r, core, pd.DataFrame(), [], lambda ns: {'X 및': 'X 기반'})
    assert len(df) == 1 and df.iloc[0]['holder_count'] == 2 and df.iloc[0]['aliases'] == 'X 및'


def test_gap_description_members_outsiders_evidence(monkeypatch):
    monkeypatch.setattr(gap.fit, 'cached_embed', lambda ts: np.array(
        [[hashlib.md5(t.encode()).digest()[i] / 255 for i in range(8)] for t in ts]))
    items = {f'0000000{i}': [f'기술{i}', '공통'] for i in range(1, 15)}
    res = gap.analyze_gaps([{'project_name': 'P'}], {'P': [{'name': '기술1', 'description': '쉬운'}]},
                           {'P': {'00000001', '00000002'}}, items, set(items))
    c = res[0]['competencies'][0]
    assert c['description'] == '쉬운' and len(c['members']) == 2 and len(c['outsiders']) == gap.OUTSIDER_TOP_N
    prompts = []
    monkeypatch.setattr(gap, 'call_llm', lambda p, s, **k: prompts.append(p) or '{"evidence":[{"idx":0,"reason":"r"}]}')
    gap.attach_evidence(res, {})
    assert c['members'][0]['reason'] == 'r' and '0000000' not in prompts[0]


def test_collab_recent_and_levels():
    r = pd.DataFrame({'researcher_id': ['1', '2', '3'], 'department': ['a', 'b', 'c']})
    pubs = pd.DataFrame({'researcher_id': ['1', '2', '1', '3'], 'title': ['t', 't', 'u', 'u'],
                         'pub_date': ['2025-01-01'] * 2 + ['2015-01-01'] * 2, 'pub_year': ['2025'] * 2 + ['2015'] * 2})
    lv = {'1': ('P1', 'T1'), '2': ('P2', 'T2'), '3': ('P2', 'T3')}
    e, _ = pm.compute_collaboration(r, pubs, pd.DataFrame(), lv, today_year=2026)
    assert cg.aggregate(e, 'level1') == {('P1', 'P2'): 1}
    assert cg.aggregate(e, 'level3') == {('T1', 'T2'): 1}
    assert cg.network_figure(cg.aggregate(e, 'level1')) is not None
