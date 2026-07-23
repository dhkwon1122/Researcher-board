"""
과제별 전문성 분석 모듈 (사내 Confluence + 사내 LLM)

data/processed/project_confl_address.csv의 각 과제에 대해:
  1) project_summary.py로 컨플루언스 페이지를 요약(핵심 기술/최종 산출물/
     기술적 난제/국영문 키워드) — process_project_search.py와 공유하는 캐시
     (project_summary_cache.json)를 사용해 중복 조회를 피한다.
  2) "R&D Project Specialist Agent" 페르소나(rd_specialist_markdown.analyze_expertise)로
     이 과제에 대해 동일한 형식(연구개발 프로젝트 개요 / R&D 필수 전문성 및 직무
     딥다이브 매핑 / 인력 수급 매트릭스 / HR 제언)의 전문성 분석을 생성한다.
  3) Bootstrap 5 + marked.js/DOMPurify로 project_expertise_analysis.html을 생성한다.

Source:
  data/processed/project_confl_address.csv (dep_name, project_name, confl_address)

Output:
  data/processed/project_expertise_analysis.json[.<profile>]
  data/processed/project_expertise_analysis[.<profile>].html

두 사내 LLM 비교(profile 인자):
  python pipeline/process_project_expertise.py                    # 기존 LLM(profile='default')
  python pipeline/process_project_expertise.py --profile thinkingcap  # 2번째 LLM

사용법:
  python pipeline/process_project_expertise.py [--profile thinkingcap]
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


def _project_desc_html(item: dict) -> str:
    """컨플루언스 요약(핵심 기술/최종 산출물/기술적 난제)을 항목별 줄바꿈으로,
    국영문 키워드는 키워드별 색상 pill 배지로 렌더링."""
    keywords = (item.get('keywords_kr') or []) + (item.get('keywords_en') or [])
    lines = ''.join([
        f"<p><strong>핵심 기술:</strong> {html.escape(item.get('core_tech') or '확인 불가')}</p>",
        f"<p><strong>최종 산출물:</strong> {html.escape(item.get('deliverable') or '확인 불가')}</p>",
        f"<p><strong>기술적 난제:</strong> {html.escape(item.get('challenge') or '확인 불가')}</p>",
    ])
    return f'<div class="tech-desc">{lines}{mmd.keyword_pills_html(keywords)}</div>'


def _build_html(items: list, profile: str = 'default') -> str:
    toc_links = []
    cards = []
    for i, it in enumerate(items, start=1):
        anchor = f'project-{i}'
        toc_links.append(
            f'<a class="btn btn-sm btn-outline-primary rounded-pill" href="#{anchor}">'
            f'{html.escape(it["project_name"])}</a>'
        )

        deepdive_html, other_html = mmd.render_expertise_html(
            it.get('expertise_analysis', ''), anchor,
            empty_message='전문성 분석 데이터 없음 (python pipeline/process_project_expertise.py 실행 필요)',
        )

        dep_badge = (
            f'<span class="badge text-bg-dark rounded-pill">{html.escape(it["dep_name"])}</span>'
            if it.get('dep_name') else ''
        )
        cards.append(f'''<section class="tech-card card" id="{anchor}">
  <div class="card-body">
    <div class="tech-header d-flex align-items-center gap-2 mb-1">
      {dep_badge}<h2>{html.escape(it['project_name'])}</h2>
    </div>
    {_project_desc_html(it)}
    {deepdive_html}
    {other_html}
  </div>
</section>''')

    profile_note = f' ({profile})' if profile != 'default' else ''
    body_html = f'<nav class="toc">{"".join(toc_links)}</nav>\n{"".join(cards)}'
    return mmd.html_page(
        title=f'사내 과제 — R&D 전문성 매핑{profile_note}',
        heading=f'사내 과제 — R&amp;D 필수 전문성 및 직무 딥다이브 매핑{profile_note}',
        subtitle='과제별 필요 직무·전문성 분석 (R&amp;D Project Specialist Agent)',
        body_html=body_html,
        extra_style=mmd.EXPERTISE_CARD_STYLE,
    )


def process(profile: str = 'default') -> bool:
    projects = _read_projects()
    if projects.empty:
        print('[process_project_expertise] project_confl_address.csv 없음 — 종료 '
              '(process_project_confl.py 먼저 실행)')
        return False

    page_cache = project_summary.load_page_cache()
    summary_cache = project_summary.load_cache(profile)
    print(f'[process_project_expertise] 과제 {len(projects)}건 전문성 분석 중 (profile={profile})...')

    # 1단계: 과제별 컨플루언스/PDF 요약 준비(순차) — Confluence 조회·요약 캐시
    # (page_cache/summary_cache)는 공유 dict이므로 한 스레드(메인)에서만 읽고
    # 쓴다. 요약이 없는(신규 캐시 미스 실패) 과제는 이 단계에서 바로 건너뛴다.
    prepared = []
    for _, proj in projects.iterrows():
        dep_name = proj['dep_name']
        project_name = proj['project_name']
        confl_address = proj['confl_address']

        summary = project_summary.get_project_summary(project_name, confl_address, page_cache, summary_cache,
                                                        profile=profile)
        if summary is None:
            print(f'  [{project_name}] 건너뜀')
            continue
        prepared.append((dep_name, project_name, summary))

    project_summary.save_page_cache(page_cache)
    project_summary.save_cache(summary_cache, profile)

    # 2단계: 실제 R&D Project Specialist Agent 딥다이브 분석(사내 LLM 호출)은
    # profile의 동시 호출 허용치만큼 스레드풀로 동시에 실행한다(요약 단계와
    # 달리 공유 캐시 없이 순수 LLM 호출 + 결과 반환뿐이라 동시 실행이 안전하다).
    # 개별 과제 분석 중 예기치 못한 예외가 나도 다른 과제 분석은 계속 진행하고,
    # 실패한 과제만 에러와 함께 로그로 남긴다.
    results = []
    if prepared:
        workers = max_concurrency(profile)
        print(f'[process_project_expertise] 과제 {len(prepared)}건 딥다이브 분석 시작 '
              f'(동시 {workers}건, profile={profile})...')

        tasks = [
            (lambda name=project_name, desc=_summary_description(summary): mmd.analyze_expertise(
                name, desc, profile=profile))
            for _, project_name, summary in prepared
        ]
        task_results = run_concurrent(tasks, max_workers=workers)

        for (dep_name, project_name, summary), (expertise_analysis, error) in zip(prepared, task_results):
            if error is not None:
                print(f'  [{project_name}] 분석 오류: {type(error).__name__}: {error}')
                continue
            if not expertise_analysis:
                print(f'  [{project_name}] 전문성 분석 실패 — 건너뜀')
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
            print(f'  [{project_name}] 분석 완료')

    suffix = mmd.profile_suffix(profile)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f'project_expertise_analysis{suffix}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   project_expertise_analysis{suffix}.json 저장 ({len(results)}건)')

    html_path = os.path.join(OUT_DIR, f'project_expertise_analysis{suffix}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(_build_html(results, profile))
    print(f'[OK]   project_expertise_analysis{suffix}.html 저장')
    return True


if __name__ == '__main__':
    process(profile=mmd.parse_profile_arg(sys.argv))
