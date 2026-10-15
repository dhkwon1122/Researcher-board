"""논문·특허 자산화 AI 요약(2026-10-15) — 집계 기준, 1인 과제 제외, LLM에 이름·사번 미전송, 실패 시 통계 문장."""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import process_asset_summary as pas  # noqa: E402

LEVELS = {'00000001': ('A플랫폼', 't1'), '00000002': ('A플랫폼', 't1'), '00000003': ('B플랫폼', 't2'),
          '00000004': ('B플랫폼', 't2'), '00000005': ('B플랫폼', 'solo')}
PUBS = pd.DataFrame({'researcher_id': ['00000001', '00000002', '00000003', '00000005', '00000003'],
                     'title': ['고효율 발광 소재', '고효율 발광 소재', '전고체 배터리 전해질', '단독 논문', '옛 논문'],
                     'grade_publication': ['최우수', '최우수', '우수', '일반', '우수'],
                     'pub_year': ['2026', '2026', '2025', '2025', '2015']})
PATS = pd.DataFrame({'researcher_id': ['00000001', '00000003', '00000004'], 'application_id': ['X', 'Y', 'Y'],
                     'patent_grade': ['A1', 'A2', 'A2'], 'patent_grade_a_sub': ['전략출원', '', ''],
                     'application_date': ['2024-01-01', '2023-01-01', '2023-01-01']})


def test_build_counts_and_prompt_has_no_ids(monkeypatch):
    prompts = []

    def fake_llm(prompt, system, **k):
        prompts.append(prompt)
        return '{"units": [{"idx": 0, "topics": ["발광 소재"]}], "overview": ["- 총평 항목"]}'
    monkeypatch.setattr(pas, 'call_llm', fake_llm)
    out = {r['level']: r for r in pas.build(LEVELS, PUBS, PATS, today=date(2026, 10, 15))}
    l1 = out['level1']
    assert (l1['papers'], l1['patents']) == (3, 2)          # 같은 단위 공저 1건, 2015년 제외, 같은 출원ID 1건
    assert l1['top_units'][0]['unit'] == 'A플랫폼' and l1['top_units'][0]['topics'] == ['발광 소재']
    assert 'titles' not in l1['top_units'][0] and l1['overview'] == ['총평 항목'] and l1['llm']
    l3 = out['level3']
    assert l3['unit_count'] == 2 and 'solo' not in str(l3)    # 1인 과제 제외
    assert all('0000000' not in p for p in prompts)


def test_llm_failure_falls_back_to_stats(monkeypatch):
    monkeypatch.setattr(pas, 'call_llm', lambda *a, **k: '')
    out = pas.build(LEVELS, PUBS, PATS, today=date(2026, 10, 15))
    assert not out[0]['llm'] and out[0]['overview'][0].startswith('최근 5년 논문 3건')
