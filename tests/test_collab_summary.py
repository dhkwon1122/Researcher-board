"""부서/과제간 협업 AI 요약(2026-10-14) — 통계·이름 미전송·폴백."""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import process_collab_summary as pcs  # noqa: E402

RES = pd.DataFrame({'researcher_id': ['1', '2', '3', '4', '5'],
                    'name': ['홍길동', '김철수', '이영희', '박민수', '최지우']})
LEVELS = {'1': ('A부서', 'a과제'), '2': ('B부서', 'b과제'), '3': ('B부서', 'b2과제'),
          '4': ('C부서', 'c과제'), '5': ('D부서', 'd과제')}
PUBS = pd.DataFrame([
    dict(researcher_id='1', title='Robot vision SLAM', pub_date='2025-03-01', pub_year='2025', grade_publication='최우수'),
    dict(researcher_id='2', title='Robot vision SLAM', pub_date='2025-03-01', pub_year='2025', grade_publication='최우수'),
    dict(researcher_id='1', title='Lidar fusion', pub_date='2023-05-01', pub_year='2023', grade_publication='일반'),
    dict(researcher_id='3', title='Lidar fusion', pub_date='2023-05-01', pub_year='2023', grade_publication='일반'),
    dict(researcher_id='1', title='Old paper', pub_date='2010-01-01', pub_year='2010', grade_publication=''),
    dict(researcher_id='4', title='Old paper', pub_date='2010-01-01', pub_year='2010', grade_publication=''),
])
PATS = pd.DataFrame([dict(researcher_id='1', application_id='P1', title_ko='센서 장치', application_date='2026-01-01'),
                     dict(researcher_id='4', application_id='P1', title_ko='센서 장치', application_date='2026-01-01')])


def test_level_stats_and_names_not_sent(monkeypatch):
    prompts = []

    def fake_llm(prompt, system, **kw):
        prompts.append(prompt)
        return '{"pairs": [{"idx": 0, "topics": ["로봇 시각"]}], "overview": ["- A부서·B부서 협업 최다"]}'

    monkeypatch.setattr(pcs, 'call_llm', fake_llm)
    out = pcs.build(RES, PUBS, PATS, LEVELS, cache={}, today=date(2026, 10, 14))
    l1 = next(r for r in out if r['level'] == 'level1')
    top = l1['top_pairs'][0]
    assert (top['a'], top['b'], top['papers'], top['patents'], top['top_grade']) == ('A부서', 'B부서', 2, 0, 1)
    assert top['topics'] == ['로봇 시각'] and top['people'][0] == '홍길동' and 'titles' not in top
    assert l1['overview'] == ['A부서·B부서 협업 최다'] and l1['llm']
    assert l1['low'][:1] == ['D부서']                      # 협업 0인 단위
    assert {(r['a'], r['b']) for r in l1['new_pairs']} == {('A부서', 'C부서')}   # 2026 특허만(오래된 논문 제외)
    assert l1['papers'] == 2 and l1['patents'] == 1
    for p in prompts:   # 이름·사번 미전송
        assert not any(n in p for n in RES['name']) and '홍길동' not in p


def test_fallback_without_llm(monkeypatch):
    monkeypatch.setattr(pcs, 'call_llm', lambda *a, **k: '')
    out = pcs.build(RES, PUBS, PATS, LEVELS, cache={}, today=date(2026, 10, 14))
    l3 = next(r for r in out if r['level'] == 'level3')
    assert not l3['llm'] and l3['overview'] and l3['overview'][0].startswith('가장 협업이 많은 과제')
