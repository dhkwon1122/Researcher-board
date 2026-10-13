"""타임라인 과제 카드 중복(2026-10-13): 같은 구간이 두 행이어도 카드 하나, 옛 과제명 행 정리."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))

ROWS = [('2019-04-01', '2021-10-11', 'AMD'), ('2021-10-12', '2022-12-07', '[탐구]AMD'),
        ('2022-12-08', '2023-04-19', '[연구]AMD'), ('2023-04-20', '2023-04-27', '[연구]AMS'),
        ('2023-04-28', '2025-05-01', '[연구]차세대AMS')]


def _rows(task_name):
    return [dict(researcher_id='00000001', task_name=task_name, start_date=s, end_date=e, input_rate='100',
                 task_code='AAA', the_task_name=n) for s, e, n in ROWS]


def test_task_points_dedupes_same_period():
    from components.timeline_data import task_points
    pts = task_points(pd.DataFrame(_rows('[연구]차세대AMS') + _rows('[연구]AMD')))
    assert [p['task_name'] for p in pts] == ['AMD', '[탐구]AMD', '[연구]AMD', '[연구]차세대AMS']


def test_drop_stale_removes_old_task_name_rows_with_same_code(tmp_path, monkeypatch):
    import process_tasks as pt
    out = tmp_path / 'tasks.csv'
    other = dict(researcher_id='00000002', task_name='[연구]AMD', start_date='2020-01-01', end_date='',
                 input_rate='100', task_code='AAA', the_task_name='[연구]AMD')
    pd.DataFrame(_rows('[연구]AMD') + [other]).to_csv(out, index=False, encoding='utf-8-sig')
    monkeypatch.setattr(pt, 'OUTPUT', str(out))
    pt._drop_stale_task_rows(pd.DataFrame(_rows('[연구]차세대AMS')))
    left = pd.read_csv(out, dtype=str, keep_default_na=False)
    assert list(left['researcher_id']) == ['00000002']   # 다른 사람 행은 보존
