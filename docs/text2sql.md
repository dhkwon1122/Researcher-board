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

## LLM 준비

ollama 실행 방식은 두 가지다. 사내망에서는 **방식 A(WSL 네이티브)** 가 가장 안정적이다
(도커 이미지 pull 을 안 거쳐서, 프록시가 큰 이미지를 손상시키는 문제를 피한다).

### 방식 A — WSL 에서 직접 실행한 ollama 사용 (권장)
앱은 도커 컨테이너, ollama 는 WSL 호스트에서 직접 실행하고 연결한다.

1) **WSL 에서 ollama 를 0.0.0.0 으로 기동** (컨테이너가 접근하려면 필수):
```bash
export OLLAMA_HOST=0.0.0.0:11434
ollama serve
# systemd 서비스로 설치된 경우:
#   sudo systemctl edit ollama   → [Service] Environment="OLLAMA_HOST=0.0.0.0:11434"
#   sudo systemctl restart ollama
```
2) **모델 준비** (WSL 에서. HuggingFace GGUF 를 import 하거나 ollama 로 pull):
```bash
ollama pull qwen3.5:4b
ollama list                     # LLM_MODEL 에 넣을 정확한 이름 확인
```
3) **앱 `.env`** — WSL 호스트(=host.docker.internal=172.17.0.1)를 가리킴:
```
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_MODEL=<ollama list 의 이름>
```
4) **앱만 기동** (ollama 컨테이너 불필요 → `--profile llm` 없이):
```bash
docker compose up -d --force-recreate
```
> 흔한 실수: `OLLAMA_HOST=0.0.0.0` 을 안 하면 기본 127.0.0.1 이라 컨테이너에서
> 연결이 refused 된다.

### 방식 B — ollama 를 도커 컨테이너로 기동
`docker-compose.yml` 의 `ollama` 서비스(**profile `llm`**)를 쓴다.
```bash
docker compose --profile llm up -d                  # app + ollama
docker compose exec ollama ollama pull qwen3.5:4b   # 모델 1회
```
- `.env` 는 `LLM_BASE_URL=http://ollama:11434/v1` (compose 기본값).
- 사내망은 이미지/모델 다운로드가 프록시를 타야 한다(ollama 서비스에 프록시 env 설정됨).
  프록시가 큰 이미지를 손상시켜 `exec format error` 가 나면 방식 A 를 쓰거나,
  외부망에서 `docker save`/`docker load` 로 이미지를 옮긴다.

### 확인 (공통)
```bash
docker compose exec app python -c "import socket; socket.create_connection(('host.docker.internal',11434),5); print('OPEN')"
docker compose exec app python -c "from services.llm import chat; print(chat([{'role':'user','content':'say hi'}]))"
```

## GPU 로 전환 (선택)
CPU 로도 동작하지만 큰 모델은 느리다. GPU 가 있으면 **오버레이 파일**로 켠다
(기본 compose 는 그대로 두고, GPU 설정만 얹는 방식).
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d
```
전제: NVIDIA GPU + 드라이버, `nvidia-container-toolkit`(Docker GPU 노출),
WSL 이면 Windows NVIDIA 드라이버 + WSL GPU 패스스루.

GPU 에서는 더 큰 코더 모델이 SQL 정확도가 좋다:
```bash
# .env: LLM_MODEL=qwen3-coder:30b   (또는 qwen3.5:27b)
docker compose exec ollama ollama pull qwen3-coder:30b
```

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
| "로컬 LLM 서버에 연결할 수 없습니다" | ollama 미기동, 또는 WSL ollama 가 127.0.0.1 로만 리슨 → `export OLLAMA_HOST=0.0.0.0:11434` 후 `ollama serve`(방식 A), 또는 `docker compose --profile llm up -d`(방식 B) |
| 컨테이너에서 ollama refused | `OLLAMA_HOST=0.0.0.0` 미설정 → 위와 동일 |
| ollama 도커 이미지 `exec format error` | 프록시가 이미지 손상/오배포 → 방식 A(WSL 네이티브) 사용, 또는 외부망에서 `docker save`/`load` |
| "LLM 응답 시간 초과" | 모델이 큼/CPU 느림 → 소형 모델 사용 또는 `LLM_TIMEOUT` 상향 |
| "허용되지 않는 키워드" | LLM 이 쓰기/시스템 쿼리 생성 → 질문을 조회 형태로 다시 |
| 결과가 이상함 | 전 컬럼이 TEXT 라 형변환 필요 — 프롬프트에 캐스팅 지시 포함되어 있으나, 질문을 더 구체적으로 |
