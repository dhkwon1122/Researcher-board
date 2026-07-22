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

사내 LLM은 초당 5회 호출 제한이 있어, call_llm()은 호출 간 최소 간격을
두어 초당 최대 MAX_CALLS_PER_SEC(4)회를 넘지 않도록 자체적으로 조절한다.
profile='default'(=1순위 thinkingcap 물리 엔드포인트)는 응답이 느리거나
서버 부하에 민감할 수 있어 LLM2_CALL_INTERVAL(초, llm_config.py)만큼 추가
간격을 둔다.

ReadTimeout/연결 오류는 일시적인 경우가 많아 LLM_MAX_RETRIES회까지
지수 백오프(LLM_RETRY_BACKOFF초부터 2배씩 증가)로 자동 재시도한다.

두 모델 비교(profile 인자, 값 자체는 하위 호환 유지 / 물리 라우팅은 반전됨):
  call_llm(prompt, system_prompt)                     → 1순위(default) thinkingcap
    (llm_config.py의 LLM2_API_URL/LLM2_MODEL/LLM2_TIMEOUT 사용, 인증/특수
     헤더 없이 Content-Type만으로 호출)
  call_llm(prompt, system_prompt, profile='thinkingcap') → 2순위 기존 gpt-4o
    (llm_config.py의 LLM_API_URL/LLM_MODEL/LLM_TIMEOUT + 인증 헤더 사용)
"""

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


def _throttle(profile: str = 'default'):
    """직전 호출과의 간격이 최소 간격 미만이면 그만큼 대기해 호출 속도를 제한한다.
    profile='default'(1순위 thinkingcap 물리 엔드포인트)는 llm_config.LLM2_CALL_INTERVAL
    (기본 1.0초)만큼 추가 간격을 둔다(응답이 느리거나 서버 부하에 민감한 모델을 배려)."""
    global _last_call_time
    extra_interval = getattr(_cfg, 'LLM2_CALL_INTERVAL', 1.0) if profile == 'default' and _cfg else 0.0
    min_interval = max(_MIN_INTERVAL, extra_interval)
    with _last_call_lock:
        now = time.monotonic()
        wait = min_interval - (now - _last_call_time)
        if wait > 0:
            time.sleep(wait)
        _last_call_time = time.monotonic()


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

    resp = None
    for attempt in range(max_retries + 1):
        try:
            _throttle(profile)
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
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
