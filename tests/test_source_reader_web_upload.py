"""read_source: 화면 업로드가 원천 사본보다 새것이면 그 파일을 읽는다(모든 원천 공통, 2026-10-15)."""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import source_reader as sr  # noqa: E402


def _setup(tmp_path, monkeypatch):
    web, raw = tmp_path / 'web', tmp_path / 'raw_csv'
    raw.mkdir()
    monkeypatch.setattr(sr, 'WEB_UPDATES_DIR', str(web))
    monkeypatch.setattr(sr, 'RAW_CSV_DIR', str(raw))
    monkeypatch.setattr(sr, '_read_from_db', lambda name: None)
    monkeypatch.setattr('excel_reader.read_xlsx', lambda path, header_row=0: pd.DataFrame(
        {'KNOXID': ['00212121'], '해제일': [20260922], 'src': [os.path.basename(path)]}))
    return web, raw


def test_newer_web_upload_wins(tmp_path, monkeypatch):
    web, raw = _setup(tmp_path, monkeypatch)
    pd.DataFrame({'KNOXID': ['00212121'], '해제일': [''], 'src': ['old']}).to_csv(raw / 'patents.csv', index=False)
    time.sleep(0.01)
    (web / 'patents').mkdir(parents=True)
    (web / 'patents' / '특허 리스트.xlsx').write_bytes(b'')
    df = sr.read_source('patents')
    assert df['src'].tolist() == ['특허 리스트.xlsx'] and df['해제일'].tolist() == ['20260922']


def test_older_web_upload_ignored(tmp_path, monkeypatch):
    web, raw = _setup(tmp_path, monkeypatch)
    (web / 'patents').mkdir(parents=True)
    f = web / 'patents' / '특허 리스트.xlsx'
    f.write_bytes(b'')
    os.utime(f, (0, 0))
    pd.DataFrame({'KNOXID': ['1'], 'src': ['csv']}).to_csv(raw / 'patents.csv', index=False)
    assert sr.read_source('patents')['src'].tolist() == ['csv']


def test_wildcard_single_file_and_work_objective_slot(tmp_path, monkeypatch):
    web, _raw = _setup(tmp_path, monkeypatch)
    (web / 'tasks').mkdir(parents=True)
    (web / 'tasks' / '과제투입_수정본.xlsx').write_bytes(b'')       # 패턴 불일치지만 폴더에 엑셀 1개
    assert sr.read_source('tasks')['src'].tolist() == ['과제투입_수정본.xlsx']
    from sources import SOURCES
    wo = next(e for e in SOURCES if e[0].startswith('work_objective_'))
    (web / 'work_objective_2').mkdir(parents=True)
    (web / 'work_objective_2' / wo[1]).write_bytes(b'')
    assert sr.read_source(wo[0])['src'].tolist() == [wo[1]]


def test_no_web_upload_falls_back(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert sr.read_source('patents') is None


def test_web_valid_date_recorded_for_same_files(tmp_path, monkeypatch):
    import json
    from datetime import date
    web, _raw = _setup(tmp_path, monkeypatch)
    d = web / 'evaluations'
    d.mkdir(parents=True)
    (d / 'T&P 기본 인사 정보 2025.xlsx').write_bytes(b'')
    assert sr.read_source('evaluations') is not None
    assert sr.web_valid_date('evaluations') is None              # 기록 없음 → 호출부는 오늘
    (d / sr.VALID_DATE_FILE).write_text(json.dumps({'files': ['T&P 기본 인사 정보 2025.xlsx'],
                                                    'valid_date': '2025-12-01'}), encoding='utf-8')
    assert sr.web_valid_date('evaluations') == date(2025, 12, 1)
    (d / sr.VALID_DATE_FILE).write_text(json.dumps({'files': ['다른파일.xlsx'], 'valid_date': '2025-12-01'}),
                                        encoding='utf-8')
    assert sr.web_valid_date('evaluations') is None              # 다른 업로드에 대한 기록이면 무시
