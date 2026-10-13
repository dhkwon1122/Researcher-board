"""과제별컨플: 관리자 화면 업로드 파일이 원천 사본보다 새것이면 그것을 "이번 업로드"로 쓴다(2026-10-13)."""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import process_project_confl as ppc  # noqa: E402


def _xlsx(path, names):
    pd.DataFrame({'소속': ['A'] * len(names), '과제명': names, '컨플 주소': [''] * len(names)}).to_excel(path, index=False)


def test_newer_web_upload_wins_and_marks_current(tmp_path, monkeypatch):
    web = tmp_path / 'web'
    web.mkdir()
    raw_csv = tmp_path / 'raw.csv'
    out = tmp_path / 'out'
    out.mkdir()
    pd.DataFrame({'소속': ['A'], '과제명': ['옛과제'], '컨플 주소': ['']}).to_csv(raw_csv, index=False, encoding='utf-8-sig')
    old = time.time() - 100
    os.utime(raw_csv, (old, old))
    _xlsx(web / ppc.SOURCE_FILE, ['새과제'])
    monkeypatch.setattr(ppc, 'WEB_UPLOAD_DIR', str(web))
    monkeypatch.setattr(ppc, 'RAW_CSV_PATH', str(raw_csv))
    monkeypatch.setattr(ppc, 'OUT_DIR', str(out))
    monkeypatch.setattr(ppc, 'read_source', lambda name: pd.read_csv(raw_csv, dtype=str).fillna(''))

    # 이전 실행 결과: 옛과제가 현재(Y)였던 상태
    pd.DataFrame({'dep_name': ['A'], 'project_name': ['옛과제'], 'confl_address': [''], 'org_code': [''],
                  'is_current': ['Y']}).to_csv(out / 'project_confl_address.csv', index=False, encoding='utf-8-sig')
    assert ppc._newer_web_upload() is not None
    assert ppc.process()
    df = pd.read_csv(out / 'project_confl_address.csv', dtype=str).fillna('')
    cur = dict(zip(df['project_name'], df['is_current']))
    assert cur == {'옛과제': 'N', '새과제': 'Y'}


def test_raw_csv_newer_than_upload_is_used(tmp_path, monkeypatch):
    web = tmp_path / 'web'
    web.mkdir()
    _xlsx(web / ppc.SOURCE_FILE, ['업로드과제'])
    old = time.time() - 100
    os.utime(web / ppc.SOURCE_FILE, (old, old))
    raw_csv = tmp_path / 'raw.csv'
    raw_csv.write_text('x')
    monkeypatch.setattr(ppc, 'WEB_UPLOAD_DIR', str(web))
    monkeypatch.setattr(ppc, 'RAW_CSV_PATH', str(raw_csv))
    assert ppc._newer_web_upload() is None
