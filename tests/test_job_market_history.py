"""JOB Market D 과제 참여 이력 + 과제정보 근거 A(2026-10-15)."""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import job_market_history as jmh  # noqa: E402

TASKS = pd.DataFrame([
    # 1: X(2020~2023) → Y(2023-02~) / 2: X(2020~2023) → Y(2023-03~) / 3: X(2021~2024) → Z / 4: Y 계속
    {'researcher_id': '1', 'task_name': '과제X', 'task_code': 'CX', 'start_date': '2020-01-01', 'end_date': '2023-01-31'},
    {'researcher_id': '1', 'task_name': '[연구] 과제 Y', 'task_code': 'CY', 'start_date': '2023-02-01', 'end_date': ''},
    {'researcher_id': '2', 'task_name': '과제X', 'task_code': 'CX', 'start_date': '2020-06-01', 'end_date': '2023-02-28'},
    {'researcher_id': '2', 'task_name': '과제Y', 'task_code': 'CY', 'start_date': '2023-03-01', 'end_date': ''},
    {'researcher_id': '3', 'task_name': '과제X', 'task_code': 'CX', 'start_date': '2021-01-01', 'end_date': '2024-06-30'},
    {'researcher_id': '3', 'task_name': '과제Z', 'task_code': 'CZ', 'start_date': '2024-07-01', 'end_date': ''},
    {'researcher_id': '4', 'task_name': '옛이름Y', 'task_code': 'CY', 'start_date': '2019-01-01', 'end_date': ''},
    {'researcher_id': '5', 'task_name': '과제X', 'task_code': 'CX', 'start_date': '2022-01-01', 'end_date': ''},
])
H = jmh.TaskHistory(TASKS, [('신과제Y', 'CY')], today=date(2026, 10, 15))


def test_keys_and_transitions():
    assert H.key_for_project('[연구] 과제Y') == 'CY' and H.key_for_project('신과제 Y') == 'CY'
    assert H.key_for_project('없는과제') is None
    assert sorted((f, t, r) for f, t, r, _w in H.transitions) == [('CX', 'CY', '00000001'), ('CX', 'CY', '00000002'),
                                                                 ('CX', 'CZ', '00000003')]


def test_signal_experience_peers_flow():
    s = H.signal('5', '과제Y', member_ids=['00000001', '00000002', '00000004'])
    assert s['experience'] is None
    assert s['peers'] == ['00000001', '00000002']               # 과제X에서 30일 이상 겹침
    assert s['flow'] == {'count': 2, 'total': 3, 'share': 0.667}  # X에서 끝난 3명 중 2명이 Y로
    assert abs(s['score'] - (0.3 * 2 / 3 + 0.2 * 0.667)) < 1e-3
    back = H.signal('1', '과제Y', member_ids=[], as_of=date(2026, 1, 1))
    assert back['experience']['score'] == 1.0


def test_as_of_hides_future():
    s = H.signal('5', '과제Y', member_ids=['00000001'], as_of=date(2023, 2, 15), from_keys={'CX'})
    assert s['flow'] == {'count': 1, 'total': 1, 'share': 1.0}   # 2번(2023-03) 이동은 아직 안 보임
    assert H.members_at('CY', date(2022, 1, 1)) == {'00000004'}


def test_task_info_lookup_and_signal_text(monkeypatch):
    from services import data_store
    from services import job_market as jm
    info = pd.DataFrame([{'task_name': '과제Y', 'task_code': 'CY', 'task_goal': '고효율 소재 확보', 'write_date': '2025-01-01'}])
    monkeypatch.setattr(data_store, 'read_processed',
                        lambda n, **k: {'tasks_information': info, 'tasks': TASKS}.get(n, pd.DataFrame()))
    look = jm._task_info_lookup()
    assert look('[연구] 과제 Y') == '목표: 고효율 소재 확보'
    assert look('옛이름Y') == '목표: 고효율 소재 확보'          # 과제코드 경유
    assert look('없는과제') == ''
    assert '옛 동료' not in jmh.signal_text({'score': 0.3, 'experience': None, 'peers': ['1'], 'flow': None})
    assert '함께 일한 현재 과제원 1명' in jmh.signal_text({'score': 0.3, 'experience': None, 'peers': ['1'], 'flow': None})
