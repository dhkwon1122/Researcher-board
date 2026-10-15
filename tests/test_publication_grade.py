"""논문 등급구분/Impact Factor 열(2026-10-14) — 선택 열 처리 + 대표 논문 우선순위."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import process_publications as pp  # noqa: E402

from components.timeline_data import publication_priority_key


def _src(extra: dict):
    base = {'사번': ['1', '1'], '저자구분': ['주저자', '공저자'], '교신저자여부': ['N', 'Y'], '논문제목': ['A', 'B'],
            '게재/발표처': ['J1', 'J2'], '발표형태': ['저널', '저널'], '진행상태': ['최종완료', '최종완료'],
            '발표일': ['20240101', '20250101'], '실적일': ['20240101', '20250101'], '저자순위': ['1', '3'],
            '총저자수': ['5', '5'], '전체 저자정보': ['x (기여도 : 30%)', 'y']}
    base.update(extra)
    return pd.DataFrame(base)


def _run(tmp_path, monkeypatch, df):
    out = tmp_path / 'publications.csv'
    monkeypatch.setattr(pp, 'OUTPUT', str(out))
    monkeypatch.setattr(pp, 'read_source', lambda name: df, raising=False)
    import source_reader
    monkeypatch.setattr(source_reader, 'read_source', lambda name: df)
    assert pp.process()
    return pd.read_csv(out, dtype=str, keep_default_na=False)


def test_new_columns_parsed(tmp_path, monkeypatch):
    res = _run(tmp_path, monkeypatch, _src({'등급구분': ['우수', '-'], 'Impact Factor': ['12.50', '-']}))
    got = dict(zip(res['title'], zip(res['grade_publication'], res['impact_factor'])))
    assert got == {'A': ('우수', '12.5'), 'B': ('-', '')}


def test_missing_columns_ok(tmp_path, monkeypatch):
    res = _run(tmp_path, monkeypatch, _src({}))
    assert set(res['grade_publication']) == {''} and set(res['impact_factor']) == {''}


def test_priority_grade_then_lead_then_if_then_recent():
    rows = [dict(t='일반-1저자-IF30', grade_publication='일반', author_rank='1', impact_factor='30', pub_date='2025-01-01'),
            dict(t='최우수-공저', grade_publication='최우수', author_rank='3', impact_factor='5', pub_date='2020-01-01'),
            dict(t='최우수-1저자-옛', grade_publication='최우수', author_rank='1', impact_factor='2', pub_date='2019-01-01'),
            dict(t='등급없음', grade_publication='-', author_rank='1', impact_factor='50', pub_date='2026-01-01'),
            dict(t='최우수-1저자-최근', grade_publication='최우수', author_rank='1', impact_factor='2', pub_date='2024-05-01')]
    assert [r['t'] for r in sorted(rows, key=publication_priority_key)] == \
        ['최우수-1저자-최근', '최우수-1저자-옛', '최우수-공저', '일반-1저자-IF30', '등급없음']


def test_asset_counts_papers_and_patents(monkeypatch):
    """논문 등급(공저 1건)·특허 등급(전략>A1>A2>기타, 출원ID 1건)을 단위별로(2026-10-15)."""
    from services import publication_quality as pq
    from services import org_units
    from services import similarity_map as sm
    pubs = pd.DataFrame({'researcher_id': ['1', '2', '3', '3'], 'title': ['P', 'p', 'Q', 'R'],
                         'grade_publication': ['최우수', '최우수', '우수', '외부'],
                         'pub_year': ['2025', '2025', '2024', '2001']})
    pats = pd.DataFrame({'researcher_id': ['1', '2', '3', '3', '3'], 'application_id': ['X', 'X', 'Y', 'Z', 'W'],
                         'patent_grade': ['A1', 'A1', 'A2', 'B', 'A1'], 'patent_grade_a_sub': ['전략출원', '전략출원', '', '', ''],
                         'application_date': ['2025-01-01', '2025-01-01', '2024-03-01', '2023-05-01', '2010-01-01']})
    monkeypatch.setattr(pq, 'read_processed', lambda n: {'publications': pubs, 'patents': pats}[n])
    monkeypatch.setattr(org_units, 'unit_members', lambda level='level1': {'1': 'A부서', '2': 'A부서', '3': 'B부서'})
    monkeypatch.setattr(sm, 'level_filter_options', lambda lvl, *a, **k: [{'value': 'B부서'}, {'value': 'A부서'}])
    rows = {r['unit']: r for r in pq.asset_counts('level1').to_dict('records')}
    assert list(rows) == ['B부서', 'A부서']
    assert rows['A부서']['논문_최우수'] == 1 and rows['A부서']['특허_전략'] == 1 and rows['A부서']['특허_계'] == 1
    assert rows['B부서']['논문_우수'] == 1 and rows['B부서']['논문_계'] == 1
    assert (rows['B부서']['특허_A2'], rows['B부서']['특허_기타'], rows['B부서']['특허_A1']) == (1, 1, 0)
    fig = pq.asset_figure(pq.asset_counts('level1'))
    assert fig is not None and fig.layout.legend.xanchor == 'center'


def test_collab_level3_drops_single_member_projects(monkeypatch):
    """협업 과제 기준: 구성원 1명인 과제가 낀 쌍은 제외(2026-10-15)."""
    import dash
    dash.Dash(__name__)
    from components import org_analysis_tab as o
    from services import org_units
    edges = pd.DataFrame([dict(level1_a='P', level1_b='Q', level3_a='a', level3_b='b', recent_count='3'),
                          dict(level1_a='P', level1_b='Q', level3_a='a', level3_b='solo', recent_count='5')])
    monkeypatch.setattr(o, 'read_processed', lambda n: edges)
    from collections import Counter
    monkeypatch.setattr(org_units, 'unit_sizes', lambda level='level1': Counter({'a': 3, 'b': 2, 'solo': 1}))
    captured = {}
    from services import collab_graph as cg
    monkeypatch.setattr(cg, 'network_figure', lambda pairs, *a, **k: captured.setdefault('pairs', pairs) and None)
    monkeypatch.setattr(cg, 'heatmap_figure', lambda *a, **k: None)
    o._collab_body('level3', 20)
    assert captured['pairs'] == {('a', 'b'): 3}


def test_evidence_grade_bonus_ranks_top_paper_first():
    import numpy as np
    from services import job_market_insights as jmi

    class Ctx:
        def evidence_items(self, rid):
            return [('논문', '일반 논문', 2025), ('논문(최우수)', '최우수 논문', 2024)]

        def embed(self, texts):
            return np.array([[1.0, 0.0], [0.99, 0.141]], dtype=np.float32)

    out = jmi.evidence_match(Ctx(), '1', [1.0, 0.0])
    assert out['items'][0]['title'] == '최우수 논문'
