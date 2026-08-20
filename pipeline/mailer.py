"""
사내 메일 발송 REST API 연동.

일부 리포트(예: process_project_expertise.py의 "과제 전문성 분석")는 앱
화면이 아니라 앱 밖(다른 부서 공유 등)으로 배포해야 할 때가 있는데, 이
경우도 data/processed/에 완성된 HTML 파일을 남겨두지 않고 그때그때 만들어
메일로만 보낸다 — 서버 파일시스템에 접근 가능한 누구나 열어볼 수 있는
사본을 남기지 않기 위해서다(역할 기반 접근 제어는 화면을 거칠 때만
적용되는 애플리케이션 레벨이라 파일 자체는 보호하지 않는다).

인증/설정: .env의 MAIL_API_URL(base URL — 이 모듈이 /mails/send?userId=...를
직접 이어붙인다. 끝에 /가 있어도 없어도 됨)/MAIL_TOKEN/MAIL_SYSTEM_ID/
MAIL_FROM(전부 필수), MAIL_USER_ID(기본값 people.sait — .env에 값이 있으면
그걸로 덮어씀), MAIL_TIMEOUT(초, 기본 30 — API 응답이 느려 타임아웃이 자주
나면 늘릴 것).
verify=False는 이 사내 전용 API에 한해 의도적으로 유지한다(사내 루트 CA가
공인 신뢰 체인에 없어 검증이 실패하기 때문 — 사용자 확인됨). 다른 외부
호출(LLM2/Confluence 등)에는 영향 없다.
"""

import json
import os
import sys
from urllib.parse import quote

import requests
import urllib3

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from services.db import load_env_file  # noqa: E402

load_env_file()

# verify=False로 인한 InsecureRequestWarning은 이 사내 API 호출에서는
# 의도된 것이라 로그를 채우지 않도록 끈다(다른 requests 호출에는 영향 없음).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DEFAULT_USER_ID = 'people.sait'


class MailError(RuntimeError):
    """메일 API 미설정 또는 발송 실패를 알리는 예외."""


def send_html_email(to: list[str], subject: str, html_body: str,
                     attachments: list[tuple[str, bytes]] | None = None) -> None:
    """to(수신자 이메일 주소 목록)에게 html_body를 HTML 본문으로 발송한다.
    MAIL_API_URL은 base URL만 넣으면 된다(예: https://mail.internal.example.com)
    — 실제 호출은 이 함수가 뒤에 /mails/send?userId=...를 이어붙인 주소로
    나간다. MAIL_API_URL/MAIL_TOKEN/MAIL_SYSTEM_ID/MAIL_FROM 미설정이거나
    발송 자체가 실패하면 MailError.

    attachments를 주면(예: [('홍길동(00000001)_프로필.pdf', pdf_bytes)])
    JSON 단일 바디 대신 멀티파트로 보낸다 — 이 API는 첨부파일이 있을 때
    'mail' 필드(JSON 문자열, 파일명 없는 폼 필드)와 'attachments' 필드
    (파일마다 하나씩, 같은 필드명 반복)로 받는다(사용자가 실제 호출 코드로
    확인: requests.post(url, data=[('mail', (None, json.dumps(payload)))],
    files=[('attachments', fileobj), ...])). 이 형태를 그대로 재현한다."""
    base_url = os.environ.get('MAIL_API_URL', '').strip()
    token = os.environ.get('MAIL_TOKEN', '').strip()
    system_id = os.environ.get('MAIL_SYSTEM_ID', '').strip()
    sender = os.environ.get('MAIL_FROM', '').strip()
    if not base_url or not token or not system_id or not sender:
        raise MailError(
            'MAIL_API_URL/MAIL_TOKEN/MAIL_SYSTEM_ID/MAIL_FROM이 설정되지 않았습니다 — '
            '.env에 사내 메일 API 정보를 추가하세요(.env.example의 MAIL_* 참고).'
        )
    recipients = [addr.strip() for addr in to if addr.strip()]
    if not recipients:
        raise MailError('수신자가 없습니다.')

    user_id = os.environ.get('MAIL_USER_ID', '').strip() or _DEFAULT_USER_ID

    headers = {
        'Authorization': f'Bearer {token}',
        'System-ID': system_id,
        'Content-Type': 'application/json;charset=utf-8',
    }
    payload = {
        'subject': subject,
        'contents': html_body,
        'contentType': 'html',
        'docSecuType': 'PERSONAL',
        'sender': {'emailAddress': sender},
        'recipients': [
            {'emailAddress': addr, 'recipientType': 'TO'} for addr in recipients
        ],
    }
    # 사내망 전용 엔드포인트라 프록시를 거치지 않고 직접 접속한다(LLM2/
    # Confluence 등 다른 외부 호출용 프록시 설정과는 무관).
    proxies = {'http': None, 'https': None}

    # 이 API는 params=(요청 바디와 별개로 requests가 인코딩해 붙이는 쿼리
    # 스트링)를 받아들이지 않는다 — URL 뒤에 문자 그대로 ?userId=...를 붙여야
    # 한다(사용자 확인). quote()로 값만 안전하게 인코딩해 직접 이어붙인다.
    # MAIL_API_URL은 base URL만 받아 여기서 /mails/send 경로를 붙인다
    # (사용자 확인 — 끝에 /가 있어도 없어도 되도록 rstrip으로 정규화).
    full_url = f'{base_url.rstrip("/")}/mails/send?userId={quote(user_id, safe="")}'

    timeout = float(os.environ.get('MAIL_TIMEOUT', '30') or '30')
    try:
        if attachments:
            # 멀티파트 요청은 requests가 Content-Type: multipart/form-data;
            # boundary=...를 스스로 정해야 하므로, 위 headers의 고정
            # application/json 값을 그대로 쓰면 안 된다 — Authorization/
            # System-ID만 남긴 별도 헤더를 쓴다.
            multipart_headers = {'Authorization': headers['Authorization'], 'System-ID': system_id}
            files = [('attachments', (name, content)) for name, content in attachments]
            resp = requests.post(
                full_url,
                headers=multipart_headers,
                data=[('mail', (None, json.dumps(payload)))],
                files=files,
                proxies=proxies,
                verify=False,
                timeout=timeout,
            )
        else:
            resp = requests.post(
                full_url,
                headers=headers,
                data=json.dumps(payload),
                proxies=proxies,
                verify=False,
                timeout=timeout,
            )
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise MailError(f'메일 발송 실패: {exc}') from exc
