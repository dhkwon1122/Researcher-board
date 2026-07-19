"""
사내 LLM 호출 공용 유틸리티

pipeline/llm_config.py 설정을 사용해 사내 LLM API를 호출한다.
process_comments.py의 호출 방식과 동일한 헤더/인증 규약을 따른다.

사내 LLM은 초당 5회 호출 제한이 있어, call_llm()은 호출 간 최소 간격을
두어 초당 최대 MAX_CALLS_PER_SEC(4)회를 넘지 않도록 자체적으로 조절한다.

두 모델 비교(profile 인자):
  call_llm(prompt, system_prompt)                     → 기존 사내 LLM(profile='default')
  call_llm(prompt, system_prompt, profile='thinkingcap') → 2번째 사내 LLM
    (llm_config.py의 LLM2_API_URL/LLM2_MODEL/LLM2_TIMEOUT 사용, 인증/특수
     헤더 없이 Content-Type만으로 호출)
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


def _throttle():
    """직전 호출과의 간격이 _MIN_INTERVAL 미만이면 그만큼 대기해 호출 속도를 제한한다."""
    global _last_call_time
    with _last_call_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_call_time)
        if wait > 0:
            time.sleep(wait)
        _last_call_time = time.monotonic()


def extract_json(text: str) -> str:
    """응답 텍스트에서 첫 번째 JSON 객체 블록만 추출."""
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    m = re.search(r'\{[\s\S]*\}', text)
    return m.group(0) if m else text


def _request_config(profile: str):
    """profile에 따른 (url, model, headers, timeout)을 반환. 미지원 profile이면 None."""
    if profile == 'default':
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
    if profile == 'thinkingcap':
        if not hasattr(_cfg, 'LLM2_API_URL'):
            return None
        headers = {'Content-Type': 'application/json'}
        timeout = getattr(_cfg, 'LLM2_TIMEOUT', 300)
        return _cfg.LLM2_API_URL, _cfg.LLM2_MODEL, headers, timeout
    return None


def call_llm(prompt: str, system_prompt: str, *, temperature: float = 0.2, max_tokens: int = 1500,
             profile: str = 'default') -> str:
    """사내 LLM API 호출 → 응답 텍스트 반환. 미설정/실패 시 빈 문자열.
    profile='default'(기존 사내 LLM) 또는 'thinkingcap'(2번째 사내 LLM, 비교용)."""
    if _cfg is None:
        print('  [LLM 오류] llm_config.py 가 없어 API 호출을 건너뜁니다.')
        return ''

    import requests

    cfg = _request_config(profile)
    if cfg is None:
        print(f'  [LLM 오류] 알 수 없거나 설정되지 않은 profile: {profile}')
        return ''
    url, model, headers, timeout = cfg

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'temperature': temperature,
        'max_tokens':  max_tokens,
    }
    try:
        _throttle()
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
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
    except requests.HTTPError as exc:
        status = exc.response.status_code
        body   = exc.response.text[:300]
        print(f'  [LLM HTTP 오류] {status} — {body}')
        return ''
    except Exception as exc:
        print(f'  [LLM 오류] {type(exc).__name__}: {exc}')
        return ''
