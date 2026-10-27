"""
엑셀 다운로드 권한 + 1회성 다운로드 요청/승인(2026-10-15, 사용자 요청; 2026-10-16 개정).

  - 권한: 계정별 "엑셀 다운로드"(download_excel, 관리자 > 사용자/권한 관리 표의 "엑셀" 체크).
    역할 기본값은 불허(2026-10-16) — 관리자 계정(is_admin)은 항상 허용.
  - 권한이 없는 구성원은 "다운로드 요청"으로 1회성 요청을 보낸다. 요청에는 대상·사용목적과 함께
    **받을 헤더(열) 구성과 대상자 명단(spec)**이 붙는다 — 관리자는 어떤 데이터를 내려받으려는지 확인하고 승인한다.
      · 조서 작성: 화면에서 구성한 열(헤더 이름·항목·묶는 방식)·여러 건 최대·대상자
      · JOB Market 결과 / 보유 전문성·유사 연구원: 그 엑셀의 헤더 중 고른 것 + 화면에서 고른 대상자
      · 연구원 명단: 열이 고정이라 별도 요청 대신 조서 작성으로 보낸다(표에 보이는 대상자를 조서 작성에 넘김,
        조서 작성 "기본 양식" = 연구원 명단 엑셀).
  - 관리자가 "관리자 > 다운로드 요청" 탭에서 승인/반려. 승인하면 요청자에게 알림(화면 알림 + 메일 — 메일은 설정돼
    있을 때만)이 가고 "다운로드한 정보의 관리 책임은 전적으로 본인에게 있다"는 안내가 붙는다. 요청자가 안내를
    확인해야 그 화면에서 1번, **승인된 구성(spec) 그대로만** 다운로드할 수 있다(유효기간 GRANT_DAYS일).
  - 로그: 요청·승인·반려·안내 확인·다운로드(권한 보유자의 다운로드 포함)를 download_log.jsonl에 남기고
    관리자 탭에서 조회한다.

  - 요청 알림 메일(2026-10-26): 관리자 > 사용자/권한 관리 탭에서 고른 계정들에게 "누가 어떤 데이터를 요청했는지" 메일
    (계정 이메일, 없으면 ID@samsung.com). 요청 화면이 메일 API를 기다리지 않도록 백그라운드로 보내고 결과는 로그에 남긴다.

저장: data/processed/download_requests.json, download_log.jsonl, download_prefill.json, download_notify.json(파일 잠금).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from services import data_store

REQUESTS_PATH = os.path.join(data_store.DATA_DIR, 'download_requests.json')
LOG_PATH = os.path.join(data_store.DATA_DIR, 'download_log.jsonl')
PREFILL_PATH = os.path.join(data_store.DATA_DIR, 'download_prefill.json')
NOTIFY_PATH = os.path.join(data_store.DATA_DIR, 'download_notify.json')
GRANT_DAYS = 7
_LOCK = threading.Lock()

FEATURES = {
    'researcher_list': '연구원 명단 엑셀',
    'report_builder': '조서 작성',
    'job_market': 'JOB Market 결과',
    'expertise': '보유 전문성·유사 연구원 명단',
}
REQUESTABLE = ('report_builder', 'job_market', 'expertise')   # 연구원 명단은 조서 작성으로 요청

RESPONSIBILITY_NOTICE = ('다운로드한 정보의 관리 책임은 전적으로 본인에게 있습니다. 승인된 사용목적 외 사용, '
                         '외부 유출·제3자 제공을 금지하며, 목적 달성 후에는 파일을 즉시 삭제해 주십시오.')

EVENTS = {'request': '요청', 'notify': '알림 메일', 'approve': '승인', 'reject': '반려', 'acknowledge': '안내 확인',
          'download': '다운로드'}


def fixed_headers(feature: str) -> list:
    """열이 고정된 화면의 엑셀 헤더(요청자가 이 중에서 고른다)."""
    if feature == 'job_market':
        from services.job_market import RESULT_HEADERS
        return list(RESULT_HEADERS)
    if feature == 'expertise':
        from services.similarity_map import SIMILARITY_HEADERS
        return list(SIMILARITY_HEADERS)
    return []


@contextmanager
def _file_lock():
    with _LOCK:
        lock_path = REQUESTS_PATH + '.lock'
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, 'w') as fh:
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            yield


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, data) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read() -> list:
    return _read_json(REQUESTS_PATH, [])


def _write(items: list) -> None:
    _write_json(REQUESTS_PATH, items)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def _current_user() -> dict:
    from services.auth import get_current_user
    return get_current_user() or {}


def has_permission() -> bool:
    from services.auth import can
    return bool(_current_user().get('is_admin')) or can('download_excel')


# ─── 로그 ────────────────────────────────────────────────────────────────────

def _log(event: str, feature: str, user: dict, req: dict | None = None, **extra) -> None:
    """한 줄 JSON 추가(append) — 요청/승인/반려/안내 확인/다운로드."""
    entry = {'at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'event': event,
             'user_id': user.get('user_id', ''), 'display_name': user.get('display_name', ''),
             'feature': feature, 'feature_label': FEATURES.get(feature, feature)}
    if req is not None:
        entry.update({'request_id': req['id'], 'requester_id': req['user_id'],
                      'requester_name': req.get('display_name', ''), 'purpose': req.get('purpose', ''),
                      'headers': req.get('headers', []), 'target_count': req.get('target_count', 0)})
    entry.update(extra)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError as exc:
        print(f'[download_access] 로그 기록 실패: {exc}')


def read_log(limit: int = 300) -> list:
    """최신순."""
    try:
        with open(LOG_PATH, encoding='utf-8') as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


# ─── 요청 ────────────────────────────────────────────────────────────────────

def _spec(feature: str, context: dict, headers: list | None) -> tuple[dict, list]:
    """요청에 붙일 구성(spec)과 관리자에게 보여줄 헤더 목록."""
    context = context or {}
    ids = list(dict.fromkeys([str(x) for x in (context.get('ids') or []) if x]))
    if not ids:
        raise ValueError('화면에서 대상자를 먼저 고르세요(요청에 대상자 명단이 함께 갑니다).')
    if feature == 'report_builder':
        from services import report_builder as rb
        columns = rb.clean_columns(context.get('columns') or [])
        if not columns:
            raise ValueError('조서 양식에 항목이 들어 있는 열을 하나 이상 구성하세요.')
        max_items = context.get('max_items')
        spec = {'ids': ids, 'columns': columns, 'max_items': int(max_items) if max_items else None}
        return spec, [c['header'] for c in columns]
    allowed = fixed_headers(feature)
    chosen = [h for h in allowed if h in (headers or [])]
    if not chosen:
        raise ValueError('받을 헤더(열)를 하나 이상 고르세요.')
    return {'ids': ids, 'headers': chosen}, chosen


def create_request(feature: str, target: str, purpose: str, context: dict | None = None,
                   headers: list | None = None) -> dict:
    user = _current_user()
    if not user.get('user_id'):
        raise PermissionError('로그인이 필요합니다.')
    if feature not in REQUESTABLE:
        raise ValueError('이 화면은 1회성 요청 대상이 아닙니다.')
    target, purpose = (target or '').strip(), (purpose or '').strip()
    if not purpose:
        raise ValueError('사용목적을 입력하세요.')
    spec, header_list = _spec(feature, context, headers)
    req = {'id': uuid.uuid4().hex[:12], 'user_id': user['user_id'], 'display_name': user.get('display_name', ''),
           'email': user.get('email', ''), 'feature': feature, 'feature_label': FEATURES[feature],
           'target': target[:500], 'purpose': purpose[:1000], 'spec': spec, 'headers': header_list,
           'target_count': len(spec['ids']), 'status': 'pending', 'created_at': _now(),
           'decided_by': '', 'decided_at': '', 'admin_comment': '', 'expires_at': '',
           'acknowledged_at': '', 'used_at': ''}
    with _file_lock():
        items = _read()
        items.append(req)
        _write(items)
    _log('request', feature, user, req, target=req['target'])
    threading.Thread(target=_notify_request_mail, args=(req, user), daemon=True).start()
    return req


# ─── 요청 알림 메일(관리자 지정 계정) ─────────────────────────────────────────

def notify_recipients() -> list:
    """알림 받을 계정 ID 목록(사용자/권한 관리 탭에서 지정)."""
    data = _read_json(NOTIFY_PATH, {})
    return [str(u) for u in data.get('user_ids', []) if u]


def set_notify_recipients(user_ids: list) -> list:
    from services.auth import can
    if not can('manage_users'):
        raise PermissionError('관리자만 설정할 수 있습니다.')
    ids = list(dict.fromkeys(str(u) for u in (user_ids or []) if u))
    with _file_lock():
        _write_json(NOTIFY_PATH, {'user_ids': ids, 'updated_at': _now(),
                                  'updated_by': _current_user().get('user_id', '')})
    return ids


def recipient_emails(user_ids: list | None = None) -> list:
    """계정 ID → 메일 주소(계정 이메일, 없으면 ID@samsung.com — 사내 메일 기본 규칙)."""
    from services.auth import list_users
    ids = notify_recipients() if user_ids is None else user_ids
    emails = {u['user_id']: (u.get('email') or '').strip() for u in list_users()}
    return list(dict.fromkeys((emails.get(uid) or f'{uid}@samsung.com') for uid in ids))


def request_mail_html(req: dict) -> str:
    from html import escape
    rows = [('요청자', f"{req.get('display_name') or req['user_id']} ({req['user_id']})"),
            ('화면', req['feature_label']),
            ('대상', f"{req.get('target') or '-'} · 대상자 {req.get('target_count', 0)}명"),
            ('받을 헤더', ', '.join(req.get('headers') or []) or '-'),
            ('사용목적', req.get('purpose', '')),
            ('요청 시각', req.get('created_at', ''))]
    body = ''.join(f'<tr><th style="text-align:left;padding:4px 10px;background:#F3F5F9;white-space:nowrap">{escape(k)}</th>'
                   f'<td style="padding:4px 10px">{escape(str(v))}</td></tr>' for k, v in rows)
    return (f'<p>엑셀 다운로드 요청이 들어왔습니다.</p>'
            f'<table style="border-collapse:collapse;border:1px solid #DCE3EE;font-size:13px">{body}</table>'
            f'<p>People in SAIT &gt; 관리자 &gt; <b>다운로드 요청</b> 탭에서 대상자 명단을 확인하고 승인 또는 반려해 주세요.</p>')


def _notify_request_mail(req: dict, user: dict) -> None:
    ids = notify_recipients()
    if not ids:
        return
    try:
        to = recipient_emails(ids)
        from pipeline.mailer import send_html_email
        send_html_email(to, f"[People in SAIT] 엑셀 다운로드 요청 — {req.get('display_name') or req['user_id']} · "
                            f"{req['feature_label']}", request_mail_html(req))
        _log('notify', req['feature'], user, req, result='발송', recipients=len(to))
    except Exception as exc:  # noqa: BLE001 — 메일 실패가 요청을 막지 않게, 사유는 로그로
        print(f'[download_access] 요청 알림 메일 실패: {exc}')
        _log('notify', req['feature'], user, req, result=f'실패: {exc}'[:300], recipients=len(ids))


def list_requests(status: str | None = None) -> list:
    items = _read()
    if status:
        items = [r for r in items if r.get('status') == status]
    return sorted(items, key=lambda r: r.get('created_at', ''), reverse=True)


def my_requests(user_id: str) -> list:
    return [r for r in list_requests() if r.get('user_id') == user_id]


def decide(request_id: str, approve: bool, comment: str = '') -> dict:
    """관리자 승인/반려. 승인 시 유효기간 GRANT_DAYS일, 요청자에게 메일(설정돼 있으면) — 화면 알림은 notices()."""
    from services.auth import can
    if not can('manage_users'):
        raise PermissionError('관리자만 처리할 수 있습니다.')
    admin = _current_user()
    with _file_lock():
        items = _read()
        req = next((r for r in items if r['id'] == request_id), None)
        if req is None:
            raise ValueError('요청을 찾을 수 없습니다.')
        if req['status'] != 'pending':
            raise ValueError('이미 처리된 요청입니다.')
        req.update({'status': 'approved' if approve else 'rejected', 'decided_by': admin.get('display_name') or admin.get('user_id', ''),
                    'decided_at': _now(), 'admin_comment': (comment or '').strip()[:500],
                    'expires_at': (datetime.now() + timedelta(days=GRANT_DAYS)).strftime('%Y-%m-%d %H:%M') if approve else ''})
        _write(items)
    _log('approve' if approve else 'reject', req['feature'], admin, req, comment=req['admin_comment'],
         expires_at=req['expires_at'])
    _notify_mail(req)
    return req


def _notify_mail(req: dict) -> None:
    """요청자에게 결과 메일(메일 API 설정이 없거나 실패해도 화면 알림은 그대로 동작)."""
    to = req.get('email') or ''
    if not to:   # 계정에 이메일이 없으면 화면 알림만
        return
    approved = req['status'] == 'approved'
    body = (f"<p>{req.get('display_name') or req['user_id']}님, 요청하신 엑셀 다운로드가 "
            f"<b>{'승인' if approved else '반려'}</b>되었습니다.</p>"
            f"<ul><li>화면: {req['feature_label']}</li><li>대상: {req.get('target') or '-'} ({req.get('target_count', 0)}명)</li>"
            f"<li>헤더: {', '.join(req.get('headers') or [])}</li><li>사용목적: {req['purpose']}</li>"
            + (f"<li>관리자 의견: {req['admin_comment']}</li>" if req.get('admin_comment') else '')
            + (f"<li>유효기간: {req['expires_at']}까지 1회</li>" if approved else '') + '</ul>'
            + (f"<p style='color:#b02a37'><b>{RESPONSIBILITY_NOTICE}</b></p>"
               '<p>People in SAIT에 로그인해 알림을 확인한 뒤 다운로드할 수 있습니다.</p>' if approved else ''))
    try:
        from pipeline.mailer import send_html_email
        send_html_email([to], f"[People in SAIT] 엑셀 다운로드 요청 {'승인' if approved else '반려'}", body)
    except Exception as exc:  # noqa: BLE001 — 메일 미설정·실패는 화면 알림으로 대체
        print(f'[download_access] 결과 메일 발송 생략/실패: {exc}')


# ─── 요청자 알림 ─────────────────────────────────────────────────────────────

def notices(user_id: str) -> list:
    """요청자가 아직 확인하지 않은 처리 결과(승인·반려)."""
    return [r for r in my_requests(user_id) if r['status'] in ('approved', 'rejected') and not r.get('acknowledged_at')]


def acknowledge(request_ids: list, user_id: str) -> None:
    done = []
    with _file_lock():
        items = _read()
        for r in items:
            if r['id'] in request_ids and r['user_id'] == user_id and not r.get('acknowledged_at'):
                r['acknowledged_at'] = _now()
                done.append(r)
        _write(items)
    user = _current_user()
    for r in done:
        if r['status'] == 'approved':
            _log('acknowledge', r['feature'], user, r, notice=RESPONSIBILITY_NOTICE)


# ─── 다운로드 관문 ───────────────────────────────────────────────────────────

def _usable_grant(user_id: str, feature: str) -> dict | None:
    now = _now()
    for r in my_requests(user_id):
        if (r['feature'] == feature and r['status'] == 'approved' and r.get('acknowledged_at')
                and not r.get('used_at') and r.get('expires_at', '') >= now):
            return r
    return None


def check(feature: str) -> tuple[bool, str, dict | None]:
    """(허용 여부, 안내 문구, 사용할 승인 건). 권한이 있으면 (True, '', None).
    승인 건이 있으면 다운로드는 그 승인 건의 spec(대상자·헤더) 그대로 만들어야 한다."""
    if has_permission():
        return True, '', None
    if feature not in REQUESTABLE:
        return False, ('엑셀 다운로드 권한이 없습니다. "조서 작성에서 요청"을 눌러 필요한 헤더를 구성한 뒤 '
                       '관리자에게 1회성 다운로드를 요청하세요.'), None
    user_id = _current_user().get('user_id', '')
    grant = _usable_grant(user_id, feature)
    if grant:
        return True, (f"승인된 요청(요청일 {grant['created_at']})의 대상 {grant.get('target_count', 0)}명·"
                      f"헤더 {len(grant.get('headers') or [])}개 그대로 1회 다운로드했습니다."), grant
    mine = [r for r in my_requests(user_id) if r['feature'] == feature]
    if any(r['status'] == 'approved' and not r.get('acknowledged_at') for r in mine):
        return False, '승인된 요청이 있습니다 — 화면 알림에서 "정보 관리 책임" 안내를 확인한 뒤 다시 시도하세요.', None
    if any(r['status'] == 'pending' for r in mine):
        return False, '엑셀 다운로드 권한이 없습니다. 보낸 요청이 관리자 승인 대기 중입니다.', None
    return False, '엑셀 다운로드 권한이 없습니다. "다운로드 요청"으로 헤더·대상·사용목적을 적어 관리자에게 요청하세요.', None


def complete(feature: str, grant: dict | None, rows: int, headers: list | None = None, filename: str = '') -> None:
    """다운로드가 만들어진 뒤 호출 — 승인 건이면 사용 처리, 어느 경우든 로그."""
    if grant:
        with _file_lock():
            items = _read()
            for r in items:
                if r['id'] == grant['id'] and not r.get('used_at'):
                    r['used_at'] = _now()
                    r['status'] = 'used'
            _write(items)
    _log('download', feature, _current_user(), grant, basis='승인 1회' if grant else '권한',
         rows=rows, file_headers=list(headers or []), filename=filename)


# ─── 연구원 명단 → 조서 작성 대상자 넘기기 ────────────────────────────────────

def set_prefill(user_id: str, ids: list) -> None:
    with _file_lock():
        data = _read_json(PREFILL_PATH, {})
        data[user_id] = {'ids': list(dict.fromkeys(ids))[:5000], 'at': _now()}
        _write_json(PREFILL_PATH, data)


def pop_prefill(user_id: str) -> list:
    if not user_id or not os.path.exists(PREFILL_PATH):
        return []
    with _file_lock():
        data = _read_json(PREFILL_PATH, {})
        item = data.pop(user_id, None)
        if item is not None:
            _write_json(PREFILL_PATH, data)
    return (item or {}).get('ids') or []
