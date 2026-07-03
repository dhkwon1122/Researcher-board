# Docker 빌드 & 실행 (사내망 포함)

앱 이미지는 `Dockerfile` 로 빌드하고, `docker-compose.yml` 로 앱 + PostgreSQL을
함께 띄운다. 사내망 빌드에 필요한 **pip 사내 저장소 / CA 인증서 / 프록시**는
모두 **빌드 인자(ARG)** 로 받는다. 값을 주지 않으면 공용 PyPI로 그대로 빌드된다.

---

## 구성 파일
| 파일 | 역할 |
|------|------|
| `Dockerfile` | 앱 이미지 (python:3.11-slim + gunicorn) |
| `.dockerignore` | data·.env·.git 등 빌드 컨텍스트 제외 |
| `docker-compose.yml` | `db`(postgres:16) + `app` 서비스 |
| `certs/` | 사내 CA 인증서(*.crt) 투입 위치 (커밋 안 함) |

앱 진입점: `app:server` (`app.py` 의 `server = app.server`, Dash 내부 Flask WSGI).
컨테이너는 gunicorn 으로 8050 포트 서빙.

---

## 1. 사외 / 공용 PyPI 빌드
```bash
docker compose build
docker compose up -d
# http://localhost:8050
```

---

## 2. 사내망 빌드 (pip 사내 저장소 · 프록시 · 인증서)

### 2-1. 사내 CA 인증서 (HTTPS 사내 저장소/프록시인 경우)
사내 루트/중간 CA 를 PEM `.crt` 로 `certs/` 에 복사한다.
```
certs/corp-root-ca.crt
```
Dockerfile 이 빌드 시 시스템 신뢰 저장소에 등록하고, 런타임 파이썬
(requests·psycopg2 SSL)이 이를 신뢰하도록 `REQUESTS_CA_BUNDLE` 등을 설정한다.

### 2-2. 빌드 인자 지정
빌드 인자를 셸 환경변수로 export 하면 compose 가 그대로 전달한다.
```bash
export PIP_INDEX_URL=https://nexus.corp/repository/pypi/simple
export PIP_TRUSTED_HOST=nexus.corp
export HTTP_PROXY=http://proxy.corp:8080
export HTTPS_PROXY=http://proxy.corp:8080
export NO_PROXY=localhost,127.0.0.1,db,.corp
# (선택) pip 이 사내 CA 로 인덱스 SSL 을 검증하게 하려면:
export PIP_CERT=/usr/local/share/ca-certificates/corp/corp-root-ca.crt

docker compose build
docker compose up -d
```

또는 compose 없이 직접:
```bash
docker build \
  --build-arg PIP_INDEX_URL=$PIP_INDEX_URL \
  --build-arg PIP_TRUSTED_HOST=$PIP_TRUSTED_HOST \
  --build-arg HTTP_PROXY=$HTTP_PROXY \
  --build-arg HTTPS_PROXY=$HTTPS_PROXY \
  --build-arg NO_PROXY=$NO_PROXY \
  -t researcher-board:latest .
```

> **인증서 vs trusted-host**: 사내 인덱스가 사내 CA HTTPS 면 `PIP_CERT` 로
> 정식 검증하거나, 간단히 `PIP_TRUSTED_HOST` 로 그 호스트의 SSL 검증을 건너뛴다.
> 프록시는 빌드 단계에만 적용되고 런타임 이미지에는 남지 않는다.

---

## 3. 데이터 & DB

- **데이터**: `./data` 를 컨테이너 `/app/data` 로 마운트한다(이미지에 굽지 않음).
  호스트의 `data/processed/*.csv` 를 그대로 사용.
- **DB 접속**: 컨테이너 내부에서는 `DATABASE_URL` 이 `db` 서비스명을 가리킨다
  (compose 에서 자동 설정: `...@db:5432/...`). 그래서 `NO_PROXY` 에 `db` 를 넣어
  DB 트래픽이 프록시로 새지 않게 한다.
- **CSV → DB 적재** (DB 사용 시 최초 1회):
  ```bash
  docker compose exec app python pipeline/load_to_db.py
  ```
  `DATABASE_URL` 미설정으로 두면 앱은 마운트된 CSV 로 그대로 동작(폴백).

---

## 4. 확인
```bash
docker compose ps          # app, db 상태
docker compose logs -f app # gunicorn 로그
curl -I http://localhost:8050
```

---

## 5. 자주 겪는 사내망 이슈
- **pip SSL 오류(CERTIFICATE_VERIFY_FAILED)**: `certs/` 에 사내 CA 넣고
  재빌드하거나 `PIP_TRUSTED_HOST` 지정.
- **빌드 중 네트워크 타임아웃**: `HTTP_PROXY`/`HTTPS_PROXY` 누락. 위 export 확인.
- **apt 단계 실패**: 사내 apt 미러가 필요할 수 있음. base 이미지를 사내
  레지스트리 미러(python:3.11-slim 사본)로 바꾸고, 필요 시 apt 프록시도 지정.
- **DB 접속 실패**: `NO_PROXY` 에 `db,localhost,127.0.0.1` 포함했는지 확인.
