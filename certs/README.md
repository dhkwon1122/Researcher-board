# 사내 CA 인증서

사내망에서 Docker 이미지를 빌드할 때, 사내 프록시/사내 pip 저장소가
사내 루트 CA로 서명된 HTTPS를 쓰는 경우 여기에 인증서를 넣는다.

## 방법 A — 개별 사내 CA (권장)
사내 루트 CA(및 중간 CA)를 **PEM 형식 `.crt`** 로 이 디렉터리에 복사한다.
```
certs/
  corp-root-ca.crt
  corp-intermediate-ca.crt   # (있으면)
```
Dockerfile 이 빌드 시 이 파일들을 시스템 신뢰 저장소에 등록하고
`update-ca-certificates` 를 실행한다.

## 방법 B — 전체 CA 번들 통째 교체 (간편)
개별 CA 를 못 구할 때, **이미 사내 CA 가 포함된 전체 번들**을
`certs/ca-bundle.crt` 로 두면 컨테이너의 시스템 번들
(`/etc/ssl/certs/ca-certificates.crt`)을 통째로 교체한다.

WSL/리눅스에서 이미 사내망이 되는 환경이라면 그 머신의 번들을 그대로 쓰면 된다:
```bash
cp /etc/ssl/certs/ca-certificates.crt certs/ca-bundle.crt
```

## 두 방법 공통 효과
- git clone(oh-my-zsh) 이 사내 프록시 TLS 인터셉션 하에서도 검증 성공.
- 런타임 파이썬(requests, psycopg2 SSL 등)이 사내 CA 를 신뢰
  (`REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` 가 시스템 번들을 가리킴).
- TLS 검증을 끄지 않으므로 보안 유지.

## 주의
- `.crt` 파일은 사내 자산이므로 git 에 커밋하지 않는다
  (`.gitignore` 에서 `certs/*.crt` 제외됨).
- 인증서가 필요 없는 사외/공용 PyPI 빌드에서는 이 디렉터리를 비워둬도 된다
  (빌드는 그대로 성공한다).
