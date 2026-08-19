"""
사내 SMTP 메일 발송 공용 유틸리티.

일부 리포트(예: process_project_expertise.py의 "과제 전문성 분석")는 앱
화면이 아니라 앱 밖(다른 부서 공유 등)으로 배포해야 할 때가 있는데, 이
경우도 data/processed/에 완성된 HTML 파일을 남겨두지 않고 그때그때 만들어
메일로만 보낸다 — 서버 파일시스템에 접근 가능한 누구나 열어볼 수 있는
사본을 남기지 않기 위해서다(역할 기반 접근 제어는 화면을 거칠 때만
적용되는 애플리케이션 레벨이라 파일 자체는 보호하지 않는다).

인증: .env의 SMTP_HOST/SMTP_FROM(필수), SMTP_PORT(기본 587)/SMTP_USE_TLS
(기본 true)/SMTP_USER/SMTP_PASSWORD(사내 릴레이가 인증 없이 열려 있으면
SMTP_USER/SMTP_PASSWORD는 생략 가능). 표준 라이브러리(smtplib)만 사용해
추가 의존성이 없다.
"""

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from services.db import load_env_file  # noqa: E402

load_env_file()


class MailError(RuntimeError):
    """SMTP 미설정 또는 발송 실패를 알리는 예외."""


def send_html_email(to: list[str], subject: str, html_body: str) -> None:
    """to(수신자 이메일 주소 목록)에게 html_body를 HTML 본문으로 발송한다.
    SMTP_HOST/SMTP_FROM 미설정이거나 발송 자체가 실패하면 MailError."""
    host = os.environ.get('SMTP_HOST', '').strip()
    sender = os.environ.get('SMTP_FROM', '').strip()
    if not host or not sender:
        raise MailError(
            'SMTP_HOST/SMTP_FROM이 설정되지 않았습니다 — .env에 사내 메일 서버 정보를 '
            '추가하세요(.env.example의 SMTP_* 참고).'
        )
    recipients = [addr.strip() for addr in to if addr.strip()]
    if not recipients:
        raise MailError('수신자가 없습니다.')

    port = int(os.environ.get('SMTP_PORT', '587') or '587')
    use_tls = os.environ.get('SMTP_USE_TLS', 'true').strip().lower() not in ('0', 'false', 'no')
    user = os.environ.get('SMTP_USER', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '').strip()

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(sender, recipients, msg.as_string())
    except Exception as exc:
        raise MailError(f'메일 발송 실패: {exc}') from exc
