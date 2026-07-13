"""
사내 LLM 호출 공용 유틸리티

pipeline/llm_config.py 설정을 사용해 사내 LLM API를 호출한다.
process_comments.py의 호출 방식과 동일한 헤더/인증 규약을 따른다.

사내 LLM은 초당 5회 호출 제한이 있어, call_llm()은 호출 간 최소 간격을
두어 초당 최대 MAX_CALLS_PER_SEC(4)회를 넘지 않도록 자체적으로 조절한다.
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


def call_llm(prompt: str, system_prompt: str, *, temperature: float = 0.2, max_tokens: int = 1500) -> str:
    """사내 LLM API 호출 → 응답 텍스트 반환. 미설정/실패 시 빈 문자열."""
    if _cfg is None:
        print('  [LLM 오류] llm_config.py 가 없어 API 호출을 건너뜁니다.')
        return ''

    import requests

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
    payload = {
        'model': _cfg.LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'temperature': temperature,
        'max_tokens':  max_tokens,
    }
    try:
        _throttle()
        resp = requests.post(_cfg.LLM_API_URL, json=payload, headers=headers, timeout=_cfg.LLM_TIMEOUT)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content'].strip()
    except requests.HTTPError as exc:
        status = exc.response.status_code
        body   = exc.response.text[:300]
        print(f'  [LLM HTTP 오류] {status} — {body}')
        return ''
    except Exception as exc:
        print(f'  [LLM 오류] {type(exc).__name__}: {exc}')
        return ''
