"""
로컬 LLM/임베딩 클라이언트.

chat(): ollama, vllm 모두 OpenAI 호환 /v1/chat/completions API 를 제공하므로
        base URL 만 바꾸면 그대로 동작한다.
  - ollama:  http://localhost:11434/v1   (docker: http://ollama:11434/v1)
  - vllm:    http://localhost:8000/v1

embed(): 사내망 제한으로 ollama에 BGE-M3를 설치할 수 없어, 별도의 로컬 BGE-M3
         python 서버를 사용한다. 엔드포인트 경로는 /api/embed 이지만 응답
         본문은 OpenAI 호환 형식(`{"data": [{"index":.., "embedding":[..]}]}`)
         이다. chat()과는 다른 서버/포트이므로 EMBED_BASE_URL 로 독립 설정한다.

환경변수:
  LLM_BASE_URL    기본 http://localhost:11434/v1 (chat 전용)
  LLM_MODEL       기본 qwen3.5:4b (CPU 가능한 소형; GPU 시 큰 코더 모델 권장)
  LLM_API_KEY     기본 'ollama' (로컬은 대개 불필요, 더미 값)
  LLM_TIMEOUT     기본 60 (초, chat/embed 공용)
  EMBED_BASE_URL  기본 http://localhost:7138 (BGE-M3 python 서버, embed 전용)
  EMBED_MODEL     기본 bge-m3
  EMBED_API_KEY   기본 '' (내부 서버라 대개 인증 불필요)
"""

import os


class LLMError(RuntimeError):
    """LLM 호출 실패(미기동/타임아웃/응답오류)를 UI 안내로 바꾸기 위한 예외."""


def _cfg():
    base = os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1').rstrip('/')
    model = os.environ.get('LLM_MODEL', 'qwen3.5:4b')
    api_key = os.environ.get('LLM_API_KEY', 'ollama')
    try:
        timeout = float(os.environ.get('LLM_TIMEOUT', '60'))
    except ValueError:
        timeout = 60.0
    return base, model, api_key, timeout


def _embed_cfg():
    base = os.environ.get('EMBED_BASE_URL', 'http://localhost:7138').rstrip('/')
    model = os.environ.get('EMBED_MODEL', 'bge-m3')
    api_key = os.environ.get('EMBED_API_KEY', '')
    try:
        timeout = float(os.environ.get('LLM_TIMEOUT', '60'))
    except ValueError:
        timeout = 60.0
    return base, model, api_key, timeout


def chat(messages, temperature: float = 0.0, max_tokens: int = 512) -> str:
    """
    messages: [{'role': 'system'|'user'|'assistant', 'content': str}, ...]
    반환: assistant 응답 텍스트. 실패 시 LLMError.
    """
    try:
        import requests
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise LLMError('requests 패키지가 없습니다. requirements.txt 를 설치하세요.') from exc

    base, model, api_key, timeout = _cfg()
    url = f'{base}/chat/completions'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    payload = {
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
        'stream': False,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        raise LLMError(
            f'로컬 LLM 서버에 연결할 수 없습니다 ({base}). '
            f'ollama/vllm 가 기동 중인지 확인하세요.'
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise LLMError(f'LLM 응답 시간 초과({timeout:.0f}s). 모델이 크거나 CPU 추론이 느릴 수 있습니다.') from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f'LLM 호출 오류: {type(exc).__name__}: {exc}') from exc

    if resp.status_code != 200:
        raise LLMError(f'LLM HTTP {resp.status_code}: {resp.text[:300]}')

    try:
        data = resp.json()
        return data['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f'LLM 응답 파싱 실패: {resp.text[:300]}') from exc


def embed(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """
    texts: 임베딩할 문자열 리스트
    반환: texts와 같은 순서의 임베딩 벡터(list[float]) 리스트. 실패 시 LLMError.
    많은 개수를 한 번에 넘겨도 내부적으로 batch_size 단위로 나눠 호출한다.
    """
    try:
        import requests
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise LLMError('requests 패키지가 없습니다. requirements.txt 를 설치하세요.') from exc

    base, model, api_key, timeout = _embed_cfg()
    url = f'{base}/api/embed'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        payload = {'model': model, 'input': chunk}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.ConnectionError as exc:
            raise LLMError(
                f'로컬 임베딩 서버에 연결할 수 없습니다 ({base}). BGE-M3 서버가 기동 중인지 확인하세요.'
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise LLMError(f'임베딩 응답 시간 초과({timeout:.0f}s).') from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f'임베딩 호출 오류: {type(exc).__name__}: {exc}') from exc

        if resp.status_code != 200:
            raise LLMError(f'임베딩 HTTP {resp.status_code}: {resp.text[:300]}')

        try:
            data = resp.json()['data']
            data.sort(key=lambda d: d.get('index', 0))
            vectors.extend(d['embedding'] for d in data)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise LLMError(f'임베딩 응답 파싱 실패: {resp.text[:300]}') from exc

    return vectors


def is_configured() -> bool:
    """LLM_BASE_URL 이 설정돼 있는지(항상 기본값 존재하므로 True). 확장 여지용."""
    return bool(os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1'))
