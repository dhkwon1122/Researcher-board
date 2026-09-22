"""
사내 Confluence 페이지 조회 공용 유틸리티 (requests 직접 호출, PAT/게이트웨이 인증)

data/processed/project_confl_address.csv의 confl_address(컨플루언스 페이지 URL)
에서 base URL과 페이지 ID를 그때그때 추출해 페이지 본문을 가져온다.

2026-09-22부터 atlassian-python-api 라이브러리를 거치지 않고 requests로
REST API(/rest/api/content/{id} 등)를 직접 호출한다 — 사용자가 curl로 검증한
요청과 완전히 동일한 URL/헤더를 코드가 그대로 재현하도록 해, 라이브러리
내부에서 헤더를 어떻게 다루는지 몰라도(추적 불가능한 불확실성) 항상 검증된
요청 그대로 나가는 것을 보장한다.

CONFLUENCE_GATEWAY_BASE_URL(.env, 2026-09-22 추가 — 사내 API 게이트웨이 경유
정책 변경)이 설정돼 있으면, confl_address에서 뽑은 호스트 대신 이 값을 실제
요청 base URL로 쓴다 — REST API 경로 구조(/rest/api/content/{id} 등)는
게이트웨이도 원본 Confluence와 동일하게 받는다고 확인됨(사용자 확인), 앞단
호스트만 게이트웨이로 바뀐다. confl_address 자체의 호스트 허용 목록 검사
(CONFLUENCE_ALLOWED_HOSTS)는 게이트웨이 사용 여부와 무관하게 그대로
적용된다 — "실제로 어느 페이지를 조회할 수 있는지"와 "그 요청을 네트워크
상 어디로 보낼지"는 별개 문제이기 때문. 미설정이면 기존처럼 confl_address의
실제 호스트를 그대로 쓴다(하위 호환).

인증: .env의 CONFLUENCE_TOKEN(개인 액세스 토큰, PAT) 사용. 기본적으로
"Authorization: Bearer <토큰>" 헤더로 보내지만, CONFLUENCE_AUTH_HEADER/
CONFLUENCE_AUTH_SCHEME(.env, 2026-09-22 추가)로 헤더명/스킴을 바꿀 수 있다
(_auth_header() 참고). 사내 게이트웨이가 추가로 요구하는 헤더
(CONFLUENCE_DEP_TICKET/CONFLUENCE_DATA_CLASSIFICATION)의 실제 헤더명도
CONFLUENCE_DEP_TICKET_HEADER/CONFLUENCE_DATA_CLASSIFICATION_HEADER로
바꿀 수 있다(_extra_headers() 참고) — 게이트웨이가 요구하는 정확한
헤더명이 확인될 때까지 코드 재배포 없이 .env만 고쳐 재시도할 수 있게 함.
"""

import os
import re
import sys
from urllib.parse import urlparse

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from services.db import load_env_file  # noqa: E402

load_env_file()

_client_cache: dict = {}


class ConfluenceError(RuntimeError):
    """Confluence 조회 실패(미설정/인증오류/페이지 없음 등)를 알리는 예외."""


def _base_url(confl_address: str) -> str:
    parsed = urlparse(confl_address)
    host = (parsed.hostname or '').lower().rstrip('.')
    allowed = [h.strip().lower().lstrip('.') for h in
               os.environ.get('CONFLUENCE_ALLOWED_HOSTS', 'samsungds.net,samsung.net').split(',')
               if h.strip()]
    allow_http = os.environ.get('CONFLUENCE_ALLOW_HTTP', 'false').lower() in ('1', 'true', 'yes', 'on')
    if parsed.scheme != 'https' and not (allow_http and parsed.scheme == 'http'):
        raise ConfluenceError('Confluence 주소는 HTTPS만 허용됩니다.')
    if parsed.username or parsed.password or not host:
        raise ConfluenceError('유효하지 않은 Confluence 주소입니다.')
    if not any(host == suffix or host.endswith('.' + suffix) for suffix in allowed):
        raise ConfluenceError(f'허용되지 않은 Confluence 호스트입니다: {host}')

    gateway_base_url = os.environ.get('CONFLUENCE_GATEWAY_BASE_URL', '').strip()
    if gateway_base_url:
        gateway_base_url = gateway_base_url.rstrip('/')
        # confl_address와 동일한 스킴 검증을 여기도 적용한다(2026-09-22 추가 —
        # 실사용 중 CONFLUENCE_GATEWAY_BASE_URL에 실수로 http://를 넣어놓고
        # "ConnectionError: Remote end closed connection without response"로
        # 한참 헤맨 사례 발견 — 이 함수는 검증 없이 그 값을 그대로 반환하고
        # 있었다. confl_address 쪽 HTTPS 강제 검증과 형평을 맞춰, 게이트웨이
        # 쪽도 스킴이 틀리면 애매한 네트워크 에러 대신 바로 이유를 알 수
        # 있는 에러를 낸다).
        gateway_scheme = urlparse(gateway_base_url).scheme
        if gateway_scheme != 'https' and not (allow_http and gateway_scheme == 'http'):
            raise ConfluenceError(
                f'CONFLUENCE_GATEWAY_BASE_URL은 HTTPS만 허용됩니다(현재: {gateway_base_url}).'
            )
        return gateway_base_url
    return f'{parsed.scheme}://{parsed.netloc}'


def extract_page_id(confl_address: str) -> str | None:
    """다양한 Confluence URL 형식에서 pageId를 추출한다.
      - .../pages/viewpage.action?pageId=123456
      - .../wiki/spaces/{SPACE}/pages/123456/{title}
      - .../pages/123456
    URL 형식이 다르면 이 함수의 정규식을 실제 형식에 맞게 수정하세요.
    """
    m = re.search(r'[?&]pageId=(\d+)', confl_address)
    if m:
        return m.group(1)
    m = re.search(r'/pages/(\d+)(?:[/?]|$)', confl_address)
    if m:
        return m.group(1)
    return None


def extract_space_title(confl_address: str) -> tuple:
    """pageId가 없는 '.../display/{SPACE}/{title}' 형식 URL에서 (space, title)을
    추출한다. 매칭되지 않으면 (None, None)."""
    m = re.search(r'/display/([^/]+)/([^/?#]+)', confl_address)
    if not m:
        return None, None
    from urllib.parse import unquote
    return m.group(1), unquote(m.group(2)).replace('+', ' ')


def _html_to_text(body_html: str) -> str:
    """Confluence storage 포맷(XHTML)을 읽기 쉬운 텍스트로 변환."""
    if not body_html:
        return ''
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(body_html, 'html.parser').get_text('\n').strip()
    except ImportError:
        return re.sub(r'<[^>]+>', ' ', body_html).strip()


def _extra_headers() -> dict:
    """사내 API 게이트웨이가 REST API 호출에 추가로 요구하는 헤더(2026-09-21,
    보안정책 변경 — 사용자 확인) — 표준 Confluence API 스펙이 아니라 사내
    정책 헤더라 값이 없으면(둘 다 .env 미설정) 보내지 않는다(기존 동작 유지).

    헤더 "이름" 자체도 .env로 바꿀 수 있다(2026-09-22 추가 — 사용자 확인,
    게이트웨이가 요구하는 실제 헤더명이 X-Dep-Ticket/X-Data-Classification과
    한 글자라도 다르면 게이트웨이가 그 값을 아예 못 알아보고 인증 실패로
    처리할 수 있어서, 값을 담을 헤더명을 코드 재배포 없이 .env만 고쳐
    바로 재시도할 수 있게 했다). CONFLUENCE_DEP_TICKET_HEADER/
    CONFLUENCE_DATA_CLASSIFICATION_HEADER 미설정 시 기존 이름 그대로 사용."""
    headers = {}
    dep_ticket = os.environ.get('CONFLUENCE_DEP_TICKET', '').strip()
    if dep_ticket:
        header_name = os.environ.get('CONFLUENCE_DEP_TICKET_HEADER', '').strip() or 'X-Dep-Ticket'
        headers[header_name] = dep_ticket
    data_classification = os.environ.get('CONFLUENCE_DATA_CLASSIFICATION', '').strip()
    if data_classification:
        header_name = os.environ.get('CONFLUENCE_DATA_CLASSIFICATION_HEADER', '').strip() or 'X-Data-Classification'
        headers[header_name] = data_classification
    return headers


def _auth_header() -> tuple:
    """(헤더 이름, 헤더 값) — 인증 토큰을 실을 헤더. 기본은 표준
    "Authorization: Bearer <토큰>"이지만, 게이트웨이가 다른 헤더명/스킴을
    요구할 수 있어(2026-09-22, 사용자 확인 — "CONFLUENCE_TOKEN도
    Authorization이라는 명칭으로 헤더명을 가져가야 하는 것 같다") .env로
    둘 다 바꿀 수 있게 했다. atlassian-python-api의 Confluence(token=...)
    생성자가 내부적으로 만드는 Authorization 헤더에 맡기지 않고, 이 값으로
    직접 덮어써서(client._session.headers.update) 정확히 어떤 이름/형식으로
    나가는지 완전히 통제한다.
      CONFLUENCE_AUTH_HEADER : 기본 'Authorization'
      CONFLUENCE_AUTH_SCHEME : 기본 'Bearer' — 빈 문자열로 두면 토큰 값만
        그대로 헤더에 싣는다(스킴 접두사 없이)."""
    header_name = os.environ.get('CONFLUENCE_AUTH_HEADER', '').strip() or 'Authorization'
    scheme = os.environ.get('CONFLUENCE_AUTH_SCHEME', 'Bearer').strip()
    token = os.environ.get('CONFLUENCE_TOKEN', '').strip()
    value = f'{scheme} {token}' if scheme else token
    return header_name, value


def _request_headers() -> dict:
    """이번 요청에 실을 헤더 전체(Accept + 인증 + 사내 게이트웨이 추가 헤더)."""
    headers = dict(_extra_headers())
    auth_name, auth_value = _auth_header()
    headers[auth_name] = auth_value
    # Accept: application/json (2026-09-22, 사용자 확인) — 게이트웨이가 낸
    # 401 fault 응답이 JSON이 아니라 XML(<status><status-code>...)이었는데,
    # 클라이언트가 원하는 응답 형식을 명시하지 않으면 게이트웨이가 기본값
    # (XML)으로 응답하는 경우가 흔하다. 인증 실패 자체를 고치는 건 아니지만
    # 최소한 에러 응답이라도 일관되게 JSON으로 받기 위해 명시한다.
    headers.setdefault('Accept', 'application/json')
    # User-Agent (2026-09-22, 사용자 확인) — 동일한 URL/인증 헤더로도 curl은
    # 200이 오는데 requests는 "Remote end closed connection without
    # response"(연결이 응답 없이 끊김)로 실패 — WAF/게이트웨이가 클라이언트를
    # User-Agent로 구분해 requests의 기본값("python-requests/x.y.z", 스크립트로
    # 식별되기 쉬움)을 차단하고 curl의 기본값("curl/x.y.z")은 통과시키는
    # 경우가 흔하다. CONFLUENCE_USER_AGENT로 다른 값을 쓸 수도 있게 하되,
    # 기본값은 curl 스타일로 맞춘다.
    headers.setdefault('User-Agent', os.environ.get('CONFLUENCE_USER_AGENT', '').strip() or 'curl/8.0.0')
    return headers


def _get_session():
    """헤더가 이미 채워진 requests.Session(연결 재사용용, 프로세스당 1개로 캐시)."""
    session = _client_cache.get('session')
    if session is None:
        import requests
        session = requests.Session()
        session.headers.update(_request_headers())
        _client_cache['session'] = session
    return session


def fetch_page_text(confl_address: str) -> str:
    """confl_address 페이지의 제목+본문을 텍스트로 반환. 실패 시 ConfluenceError.

    2026-09-22 — atlassian-python-api(get_page_by_id/get_page_by_title)를
    거치지 않고 requests로 REST API를 직접 호출하도록 변경했다. 사용자가
    curl로 직접 만든 요청(정확히 동일한 URL/헤더)은 200이 오는데 이
    라이브러리를 거친 호출만 계속 401(HTTPError)이 나는 문제가 있었고,
    라이브러리 내부에서 세션 헤더를 요청 시점에 다시 만지는지 이 저장소
    환경에서는 확인할 수 없어(atlassian 패키지가 개발 샌드박스에 설치돼
    있지 않음) — 라이브러리 내부 동작에 기대지 않고 사용자가 검증한 curl과
    한 글자도 다르지 않은 요청을 직접 만드는 쪽으로 바꿔 이 불확실성을
    아예 없앴다."""
    if not confl_address:
        raise ConfluenceError('컨플루언스 주소가 비어 있습니다.')
    if not os.environ.get('CONFLUENCE_TOKEN', '').strip():
        raise ConfluenceError(
            '.env에 CONFLUENCE_TOKEN이 설정되어 있지 않습니다. '
            '.env.example을 참고해 설정하세요.'
        )

    base_url = _base_url(confl_address)
    session = _get_session()
    page_id = extract_page_id(confl_address)

    try:
        if page_id:
            url = f'{base_url}/rest/api/content/{page_id}'
            params = {'expand': 'body.storage,title'}
        else:
            space, title = extract_space_title(confl_address)
            if not space:
                raise ConfluenceError(f'컨플루언스 주소에서 페이지를 특정하지 못했습니다: {confl_address}')
            url = f'{base_url}/rest/api/content'
            params = {'spaceKey': space, 'title': title, 'expand': 'body.storage,title'}
        resp = session.get(url, params=params, timeout=30)
    except ConfluenceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConfluenceError(f'페이지 조회 실패({confl_address}): {type(exc).__name__}: {exc}') from exc

    if resp.status_code != 200:
        raise ConfluenceError(f'페이지 조회 실패({confl_address}): HTTP {resp.status_code}: {resp.text[:300]}')

    try:
        data = resp.json()
    except ValueError as exc:
        raise ConfluenceError(f'페이지 조회 실패({confl_address}): JSON 응답이 아닙니다: {resp.text[:300]}') from exc

    if page_id:
        page = data
    else:
        # /rest/api/content?spaceKey=...&title=...는 검색형 엔드포인트라
        # {"results": [...]} 형태로 온다 — 첫 결과를 그 페이지로 본다.
        results = data.get('results') or []
        page = results[0] if results else None

    if not page:
        raise ConfluenceError(f'페이지를 찾을 수 없습니다: {confl_address}')

    title = page.get('title', '')
    body_html = page.get('body', {}).get('storage', {}).get('value', '')
    body_text = _html_to_text(body_html)
    return f'{title}\n\n{body_text}'.strip()
