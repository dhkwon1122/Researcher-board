"""
사내 LLM API 설정 예시 파일

사용법:
  1. 이 파일을 llm_config.py 로 복사하세요.
     cp pipeline/llm_config.example.py pipeline/llm_config.py

  2. llm_config.py 의 값들을 실제 사내 정보로 채워주세요.

  3. llm_config.py 는 .gitignore 에 등록되어 있으므로
     형상관리(git)에 포함되지 않습니다.

아무 옵션 없이 call_llm(prompt, system_prompt)만 호출해도 아래 LLM2_* 설정
(thinkingcap, 전용 vLLM 서버)이 사용된다.
"""

# ── LLM: thinkingcap (인증/헤더 불필요) ───────────────────────────────────────
# Content-Type 외 별도 인증/헤더가 필요 없는 단순 OpenAI 호환 엔드포인트.
LLM2_API_URL = 'http://75.12.15.121:8000/v1/chat/completions'
LLM2_MODEL   = 'thinkingcap'
LLM2_TIMEOUT = 300              # 초

# thinkingcap처럼 최종 답변 전에 사고 과정(reasoning)에도 토큰을 쓰는 모델은
# max_tokens가 부족하면 사고 과정만 쓰다 끝나 답변(JSON 등)을 못 내는 경우가
# 있다. 호출 시 요청한 max_tokens에 이 배수를 곱해 여유를 준다.
LLM2_MAX_TOKENS_MULTIPLIER = 3

# thinkingcap은 전용 vLLM 서버(예: RTX PRO 6000 Blackwell 96GB 1장)에서 서빙되는
# 것을 전제로, 시간 기반 간격 대신 "동시 호출 허용 개수"로 부하를 조절한다.
# vLLM은 continuous batching으로 여러 요청을 한꺼번에 배치 처리하므로, 순차
# 호출보다 동시에 여러 건을 보내는 편이 훨씬 효율적이다.
#   예) Qwen3.6-27B-NVFP4 같은 4bit 양자화 모델은 가중치가 약 13~14GB로 작아
#       96GB 카드에서 KV 캐시 여유가 크다 — 8~16 정도로 시작해 서버 로그(큐
#       대기·타임아웃 증가 여부)를 보며 올리거나 낮추면 된다.
#   실제 안전한 값은 모델 크기/양자화, 프롬프트 길이, vLLM 자체 설정
#   (--max-num-seqs 등)에 따라 달라지므로 반드시 실측으로 조정할 것.
LLM2_MAX_CONCURRENT = 8

# "보유 전문성" 탭의 자연어 질문 기능처럼 사용자가 화면에서 실시간으로 응답을
# 기다리는 호출은, 배치 파이프라인이 LLM2_MAX_CONCURRENT 슬롯을 모두 쓰고 있을
# 때 무한정 대기하면 화면이 멈춘 것처럼 보인다. call_llm(..., max_wait=이 값)
# 으로 호출하면 이 시간(초) 안에 슬롯을 못 얻을 경우 즉시 실패로 처리해
# "지금은 바쁘다"는 안내를 보여줄 수 있다(배치 스크립트는 기존처럼 무한 대기).
LLM2_QUERY_MAX_WAIT_SECONDS = 15

# ReadTimeout/연결 오류 시 자동 재시도 횟수와 백오프 시작 시간(초, 회차마다
# 2배씩 증가). 사내 LLM API 호출이 불안정할 때 값을 더 늘려도 된다.
LLM_MAX_RETRIES   = 5
LLM_RETRY_BACKOFF = 5.0

# ── 사내 Confluence 접속 정보 (개인 액세스 토큰, PAT 방식) ──────────────────────
# base URL은 별도로 설정하지 않고, project_confl_address.csv의 각 행 confl_address
# (컨플루언스 페이지 URL) 에서 그때그때 추출해서 사용합니다.
CONFLUENCE_TOKEN = 'your-confluence-personal-access-token'   # 개인 액세스 토큰(PAT)
