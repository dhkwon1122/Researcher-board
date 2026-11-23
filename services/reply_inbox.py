"""
회신 메일 자동 취합(2026-11-23, 사용자 요청 "dhkwon1122/exec_org를 참고해서 비실명계정을 추가해서 pop3로 메일을 읽어서(첨부파일
다운로드까지) 업무분장과 인사발령 회신오는 내용을 취합하고 싶어(개인 계정은 pop3로 메일 읽어 오기 불가능)").

exec_org의 services/mailbox.py·mail_text.py 방식을 따른다: POP3(UIDL 목록 → 새 메일만 RETR) → email 패키지로 제목·보낸 사람·
날짜·첨부 파싱 → UIDL을 기록해 같은 메일을 두 번 읽지 않음 → 서버 메일은 지우지 않음(기본) → 백그라운드에서 N분마다(워커 여럿이어도
파일 잠금으로 하나만).

설정(.env, exec_org와 같은 이름): MAIL_POP3_HOST, MAIL_POP3_PORT(비우면 SSL 995/평문 110), MAIL_POP3_SSL(기본 1),
MAIL_POP3_USER, MAIL_POP3_PASSWORD, MAIL_POLL_MINUTES(기본 10), MAIL_SINCE_DAYS(기본 30 — 이보다 오래된 메일은 건너뜀),
MAIL_MAX_PER_RUN(기본 50), MAIL_MAX_ATTACHMENT_MB(기본 20). REPLY_INBOX_DISABLED=1이면 주기 실행 안 함.

회신 연결(LLM 없음 — 개인정보를 밖으로 보내지 않음):
1) 어느 메일의 회신인지: 제목에서 RE:/회신:/답장:/FW: 등을 떼고, 업무분장·인사발령 발송 이력의 제목이 들어 있으면 그 발송(대상월/
   발령일). 없으면 제목 글자(업무분장/인사발령 + 연·월/날짜)로 추정.
2) 어느 부서인지: 보낸 사람 이메일이 그 시나리오 담당자 명단에 있으면 그 부서(겸직이면 첨부 파일 이름의 부서명으로 고름),
   명단에 없으면 첨부 파일 이름의 부서명.
3) 업무분장: 엑셀·CSV 첨부를 제출 현황에 등록(work_assign.store_submission — 부서별로 교체). 인사발령: 첨부 전체를 회신 현황에
   등록(hr_order_mail.store_reply). 못 정하면 "확인 필요"로 남기고 화면에서 직접 지정.

저장(data/processed): reply_inbox.json(받은 메일 목록·UIDL·처리 결과), reply_inbox_files/<메일 id>/(첨부 원본),
.reply_inbox_status.json(마지막 확인), .reply_inbox_fetch.lock/.reply_inbox_poll.lock.
"""
from __future__ import annotations

import email
import email.policy
import fcntl
import logging
import os
import poplib
import re
import threading
import time
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime

from services import data_store
from services import hr_order_mail as hom
from services.db import load_env_file

load_env_file()          # 도커 밖에서 실행할 때도 .env의 MAIL_POP3_*를 읽도록(이미 있는 환경변수는 덮지 않음)

log = logging.getLogger(__name__)

INDEX_PATH = os.path.join(data_store.DATA_DIR, 'reply_inbox.json')
FILES_DIR = os.path.join(data_store.DATA_DIR, 'reply_inbox_files')
STATUS_PATH = os.path.join(data_store.DATA_DIR, '.reply_inbox_status.json')
FETCH_LOCK = os.path.join(data_store.DATA_DIR, '.reply_inbox_fetch.lock')
POLL_LOCK = os.path.join(data_store.DATA_DIR, '.reply_inbox_poll.lock')
SCENARIOS = {'work_assign': '업무분장', 'hr_order': '인사발령'}
STATUS = {'registered': '등록됨', 'review': '확인 필요', 'ignored': '무시', 'no_attachment': '첨부 없음',
          'skipped': '오래돼 건너뜀'}
AUTO_BY = {'user_id': 'mail', 'display_name': '회신 메일'}
_LOCK = threading.Lock()
_KOREAN_CHARSETS = {'ks_c_5601-1987', 'ks_c_5601', 'ksc5601', 'euc-kr', 'euc_kr', 'euckr', 'ks_c_5601-1989', 'x-windows-949'}


def _env(name: str, default: str = '') -> str:
    return os.environ.get(f'MAIL_{name}', default).strip()


def is_configured() -> bool:
    return bool(_env('POP3_HOST') and _env('POP3_USER'))


def settings() -> dict:
    ssl = _env('POP3_SSL', '1').lower() not in ('0', 'false', 'no')
    return {'host': _env('POP3_HOST'), 'port': int(_env('POP3_PORT') or ('995' if ssl else '110')), 'ssl': ssl,
            'user': _env('POP3_USER'), 'password': _env('POP3_PASSWORD'),
            'minutes': max(1, int(_env('POLL_MINUTES', '10') or 10)), 'since_days': int(_env('SINCE_DAYS', '30') or 30),
            'max_per_run': int(_env('MAX_PER_RUN', '50') or 50),
            'max_attachment_mb': int(_env('MAX_ATTACHMENT_MB', '20') or 20)}


# ── 메일 파싱(exec_org services/mail_text.py와 같은 방식) ───────────────────────

def _part_text(part) -> str:
    raw = part.get_payload(decode=True) or b''
    charset = (part.get_content_charset() or '').lower()
    for enc in (('cp949',) if charset in _KOREAN_CHARSETS else (charset,) if charset else ()) + ('utf-8', 'cp949'):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('utf-8', errors='replace')


def _header(msg, name: str) -> str:
    try:
        return str(msg.get(name) or '').strip()
    except Exception:  # noqa: BLE001 — 깨진 머리글
        return ''


def parse(data: bytes, max_bytes: int = 20 * 1024 * 1024) -> dict:
    """메일 원본(RFC 822) → {'subject','sender','sender_email','mail_date','message_id','attachments':[(이름, bytes)]}.
    본문 속 그림(서명 이미지 등)과 max_bytes보다 큰 첨부는 뺀다."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    sender = _header(msg, 'from')
    try:
        dt = parsedate_to_datetime(_header(msg, 'date'))
        mail_date = dt.strftime('%Y-%m-%d %H:%M')      # 보낸 쪽 머리글 시각 그대로(서버 시간대와 무관 — 사내는 KST)
    except (TypeError, ValueError, IndexError):
        mail_date = ''
    files = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        try:
            name = part.get_filename()
        except Exception:  # noqa: BLE001
            name = None
        if not name:
            continue
        if (part.get_content_disposition() or '').lower() == 'inline' and part.get_content_maintype() == 'image' \
                and part.get('content-id'):
            continue
        payload = part.get_payload(decode=True) or b''
        if payload and len(payload) <= max_bytes:
            files.append((str(name).strip().replace('\r', '').replace('\n', ''), payload))
    return {'subject': _header(msg, 'subject'), 'sender': sender, 'sender_email': parseaddr(sender)[1].lower(),
            'mail_date': mail_date, 'message_id': _header(msg, 'message-id'), 'attachments': files}


# ── 목록 저장 ───────────────────────────────────────────────────────────────

def _load() -> list:
    data = hom._read_json(INDEX_PATH, [])
    return data if isinstance(data, list) else []


def _save(rows: list) -> None:
    hom._write_json(INDEX_PATH, rows)


def list_mails(scenario: str | None = None, limit: int = 100) -> list:
    """최근 받은 회신(새것부터). scenario를 주면 그 시나리오 + 시나리오를 못 정한 메일."""
    rows = [m for m in _load() if m.get('status') != 'skipped']
    if scenario:
        rows = [m for m in rows if m.get('scenario') in (scenario, '', None)]
    return list(reversed(rows))[:limit]


def get_mail(mail_id: int) -> dict | None:
    return next((m for m in _load() if m['id'] == mail_id), None)


def _update(mail_id: int, **fields) -> dict | None:
    with _LOCK:
        rows = _load()
        for m in rows:
            if m['id'] == mail_id:
                m.update(fields)
                _save(rows)
                return m
    return None


def mail_files(mail_id: int) -> list:
    """저장한 첨부 [(이름, bytes)]."""
    m = get_mail(mail_id) or {}
    out = []
    for f in m.get('files', []):
        try:
            with open(os.path.join(FILES_DIR, str(mail_id), f['file']), 'rb') as fh:
                out.append((f['name'], fh.read()))
        except OSError:
            continue
    return out


# ── 회신 연결 ───────────────────────────────────────────────────────────────

_PREFIX_RE = re.compile(r'^\s*(?:\[?(?:re|fw|fwd|회신|답장|전달|답신)\]?\s*[:：]\s*)+', re.I)


def norm_subject(subject: str) -> str:
    s = subject or ''
    prev = None
    while prev != s:
        prev, s = s, _PREFIX_RE.sub('', s)
    return re.sub(r'\s+', ' ', s).strip().lower()


def _sent_logs() -> list:
    """[(시나리오, 기간 키, 정규화한 제목)] — 최근 발송부터."""
    from services import work_assign as wa
    out = []
    for e in wa.read_log(500):
        if e.get('target') and e.get('subject'):
            out.append(('work_assign', e['target'], norm_subject(e['subject'])))
    for e in hom.read_log(500):
        if e.get('order_date') and e.get('subject'):
            out.append(('hr_order', e['order_date'], norm_subject(e['subject'])))
    return out


def guess_scenario(subject: str) -> tuple[str, str, str]:
    """(시나리오, 기간 키, 근거). 못 정하면 ('', '', 이유)."""
    ns = norm_subject(subject)
    if not ns:
        return '', '', '제목 없음'
    for sc, period, sent in _sent_logs():
        if sent and sent in ns:
            return sc, period, '발송 제목과 일치'
    if '업무분장' in ns:
        m = re.search(r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*월?", ns) or re.search(r"'?(\d{2})\s*년\s*(\d{1,2})\s*월", ns)
        if m:
            y = int(m.group(1))
            y = y + 2000 if y < 100 else y
            if 1 <= int(m.group(2)) <= 12:
                return 'work_assign', f'{y:04d}-{int(m.group(2)):02d}', '제목의 업무분장·연월'
        return 'work_assign', '', '제목에 업무분장(대상월 못 찾음)'
    if '인사발령' in ns:
        m = re.search(r'(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})', ns)
        if m:
            try:
                return 'hr_order', date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), '제목의 인사발령·날짜'
            except ValueError:
                pass
        return 'hr_order', '', '제목에 인사발령(발령일 못 찾음)'
    return '', '', '업무분장·인사발령 회신으로 보이지 않음'


def _contacts(scenario: str) -> list:
    from services import work_assign as wa
    return wa.load_contacts() if scenario == 'work_assign' else hom.load_contacts()


def _departments(scenario: str) -> list:
    from services import work_assign as wa
    return wa.departments() if scenario == 'work_assign' else hom.departments()


def guess_depts(scenario: str, sender_email: str, file_names: list) -> dict:
    """첨부 파일별 부서 {파일 이름: 부서 또는 ''} — 보낸 사람 담당 부서 하나면 그 부서, 겸직·명단 밖이면 파일 이름으로."""
    from services import work_assign as wa
    mine = [c['dept'] for c in _contacts(scenario) if c['email'].lower() == (sender_email or '').lower()]
    mine = list(dict.fromkeys(mine))
    all_depts = _departments(scenario)
    out = {}
    for name in file_names:
        by_name = wa.match_department(name, mine) if len(mine) > 1 else None
        if len(mine) == 1:
            out[name] = mine[0]
        elif by_name:
            out[name] = by_name
        else:
            out[name] = wa.match_department(name, all_depts) or ''
    return out


def _is_table(name: str) -> bool:
    return name.lower().endswith(('.xlsx', '.xlsm', '.xls', '.csv'))


def apply(mail_id: int, scenario: str | None = None, period: str | None = None, dept: str | None = None,
          by: dict | None = None) -> dict:
    """메일 한 통을 시나리오·기간·부서에 등록. 인자를 주면 그 값으로(화면에서 직접 지정 — dept를 주면 모든 첨부를 그 부서로),
    안 주면 자동 판정. 결과를 메일 기록에 남기고 돌려준다."""
    from services import work_assign as wa
    m = get_mail(mail_id)
    if not m:
        raise ValueError('메일을 찾을 수 없습니다.')
    files = mail_files(mail_id)
    sc, per, why = (scenario, period, '직접 지정') if scenario else guess_scenario(m['subject'])
    if not sc:
        return _update(mail_id, status='review', scenario='', period='', note=why)
    if not files:
        return _update(mail_id, status='no_attachment', scenario=sc, period=per or '', note='첨부 파일이 없습니다.')
    if not per:
        return _update(mail_id, status='review', scenario=sc, period='', note=f'{why} — 기간을 정하세요.')
    names = [n for n, _ in files]
    depts = {n: dept for n in names} if dept else guess_depts(sc, m.get('sender_email', ''), names)
    by = by or AUTO_BY
    done, problems = [], []
    if sc == 'work_assign':
        for name, content in files:
            if not _is_table(name):
                continue
            d = depts.get(name)
            if not d:
                problems.append(f'{name}: 부서를 못 정함')
                continue
            try:
                wa.store_submission(per, d, name, content, by, source='mail')
                done.append(d)
            except ValueError as exc:
                problems.append(str(exc))
        if not done and not problems:
            problems.append('엑셀·CSV 첨부가 없습니다.')
    else:
        groups = {}
        for name, content in files:
            d = depts.get(name) or (dept or '')
            if not d:
                # 보낸 사람 담당 부서가 하나뿐인데 파일 이름엔 부서명이 없는 경우 등 — 같은 메일의 다른 첨부 부서를 따름
                known = [v for v in depts.values() if v]
                d = known[0] if len(set(known)) == 1 else ''
            if not d:
                problems.append(f'{name}: 부서를 못 정함')
                continue
            groups.setdefault(d, []).append((name, content))
        for d, fs in groups.items():
            try:
                hom.store_reply(per, d, fs, by, source='mail', sender=m.get('sender', ''), mail_subject=m['subject'])
                done.append(d)
            except ValueError as exc:
                problems.append(str(exc))
    status = 'registered' if done and not problems else 'review'
    note = '; '.join(([f"등록: {', '.join(dict.fromkeys(done))}"] if done else []) + problems) or why
    return _update(mail_id, status=status, scenario=sc, period=per, depts=list(dict.fromkeys(done)), note=note,
                   handled_by=by.get('display_name', ''), handled_at=datetime.now().isoformat(timespec='seconds'))


def assign(mail_id: int, scenario: str, period: str, dept: str) -> dict:
    """화면에서 직접 지정(권한 필요)."""
    from services.auth import get_current_user
    hom._require_use()
    if scenario not in SCENARIOS:
        raise ValueError('업무분장/인사발령을 고르세요.')
    if not period:
        raise ValueError('대상월/발령일을 고르세요.')
    if not dept:
        raise ValueError('부서를 고르세요.')
    return apply(mail_id, scenario, period, dept, by=get_current_user() or {})


def ignore(mail_id: int) -> dict | None:
    hom._require_use()
    return _update(mail_id, status='ignored', note='무시함')


# ── POP3 가져오기 ───────────────────────────────────────────────────────────

def _connect(cfg: dict):
    cls = poplib.POP3_SSL if cfg['ssl'] else poplib.POP3
    conn = cls(cfg['host'], cfg['port'], timeout=30)
    conn.user(cfg['user'])
    conn.pass_(cfg['password'])
    return conn


def fetch_new(connect=None, today: date | None = None) -> dict:
    """새 메일을 가져와 첨부를 저장하고 회신으로 연결 → {'new','skipped','registered','review'}. 서버 메일은 지우지 않는다."""
    cfg = settings()
    conn = (connect or _connect)(cfg)
    new_ids, skipped = [], 0
    try:
        _, listing, _ = conn.uidl()
        pairs = []
        for line in listing:
            num, uid = line.decode('utf-8', 'replace').split(None, 1)
            pairs.append((int(num), uid.strip()))
        known = {m.get('uidl') for m in _load()}
        todo = [(n, u) for n, u in pairs if u not in known]
        since = ((today or date.today()) - timedelta(days=cfg['since_days'])).isoformat() if cfg['since_days'] > 0 else ''
        for num, uid in (todo[-cfg['max_per_run']:] if cfg['max_per_run'] > 0 else todo):   # 가장 최근 것들
            _, lines, _ = conn.retr(num)
            parsed = parse(b'\r\n'.join(lines), cfg['max_attachment_mb'] * 1024 * 1024)
            old = bool(since and parsed['mail_date'] and parsed['mail_date'][:10] < since)
            with _LOCK:
                rows = _load()
                if any(r.get('uidl') == uid for r in rows):
                    continue
                mid = max([r['id'] for r in rows] or [0]) + 1
                saved = []
                if not old:
                    folder = os.path.join(FILES_DIR, str(mid))
                    os.makedirs(folder, exist_ok=True)
                    for i, (name, content) in enumerate(parsed['attachments']):
                        fname = f'{i + 1:02d}_{hom._safe_name(name)}'
                        with open(os.path.join(folder, fname), 'wb') as fh:
                            fh.write(content)
                        saved.append({'name': name, 'file': fname, 'size': len(content)})
                rows.append({'id': mid, 'uidl': uid, 'subject': parsed['subject'][:500], 'sender': parsed['sender'][:300],
                             'sender_email': parsed['sender_email'], 'mail_date': parsed['mail_date'],
                             'received_at': datetime.now().isoformat(timespec='seconds'), 'files': saved,
                             'status': 'skipped' if old else 'review', 'scenario': '', 'period': '', 'depts': [],
                             'note': ''})
                _save(rows)
            if old:
                skipped += 1
            else:
                new_ids.append(mid)
    finally:
        try:
            conn.quit()
        except Exception:  # noqa: BLE001
            pass
    registered = review = 0
    for mid in new_ids:
        try:
            r = apply(mid) or {}
        except Exception as exc:  # noqa: BLE001 — 한 통 실패가 나머지를 막지 않게
            log.exception('회신 연결 실패 %s', mid)
            r = _update(mid, status='review', note=f'{type(exc).__name__}: {exc}') or {}
        registered += r.get('status') == 'registered'
        review += r.get('status') == 'review'
    return {'new': len(new_ids), 'skipped': skipped, 'registered': registered, 'review': review}


def last_run() -> dict:
    data = hom._read_json(STATUS_PATH, {})
    return data if isinstance(data, dict) else {}


def run_once(connect=None) -> dict:
    """한 번 가져오기 — 주기 실행과 '지금 가져오기'가 겹치지 않게 파일 잠금(겹치면 busy). 결과는 상태 파일에."""
    at = datetime.now().strftime('%Y-%m-%d %H:%M')
    if not is_configured() and connect is None:
        return {'at': at, 'ok': False, 'error': 'MAIL_POP3_HOST/MAIL_POP3_USER가 앱에 전달되지 않았습니다 — .env에 넣은 뒤 '
                                                 'docker-compose.yml의 app environment에도 있는지 확인하고 '
                                                 '`docker compose up -d app`으로 다시 띄우세요.'}
    os.makedirs(os.path.dirname(FETCH_LOCK), exist_ok=True)
    with open(FETCH_LOCK, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {'at': at, 'ok': True, 'busy': True, 'new': 0, 'skipped': 0, 'registered': 0, 'review': 0}
        try:
            st = {'at': at, 'ok': True, **fetch_new(connect)}
        except Exception as exc:  # noqa: BLE001
            log.warning('회신 메일 가져오기 실패: %s', exc)
            st = {'at': at, 'ok': False, 'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
    hom._write_json(STATUS_PATH, st)
    return st


_started = False
_lock_holder: list = []


def start_poller() -> bool:
    """MAIL_POP3_*가 있으면 백그라운드에서 주기적으로 가져온다(gunicorn 워커 중 잠금을 잡은 하나만)."""
    global _started
    if _started or not is_configured() or os.environ.get('REPLY_INBOX_DISABLED') == '1':
        return False
    try:
        os.makedirs(os.path.dirname(POLL_LOCK), exist_ok=True)
        lock = open(POLL_LOCK, 'w')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    _started = True

    def loop():
        time.sleep(15)
        while True:
            run_once()
            time.sleep(settings()['minutes'] * 60)

    threading.Thread(target=loop, name='reply-inbox', daemon=True).start()
    _lock_holder.append(lock)
    return True


def config_summary() -> dict:
    cfg = settings()
    return {'configured': is_configured(), 'account': f"{cfg['user']} @ {cfg['host']}:{cfg['port']}" if is_configured() else '',
            'minutes': cfg['minutes'], 'since_days': cfg['since_days']}

