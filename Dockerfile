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

# ── 빌드 인자 (사내 기본값 내장. 빌드 시 --build-arg 로 덮어쓸 수 있음) ──
# 사외/공용 PyPI 로 빌드하려면 빈 값으로 덮어쓴다:
#   docker build --build-arg PIP_INDEX_URL= --build-arg HTTP_PROXY= ... .
ARG PIP_INDEX_URL=http://repository.samsungds.net/repository/proxy-pypi-files.pythonhosted.org/simple
ARG PIP_TRUSTED_HOST=repository.samsungds.net
ARG PIP_CERT=
ARG HTTP_PROXY=http://12.26.204.100:8080
ARG HTTPS_PROXY=http://12.26.204.100:8080
ARG NO_PROXY=localhost,127.0.0.1,db,::1,samsungds.net,*.samsungds.net,*.samsung.net,12.0.0.0/8,10.0.0.0/8,192.0.0.0/8,172.0.0.0/8

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── 1) 사내 CA 인증서 등록 + 개발 편의 도구(vim) 설치 ──
# (zsh/oh-my-zsh 설치는 빌드 환경에서 오류가 나 제외 — 필요해지면 재검토)
# certs/ 에 아래 중 하나(또는 둘 다)를 둘 수 있다:
#   (a) 개별 사내 CA:  certs/corp-root-ca.crt  → update-ca-certificates 로 등록
#   (b) 전체 CA 번들:  certs/ca-bundle.crt     → 시스템 번들을 통째로 교체
#       (WSL 의 /etc/ssl/certs/ca-certificates.crt 를 그대로 복사한 파일)
# 둘 다 없으면 컨테이너 기본 CA 로 빌드한다.
COPY certs/ /tmp/corp-certs/
RUN http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" no_proxy="$NO_PROXY" \
    apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates vim git curl \
    && for f in /tmp/corp-certs/*.crt; do \
         [ -e "$f" ] || continue; \
         case "$f" in */ca-bundle.crt) continue ;; esac; \
         cp "$f" /usr/local/share/ca-certificates/; \
       done \
    && update-ca-certificates \
    && if [ -f /tmp/corp-certs/ca-bundle.crt ]; then \
         cp /tmp/corp-certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt; \
         echo '[build] 사내 CA 번들 적용: /etc/ssl/certs/ca-certificates.crt'; \
       fi \
    && rm -rf /var/lib/apt/lists/* /tmp/corp-certs

# vim 설정을 이미지에 굽는다. dotfiles/ 의 내용을 본인 설정으로 교체 후
# 리빌드하면 반영된다.
COPY dotfiles/vimrc /root/.vimrc

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
      -r requirements.txt

# ── 2.5) Playwright 헤드리스 브라우저 설치 (개별 프로필 PDF 메일 첨부용) ──
# services/profile_pdf.py가 "프로필 인쇄 (A4)" 화면을 헤드리스 브라우저로
# 그대로 렌더링해 PDF로 캡처한다(pipeline/mailer.py의 첨부파일 발송과 함께
# 씀). --with-deps가 Chromium 실행에 필요한 시스템 라이브러리까지 apt로
# 설치한다. 이미지가 커지고(+300MB 안팎) 브라우저 바이너리를 Microsoft
# CDN에서 내려받아야 하는데, 이 호스트는 사내 pip 프록시 허용 목록에는
# 없을 수 있어(pip은 repository.samsungds.net만 거치면 되지만 이건 별도
# 외부 호스트) 사내망에서 막혀 있을 가능성이 높다.
#
# playwright install은 내부적으로 Node.js로 다운로드를 받는데, Node는
# Python의 requests(REQUESTS_CA_BUNDLE)와 달리 OS 인증서 저장소를 자동으로
# 쓰지 않아, 사내망 프록시가 TLS를 가로채는(MITM) 환경에서는 Node가 그
# 체인을 검증하지 못해 실패한다("unable to verify the first certificate").
# NODE_EXTRA_CA_CERTS로 시스템 CA 번들을 알려주는 것으로 충분할 수도
# 있지만, certs/ 에 사내 루트 CA를 실제로 넣어 빌드했을 때만 그 번들에
# 그 인증서가 들어 있다 — pip 쪽은 --trusted-host로 검증 자체를 건너뛰고
# 있어서(위 2번 단계) 이 이미지가 사내 CA를 실제로 신뢰 저장소에 갖고
# 있는지가 여태 검증된 적이 없었다. 그래서 NODE_EXTRA_CA_CERTS만으로도
# 안 되면, pip과 동일한 원칙(신뢰할 수 있는 대상에 한해 이 빌드 시점
# 다운로드만 검증을 건너뛰는 방식은 공급망 변조를 허용하므로 사용하지 않는다.
#
# 그래도 실패하면(사내망 자체가 이 호스트를 막아둔 경우) 이 단계만
# 실패해도(|| true) 전체 빌드는 계속되고 나머지 기능은 정상 배포되며,
# PDF 첨부 메일만 "PDF 생성 실패" 에러로 비활성 상태가 된다 — 사내 미러가
# 있다면 PLAYWRIGHT_DOWNLOAD_HOST로 지정해 재시도할 것.
RUN http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" no_proxy="$NO_PROXY" \
    NODE_EXTRA_CA_CERTS="/etc/ssl/certs/ca-certificates.crt" \
    playwright install --with-deps chromium \
    || echo "[build] Playwright 브라우저 설치 실패 — PDF 첨부 메일 기능은 비활성화된 채로 나머지는 정상 빌드합니다. 원인은 보통 사내망에서 Chromium 다운로드 호스트가 막혀 있는 경우입니다."

# ── 3) 앱 소스 복사 ──
# data/ 와 .env 는 .dockerignore 로 제외 → 컨테이너에는 볼륨/시크릿으로 주입.
COPY . .

# 애플리케이션은 root 권한이 필요하지 않다. 바인드 마운트하는 ./data도
# 호스트에서 uid 10001이 읽고 쓸 수 있도록 소유권/ACL을 맞춘다.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

# 리슨 포트 (기본 8501). 실행 시 -e PORT=... 로 바꿀 수 있음.
ENV PORT=8501
EXPOSE 8501

# WSGI 서버로 구동 (app.py 의 server = app.server).
# PORT 환경변수를 반영하려 shell 형식 + exec (gunicorn 이 PID 1 로 신호 수신).
CMD exec gunicorn --bind "0.0.0.0:${PORT:-8501}" --workers 2 --timeout 120 app:server
