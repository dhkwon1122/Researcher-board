"""과제별컨플 "비공식소속부서명" 선택 열(2026-10-13) — 과제명 대신 과제원 매칭 키로 쓰인다."""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))

import researcher_fit as fit  # noqa: E402

CONFL = pd.DataFrame([
    {'dep_name': 'D', 'project_name': '[연구] 발광소재 개발', 'confl_address': '1', 'org_code': '발광소재파트'},
    {'dep_name': 'D', 'project_name': '전지과제', 'confl_address': '2', 'org_code': ''},
])
RESEARCHERS = pd.DataFrame({'researcher_id': ['00000001', '00000002', '00000003'], 'name': ['갑', '을', '병'],
                            'department': ['d'] * 3, 'org_code': ['발광소재파트', '전지과제', '기타']})


def test_override_helpers():
    ov = fit.project_org_overrides(CONFL)
    assert ov == {'발광소재개발': '발광소재파트'}
    assert fit.project_member_key('[연구] 발광소재 개발', ov) == '발광소재파트'
    assert fit.project_member_key('전지과제', ov) == '전지과제'           # 빈 값 → 기존처럼 과제명
    assert fit.project_org_code('[연구]발광소재개발', ov) == '발광소재파트'
    assert fit.project_org_overrides(CONFL.drop(columns=['org_code'])) == {}   # 열 없는 옛 파일


def test_members_and_personnel_use_override(monkeypatch):
    from services import data_store as ds
    from services import jd_reconciliation as jd
    monkeypatch.setattr(ds, 'read_processed',
                        lambda name, **k: {'researchers': RESEARCHERS, 'project_confl_address': CONFL}.get(name, pd.DataFrame()))
    jd._ORG_OVERRIDE_CACHE['ts'] = 0.0
    assert [m['researcher_id'] for m in jd.get_project_members('[연구] 발광소재 개발')] == ['00000001']
    assert [m['researcher_id'] for m in jd.get_project_members('전지과제')] == ['00000002']

    from pipeline import process_project_expertise as ppe
    ov = fit.project_org_overrides(CONFL)
    got = ppe._resolve_personnel('[연구] 발광소재 개발', [{'name': '갑', 'role_description': 'r'}], RESEARCHERS, ov)
    assert got[0]['researcher_id'] == '00000001'
    assert ppe._resolve_personnel('[연구] 발광소재 개발', [{'name': '갑'}], RESEARCHERS)[0]['researcher_id'] == ''


def test_gap_team_and_job_market_exclusion(monkeypatch):
    import numpy as np
    from pipeline import process_project_competency_gap as gap
    monkeypatch.setattr(gap.fit, 'cached_embed', lambda ts: np.ones((len(ts), 4)))
    ov = fit.project_org_overrides(CONFL)
    members = {'발광소재파트': {'00000001'}}
    res = gap.analyze_gaps([{'project_name': '[연구] 발광소재 개발'}], {'[연구] 발광소재 개발': ['광학']}, members,
                           {'00000001': ['광학']}, {'00000001'}, org_overrides=ov)
    assert res[0]['member_count'] == 1 and res[0]['org_code'] == '발광소재파트'

    from services import job_market as jm
    rows = jm._dedup_candidate_rows(CONFL)
    assert rows[0]['member_key'] == '발광소재파트'
    # 본인 소속(발광소재파트)으로 제외하면 과제명이 달라도 후보에서 빠진다
    monkeypatch.setattr(jm.data_store, 'read_processed', lambda name, **k: CONFL)
    monkeypatch.setattr(jm.jd, 'get_project_members', lambda name: [])
    monkeypatch.setattr(jm.jd, 'read_confluence_summary', lambda name: {'core_tech': 'x'})
    monkeypatch.setattr(jm.jd, 'confluence_context_text', lambda e: 'x')
    monkeypatch.setattr(jm.fit, 'cached_embed', lambda ts: np.ones((len(ts), 4)))
    pool = jm._build_candidate_pool({'발광소재파트'}, {})
    assert list(pool) == ['전지과제']


def test_job_market_projects_by_levels(monkeypatch):
    from services import job_market as jm
    from services import similarity_map as sm
    confl = pd.DataFrame([
        {'dep_name': 'D', 'project_name': '[연구] 발광소재 개발', 'org_code': '발광파트'},   # 비공식소속부서명으로 매칭
        {'dep_name': 'D', 'project_name': '전지과제', 'org_code': ''},                      # 3단계부서명으로 매칭
        {'dep_name': 'D', 'project_name': '기타과제', 'org_code': ''},
    ])
    rows = [{'org_name_wd': '발광파트', 'dep_3rd_name': '발광소재파트'},
            {'org_name_wd': 'ORG-9', 'dep_3rd_name': '전지 과제'}]
    monkeypatch.setattr(jm.data_store, 'read_processed', lambda name, **k: confl)
    monkeypatch.setattr(sm, 'org_rows_for_levels', lambda l1, l2, l3: rows if (l1 or l2) else None)
    assert jm.list_projects_by_levels(None, None) == ['[연구] 발광소재 개발', '기타과제', '전지과제']
    assert jm.list_projects_by_levels(['P'], None) == ['[연구] 발광소재 개발', '전지과제']


def test_confl_is_current_marking(tmp_path, monkeypatch):
    """두 번 올리면: 두 번째 파일에 있는 행 Y, 첫 파일에만 있던 행 N(기록은 보존)."""
    from pipeline import process_project_confl as pc
    monkeypatch.setattr(pc, 'OUT_DIR', str(tmp_path / 'out'))
    os.makedirs(tmp_path / 'out')

    def upload(rows):
        d = tmp_path / f'raw{len(rows)}'
        os.makedirs(d, exist_ok=True)
        monkeypatch.setattr(pc, 'resolve_excel', lambda raw_dir, name: str(d / name))
        monkeypatch.setattr(pc, 'read_xlsx', lambda path: pd.DataFrame(rows))
        (d / '과제별컨플.xlsx').write_bytes(b'x')
        assert pc.process(raw_dir=str(d))
        return pd.read_csv(tmp_path / 'out' / 'project_confl_address.csv', dtype=str).fillna('')

    upload([{'소속': 'D', '과제명': '옛과제', '컨플 주소': '1'}, {'소속': 'D', '과제명': '유지과제', '컨플 주소': '2'}])
    out = upload([{'소속': 'D', '과제명': '유지과제', '컨플 주소': '2'}, {'소속': 'D', '과제명': '새과제', '컨플 주소': '3'}])
    flags = dict(zip(out['project_name'], out['is_current']))
    assert flags == {'옛과제': 'N', '유지과제': 'Y', '새과제': 'Y'}
    assert sorted(fit.current_rows(out)['project_name']) == ['새과제', '유지과제']


def test_current_only_members_and_projects(monkeypatch):
    from services import data_store as ds
    from services import jd_reconciliation as jd
    from services import job_market as jm
    researchers = RESEARCHERS.assign(is_current=['Y', 'N', 'Y'])          # 을(전지과제)은 퇴직·전배
    confl = CONFL.assign(is_current=['Y', 'N'])                           # 전지과제는 과제별컨플에서 빠짐
    tables = {'researchers': researchers, 'project_confl_address': confl}
    monkeypatch.setattr(ds, 'read_processed', lambda name, **k: tables.get(name, pd.DataFrame()))
    jd._ORG_OVERRIDE_CACHE['ts'] = 0.0
    assert jd.get_project_members('전지과제') == []                         # 현재 소속자만
    assert [m['researcher_id'] for m in jd.get_project_members('[연구] 발광소재 개발')] == ['00000001']
    assert jm.list_projects_by_levels(None, None) == ['[연구] 발광소재 개발']   # 최신 과제별컨플만
    assert jd.list_project_names() == ['[연구] 발광소재 개발']
