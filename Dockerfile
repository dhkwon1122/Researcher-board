# 연구원 대시보드 — 사내 빌드용 이미지
#
# 사내망에서 빌드 시 pip 사내 저장소 / CA 인증서 / 프록시가 필요할 수 있어
# 모두 '빌드 인자(ARG)'로 받는다. 값을 주지 않으면 공용 PyPI로 동작한다.
#
# ── 빌드 예시 (사내망) ─────────────────────────────────────────────
#   docker build \
#     --build-arg PIP_INDEX_URL=https://nexus.corp/repository/pypi/simple \
#     --build-arg PIP_TRUSTED_HOST=nexus.corp \
#     --build-arg HTTP_PROXY=http://proxy.corp:8080 \
#     --build-arg HTTPS_PROXY=http://proxy.corp:8080 \
#     --build-arg NO_PROXY=localhost,127.0.0.1,.corp \
#     -t researcher-board:latest .
#
#   # 사내 CA 인증서가 필요하면 빌드 전에 certs/ 에 *.crt 를 넣어둔다.
#   #   cp 사내루트CA.crt certs/corp-root-ca.crt
#
# ── 빌드 예시 (사외/공용 PyPI) ─────────────────────────────────────
#   docker build -t researcher-board:latest .

FROM python:3.11-slim

# ── 빌드 인자 (미지정 시 빈 값 → 공용 PyPI/무프록시) ──
ARG PIP_INDEX_URL=
ARG PIP_TRUSTED_HOST=
ARG PIP_CERT=
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG NO_PROXY=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── 1) 사내 CA 인증서 등록 ──
# certs/ 안의 *.crt 를 시스템 신뢰 저장소에 등록한다.
# (certs/ 에 .crt 가 없으면 update-ca-certificates 는 아무 것도 추가하지 않음)
COPY certs/ /usr/local/share/ca-certificates/corp/
RUN http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" no_proxy="$NO_PROXY" \
    apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 런타임 파이썬(requests/psycopg2 등)이 사내 CA 를 신뢰하도록 시스템 번들 지정
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# ── 2) 의존성 설치 (사내 pip 인덱스/프록시/인증서 반영) ──
# ${VAR:+--flag $VAR} : VAR 가 비어있지 않을 때만 해당 옵션을 추가.
COPY requirements.txt .
RUN http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" no_proxy="$NO_PROXY" \
    pip install --upgrade pip \
      ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
      ${PIP_TRUSTED_HOST:+--trusted-host "$PIP_TRUSTED_HOST"} \
      ${PIP_CERT:+--cert "$PIP_CERT"} \
    && http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" no_proxy="$NO_PROXY" \
    pip install \
      ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
      ${PIP_TRUSTED_HOST:+--trusted-host "$PIP_TRUSTED_HOST"} \
      ${PIP_CERT:+--cert "$PIP_CERT"} \
      -r requirements.txt gunicorn

# ── 3) 앱 소스 복사 ──
# data/ 와 .env 는 .dockerignore 로 제외 → 컨테이너에는 볼륨/시크릿으로 주입.
COPY . .

EXPOSE 8050

# WSGI 서버로 구동 (app.py 의 server = app.server)
CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "2", "--timeout", "120", "app:server"]
