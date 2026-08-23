# 인증서

이 디렉터리는 용도가 다른 두 종류의 인증서를 담는다 — 헷갈리지 않도록 구분할 것.

1. **사내 CA 인증서(아래 "사내 CA 인증서" 섹션)** — 이 앱이 *밖으로* 나가는
   HTTPS 요청(pip 설치, 사내 프록시 등)에서 사내 루트 CA를 신뢰하게 만드는
   용도. Dockerfile 빌드 시점에 쓰인다.
2. **리버스 프록시 서버 인증서(`server.crt`/`server.key`)** — deploy/nginx.conf가
   TLS 종료에 쓰는, 이 앱을 브라우저에 *서빙*하기 위한 서버 인증서. 로컬/개발용은
   `scripts/gen_self_signed_cert.sh`로 자체 서명 인증서를 생성하고, 운영
   배포에서는 사내 PKI 발급 인증서로 같은 파일명(`certs/server.crt`,
   `certs/server.key`)으로 교체한다. docker-compose.yml의 `reverse-proxy`
   서비스(`--profile proxy`)가 이 두 파일을 마운트한다.

두 종류 모두 `.gitignore`로 제외되어 있어 git에는 커밋되지 않는다.

## 사내 CA 인증서

사내망에서 Docker 이미지를 빌드할 때, 사내 프록시/사내 pip 저장소가
사내 루트 CA로 서명된 HTTPS를 쓰는 경우 여기에 인증서를 넣는다.

### 방법 A — 개별 사내 CA (권장)
사내 루트 CA(및 중간 CA)를 **PEM 형식 `.crt`** 로 이 디렉터리에 복사한다.
```
certs/
  corp-root-ca.crt
  corp-intermediate-ca.crt   # (있으면)
```
Dockerfile 이 빌드 시 이 파일들을 시스템 신뢰 저장소에 등록하고
`update-ca-certificates` 를 실행한다.

### 방법 B — 전체 CA 번들 통째 교체 (간편)
개별 CA 를 못 구할 때, **이미 사내 CA 가 포함된 전체 번들**을
`certs/ca-bundle.crt` 로 두면 컨테이너의 시스템 번들
(`/etc/ssl/certs/ca-certificates.crt`)을 통째로 교체한다.

WSL/리눅스에서 이미 사내망이 되는 환경이라면 그 머신의 번들을 그대로 쓰면 된다:
```bash
cp /etc/ssl/certs/ca-certificates.crt certs/ca-bundle.crt
```

### 두 방법 공통 효과
- git clone(oh-my-zsh) 이 사내 프록시 TLS 인터셉션 하에서도 검증 성공.
- 런타임 파이썬(requests, psycopg2 SSL 등)이 사내 CA 를 신뢰
  (`REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` 가 시스템 번들을 가리킴).
- TLS 검증을 끄지 않으므로 보안 유지.

### 주의
- `.crt` 파일은 사내 자산이므로 git 에 커밋하지 않는다
  (`.gitignore` 에서 `certs/*.crt` 제외됨).
- 인증서가 필요 없는 사외/공용 PyPI 빌드에서는 이 디렉터리를 비워둬도 된다
  (빌드는 그대로 성공한다).

## 리버스 프록시 서버 인증서

`deploy/nginx.conf`(TLS 종료)가 참조하는 `certs/server.crt`·`certs/server.key`.

### 로컬/개발 — 자체 서명
```bash
scripts/gen_self_signed_cert.sh            # CN=localhost
scripts/gen_self_signed_cert.sh my.host    # 도메인 지정
docker compose --profile proxy up -d
```
브라우저에 "신뢰할 수 없는 인증서" 경고가 뜨는 게 정상이다(사내 PKI 서명이
아니므로) — 로컬 검증용으로만 쓸 것.

### 운영 배포 — 사내 PKI 발급 인증서
사내 보안팀에서 서버 인증서를 발급받아 같은 파일명으로 교체한다:
```
certs/server.crt
certs/server.key
```
파일명·경로만 맞으면 `deploy/nginx.conf`나 `docker-compose.yml`은 손댈 필요 없다.
