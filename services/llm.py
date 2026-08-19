"""
로컬 BGE-M3 임베딩 클라이언트.

사내망 제한으로 ollama에 BGE-M3를 설치할 수 없어, 별도의 로컬 BGE-M3 python
서버(services/bge_server.py, pipeline/embed_server.py)를 사용한다. 엔드포인트
경로는 /api/embed 이지만 응답 본문은 OpenAI 호환 형식
(`{"data": [{"index":.., "embedding":[..]}]}`)이다.

채팅형 LLM 호출(사내 "LLM2", thinkingcap)은 이 모듈이 아니라
pipeline/llm_client.py의 call_llm()이 맡는다 — 예전에는 이 모듈에 별도
chat()/LLM_BASE_URL 설정이 있었지만, 결국 같은 사내 LLM 서버를 가리키면서
동시 호출 제한(세마포어)·재시도 같은 보호 장치는 없는 중복 경로였다. 유일한
호출부였던 pipeline/process_comments.py --llm도 llm_client.call_llm()을
쓰도록 옮겨, 이제 이 모듈은 임베딩 전용이다.

환경변수:
  EMBED_BASE_URL  기본 http://localhost:7138 (BGE-M3 python 서버)
  EMBED_MODEL     기본 bge-m3
  EMBED_API_KEY   기본 '' (내부 서버라 대개 인증 불필요)
  EMBED_TIMEOUT   기본 300 (초 — CPU 추론 시 배치당 오래 걸릴 수 있어 넉넉하게)
"""

import os


class LLMError(RuntimeError):
    """LLM 호출 실패(미기동/타임아웃/응답오류)를 UI 안내로 바꾸기 위한 예외."""


def _embed_cfg():
    base = os.environ.get('EMBED_BASE_URL', 'http://localhost:7138').rstrip('/')
    model = os.environ.get('EMBED_MODEL', 'bge-m3')
    api_key = os.environ.get('EMBED_API_KEY', '')
    try:
        timeout = float(os.environ.get('EMBED_TIMEOUT', '300'))
    except ValueError:
        timeout = 300.0
    return base, model, api_key, timeout


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
