"""
사내 Confluence 페이지 조회 공용 유틸리티 (atlassian-python-api, PAT 인증)

data/processed/project_confl_address.csv의 confl_address(컨플루언스 페이지 URL)
에서 base URL과 페이지 ID를 그때그때 추출해 페이지 본문을 가져온다. 별도의
고정 CONFLUENCE_BASE_URL 설정 없이, 각 행의 실제 URL을 그대로 사용한다.

인증: .env의 CONFLUENCE_TOKEN(개인 액세스 토큰, PAT) 사용.
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


def _get_client(base_url: str):
    client = _client_cache.get(base_url)
    if client is None:
        from atlassian import Confluence
        client = Confluence(url=base_url, token=os.environ.get('CONFLUENCE_TOKEN', ''))
        _client_cache[base_url] = client
    return client


def fetch_page_text(confl_address: str) -> str:
    """confl_address 페이지의 제목+본문을 텍스트로 반환. 실패 시 ConfluenceError."""
    if not confl_address:
        raise ConfluenceError('컨플루언스 주소가 비어 있습니다.')
    if not os.environ.get('CONFLUENCE_TOKEN', '').strip():
        raise ConfluenceError(
            '.env에 CONFLUENCE_TOKEN이 설정되어 있지 않습니다. '
            '.env.example을 참고해 설정하세요.'
        )

    client = _get_client(_base_url(confl_address))
    page_id = extract_page_id(confl_address)
    try:
        if page_id:
            page = client.get_page_by_id(page_id, expand='body.storage,title')
        else:
            space, title = extract_space_title(confl_address)
            if not space:
                raise ConfluenceError(f'컨플루언스 주소에서 페이지를 특정하지 못했습니다: {confl_address}')
            page = client.get_page_by_title(space, title, expand='body.storage,title')
    except ConfluenceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConfluenceError(f'페이지 조회 실패({confl_address}): {type(exc).__name__}: {exc}') from exc

    if not page:
        raise ConfluenceError(f'페이지를 찾을 수 없습니다: {confl_address}')

    title = page.get('title', '')
    body_html = page.get('body', {}).get('storage', {}).get('value', '')
    body_text = _html_to_text(body_html)
    return f'{title}\n\n{body_text}'.strip()
