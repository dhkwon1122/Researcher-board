"""
연구원 개별 프로필의 "A4 인쇄" 콘텐츠를 헤드리스 브라우저(Playwright)로
그대로 렌더링해 PDF로 캡처한다 — pages/researcher_profile.py의 "프로필
인쇄 (A4)" 버튼이 브라우저에서 만드는 것과 동일한 결과물을, 서버 쪽에서
파일(bytes)로 뽑아 메일 첨부에 쓴다. 화면 인쇄 시 실행하는 동적 폰트/행
자르기 로직(assets/profile_print.js의 window.__prepareProfilePrint())을
그대로 재사용해, PDF 전용 레이아웃을 별도로 만들지 않는다 — 인쇄 결과와
항상 100% 동일하다(레이아웃이 바뀌어도 이원화된 두 구현이 서로 어긋날
일이 없음).

이 앱은 로그인이 필요하다(app.py의 require_login). 헤드리스 브라우저가
같은 컨테이너 안에서 앱 자신에게 http://127.0.0.1:{PORT}로 다시 접속하는
서버사이드 렌더링 패턴을 쓰는데, 이때도 로그인이 필요하므로 호출부(현재
로그인된 사용자의 Flask 세션 쿠키)가 그 쿠키 값을 그대로 넘겨줘야 한다
— 헤드리스 브라우저 컨텍스트에 같은 쿠키를 심어 "이미 로그인된 상태"로
만든다(별도 서버사이드 세션 저장소 없이 서명된 쿠키만으로 인증하므로,
같은 SECRET_KEY를 쓰는 이 앱 프로세스가 그대로 검증할 수 있다).
"""

import os

from playwright.sync_api import sync_playwright


class ProfilePdfError(RuntimeError):
    """PDF 생성 실패를 알리는 예외."""


def render_profile_pdf(rid: str, session_cookie: str) -> bytes:
    """researcher_id=rid인 연구원의 A4 인쇄 콘텐츠를 PDF bytes로 렌더링한다.
    session_cookie는 현재 로그인된 사용자의 Flask 'session' 쿠키 값(호출부가
    flask.request.cookies.get('session')로 가져와 그대로 전달)."""
    if not session_cookie:
        raise ProfilePdfError('로그인 세션을 확인할 수 없습니다.')

    port = os.environ.get('PORT', '8501')
    base_url = f'http://127.0.0.1:{port}'

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context()
                context.add_cookies([{
                    'name': 'session', 'value': session_cookie, 'url': base_url,
                }])
                page = context.new_page()
                page.goto(f'{base_url}/?id={rid}', wait_until='networkidle', timeout=30000)
                # _print_profile_content()가 항상 만드는 2페이지(논문·특허)
                # 블록이 나타날 때까지 대기 — update_profile() 콜백이 profile-
                # print-content를 채웠다는 신호로 쓴다. .profile-print-only는
                # 화면에서 항상 display:none이라(인쇄/PDF 캡처 시에만 보임)
                # state='attached'로 기다려야 한다 — 기본값(visible)이면 절대
                # 만족되지 않아 타임아웃난다.
                page.wait_for_selector('#profile-print-content .print-page-block', state='attached', timeout=15000)
                page.evaluate('window.__prepareProfilePrint && window.__prepareProfilePrint()')
                page.emulate_media(media='print')
                # prefer_css_page_size=True — assets/profile_print.js가 주입한
                # @page(A4, 14mm/16mm 여백) CSS를 그대로 따르게 한다. 이 옵션이
                # 없으면 Chromium이 기본 Letter 포맷 + 0 여백으로 캡처해버려,
                # 실제 브라우저 인쇄 결과와 달라진다.
                pdf_bytes = page.pdf(print_background=True, prefer_css_page_size=True)
            finally:
                browser.close()
        return pdf_bytes
    except ProfilePdfError:
        raise
    except Exception as exc:
        raise ProfilePdfError(f'PDF 생성 실패: {exc}') from exc
