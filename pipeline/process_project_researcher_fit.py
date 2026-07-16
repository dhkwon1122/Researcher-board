"""
사내 과제 ↔ 연구원 적합도 매칭 모듈

process_project_expertise.py가 만든 과제별 직무 딥다이브 매핑("R&D 필수 전문성
및 직무 딥다이브 매핑" 섹션)과 연구원 보유 전문성 분석.json을 서로 비교해, 두
방향으로 적합도를 판단한다.
  1) 과제 기준: 각 과제의 각 직무에 어떤 연구원이 적합한지
  2) 인별 기준: 각 연구원이 사내 어떤 과제의 어떤 직무와 맞는지

매칭 로직(임베딩 1차 후보 추출 + 사내 LLM 최종 판단)은 pipeline/researcher_fit.py
공용 모듈을 사용한다(process_mit10_researcher_fit.py와 공유).

Source:
  data/processed/project_expertise_analysis.json (process_project_expertise.py)
  data/processed/연구원 보유 전문성 분석.json      (process_researcher_expertise.py)
  data/processed/researchers.csv                  (HTML에 이름 표시용)

Output:
  data/processed/project_fit_by_project.json
  data/processed/project_fit_by_researcher.json
  data/processed/project_researcher_fit.html     (두 방향을 한 페이지에 함께 시각화)

※ LLM 프롬프트에는 researcher_id/이름을 절대 포함하지 않는다.

사용법:
  python pipeline/process_project_researcher_fit.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mit_markdown as mmd  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'processed')


def process() -> bool:
    projects = fit.read_json(OUT_DIR, 'project_expertise_analysis')
    if not projects:
        print('[process_project_researcher_fit] project_expertise_analysis.json 없음 — 종료 '
              '(process_project_expertise.py 먼저 실행)')
        return False

    researcher_profiles = fit.read_json(OUT_DIR, '연구원 보유 전문성 분석')
    if not researcher_profiles:
        print('[process_project_researcher_fit] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
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

    print('[process_project_researcher_fit] 과제 기준 매칭 중...')
    by_target = fit.match_by_target(jobs, researcher_ids, researcher_texts, job_texts, sims, log_prefix='    ')

    print('[process_project_researcher_fit] 인별 기준 매칭 중...')
    by_researcher = fit.match_by_researcher(jobs, researcher_ids, researcher_texts, job_texts, sims, log_prefix='    ')

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
    with open(os.path.join(OUT_DIR, 'project_fit_by_project.json'), 'w', encoding='utf-8') as f:
        json.dump(by_project_results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   project_fit_by_project.json 저장 ({len(by_project_results)}건)')

    with open(os.path.join(OUT_DIR, 'project_fit_by_researcher.json'), 'w', encoding='utf-8') as f:
        json.dump(by_researcher_results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   project_fit_by_researcher.json 저장 ({len(by_researcher_results)}건)')

    html_out = fit.build_fit_html(
        by_target, by_researcher, fit.read_researchers(OUT_DIR),
        page_title='사내 과제 ↔ 연구원 적합도 매칭',
        heading='사내 과제 ↔ 연구원 적합도 매칭',
        subtitle='과제 기준 / 인별 기준 매칭 결과 (R&D Talent Matching Agent, 임베딩 1차 후보 + 사내 LLM 판단)',
        target_tab_label='과제 기준',
        target_header=lambda item: (
            f"{dep_map.get(item['target_name'], '')} · {item['target_name']} — {item['job_title']}"
        ),
        target_card_subtitle='이 직무에 적합한 연구원 (적합도 순)',
        researcher_card_subtitle='이 연구원에게 적합한 사내 과제 직무 (적합도 순)',
    )
    html_path = os.path.join(OUT_DIR, 'project_researcher_fit.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print('[OK]   project_researcher_fit.html 저장')

    return True


if __name__ == '__main__':
    process()
