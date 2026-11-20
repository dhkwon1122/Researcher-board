"""
업무 시나리오 > 업무분장(2026-11-20) — 매월 부서별 담당자에게 업무분장표 작성 양식을 메일로 보내고, 회신받은 업무분장표
(엑셀)를 화면에 올려 부서별 제출 현황과 통합표로 관리한다.

사용자 확정(2026-11-20):
- 형태: 메일 취합 + 회신 파일 관리 "둘 다".
- 받는 사람: 인사발령과 같은 명단(부서별 담당자·참조/비밀참조·발송 방식 공유 — services/hr_order_mail.py가 관리).
- 주기: 매월, "마지막 워킹데이 N일 전"에 자동 발송(N은 화면에서 설정, 0이면 마지막 워킹데이 당일).
- 회신 관리: 부서별 제출 현황 + 통합표(양식의 열 그대로 + 부서 열, 엑셀 다운로드).

기간 키는 "대상월"(YYYY-MM) — 월말에 다음 달 업무분장을 미리 취합한다는 전제로, 대상월의 전달 마지막 워킹데이를 기준일로
잡는다(예: 대상월 2026-12 → 기준일 2026-11-30(월), N=3이면 11-25(수) 발송). 회신 기한 = 발송일로부터 워킹데이 K일 후.
자리표시자: {대상월}(2026년 12월)·{대상월_숫자}(2026.12)·{회신일}·{회신일_월일}.

권한·워킹데이(공휴일·회사 휴무일)·발신 계정·본문 서식 정리·메일 발송은 인사발령 모듈을 그대로 쓴다.
저장(data/processed): work_assign_settings.json(템플릿·일수·자동 발송), work_assign_auto_files/(자동 발송용 첨부),
work_assign_auto_sent.json, work_assign_log.jsonl(발송 이력), work_assign_submissions.json + work_assign_files/<대상월>/
(회신 파일).
"""
from __future__ import annotations

import fcntl
import io
import os
import re
import threading
from datetime import date, datetime, timedelta

import pandas as pd

from services import data_store
from services import hr_order_mail as hom

SETTINGS_PATH = os.path.join(data_store.DATA_DIR, 'work_assign_settings.json')
LOG_PATH = os.path.join(data_store.DATA_DIR, 'work_assign_log.jsonl')
AUTO_FILES_DIR = os.path.join(data_store.DATA_DIR, 'work_assign_auto_files')
AUTO_SENT_PATH = os.path.join(data_store.DATA_DIR, 'work_assign_auto_sent.json')
AUTO_LOCK_PATH = os.path.join(data_store.DATA_DIR, '.work_assign_auto.lock')
SUBMISSIONS_PATH = os.path.join(data_store.DATA_DIR, 'work_assign_submissions.json')
SUBMIT_DIR = os.path.join(data_store.DATA_DIR, 'work_assign_files')
SEND_DAYS_DEFAULT = 3                     # 마지막 워킹데이 3일 전 발송(기본값)
REPLY_DAYS_DEFAULT = 3                    # 발송일로부터 워킹데이 3일 후 회신(기본값)
MAX_DAYS = 15
DEFAULT_AUTO_HOUR = 9
_LOCK = threading.Lock()

DEFAULT_SUBJECT = '[업무분장] {대상월} 업무분장표 작성 요청'
DEFAULT_BODY = ('안녕하세요.\n\n{대상월} 업무분장표를 취합합니다.\n'
                '첨부한 양식에 부서 구성원별 담당 업무를 작성하여 {회신일_월일}까지 회신 부탁드립니다.\n'
                '변동이 없는 경우에도 현행 업무분장으로 회신해 주세요.\n\n감사합니다.')


def _settings() -> dict:
    data = hom._read_json(SETTINGS_PATH, {})
    return data if isinstance(data, dict) else {}


def _update_settings(**fields) -> dict:
    with _LOCK:
        data = _settings()
        data.update(fields)
        hom._write_json(SETTINGS_PATH, data)
    return data


can_use = hom.can_use
_require_use = hom._require_use


# ── 날짜 ────────────────────────────────────────────────────────────────────

def _month(target: str) -> tuple[int, int]:
    if not re.fullmatch(r'\d{4}-\d{2}', target or ''):
        raise ValueError('대상월 형식이 올바르지 않습니다.')
    y, m = int(target[:4]), int(target[5:])
    if not 1 <= m <= 12:
        raise ValueError('대상월 형식이 올바르지 않습니다.')
    return y, m


def _shift_month(y: int, m: int, k: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + k
    return idx // 12, idx % 12 + 1


def target_of(d: date, k: int = 1) -> str:
    y, m = _shift_month(d.year, d.month, k)
    return f'{y:04d}-{m:02d}'


def last_workday(y: int, m: int) -> date:
    ny, nm = _shift_month(y, m, 1)
    cur, cache = date(ny, nm, 1) - timedelta(days=1), {}
    while not hom.is_workday(cur, cache):
        cur -= timedelta(days=1)
    return cur


def workdays_after(d: date, n: int) -> date:
    cache, cur, left = {}, d, n
    while left:
        cur += timedelta(days=1)
        if hom.is_workday(cur, cache):
            left -= 1
    return cur


def base_date(target: str) -> date:
    """대상월의 전달 마지막 워킹데이."""
    y, m = _month(target)
    py, pm = _shift_month(y, m, -1)
    return last_workday(py, pm)


def send_workdays() -> int:
    return int((_settings().get('days') or {}).get('send', SEND_DAYS_DEFAULT))


def reply_workdays() -> int:
    return int((_settings().get('days') or {}).get('reply', REPLY_DAYS_DEFAULT))


def set_workdays(send: int, reply: int) -> tuple[int, int]:
    _require_use()
    try:
        send, reply = int(send), int(reply)
    except (TypeError, ValueError):
        raise ValueError('발송일·회신 기한을 숫자로 고르세요.') from None
    if not 0 <= send <= MAX_DAYS or not 1 <= reply <= MAX_DAYS:
        raise ValueError(f'발송은 마지막 워킹데이 0~{MAX_DAYS}일 전, 회신 기한은 발송 후 1~{MAX_DAYS} 워킹데이입니다.')
    _update_settings(days={'send': send, 'reply': reply})
    return send, reply


def send_date(target: str) -> date:
    return hom.workdays_before(base_date(target), send_workdays())


def reply_due(target: str, sent_on: date | None = None) -> date:
    """회신 기한 = 발송일(수동이면 실제 보낸 날)로부터 워킹데이 K일 후."""
    return workdays_after(sent_on or send_date(target), reply_workdays())


def target_label(target: str) -> str:
    y, m = _month(target)
    return f'{y}년 {m}월'


def target_options(today: date | None = None, n: int = 6) -> list:
    """대상월 선택지 — 이번 달부터 n개월(기본값은 다음 달)."""
    today = today or date.today()
    return [target_of(today, k) for k in range(0, n)]


# ── 템플릿 ──────────────────────────────────────────────────────────────────

def placeholder_values(target: str, reply: date) -> dict:
    y, m = _month(target)
    return {'대상월': f'{y}년 {m}월', '대상월_숫자': f'{y}.{m:02d}', '회신일': f'{reply:%Y.%m.%d}',
            '회신일_월일': hom._md(reply)}


def render(text: str, target: str, reply: date) -> str:
    out = text or ''
    for k, v in placeholder_values(target, reply).items():
        out = out.replace('{' + k + '}', v)
    return out


def template() -> tuple[str, str]:
    t = _settings().get('template') or {}
    return t.get('subject') or DEFAULT_SUBJECT, t.get('body') or hom.text_to_html(DEFAULT_BODY)


def save_template(subject: str, body: str) -> None:
    _require_use()
    body = hom.sanitize_html(body)
    if not (subject or '').strip() or not hom._plain(body):
        raise ValueError('제목과 본문을 입력하세요.')
    _update_settings(template={'subject': subject.strip(), 'body': body})


# ── 발송 ────────────────────────────────────────────────────────────────────

def send(contacts: list, subject: str, body_html_text: str, attachments: list, sender_value: str, target: str,
         cc: list | None = None, bcc: list | None = None, mode: str = 'each') -> list:
    """수동 발송 — subject/body는 이미 대상월·회신일이 들어간 문구. 받는 사람·참조인은 인사발령과 같은 명단."""
    from services.auth import get_current_user
    _require_use()
    hom._check(contacts, subject, attachments)
    if mode not in hom.SEND_MODES:
        raise ValueError('발송 방식이 올바르지 않습니다.')
    sender = hom._resolve_sender(sender_value)
    return hom._deliver(contacts, subject, body_html_text, attachments, sender, get_current_user() or {}, 'manual',
                        None, cc=cc, bcc=bcc, mode=mode, log_path=LOG_PATH, extra={'target': target})


def read_log(limit: int = 50) -> list:
    return hom.read_log(limit, LOG_PATH)


# ── 자동 발송(매월 마지막 워킹데이 N일 전) ────────────────────────────────────

def auto_settings() -> dict:
    a = _settings().get('auto') or {}
    return {'enabled': bool(a.get('enabled')), 'hour': int(a.get('hour', DEFAULT_AUTO_HOUR)),
            'sender': a.get('sender') or {}, 'files': list(a.get('files') or []),
            'set_by': a.get('set_by', ''), 'set_at': a.get('set_at', '')}


def auto_files() -> list:
    out = []
    for name in auto_settings()['files']:
        try:
            with open(os.path.join(AUTO_FILES_DIR, os.path.basename(name)), 'rb') as f:
                out.append((name, f.read()))
        except OSError:
            continue
    return out


def _save_auto_files(files: list) -> list:
    _require_use()
    if sum(len(b) for _, b in files) > hom.MAX_TOTAL_BYTES:
        raise ValueError(f'첨부 합계가 {hom.MAX_TOTAL_BYTES // (1024 * 1024)}MB를 넘습니다.')
    names = []
    with _LOCK:
        os.makedirs(AUTO_FILES_DIR, exist_ok=True)
        for old in os.listdir(AUTO_FILES_DIR):
            os.remove(os.path.join(AUTO_FILES_DIR, old))
        for name, content in files:
            safe = os.path.basename(name).strip() or 'attachment'
            with open(os.path.join(AUTO_FILES_DIR, safe), 'wb') as f:
                f.write(content)
            names.append(safe)
    a = _settings().get('auto') or {}
    _update_settings(auto={**a, 'files': names})
    return names


def add_auto_files(files: list) -> list:
    new_names = {os.path.basename(n).strip() or 'attachment' for n, _ in files}
    keep = [(n, b) for n, b in auto_files() if n not in new_names]
    return _save_auto_files(keep + [(os.path.basename(n).strip() or 'attachment', b) for n, b in files])


def remove_auto_file(name: str) -> list:
    return _save_auto_files([(n, b) for n, b in auto_files() if n != name])


def save_auto(enabled: bool, hour: int, sender_value: str) -> dict:
    from services.auth import get_current_user
    _require_use()
    hour = int(hour)
    if not 0 <= hour <= 23:
        raise ValueError('발송 시각은 0~23시입니다.')
    sender = hom._resolve_sender(sender_value)
    if enabled:
        if not hom.load_contacts():
            raise ValueError('부서별 담당자를 먼저 등록하세요(인사발령 화면).')
        if not auto_files():
            raise ValueError('자동 발송에 쓸 첨부파일을 먼저 올리세요.')
    me = get_current_user() or {}
    a = _settings().get('auto') or {}
    _update_settings(auto={**a, 'enabled': bool(enabled), 'hour': hour, 'sender': sender,
                           'set_by': me.get('user_id', ''), 'set_at': datetime.now().isoformat(timespec='seconds')})
    return auto_settings()


def _auto_sent() -> dict:
    data = hom._read_json(AUTO_SENT_PATH, {})
    return data if isinstance(data, dict) else {}


def next_auto_send(now: datetime | None = None) -> tuple[str, datetime] | None:
    """다음 자동 발송 예정(대상월, 발송 시각). 보낸 대상월·회신 기한 지난 대상월·설정 저장 전에 지난 예정분은 건너뜀."""
    now = now or datetime.now()
    cfg = auto_settings()
    try:
        set_at = datetime.fromisoformat(cfg['set_at']) if cfg['set_at'] else None
    except ValueError:
        set_at = None
    sent = _auto_sent()
    for target in (target_of(now.date(), 1), target_of(now.date(), 2)):
        if target in sent:
            continue
        sd = send_date(target)
        if now.date() >= reply_due(target, sd):
            continue
        when = datetime.combine(sd, datetime.min.time()).replace(hour=cfg['hour'])
        if set_at and when < set_at:
            continue
        return target, when
    return None


def run_auto_if_due(now: datetime | None = None) -> dict | None:
    now = now or datetime.now()
    cfg = auto_settings()
    if not cfg['enabled']:
        return None
    os.makedirs(os.path.dirname(AUTO_LOCK_PATH), exist_ok=True)
    with open(AUTO_LOCK_PATH, 'a+') as lock_f:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        try:
            nxt = next_auto_send(now)
            if not nxt or nxt[1] > now:
                return None
            target = nxt[0]
            contacts, files = hom.load_contacts(), auto_files()
            subject_t, body_t = template()
            sender = cfg['sender'] or hom._resolve_shared()
            reply = reply_due(target, now.date())
            if not contacts or not files:
                results = [{'dept': '', 'name': '', 'email': '', 'ok': False,
                            'error': '담당자 또는 자동 발송용 첨부가 없어 보내지 못했습니다.'}]
            else:
                rcp = hom.recipient_settings()
                results = hom._deliver(contacts, render(subject_t, target, reply), render(body_t, target, reply), files,
                                       sender, {'user_id': 'auto', 'display_name': '자동 발송'}, 'auto', None,
                                       cc=rcp['cc'], bcc=rcp['bcc'], mode=rcp['mode'], log_path=LOG_PATH,
                                       extra={'target': target})
            sent = _auto_sent()
            sent[target] = {'at': now.isoformat(timespec='seconds'),
                            'ok': sum(1 for r in results if r['ok']), 'fail': sum(1 for r in results if not r['ok'])}
            hom._write_json(AUTO_SENT_PATH, sent)
            return {'target': target, 'results': results}
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


# ── 회신 파일: 부서별 제출 현황 + 통합표 ──────────────────────────────────────

_TABLE_EXT = ('.xlsx', '.xlsm', '.xls', '.csv')


def departments() -> list:
    """제출 현황의 부서 목록 = 인사발령 부서별 담당자의 부서(등록 순서, 중복 제거)."""
    out = []
    for c in hom.load_contacts():
        if c.get('dept') and c['dept'] not in out:
            out.append(c['dept'])
    return out


def _submissions() -> dict:
    data = hom._read_json(SUBMISSIONS_PATH, {})
    return data if isinstance(data, dict) else {}


def submissions(target: str) -> dict:
    """{부서: {'file','name','size','rows','by','by_name','at'}}."""
    return dict(_submissions().get(target) or {})


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_') or 'x'


def match_department(filename: str, depts: list) -> str | None:
    """파일 이름에 들어 있는 부서명(가장 긴 것)으로 부서를 찾는다(공백 무시)."""
    key = re.sub(r'\s+', '', filename)
    hits = [d for d in depts if re.sub(r'\s+', '', d) and re.sub(r'\s+', '', d) in key]
    return max(hits, key=len) if hits else None


def read_table(name: str, content: bytes) -> pd.DataFrame:
    """업무분장표 파일 → 표. 첫 시트에서 머리글 행(처음 10행 중 채워진 칸이 가장 많은 첫 행)을 찾아 그 아래를 읽는다
    (양식 위쪽의 제목·안내 행을 건너뛰기 위해)."""
    low = name.lower()
    if not low.endswith(_TABLE_EXT):
        raise ValueError(f'{name}: 엑셀(xlsx·xls) 또는 CSV 파일만 올릴 수 있습니다.')
    try:
        if low.endswith('.csv'):
            try:
                raw = pd.read_csv(io.BytesIO(content), header=None, dtype=str, encoding='utf-8-sig')
            except UnicodeDecodeError:
                raw = pd.read_csv(io.BytesIO(content), header=None, dtype=str, encoding='cp949')
        else:
            raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str)
    except Exception as exc:  # noqa: BLE001 — 깨진 파일 등은 사용자 메시지로
        raise ValueError(f'{name}: 표를 읽지 못했습니다({type(exc).__name__}).') from exc
    raw = raw.dropna(how='all').dropna(axis=1, how='all')
    if raw.empty:
        return pd.DataFrame()
    head = raw.head(10)
    counts = head.notna().sum(axis=1)
    hdr_idx = counts.idxmax()
    header, cols = [], []
    for i, v in enumerate(raw.loc[hdr_idx].tolist()):
        h = str(v).strip() if isinstance(v, str) or pd.notna(v) else ''
        h = h or f'열{i + 1}'
        base, k = h, 2
        while h in header:
            h, k = f'{base}_{k}', k + 1
        header.append(h)
        cols.append(raw.columns[i])
    body = raw.loc[raw.index > hdr_idx, cols]
    body.columns = header
    body = body.dropna(how='all').fillna('')
    strip = getattr(body, 'map', None) if hasattr(pd.DataFrame, 'map') else body.applymap
    return strip(lambda x: str(x).strip())


def save_submission(target: str, dept: str, name: str, content: bytes) -> dict:
    """부서 회신 파일 저장(같은 부서는 새 파일로 교체). 표를 읽을 수 없으면 ValueError."""
    from services.auth import get_current_user
    _require_use()
    _month(target)
    if dept not in departments():
        raise ValueError(f'{dept}: 부서별 담당자에 없는 부서입니다.')
    df = read_table(name, content)
    me = get_current_user() or {}
    ext = os.path.splitext(name)[1].lower()
    fname = f'{_safe(dept)}{ext}'
    folder = os.path.join(SUBMIT_DIR, target)
    with _LOCK:
        os.makedirs(folder, exist_ok=True)
        old = (_submissions().get(target) or {}).get(dept)
        if old and old.get('file') and old['file'] != fname:
            try:
                os.remove(os.path.join(folder, old['file']))
            except OSError:
                pass
        with open(os.path.join(folder, fname), 'wb') as f:
            f.write(content)
        data = _submissions()
        rec = {'file': fname, 'name': os.path.basename(name), 'size': len(content), 'rows': int(len(df)),
               'by': me.get('user_id', ''), 'by_name': me.get('display_name', ''),
               'at': datetime.now().isoformat(timespec='seconds')}
        data.setdefault(target, {})[dept] = rec
        hom._write_json(SUBMISSIONS_PATH, data)
    return rec


def save_uploads(target: str, files: list, dept: str | None = None) -> tuple[list, list]:
    """여러 파일 올리기 — dept를 고르고 파일 1개면 그 부서, 아니면 파일 이름의 부서명으로 자동 연결.
    반환 (저장한 [(부서, 파일명)], 오류 메시지 목록)."""
    depts = departments()
    done, errors = [], []
    for name, content in files:
        d = dept if (dept and len(files) == 1) else match_department(name, depts)
        if not d:
            errors.append(f'{name}: 파일 이름에서 부서를 찾지 못했습니다 — 부서를 고르고 한 개씩 올리세요.')
            continue
        try:
            save_submission(target, d, name, content)
            done.append((d, name))
        except ValueError as exc:
            errors.append(str(exc))
    return done, errors


def delete_submission(target: str, dept: str) -> None:
    _require_use()
    with _LOCK:
        data = _submissions()
        rec = (data.get(target) or {}).pop(dept, None)
        if rec:
            try:
                os.remove(os.path.join(SUBMIT_DIR, target, rec['file']))
            except OSError:
                pass
            hom._write_json(SUBMISSIONS_PATH, data)


def submission_file(target: str, dept: str) -> tuple[str, bytes] | None:
    rec = submissions(target).get(dept)
    if not rec:
        return None
    try:
        with open(os.path.join(SUBMIT_DIR, target, rec['file']), 'rb') as f:
            return rec['name'], f.read()
    except OSError:
        return None


def status(target: str) -> list:
    """부서별 제출 현황 [{'dept','contact','submitted','name','rows','at','by_name'}] — 담당자 명단 순서."""
    subs = submissions(target)
    contacts = {}
    for c in hom.load_contacts():
        contacts.setdefault(c['dept'], []).append(c.get('name') or c.get('email', ''))
    rows = []
    for d in departments():
        r = subs.get(d) or {}
        rows.append({'dept': d, 'contact': ', '.join(contacts.get(d, [])), 'submitted': bool(r),
                     'name': r.get('name', ''), 'rows': r.get('rows', ''), 'at': r.get('at', ''),
                     'by_name': r.get('by_name', '')})
    return rows


def merged(target: str) -> pd.DataFrame:
    """제출된 부서 파일을 합친 통합표 — 맨 앞에 '부서' 열, 열은 처음 나온 순서대로 합침."""
    frames = []
    for d in departments():
        f = submission_file(target, d)
        if not f:
            continue
        try:
            df = read_table(*f)
        except ValueError:
            continue
        if df.empty:
            continue
        df.insert(0, '제출부서' if '부서' in df.columns else '부서', d)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False).fillna('')


def merged_excel(target: str) -> bytes:
    df = merged(target)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as xw:
        df.to_excel(xw, index=False, sheet_name=f'업무분장_{target}')
        ws = xw.sheets[f'업무분장_{target}']
        from openpyxl.styles import Font, PatternFill
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='DDEBF7')
        for col in ws.columns:
            width = max(len(str(c.value or '')) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(10, width * 1.6), 60)
        ws.freeze_panes = 'A2'
    return buf.getvalue()
