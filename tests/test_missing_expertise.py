"""현재 명단에 없는 연구원(파견 등)의 별도 전문성 분석 보충(2026-11-12)."""
import json

import pandas as pd

from services import data_store


def test_ondemand_fills_only_missing_and_latest_wins(tmp_path, monkeypatch):
    cache = {
        '00000009|2026-01-01': {'researcher_id': '00000009', 'as_of': '2026-01-01', 'strength_fields': ['예전']},
        '00000009|2026-11-12': {'researcher_id': '00000009', 'as_of': '2026-11-12', 'strength_fields': ['최신']},
        '00000008|2026-11-12': {'researcher_id': '00000008', 'as_of': '2026-11-12', 'error': '데이터 없음'},
        '00000001|2026-11-12': {'researcher_id': '00000001', 'as_of': '2026-11-12', 'strength_fields': ['별도']},
    }
    path = tmp_path / 'c.json'
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(data_store, 'ONDEMAND_CACHE_PATH', str(path))
    monkeypatch.setattr(data_store, '_read_json_records',
                        lambda *a: [{'researcher_id': '00000001', 'strength_fields': ['배치']}])
    assert set(data_store.read_expertise_profiles()) == {'00000001'}                     # 기본값은 배치만
    merged = data_store.read_expertise_profiles(include_ondemand=True)
    assert merged['00000001']['strength_fields'] == ['배치']                            # 배치가 우선
    assert merged['00000009']['strength_fields'] == ['최신'] and merged['00000009']['_source'] == 'ondemand'
    assert '00000008' not in merged                                                      # 오류 결과는 제외


def test_missing_options_only_non_current_without_profile(monkeypatch):
    import app  # noqa: F401
    from pages import researcher_similarity_map as m
    df = pd.DataFrame([
        {'researcher_id': '00000001', 'name': '재직', 'department': 'A', 'is_current': 'Y', 'valid_year': 2026, 'valid_month': 10},
        {'researcher_id': '00000002', 'name': '파견', 'department': 'B', 'is_current': 'N', 'valid_year': 2026.0, 'valid_month': 5.0},
        {'researcher_id': '00000003', 'name': '분석됨', 'department': 'B', 'is_current': 'N', 'valid_year': 2025, 'valid_month': 3},
    ])
    monkeypatch.setattr(m, 'read_processed', lambda name: df)
    monkeypatch.setattr(m, 'read_expertise_profiles', lambda include_ondemand=False: {'00000003': {}})
    opts = m._missing_expertise_options()
    assert [o['value'] for o in opts] == ['00000002'] and '마지막 인력현황 2026-05' in opts[0]['label']


def test_job_market_individual_uses_ondemand_for_selected_only(monkeypatch):
    """JOB Market 개인별 검색 — 배치 분석이 없는 대상자는 별도 분석으로 추천, 후보 과제(근거 B)는 배치만(2026-11-12)."""
    from services import job_market as jm
    batch = {'00000001': {'researcher_id': '00000001', 'strength_fields': ['배치']}}
    monkeypatch.setattr(jm.data_store, 'read_expertise_profiles_std', lambda: dict(batch))
    monkeypatch.setattr(jm.data_store, 'read_ondemand_expertise_latest', lambda: {
        '00000009': {'researcher_id': '00000009', 'strength_fields': ['파견']},
        '00000007': {'researcher_id': '00000007', 'strength_fields': ['선택 안 함']}})
    monkeypatch.setattr(jm.data_store, 'read_processed', lambda name: pd.DataFrame(
        [{'researcher_id': r, 'org_code': ''} for r in ('00000001', '00000009')]))
    monkeypatch.setattr(jm, 'build_roster', lambda ids: [{'researcher_id': r} for r in ids])
    monkeypatch.setattr(jm, 'save_history', lambda report: 'h.json')
    pools, seen = [], {}
    monkeypatch.setattr(jm, '_build_candidate_pool', lambda excl, profiles: pools.append(set(profiles)) or {'P': {}})
    monkeypatch.setattr(jm, '_safe_context', lambda profiles: None)

    def fake_recommend(rid, profiles, pool, ctx):
        seen[rid] = profiles.get(rid)
        return {'recommendations': []}
    monkeypatch.setattr(jm, 'recommend_for_researcher', fake_recommend)
    monkeypatch.setattr(jm.llm_client, 'run_concurrent', lambda tasks, **k: [(t(), None) for t in tasks])
    jm.run_individual_search(['00000001', '00000009'], [])
    assert seen['00000001']['strength_fields'] == ['배치']
    assert seen['00000009']['strength_fields'] == ['파견'] and seen['00000009']['_source'] == 'ondemand'
    assert pools == [{'00000001'}]                                    # 후보 과제 풀은 배치 분석만
