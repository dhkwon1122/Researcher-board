"""
엑셀 다운로드 권한 + 1회성 다운로드 요청/승인(2026-10-15, 사용자 요청).

  - 권한: 계정별 "엑셀 다운로드"(download_excel, 관리자 > 사용자/권한 관리 표의 "엑셀" 체크). 역할 기본값은 허용.
  - 권한이 없는 구성원은 화면의 "다운로드 요청"으로 대상·사용목적을 적어 관리자에게 1회성 요청을 보낸다.
  - 관리자가 "관리자 > 다운로드 요청" 탭에서 승인/반려. 승인하면 요청자에게 알림(화면 알림 + 메일 — 메일은 설정돼
    있을 때만)이 가고, 알림에 "다운로드한 정보의 관리 책임은 전적으로 본인에게 있다"는 안내가 붙는다.
    요청자가 그 안내를 "확인"해야 승인 1건으로 그 화면에서 1번 다운로드할 수 있다(유효기간 GRANT_DAYS일).
  - 대상 화면(FEATURES): 연구원 명단 엑셀, 조서 작성, JOB Market 결과, 보유 전문성·유사 연구원 명단.
    관리자 화면 안의 다운로드(사용자 양식 등)는 관리자 전용이라 대상 아님.

저장: data/processed/download_requests.json(파일 잠금으로 여러 프로세스 동시 쓰기 보호).
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
GRANT_DAYS = 7
_LOCK = threading.Lock()

FEATURES = {
    'researcher_list': '연구원 명단 엑셀',
    'report_builder': '조서 작성',
    'job_market': 'JOB Market 결과',
    'expertise': '보유 전문성·유사 연구원 명단',
}

RESPONSIBILITY_NOTICE = ('다운로드한 정보의 관리 책임은 전적으로 본인에게 있습니다. 승인된 사용목적 외 사용, '
                         '외부 유출·제3자 제공을 금지하며, 목적 달성 후에는 파일을 즉시 삭제해 주십시오.')


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


def _read() -> list:
    try:
        with open(REQUESTS_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(items: list) -> None:
    tmp = REQUESTS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REQUESTS_PATH)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def _current_user() -> dict:
    from services.auth import get_current_user
    return get_current_user() or {}


def has_permission() -> bool:
    from services.auth import can
    return can('download_excel')


# ─── 요청 ────────────────────────────────────────────────────────────────────

def create_request(feature: str, target: str, purpose: str) -> dict:
    user = _current_user()
    if not user.get('user_id'):
        raise PermissionError('로그인이 필요합니다.')
    if feature not in FEATURES:
        raise ValueError('알 수 없는 다운로드 화면입니다.')
    target, purpose = (target or '').strip(), (purpose or '').strip()
    if not target or not purpose:
        raise ValueError('대상과 사용목적을 모두 입력하세요.')
    req = {'id': uuid.uuid4().hex[:12], 'user_id': user['user_id'], 'display_name': user.get('display_name', ''),
           'email': user.get('email', ''), 'feature': feature, 'feature_label': FEATURES[feature],
           'target': target[:500], 'purpose': purpose[:1000], 'status': 'pending', 'created_at': _now(),
           'decided_by': '', 'decided_at': '', 'admin_comment': '', 'expires_at': '',
           'acknowledged_at': '', 'used_at': ''}
    with _file_lock():
        items = _read()
        items.append(req)
        _write(items)
    return req


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
            f"<ul><li>화면: {req['feature_label']}</li><li>대상: {req['target']}</li><li>사용목적: {req['purpose']}</li>"
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
    with _file_lock():
        items = _read()
        for r in items:
            if r['id'] in request_ids and r['user_id'] == user_id and not r.get('acknowledged_at'):
                r['acknowledged_at'] = _now()
        _write(items)


# ─── 다운로드 관문 ───────────────────────────────────────────────────────────

def _usable_grant(user_id: str, feature: str) -> dict | None:
    now = _now()
    for r in my_requests(user_id):
        if (r['feature'] == feature and r['status'] == 'approved' and r.get('acknowledged_at')
                and not r.get('used_at') and r.get('expires_at', '') >= now):
            return r
    return None


def check(feature: str) -> tuple[bool, str, str | None]:
    """(허용 여부, 안내 문구, 사용할 승인 id). 권한이 있으면 (True, '', None)."""
    if has_permission():
        return True, '', None
    user_id = _current_user().get('user_id', '')
    grant = _usable_grant(user_id, feature)
    if grant:
        return True, f"승인된 1회성 다운로드를 사용합니다(요청일 {grant['created_at']}).", grant['id']
    pending = any(r['feature'] == feature and r['status'] == 'pending' for r in my_requests(user_id))
    unacked = any(r['feature'] == feature and r['status'] == 'approved' and not r.get('acknowledged_at')
                  for r in my_requests(user_id))
    if unacked:
        return False, '승인된 요청이 있습니다 — 화면 상단 알림에서 "정보 관리 책임" 안내를 확인한 뒤 다시 시도하세요.', None
    if pending:
        return False, '엑셀 다운로드 권한이 없습니다. 보낸 요청이 관리자 승인 대기 중입니다.', None
    return False, '엑셀 다운로드 권한이 없습니다. "다운로드 요청"으로 대상과 사용목적을 적어 관리자에게 요청하세요.', None


def consume(grant_id: str | None) -> None:
    if not grant_id:
        return
    with _file_lock():
        items = _read()
        for r in items:
            if r['id'] == grant_id and not r.get('used_at'):
                r['used_at'] = _now()
                r['status'] = 'used'
        _write(items)
