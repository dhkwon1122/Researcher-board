"""
사내 과제 ↔ 연구원 적합도 매칭 모듈

process_project_expertise.py가 만든 과제별 직무 딥다이브 매핑("R&D 필수 전문성
및 직무 딥다이브 매핑" 섹션)과 연구원 보유 전문성 분석.json을 서로 비교해, 두
방향으로 적합도를 판단한다.
  1) 과제 기준: 각 과제의 각 직무에 어떤 연구원이 적합한지
  2) 인별 기준: 각 연구원이 사내 어떤 과제의 어떤 직무와 맞는지

매칭 로직(임베딩 1차 후보 추출 + 사내 LLM 최종 판단)은 pipeline/researcher_fit.py
공용 모듈을 사용한다.

Source:
  data/processed/project_expertise_analysis[.<profile>].json (process_project_expertise.py)
  data/processed/연구원 보유 전문성 분석[.<profile>].json      (process_researcher_expertise.py)
  data/processed/researchers.csv                             (HTML에 이름 표시용)

Output:
  data/processed/project_fit_by_project[.<profile>].json
  data/processed/project_fit_by_researcher[.<profile>].json
  data/processed/project_researcher_fit[.<profile>].html    (두 방향을 한 페이지에 함께 시각화)

※ LLM 프롬프트에는 researcher_id/이름을 절대 포함하지 않는다.

임베딩(1차 후보 추출)은 profile과 무관하게 항상 공유되며, 최종 LLM 판단만
profile별로 달라진다.

실행 시작 시 BGE-M3 임베딩 서버가 응답하는지 먼저 확인하고, 응답하지 않으면
services/bge_server.py를 백그라운드로 자동 기동한 뒤 준비될 때까지 기다린다
(pipeline/embed_server.py). 이미 다른 실행이 띄워 둔 서버가 있으면 재사용하고
새로 기동하지 않는다.

두 사내 LLM 비교(profile 인자):
  python pipeline/process_project_researcher_fit.py                    # 기존 LLM(profile='default')
  python pipeline/process_project_researcher_fit.py --profile thinkingcap  # 2번째 LLM

사용법:
  python pipeline/process_project_researcher_fit.py [--profile thinkingcap]
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import embed_server  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402
import researcher_fit as fit  # noqa: E402
import result_archive  # noqa: E402
from services.llm import LLMError  # noqa: E402


def process(profile: str = 'default') -> bool:
    if not embed_server.ensure_embed_server():
        print('[process_project_researcher_fit] BGE-M3 임베딩 서버를 사용할 수 없어 종료합니다.')
        return False

    suffix = mmd.profile_suffix(profile)

    projects = fit.read_json(OUT_DIR, f'project_expertise_analysis{suffix}')
    if not projects:
        print(f'[process_project_researcher_fit] project_expertise_analysis{suffix}.json 없음 — 종료 '
              f'(process_project_expertise.py{" --profile " + profile if profile != "default" else ""} 먼저 실행)')
        return False

    researcher_profiles = fit.read_json(OUT_DIR, f'연구원 보유 전문성 분석{suffix}')
    if not researcher_profiles:
        print(f'[process_project_researcher_fit] 연구원 보유 전문성 분석{suffix}.json 없음 — 종료 '
              f'(process_researcher_expertise.py{" --profile " + profile if profile != "default" else ""} 먼저 실행)')
        return False

    dep_map = {p.get('project_name'): p.get('dep_name', '') for p in projects}

    jobs = []
    for i, proj in enumerate(projects, start=1):
        for job in mmd.deepdive_jobs(proj.get('expertise_analysis', '')):
            jobs.append({
                'target_id': i,
                'target_name': proj.get('project_name'),
                'title': job['title'],
                'body_raw': job['body_raw'],
            })
    if not jobs:
        print('[process_project_researcher_fit] 과제 직무 딥다이브 데이터 없음 — 종료 '
              '(process_project_expertise.py 실행 필요)')
        return False

    job_texts = [fit.job_text(j) for j in jobs]
    researcher_ids = [p['researcher_id'] for p in researcher_profiles]
    researcher_texts = [fit.researcher_profile_text(p) for p in researcher_profiles]

    print(f'[process_project_researcher_fit] 직무 {len(jobs)}건, 연구원 {len(researcher_ids)}명 임베딩 계산 중...')
    try:
        job_emb, researcher_emb = fit.compute_embeddings(job_texts, researcher_texts)
    except LLMError as exc:
        print(f'[process_project_researcher_fit] 임베딩 실패 — 종료: {exc}')
        return False

    sims = fit.cosine_sim_matrix(researcher_emb, job_emb)  # (n_researchers, n_jobs)

    print(f'[process_project_researcher_fit] 과제 기준 매칭 중 (profile={profile})...')
    by_target = fit.match_by_target(jobs, researcher_ids, researcher_texts, job_texts, sims, log_prefix='    ',
                                     profile=profile)

    print(f'[process_project_researcher_fit] 인별 기준 매칭 중 (profile={profile})...')
    by_researcher = fit.match_by_researcher(jobs, researcher_ids, researcher_texts, job_texts, sims, log_prefix='    ',
                                             profile=profile)

    by_project_results = [
        {
            'dep_name': dep_map.get(t['target_name'], ''), 'project_name': t['target_name'],
            'job_title': t['job_title'], 'rankings': t['rankings'],
        }
        for t in by_target
    ]
    by_researcher_results = [
        {
            'researcher_id': r['researcher_id'],
            'matches': [
                {
                    'dep_name': dep_map.get(m['target_name'], ''), 'project_name': m['target_name'],
                    'job_title': m['job_title'], 'fit_score': m['fit_score'], 'reason': m['reason'],
                }
                for m in r['matches']
            ],
        }
        for r in by_researcher
    ]

    os.makedirs(OUT_DIR, exist_ok=True)
    by_project_json = json.dumps(by_project_results, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, f'project_fit_by_project{suffix}.json'), 'w', encoding='utf-8') as f:
        f.write(by_project_json)
    print(f'[OK]   project_fit_by_project{suffix}.json 저장 ({len(by_project_results)}건)')
    result_archive.archive_copy('과제_연구원간_매칭', '과제, 연구원간 매칭_과제기준', 'json', by_project_json, profile=profile)

    by_researcher_json = json.dumps(by_researcher_results, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, f'project_fit_by_researcher{suffix}.json'), 'w', encoding='utf-8') as f:
        f.write(by_researcher_json)
    print(f'[OK]   project_fit_by_researcher{suffix}.json 저장 ({len(by_researcher_results)}건)')
    result_archive.archive_copy('과제_연구원간_매칭', '과제, 연구원간 매칭_인별기준', 'json', by_researcher_json,
                                 profile=profile)

    profile_note = f' ({profile})' if profile != 'default' else ''
    html_out = fit.build_fit_html(
        by_target, by_researcher, fit.read_researchers(OUT_DIR),
        page_title=f'사내 과제 ↔ 연구원 적합도 매칭{profile_note}',
        heading=f'사내 과제 ↔ 연구원 적합도 매칭{profile_note}',
        subtitle='과제 기준 / 인별 기준 매칭 결과 (R&D Talent Matching Agent, 임베딩 1차 후보 + 사내 LLM 판단)',
        target_tab_label='과제 기준',
        target_header=lambda item: (
            f"{dep_map.get(item['target_name'], '')} · {item['target_name']} — {item['job_title']}"
        ),
        target_card_subtitle='이 직무에 적합한 연구원 (적합도 순)',
        researcher_card_subtitle='이 연구원에게 적합한 사내 과제 직무 (적합도 순)',
    )
    html_path = os.path.join(OUT_DIR, f'project_researcher_fit{suffix}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f'[OK]   project_researcher_fit{suffix}.html 저장')
    result_archive.archive_copy('과제_연구원간_매칭', '과제, 연구원간 매칭', 'html', html_out, profile=profile)

    return True


if __name__ == '__main__':
    process(profile=mmd.parse_profile_arg(sys.argv))
