"""
run_expertise.py(전처리) + run_analysis.py(LLM 체인)를 한 번에 순차 실행하는
통합 스크립트.

run_analysis.py 단계는 사내 LLM/BGE-M3 호출이 많아 전체 실행에 수십 분~수
시간이 걸릴 수 있다. 그 긴 실행이 환경 설정 문제(사내 LLM 미기동, BGE-M3
서버 문제, Confluence 인증 오류 등)로 중간에 끊기면 이미 지난 시간을 그대로
버리게 되므로, 본 실행 전에 반드시 pipeline/run_ready.py로 환경을 먼저
점검한다 — 여기서 문제(FAIL)가 발견되면 곧바로 중단하고, 문제를 고친 뒤 다시
실행하도록 안내한다(--force로 점검을 무시하고 강행 가능, --skip-ready로 점검
자체를 건너뛰기 가능 — 둘 다 문제를 이미 알고 있고 굳이 기다리고 싶지 않을
때만 사용).

실행 순서:
  0) pipeline/run_ready.py  환경 점검 (--skip-ready 아니면 항상 먼저 실행)
  1) pipeline/run_expertise.py  원천 데이터 전처리 (LLM 호출 없음)
  2) pipeline/run_analysis.py   전문성 분석 LLM 체인 (4단계, 비용 발생)

사용법:
  python pipeline/run_integration.py
    [--skip-ready] [--force] [--skip-bge]
    [--refresh-journals] [--refresh-judgments] [--top-k 5]

  --skip-ready : 0단계(환경 점검) 자체를 건너뛴다.
  --force      : 0단계에서 FAIL이 나와도 무시하고 1~2단계를 강행한다.
  --skip-bge   : 0단계 중 BGE-M3 서버 확인/자동기동만 건너뛴다(run_ready.py로 그대로 전달).
  그 외 옵션은 run_analysis.py에 그대로 전달된다(자세한 의미는 그 파일 참고).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _parse_top_k_arg(argv: list) -> int | None:
    if '--top-k' in argv:
        idx = argv.index('--top-k')
        if idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                pass
    return None


def run(skip_ready: bool = False, force: bool = False, skip_bge: bool = False, **analysis_kwargs) -> bool:
    """0) 환경 점검 → 1) run_expertise → 2) run_analysis 순서로 실행한다.
    환경 점검에서 FAIL이 있고 force가 아니면 여기서 중단하고 False를 반환한다
    (1~2단계는 아예 실행되지 않음 — 오래 걸리는 실행을 애초에 시작하지 않는다)."""
    start = time.monotonic()

    if not skip_ready:
        print('[run_integration] 0/2 환경 점검 (run_ready.py)')
        from run_ready import run as run_ready
        ready = run_ready(skip_bge=skip_bge)
        if not ready and not force:
            print('\n[run_integration] 환경 점검 실패 — 실행을 중단합니다.')
            print('  위 [실패] 항목을 해결한 뒤 다시 실행하거나, 문제를 알고도 강행하려면 --force를 사용하세요.')
            return False
        if not ready and force:
            print('\n[run_integration] 환경 점검 실패했지만 --force로 강행합니다.')
    else:
        print('[run_integration] 0/2 환경 점검 — 건너뜀(--skip-ready)')

    print('\n[run_integration] 1/2 전처리 (run_expertise.py)')
    from run_expertise import run as run_expertise
    run_expertise()

    print('\n[run_integration] 2/2 전문성 분석 LLM 체인 (run_analysis.py)')
    from run_analysis import run as run_analysis
    run_analysis(**analysis_kwargs)

    elapsed = time.monotonic() - start
    print(f'\n[run_integration] 전체 완료 (총 소요 시간: {elapsed / 60:.1f}분)')
    return True


if __name__ == '__main__':
    _argv = sys.argv
    ok = run(
        skip_ready='--skip-ready' in _argv,
        force='--force' in _argv,
        skip_bge='--skip-bge' in _argv,
        refresh_journals='--refresh-journals' in _argv,
        refresh_judgments='--refresh-judgments' in _argv,
        top_k=_parse_top_k_arg(_argv),
    )
    sys.exit(0 if ok else 1)
