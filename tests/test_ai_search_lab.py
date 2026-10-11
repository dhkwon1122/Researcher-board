import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
sys.path.insert(0, ROOT)

import llm_client  # noqa: E402
from services import ai_search_lab as lab  # noqa: E402
from services import nl_query  # noqa: E402
from services import web_pipeline_runner as wpr  # noqa: E402


def _tmp_lab(monkeypatch, tmp_path):
    monkeypatch.setattr(wpr, 'WEB_UPDATES_DIR', str(tmp_path))


def _wait():
    for _ in range(200):
        if not lab.is_busy():
            return
        time.sleep(0.05)


def test_golden_compare_precision_recall_f1():
    g = lab._golden_compare(['00000001', '00000002', '00000003'], {'00000001', '00000002', '00000009'})
    assert g['precision'] == 0.667 and g['recall'] == 0.667 and g['f1'] == 0.667
    assert g['missing_sample'] == ['00000003'] and g['extra_sample'] == ['00000009']
    assert lab._golden_compare([], set())['f1'] == 0.0


def test_normalize_items_dedupes_and_drops_blank():
    items = lab._normalize_items([{'question': ' a '}, {'question': 'a'}, {'question': ''}, {'question': 'b', 'category': '복합 조건'}])
    assert [i['question'] for i in items] == ['a', 'b'] and items[1]['category'] == '복합 조건'


def test_status_rules():
    base = {'intent': 'open_data_query', 'row_count': 5, 'flags': [], 'golden': None, 'judge': None}
    assert lab._status({'category': '복합 조건'}, base) == '양호'
    assert lab._status({'category': '복합 조건'}, {**base, 'flags': ['error']}) == '실패'
    assert lab._status({'category': '복합 조건'}, {**base, 'flags': ['empty'], 'row_count': 0}) == '주의'
    assert lab._status({'category': '정답 대조'}, {**base, 'golden': {'f1': 0.3}}) == '실패'
    assert lab._status({'category': '정답 대조'}, {**base, 'golden': {'f1': 0.7}}) == '주의'
    assert lab._status({'category': '복합 조건'}, {**base, 'judge': {'score': 2}}) == '실패'
    neg = {'category': lab.NEGATIVE_CATEGORY}
    assert lab._status(neg, {**base, 'intent': 'unsupported', 'row_count': 0}) == '양호'
    assert lab._status(neg, {**base, 'row_count': 5}) == '실패'


def test_run_one_uses_real_pipeline_shape_and_scores(monkeypatch):
    monkeypatch.setattr(nl_query, 'parse_question', lambda q: {'intent': 'x', 'question': q})
    monkeypatch.setattr(nl_query, 'execute_query', lambda parsed, current_only=True, period=None: {
        'intent': 'find_researchers_by_criteria', 'columns': ['researcher_id', 'name'], 'labels': ['사번', '성명'],
        'rows': [['00000001', 'A'], ['00000002', 'B']], 'total_rows': 2, 'note': ''})
    monkeypatch.setattr(nl_query, '_generate_answer_summary', lambda q, r: '- 설명')
    monkeypatch.setattr(llm_client, 'call_llm', lambda *a, **k: json.dumps({'score': 5, 'issue_type': '정확', 'reason': 'ok'}))
    item = {'id': '1', 'category': '정답 대조', 'question': '테스트', 'expected': {'ids': ['00000001', '00000002'], 'desc': 'd'}}
    rec = lab.run_one(item)
    assert rec['golden']['f1'] == 1.0 and rec['judge']['score'] == 5 and rec['status'] == '양호'
    assert rec['row_count'] == 2 and rec['answer'] == '- 설명' and rec['flags'] == []


def test_run_one_survives_exceptions(monkeypatch):
    def boom(q):
        raise RuntimeError('x')
    monkeypatch.setattr(nl_query, 'parse_question', boom)
    rec = lab.run_one({'question': 'q', 'category': '복합 조건'}, judge=False)
    assert rec['intent'] == 'error' and rec['status'] == '실패'


def test_batch_run_persists_results_and_compare(monkeypatch, tmp_path):
    _tmp_lab(monkeypatch, tmp_path)
    monkeypatch.setattr(nl_query, 'parse_question', lambda q: {'intent': 'x', 'question': q})
    monkeypatch.setattr(nl_query, 'execute_query', lambda parsed, current_only=True, period=None: {
        'intent': 'open_data_query', 'columns': ['researcher_id'], 'labels': ['사번'], 'rows': [['00000001']],
        'total_rows': 1, 'note': '', 'sql': 'SELECT 1'})
    monkeypatch.setattr(nl_query, '_generate_answer_summary', lambda q, r: '- 설명')
    scores = iter([2, 5])
    monkeypatch.setattr(llm_client, 'call_llm', lambda *a, **k: json.dumps({'score': next(scores), 'issue_type': '기타', 'reason': 'r'}))
    items = [{'question': 'q1', 'category': '복합 조건'}]
    ok, _, run_a = lab.start_run(items, None, label='before')
    assert ok
    _wait()
    time.sleep(1.1)   # run_id가 초 단위라 구분
    ok, _, run_b = lab.start_run(items, None, label='after')
    assert ok
    _wait()
    a, b = lab.load_run(run_a), lab.load_run(run_b)
    assert a['status'] == b['status'] == 'done' and a['summary']['n'] == 1
    cmp = lab.compare_runs(a, b)[0]
    assert cmp['score_before'] == 2 and cmp['score_after'] == 5 and cmp['delta_score'] == 3
    assert len(lab.list_runs()) == 2 and lab.build_run_workbook(b)[:2] == b'PK'


def test_busy_guard_and_stale_job(monkeypatch, tmp_path):
    _tmp_lab(monkeypatch, tmp_path)
    ok, _ = lab._begin('run', 3, 'x')
    assert ok and lab.is_busy()
    ok2, reason = lab._begin('run', 3, 'y')
    assert not ok2 and '실행 중' in reason
    lab._save_job()
    raw = json.load(open(lab._job_path(), encoding='utf-8'))
    raw['updated_at'] = 1.0
    json.dump(raw, open(lab._job_path(), 'w', encoding='utf-8'))
    assert lab.job_state()['status'] == 'error' and not lab.is_busy()


def test_acting_as_overrides_current_user():
    from services import auth
    with auth.acting_as({'user_id': 'u', 'role': 'admin', 'is_admin': True, 'permissions': {}}):
        assert auth.get_current_user()['user_id'] == 'u' and auth.can('manage_users')
