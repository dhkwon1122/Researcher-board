# AI 검색 (Text2SQL)

연구원 목록 페이지 상단의 **AI 검색**에 자연어로 질문하면, 로컬 LLM 이
PostgreSQL `SELECT` 쿼리를 생성하고 안전 검증을 거쳐 실행한 뒤 결과를 표로 보여준다.

예) "AI 부서에서 논문이 가장 많은 연구원 5명", "특허 등록이 3건 이상인 연구원",
"부서별 평균 논문 수"

## 구성
```
자연어 질문
  → services/text2sql.py: 스키마(information_schema) + 질문을 LLM 에 전달
  → 로컬 LLM(ollama/vllm)이 SELECT 생성
  → sanitize_sql(): 안전 검증
  → read-only 트랜잭션 + statement_timeout 로 실행
  → 결과 표 + 실행된 SQL 표시
```
- LLM 클라이언트: `services/llm.py` (OpenAI 호환 `/v1/chat/completions`)
- **DB 필요**: PostgreSQL 연결(DATABASE_URL)이 있어야 동작. CSV 모드면 안내만 표시.

## LLM 준비 (ollama 기본)

### 1) ollama 컨테이너 기동
`docker-compose.yml` 에 `ollama` 서비스가 있으며 **profile `llm`** 로 옵트인이다.
```bash
docker compose --profile llm up -d          # app + ollama 함께 기동
```

### 2) 모델 1회 다운로드
```bash
docker compose exec ollama ollama pull qwen2.5-coder:3b
```
- 기본 모델은 `qwen2.5-coder:3b`(SQL 생성에 강하고 CPU 에서도 동작). `.env` 의
  `LLM_MODEL` 로 바꿀 수 있다(예: 성능 여유 시 `qwen2.5-coder:7b`).
- 사내망에서는 모델 다운로드가 프록시를 타야 한다. compose 의 ollama 서비스에
  `HTTP_PROXY/HTTPS_PROXY` 가 설정돼 있다.

### 3) 확인
```bash
docker compose exec app python -c "from services.llm import chat; print(chat([{'role':'user','content':'say hi'}]))"
```

## GPU (선택)
CPU 로도 동작하지만 느리다. NVIDIA GPU + WSL GPU 패스스루가 준비돼 있으면
`docker-compose.yml` 의 ollama `deploy.resources` 주석을 해제한다.

## vllm 으로 교체 (대안, GPU 필요)
vllm 도 OpenAI 호환 API 라 `LLM_BASE_URL` 만 바꾸면 된다.
```bash
docker run --gpus all -p 8000:8000 vllm/vllm-openai \
  --model Qwen/Qwen2.5-Coder-7B-Instruct
```
그리고 `.env`:
```
LLM_BASE_URL=http://host.docker.internal:8000/v1
LLM_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
```

## 사내망에서 ollama 레지스트리 접근이 막힐 때
`ollama pull` 이 프록시로도 안 되면:
1. 접근 가능한 PC 에서 `ollama pull qwen2.5-coder:3b` 후, 모델이 저장된
   `~/.ollama` (컨테이너는 `ollama_models` 볼륨)를 옮긴다.
2. 또는 GGUF 파일을 구해 `Modelfile` 로 import:
   ```
   docker compose exec ollama sh -c 'echo "FROM /models/model.gguf" > /tmp/Modelfile && ollama create mymodel -f /tmp/Modelfile'
   ```

## 보안 (LLM 이 만든 SQL 을 실행하므로 다층 방어)
`services/text2sql.py` 의 `sanitize_sql()` 이 실행 전 검증한다:
1. `SELECT`/`WITH` 로 시작하는 **단일 문장만** 허용
2. 쓰기/DDL/권한/시스템 함수 키워드 차단
   (INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/GRANT/COPY/pg_*/… — 문자열
   리터럴은 스캔에서 제외해 오탐 방지)
3. 다중 문장(`;`)·SQL 주석(`--`,`/* */`) 차단
4. `LIMIT` 자동 부착(기본 200) + `statement_timeout`(10초) + **read-only 트랜잭션**

### 권장: DB 읽기 전용 롤
추가 방어로, 앱이 접속하는 DB 계정을 **SELECT 전용**으로 두면 가장 안전하다.
```sql
CREATE ROLE dashboard_ro LOGIN PASSWORD '****';
GRANT CONNECT ON DATABASE researcher_board TO dashboard_ro;
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
```
그리고 `.env` 의 `DATABASE_URL` 에 이 계정을 쓴다. (단, 이 경우 부서장 코멘트
저장 기능은 쓰기 권한이 필요하므로, 코멘트 저장까지 쓰려면 별도 고려가 필요하다.)

## 문제 해결
| 증상 | 원인/해결 |
|------|-----------|
| "PostgreSQL 연결이 필요합니다" | DATABASE_URL 미설정 → `.env` 설정 |
| "로컬 LLM 서버에 연결할 수 없습니다" | ollama 미기동 → `docker compose --profile llm up -d` |
| "LLM 응답 시간 초과" | 모델이 큼/CPU 느림 → 소형 모델 사용 또는 `LLM_TIMEOUT` 상향 |
| "허용되지 않는 키워드" | LLM 이 쓰기/시스템 쿼리 생성 → 질문을 조회 형태로 다시 |
| 결과가 이상함 | 전 컬럼이 TEXT 라 형변환 필요 — 프롬프트에 캐스팅 지시 포함되어 있으나, 질문을 더 구체적으로 |
