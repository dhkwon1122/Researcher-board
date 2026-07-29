"""
과제별 전문성 분석 모듈 (사내 Confluence + 사내 LLM)

data/processed/project_confl_address.csv의 각 과제에 대해:
  1) project_summary.py로 컨플루언스 페이지를 요약(핵심 기술/최종 산출물/
     기술적 난제/국영문 키워드) — process_project_search.py와 공유하는 캐시
     (project_summary_cache.json)를 사용해 중복 조회를 피한다.
  2) "R&D Project Specialist Agent" 페르소나(rd_specialist_markdown.analyze_expertise)로
     이 과제에 대해 동일한 형식(연구개발 프로젝트 개요 / R&D 필수 전문성 및 직무
     딥다이브 매핑 / 인력 수급 매트릭스 / HR 제언)의 전문성 분석을 생성한다.
  3) 콘솔형 리포트(rd_specialist_markdown.console_page, 외부 CDN 없이 독립적인
     정적 페이지)로 project_expertise_analysis.html을 생성한다 — 딥다이브 매핑
     섹션은 직무 카드로, 나머지(프로젝트 개요/인력 수급 매트릭스/HR 제언)는
     자유 형식 마크다운이라 원문 그대로 접어서 보여준다.

Source:
  data/processed/project_confl_address.csv (dep_name, project_name, confl_address)

Output:
  data/processed/project_expertise_analysis.json
  data/processed/project_expertise_analysis.html

사용법:
  python pipeline/process_project_expertise.py
"""

import html
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402
import project_summary  # noqa: E402
from llm_client import max_concurrency, run_concurrent  # noqa: E402
import result_archive  # noqa: E402


def _read_projects() -> pd.DataFrame:
    path = os.path.join(OUT_DIR, 'project_confl_address.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')


def _summary_description(summary: dict) -> str:
    """R&D Project Specialist Agent 프롬프트에 넣을 '연구 내용' 텍스트를
    컨플루언스 요약 결과로부터 구성."""
    keywords = ', '.join((summary.get('keywords_kr') or []) + (summary.get('keywords_en') or []))
    parts = [
        f"핵심 연구 대상 기술: {summary.get('core_tech') or '확인 불가'}",
        f"최종 산출물: {summary.get('deliverable') or '확인 불가'}",
        f"현재 직면한 기술적 장벽/난제: {summary.get('challenge') or '확인 불가'}",
    ]
    if keywords:
        parts.append(f'관련 키워드: {keywords}')
    return '\n'.join(parts)


def _build_html(items: list, total_projects: int) -> str:
    """과제(project_confl_address.csv의 '소속' → dep_name)를 '플랫폼/팀'으로
    라벨링해 좌측 사이드바와 본문을 그룹핑해 보여준다."""
    anchor_of = {it['project_name']: f'p-{i}' for i, it in enumerate(items, start=1)}
    jobs_by_project = {it['project_name']: mmd.deepdive_jobs(it.get('expertise_analysis', '')) for it in items}

    nav_groups = []
    for dept, dept_items in mmd.group_ordered(items, lambda it: it.get('dep_name', '')):
        entries = ''.join(
            f'<a class="nav-item" href="#{anchor_of[it["project_name"]]}">'
            f'<span>{html.escape(it["project_name"])}</span>'
            f'<span class="n-count">{len(jobs_by_project[it["project_name"]])}</span></a>'
            for it in dept_items
        )
        nav_groups.append(f'<div class="nav-group"><div class="nav-group-label">{html.escape(dept)}</div>{entries}</div>')

    all_jobs = [j for jobs in jobs_by_project.values() for j in jobs]
    stats = mmd.stat_row_html([
        mmd.coverage_stat(len(items), total_projects, '분석 완료 / 분석 대상 과제'),
        (len(all_jobs), '딥다이브 직무 수'),
        (sum(1 for j in all_jobs if j.get('difficulty') == '상'), '채용난이도 상(외부 영입 필요)'),
        mmd.generated_at_stat(),
    ])

    sections = []
    for dept, dept_items in mmd.group_ordered(items, lambda it: it.get('dep_name', '')):
        sections.append(f'<div class="dept-heading">{html.escape(dept)}</div>')
        for it in dept_items:
            sections.append(mmd.project_card_html(it, jobs_by_project[it['project_name']], anchor_of[it['project_name']]))

    sidebar = (
        '<h1>과제 전문성 콘솔</h1>'
        '<p class="tagline">컨플루언스 요약 + R&amp;D 필수 전문성·직무 딥다이브 매핑 (R&amp;D Project Specialist Agent)</p>'
        f'{"".join(nav_groups)}'
    )
    return mmd.console_page('과제 전문성 분석', sidebar, stats + ''.join(sections))


def process() -> bool:
    projects = _read_projects()
    if projects.empty:
        print('[process_project_expertise] project_confl_address.csv 없음 — 종료 '
              '(process_project_confl.py 먼저 실행)')
        return False

    page_cache = project_summary.load_page_cache()
    summary_cache = project_summary.load_cache()
    print(f'[process_project_expertise] 과제 {len(projects)}건 전문성 분석 중...')

    # 1단계: 과제별 컨플루언스/PDF 요약 준비(순차) — Confluence 조회·요약 캐시
    # (page_cache/summary_cache)는 공유 dict이므로 한 스레드(메인)에서만 읽고
    # 쓴다. 요약이 없는(신규 캐시 미스 실패) 과제는 이 단계에서 바로 건너뛴다.
    prepared = []
    for _, proj in projects.iterrows():
        dep_name = proj['dep_name']
        project_name = proj['project_name']
        confl_address = proj['confl_address']

        summary = project_summary.get_project_summary(project_name, confl_address, page_cache, summary_cache)
        if summary is None:
            print(f'  [{project_name}] 건너뜀')
            continue
        prepared.append((dep_name, project_name, summary))

    project_summary.save_page_cache(page_cache)
    project_summary.save_cache(summary_cache)

    # 2단계: 실제 R&D Project Specialist Agent 딥다이브 분석(사내 LLM 호출)은
    # 동시 호출 허용치만큼 스레드풀로 동시에 실행한다(요약 단계와 달리 공유
    # 캐시 없이 순수 LLM 호출 + 결과 반환뿐이라 동시 실행이 안전하다). 개별
    # 과제 분석 중 예기치 못한 예외가 나도 다른 과제 분석은 계속 진행하고,
    # 실패한 과제만 에러와 함께 로그로 남긴다.
    results = []
    if prepared:
        workers = max_concurrency()
        deepdive_total = len(prepared)
        print(f'[process_project_expertise] 과제 {deepdive_total}건 딥다이브 분석 시작 '
              f'(동시 {workers}건)...')
        completed = 0

        # run_concurrent()는 제출된 작업을 전부 마칠 때까지 반환하지 않으므로,
        # 실시간 진행 로그는 on_complete 콜백에서 찍는다(반환값을 받은 뒤
        # 순회하며 출력하면 전체가 다 끝난 뒤에야 한꺼번에 찍힌다).
        def _on_complete(i, expertise_analysis, error):
            nonlocal completed
            project_name = prepared[i][1]
            completed += 1
            if error is not None:
                print(f'  [{project_name}] 분석 오류: {type(error).__name__}: {error}')
            elif not expertise_analysis:
                print(f'  [{project_name}] 전문성 분석 실패 — 건너뜀')
            else:
                print(f'  [{project_name}] 분석 완료')
            if completed % 5 == 0 or completed == deepdive_total:
                print(f'    (진행: {completed}/{deepdive_total} 완료)')

        tasks = [
            (lambda name=project_name, desc=_summary_description(summary): mmd.analyze_expertise(name, desc))
            for _, project_name, summary in prepared
        ]
        task_results = run_concurrent(tasks, max_workers=workers, on_complete=_on_complete)

        # 위 콜백에서 이미 출력을 끝냈으므로, 여기서는 결과만 원래 순서대로 모은다
        # (완료 순서는 스레드 스케줄링에 따라 달라지므로).
        for (dep_name, project_name, summary), (expertise_analysis, _error) in zip(prepared, task_results):
            if not expertise_analysis:
                continue
            results.append({
                'dep_name': dep_name,
                'project_name': project_name,
                'core_tech': summary.get('core_tech', ''),
                'deliverable': summary.get('deliverable', ''),
                'challenge': summary.get('challenge', ''),
                'keywords_kr': summary.get('keywords_kr') or [],
                'keywords_en': summary.get('keywords_en') or [],
                'expertise_analysis': expertise_analysis,
            })

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'project_expertise_analysis.json')
    json_text = json.dumps(results, ensure_ascii=False, indent=2)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json_text)
    print(f'[OK]   project_expertise_analysis.json 저장 ({len(results)}건)')
    result_archive.archive_copy('01. 과제분석', '과제 전문성 분석', 'json', json_text)

    html_out = _build_html(results, len(projects))
    html_path = os.path.join(OUT_DIR, 'project_expertise_analysis.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print('[OK]   project_expertise_analysis.html 저장')
    result_archive.archive_copy('01. 과제분석', '과제 전문성 분석', 'html', html_out)
    return True


if __name__ == '__main__':
    process()
