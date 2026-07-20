"""
사내 LLM API 설정 예시 파일

사용법:
  1. 이 파일을 llm_config.py 로 복사하세요.
     cp pipeline/llm_config.example.py pipeline/llm_config.py

  2. llm_config.py 의 값들을 실제 사내 정보로 채워주세요.

  3. llm_config.py 는 .gitignore 에 등록되어 있으므로
     형상관리(git)에 포함되지 않습니다.
"""

# ── API 기본 정보 ─────────────────────────────────────────────────────────────
LLM_API_URL = 'http://apigw.samsungds.net:8000/gpt-oss/1/chat/completions'
LLM_MODEL   = 'gpt-4o'       # 사내 모델명으로 교체
LLM_TIMEOUT = 300              # 초

# ── 인증 ─────────────────────────────────────────────────────────────────────
LLM_API_KEY = 'credential:TICKET-여기에_실제_티켓_입력'   # x-dep-ticket 값

# ── 고정 헤더 ─────────────────────────────────────────────────────────────────
SEND_SYSTEM_NAME = 'SAIT_People_Summary'
USER_ID          = 'your.user.id'   # 사번 또는 Knox ID
USER_TYPE        = 'your.user.id'   # 보통 USER_ID 와 동일
CONTENT_TYPE     = 'application/json'
ACCEPT           = 'application/json'
# Prompt-Msg-Id / Completion-Msg-Id 는 호출마다 uuid 로 자동 생성됩니다.

# ── 2번째 사내 LLM (비교용, 인증/헤더 불필요) ───────────────────────────────────
# call_llm(..., profile='thinkingcap')으로 호출 시 사용. Content-Type 외 별도
# 인증/헤더가 필요 없는 단순 OpenAI 호환 엔드포인트.
LLM2_API_URL = 'http://75.12.15.121:8000/v1/chat/completions'
LLM2_MODEL   = 'thinkingcap'
LLM2_TIMEOUT = 300              # 초

# thinkingcap처럼 최종 답변 전에 사고 과정(reasoning)에도 토큰을 쓰는 모델은
# max_tokens가 부족하면 사고 과정만 쓰다 끝나 답변(JSON 등)을 못 내는 경우가
# 있다. 호출 시 요청한 max_tokens에 이 배수를 곱해 여유를 준다.
LLM2_MAX_TOKENS_MULTIPLIER = 3

# thinkingcap 호출 간 최소 간격(초). 응답이 느리거나 서버 부하에 민감한 모델을
# 배려해 초당 호출 제한과 별개로 추가 대기 시간을 둔다.
LLM2_CALL_INTERVAL = 1.0

# ReadTimeout/연결 오류 시 자동 재시도 횟수와 백오프 시작 시간(초, 회차마다
# 2배씩 증가). 두 profile 모두 공통 적용.
LLM_MAX_RETRIES   = 2
LLM_RETRY_BACKOFF = 5.0

# ── 사내 Confluence 접속 정보 (개인 액세스 토큰, PAT 방식) ──────────────────────
# base URL은 별도로 설정하지 않고, project_confl_address.csv의 각 행 confl_address
# (컨플루언스 페이지 URL) 에서 그때그때 추출해서 사용합니다.
CONFLUENCE_TOKEN = 'your-confluence-personal-access-token'   # 개인 액세스 토큰(PAT)
