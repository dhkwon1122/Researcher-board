"""
JOB Market 검색 백그라운드 실행(2026-10-16, 사용자 요청: "결과가 나오든 안 나오든 프로세스가 종료됐는지는 알려줘야").

원인: 검색이 브라우저 요청 하나 안에서 끝까지 돌았다 — 인원이 많아 LLM 추천이 GUNICORN_TIMEOUT(300초)을 넘기면
gunicorn이 워커를 강제 종료해, 화면은 응답을 못 받고 아무 변화 없이 끝났다.

구조:
  - start(): 상태 파일(data/processed/jm_jobs/<job_id>.json)을 만들고 데몬 스레드에서 검색 실행 → 요청은 즉시 반환.
    스레드는 서버 프로세스(워커)가 살아있는 한 시간 제한 없이 돈다.
  - 진행 상황(단계·완료 인원)과 heartbeat를 상태 파일에 기록. 화면은 dcc.Interval로 get()을 읽는다 —
    gunicorn 워커가 2개라 메모리 대신 파일로 공유.
  - 종료 상태: done(결과 있음/추천 없음 포함) · error(검색 조건·데이터 문제, 결과의 error) · failed(예외) ·
    lost(heartbeat가 STALE_SECONDS 넘게 끊김 = 워커 재시작·메모리 부족 등으로 프로세스가 중단됨).
  - 사용자당 동시에 1건만 실행.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime

from services import data_store

JOBS_DIR = os.path.join(data_store.DATA_DIR, 'jm_jobs')
HEARTBEAT_SECONDS = 10
STALE_SECONDS = 90
KEEP_DAYS = 7
_LOCK = threading.Lock()

STATUS_LABELS = {'running': '실행 중', 'done': '완료', 'error': '종료(결과 없음)', 'failed': '오류로 종료',
                 'lost': '중단됨'}


def _path(job_id: str) -> str:
    return os.path.join(JOBS_DIR, f'{job_id}.json')


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _read(job_id: str) -> dict | None:
    if not job_id or not all(c.isalnum() for c in job_id):
        return None
    try:
        with open(_path(job_id), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(job: dict) -> None:
    os.makedirs(JOBS_DIR, exist_ok=True)
    tmp = _path(job['id']) + f'.{threading.get_ident()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(job, f, ensure_ascii=False)
    os.replace(tmp, _path(job['id']))


def _update(job_id: str, **fields) -> None:
    with _LOCK:
        job = _read(job_id)
        if job is None:
            return
        job.update(fields)
        job['heartbeat'] = time.time()
        _write(job)


def _cleanup() -> None:
    try:
        cutoff = time.time() - KEEP_DAYS * 86400
        for name in os.listdir(JOBS_DIR):
            p = os.path.join(JOBS_DIR, name)
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
    except OSError:
        pass


def running_job(user_id: str) -> dict | None:
    """이 사용자의 실행 중인(끊기지 않은) 작업."""
    try:
        names = os.listdir(JOBS_DIR)
    except OSError:
        return None
    for name in names:
        if name.endswith('.json'):
            job = get(name[:-5])
            if job and job.get('user_id') == user_id and job['status'] == 'running':
                return job
    return None


def start(user_id: str, mode: str, args: dict) -> dict:
    """검색을 백그라운드로 시작. 반환: 작업 상태. 같은 사용자가 이미 실행 중이면 그 작업을 그대로 돌려준다."""
    existing = running_job(user_id)
    if existing:
        return {**existing, 'already_running': True}
    _cleanup()
    job = {'id': uuid.uuid4().hex[:16], 'user_id': user_id, 'mode': mode, 'args': args, 'status': 'running',
           'stage': '시작', 'done': 0, 'total': 0, 'started_at': _now(), 'started_ts': time.time(),
           'finished_at': '', 'heartbeat': time.time(), 'pid': os.getpid(), 'history_file': '', 'message': ''}
    with _LOCK:
        _write(job)
    threading.Thread(target=_run, args=(job['id'], mode, args), daemon=True, name=f'jm-job-{job["id"]}').start()
    return job


def _run(job_id: str, mode: str, args: dict) -> None:
    from services import job_market as jm
    stop = threading.Event()

    def _beat():
        while not stop.wait(HEARTBEAT_SECONDS):
            _update(job_id)
    threading.Thread(target=_beat, daemon=True).start()

    def _progress(stage, done, total):
        _update(job_id, stage=stage, done=done, total=total)

    try:
        if mode == 'individual':
            result = jm.run_individual_search(args.get('researcher_ids') or [], args.get('excluded') or [], _progress)
        else:
            result = jm.run_project_search(args.get('project_names') or [], args.get('excluded') or [], _progress)
        if result.get('error'):
            final = {'status': 'error', 'message': result['error']}
        else:
            results = result.get('results') or {}
            n_rec = sum(1 for r in results.values() if r.get('recommendations'))
            final = {'status': 'done', 'history_file': result.get('history_file', ''),
                     'people': len(results), 'recommended': n_rec}
    except Exception as exc:  # noqa: BLE001 — 어떤 오류든 "종료됐다"는 사실과 원인을 화면에 남긴다
        traceback.print_exc()
        final = {'status': 'failed', 'message': f'{type(exc).__name__}: {exc}'}
    finally:
        stop.set()
    _update(job_id, finished_at=_now(), **final)


def get(job_id: str) -> dict | None:
    """작업 상태. 실행 중인데 heartbeat가 끊겼으면 lost로 확정해 기록한다."""
    job = _read(job_id)
    if job is None:
        return None
    if job['status'] == 'running' and time.time() - float(job.get('heartbeat') or 0) > STALE_SECONDS:
        _update(job_id, status='lost', finished_at=_now(),
                message='서버 프로세스가 중간에 종료되어 검색이 끝나지 못했습니다(서버 재시작·메모리 부족 등). 다시 실행해 주세요.')
        job = _read(job_id)
    return job


def elapsed_text(job: dict) -> str:
    end = time.time()
    if job.get('finished_at'):
        try:
            end = datetime.fromisoformat(job['finished_at']).timestamp()
        except ValueError:
            pass
    sec = max(0, int(end - float(job.get('started_ts') or end)))
    return f'{sec // 60}분 {sec % 60}초' if sec >= 60 else f'{sec}초'
