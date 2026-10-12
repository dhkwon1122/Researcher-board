"""run_integration 결과 자동 점검(verify_outputs) + 과제 문서 분석 실패 시 직전 결과 유지(2026-10-12)."""
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))

from pipeline import verify_outputs as vo  # noqa: E402


def _write(tmp, name, obj):
    with open(os.path.join(tmp, name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


def test_verify_ok_and_old(tmp_path, monkeypatch):
    monkeypatch.setattr(vo, 'OUT_DIR', str(tmp_path))
    pd.DataFrame([{'researcher_a': '1', 'researcher_b': '2', 'recent_count': 1, 'level1_a': 'P1', 'level1_b': 'P2',
                   'level3_a': 'T1', 'level3_b': 'T2'}]).to_csv(tmp_path / 'collaboration_edges.csv', index=False)
    pd.DataFrame([{'technology': 'X', 'aliases': 'X 기반'}]).to_csv(tmp_path / 'technology_holder_summary.csv', index=False)
    _write(tmp_path, 'project_competency_gap.json',
           [{'project_name': 'P', 'competencies': [{'competency': 'A', 'description': '쉬운 설명',
                                                    'members': [{'reason': 'r'}], 'outsiders': []}]}])
    res = vo.check_files()
    assert all(level == 'OK' for level, _ in res), res

    # 옛 형식(최신 열/설명 필드 없음) → WARN
    pd.DataFrame([{'researcher_a': '1', 'researcher_b': '2'}]).to_csv(tmp_path / 'collaboration_edges.csv', index=False)
    _write(tmp_path, 'project_competency_gap.json', [{'project_name': 'P', 'competencies': [{'competency': 'A'}]}])
    warns = [m for level, m in vo.check_files() if level == 'WARN']
    assert any('collaboration_edges' in m for m in warns)
    assert any('옛 코드' in m and '과제별 필요 역량' in m for m in warns)


def test_project_analysis_keeps_previous_on_failure(tmp_path, monkeypatch):
    from pipeline import process_project_expertise as ppe
    monkeypatch.setattr(ppe, 'OUT_DIR', str(tmp_path))
    prev = [{'dep_name': 'D', 'project_name': 'A', 'core_tech': 'old', 'personnel': [
        {'researcher_id': '00000001', 'name': '홍', 'name_suffix': '', 'role_description': 'r'}]}]
    _write(tmp_path, 'project_expertise_analysis.json', prev)
    monkeypatch.setattr(ppe, '_read_projects', lambda: pd.DataFrame(
        [{'dep_name': 'D', 'project_name': 'A', 'confl_address': 'u1'},
         {'dep_name': 'D', 'project_name': 'B', 'confl_address': 'u2'}]))
    monkeypatch.setattr(ppe.fit, 'read_researchers', lambda d: pd.DataFrame())
    monkeypatch.setattr(ppe.project_summary, 'load_page_cache', lambda: {})
    monkeypatch.setattr(ppe.project_summary, 'load_cache', lambda: {})
    monkeypatch.setattr(ppe.project_summary, 'save_page_cache', lambda c: None)
    monkeypatch.setattr(ppe.project_summary, 'save_cache', lambda c: None)
    monkeypatch.setattr(ppe.project_summary, 'get_project_summary', lambda *a, **k: None)  # 전부 조회 실패
    monkeypatch.setattr(ppe.result_archive, 'archive_copy', lambda *a, **k: None)
    monkeypatch.setattr(ppe, 'build_html', lambda *a, **k: '')
    assert ppe.process()
    with open(tmp_path / 'project_expertise_analysis.json', encoding='utf-8') as f:
        out = json.load(f)
    assert [x['project_name'] for x in out] == ['A'] and out[0]['core_tech'] == 'old'
    pers = pd.read_csv(tmp_path / 'project_personnel.csv', dtype=str)
    assert list(pers['researcher_id']) == ['00000001'] and list(pers['project_name']) == ['A']
