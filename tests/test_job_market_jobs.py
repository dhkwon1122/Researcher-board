"""JOB Market 백그라운드 검색 — 종료 상태(완료/결과 없음/오류/중단) 표시(2026-10-16)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import job_market as jm  # noqa: E402
from services import job_market_jobs as jobs  # noqa: E402


def _wait(job_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        job = jobs.get(job_id)
        if job['status'] != 'running':
            return job
        time.sleep(0.05)
    raise AssertionError('작업이 끝나지 않음')


def test_done_error_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, 'JOBS_DIR', str(tmp_path))

    def ok(names, excluded, progress=None):
        progress('추천 계산(LLM)', 1, 2)
        return {'results': {'a': {'recommendations': [{'x': 1}]}, 'b': {'recommendations': []}}, 'history_file': 'h.json'}
    monkeypatch.setattr(jm, 'run_project_search', ok)
    job = _wait(jobs.start('u1', 'project', {'project_names': ['P']})['id'])
    assert job['status'] == 'done' and job['people'] == 2 and job['recommended'] == 1 and job['history_file'] == 'h.json'
    assert job['finished_at']

    monkeypatch.setattr(jm, 'run_project_search', lambda *a, **k: {'error': '배정된 인원이 없습니다.'})
    job = _wait(jobs.start('u1', 'project', {'project_names': ['P']})['id'])
    assert job['status'] == 'error' and '인원' in job['message']

    def boom(*a, **k):
        raise RuntimeError('LLM 서버 응답 없음')
    monkeypatch.setattr(jm, 'run_individual_search', boom)
    job = _wait(jobs.start('u1', 'individual', {'researcher_ids': ['1']})['id'])
    assert job['status'] == 'failed' and 'LLM 서버' in job['message']


def test_lost_when_heartbeat_stops_and_single_run(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, 'JOBS_DIR', str(tmp_path))
    gate = {'go': False}

    def slow(*a, **k):
        while not gate['go']:
            time.sleep(0.02)
        return {'results': {}, 'history_file': ''}
    monkeypatch.setattr(jm, 'run_project_search', slow)
    job = jobs.start('u1', 'project', {'project_names': ['P']})
    assert jobs.start('u1', 'project', {'project_names': ['Q']}).get('already_running')   # 사용자당 1건
    # 워커가 죽은 상황 흉내: heartbeat를 오래전으로
    j = jobs._read(job['id']); j['heartbeat'] = time.time() - jobs.STALE_SECONDS - 5; jobs._write(j)
    lost = jobs.get(job['id'])
    assert lost['status'] == 'lost' and '종료' in lost['message']
    gate['go'] = True
