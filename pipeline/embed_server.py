"""
BGE-M3 임베딩 서버(services/bge_server.py) 자동 기동/재사용 유틸리티.

process_project_researcher_fit.py, run_expertise.py가 실행 시 이 모듈의
ensure_embed_server()를 호출한다. 이미 서버가 응답 중이면 그대로 재사용하고
(모델 재로딩 비용을 피함), 응답하지 않으면 services/bge_server.py를 백그라운드
데몬 프로세스로 새로 기동한 뒤 준비될 때까지 폴링한다. 기동된 프로세스는
호출 스크립트가 끝나도 계속 살아 있어 다음 실행이 그대로 재사용할 수 있다.

pid 파일로 "이미 우리가 띄워서 로딩 중인 프로세스"를 추적해, 모델 로딩이
끝나기 전에 같은 스크립트를 다시 실행하거나 다른 스크립트가 동시에 실행돼도
중복으로 새 프로세스를 기동하지 않는다.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, RAW_DIR  # noqa: E402
sys.path.insert(0, BASE_DIR)
from services.llm import LLMError, embed  # noqa: E402

_RUNTIME_DIR = os.path.join(RAW_DIR, 'bge_server')
_PID_PATH = os.path.join(_RUNTIME_DIR, 'bge_server.pid')
_LOG_PATH = os.path.join(_RUNTIME_DIR, 'bge_server.log')
_SERVER_SCRIPT = os.path.join(BASE_DIR, 'services', 'bge_server.py')


def _is_pid_alive(pid: int) -> bool:
    if os.name == 'nt':
        # Windows에서는 os.kill(pid, 0)이 POSIX와 달리 프로세스 생존 확인용이
        # 아니다(0은 CTRL_C_EVENT로 취급됨) — OpenProcess로 직접 확인한다.
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _health_ok() -> bool:
    try:
        embed(['ping'])
        return True
    except LLMError:
        return False


def ensure_embed_server(wait_timeout: float = 180.0, poll_interval: float = 2.0) -> bool:
    """BGE-M3 임베딩 서버가 이미 응답하면 True를 바로 반환한다(재기동 없음).
    응답하지 않으면 services/bge_server.py를 백그라운드로 기동하고, 최대
    wait_timeout초 동안 poll_interval초 간격으로 준비 여부를 확인한다.
    시간 내 준비되지 않으면 False(호출부가 로그 경로를 안내하며 종료할 수 있음)."""
    if _health_ok():
        return True

    os.makedirs(_RUNTIME_DIR, exist_ok=True)

    already_starting = False
    if os.path.exists(_PID_PATH):
        with open(_PID_PATH, encoding='utf-8') as f:
            pid_text = f.read().strip()
        if pid_text.isdigit() and _is_pid_alive(int(pid_text)):
            already_starting = True

    if already_starting:
        print('[embed_server] 이미 기동 중인 BGE-M3 서버가 있음 — 준비될 때까지 대기')
    else:
        if not os.path.exists(_SERVER_SCRIPT):
            print(f'[embed_server] {_SERVER_SCRIPT} 없음 — 자동 기동 불가')
            return False
        print(f'[embed_server] BGE-M3 서버 응답 없음 — 백그라운드로 자동 기동 (로그: {_LOG_PATH})')
        log_file = open(_LOG_PATH, 'a', encoding='utf-8')
        # 호출 스크립트가 끝나도 서버 프로세스가 계속 살아있도록 분리한다.
        # start_new_session(setsid)은 POSIX 전용 — Windows에서 그대로 쓰면
        # CreateProcess가 WinError 87(매개 변수가 틀립니다)로 실패한다.
        if os.name == 'nt':
            detach_kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
        else:
            detach_kwargs = {'start_new_session': True}
        proc = subprocess.Popen(
            [sys.executable, _SERVER_SCRIPT],
            stdout=log_file, stderr=subprocess.STDOUT,
            **detach_kwargs,
        )
        with open(_PID_PATH, 'w', encoding='utf-8') as f:
            f.write(str(proc.pid))

    print(f'[embed_server] 서버 준비 대기 중(최대 {wait_timeout:.0f}초 — 모델 로딩에 시간이 걸릴 수 있음)...')
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if _health_ok():
            print('[embed_server] BGE-M3 서버 준비 완료')
            return True
        time.sleep(poll_interval)

    print(f'[embed_server] {wait_timeout:.0f}초 내에 서버가 준비되지 않았습니다 — 로그 확인: {_LOG_PATH}')
    return False
