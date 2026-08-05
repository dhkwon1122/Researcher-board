"""
전문성 분석 LLM 체인 순차 실행 스크립트

run_expertise.py(전처리, LLM 호출 없음)가 끝난 뒤 사람이 하나씩 실행하던 아래
3단계를 이 스크립트 하나로 순서대로 실행한다. 각 단계는 사내 LLM(과 일부 단계는
BGE-M3 임베딩)을 호출하므로 비용이 발생한다.

  1) process_project_expertise.py   과제 문서 상세 분석 + 인력·담당 업무 매칭
  2) process_researcher_expertise.py 연구원 전문성 분석 (1)의 담당 업무를 새
     근거로 사용, 저널 권위도 조회 자동 포함)
  3) process_researcher_similarity.py  연구원 ↔ 연구원 유사도 (BGE-M3 임베딩 서버 자동 기동)

process_project_search.py(유사 기업/학계 탐색)는 이 체인에 포함되지 않는다 —
필요하면 별도로 직접 실행: python pipeline/process_project_search.py

(예전에는 과제↔연구원 매칭 단계가 더 있었지만, 그 기능 자체가 제거되면서
삭제됐다 — data/processed/CLAUDE.md 참고.)

한 단계가 실패해도(반환값 False) 이후 단계는 계속 진행한다 — 2단계는 1단계의
산출물을(과제 내 담당 업무), 3단계는 2단계의 산출물을 입력으로 읽으므로, 앞
단계가 실패해도 나머지 근거만으로 계속 진행된다(완전히 필수 입력은 아님).
마지막에 단계별 성공/실패를 요약해서 보여준다.

사용법:
  python pipeline/run_analysis.py [--refresh-journals] [--refresh-judgments] [--top-k 5]

run_expertise.py(전처리)까지 포함해 한 번에 순차 실행하려면 pipeline/run_integration.py를
쓰면 된다. 전체 실행에 수십 분~수 시간이 걸릴 수 있어 도중에 환경 문제로
끊기면 시간 낭비가 크므로, 실행 전 pipeline/run_ready.py로 사내 LLM/BGE-M3/
Confluence 연결을 먼저 점검하는 것을 권장한다(run_integration.py는 이 점검을
자동으로 먼저 수행함).
"""

import sys


def _parse_top_k_arg(argv: list) -> int | None:
    if '--top-k' in argv:
        idx = argv.index('--top-k')
        if idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                pass
    return None


def run(refresh_journals: bool = False, refresh_judgments: bool = False, top_k: int | None = None):
    steps = []  # [(단계명, True/False), ...]

    print('[run_analysis] 1/3 과제 문서 상세 분석')
    from process_project_expertise import process as process_project_expertise
    steps.append(('과제 문서 상세 분석', process_project_expertise()))

    print('[run_analysis] 2/3 연구원 전문성 분석')
    from process_researcher_expertise import process as process_researcher_expertise
    steps.append(('연구원 전문성 분석', process_researcher_expertise(refresh_journals=refresh_journals)))

    print('[run_analysis] 3/3 연구원 ↔ 연구원 유사도')
    from process_researcher_similarity import process as process_researcher_similarity
    similarity_kwargs = {'refresh_judgments': refresh_judgments}
    if top_k is not None:
        similarity_kwargs['top_k'] = top_k
    steps.append(('연구원 유사도', process_researcher_similarity(**similarity_kwargs)))

    print('\n[run_analysis] 실행 결과 요약:')
    for name, ok in steps:
        print(f'  [{"성공" if ok else "실패"}] {name}')


if __name__ == '__main__':
    _argv = sys.argv
    run(
        refresh_journals='--refresh-journals' in _argv,
        refresh_judgments='--refresh-judgments' in _argv,
        top_k=_parse_top_k_arg(_argv),
    )
