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
