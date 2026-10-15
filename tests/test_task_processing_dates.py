"""과제 투입기간 해제일 오타(10자리 등) — 진행중으로 남지 않고 뒤 구간과 이어 붙임(2026-10-15)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
import process_tasks as pt  # noqa: E402
from excel_reader import parse_yyyymmdd  # noqa: E402


def _df(rows):
    return pd.DataFrame([{'researcher_id': '00212121', 'task_name': '[연구]소재개발', 'start_date': parse_yyyymmdd(s),
                          'end_date': parse_yyyymmdd(e), 'input_rate': '100'} for s, e in rows])


def test_typo_end_date_merges_with_later_period():
    df = _df([('20250715', '20260922'), ('20250614', '20250715'), ('20190218', '2020250614')])
    out = pt._merge_consecutive_periods(pt._clean_dates(df))
    assert out[['start_date', 'end_date']].values.tolist() == [['2019-02-18', '2026-09-22']]


def test_blank_end_without_later_period_stays_ongoing():
    out = pt._merge_consecutive_periods(pt._clean_dates(_df([('20190218', '20200101'), ('20240101', '')])))
    assert out[['start_date', 'end_date']].values.tolist() == [['2019-02-18', '2020-01-01'], ['2024-01-01', '']]


def test_invalid_start_row_dropped():
    out = pt._clean_dates(_df([('2019021', '20200101'), ('20240101', '20250101')]))
    assert out['start_date'].tolist() == ['2024-01-01']


def test_run_integration_prefers_newer_web_upload(tmp_path, monkeypatch):
    """화면 업로드 후 run_integration(기본 경로)이 옛 원천 사본으로 tasks.csv를 덮어쓰지 않는다(2026-10-15)."""
    import time
    web = tmp_path / 'web'
    web.mkdir()
    raw_csv = tmp_path / 'tasks.csv'
    raw_csv.write_text('x', encoding='utf-8')
    time.sleep(0.01)
    (web / '개인별과제투입기간데이터_260114.xlsx').write_bytes(b'')
    monkeypatch.setattr(pt, 'WEB_UPLOAD_DIR', str(web))
    monkeypatch.setattr(pt, 'RAW_CSV_PATH', str(raw_csv))
    assert pt._newer_web_upload() == str(web)
    os.utime(raw_csv, None)   # 원천 사본이 더 새것이면 원천 사본 사용
    os.utime(web / '개인별과제투입기간데이터_260114.xlsx', (0, 0))
    assert pt._newer_web_upload() is None
