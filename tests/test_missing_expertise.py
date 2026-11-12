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
