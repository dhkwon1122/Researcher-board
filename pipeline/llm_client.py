"""
사내 LLM 호출 공용 유틸리티

프로젝트 루트의 .env(또는 환경변수)에 있는 LLM2_* 설정(thinkingcap 물리
엔드포인트 — 전용 vLLM 서버)을 사용해 사내 LLM API를 호출한다. 예전에는
이 설정이 pipeline/llm_config.py라는 별도 파일(.env와 따로 관리)에 있었지만,
비밀값을 관리하는 파일이 두 개로 나뉠 이유가 없어 .env 하나로 합쳤다
(services.db.load_env_file() 재사용 — DATABASE_URL을 읽던 것과 동일한 로더).

vLLM은 여러 요청을 continuous batching으로 동시에 처리하도록 설계되어 있어,
요청을 순차로 띄엄띄엄 보내는 것보다 여러 요청을 동시에 보내고 서버가 배치로
처리하게 하는 편이 훨씬 효율적이다. call_llm()은 "동시 요청 수 제한(세마포어)"
으로 부하를 조절한다. 동시 허용 개수는 환경변수 LLM2_MAX_CONCURRENT(기본 8)
로 조정한다 — 전용 GPU의 VRAM 여유, 모델 크기/양자화에 맞춰 값을 올리거나
낮출 수 있다. run_concurrent()를 쓰면 호출부가 여러 건을 한꺼번에 스레드풀로
넘기고, 이 세마포어가 실제 동시 요청 수를 안전하게 제한해 준다.

ReadTimeout/연결 오류는 일시적인 경우가 많아 LLM_MAX_RETRIES회까지
지수 백오프(LLM_RETRY_BACKOFF초부터 2배씩 증가)로 자동 재시도한다.

동시 호출 유틸리티:
  run_concurrent(tasks, max_workers=None) — 인자 없는 callable 목록을 스레드풀로
  동시 실행하고, 각각의 (결과, 예외) 튜플을 원래 순서대로 반환한다. 개별 작업이
  예기치 못한 예외를 던져도 잡아서 반환할 뿐 다른 작업이나 배치 전체를 중단시키지
  않는다 — 호출부가 error가 있는 항목만 로그로 남겨 추후 동시성/설정을 조정하는
  데 쓸 수 있다(call_llm() 자체가 이미 처리하는 재시도/HTTP오류/타임아웃과는
  별개로, 그 바깥에서 발생하는 예상 못한 예외에 대한 안전망).
  max_concurrency() — 설정된 동시 호출 허용치를 반환한다. 호출부가 스레드풀
  크기를 이 값에 맞춰 잡을 때 사용한다.
  query_max_wait() — 화면에서 실시간으로 응답을 기다리는 호출부(services/
  nl_query.py, services/open_data_query.py)가 공유하는 LLM2_QUERY_MAX_WAIT_SECONDS
  기본값(15초) 조회 헬퍼 — 세 곳에서 각자 os.environ을 읽던 것을 여기 하나로 모음.
"""

import concurrent.futures
import os
import re
import sys
import threading
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from services.db import load_env_file  # noqa: E402

load_env_file()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

_semaphore_lock = threading.Lock()
_semaphore: threading.Semaphore | None = None

_stats_lock = threading.Lock()
_truncation_count = 0  # content가 비어 finish_reason=length로 대체/실패 처리된 누적 횟수


def get_truncation_count() -> int:
    """이번 프로세스에서 (마지막 reset_truncation_count() 이후) content가 비어
    reasoning_content로 대체하거나 그마저 없어 빈 문자열을 반환한 횟수 — 대부분
    finish_reason=length(사고 과정이 max_tokens 예산을 다 쓴 경우)다. 배치
    스크립트가 실행 끝에 "이 경고가 몇 번 발생했는지"를 요약해 보여줄 때 쓴다."""
    return _truncation_count


def reset_truncation_count():
    """배치 실행 시작 시 호출해 이번 실행분만 집계되게 한다(여러 프로세스가
    이 모듈을 계속 import해서 쓰는 장기 실행 환경이 아니라, 스크립트 1회
    실행이 곧 1번의 집계 단위이므로 process() 시작 시 리셋하는 것으로 충분)."""
    global _truncation_count
    with _stats_lock:
        _truncation_count = 0


def _record_truncation():
    global _truncation_count
    with _stats_lock:
        _truncation_count += 1


def max_concurrency() -> int:
    """설정된 동시 호출 허용치. run_concurrent()로 여러 건을 한꺼번에 넘길 때
    스레드풀 크기를 이 값에 맞추면 된다(세마포어 자체는 call_llm() 내부에서
    이 값과 무관하게 항상 강제 적용됨). 환경변수 LLM2_MAX_CONCURRENT(기본 8)
    로 조정한다."""
    return max(1, _int_env('LLM2_MAX_CONCURRENT', 8))


def query_max_wait() -> float:
    """화면에서 실시간으로 응답을 기다리는 호출부가 공유하는 기본 대기 한도(초).
    배치 파이프라인이 동시 호출 슬롯을 다 쓰고 있어도 화면이 무한정 멈추지
    않도록, 이 시간 안에 슬롯을 못 얻으면 call_llm(..., max_wait=이 값)이
    빈 문자열로 빠르게 실패 처리한다. 환경변수 LLM2_QUERY_MAX_WAIT_SECONDS로
    조정한다(기본 15초)."""
    return _float_env('LLM2_QUERY_MAX_WAIT_SECONDS', 15)


def _get_semaphore() -> threading.Semaphore:
    global _semaphore
    with _semaphore_lock:
        if _semaphore is None:
            _semaphore = threading.Semaphore(max_concurrency())
        return _semaphore


def run_concurrent(tasks: list, max_workers: int | None = None, on_complete=None) -> list:
    """인자 없는 callable 목록(tasks)을 스레드풀로 동시 실행한다.
    각 작업의 결과를 (결과, 예외) 튜플로 tasks와 같은 순서로 반환한다 — 개별
    작업이 예기치 못한 예외를 던져도 잡아서 반환할 뿐, 다른 작업이나 배치
    전체를 중단시키지 않는다. call_llm() 자체가 이미 처리하는 재시도/HTTP
    오류/타임아웃(실패 시 빈 문자열 반환, 예외를 던지지 않음)과는 별개로,
    그 바깥(예: 응답 파싱 로직의 버그 등)에서 발생하는 예상 못한 예외에 대한
    안전망이다. 호출부는 error가 있는 항목만 로그로 남겨 추후 원인을 파악하고
    동시성 설정을 조정하는 데 활용할 수 있다.

    on_complete(index, result, error): 지정하면 각 작업이 끝나는 즉시(제출
    순서가 아니라 실제 완료되는 순서대로) 호출된다. run_concurrent() 자체는
    ThreadPoolExecutor가 제출된 작업을 전부 마칠 때까지 반환하지 않으므로,
    실행 도중 진행 상황(완료 건수 등)을 실시간으로 보여주고 싶은 호출부는
    반드시 이 콜백을 써야 한다 — 반환값을 받은 뒤 순회하며 출력하면 배치가
    다 끝난 뒤에야 로그가 한꺼번에 찍힌다. 이 콜백은 run_concurrent를 호출한
    스레드에서 순차적으로 실행되므로(as_completed 루프 자체가 그 스레드에서
    돎) 별도 락 없이 카운터를 증가시켜도 안전하다."""
    if not tasks:
        return []
    results: list = [None] * len(tasks)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(task): i for i, task in enumerate(tasks)}
        for future in concurrent.futures.as_completed(future_to_idx):
            i = future_to_idx[future]
            try:
                result, error = future.result(), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            results[i] = (result, error)
            if on_complete is not None:
                on_complete(i, result, error)
    return results


def extract_json(text: str) -> str:
    """응답 텍스트에서 첫 번째 JSON 객체 블록만 추출."""
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    m = re.search(r'\{[\s\S]*\}', text)
    return m.group(0) if m else text


def call_llm(prompt: str, system_prompt: str, *, temperature: float = 0.2, max_tokens: int = 1500,
             max_wait: float | None = None) -> str:
    """사내 LLM API 호출 → 응답 텍스트 반환. 미설정/실패 시 빈 문자열.

    max_wait: 세마포어(동시 호출 허용치) 슬롯이 비기를 기다릴 최대 시간(초).
    None(기본)이면 배치 스크립트들처럼 슬롯이 빌 때까지 무한정 기다린다.
    대시보드 등 사용자가 응답을 실시간으로 기다리는 호출부는 값을 지정해,
    배치 작업이 슬롯을 다 쓰고 있을 때 무한정 멈춰 있지 않고 빈 문자열로
    빠르게 실패해 "지금은 바쁘다"는 안내를 보여줄 수 있게 한다."""
    url = os.environ.get('LLM2_API_URL', '').strip()
    if not url:
        print('  [LLM 오류] LLM2_API_URL이 설정되지 않아 API 호출을 건너뜁니다 '
              '(.env 확인 — .env.example 참고).')
        return ''

    import requests

    model = os.environ.get('LLM2_MODEL', '')
    headers = {'Content-Type': 'application/json'}
    timeout = _float_env('LLM2_TIMEOUT', 300)

    # 추론형 모델은 최종 답변 전에 사고 과정에도 토큰을 쓰므로 요청 시
    # max_tokens를 배수 적용해 여유를 준다(기본 3배, LLM2_MAX_TOKENS_MULTIPLIER로 조정 가능).
    max_tokens = max_tokens * _int_env('LLM2_MAX_TOKENS_MULTIPLIER', 3)

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'temperature': temperature,
        'max_tokens':  max_tokens,
    }

    max_retries = _int_env('LLM_MAX_RETRIES', 5)
    retry_backoff = _float_env('LLM_RETRY_BACKOFF', 5.0)
    semaphore = _get_semaphore()

    resp = None
    for attempt in range(max_retries + 1):
        try:
            if max_wait is not None:
                if not semaphore.acquire(timeout=max_wait):
                    print(f'  [LLM 대기 초과] {max_wait:.0f}초 안에 동시 호출 슬롯을 얻지 못했습니다 '
                          f'(다른 작업이 사용 중).')
                    return ''
            else:
                semaphore.acquire()
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
                resp.raise_for_status()
            finally:
                semaphore.release()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt < max_retries:
                wait = retry_backoff * (2 ** attempt)
                print(f'  [LLM 재시도] {type(exc).__name__} — {wait:.0f}초 후 재시도 '
                      f'({attempt + 1}/{max_retries})')
                time.sleep(wait)
                continue
            print(f'  [LLM 오류] {max_retries}회 재시도 후에도 실패: {type(exc).__name__}: {exc}')
            return ''
        except requests.HTTPError as exc:
            status = exc.response.status_code
            body   = exc.response.text[:300]
            print(f'  [LLM HTTP 오류] {status} — {body}')
            return ''
        except Exception as exc:
            print(f'  [LLM 오류] {type(exc).__name__}: {exc}')
            return ''

    try:
        choice = resp.json()['choices'][0]
        message = choice.get('message', {})
        content = message.get('content')
        if content:
            return content.strip()

        # 일부 추론형(reasoning) 모델은 사고 과정을 reasoning_content 등 별도
        # 필드에 담고 content는 비워 두거나(특히 max_tokens가 작아 사고 과정만으로
        # 토큰 예산을 다 쓴 경우) null로 반환한다. 크래시 대신 대체 필드를
        # 시도하고, 그래도 없으면 원인을 알 수 있도록 로그를 남긴다.
        reasoning = message.get('reasoning_content') or message.get('reasoning')
        finish_reason = choice.get('finish_reason')
        _record_truncation()
        if reasoning:
            print(f'  [LLM 경고] content가 비어 있어 reasoning_content로 대체 사용 '
                  f'(finish_reason={finish_reason})')
            return reasoning.strip()
        print(f'  [LLM 경고] 응답 content가 비어 있음 (finish_reason={finish_reason}, '
              f'max_tokens={max_tokens}) — 추론형 모델은 사고 과정에 토큰을 많이 쓰므로 '
              f'max_tokens를 늘려야 할 수 있습니다.')
        return ''
    except Exception as exc:
        print(f'  [LLM 오류] {type(exc).__name__}: {exc}')
        return ''
