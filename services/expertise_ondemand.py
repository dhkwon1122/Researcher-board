"""
'보유 전문성' 화면 하단의 과거 시점 온디맨드 전문성 분석 — 기본은
pipeline/process_researcher_expertise.py의 배치(현재 재직자 전체, 수동 CLI
실행)로 처리하지만, 특정 과거 시점 + 특정 사번들만 필요할 때는 화면에서 바로
요청받아 그 자리에서 LLM을 돌려 분석한다(사용자 확정, 2026-08-29 — "기본은
현재 재직자만 자동 분석하고, 과거 시점 분석은 필요할 때 화면에서 시점+사번을
입력해 요청").

결과는 (researcher_id, valid_date) 키로 영구 캐시한다(data/processed/
expertise_ondemand_cache.json) — 같은 사번+시점을 다시 조회하면 LLM을 또
부르지 않고 캐시된 값을 그대로 보여준다("저장해서 재사용", 사용자 확정).

여러 사번을 한 번에 요청하면 LLM 호출이 순차/병렬로 오래(수십초~수분) 걸릴
수 있어, 관리자 "데이터 업데이트" 탭(services/web_pipeline_runner.py)과
동일한 패턴(threading.Thread(daemon=True) + 파일 기반 락 + dcc.Interval
폴링)으로 백그라운드 실행한다(사용자 확정 "백그라운드 실행 + 진행 상황
폴링") — 이 앱이 gunicorn --workers 2로 뜨기 때문에(Dockerfile) 워커
프로세스 메모리상의 상태로는 두 워커 간에 공유가 안 되어, 락도 파일로
관리한다(web_pipeline_runner.py와 동일한 이유).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import date, datetime

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

from paths import OUT_DIR  # noqa: E402
import process_researcher_expertise as expertise  # noqa: E402

CACHE_PATH = os.path.join(OUT_DIR, 'expertise_ondemand_cache.json')
LOCK_PATH = os.path.join(OUT_DIR, '.expertise_ondemand.lock.json')
_LOCK_STALE_SECONDS = 30 * 60  # 30분 넘게 살아있는 락은 죽은 것으로 간주(web_pipeline_runner.py와 동일 정책)

_local_lock = threading.Lock()


def cache_key(researcher_id: str, valid_date: date) -> str:
    return f'{str(researcher_id).strip().zfill(8)}|{valid_date.isoformat()}'


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_results(researcher_ids: list, valid_date: date) -> list:
    """캐시에 있는 값만 researcher_ids 순서 그대로 반환(없으면 그 자리에
    None — 아직 한 번도 분석 요청을 안 했거나, 계산 중 예기치 못하게
    사라진 경우)."""
    cache = _load_cache()
    return [cache.get(cache_key(rid, valid_date)) for rid in researcher_ids]


# ── 동시 실행 방지 락(파일 기반 — 워커 프로세스 2개 간 공유) ──────────────────

def lock_status() -> dict | None:
    """실행 중이면(그리고 오래되지 않았으면) 락 정보를, 아니면 None."""
    if not os.path.exists(LOCK_PATH):
        return None
    try:
        with open(LOCK_PATH, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - data.get('started_at_ts', 0) > _LOCK_STALE_SECONDS:
        return None  # 죽은 락으로 간주 — 다음 request_analysis()가 새로 잡음
    return data


def _try_acquire_lock(researcher_ids: list, valid_date: date) -> bool:
    with _local_lock:
        if lock_status() is not None:
            return False
        os.makedirs(OUT_DIR, exist_ok=True)
        data = {
            'started_at': datetime.now().strftime('%y-%m-%d %H:%M:%S'),
            'started_at_ts': time.time(),
            'researcher_ids': researcher_ids,
            'valid_date': valid_date.isoformat(),
            'total': len(researcher_ids),
        }
        with open(LOCK_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return True


def _release_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass


def _run_batch(researcher_ids: list, valid_date: date) -> None:
    """백그라운드 스레드 본체 — 캐시에 없는 사번만 실제로 LLM 분석하고,
    끝나면 캐시에 저장 + 락 해제. 예외가 나도(예: LLM 서버 문제) 락이
    영원히 안 풀리는 일이 없도록 반드시 release로 마무리한다."""
    try:
        cache = _load_cache()
        results = expertise.analyze_researchers_as_of(researcher_ids, valid_date)
        for r in results:
            cache[cache_key(r['researcher_id'], valid_date)] = r
        _save_cache(cache)
    except Exception as exc:  # noqa: BLE001 — 실패도 결과로 캐시에 남겨 폴링이 멈추게 함
        cache = _load_cache()
        for rid in researcher_ids:
            key = cache_key(rid, valid_date)
            if key not in cache:
                cache[key] = {'researcher_id': rid, 'as_of': valid_date.isoformat(),
                               'error': f'분석 중 오류: {exc}'}
        _save_cache(cache)
    finally:
        _release_lock()


def request_analysis(researcher_ids: list, valid_date: date) -> str:
    """분석을 요청한다. 반환값:
      'empty'   — 사번이 하나도 없음
      'ready'   — 전부 이미 캐시에 있음(백그라운드 실행 불필요, 바로 get_results()로 표시)
      'started' — 캐시에 없는 사번이 있어 백그라운드 스레드를 새로 시작함
      'busy'    — 다른 분석이 이미 진행 중(락을 못 잡음) — 잠시 후 재시도 안내"""
    researcher_ids = [str(r).strip().zfill(8) for r in researcher_ids if str(r).strip()]
    if not researcher_ids:
        return 'empty'
    cache = _load_cache()
    missing = [rid for rid in researcher_ids if cache_key(rid, valid_date) not in cache]
    if not missing:
        return 'ready'
    if not _try_acquire_lock(researcher_ids, valid_date):
        return 'busy'
    t = threading.Thread(target=_run_batch, args=(missing, valid_date), daemon=True)
    t.start()
    return 'started'
