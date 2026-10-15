"""AI 검색 평가등급 조건 — People제외 계정은 그 부서 소속만 빼고 검색(2026-10-15)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import nl_query as nq  # noqa: E402

RES = pd.DataFrame({'researcher_id': ['00000001', '00000002', '00000003'],
                    'org_code': ['개발팀', 'People팀', '개발팀'], 'department': ['개발', 'People', '개발'],
                    'is_current': ['Y', 'Y', 'Y']})


def _setup(monkeypatch, can_eval=True, excluded=frozenset()):
    years = [2025, 2024, 2023]
    cols = [f'g{y}' for y in years]
    ev = pd.DataFrame({'researcher_id': ['00000001', '00000002', '00000003'],
                       cols[0]: ['가', '가', '다'], cols[1]: ['가', '가', '다'], cols[2]: ['나', '나', '다']})
    monkeypatch.setattr(nq.data_store, 'read_processed', lambda n, **k: {'researchers': RES, 'evaluations': ev}.get(n, pd.DataFrame()))
    monkeypatch.setattr(nq, 'evaluation_years', lambda: (years, []))
    monkeypatch.setattr(nq, 'salary_grade_column', lambda y: f'g{y}')
    monkeypatch.setattr(nq.auth, 'get_current_user', lambda: {'user_id': 'admin'})
    monkeypatch.setattr(nq.auth, 'can', lambda p: can_eval)
    monkeypatch.setattr(nq.auth, 'eval_excluded_dep_ids', lambda: set(excluded))
    import services.similarity_map as sm
    monkeypatch.setattr(sm, 'org_code_dep_id_map', lambda period=None: {'개발팀': 'D1', 'People팀': 'P1'})


def _ids(res):
    i = res['columns'].index('researcher_id')
    return [r[i] for r in res['rows']]


def test_people_excluded_account_searches_without_people_team(monkeypatch):
    _setup(monkeypatch, excluded={'P1'})
    res = nq.find_researchers_by_criteria(grade_threshold=list('가가나'), grade_comparison='이상')
    assert _ids(res) == ['00000001']
    assert 'People팀 등' in res['note'] and '1명' in res['note']


def test_no_exclusion_includes_everyone(monkeypatch):
    _setup(monkeypatch)
    res = nq.find_researchers_by_criteria(grade_threshold=list('가가나'), grade_comparison='이상')
    assert _ids(res) == ['00000001', '00000002']


def test_no_view_evaluation_blocked(monkeypatch):
    _setup(monkeypatch, can_eval=False)
    res = nq.find_researchers_by_criteria(grade_threshold=list('가가나'), grade_comparison='이상')
    assert res['rows'] == [] and '권한이 없습니다' in res['note']
