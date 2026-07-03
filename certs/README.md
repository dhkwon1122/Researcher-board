# 사내 CA 인증서

사내망에서 Docker 이미지를 빌드할 때, 사내 프록시/사내 pip 저장소가
사내 루트 CA로 서명된 HTTPS를 쓰는 경우 여기에 인증서를 넣는다.

## 사용법
사내 루트 CA(및 중간 CA) 인증서를 **PEM 형식 `.crt`** 로 이 디렉터리에 복사한다.
```
certs/
  corp-root-ca.crt
  corp-intermediate-ca.crt   # (있으면)
```

Dockerfile 이 빌드 시 `certs/*.crt` 를 시스템 신뢰 저장소에 등록하고
`update-ca-certificates` 를 실행한다. 그러면:
- 런타임 파이썬(requests, psycopg2 SSL 등)이 사내 CA 를 신뢰한다.
- pip 빌드 단계에서도 `--cert` 로 사내 인증서를 지정할 수 있다
  (`--build-arg PIP_CERT=/usr/local/share/ca-certificates/corp/corp-root-ca.crt`).

## 주의
- `.crt` 파일은 사내 자산이므로 git 에 커밋하지 않는다
  (`.gitignore` 에서 `certs/*.crt` 제외됨).
- 인증서가 필요 없는 사외/공용 PyPI 빌드에서는 이 디렉터리를 비워둬도 된다
  (빌드는 그대로 성공한다).
