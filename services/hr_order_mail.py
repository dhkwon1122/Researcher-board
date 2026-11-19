"""
업무 시나리오 > 인사발령 — 부서별 담당자에게 인사발령 작성 양식(첨부파일)을 메일로 보낸다(2026-11-19).

사용자 확정 흐름: 시스템 안에서 발령 내용을 입력받는 대신, 화면에서 양식 파일을 올리면 선택한 부서 담당자들에게
같은 첨부로 한 명씩 메일을 보낸다(매월 1일·16일 발령 취합용). 발신 계정은 기본이 로그인한 본인 계정이고
(.env의 MAIL_FROM은 팀 공용 비실명 계정), 팀 공용 계정을 고르거나 관리자는 다른 등록 계정을 고를 수 있다.

저장: data/processed/hr_order_contacts.json(부서별 담당자 표), hr_order_settings.json(사용 허용 역할),
hr_order_log.jsonl(발송 이력 — 첨부 파일 내용은 저장하지 않고 이름·크기만).
"""
from __future__ import annotations

import html
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from services import data_store

CONTACTS_PATH = os.path.join(data_store.DATA_DIR, 'hr_order_contacts.json')
SETTINGS_PATH = os.path.join(data_store.DATA_DIR, 'hr_order_settings.json')
LOG_PATH = os.path.join(data_store.DATA_DIR, 'hr_order_log.jsonl')
MAX_TOTAL_BYTES = 20 * 1024 * 1024        # 첨부 합계 상한(메일 서버 제한 대비)
SHARED_SENDER = '__shared__'              # 발신 계정 선택값: .env의 팀 공용 계정
_LOCK = threading.Lock()


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{threading.get_ident()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ── 사용 권한: 관리자 + 관리자가 허용한 역할 ──────────────────────────────────

def allowed_roles() -> list:
    return list(_read_json(SETTINGS_PATH, {}).get('roles') or [])


def set_allowed_roles(roles: list) -> list:
    from services.auth import can
    if not can('manage_users'):
        raise PermissionError('관리자만 바꿀 수 있습니다.')
    from config.auth_config import ROLE_LABELS
    roles = [r for r in dict.fromkeys(roles or []) if r in ROLE_LABELS]
    with _LOCK:
        data = _read_json(SETTINGS_PATH, {})
        data['roles'] = roles
        _write_json(SETTINGS_PATH, data)
    return roles


def can_use() -> bool:
    from services.auth import can, get_current_user
    user = get_current_user()
    if not user:
        return False
    return can('manage_users') or user.get('role') in allowed_roles()


# ── 부서별 담당자 표 ────────────────────────────────────────────────────────

def load_contacts() -> list:
    return [c for c in _read_json(CONTACTS_PATH, []) if isinstance(c, dict)]


def _clean_contacts(rows: list) -> tuple[list, list]:
    """빈 행은 버리고, 이메일 형식이 틀린 행은 오류로 돌려준다. 반환: (정리된 행, 오류 문구)."""
    out, errors = [], []
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
        out.append({'dept': dept, 'name': name, 'email': email})
    return out, errors


def save_contacts(rows: list) -> tuple[list, list]:
    if not can_use():
        raise PermissionError('인사발령 메뉴 권한이 없습니다.')
    rows, errors = _clean_contacts(rows)
    if not errors:
        with _LOCK:
            _write_json(CONTACTS_PATH, rows)
    return rows, errors


def contacts_from_table(df) -> list:
    """엑셀/CSV(부서·담당자·이메일 열)에서 담당자 행을 읽는다. 열 이름은 '부서'/'담당자'(또는 '이름')/'이메일'."""
    cols = {str(c).strip(): c for c in df.columns}
    pick = lambda *names: next((cols[n] for n in names if n in cols), None)  # noqa: E731
    dept_c, name_c, mail_c = pick('부서', '부서명'), pick('담당자', '이름', '성명'), pick('이메일', '메일', 'email')
    if dept_c is None or mail_c is None:
        raise ValueError('엑셀에 "부서"와 "이메일" 열이 있어야 합니다(담당자 이름 열은 선택).')
    return [{'dept': r.get(dept_c, ''), 'name': r.get(name_c, '') if name_c is not None else '', 'email': r.get(mail_c, '')}
            for r in df.fillna('').to_dict('records')]


# ── 발신 계정 ───────────────────────────────────────────────────────────────

def _account_email(user: dict) -> str:
    return (user.get('email') or '').strip() or f"{user['user_id']}@samsung.com"


def sender_options() -> list:
    """[{'label', 'value'}] — 첫 항목은 로그인한 본인(기본값). 팀 공용 계정(.env MAIL_FROM)이 있으면 그다음.
    관리자는 다른 등록 계정도 고를 수 있다."""
    from services.auth import can, get_current_user, list_users
    me = get_current_user() or {}
    opts = []
    if me.get('user_id'):
        opts.append({'label': f"본인 — {me.get('display_name') or me['user_id']} · {_account_email(me)}",
                     'value': me['user_id']})
    shared = os.environ.get('MAIL_FROM', '').strip()
    if shared:
        opts.append({'label': f'팀 공용 계정 · {shared}', 'value': SHARED_SENDER})
    if can('manage_users'):
        for u in list_users():
            if u['user_id'] != me.get('user_id'):
                opts.append({'label': f"{u.get('display_name') or u['user_id']} ({u['user_id']}) · {_account_email(u)}",
                             'value': u['user_id']})
    return opts


def _resolve_sender(value: str) -> tuple[str | None, str | None, str]:
    """선택값 → (발신 이메일, 메일 API userId, 화면·로그 표시). 팀 공용이면 (None, None) — mailer가 .env 값 사용."""
    from services.auth import can, get_current_user, list_users
    if value == SHARED_SENDER:
        return None, None, f"팀 공용 계정({os.environ.get('MAIL_FROM', '').strip()})"
    me = get_current_user() or {}
    if value != me.get('user_id') and not can('manage_users'):
        raise PermissionError('다른 계정으로는 관리자만 보낼 수 있습니다.')
    user = me if value == me.get('user_id') else next((u for u in list_users() if u['user_id'] == value), None)
    if not user:
        raise ValueError('발신 계정을 찾을 수 없습니다.')
    email = _account_email(user)
    return email, user['user_id'], email


# ── 메일 ────────────────────────────────────────────────────────────────────

def next_order_date(today: date | None = None) -> date:
    """다음 발령일(매월 1일·16일 중 오늘 이후 가장 가까운 날)."""
    today = today or date.today()
    if today.day < 16:
        return today.replace(day=16)
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    return nxt


def default_subject(order_date: date) -> str:
    return f'[인사발령] {order_date:%Y.%m.%d}자 발령 대상 작성 요청'


def default_body(order_date: date) -> str:
    due = order_date - timedelta(days=3)
    return (f'안녕하세요.\n\n{order_date:%Y년 %m월 %d일}자 인사발령(부서이동·파트이동 등) 대상을 취합합니다.\n'
            f'첨부한 양식에 부서 내 발령 대상자를 작성하여 {due:%m월 %d일}까지 회신 부탁드립니다.\n'
            f'해당 인원이 없는 경우에도 "해당 없음"으로 회신해 주세요.\n\n감사합니다.')


def body_html(text: str) -> str:
    """본문 텍스트(사용자 입력)를 이스케이프해 줄바꿈만 살린 HTML로."""
    return ('<div style="font-family:\'Malgun Gothic\',sans-serif;font-size:14px;line-height:1.7">'
            + html.escape(text or '').replace('\n', '<br>') + '</div>')


def send(contacts: list, subject: str, body_text: str, attachments: list, sender_value: str) -> list:
    """선택한 담당자들에게 같은 첨부로 한 명씩 보낸다. 반환: [{'dept','name','email','ok','error'}].
    attachments: [(파일명, bytes)]. 결과는 발송 이력(hr_order_log.jsonl)에 남긴다(파일 내용 제외)."""
    from pipeline.mailer import MailError, send_html_email
    from services.auth import get_current_user
    if not can_use():
        raise PermissionError('인사발령 메뉴 권한이 없습니다.')
    if not contacts:
        raise ValueError('받을 부서 담당자를 고르세요.')
    if not (subject or '').strip():
        raise ValueError('제목을 입력하세요.')
    if not attachments:
        raise ValueError('첨부파일을 올리세요.')
    total = sum(len(b) for _, b in attachments)
    if total > MAX_TOTAL_BYTES:
        raise ValueError(f'첨부 합계가 {MAX_TOTAL_BYTES // (1024 * 1024)}MB를 넘습니다({total / 1048576:.1f}MB).')
    sender_email, sender_user_id, sender_label = _resolve_sender(sender_value)
    html_body = body_html(body_text)

    def _one(c):
        try:
            send_html_email([c['email']], subject.strip(), html_body, attachments,
                            sender_email=sender_email, sender_user_id=sender_user_id)
            return {**c, 'ok': True, 'error': ''}
        except MailError as exc:
            return {**c, 'ok': False, 'error': str(exc)}
        except Exception as exc:  # noqa: BLE001 — 한 명 실패가 나머지 발송을 막지 않게
            return {**c, 'ok': False, 'error': f'{type(exc).__name__}: {exc}'}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_one, contacts))

    user = get_current_user() or {}
    entry = {'at': datetime.now().isoformat(timespec='seconds'), 'by': user.get('user_id', ''),
             'by_name': user.get('display_name', ''), 'sender': sender_label, 'subject': subject.strip(),
             'files': [{'name': n, 'size': len(b)} for n, b in attachments],
             'results': [{k: r[k] for k in ('dept', 'name', 'email', 'ok', 'error')} for r in results]}
    with _LOCK:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return results


def read_log(limit: int = 50) -> list:
    try:
        with open(LOG_PATH, encoding='utf-8') as f:
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
