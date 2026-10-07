"""
사내 Confluence 페이지 조회 공용 유틸리티 (requests 직접 호출, PAT/게이트웨이 인증)

data/processed/project_confl_address.csv의 confl_address에서 base URL과
페이지 ID를 그때그때 추출해 페이지 본문을 가져온다. confl_address는 두 형식을
지원한다.
  1) 페이지 ID 숫자만(예: "1234123456") — 2026-09-22 추가, 사용자 확정.
     게이트웨이 경유가 기본이 된 뒤로는 전체 URL을 넣을 필요 없이 페이지
     ID만 넣으면 된다(CONFLUENCE_GATEWAY_BASE_URL이 반드시 설정돼 있어야
     함 — 호스트 정보가 없어 이 값이 유일한 신뢰 경계가 된다).
  2) 기존처럼 전체 컨플루언스 페이지 URL(하위 호환, CONFLUENCE_ALLOWED_HOSTS
     로 호스트를 검증) — 이미 이 형식으로 채워진 데이터도 계속 동작한다.

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
import threading
import time
from urllib.parse import urlparse

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from services.db import load_env_file  # noqa: E402

load_env_file()

_client_cache: dict = {}


class ConfluenceError(RuntimeError):
    """Confluence 조회 실패(미설정/인증오류/페이지 없음 등)를 알리는 예외.
    HTTP 응답 오류면 status_code에 그 코드를 담는다(없으면 None)."""

    def __init__(self, message: str = '', status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# ── 호출 빈도 제한(2026-10) ──────────────────────────────────────────────────
# 사내 게이트웨이가 분당 호출 수를 제한해 초과 시 HTTP 429("rate limit exceeded")를
# 돌려준다(실측 한도 분당 15회) — 여유를 둬 기본 분당 10회로 호출 간격을 벌린다
# (CONFLUENCE_MAX_CALLS_PER_MINUTE, 0 이하면 제한 끄기). 프로세스 안에서만 공유되는
# 제한이라, 다른 프로세스(예: 파이프라인과 웹 화면)가 동시에 호출하면 합산은 이를 넘을
# 수 있다 — 429를 받으면 Retry-After(없으면 60초)만큼 쉬었다 다시 시도한다.
_rate_lock = threading.Lock()
_last_call_at = 0.0
_RATE_LIMIT_RETRIES = 3
_MAX_SLEEP_CHUNK = 30.0   # 한 번에 오래 자지 않고 쪼개 자야 진행 표시(heartbeat)가 끊기지 않는다


def _min_interval() -> float:
    try:
        per_minute = float(os.environ.get('CONFLUENCE_MAX_CALLS_PER_MINUTE', '10'))
    except ValueError:
        per_minute = 10.0
    return 60.0 / per_minute if per_minute > 0 else 0.0


def _throttle(on_wait=None) -> None:
    """직전 호출로부터 최소 간격(분당 N회 → 60/N초)이 지나도록 기다린 뒤 이번 호출 시각을
    기록한다. on_wait(남은_초)가 있으면 쉬는 동안 주기적으로 불러 준다."""
    global _last_call_at
    interval = _min_interval()
    if interval <= 0:
        return
    with _rate_lock:
        wait = _last_call_at + interval - time.monotonic()
        while wait > 0:
            if on_wait:
                on_wait(wait)
            time.sleep(min(wait, _MAX_SLEEP_CHUNK))
            wait = _last_call_at + interval - time.monotonic()
        _last_call_at = time.monotonic()


def _sleep_for_rate_limit(resp, on_wait=None) -> None:
    try:
        wait = float(resp.headers.get('Retry-After', '')) if getattr(resp, 'headers', None) else 60.0
    except (TypeError, ValueError):
        wait = 60.0
    wait = max(1.0, min(wait, 120.0))
    end = time.monotonic() + wait
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return
        if on_wait:
            on_wait(left)
        time.sleep(min(left, _MAX_SLEEP_CHUNK))


def normalize_address(confl_address: str) -> str:
    """화면/로그 표시용 정리 — 페이지 ID(소수부 .0 포함)면 정수 문자열로, 그 외(URL
    등)는 앞뒤 공백만 제거해 반환한다(2026-10)."""
    text = (confl_address or '').strip()
    return _bare_page_id(text) or text


def _is_bare_page_id(confl_address: str) -> bool:
    """confl_address가 전체 URL이 아니라 페이지 ID 숫자만 있는지(2026-09-22
    추가 — 사용자 확정, 게이트웨이 경유가 기본이 되면서 project_confl_
    address.csv에 굳이 전체 URL을 넣을 필요 없이 페이지 ID만 넣는 방식으로
    단순화). 앞뒤 공백만 제거하고 순수 숫자로만 되어 있으면 페이지 ID로 본다."""
    return _bare_page_id(confl_address) is not None


_BARE_ID_RE = re.compile(r'^(\d+)(?:\.0+)?$')


def _bare_page_id(confl_address: str) -> str | None:
    """페이지 ID만 있는 값이면 그 숫자 문자열을, 아니면 None. 엑셀 숫자 셀이
    실수로 읽혀 '3957970224.0'처럼 ".0"이 붙어 들어온 경우도 같은 ID로 본다
    (2026-10 — 이 값이 전체 URL로 오인돼 "Confluence 주소는 HTTPS만 허용됩니다"가
    나던 문제, CONFLUENCE_ALLOW_HTTP와 무관)."""
    m = _BARE_ID_RE.match((confl_address or '').strip())
    return m.group(1) if m else None


def _validate_https(url: str, allow_http: bool, label: str) -> None:
    scheme = urlparse(url).scheme
    if scheme != 'https' and not (allow_http and scheme == 'http'):
        raise ConfluenceError(f'{label}은(는) HTTPS만 허용됩니다(현재: {url}).')


def _base_url(confl_address: str) -> str:
    allow_http = os.environ.get('CONFLUENCE_ALLOW_HTTP', 'false').lower() in ('1', 'true', 'yes', 'on')

    if _is_bare_page_id(confl_address):
        # 페이지 ID만 있으면 호스트 정보 자체가 없어 CONFLUENCE_ALLOWED_HOSTS
        # 검증을 적용할 대상이 없다 — 대신 CONFLUENCE_GATEWAY_BASE_URL이
        # 반드시 설정돼 있어야 한다(관리자만 바꿀 수 있는 값이라 이게 신뢰
        # 경계 역할을 한다).
        gateway_base_url = os.environ.get('CONFLUENCE_GATEWAY_BASE_URL', '').strip().rstrip('/')
        if not gateway_base_url:
            raise ConfluenceError(
                'confl_address가 페이지 ID만 있는 형식인데 CONFLUENCE_GATEWAY_BASE_URL이 '
                '설정되어 있지 않습니다 — 이 형식은 게이트웨이 경유가 전제입니다.'
            )
        _validate_https(gateway_base_url, allow_http, 'CONFLUENCE_GATEWAY_BASE_URL')
        return gateway_base_url

    parsed = urlparse(confl_address)
    host = (parsed.hostname or '').lower().rstrip('.')
    allowed = [h.strip().lower().lstrip('.') for h in
               os.environ.get('CONFLUENCE_ALLOWED_HOSTS', 'samsungds.net,samsung.net').split(',')
               if h.strip()]
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
        _validate_https(gateway_base_url, allow_http, 'CONFLUENCE_GATEWAY_BASE_URL')
        return gateway_base_url
    return f'{parsed.scheme}://{parsed.netloc}'


def extract_page_id(confl_address: str) -> str | None:
    """다양한 Confluence URL 형식에서 pageId를 추출한다.
      - 페이지 ID 숫자만 있는 경우(2026-09-22 추가) — 그대로 반환
      - .../pages/viewpage.action?pageId=123456
      - .../wiki/spaces/{SPACE}/pages/123456/{title}
      - .../pages/123456
    URL 형식이 다르면 이 함수의 정규식을 실제 형식에 맞게 수정하세요.
    """
    bare = _bare_page_id(confl_address)
    if bare:
        return bare
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
        resp = _throttled_get(session, url, params)
    except ConfluenceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConfluenceError(f'페이지 조회 실패({confl_address}): {type(exc).__name__}: {exc}') from exc

    if resp.status_code != 200:
        raise ConfluenceError(f'페이지 조회 실패({confl_address}): HTTP {resp.status_code}: {resp.text[:300]}',
                              resp.status_code)

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



# ── 하위 페이지 목록 추출(2026-10, 사용자 요청) ───────────────────────────────
# 특정 상위 페이지 아래 모든 하위 페이지(자식 → 손자 → … 최하위)의 제목/페이지 ID를
# 뽑는다 — 과제별컨플의 컨플 주소(10자리 페이지 ID)를 일일이 확인하지 않아도 되게.
# 표준 REST: GET /rest/api/content/{id}/child/page?limit=&start= (페이지 단위
# 페이징). fetch_page_text()와 같은 게이트웨이/헤더/세션을 쓴다.
_CHILD_PAGE_LIMIT = 100


def _throttled_get(session, url: str, params: dict | None = None, on_wait=None):
    """호출 간격을 지켜 GET하고, 429(rate limit)면 Retry-After만큼 쉬었다 최대
    _RATE_LIMIT_RETRIES번 다시 시도한다. 마지막 응답 객체를 그대로 반환."""
    resp = None
    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        _throttle(on_wait)
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code != 429 or attempt == _RATE_LIMIT_RETRIES:
            return resp
        _sleep_for_rate_limit(resp, on_wait)
    return resp


def _get_json(session, url: str, params: dict | None = None, on_wait=None) -> dict:
    try:
        resp = _throttled_get(session, url, params, on_wait)
    except Exception as exc:  # noqa: BLE001
        raise ConfluenceError(f'요청 실패({url}): {type(exc).__name__}: {exc}') from exc
    if resp.status_code != 200:
        raise ConfluenceError(f'요청 실패({url}): HTTP {resp.status_code}: {resp.text[:300]}', resp.status_code)
    try:
        return resp.json()
    except ValueError as exc:
        raise ConfluenceError(f'JSON 응답이 아닙니다({url}): {resp.text[:300]}') from exc


def list_child_pages(page_id: str, session=None, base_url: str | None = None, on_wait=None) -> list[dict]:
    """page_id의 직계 하위 페이지 [{'id', 'title'}, ...] (페이징을 끝까지 따라감)."""
    session = session or _get_session()
    base_url = base_url or _base_url(page_id)
    out, start = [], 0
    while True:
        data = _get_json(session, f'{base_url}/rest/api/content/{page_id}/child/page',
                         {'limit': _CHILD_PAGE_LIMIT, 'start': start}, on_wait)
        results = data.get('results') or []
        out.extend({'id': str(r.get('id', '')), 'title': str(r.get('title', ''))} for r in results)
        if len(results) < _CHILD_PAGE_LIMIT:
            return out
        start += len(results)


class _NeedFallback(Exception):
    """descendant/page(한 번에 전체 하위 조회)를 쓸 수 없어 child/page 재귀로 바꿔야 함."""


_DESC_LIMIT = 100
_FALLBACK_STATUS = {400, 404, 405, 501}


def _collect_via_descendants(session, base_url, root_id, root_title, max_depth, max_pages, progress, on_wait):
    """GET /rest/api/content/{root}/descendant/page?expand=ancestors — 하위 전체를 100개씩
    평면 목록으로 받아(호출 수 ≈ 페이지 수/100 — 분당 호출 제한에 훨씬 유리) ancestors로
    트리를 복원한다. 응답에 ancestors가 없거나 루트가 그 안에 없으면 _NeedFallback."""
    items, start = [], 0
    while True:
        data = _get_json(session, f'{base_url}/rest/api/content/{root_id}/descendant/page',
                         {'limit': _DESC_LIMIT, 'start': start, 'expand': 'ancestors'}, on_wait)
        results = data.get('results') or []
        items.extend(results)
        if progress and results:
            progress(len(items) + 1, str(results[-1].get('title', '')))
        if len(items) + 1 > max_pages:
            raise ConfluenceError(f'하위 페이지가 {max_pages}개를 넘어 중단했습니다 — 더 아래 단계의 페이지를 지정하세요.')
        if len(results) < _DESC_LIMIT:
            break
        start += len(results)

    titles = {root_id: root_title}
    kids: dict = {root_id: []}
    parent_of, depth_of = {}, {}
    for r in items:
        pid = str(r.get('id', ''))
        ancestors = r.get('ancestors')
        if not pid or ancestors is None:
            raise _NeedFallback()
        chain = [str(x.get('id', '')) for x in ancestors]
        if root_id not in chain:
            raise _NeedFallback()
        titles[pid] = str(r.get('title', ''))
        parent_of[pid] = chain[-1]
        depth_of[pid] = len(chain) - chain.index(root_id)
        kids.setdefault(pid, [])
    for pid, parent in parent_of.items():
        if parent not in kids:          # 부모가 목록에 없음 — 구조를 복원할 수 없다
            raise _NeedFallback()
        kids[parent].append(pid)

    rows: list[dict] = []

    def _walk(pid, parent_id, path, depth):
        if pid != root_id and max_depth is not None and depth > max_depth:
            return
        title = titles[pid]
        full = f'{path} > {title}' if path else title
        rows.append({'depth': depth, 'id': pid, 'title': title, 'parent_id': parent_id,
                     'parent_title': titles.get(parent_id, ''), 'path': full})
        for child in kids.get(pid, []):
            _walk(child, pid, full, depth + 1)

    _walk(root_id, '', '', 0)
    return rows


def crawl_descendants(root_address: str, max_depth: int | None = None, max_pages: int = 5000,
                      progress=None, on_wait=None) -> list[dict]:
    """root_address(페이지 ID 또는 URL) 아래 모든 하위 페이지를 깊이 우선(문서 순서)으로
    수집한다. 반환 행: {depth(루트=0), id, title, parent_id, parent_title, path}.
    max_depth=None이면 최하위까지, max_pages를 넘으면 ConfluenceError(폭주 방지).
    progress(count, last_title)가 있으면 수집 중 호출한다. on_wait(남은_초)는 호출 제한
    때문에 쉬는 동안 불린다.

    호출 수를 줄이려고 먼저 descendant/page(한 번에 하위 전체)를 시도하고, 그 엔드포인트가
    없거나(400/404/405/501) 응답에 ancestors가 없으면 child/page를 페이지마다 재귀 호출하는
    방식으로 바꾼다. 어느 쪽이든 모든 호출은 분당 호출 제한(_throttle)을 지킨다."""
    if not os.environ.get('CONFLUENCE_TOKEN', '').strip():
        raise ConfluenceError('.env에 CONFLUENCE_TOKEN이 설정되어 있지 않습니다.')
    root_id = extract_page_id(root_address or '')
    if not root_id:
        raise ConfluenceError('상위 페이지의 페이지 ID(숫자) 또는 pageId가 들어 있는 주소를 입력하세요.')

    base_url = _base_url(root_address)
    session = _get_session()
    root = _get_json(session, f'{base_url}/rest/api/content/{root_id}', None, on_wait)
    root_title = str(root.get('title', ''))
    if progress:
        progress(1, root_title)

    try:
        return _collect_via_descendants(session, base_url, root_id, root_title, max_depth, max_pages,
                                        progress, on_wait)
    except _NeedFallback:
        pass
    except ConfluenceError as exc:
        if exc.status_code not in _FALLBACK_STATUS:
            raise

    rows: list[dict] = []
    seen = {root_id}

    def _add(page_id, title, depth, parent_id, parent_title, parent_path):
        path = f'{parent_path} > {title}' if parent_path else title
        rows.append({'depth': depth, 'id': page_id, 'title': title, 'parent_id': parent_id,
                     'parent_title': parent_title, 'path': path})
        if progress:
            progress(len(rows), title)
        if len(rows) > max_pages:
            raise ConfluenceError(f'하위 페이지가 {max_pages}개를 넘어 중단했습니다 — 더 아래 단계의 페이지를 지정하세요.')
        return path

    def _walk(page_id, title, depth, path):
        if max_depth is not None and depth >= max_depth:
            return
        for child in list_child_pages(page_id, session, base_url, on_wait):
            if child['id'] in seen:
                continue
            seen.add(child['id'])
            child_path = _add(child['id'], child['title'], depth + 1, page_id, title, path)
            _walk(child['id'], child['title'], depth + 1, child_path)

    root_path = _add(root_id, root_title, 0, '', '', '')
    _walk(root_id, root_title, 0, root_path)
    return rows
