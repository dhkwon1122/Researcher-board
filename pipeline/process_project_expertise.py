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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rd_specialist_markdown as mmd  # noqa: E402
import project_summary  # noqa: E402


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


def _project_desc_line(item: dict) -> str:
    keywords = ', '.join((item.get('keywords_kr') or []) + (item.get('keywords_en') or []))
    parts = [
        f"핵심 기술: {item.get('core_tech') or '확인 불가'}",
        f"최종 산출물: {item.get('deliverable') or '확인 불가'}",
        f"기술적 난제: {item.get('challenge') or '확인 불가'}",
    ]
    if keywords:
        parts.append(f'키워드: {keywords}')
    return ' · '.join(parts)


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
    <p class="tech-desc">{html.escape(_project_desc_line(it))}</p>
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
    results = []
    print(f'[process_project_expertise] 과제 {len(projects)}건 전문성 분석 중 (profile={profile})...')
    for _, proj in projects.iterrows():
        dep_name = proj['dep_name']
        project_name = proj['project_name']
        confl_address = proj['confl_address']

        summary = project_summary.get_project_summary(project_name, confl_address, page_cache, summary_cache,
                                                        profile=profile)
        if summary is None:
            print(f'  [{project_name}] 건너뜀')
            continue

        description = _summary_description(summary)
        expertise_analysis = mmd.analyze_expertise(project_name, description, profile=profile)
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

    project_summary.save_page_cache(page_cache)
    project_summary.save_cache(summary_cache, profile)

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
