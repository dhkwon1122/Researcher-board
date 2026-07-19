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

# ── 사내 Confluence 접속 정보 (개인 액세스 토큰, PAT 방식) ──────────────────────
# base URL은 별도로 설정하지 않고, project_confl_address.csv의 각 행 confl_address
# (컨플루언스 페이지 URL) 에서 그때그때 추출해서 사용합니다.
CONFLUENCE_TOKEN = 'your-confluence-personal-access-token'   # 개인 액세스 토큰(PAT)
