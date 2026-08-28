"""
전문성 분석 LLM 체인(run_integration.py/run_analysis.py) 실행 전 환경 점검 스크립트

run_analysis.py 체인은 사내 LLM 호출이 많아 전체 실행에 수십 분~수 시간이 걸릴
수 있다. 실행 도중에 사내 LLM/BGE-M3/Confluence 설정 문제로 끊기면 그동안의
시간을 그대로 낭비하게 되므로, 이 스크립트로 미리 아래 항목을 빠르게 점검한다
(LLM 분석 자체는 호출하지 않음 — 연결 확인용 최소 요청만 보낸다).

점검 항목:
  1) .env(환경변수)에 필수 값(LLM2_API_URL, LLM2_MODEL) 설정 여부
  2) 사내 LLM(LLM2, thinkingcap) 엔드포인트 연결 확인
  3) 사내 Confluence 토큰 설정 + (project_confl_address.csv가 있으면) 실제 접속 확인
  4) BGE-M3 임베딩 서버 기동 확인 — 응답 없으면 자동 기동 후 준비될 때까지 대기
     (services/bge_server.py, pipeline/embed_server.py 재사용)
  5) 필수 파이썬 패키지 설치 여부(requests/pandas는 필수, atlassian/bs4/sklearn/
     umap-learn/xlwings는 해당 기능 사용 시에만 필요해 경고로만 표시)

사용법:
  python pipeline/run_ready.py [--skip-bge]
  --skip-bge : BGE-M3 서버 확인/자동기동을 건너뛴다(다른 항목만 빠르게 보고 싶을 때)

종료 코드: 문제(FAIL) 없으면 0, 하나라도 있으면 1 — run_integration.py가 이
값을 보고 본 실행 여부를 판단한다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 프로젝트 루트 (services.db용)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
from services.db import load_env_file  # noqa: E402

_PLACEHOLDER_TOKEN = 'your-confluence-personal-access-token'


class Check:
    def __init__(self, name: str, status: str, message: str):
        self.name = name       # 점검 항목명
        self.status = status   # 'ok' | 'warn' | 'fail'
        self.message = message


def _check_env_file() -> Check:
    from services.db import ENV_PATH
    if os.path.exists(ENV_PATH):
        return Check('.env', 'ok', f'존재함 ({ENV_PATH})')
    return Check(
        '.env', 'warn',
        f'{ENV_PATH}가 없습니다 — 환경변수를 셸/컨테이너에서 직접 주입하지 않는다면 '
        'cp .env.example .env 로 만든 뒤 값을 채우세요.',
    )


def _check_llm2_fields() -> Check:
    api_url = os.environ.get('LLM2_API_URL', '').strip()
    model = os.environ.get('LLM2_MODEL', '').strip()
    if not api_url:
        return Check('LLM2 설정', 'fail', '.env(또는 환경변수)에 LLM2_API_URL이 설정되어 있지 않습니다.')
    if not model:
        return Check('LLM2 설정', 'fail', '.env(또는 환경변수)에 LLM2_MODEL이 설정되어 있지 않습니다.')
    return Check('LLM2 설정', 'ok', f'{api_url} (model={model})')


def _check_llm2_endpoint(timeout: float = 15.0) -> Check:
    """call_llm()의 재시도/큰 max_tokens 없이, 연결 여부만 빠르게 확인하는
    최소 요청 — 실패해도 몇 초~timeout초 안에 끝나야 이 스크립트의 존재
    의미(끊기기 전에 빨리 확인)가 있다."""
    import requests

    api_url = os.environ['LLM2_API_URL']
    payload = {
        'model': os.environ['LLM2_MODEL'],
        'messages': [{'role': 'user', 'content': 'ping'}],
        'max_tokens': 4,
    }
    try:
        resp = requests.post(
            api_url, json=payload,
            headers={'Content-Type': 'application/json'}, timeout=timeout,
        )
    except requests.exceptions.ConnectionError:
        return Check('LLM2 연결', 'fail', f'{api_url}에 연결할 수 없습니다 (서버 미기동/네트워크 확인).')
    except requests.exceptions.Timeout:
        return Check('LLM2 연결', 'fail', f'{timeout:.0f}초 내에 응답이 없습니다.')
    except Exception as exc:  # noqa: BLE001
        return Check('LLM2 연결', 'fail', f'{type(exc).__name__}: {exc}')

    if resp.status_code != 200:
        return Check('LLM2 연결', 'fail', f'HTTP {resp.status_code}: {resp.text[:200]}')
    return Check('LLM2 연결', 'ok', '정상 응답')


def _check_confluence() -> list:
    checks = []
    token = os.environ.get('CONFLUENCE_TOKEN', '')
    if not token or token == _PLACEHOLDER_TOKEN:
        checks.append(Check(
            'Confluence 토큰', 'warn',
            # pipeline/project_summary.py._get_page_text()는 confl_address 유무로
            # 분기한다 — confl_address가 있으면 Confluence만 시도하고 실패하면
            # 그대로 건너뛴다(PDF 폴백은 안 봄). PDF 폴백은 confl_address가
            # 아예 없는 과제에서만 쓰인다(사용자 지적으로 문구 수정 —
            # data/processed/CLAUDE.md 참고).
            'CONFLUENCE_TOKEN이 설정되지 않았습니다 — confl_address가 있는 과제는 '
            '(PDF 폴백 여부와 무관하게) 전부 건너뛰어집니다. confl_address가 없는 '
            '과제만 data/raw/conflue_MPR/{과제명}.pdf 로 계속 처리됩니다.',
        ))
        return checks
    checks.append(Check('Confluence 토큰', 'ok', '설정됨'))

    csv_path = os.path.join(OUT_DIR, 'project_confl_address.csv')
    if not os.path.exists(csv_path):
        checks.append(Check(
            'Confluence 접속', 'warn',
            'project_confl_address.csv가 아직 없어 실제 접속 확인은 건너뜁니다 '
            '(run_expertise.py 실행 후 다시 확인 가능).',
        ))
        return checks

    import pandas as pd
    df = pd.read_csv(csv_path, encoding='utf-8-sig', dtype=str)
    addr = next((a for a in df.get('confl_address', []) if a), None)
    if not addr:
        checks.append(Check('Confluence 접속', 'warn', 'project_confl_address.csv에 유효한 주소가 없습니다.'))
        return checks

    import confluence_client
    try:
        confluence_client.fetch_page_text(addr)
        checks.append(Check('Confluence 접속', 'ok', f'페이지 조회 성공 ({addr})'))
    except confluence_client.ConfluenceError as exc:
        checks.append(Check('Confluence 접속', 'warn', f'{addr} 조회 실패: {exc}'))
    return checks


def _check_bge_server() -> Check:
    from embed_server import ensure_embed_server
    ok = ensure_embed_server()
    if ok:
        return Check('BGE-M3 임베딩 서버', 'ok', '응답 확인됨')
    return Check('BGE-M3 임베딩 서버', 'fail', '기동/응답 확인에 실패했습니다 — 로그를 확인하세요.')


def _check_packages() -> list:
    checks = []
    for pkg, level in (('requests', 'fail'), ('pandas', 'fail'),
                        ('atlassian', 'warn'), ('bs4', 'warn'),
                        ('sklearn', 'warn'), ('umap', 'warn'), ('xlwings', 'warn')):
        try:
            __import__(pkg)
            checks.append(Check(f'패키지: {pkg}', 'ok', '설치됨'))
        except ModuleNotFoundError:
            checks.append(Check(f'패키지: {pkg}', level, 'requirements.txt를 설치하세요.'))
    return checks


def run(skip_bge: bool = False) -> bool:
    """모든 점검을 실행하고 결과를 출력한다. FAIL이 하나도 없으면 True."""
    load_env_file()
    results: list = []

    results.append(_check_env_file())
    results.append(_check_llm2_fields())
    if os.environ.get('LLM2_API_URL', '').strip():
        results.append(_check_llm2_endpoint())
    results.extend(_check_confluence())

    if skip_bge:
        results.append(Check('BGE-M3 임베딩 서버', 'warn', '건너뜀(--skip-bge)'))
    else:
        results.append(_check_bge_server())

    results.extend(_check_packages())

    print('\n[run_ready] 환경 점검 결과:')
    icon = {'ok': '[OK]  ', 'warn': '[경고]', 'fail': '[실패]'}
    for c in results:
        print(f'  {icon[c.status]} {c.name}: {c.message}')

    fails = [c for c in results if c.status == 'fail']
    warns = [c for c in results if c.status == 'warn']
    print()
    if fails:
        print(f'[run_ready] 실패 {len(fails)}건, 경고 {len(warns)}건 — 위 [실패] 항목을 먼저 해결하세요.')
        return False
    if warns:
        print(f'[run_ready] 경고 {len(warns)}건이 있지만 실행은 가능합니다.')
    else:
        print('[run_ready] 모든 항목 정상 — 실행 가능합니다.')
    return True


if __name__ == '__main__':
    ready = run(skip_bge='--skip-bge' in sys.argv)
    sys.exit(0 if ready else 1)
