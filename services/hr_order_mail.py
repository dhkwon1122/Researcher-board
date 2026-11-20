"""
업무 시나리오 > 인사발령 — 부서별 담당자에게 인사발령 작성 양식(첨부파일)을 메일로 보낸다(2026-11-19).

사용자 확정 흐름: 시스템 안에서 발령 내용을 입력받는 대신, 화면에서 양식 파일을 올리면 선택한 부서 담당자들에게
같은 첨부로 한 명씩 메일을 보낸다(매월 1일·16일 발령 취합용).

- 발신 계정: 로그인한 본인 또는 팀 공용 계정(.env MAIL_FROM, 비실명)만(2026-11-19 개정). 토큰·시스템 ID는 공용,
  본인이면 발신 주소와 ?userId=를 그 계정으로(pipeline/mailer.send_html_email).
- 메일 문구: 담당자가 평소 쓰는 제목·본문을 그대로 템플릿으로 저장하고, {발령일}/{회신일} 등 자리표시자를 발령일에
  맞춰 바꿔 넣는다. 회신일 = 발령일의 워킹데이 4일 전(예: 12.16 → 12.10).
- 워킹데이: 토·일, 공휴일(holidays 패키지 KR — 대체공휴일·설·추석 포함), 관리자가 넣은 회사 휴무일 제외.
- 본문 서식(2026-11-20): 본문은 HTML(화면의 서식 편집기 — 글꼴·크기·굵게·밑줄·글자색·바탕색 등). 저장·발송 전에
  sanitize_html로 허용한 태그·스타일만 남긴다(스크립트·이벤트 속성·url() 등 제거). 예전 텍스트 템플릿은 읽을 때 HTML로 바꿈.
- 참조(CC)·비밀참조(BCC)(2026-11-20): 받는 부서 담당자(TO)와 별도로, 인력현황에서 고른 동료를 참조/비밀참조로
  넣는다. 화면에서 저장해 두면 수동·자동 발송 모두에 쓴다. 발송 방식은 "담당자별 따로"(기본 — 참조인은 담당자 수만큼
  받음) 또는 "한 통으로"(담당자 전원 TO + 참조인 한 번) 중 선택.
- 자동 발송: 켜 두면 서버가 발령일(1일·16일)의 워킹데이 7일 전 지정 시각에 담당자 전체에게 저장된 템플릿·첨부로
  보낸다(발령일당 한 번 — 발송 기록 파일로 중복 방지, gunicorn 워커 2개라 파일 잠금으로 한 곳에서만).

저장(data/processed): hr_order_contacts.json(부서별 담당자), hr_order_settings.json(허용 역할·템플릿·자동 발송·휴무일·참조인),
hr_order_files/(자동 발송용 첨부), hr_order_auto_sent.json(자동 발송 기록), hr_order_log.jsonl(발송 이력 — 첨부 내용 제외).
"""
from __future__ import annotations

import fcntl
import html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

from services import data_store

CONTACTS_PATH = os.path.join(data_store.DATA_DIR, 'hr_order_contacts.json')
SETTINGS_PATH = os.path.join(data_store.DATA_DIR, 'hr_order_settings.json')
LOG_PATH = os.path.join(data_store.DATA_DIR, 'hr_order_log.jsonl')
FILES_DIR = os.path.join(data_store.DATA_DIR, 'hr_order_files')
AUTO_SENT_PATH = os.path.join(data_store.DATA_DIR, 'hr_order_auto_sent.json')
AUTO_LOCK_PATH = os.path.join(data_store.DATA_DIR, '.hr_order_auto.lock')
MAX_TOTAL_BYTES = 20 * 1024 * 1024        # 첨부 합계 상한(메일 서버 제한 대비)
SHARED_SENDER = '__shared__'              # 발신 계정 선택값: .env의 팀 공용 계정
REPLY_WORKDAYS = 4                        # 회신일 기본값 = 발령일의 워킹데이 4일 전(화면에서 변경 — reply_workdays())
AUTO_SEND_WORKDAYS = 7                    # 자동 발송 기본값 = 발령일의 워킹데이 7일 전(화면에서 변경 — send_workdays())
MAX_WORKDAYS = 20
DEFAULT_AUTO_HOUR = 9
_LOCK = threading.Lock()

DEFAULT_SUBJECT = '[인사발령] {발령일}자 발령 대상 작성 요청'
DEFAULT_BODY = ('안녕하세요.\n\n{발령일_월일}자 인사발령(부서이동·파트이동 등) 대상을 취합합니다.\n'
                '첨부한 양식에 부서 내 발령 대상자를 작성하여 {회신일_월일}까지 회신 부탁드립니다.\n'
                '해당 인원이 없는 경우에도 "해당 없음"으로 회신해 주세요.\n\n감사합니다.')


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _settings() -> dict:
    data = _read_json(SETTINGS_PATH, {})
    return data if isinstance(data, dict) else {}


def _update_settings(**fields) -> dict:
    with _LOCK:
        data = _settings()
        data.update(fields)
        _write_json(SETTINGS_PATH, data)
    return data


# ── 사용 권한: 관리자 + 관리자가 허용한 역할 ──────────────────────────────────

def allowed_roles() -> list:
    return list(_settings().get('roles') or [])


def set_allowed_roles(roles: list) -> list:
    from services.auth import can
    if not can('manage_users'):
        raise PermissionError('관리자만 바꿀 수 있습니다.')
    from config.auth_config import ROLE_LABELS
    roles = [r for r in dict.fromkeys(roles or []) if r in ROLE_LABELS]
    _update_settings(roles=roles)
    return roles


def can_use() -> bool:
    from services.auth import can, get_current_user
    user = get_current_user()
    if not user:
        return False
    return can('manage_users') or user.get('role') in allowed_roles()


def _require_use() -> None:
    if not can_use():
        raise PermissionError('인사발령 메뉴 권한이 없습니다.')


# ── 워킹데이 ────────────────────────────────────────────────────────────────

def company_holidays() -> list:
    return sorted(set(_settings().get('holidays') or []))


def set_company_holidays(text: str) -> list:
    """회사 휴무일(공휴일 외, 예: 창립기념일) — 줄/쉼표로 구분한 YYYY-MM-DD. 형식이 틀리면 ValueError."""
    _require_use()
    days = []
    for tok in re.split(r'[\s,]+', text or ''):
        if not tok:
            continue
        try:
            days.append(date.fromisoformat(tok).isoformat())
        except ValueError as exc:
            raise ValueError(f'날짜 형식이 아닙니다: {tok} (예: 2026-11-02)') from exc
    days = sorted(set(days))
    _update_settings(holidays=days)
    return days


def _public_holidays(years) -> set:
    try:
        import holidays as _h
    except ImportError:            # 패키지가 없으면 주말·회사 휴무일만 제외(화면에 안내)
        return set()
    return set(_h.KR(years=list(years)).keys())


def holidays_available() -> bool:
    try:
        import holidays  # noqa: F401 — 설치 여부만 확인
        return True
    except ImportError:
        return False


def is_workday(d: date, _cache: dict | None = None) -> bool:
    if d.weekday() >= 5:
        return False
    cache = _cache if _cache is not None else {}
    if 'days' not in cache:
        cache['days'] = _public_holidays(range(d.year - 1, d.year + 2)) | {
            date.fromisoformat(s) for s in company_holidays()}
    return d not in cache['days']


def workdays_before(d: date, n: int) -> date:
    """d의 워킹데이 n일 전(d 당일은 세지 않음). 예: 2026-12-16(수), 4 → 2026-12-10(목)."""
    cache: dict = {}
    cur, left = d, n
    while left:
        cur -= timedelta(days=1)
        if is_workday(cur, cache):
            left -= 1
    return cur


def next_order_date(today: date | None = None) -> date:
    """다음 발령일(매월 1일·16일 중 오늘 이후 가장 가까운 날)."""
    today = today or date.today()
    if today.day < 16:
        return today.replace(day=16)
    return (today.replace(day=1) + timedelta(days=32)).replace(day=1)


def _days_setting() -> dict:
    return _settings().get('days') or {}


def send_workdays() -> int:
    """자동 발송 시점 — 발령일의 워킹데이 며칠 전(2026-11-20부터 화면에서 설정, 기본 7)."""
    return int(_days_setting().get('send', AUTO_SEND_WORKDAYS))


def reply_workdays() -> int:
    """회신 기한 — 발령일의 워킹데이 며칠 전(기본 4). 수동 발송의 {회신일}에도 같이 쓰임."""
    return int(_days_setting().get('reply', REPLY_WORKDAYS))


def set_workdays(send: int, reply: int) -> tuple[int, int]:
    _require_use()
    try:
        send, reply = int(send), int(reply)
    except (TypeError, ValueError):
        raise ValueError('발송일·회신 기한을 숫자로 고르세요.') from None
    if not 1 <= reply < send <= MAX_WORKDAYS:
        raise ValueError(f'발송은 회신 기한보다 앞서야 합니다(1 ≤ 회신 기한 < 발송 ≤ {MAX_WORKDAYS} 워킹데이 전).')
    _update_settings(days={'send': send, 'reply': reply})
    return send, reply


def reply_due(order_date: date) -> date:
    return workdays_before(order_date, reply_workdays())


def auto_send_date(order_date: date) -> date:
    return workdays_before(order_date, send_workdays())


# ── 템플릿(담당자가 평소 쓰는 제목·본문 + 자리표시자) ─────────────────────────

_WD = '월화수목금토일'
PLACEHOLDERS = ('{발령일}', '{발령일_월일}', '{회신일}', '{회신일_월일}')


def _md(d: date) -> str:
    return f'{d.month}월 {d.day}일({_WD[d.weekday()]})'


def placeholder_values(order_date: date) -> dict:
    due = reply_due(order_date)
    return {'발령일': f'{order_date:%Y.%m.%d}', '발령일_월일': _md(order_date),
            '회신일': f'{due:%Y.%m.%d}', '회신일_월일': _md(due)}


def render(text: str, order_date: date) -> str:
    """{발령일}·{발령일_월일}·{회신일}·{회신일_월일}만 바꾼다(다른 중괄호는 그대로)."""
    out = text or ''
    for k, v in placeholder_values(order_date).items():
        out = out.replace('{' + k + '}', v)
    return out


def text_to_html(text: str) -> str:
    """예전 텍스트 본문 → HTML(이스케이프 + 줄바꿈 <br>)."""
    return html.escape(text or '', quote=False).replace('\n', '<br>')


def template() -> tuple[str, str]:
    """(제목, 본문 HTML). 2026-11-20 이전에 저장된 텍스트 본문은 HTML로 바꿔 돌려준다."""
    t = _settings().get('template') or {}
    body = t.get('body') or ''
    if not body:
        body = text_to_html(DEFAULT_BODY)
    elif t.get('format') != 'html':
        body = text_to_html(body)
    return t.get('subject') or DEFAULT_SUBJECT, body


def _plain(body_html_text: str) -> str:
    return re.sub(r'<[^>]+>', '', body_html_text or '').replace('&nbsp;', ' ').strip()


def save_template(subject: str, body: str) -> None:
    """body는 서식 편집기의 HTML — 허용한 서식만 남겨 저장."""
    _require_use()
    body = sanitize_html(body)
    if not (subject or '').strip() or not _plain(body):
        raise ValueError('제목과 본문을 입력하세요.')
    _update_settings(template={'subject': subject.strip(), 'body': body, 'format': 'html'})


# 본문 서식 허용 목록 — 메일 본문에 필요한 글자 서식·문단·목록·링크만. 나머지 태그는 글자만 남기고, 스크립트류는 내용째 버림.
_ALLOWED_TAGS = {'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'del', 'sub', 'sup', 'br', 'hr', 'p', 'div', 'span',
                 'font', 'ul', 'ol', 'li', 'blockquote', 'a', 'h1', 'h2', 'h3', 'h4', 'table', 'thead', 'tbody', 'tr',
                 'td', 'th', 'center'}
_VOID_TAGS = {'br', 'hr'}
_DROP_WITH_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'head', 'title', 'svg', 'math', 'template',
                      'noscript', 'textarea', 'select', 'button', 'form', 'xml'}
_ALLOWED_CSS = {'color', 'background-color', 'background', 'font-family', 'font-size', 'font-weight', 'font-style',
                'text-decoration', 'text-decoration-line', 'text-align', 'margin-left', 'padding-left', 'line-height',
                'border', 'border-collapse', 'padding', 'width', 'vertical-align'}
_CSS_VALUE_RE = re.compile(r"""^[\w\s#,.'"%()+-]*$""")
_CSS_BANNED = ('url(', 'expression', 'javascript', 'behavior', '@import', '\\')


def _clean_style(style: str) -> str:
    out = []
    for decl in (style or '').split(';'):
        if ':' not in decl:
            continue
        prop, val = decl.split(':', 1)
        prop, val = prop.strip().lower(), val.strip()
        low = val.lower()
        if prop in _ALLOWED_CSS and val and _CSS_VALUE_RE.match(val) and not any(b in low for b in _CSS_BANNED):
            out.append(f'{prop}: {val}')
    return '; '.join(out)


def _clean_attrs(tag: str, attrs: list) -> str:
    keep = []
    for name, value in attrs:
        name, value = (name or '').lower(), value or ''
        if name == 'style':
            value = _clean_style(value)
        elif tag == 'font' and name == 'color':
            if not re.fullmatch(r'#?[\w]{1,20}', value):
                continue
        elif tag == 'font' and name == 'face':
            if not re.fullmatch(r"""[\w\s,'"-]{1,80}""", value):
                continue
        elif tag == 'font' and name == 'size':
            if not re.fullmatch(r'[1-7]', value):
                continue
        elif tag == 'a' and name == 'href':
            if not re.match(r'(https?:|mailto:)', value.strip(), re.I):
                continue
        elif tag in ('td', 'th') and name in ('colspan', 'rowspan'):
            if not value.isdigit():
                continue
        elif name == 'align' and value.lower() in ('left', 'center', 'right', 'justify'):
            pass
        else:
            continue
        if value:
            keep.append(f' {name}="{html.escape(value, quote=True)}"')
    if tag == 'a' and any(k.startswith(' href=') for k in keep):
        keep.append(' target="_blank" rel="noopener"')
    return ''.join(keep)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_WITH_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in _ALLOWED_TAGS:
            return
        self.out.append(f'<{tag}{_clean_attrs(tag, attrs)}>')
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in _VOID_TAGS and not self.skip:
            self.out.append(f'<{tag}>')

    def handle_endtag(self, tag):
        if tag in _DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f'</{t}>')
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        return ''.join(self.out) + ''.join(f'</{t}>' for t in reversed(self.stack))


def sanitize_html(text: str) -> str:
    """서식 편집기·붙여넣기 HTML에서 허용한 태그·속성·스타일만 남긴다(메일 본문·미리보기 공용)."""
    p = _Sanitizer()
    p.feed(re.sub(r'<!--.*?-->', '', text or '', flags=re.S))
    p.close()
    return p.result()


def body_html(body: str) -> str:
    """본문 HTML(서식 편집기)을 정리해 기본 글꼴(맑은 고딕 14px)로 감싼다."""
    return ('<div style="font-family:\'Malgun Gothic\',sans-serif;font-size:14px;line-height:1.7">'
            + sanitize_html(body) + '</div>')


# ── 부서별 담당자 표 ────────────────────────────────────────────────────────

def load_contacts(path: str | None = None) -> list:
    """부서별 담당자. path를 주면 그 파일(업무분장은 자기 명단 — services/work_assign.CONTACTS_PATH, 2026-11-20 분리)."""
    return [c for c in _read_json(path or CONTACTS_PATH, []) if isinstance(c, dict)]


def _clean_contacts(rows: list) -> tuple[list, list]:
    """빈 행은 버리고, 이메일 형식이 틀린 행은 오류로 돌려준다. 반환: (정리된 행, 오류 문구)."""
    out, errors, seen = [], [], set()
    for i, r in enumerate(rows or [], 1):
        dept = str(r.get('dept') or '').strip()
        name = str(r.get('name') or '').strip()
        email = str(r.get('email') or '').strip()
        if not (dept or name or email):
            continue
        if not dept or not email:
            errors.append(f'{i}번째 행: 부서와 이메일은 필수입니다.')
            continue
        if '@' not in email or ' ' in email:
            errors.append(f'{i}번째 행: 이메일 형식이 아닙니다({email}).')
            continue
        key = (dept, email.lower())          # 겸직(2026-11-20): 같은 이메일이 여러 부서 담당자일 수 있음 — 같은 부서에 두 번만 막음
        if key in seen:
            errors.append(f'{i}번째 행: 같은 부서에 같은 이메일이 중복됩니다({dept} · {email}).')
            continue
        seen.add(key)
        out.append({'dept': dept, 'name': name, 'email': email})
    return out, errors


def save_contacts(rows: list, path: str | None = None) -> tuple[list, list]:
    _require_use()
    rows, errors = _clean_contacts(rows)
    if not errors:
        with _LOCK:
            _write_json(path or CONTACTS_PATH, rows)
    return rows, errors


def group_contacts(contacts: list) -> list:
    """같은 이메일(겸직 담당자)을 한 사람으로 — [{'email','name','depts':[...],'dept':'A · B'}] (처음 나온 순서)."""
    out, idx = [], {}
    for c in contacts or []:
        k = (c.get('email') or '').strip().lower()
        if not k:
            continue
        if k not in idx:
            idx[k] = len(out)
            out.append({'email': c['email'], 'name': c.get('name', ''), 'depts': []})
        g = out[idx[k]]
        if c.get('dept') and c['dept'] not in g['depts']:
            g['depts'].append(c['dept'])
        if not g['name'] and c.get('name'):
            g['name'] = c['name']
    for g in out:
        g['dept'] = ' · '.join(g['depts'])
    return out


def contacts_for_emails(emails: list, path: str | None = None) -> list:
    """선택한 이메일들의 담당자 행 전부(겸직이면 여러 행)."""
    want = {(e or '').strip().lower() for e in emails or []}
    return [c for c in load_contacts(path) if c['email'].lower() in want]


def contacts_from_table(df) -> list:
    """엑셀/CSV(부서·담당자·이메일 열)에서 담당자 행을 읽는다. 열 이름은 '부서'/'담당자'(또는 '이름')/'이메일'."""
    cols = {str(c).strip(): c for c in df.columns}
    pick = lambda *names: next((cols[n] for n in names if n in cols), None)  # noqa: E731
    dept_c, name_c, mail_c = pick('부서', '부서명'), pick('담당자', '이름', '성명'), pick('이메일', '메일', 'email')
    if dept_c is None or mail_c is None:
        raise ValueError('엑셀에 "부서"와 "이메일" 열이 있어야 합니다(담당자 이름 열은 선택).')
    return [{'dept': r.get(dept_c, ''), 'name': r.get(name_c, '') if name_c is not None else '', 'email': r.get(mail_c, '')}
            for r in df.fillna('').to_dict('records')]


def person_options() -> list:
    """현재 인력현황(재직자) 검색 옵션 — 담당자 추가용."""
    from services.similarity_map import individual_search_options
    return individual_search_options(current_only=True)


def contact_for_person(researcher_id: str) -> dict:
    """인력현황의 한 사람 → 담당자 행. 이메일은 Knox ID@samsung.com(사용자 확정), 부서는 1단계 부서명."""
    from services.similarity_map import dep_name_for_org_code
    df = data_store.read_processed('researchers')
    rows = df[df['researcher_id'] == researcher_id] if not df.empty else df
    if rows.empty:
        raise ValueError('인력현황에서 찾을 수 없습니다.')
    r = rows.iloc[0]
    knox = str(r.get('knox_id', '') or '').strip()
    if knox.lower() in ('', 'nan'):
        knox = ''
    dept = dep_name_for_org_code(str(r.get('org_code', '') or '')) or str(r.get('department', '') or '').strip()
    return {'dept': dept, 'name': str(r.get('name', '') or ''), 'email': f'{knox}@samsung.com' if knox else ''}


# ── 참조(CC)·비밀참조(BCC) ─────────────────────────────────────────────────────

SEND_MODES = ('each', 'single')           # each: 담당자별 따로 / single: 한 통으로(담당자 전원 TO)


MAIL_PREFIX = 'mail:'                       # 참조 선택값 중 직접 입력한 주소(비실명·팀 계정 등 — 인력현황 검색 불가)


def is_email(addr: str) -> bool:
    return bool(re.fullmatch(r'[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+', (addr or '').strip()))


def parse_recipients(raw: dict | None) -> dict:
    """저장 형식 → {'cc': [...], 'bcc': [...], 'mode'} (빈 값·잘못된 값 정리)."""
    r = raw or {}
    mode = r.get('mode') if r.get('mode') in SEND_MODES else 'each'
    return {'cc': [p for p in r.get('cc') or [] if isinstance(p, dict) and p.get('email')],
            'bcc': [p for p in r.get('bcc') or [] if isinstance(p, dict) and p.get('email')], 'mode': mode}


def people_for(researcher_ids: list, saved: list | None = None) -> list:
    """인력현황 사번 목록 → [{'rid','dept','name','email'}]. Knox ID가 없으면 ValueError.
    saved(이미 저장된 사람)에 있으면 그 값을 쓴다(파견 등으로 인력현황에서 빠져도 유지)."""
    known = {p.get('rid'): p for p in saved or []}
    out, seen = [], set()
    for rid in researcher_ids or []:
        if rid in seen:
            continue
        seen.add(rid)
        if rid in known:
            out.append(known[rid])
            continue
        if str(rid).startswith(MAIL_PREFIX):          # 직접 입력한 주소(팀 계정 등)
            addr = rid[len(MAIL_PREFIX):].strip()
            if not is_email(addr):
                raise ValueError(f'이메일 형식이 아닙니다({addr}).')
            out.append({'rid': rid, 'dept': '', 'name': addr.split('@')[0], 'email': addr})
            continue
        c = contact_for_person(rid)
        if not c['email']:
            raise ValueError(f"{c['name'] or rid}: 인력현황에 Knox ID가 없어 참조에 넣을 수 없습니다.")
        out.append({'rid': rid, **c})
    return out


def recipient_settings() -> dict:
    """저장된 참조인 — {'cc': [{'rid','dept','name','email'}], 'bcc': [...], 'mode': 'each'|'single'}."""
    return parse_recipients(_settings().get('recipients'))


def build_recipients(cc_vals: list, bcc_vals: list, mode: str, saved: list) -> dict:
    """선택값(사번 또는 mail:주소) → 저장할 참조 설정. CC와 겹치는 BCC는 뺌."""
    if mode not in SEND_MODES:
        raise ValueError('발송 방식이 올바르지 않습니다.')
    cc = people_for(cc_vals, saved)
    cc_emails = {p['email'].lower() for p in cc}
    bcc = [p for p in people_for(bcc_vals, saved) if p['email'].lower() not in cc_emails]
    return {'cc': cc, 'bcc': bcc, 'mode': mode}


def save_recipient_settings(cc_rids: list, bcc_rids: list, mode: str) -> dict:
    """참조/비밀참조/발송 방식 저장(수동 화면의 기본값이자 자동 발송에 사용)."""
    _require_use()
    cur = recipient_settings()
    _update_settings(recipients=build_recipients(cc_rids, bcc_rids, mode, cur['cc'] + cur['bcc']))
    return recipient_settings()


# ── 발신 계정 ───────────────────────────────────────────────────────────────

def _account_email(user: dict) -> str:
    return (user.get('email') or '').strip() or f"{user['user_id']}@samsung.com"


def sender_options() -> list:
    """로그인한 본인(기본값)과 팀 공용 계정(.env MAIL_FROM)만(2026-11-19 사용자 확정)."""
    from services.auth import get_current_user
    me = get_current_user() or {}
    opts = []
    if me.get('user_id'):
        opts.append({'label': f"본인 — {me.get('display_name') or me['user_id']} · {_account_email(me)}",
                     'value': me['user_id']})
    shared = os.environ.get('MAIL_FROM', '').strip()
    if shared:
        opts.append({'label': f'팀 공용 계정 · {shared}', 'value': SHARED_SENDER})
    return opts


def _resolve_sender(value: str) -> dict:
    """선택값 → {'email', 'user_id', 'label'}. 팀 공용이면 email/user_id None(mailer가 .env 값 사용)."""
    from services.auth import get_current_user
    if value == SHARED_SENDER:
        return {'email': None, 'user_id': None, 'label': f"팀 공용 계정({os.environ.get('MAIL_FROM', '').strip()})"}
    me = get_current_user() or {}
    if not me.get('user_id') or value != me['user_id']:
        raise PermissionError('발신 계정은 본인 또는 팀 공용 계정만 고를 수 있습니다.')
    email = _account_email(me)
    return {'email': email, 'user_id': me['user_id'], 'label': email}


# ── 발송 ────────────────────────────────────────────────────────────────────

def _deliver(contacts: list, subject: str, body_text: str, attachments: list, sender: dict,
             by: dict, kind: str, order_date: date | None, cc: list | None = None, bcc: list | None = None,
             mode: str = 'each', log_path: str | None = None, extra: dict | None = None,
             per_contact=None) -> list:
    """contacts(TO)에게 발송. cc/bcc는 [{'email',...}] — 담당자별 따로(each)면 메일마다 참조로, 한 통으로(single)면
    담당자 전원을 TO로 한 메일 한 통에 참조로 넣는다(결과는 담당자마다 같은 성공/실패)."""
    from pipeline.mailer import MailError, send_html_email
    html_body = body_html(body_text)
    contacts = group_contacts(contacts)      # 겸직 담당자는 메일 한 통(부서별 첨부는 per_contact가 합쳐 줌)
    cc_emails = [p['email'] for p in cc or []]
    bcc_emails = [p['email'] for p in bcc or []]

    def _try(to_emails, own=()):
        try:
            send_html_email(to_emails, subject.strip(), html_body, list(attachments) + list(own),
                            sender_email=sender['email'], sender_user_id=sender['user_id'],
                            cc=cc_emails, bcc=bcc_emails)
            return True, ''
        except MailError as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001 — 한 명 실패가 나머지 발송을 막지 않게
            return False, f'{type(exc).__name__}: {exc}'

    if mode == 'single' and per_contact is None:
        ok, err = _try([c['email'] for c in contacts])
        results = [{**c, 'ok': ok, 'error': err} for c in contacts]
    else:
        def _one(c):
            try:
                own = per_contact(c) if per_contact else []     # 담당자별 첨부(업무분장 플랫폼별 양식 등)
            except ValueError as exc:                           # 보낼 양식이 없음 등 — 사유 그대로
                return {**c, 'ok': False, 'error': str(exc)}
            except Exception as exc:  # noqa: BLE001 — 양식 생성 실패는 그 담당자 결과로
                return {**c, 'ok': False, 'error': f'첨부 생성 실패: {exc}'}
            ok, err = _try([c['email']], own)
            return {**c, 'ok': ok, 'error': err}

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_one, contacts))
    entry = {'at': datetime.now().isoformat(timespec='seconds'), 'kind': kind,
             'order_date': order_date.isoformat() if order_date else '',
             'by': by.get('user_id', ''), 'by_name': by.get('display_name', ''), 'sender': sender['label'],
             'mode': mode, 'cc': [{'name': p.get('name', ''), 'email': p['email']} for p in cc or []],
             'bcc': [{'name': p.get('name', ''), 'email': p['email']} for p in bcc or []],
             'subject': subject.strip(), 'files': [{'name': n, 'size': len(b)} for n, b in attachments],
             'results': [{k: r[k] for k in ('dept', 'name', 'email', 'ok', 'error')} for r in results]}
    entry.update(extra or {})
    log_path = log_path or LOG_PATH            # 업무분장(services/work_assign.py)은 자기 이력 파일로
    with _LOCK:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return results


def _check(contacts, subject, attachments):
    if not contacts:
        raise ValueError('받을 부서 담당자를 고르세요.')
    if not (subject or '').strip():
        raise ValueError('제목을 입력하세요.')
    if not attachments:
        raise ValueError('첨부파일을 올리세요.')
    total = sum(len(b) for _, b in attachments)
    if total > MAX_TOTAL_BYTES:
        raise ValueError(f'첨부 합계가 {MAX_TOTAL_BYTES // (1024 * 1024)}MB를 넘습니다({total / 1048576:.1f}MB).')


def send(contacts: list, subject: str, body_text: str, attachments: list, sender_value: str,
         order_date: date | None = None, cc: list | None = None, bcc: list | None = None, mode: str = 'each') -> list:
    """화면에서 보내기 — 선택한 담당자들에게 같은 첨부로(기본 한 명씩). subject/body는 이미 발령일이 들어간 문구.
    cc/bcc: [{'email', 'name', ...}](people_for 결과). 반환: [{'dept','name','email','ok','error'}].
    결과는 발송 이력에 남긴다(파일 내용 제외)."""
    from services.auth import get_current_user
    _require_use()
    _check(contacts, subject, attachments)
    if mode not in SEND_MODES:
        raise ValueError('발송 방식이 올바르지 않습니다.')
    sender = _resolve_sender(sender_value)
    return _deliver(contacts, subject, body_text, attachments, sender, get_current_user() or {}, 'manual', order_date,
                    cc=cc, bcc=bcc, mode=mode)


def read_log(limit: int = 50, log_path: str | None = None) -> list:
    try:
        with open(log_path or LOG_PATH, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ── 자동 발송(발령일의 워킹데이 N일 전, 기본 7) ──────────────────────────────────

def auto_settings() -> dict:
    a = _settings().get('auto') or {}
    return {'enabled': bool(a.get('enabled')), 'hour': int(a.get('hour', DEFAULT_AUTO_HOUR)),
            'sender': a.get('sender') or {}, 'files': list(a.get('files') or []),
            'set_by': a.get('set_by', ''), 'set_at': a.get('set_at', '')}


def auto_files() -> list:
    """자동 발송용 첨부 [(이름, bytes)] — 저장된 순서대로, 없어진 파일은 건너뜀."""
    out = []
    for name in auto_settings()['files']:
        path = os.path.join(FILES_DIR, os.path.basename(name))
        try:
            with open(path, 'rb') as f:
                out.append((name, f.read()))
        except OSError:
            continue
    return out


def save_auto_files(files: list) -> list:
    """자동 발송용 첨부를 바꾼다(기존 파일은 지움). files: [(이름, bytes)]."""
    _require_use()
    if sum(len(b) for _, b in files) > MAX_TOTAL_BYTES:
        raise ValueError(f'첨부 합계가 {MAX_TOTAL_BYTES // (1024 * 1024)}MB를 넘습니다.')
    names = []
    with _LOCK:
        os.makedirs(FILES_DIR, exist_ok=True)
        for old in os.listdir(FILES_DIR):
            os.remove(os.path.join(FILES_DIR, old))
        for name, content in files:
            safe = os.path.basename(name).strip() or 'attachment'
            with open(os.path.join(FILES_DIR, safe), 'wb') as f:
                f.write(content)
            names.append(safe)
    a = _settings().get('auto') or {}
    _update_settings(auto={**a, 'files': names})
    return names


def add_auto_files(files: list) -> list:
    """자동 발송용 첨부를 추가(2026-11-20 — 여러 개 누적). 이름이 같으면 새 파일로 바꾼다."""
    new_names = {os.path.basename(n).strip() or 'attachment' for n, _ in files}
    keep = [(n, b) for n, b in auto_files() if n not in new_names]
    return save_auto_files(keep + [(os.path.basename(n).strip() or 'attachment', b) for n, b in files])


def remove_auto_file(name: str) -> list:
    return save_auto_files([(n, b) for n, b in auto_files() if n != name])


def save_auto(enabled: bool, hour: int, sender_value: str) -> dict:
    """자동 발송 설정 — 발신 계정은 저장하는 사람 본인 또는 팀 공용(그대로 기억해 두었다가 자동 발송 때 사용)."""
    from services.auth import get_current_user
    _require_use()
    hour = int(hour)
    if not 0 <= hour <= 23:
        raise ValueError('발송 시각은 0~23시입니다.')
    sender = _resolve_sender(sender_value)
    if enabled:
        if not load_contacts():
            raise ValueError('부서별 담당자를 먼저 등록하세요.')
        if not auto_files():
            raise ValueError('자동 발송에 쓸 첨부파일을 먼저 올리세요.')
    me = get_current_user() or {}
    a = _settings().get('auto') or {}
    _update_settings(auto={**a, 'enabled': bool(enabled), 'hour': hour, 'sender': sender,
                           'set_by': me.get('user_id', ''), 'set_at': datetime.now().isoformat(timespec='seconds')})
    return auto_settings()


def _auto_sent() -> dict:
    data = _read_json(AUTO_SENT_PATH, {})
    return data if isinstance(data, dict) else {}


def _candidate_order_dates(today: date) -> list:
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    nxt2 = (nxt + timedelta(days=32)).replace(day=1)
    return [d for d in (first.replace(day=16), nxt, nxt.replace(day=16), nxt2) if d > today]


def next_auto_send(now: datetime | None = None) -> tuple[date, datetime] | None:
    """다음 자동 발송 예정(발령일, 발송 시각). 이미 보낸 발령일은 건너뜀."""
    now = now or datetime.now()
    cfg = auto_settings()
    hour = cfg['hour']
    try:
        set_at = datetime.fromisoformat(cfg['set_at']) if cfg['set_at'] else None
    except ValueError:
        set_at = None
    sent = _auto_sent()
    for od in _candidate_order_dates(now.date()):
        if od.isoformat() in sent:
            continue
        due = reply_due(od)
        if now.date() >= due:          # 회신 기한이 지난 발령일은 자동 발송하지 않음
            continue
        when = datetime.combine(auto_send_date(od), datetime.min.time()).replace(hour=hour)
        if set_at and when < set_at:     # 설정을 저장(켜기·발송일 변경)하기 전에 이미 지난 예정분은 늦게 보내지 않음
            continue
        return od, when
    return None


def run_auto_if_due(now: datetime | None = None) -> dict | None:
    """자동 발송 시각이 지난 발령일이 있으면 한 번 보낸다(파일 잠금으로 워커 하나만, 발송 기록으로 중복 방지).
    보낼 게 없으면 None, 보냈으면 {'order_date', 'results'}."""
    now = now or datetime.now()
    cfg = auto_settings()
    if not cfg['enabled']:
        return None
    os.makedirs(os.path.dirname(AUTO_LOCK_PATH), exist_ok=True)
    with open(AUTO_LOCK_PATH, 'a+') as lock_f:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None                  # 다른 워커가 처리 중
        try:
            nxt = next_auto_send(now)
            if not nxt or nxt[1] > now:
                return None
            od = nxt[0]
            contacts, files = load_contacts(), auto_files()
            subject_t, body_t = template()
            sender = cfg['sender'] or _resolve_shared()
            if not contacts or not files:
                results = [{'dept': '', 'name': '', 'email': '', 'ok': False,
                            'error': '담당자 또는 자동 발송용 첨부가 없어 보내지 못했습니다.'}]
            else:
                rcp = recipient_settings()
                results = _deliver(contacts, render(subject_t, od), render(body_t, od), files, sender,
                                   {'user_id': 'auto', 'display_name': '자동 발송'}, 'auto', od,
                                   cc=rcp['cc'], bcc=rcp['bcc'], mode=rcp['mode'])
            sent = _auto_sent()
            sent[od.isoformat()] = {'at': now.isoformat(timespec='seconds'),
                                    'ok': sum(1 for r in results if r['ok']), 'fail': sum(1 for r in results if not r['ok'])}
            _write_json(AUTO_SENT_PATH, sent)
            return {'order_date': od, 'results': results}
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _resolve_shared() -> dict:
    return {'email': None, 'user_id': None, 'label': f"팀 공용 계정({os.environ.get('MAIL_FROM', '').strip()})"}


_scheduler_started = False


def start_scheduler(interval_seconds: int = 600) -> None:
    """서버 프로세스마다 데몬 스레드 하나 — interval마다 run_auto_if_due(). 실제 발송은 잠금·기록으로 한 번만."""
    global _scheduler_started
    if _scheduler_started or os.environ.get('HR_ORDER_AUTO_DISABLED') == '1':
        return
    _scheduler_started = True

    def _loop():
        while True:
            try:
                r = run_auto_if_due()
                if r:
                    ok = sum(1 for x in r['results'] if x['ok'])
                    print(f"[hr_order] {r['order_date']} 발령분 자동 발송 — 성공 {ok}/{len(r['results'])}")
            except Exception as exc:  # noqa: BLE001 — 스케줄러가 죽지 않게
                print(f'[hr_order] 자동 발송 점검 실패: {exc}')
            try:                          # 업무분장 자동 발송(2026-11-20)도 같은 스레드에서 점검
                from services import work_assign
                r = work_assign.run_auto_if_due()
                if r:
                    ok = sum(1 for x in r['results'] if x['ok'])
                    print(f"[work_assign] {r['target']} 업무분장 자동 발송 — 성공 {ok}/{len(r['results'])}")
            except Exception as exc:  # noqa: BLE001
                print(f'[work_assign] 자동 발송 점검 실패: {exc}')
            time.sleep(interval_seconds)
    threading.Thread(target=_loop, daemon=True, name='hr-order-auto').start()
