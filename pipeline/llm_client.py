"""
사내 LLM 호출 공용 유틸리티

pipeline/llm_config.py 설정을 사용해 사내 LLM API를 호출한다.

※ 1순위(default)/2순위 우선순위 변경 안내
  profile 문자열('default'/'thinkingcap') 자체와 각 스크립트의 --profile
  플래그·기본값·결과 파일명 접미사 규칙(rd_specialist_markdown.profile_suffix)은
  하위 호환을 위해 그대로 유지한다. 대신 이 파일 안에서 각 profile 문자열이
  가리키는 실제 물리 엔드포인트/헤더 방식만 서로 바꿔, 아무 옵션 없이 실행하는
  기본 호출(profile='default')이 이제 1순위인 thinkingcap(LLM2_* 설정, 단순
  Content-Type 헤더)을 호출하고, profile='thinkingcap'을 명시했을 때 2순위인
  기존 gpt-4o(LLM_* 설정, 인증 헤더 포함)를 호출하도록 라우팅한다.
  → --profile thinkingcap 이라는 이름과 실제로 호출되는 물리 모델이 서로
    반대라는 점에 주의할 것(이름은 유지, 라우팅만 반전).

profile='thinkingcap'(2순위, 기존 gpt-4o 물리 엔드포인트 — 사내 공용 게이트웨이)은
자체적으로 초당 5회 호출 제한이 있어, call_llm()이 호출 간 최소 간격을 두어
초당 최대 MAX_CALLS_PER_SEC(4)회를 넘지 않도록 자체적으로 조절한다(시간 기반
순차 제한).

profile='default'(1순위 thinkingcap 물리 엔드포인트 — 전용 vLLM 서버)는 위와
반대로 시간 기반 간격 대신 "동시 요청 수 제한(세마포어)"으로 부하를 조절한다.
vLLM은 여러 요청을 continuous batching으로 동시에 처리하도록 설계되어 있어,
요청을 순차로 띄엄띄엄 보내는 것보다 여러 요청을 동시에 보내고 서버가 배치로
처리하게 하는 편이 훨씬 효율적이기 때문이다. 동시 허용 개수는
llm_config.LLM2_MAX_CONCURRENT(기본 8)로 조정한다 — 전용 GPU의 VRAM 여유,
모델 크기/양자화에 맞춰 값을 올리거나 낮출 수 있다. run_concurrent()를 쓰면
호출부가 여러 건을 한꺼번에 스레드풀로 넘기고, 이 세마포어가 실제 동시
요청 수를 안전하게 제한해 준다.

ReadTimeout/연결 오류는 일시적인 경우가 많아 LLM_MAX_RETRIES회까지
지수 백오프(LLM_RETRY_BACKOFF초부터 2배씩 증가)로 자동 재시도한다.

동시 호출 유틸리티:
  run_concurrent(tasks, max_workers=None) — 인자 없는 callable 목록을 스레드풀로
  동시 실행하고, 각각의 (결과, 예외) 튜플을 원래 순서대로 반환한다. 개별 작업이
  예기치 못한 예외를 던져도 잡아서 반환할 뿐 다른 작업이나 배치 전체를 중단시키지
  않는다 — 호출부가 error가 있는 항목만 로그로 남겨 추후 동시성/설정을 조정하는
  데 쓸 수 있다(call_llm() 자체가 이미 처리하는 재시도/HTTP오류/타임아웃과는
  별개로, 그 바깥에서 발생하는 예상 못한 예외에 대한 안전망).
  max_concurrency(profile) — profile에 설정된 동시 호출 허용치를 반환한다.
  호출부가 스레드풀 크기를 이 값에 맞춰 잡을 때 사용한다.

두 모델 비교(profile 인자, 값 자체는 하위 호환 유지 / 물리 라우팅은 반전됨):
  call_llm(prompt, system_prompt)                     → 1순위(default) thinkingcap
    (llm_config.py의 LLM2_API_URL/LLM2_MODEL/LLM2_TIMEOUT 사용, 인증/특수
     헤더 없이 Content-Type만으로 호출)
  call_llm(prompt, system_prompt, profile='thinkingcap') → 2순위 기존 gpt-4o
    (llm_config.py의 LLM_API_URL/LLM_MODEL/LLM_TIMEOUT + 인증 헤더 사용)
"""

import concurrent.futures
import re
import threading
import time
import uuid

try:
    import llm_config as _cfg
except ModuleNotFoundError:
    _cfg = None  # type: ignore

MAX_CALLS_PER_SEC = 4
_MIN_INTERVAL = 1.0 / MAX_CALLS_PER_SEC
_last_call_lock = threading.Lock()
_last_call_time = 0.0

_semaphore_lock = threading.Lock()
_semaphores: dict[str, threading.Semaphore] = {}


def _throttle(profile: str = 'default'):
    """profile='thinkingcap'(2순위, 기존 gpt-4o 물리 엔드포인트 — 사내 공용
    게이트웨이)만 시간 기반으로 제한한다. 게이트웨이 자체의 초당 호출 제한을
    넘지 않도록 직전 호출과의 간격이 MAX_CALLS_PER_SEC 미만이면 대기한다.
    profile='default'(1순위 thinkingcap 물리 엔드포인트, 전용 vLLM 서버)는 이
    함수에서 아무것도 하지 않는다 — 부하 조절은 call_llm() 쪽의 동시 요청 수
    제한(세마포어, _get_semaphore 참고)으로 대신한다."""
    if profile != 'thinkingcap':
        return
    global _last_call_time
    with _last_call_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_call_time)
        if wait > 0:
            time.sleep(wait)
        _last_call_time = time.monotonic()


def max_concurrency(profile: str = 'default') -> int:
    """profile에 대해 설정된 동시 호출 허용치. run_concurrent()로 여러 건을
    한꺼번에 넘길 때 스레드풀 크기를 이 값에 맞추면 된다(세마포어 자체는
    call_llm() 내부에서 이 값과 무관하게 항상 강제 적용됨).
    profile='default'(전용 vLLM 서버)만 동시 처리 대상이며, llm_config.
    LLM2_MAX_CONCURRENT(기본 8)로 조정한다. profile='thinkingcap'(사내 공용
    게이트웨이)은 시간 기반 순차 제한만 적용하므로 1을 반환한다."""
    if profile == 'default':
        return max(1, getattr(_cfg, 'LLM2_MAX_CONCURRENT', 8) if _cfg else 8)
    return 1


def _get_semaphore(profile: str) -> threading.Semaphore:
    with _semaphore_lock:
        sem = _semaphores.get(profile)
        if sem is None:
            sem = threading.Semaphore(max_concurrency(profile))
            _semaphores[profile] = sem
        return sem


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


def _request_config(profile: str):
    """profile에 따른 (url, model, headers, timeout)을 반환. 미지원 profile이면 None.

    ※ profile='default'(1순위)는 LLM2_*(thinkingcap) 물리 엔드포인트를,
      profile='thinkingcap'(2순위)은 LLM_*(기존 gpt-4o) 물리 엔드포인트를
      가리키도록 라우팅이 반전되어 있다(문자열 자체의 하위 호환 유지 목적)."""
    if profile == 'default':
        if not hasattr(_cfg, 'LLM2_API_URL'):
            return None
        headers = {'Content-Type': 'application/json'}
        timeout = getattr(_cfg, 'LLM2_TIMEOUT', 300)
        return _cfg.LLM2_API_URL, _cfg.LLM2_MODEL, headers, timeout
    if profile == 'thinkingcap':
        headers = {
            'Content-Type':      _cfg.CONTENT_TYPE,
            'Accept':            _cfg.ACCEPT,
            'x-dep-ticket':      _cfg.LLM_API_KEY,
            'Send-System-Name':  _cfg.SEND_SYSTEM_NAME,
            'User-Id':           _cfg.USER_ID,
            'User-Type':         _cfg.USER_TYPE,
            'Prompt-Msg-Id':     str(uuid.uuid4()),
            'Completion-Msg-Id': str(uuid.uuid4()),
        }
        return _cfg.LLM_API_URL, _cfg.LLM_MODEL, headers, _cfg.LLM_TIMEOUT
    return None


def call_llm(prompt: str, system_prompt: str, *, temperature: float = 0.2, max_tokens: int = 1500,
             profile: str = 'default') -> str:
    """사내 LLM API 호출 → 응답 텍스트 반환. 미설정/실패 시 빈 문자열.
    profile='default'(1순위, thinkingcap 물리 엔드포인트) 또는
    'thinkingcap'(2순위, 기존 gpt-4o 물리 엔드포인트, 비교용)."""
    if _cfg is None:
        print('  [LLM 오류] llm_config.py 가 없어 API 호출을 건너뜁니다.')
        return ''

    import requests

    cfg = _request_config(profile)
    if cfg is None:
        print(f'  [LLM 오류] 알 수 없거나 설정되지 않은 profile: {profile}')
        return ''
    url, model, headers, timeout = cfg

    if profile == 'default':
        # 1순위(thinkingcap)는 추론형 모델로 최종 답변 전에 사고 과정에도 토큰을
        # 쓰므로 요청 시 max_tokens를 배수 적용해 여유를 준다(기본 3배,
        # LLM2_MAX_TOKENS_MULTIPLIER로 조정 가능).
        max_tokens = max_tokens * getattr(_cfg, 'LLM2_MAX_TOKENS_MULTIPLIER', 3)

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'temperature': temperature,
        'max_tokens':  max_tokens,
    }

    max_retries = getattr(_cfg, 'LLM_MAX_RETRIES', 5)
    retry_backoff = getattr(_cfg, 'LLM_RETRY_BACKOFF', 5.0)
    semaphore = _get_semaphore(profile) if profile == 'default' else None

    resp = None
    for attempt in range(max_retries + 1):
        try:
            _throttle(profile)
            if semaphore is not None:
                semaphore.acquire()
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
                resp.raise_for_status()
            finally:
                if semaphore is not None:
                    semaphore.release()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt < max_retries:
                wait = retry_backoff * (2 ** attempt)
                print(f'  [LLM 재시도] {type(exc).__name__} — {wait:.0f}초 후 재시도 '
                      f'({attempt + 1}/{max_retries}, profile={profile})')
                time.sleep(wait)
                continue
            print(f'  [LLM 오류] {max_retries}회 재시도 후에도 실패 (profile={profile}): '
                  f'{type(exc).__name__}: {exc}')
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
        if reasoning:
            print(f'  [LLM 경고] content가 비어 있어 reasoning_content로 대체 사용 '
                  f'(profile={profile}, finish_reason={finish_reason})')
            return reasoning.strip()
        print(f'  [LLM 경고] 응답 content가 비어 있음 (profile={profile}, finish_reason={finish_reason}, '
              f'max_tokens={max_tokens}) — 추론형 모델은 사고 과정에 토큰을 많이 쓰므로 '
              f'max_tokens를 늘려야 할 수 있습니다.')
        return ''
    except Exception as exc:
        print(f'  [LLM 오류] {type(exc).__name__}: {exc}')
        return ''
