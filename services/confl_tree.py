"""
컨플루언스 하위 페이지 목록 추출(2026-10, 사용자 요청) — "데이터 업데이트" 탭 하단.

상위 페이지(페이지 ID 또는 주소)를 입력하면 그 아래 모든 하위 페이지(자식 → 손자 →
최하위까지, 또는 지정한 단계까지)의 제목과 페이지 ID(10자리)를 엑셀로 내려받게 한다.
과제별컨플의 컨플 주소(페이지 ID)를 일일이 확인하던 작업을 대신한다.

하위 페이지가 많으면 요청 시간이 길어질 수 있어(gunicorn 워커 타임아웃) 백그라운드
스레드로 실행하고 화면은 진행 상황을 폴링한다. 동시에 하나의 작업만 허용한다.

상태/결과는 **파일**(data/web_updates/confl_tree/)에 둔다 — 앱이 gunicorn 워커 2개로
돌아 "시작 요청을 받은 워커"와 "폴링 요청을 받은 워커"가 서로 다를 수 있는데, 프로세스
메모리에만 두면 폴링이 다른 워커로 가는 순간 진행 중인데도 "대기 중"으로 보였다
(2026-10 사용자 신고: "추출 중인지 아닌지 모르겠다"). 결과 파일은 다음 실행 때 덮어쓰며
권한은 소유자 전용(0600)으로 둔다.
"""

import io
import json
import os
import sys
import threading
import time
from datetime import datetime

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import confluence_client  # noqa: E402

EXCEL_HEADERS = ['단계', '제목', '페이지 ID', '상위 페이지 제목', '상위 페이지 ID', '경로']

# 'running' 상태가 이 시간(초) 이상 갱신되지 않으면 워커가 죽은 것으로 보고 중단 처리한다.
_STALE_SECONDS = 120
_WRITE_INTERVAL = 0.5   # 진행 상황 파일 갱신 최소 간격(초)

_lock = threading.Lock()
_last_write = 0.0


def _dir() -> str:
    from services import web_pipeline_runner as wpr   # WEB_UPDATES_DIR (테스트에서 바꿀 수 있게 호출 시점에 읽음)
    d = os.path.join(wpr.WEB_UPDATES_DIR, 'confl_tree')
    os.makedirs(d, exist_ok=True)
    return d


def _state_path() -> str:
    return os.path.join(_dir(), 'state.json')


def _rows_path() -> str:
    return os.path.join(_dir(), 'rows.json')


def _write_json_atomic(path: str, data) -> None:
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _read_state() -> dict:
    try:
        with open(_state_path(), encoding='utf-8') as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    base = {'status': 'idle', 'message': '', 'count': 0, 'root': '', 'started_at': 0.0,
            'updated_at': 0.0, 'finished_at': ''}
    base.update(st)
    if base['status'] == 'running' and time.time() - float(base['updated_at'] or 0) > _STALE_SECONDS:
        base.update(status='error', message='작업이 응답 없이 중단됐습니다(서버 재시작 등). 다시 실행하세요.')
    return base


def _save_state(**updates) -> dict:
    st = _read_state()
    st.update(updates)
    st['updated_at'] = time.time()
    _write_json_atomic(_state_path(), st)
    return st


def snapshot() -> dict:
    st = _read_state()
    st['has_result'] = st['status'] == 'done' and os.path.exists(_rows_path())
    st['elapsed'] = int(time.time() - float(st['started_at'])) if st['status'] == 'running' and st['started_at'] else 0
    return st


def is_running() -> bool:
    return _read_state()['status'] == 'running'


def start(root_address: str, max_depth: int | None) -> tuple[bool, str]:
    """작업 시작. 이미 실행 중이면 (False, 사유)."""
    root = confluence_client.normalize_address(root_address)
    if not root:
        return False, '상위 페이지 주소(또는 페이지 ID)를 입력하세요.'
    with _lock:
        if is_running():
            return False, '이미 하위 페이지를 추출하는 중입니다. 끝난 뒤 다시 시도하세요.'
        try:
            os.remove(_rows_path())
        except OSError:
            pass
        _save_state(status='running', message='시작', count=0, root=root,
                    started_at=time.time(), finished_at='')
    threading.Thread(target=_run, args=(root, max_depth), daemon=True).start()
    return True, ''


def _run(root: str, max_depth: int | None) -> None:
    global _last_write

    def _progress(count: int, title: str) -> None:
        global _last_write
        now = time.time()
        if now - _last_write >= _WRITE_INTERVAL:
            _last_write = now
            _save_state(count=count, message=title)

    try:
        rows = confluence_client.crawl_descendants(root, max_depth=max_depth, progress=_progress)
        _write_json_atomic(_rows_path(), rows)
        _save_state(status='done', count=len(rows), message='완료',
                    finished_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    except Exception as exc:  # noqa: BLE001 — 사유를 화면에 그대로 보여줘야 함
        _save_state(status='error', message=str(exc)[:500],
                    finished_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


def build_workbook_bytes(rows: list[dict]) -> bytes:
    """결과 행을 엑셀(xlsx) 바이트로. 페이지 ID는 '3862782334'처럼 숫자 서식이 아닌
    텍스트 셀로 써서 엑셀이 지수/실수로 바꾸지 않게 한다."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = '하위 페이지'
    ws.append(EXCEL_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in rows:
        ws.append([r['depth'], r['title'], str(r['id']), r['parent_title'], str(r['parent_id']), r['path']])
    for row in ws.iter_rows(min_row=2):
        for idx in (2, 4):   # 페이지 ID 열들을 텍스트 서식으로
            row[idx].number_format = '@'
    widths = [6, 50, 14, 40, 14, 80]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def result_workbook() -> tuple[str, bytes] | None:
    """(파일명, 바이트) — 결과가 없으면 None."""
    st = _read_state()
    if st['status'] != 'done':
        return None
    try:
        with open(_rows_path(), encoding='utf-8') as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return None
    if not rows:
        return None
    return f'컨플_하위페이지_{st["root"]}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx', build_workbook_bytes(rows)
