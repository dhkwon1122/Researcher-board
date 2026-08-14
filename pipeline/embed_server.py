"""
BGE-M3 임베딩 서버(services/bge_server.py) 자동 기동/재사용 유틸리티.

run_expertise.py가 실행 시 이 모듈의 ensure_embed_server()를 호출해
process_researcher_similarity.py가 쓸 서버를 미리 띄워 둔다. 이미 서버가
응답 중이면 그대로 재사용하고
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


_DEFAULT_WAIT_TIMEOUT = 600.0  # 10분 — BGE-M3 첫 로딩+첫 추론(CPU 환경 등)은 오래 걸릴 수 있음


def ensure_embed_server(wait_timeout: float | None = None, poll_interval: float = 2.0) -> bool:
    """BGE-M3 임베딩 서버가 이미 응답하면 True를 바로 반환한다(재기동 없음).
    응답하지 않으면 services/bge_server.py를 백그라운드로 기동하고, 최대
    wait_timeout초 동안 poll_interval초 간격으로 준비 여부를 확인한다.
    시간 내 준비되지 않으면 False(호출부가 로그 경로를 안내하며 종료할 수 있음).

    wait_timeout 기본값은 EMBED_SERVER_WAIT_TIMEOUT 환경변수(없으면 600초)를
    따른다. 모델 로딩 자체는 포트가 열리기 전이라 헬스체크가 곧바로(순간적인
    연결 실패로) 반환되지만, 로딩이 끝난 직후 첫 실제 추론 요청은 CPU 환경 등에서
    응답까지 꽤 걸릴 수 있어 그동안 헬스체크 한 번이 블로킹된다 — 너무 짧은
    타임아웃을 주면 서버가 실제로는 정상 응답했는데도(로그에 '200 OK'가 남음)
    이 함수는 그 응답을 못 보고 먼저 포기해 버릴 수 있다. 서버는 한 번 뜨면
    다음 실행부터 그대로 재사용되므로, 넉넉하게 기다리는 편이 유리하다."""
    if wait_timeout is None:
        try:
            wait_timeout = float(os.environ.get('EMBED_SERVER_WAIT_TIMEOUT', str(_DEFAULT_WAIT_TIMEOUT)))
        except ValueError:
            wait_timeout = _DEFAULT_WAIT_TIMEOUT

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

    print(f'[embed_server] 서버 준비 대기 중(최대 {wait_timeout:.0f}초 — 첫 로딩/첫 추론은 오래 걸릴 수 있음)...')
    start = time.monotonic()
    deadline = start + wait_timeout
    last_heartbeat = start
    while time.monotonic() < deadline:
        if _health_ok():
            print('[embed_server] BGE-M3 서버 준비 완료')
            return True
        now = time.monotonic()
        if now - last_heartbeat >= 30:
            print(f'[embed_server] 아직 대기 중... ({now - start:.0f}초 경과, 로그: {_LOG_PATH})')
            last_heartbeat = now
        time.sleep(poll_interval)

    print(f'[embed_server] {wait_timeout:.0f}초 내에 서버가 준비되지 않았습니다 — 로그 확인: {_LOG_PATH}')
    return False
