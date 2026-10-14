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


def test_grade_counts_by_dept_dedupes_coauthors(monkeypatch):
    from services import publication_quality as pq
    from services import similarity_map as sm
    res = pd.DataFrame({'researcher_id': ['1', '2', '3'], 'org_code': ['O1', 'O1', 'O2'], 'is_current': ['Y'] * 3})
    pubs = pd.DataFrame({'researcher_id': ['1', '2', '3', '3'], 'title': ['P', 'p', 'Q', 'R'],
                         'grade_publication': ['최우수', '최우수', '우수', '외부'],
                         'pub_year': ['2025', '2025', '2024', '2001']})
    monkeypatch.setattr(pq, 'read_processed', lambda n: {'publications': pubs, 'researchers': res}[n])
    monkeypatch.setattr(sm, 'org_code_level_names', lambda o: ({'O1': 'A부서', 'O2': 'B부서'}[o], '', o))
    monkeypatch.setattr(sm, 'level_filter_options', lambda lvl, *a, **k: [{'value': 'B부서'}, {'value': 'A부서'}])
    df = pq.grade_counts('level1')
    assert df.to_dict('records') == [
        {'unit': 'B부서', '최우수': 0, '우수': 1, '일반': 0, '외부': 0, '합계': 1},
        {'unit': 'A부서', '최우수': 1, '우수': 0, '일반': 0, '외부': 0, '합계': 1},
    ]
    assert pq.grade_figure(df) is not None


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
