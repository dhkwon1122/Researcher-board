"""
MIT 10대 기술 ↔ 연구원 적합도 매칭 모듈

2026MITTech10.json의 기술별 직무 딥다이브 매핑("R&D 필수 전문성 및 직무
딥다이브 매핑" 섹션)과 연구원 보유 전문성 분석.json을 서로 비교해, 두 방향으로
적합도를 판단한다.
  1) 기술 기준: 각 기술의 각 직무에 어떤 연구원이 적합한지
  2) 인별 기준: 각 연구원이 MIT10 어떤 기술의 어떤 직무와 맞는지

매칭 로직(임베딩 1차 후보 추출 + 사내 LLM 최종 판단)은 pipeline/researcher_fit.py
공용 모듈을 사용한다(process_project_researcher_fit.py와 공유).

Source:
  data/processed/2026MITTech10.json           (process_mit10.py --llm 로 생성)
  data/processed/연구원 보유 전문성 분석.json   (process_researcher_expertise.py)
  data/processed/researchers.csv               (HTML에 이름 표시용)

Output:
  data/processed/mit10_fit_by_tech.json
  data/processed/mit10_fit_by_researcher.json
  data/processed/mit10_researcher_fit.html     (두 방향을 한 페이지에 함께 시각화)

사용법:
  python pipeline/process_mit10_researcher_fit.py
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
    mit10 = fit.read_json(OUT_DIR, '2026MITTech10')
    if not mit10:
        print('[process_mit10_researcher_fit] 2026MITTech10.json 없음 — 종료 (process_mit10.py 먼저 실행)')
        return False

    researcher_profiles = fit.read_json(OUT_DIR, '연구원 보유 전문성 분석')
    if not researcher_profiles:
        print('[process_mit10_researcher_fit] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
        return False

    jobs = []
    for tech in mit10:
        for job in mmd.deepdive_jobs(tech.get('expertise_analysis', '')):
            jobs.append({
                'target_id': tech.get('rank'),
                'target_name': tech.get('name'),
                'title': job['title'],
                'body_raw': job['body_raw'],
            })
    if not jobs:
        print('[process_mit10_researcher_fit] MIT10 직무 딥다이브 데이터 없음 — 종료 '
              '(python pipeline/process_mit10.py --llm 실행 필요)')
        return False

    job_texts = [fit.job_text(j) for j in jobs]
    researcher_ids = [p['researcher_id'] for p in researcher_profiles]
    researcher_texts = [fit.researcher_profile_text(p) for p in researcher_profiles]

    print(f'[process_mit10_researcher_fit] 직무 {len(jobs)}건, 연구원 {len(researcher_ids)}명 임베딩 계산 중...')
    try:
        job_emb, researcher_emb = fit.compute_embeddings(job_texts, researcher_texts)
    except LLMError as exc:
        print(f'[process_mit10_researcher_fit] 임베딩 실패 — 종료: {exc}')
        return False

    sims = fit.cosine_sim_matrix(researcher_emb, job_emb)  # (n_researchers, n_jobs)

    print('[process_mit10_researcher_fit] 기술 기준 매칭 중...')
    by_target = fit.match_by_target(jobs, researcher_ids, researcher_texts, job_texts, sims, log_prefix='    ')

    print('[process_mit10_researcher_fit] 인별 기준 매칭 중...')
    by_researcher = fit.match_by_researcher(jobs, researcher_ids, researcher_texts, job_texts, sims, log_prefix='    ')

    # 기존에 배포된 JSON 스키마(tech_rank/tech_name)를 유지하기 위해 필드명을 변환
    by_tech_results = [
        {'tech_rank': t['target_id'], 'tech_name': t['target_name'], 'job_title': t['job_title'],
         'rankings': t['rankings']}
        for t in by_target
    ]
    by_researcher_results = [
        {
            'researcher_id': r['researcher_id'],
            'matches': [
                {'tech_rank': m['target_id'], 'tech_name': m['target_name'], 'job_title': m['job_title'],
                 'fit_score': m['fit_score'], 'reason': m['reason']}
                for m in r['matches']
            ],
        }
        for r in by_researcher
    ]

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, 'mit10_fit_by_tech.json'), 'w', encoding='utf-8') as f:
        json.dump(by_tech_results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   mit10_fit_by_tech.json 저장 ({len(by_tech_results)}건)')

    with open(os.path.join(OUT_DIR, 'mit10_fit_by_researcher.json'), 'w', encoding='utf-8') as f:
        json.dump(by_researcher_results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   mit10_fit_by_researcher.json 저장 ({len(by_researcher_results)}건)')

    html_out = fit.build_fit_html(
        by_target, by_researcher, fit.read_researchers(OUT_DIR),
        page_title='MIT10 ↔ 연구원 적합도 매칭',
        heading='2026 MIT 10대 기술 ↔ 연구원 적합도 매칭',
        subtitle='기술 기준 / 인별 기준 매칭 결과 (R&D Talent Matching Agent, 임베딩 1차 후보 + 사내 LLM 판단)',
        target_tab_label='기술 기준',
        target_header=lambda item: f"#{item['target_id']} {item['target_name']} — {item['job_title']}",
        target_card_subtitle='이 직무에 적합한 연구원 (적합도 순)',
        researcher_card_subtitle='이 연구원에게 적합한 MIT10 기술 직무 (적합도 순)',
    )
    html_path = os.path.join(OUT_DIR, 'mit10_researcher_fit.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print('[OK]   mit10_researcher_fit.html 저장')

    return True


if __name__ == '__main__':
    process()
