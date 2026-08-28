"""
관리자 화면 "데이터 업데이트" 탭의 백엔드 — 매니페스트 등록 파일(pipeline/sources.py)
중 웹에서 직접 갱신 가능한 20개(리더십진단(7)·comments_raw(10, 원본 없음) 제외)를
브라우저로 업로드해 각 pipeline/process_*.py를 그 자리에서 돌린다.

전제(사용자 확정): 원본이 사내 DRM으로 보호돼 있을 수 있으므로, 업로드 전에
사용자가 자기 PC의 Excel에서 열어 '다른 이름으로 저장'으로 DRM을 해제한
사본을 올린다 — 이 서버(Linux, xlwings/Excel 없음)는 평범한 xlsx만 받는다는
전제로 동작한다(excel_reader.read_xlsx()가 xlwings 임포트 실패 시 자동으로
openpyxl 폴백을 쓰므로 이 서버에서도 그대로 읽힌다).

구조:
  - data/web_updates/<key>/ 에 업로드 파일을 보관한다(행마다 폴더 하나).
    'exact' 모드는 그 파일의 처리기가 요구하는 정확한 파일명으로 저장(폴더
    안 다른 파일은 정리), 'wildcard' 모드는 원본 브라우저 파일명을 그대로
    보존해(폴더를 비우고 새로 저장) 각 처리기의 raw_dir 오버라이드 분기가
    기존 와일드카드 매칭(pipeline/source_files.py)으로 알아서 찾게 한다.
    job_profile(직무이력)만 파일 두 개(legacy/new)를 따로 받는 'dual' 모드.
  - 실행 결과는 data/processed/web_pipeline_runs.csv에 키당 1행으로 남긴다
    (최종실행이력/실행결과) — 사용자 확정: DB 대신 CSV.
  - 동시 실행 방지 락은 파일 기반이다(data/web_updates/.lock.json) — 이
    앱이 gunicorn --workers 2로 뜨기 때문에(Dockerfile) 워커 프로세스
    메모리상의 플래그로는 두 워커 간에 공유가 안 된다.
  - "전체/선택 실행"은 백그라운드 스레드에서 돈다 — 브라우저 탭을 닫아도
    서버(그 gunicorn 워커 프로세스)가 살아있는 한 계속 진행되고, 화면은
    dcc.Interval로 몇 초마다 run log/락 상태를 다시 읽어와 갱신한다
    (사용자 확정).
  - 각 process_*.py는 성공 여부만 반환하고 실패 사유는 print()로만 남기는
    경우가 많아, stdout을 캡처해 마지막 [ERROR]/[SKIP] 줄을 실패 사유로
    보여준다(사용자 확정 — "실제 처리를 시도해서 에러 메시지를 보여주는
    걸로 충분").
"""
from __future__ import annotations

import contextlib
import csv
import glob
import importlib
import io
import json
import os
import sys
import threading
import time
from datetime import date, datetime

import pandas as pd

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

from paths import BASE_DIR, OUT_DIR  # noqa: E402
from raw_archive import archive_raw_bytes  # noqa: E402

WEB_UPDATES_DIR = os.path.join(BASE_DIR, 'data', 'web_updates')
RUN_LOG_PATH = os.path.join(OUT_DIR, 'web_pipeline_runs.csv')
LOCK_PATH = os.path.join(WEB_UPDATES_DIR, '.lock.json')

# 락이 이 시간(초)보다 오래됐으면 죽은 것으로 보고 무시한다(워커가 죽는 등
# release_lock()이 못 불린 경우 영구 잠김 방지).
_LOCK_STALE_SECONDS = 30 * 60

JOB_PROFILE_LEGACY_FILE = "임직원_직무이력('18.5월_이전).xlsx"

# (key, label, pipeline 모듈명, 업로드 안내문구, mode)
# mode: 'exact'(정확한 파일명 하나) | 'wildcard'(패턴, 원본 파일명 유지) |
#       'dual'(직무이력 전용 — legacy/new 두 슬롯)
MANIFEST = [
    dict(key='researchers', label='인력현황', module='process_researchers',
         hint='예: 202608_That Month Headcount_*.xlsx 또는 *_End of Month Headcount_*.xlsx',
         mode='wildcard'),
    dict(key='evaluations', label='T&P(평가)', module='process_tp_evaluation',
         hint='예: T&P 기본 인사 정보 *.xlsx', mode='wildcard', needs_valid_date=True),
    dict(key='patents', label='특허', module='process_patents',
         hint='특허 리스트.xlsx', mode='exact', dest_filename='특허 리스트.xlsx'),
    dict(key='nurturing', label='양성이력', module='process_nurturing',
         hint='양성_인력_현황.xlsx', mode='exact', dest_filename='양성_인력_현황.xlsx'),
    dict(key='awards', label='시상이력', module='process_awards',
         hint='예: 시상 세부사항 *.xlsx', mode='wildcard'),
    dict(key='education', label='학력', module='process_education',
         hint='예: 임직원 학력 *.xlsx', mode='wildcard'),
    dict(key='incentive_selection', label='핵심이력', module='process_incentive',
         hint='핵심이력.xlsx', mode='exact', dest_filename='핵심이력.xlsx'),
    dict(key='publications', label='논문', module='process_publications',
         hint='개인별논문현황_2016_2026.xlsx', mode='exact',
         dest_filename='개인별논문현황_2016_2026.xlsx'),
    dict(key='hr_orders', label='인사발령', module='process_personnel_orders',
         hint='예: report_*.xlsx', mode='wildcard'),
    dict(key='tasks_information', label='과제정보', module='process_task_information',
         hint='과제정보.xlsx', mode='exact', dest_filename='과제정보.xlsx'),
    dict(key='core_technology', label='핵심기술', module='process_core_technology',
         hint='핵심기술.xlsx', mode='exact', dest_filename='핵심기술.xlsx', needs_valid_date=True),
    dict(key='tech_ownership', label='보유기술', module='process_tech_ownership',
         hint='보유기술.xlsx', mode='exact', dest_filename='보유기술.xlsx', needs_valid_date=True),
    dict(key='job_profile', label='직무이력', module='process_job_profile',
         hint=f"① {JOB_PROFILE_LEGACY_FILE}(선택 — 최초 1회만 필요) "
              "② 내 리포트 *.xlsx(필수, 매번 최신 파일)",
         mode='dual', needs_valid_date=True),
    dict(key='work_objective_24', label='업무목표24', module='process_work_objective',
         hint='업무목표24.xlsx', mode='exact', dest_filename='업무목표24.xlsx', needs_valid_date=True),
    dict(key='work_objective_25', label='업무목표25', module='process_work_objective',
         hint='업무목표25.xlsx', mode='exact', dest_filename='업무목표25.xlsx', needs_valid_date=True),
    dict(key='work_objective_26', label='업무목표26', module='process_work_objective',
         hint='업무목표26.xlsx', mode='exact', dest_filename='업무목표26.xlsx', needs_valid_date=True),
    dict(key='tasks', label='과제참여이력', module='process_tasks',
         hint='개인별과제투입기간데이터_260114.xlsb', mode='exact',
         dest_filename='개인별과제투입기간데이터_260114.xlsb'),
    dict(key='project_confl_address', label='과제별컨플', module='process_project_confl',
         hint='과제별컨플.xlsx', mode='exact', dest_filename='과제별컨플.xlsx'),
    dict(key='job_profile_info_standard', label='직무정보(DS)', module='process_job_profile_standard',
         hint='직무정보_표준.xlsx', mode='exact', dest_filename='직무정보_표준.xlsx'),
    dict(key='job_profile_info_sait', label='직무정보(SAIT자체)', module='process_job_profile_sait',
         hint='직무정보_부서.xlsx', mode='exact', dest_filename='직무정보_부서.xlsx'),
]
_BY_KEY = {item['key']: item for item in MANIFEST}

MAX_UPLOAD_BYTES = int(os.environ.get('WEB_UPDATE_MAX_UPLOAD_BYTES', str(50 * 1024 * 1024)))  # 50MB


# ── 사내 API 연동 확장 포인트 ─────────────────────────────────────────────────
# 지금은 파일 업로드만 지원하지만, 최종 목표는 사내 API에서 직접 데이터를
# 받는 것(사용자 확정) — 그때 가서 화면을 다시 만들지 않아도 되도록, 각
# 항목에 "API에서 가져오기" 훅을 미리 심어 둔다. 지금은 전부 비어 있어
# (register_api_fetch()가 호출된 적 없음) 화면의 API 아이콘을 눌러도
# "아직 연동되지 않음" 결과가 실행결과 칸에 그대로 남을 뿐이고, 실제
# 코드/데이터 흐름에는 아무 영향이 없다.
#
# 실제 연동 시 붙이는 방법(신규 파일, 예: services/hr_api_client.py):
#   from services.web_pipeline_runner import register_api_fetch
#   def _fetch_researchers(key):
#       resp = requests.get(...)
#       return [(filename, resp.content, None)]   # slot은 job_profile만 사용
#   register_api_fetch('researchers', _fetch_researchers)
# 이렇게 등록만 하면 화면 변경 없이 바로 그 항목의 API 아이콘이 동작한다
# (run_one(..., via_api=True)가 이 훅을 호출해 파일 업로드와 완전히 같은
# 경로 — 실행/락/로그 — 를 그대로 탄다).
for _item in MANIFEST:
    _item.setdefault('api_fetch', None)
    _item.setdefault('needs_valid_date', False)


def register_api_fetch(key: str, fetch_fn) -> None:
    """key 항목의 "API에서 가져오기" 구현을 등록한다.
    fetch_fn(key: str) -> list[(filename: str, content: bytes, slot: str | None)]
    실패 시 예외를 던지면 그대로 실행결과에 표시된다(run_one과 동일한 처리)."""
    if key not in _BY_KEY:
        raise KeyError(f'알 수 없는 항목: {key}')
    _BY_KEY[key]['api_fetch'] = fetch_fn


def has_api(key: str) -> bool:
    return _BY_KEY[key].get('api_fetch') is not None


def _key_dir(key: str) -> str:
    d = os.path.join(WEB_UPDATES_DIR, key)
    os.makedirs(d, exist_ok=True)
    return d


# ── 업로드 저장 ──────────────────────────────────────────────────────────────

def save_upload(key: str, filename: str, content_bytes: bytes, slot: str | None = None) -> str:
    """업로드된 파일을 저장하고 최종 저장 경로를 반환한다.
    slot은 job_profile(mode='dual')에서만 쓴다: 'legacy' | 'new'."""
    item = _BY_KEY[key]
    d = _key_dir(key)

    if item['mode'] == 'exact':
        for stale in glob.glob(os.path.join(d, '*')):
            if os.path.basename(stale) not in ('.uploaded_at',):
                os.remove(stale)
        dest = os.path.join(d, item['dest_filename'])

    elif item['mode'] == 'wildcard':
        for stale in glob.glob(os.path.join(d, '*')):
            os.remove(stale)
        dest = os.path.join(d, filename)

    elif item['mode'] == 'dual':
        if slot == 'legacy':
            dest = os.path.join(d, JOB_PROFILE_LEGACY_FILE)
        elif slot == 'new':
            for stale in glob.glob(os.path.join(d, '*')):
                base = os.path.basename(stale)
                if base != JOB_PROFILE_LEGACY_FILE:
                    os.remove(stale)
            dest = os.path.join(d, filename)
        else:
            raise ValueError("job_profile 업로드는 slot='legacy' 또는 'new'가 필요합니다")
    else:
        raise ValueError(f'알 수 없는 mode: {item["mode"]}')

    with open(dest, 'wb') as f:
        f.write(content_bytes)
    with open(os.path.join(d, '.uploaded_at'), 'w') as f:
        f.write(datetime.now().isoformat())

    # 원본을 덮어쓰기 전에 위에서 기존 파일을 지웠으므로, 여기서는 이번에
    # 올라온 원본을 그대로 아카이브에 남긴다(무제한 보관 — 사용자 확정,
    # data/processed/CLAUDE.md 참고). 아카이브 실패가 업로드 자체를 막으면
    # 안 되므로 실패해도 무시하고 진행한다.
    try:
        archive_raw_bytes(content_bytes, filename, category=key)
    except OSError as exc:
        print(f'[web_pipeline_runner] 원본 아카이브 실패(무시하고 계속) {key}: {exc}')

    return dest


def uploaded_files(key: str) -> list[str]:
    """이 항목 폴더에 현재 올라와 있는 파일 목록(전체 경로, .uploaded_at 제외)."""
    d = _key_dir(key)
    return sorted(
        p for p in glob.glob(os.path.join(d, '*'))
        if os.path.basename(p) != '.uploaded_at'
    )


def has_upload(key: str) -> bool:
    item = _BY_KEY[key]
    files = uploaded_files(key)
    if item['mode'] == 'dual':
        # 최소한 '내 리포트 *.xlsx'(new)는 있어야 실행 가능 — legacy는 선택.
        return any(os.path.basename(p) != JOB_PROFILE_LEGACY_FILE for p in files)
    return bool(files)


def uploaded_at(key: str) -> str:
    path = os.path.join(_key_dir(key), '.uploaded_at')
    if not os.path.exists(path):
        return ''
    with open(path) as f:
        try:
            return datetime.fromisoformat(f.read().strip()).strftime('%y-%m-%d %H:%M')
        except ValueError:
            return ''


# ── 실행 로그(CSV) ───────────────────────────────────────────────────────────

_LOG_COLUMNS = ['key', 'last_run_at', 'status', 'message']


def _read_log() -> dict[str, dict]:
    if not os.path.exists(RUN_LOG_PATH):
        return {}
    df = pd.read_csv(RUN_LOG_PATH, encoding='utf-8-sig', dtype=str).fillna('')
    return {row['key']: row.to_dict() for _, row in df.iterrows()}


def _write_log(log: dict[str, dict]) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = [log[k] for k in log]
    with open(RUN_LOG_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=_LOG_COLUMNS, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in _LOG_COLUMNS})


def _record_result(key: str, status: str, message: str) -> None:
    log = _read_log()
    log[key] = {
        'key': key,
        'last_run_at': datetime.now().strftime('%y-%m-%d %H:%M'),
        'status': status,
        'message': message,
    }
    _write_log(log)


def last_result(key: str) -> dict:
    return _read_log().get(key, {'last_run_at': '', 'status': '', 'message': ''})


# ── 동시 실행 방지 락(파일 기반 — 워커 프로세스 2개 간 공유) ──────────────────

_local_lock = threading.Lock()


def lock_status() -> dict | None:
    """실행 중이면(그리고 오래되지 않았으면) 락 정보를, 아니면 None."""
    if not os.path.exists(LOCK_PATH):
        return None
    try:
        with open(LOCK_PATH, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - data.get('started_at_ts', 0) > _LOCK_STALE_SECONDS:
        return None  # 죽은 락으로 간주 — acquire_lock()이 덮어씀
    return data


def try_acquire_lock(keys: list[str]) -> bool:
    """락을 잡으면 True, 이미 다른 실행이 진행 중이면 False."""
    with _local_lock:
        if lock_status() is not None:
            return False
        os.makedirs(WEB_UPDATES_DIR, exist_ok=True)
        data = {
            'started_at': datetime.now().strftime('%y-%m-%d %H:%M:%S'),
            'started_at_ts': time.time(),
            'keys': keys,
            'done': [],
        }
        with open(LOCK_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return True


def _mark_progress(key: str) -> None:
    if not os.path.exists(LOCK_PATH):
        return
    try:
        with open(LOCK_PATH, encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('done', []).append(key)
        with open(LOCK_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except (OSError, json.JSONDecodeError):
        pass


def release_lock() -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(LOCK_PATH)


# ── 실행 ─────────────────────────────────────────────────────────────────────

def _last_meaningful_line(output: str) -> str:
    """캡처한 stdout에서 실패 사유로 보여줄 만한 마지막 줄(ERROR 우선,
    없으면 SKIP/WARN, 그것도 없으면 마지막 비어있지 않은 줄)을 고른다."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    for tag in ('[ERROR]', '[SKIP]', '[WARN]'):
        for ln in reversed(lines):
            if tag in ln:
                return ln
    return lines[-1] if lines else ''


def run_one(key: str, via_api: bool = False, valid_date: date | None = None) -> dict:
    """항목 하나를 실제로 처리한다 — process_*.py의 stdout/예외를 캡처해
    실행결과 메시지를 만든다. run log에도 즉시 반영한다.

    via_api=True면 파일 업로드 대신 등록된 API 훅(register_api_fetch())으로
    먼저 데이터를 받아 그 폴더에 저장한 뒤, 이후 처리는 업로드 경로와
    완전히 동일하다 — 아직 훅이 없으면(현재 전 항목이 그렇다) 바로
    "미연동" 실패로 기록하고 끝난다.

    valid_date: needs_valid_date=True인 항목(evaluations/tech_ownership/
    job_profile/work_objective_*)에서 이번 업로드분의 기준 연/월로 넘겨준다
    (관리자가 화면에서 지정, 기본값은 process_*.py 쪽에서 오늘로 처리)."""
    item = _BY_KEY[key]
    raw_dir = _key_dir(key)
    buf = io.StringIO()
    try:
        if via_api:
            fetch_fn = item.get('api_fetch')
            if fetch_fn is None:
                _record_result(key, '실패', '아직 사내 API 연동이 준비되지 않았습니다 — '
                                            '지금은 파일 업로드를 이용해주세요.')
                return last_result(key)
            for filename, content, slot in fetch_fn(key):
                save_upload(key, filename, content, slot=slot)

        if not has_upload(key):
            _record_result(key, '실패', '업로드된 파일이 없습니다.')
            return last_result(key)

        with contextlib.redirect_stdout(buf):
            if key == 'job_profile':
                import merge_job_profile_source
                importlib.reload(merge_job_profile_source)
                merge_job_profile_source.run(raw_dir=raw_dir)

            module = importlib.import_module(item['module'])
            importlib.reload(module)
            if item['needs_valid_date'] and valid_date is not None:
                ok = module.process(raw_dir=raw_dir, valid_date=valid_date)
            else:
                ok = module.process(raw_dir=raw_dir)

        output = buf.getvalue()
        if ok:
            summary = _last_meaningful_line(output) or '성공'
            _record_result(key, '성공', summary)
        else:
            _record_result(key, '실패', _last_meaningful_line(output) or '처리 실패(사유 불명 — 로그 확인 필요)')

    except Exception as exc:  # noqa: BLE001 — 실행결과 칸에 그대로 보여줘야 함
        output = buf.getvalue()
        reason = _last_meaningful_line(output)
        message = f'{exc}' + (f' ({reason})' if reason else '')
        _record_result(key, '실패', message[:500])

    return last_result(key)


def run_many(keys: list[str], via_api: bool = False, valid_dates: dict[str, date] | None = None) -> None:
    """백그라운드 스레드에서 순차 실행 — 브라우저가 꺼져도 계속 진행.

    valid_dates: {key: date} — needs_valid_date 항목에 대해 관리자가 지정한
    기준 연/월. 지정 없는 키는 process_*.py 쪽 기본값(오늘)이 적용된다."""
    valid_dates = valid_dates or {}
    try:
        for key in keys:
            run_one(key, via_api=via_api, valid_date=valid_dates.get(key))
            _mark_progress(key)
    finally:
        release_lock()


def start_run(keys: list[str], valid_dates: dict[str, date] | None = None) -> bool:
    """keys를 백그라운드로 실행 시작. 이미 실행 중이면 False(시작 안 함).

    valid_dates: run_many()로 그대로 전달 — needs_valid_date 항목의 기준 연/월."""
    keys = [k for k in keys if k in _BY_KEY]
    if not keys:
        return False
    if not try_acquire_lock(keys):
        return False
    for key in keys:
        _record_result(key, '실행중', '')
    t = threading.Thread(target=run_many, args=(keys,), kwargs={'valid_dates': valid_dates}, daemon=True)
    t.start()
    return True


def start_run_via_api(keys: list[str]) -> bool:
    """화면의 "API로 가져오기" 아이콘용 — start_run()과 동일하지만 업로드
    폴더 대신 register_api_fetch()로 등록된 훅을 먼저 호출한다. 훅이 없는
    항목은 그 자리에서 "미연동" 실패로 기록된다(현재는 전부 그렇다)."""
    keys = [k for k in keys if k in _BY_KEY]
    if not keys:
        return False
    if not try_acquire_lock(keys):
        return False
    for key in keys:
        _record_result(key, '실행중', '')
    t = threading.Thread(target=run_many, args=(keys,), kwargs={'via_api': True}, daemon=True)
    t.start()
    return True


def runnable_keys() -> list[str]:
    """'전체 실행' 대상 — 업로드된 파일이 있는 항목만(실패 방지)."""
    return [item['key'] for item in MANIFEST if has_upload(item['key'])]


# ── 화면 렌더용 상태 스냅샷 ──────────────────────────────────────────────────

def snapshot() -> list[dict]:
    lock = lock_status()
    running_keys = set(lock['keys']) if lock else set()
    rows = []
    for item in MANIFEST:
        result = last_result(item['key'])
        status = result.get('status', '')
        if item['key'] in running_keys:
            status = '실행중'
        rows.append({
            'key': item['key'],
            'label': item['label'],
            'hint': item['hint'],
            'mode': item['mode'],
            'needs_valid_date': item['needs_valid_date'],
            'has_upload': has_upload(item['key']),
            'has_api': has_api(item['key']),
            'uploaded_at': uploaded_at(item['key']),
            'uploaded_filenames': [os.path.basename(p) for p in uploaded_files(item['key'])],
            'last_run_at': result.get('last_run_at', ''),
            'status': status,
            'message': result.get('message', ''),
        })
    return rows


def is_running() -> bool:
    """20개 항목 파이프라인 실행이 진행 중인지(DB 반영 실행 중은 별도 —
    is_db_load_running() 참고, 락은 같이 쓰지만 종류가 다르다)."""
    lock = lock_status()
    return bool(lock and lock.get('keys') != ['__db_load__'])


def any_running() -> bool:
    """파이프라인 실행이든 DB 반영이든 뭐든 하나라도 진행 중이면 True —
    버튼 비활성화 판단용(같은 락을 공유하므로 동시 진행 자체가 안 됨)."""
    return lock_status() is not None


# ── DB 반영("데이터 업데이트" 화면의 별도 버튼) ────────────────────────────────
# pipeline/load_to_db.py를 그대로 재사용한다 — 순수 CSV→Postgres라 DRM/xlwings와
# 무관하게 리눅스 서버에서 문제없이 돈다. 파이프라인 실행 락을 그대로 같이
# 써서 "CSV 갱신 중에 DB 반영" 같은 동시 진행을 막는다(둘 다 data/processed를
# 건드림).

DB_LOG_PATH = os.path.join(OUT_DIR, 'web_db_load_runs.csv')


def _record_db_result(status: str, message: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(DB_LOG_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['last_run_at', 'status', 'message'],
                            quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerow({
            'last_run_at': datetime.now().strftime('%y-%m-%d %H:%M'),
            'status': status,
            'message': message[:500],
        })


def db_load_status() -> dict:
    if not os.path.exists(DB_LOG_PATH):
        return {'last_run_at': '', 'status': '', 'message': ''}
    df = pd.read_csv(DB_LOG_PATH, encoding='utf-8-sig', dtype=str).fillna('')
    return df.iloc[0].to_dict() if len(df) else {'last_run_at': '', 'status': '', 'message': ''}


def _run_db_load() -> None:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            import load_to_db
            importlib.reload(load_to_db)
            load_to_db.load()
        output = buf.getvalue()
        if 'DATABASE_URL 미설정' in output:
            _record_db_result('실패', 'DATABASE_URL 미설정 — DB 연결 정보가 없어 반영하지 못했습니다.')
        else:
            _record_db_result('성공', _last_meaningful_line(output) or '완료')
    except Exception as exc:  # noqa: BLE001
        _record_db_result('실패', f'{exc}'[:500])
    finally:
        release_lock()


def start_db_load() -> bool:
    """DB 반영을 백그라운드로 시작. 이미 다른 실행이 진행 중이면 False."""
    if not try_acquire_lock(['__db_load__']):
        return False
    _record_db_result('실행중', '')
    t = threading.Thread(target=_run_db_load, daemon=True)
    t.start()
    return True


def is_db_load_running() -> bool:
    lock = lock_status()
    return bool(lock and lock.get('keys') == ['__db_load__'])
