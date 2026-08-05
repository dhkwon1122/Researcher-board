"""
BGE-M3 로컬 임베딩 서버.

services/llm.py의 embed()가 기대하는 계약을 그대로 구현한다:
  POST {EMBED_BASE_URL}/api/embed
  요청: {"model": "<모델명>", "input": ["텍스트1", "텍스트2", ...]}
  응답: {"data": [{"index": 0, "embedding": [...]}, ...]}

pipeline/embed_server.py의 ensure_embed_server()가 run_expertise.py 실행 시
이 스크립트를 백그라운드 프로세스로 자동 기동한다(이미 응답 중이면
재기동하지 않음). 수동으로 직접 띄우려면:
  python services/bge_server.py

필요 패키지(requirements-embed.txt, 무거운 ML 의존성이라 별도 분리):
  pip install -r requirements-embed.txt

환경변수(services/llm.py의 embed() 클라이언트 설정과 반드시 일치해야 함):
  EMBED_BASE_URL  기본 http://localhost:7138 (호스트/포트를 여기서 파싱해 바인딩)
  EMBED_MODEL     기본 bge-m3 → HuggingFace 'BAAI/bge-m3'로 로드

모델 로딩(수십 초~수 분)을 서버 리스닝 시작 전에 동기적으로 끝내 두어, 포트가
열린 시점 = 첫 요청을 바로 처리할 수 있는 시점이 되도록 한다(헬스체크가 곧
준비 상태를 의미하게 하기 위함 — 별도 '로딩 중' 상태를 두지 않는다).
"""

import os
import sys
from urllib.parse import urlparse

_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    try:
        from FlagEmbedding import BGEM3FlagModel
    except ModuleNotFoundError:
        print('[bge_server] FlagEmbedding 패키지가 없습니다. 다음으로 설치하세요:\n'
              '  pip install -r requirements-embed.txt')
        sys.exit(1)

    model_name = os.environ.get('EMBED_MODEL', 'bge-m3')
    hf_name = model_name if '/' in model_name else 'BAAI/bge-m3'
    print(f'[bge_server] 모델 로딩 중: {hf_name} (수십 초~수 분 소요될 수 있음)...')
    _model = BGEM3FlagModel(hf_name, use_fp16=True)
    print('[bge_server] 모델 로딩 완료')
    return _model


def create_app():
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI()

    class EmbedRequest(BaseModel):
        model: str = 'bge-m3'
        input: list[str]

    @app.post('/api/embed')
    def embed_endpoint(req: EmbedRequest):
        model = _load_model()
        vecs = model.encode(req.input)['dense_vecs']
        return {'data': [{'index': i, 'embedding': v.tolist()} for i, v in enumerate(vecs)]}

    return app


if __name__ == '__main__':
    try:
        import uvicorn
    except ModuleNotFoundError:
        print('[bge_server] fastapi/uvicorn 패키지가 없습니다. 다음으로 설치하세요:\n'
              '  pip install -r requirements-embed.txt')
        sys.exit(1)

    base = os.environ.get('EMBED_BASE_URL', 'http://localhost:7138')
    parsed = urlparse(base)
    host = parsed.hostname or '0.0.0.0'
    port = parsed.port or 7138

    _load_model()
    uvicorn.run(create_app(), host=host, port=port)
