"""
2026 MIT 10대 기술 처리 모듈

원천 파일: data/raw/2026MIT10대기술.xlsx
출력 파일: data/processed/2026MITTech10.json, data/processed/2026MITTech10.html

읽는 컬럼:
  No., 기술명, 설명

처리:
  - xlsx를 JSON 배열로 변환합니다.
  - --llm 옵션을 주면, 기술마다 "R&D Project Specialist Agent" 역할의 사내 LLM을
    호출해 해당 기술 연구개발에 필요한 직무·전문성 딥다이브 분석을 생성하고
    expertise_analysis 필드에 채웁니다(마크다운 원문 그대로 저장).
  - JSON과 함께 2026MITTech10.html도 생성합니다. "R&D 필수 전문성 및 직무
    딥다이브 매핑" 섹션은 직무별 카드로 강조해서 보여주고, 나머지 섹션(개요/
    인력 수급 매트릭스/HR 제언)은 아코디언으로 접어서 함께 제공합니다.
    Bootstrap 5(연구원 개별 프로필과 동일 CDN 버전) + marked.js/DOMPurify로
    렌더링합니다.

사용법:
  python pipeline/process_mit10.py           # JSON+HTML 변환만 (전문성 분석 없음)
  python pipeline/process_mit10.py --llm     # 전문성 분석 포함

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mit_markdown as mmd
from excel_reader import read_xlsx

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

MIT10_FILE = '2026MIT10대기술.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_RANK = 'No.'
COL_NAME = '기술명'
COL_DESC = '설명'
# ─────────────────────────────────────────────────────────────────────────────


def _clean(val) -> str:
    s = str(val).strip() if val is not None else ''
    return '' if s.lower() in ('nan', 'none', 'nat') else s


_EXTRA_STYLE = """
  .tech-card {
    max-width: 900px; margin: 0 auto 32px; border: 1px solid var(--gs-border);
    border-radius: 18px; background: var(--gs-surface); box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .tech-card .card-body { padding: 28px 32px; }
  .tech-header .badge { font-size: 0.7rem; }
  .tech-header h2 { font-size: 1.2rem; font-weight: 700; margin: 0; }
  .tech-desc { color: #444; font-size: 0.86rem; margin: 6px 0 22px; }
  .deepdive-title {
    font-size: 1rem; font-weight: 700; color: var(--gs-accent); margin: 0 0 4px;
    display: flex; align-items: center; gap: 8px;
  }
  .deepdive-lead { color: var(--gs-muted); font-size: 0.8rem; margin: 0 0 16px; }
  .job-card {
    border: 1px solid var(--gs-border); border-left: 3px solid var(--gs-accent);
    border-radius: 12px; background: #fafafa; height: 100%;
  }
  .job-card .card-body { padding: 18px 20px; }
  .job-card .job-title { font-size: 0.92rem; font-weight: 700; margin: 0; }
  .job-card .badge { font-size: 0.68rem; }
  .other-sections .accordion-button {
    font-size: 0.82rem; font-weight: 600; color: var(--gs-muted); background: var(--gs-bg);
  }
  .other-sections .accordion-button:not(.collapsed) { color: var(--gs-text); background: var(--gs-bg); box-shadow: none; }
  .other-sections .accordion-button:focus { box-shadow: none; }
"""


def _build_html(items: list) -> str:
    toc_links = []
    cards = []
    for i, it in enumerate(items, start=1):
        rank = it.get('rank')
        anchor = f"tech-{rank if rank is not None else i}"
        toc_links.append(
            f'<a class="btn btn-sm btn-outline-primary rounded-pill" href="#{anchor}">'
            f'{rank or i}. {html.escape(it["name"])}</a>'
        )

        analysis = it.get('expertise_analysis', '')
        sections = mmd.split_top_sections(analysis)
        deepdive_idx = next((idx for idx, s in enumerate(sections) if mmd.is_deepdive_section(s)), None)

        if deepdive_idx is not None:
            deepdive_section = sections[deepdive_idx]
            other_sections = sections[:deepdive_idx] + sections[deepdive_idx + 1:]
            # 섹션 자체의 '## 2. ...' 헤더 행은 우리가 별도 타이틀로 그리므로 본문에서 제외
            deepdive_body = deepdive_section.split('\n', 1)[1] if '\n' in deepdive_section else ''
            intro_raw, job_blocks_raw = mmd.split_job_blocks(deepdive_body)

            deepdive_lead = (
                f'<p class="deepdive-lead md-render" data-md-b64="{mmd.b64_encode(intro_raw)}"></p>'
                if intro_raw.strip() else ''
            )
            job_cards = []
            for jb in job_blocks_raw:
                title = html.escape(mmd.extract_job_title(jb))
                diff = mmd.extract_difficulty(jb)
                diff_badge = (
                    f'<span class="badge rounded-pill {mmd.DIFFICULTY_BADGE.get(diff, "text-bg-secondary")}">'
                    f'채용난이도 {diff}</span>'
                ) if diff else ''
                body = mmd.job_body(jb)
                job_cards.append(f'''<div class="col-md-6">
  <div class="job-card card">
    <div class="card-body">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
        <p class="job-title mb-0">{title}</p>
        {diff_badge}
      </div>
      <div class="md-render" data-md-b64="{mmd.b64_encode(body)}"></div>
    </div>
  </div>
</div>''')
            deepdive_html = f'''<p class="deepdive-title"><i class="bi bi-diagram-3-fill"></i> R&amp;D 필수 전문성 및 직무 딥다이브 매핑</p>
{deepdive_lead}
<div class="row row-cols-1 row-cols-lg-2 g-3">{''.join(job_cards)}</div>'''
        else:
            deepdive_html = (
                '<p class="deepdive-title"><i class="bi bi-diagram-3-fill"></i> '
                'R&amp;D 필수 전문성 및 직무 딥다이브 매핑</p>'
                '<p class="empty">전문성 분석 데이터 없음 (python pipeline/process_mit10.py --llm 실행 필요)</p>'
            )
            other_sections = []

        other_html = ''
        if other_sections:
            other_raw = '\n\n'.join(other_sections)
            other_html = f'''<div class="other-sections accordion accordion-flush mt-4">
  <div class="accordion-item">
    <h2 class="accordion-header">
      <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#{anchor}-more">
        프로젝트 개요 · 인력 수급 매트릭스 · HR 제언 더 보기
      </button>
    </h2>
    <div id="{anchor}-more" class="accordion-collapse collapse">
      <div class="accordion-body md-render" data-md-b64="{mmd.b64_encode(other_raw)}"></div>
    </div>
  </div>
</div>'''

        rank_badge = f'<span class="badge text-bg-dark rounded-pill">#{rank}</span>' if rank is not None else ''
        cards.append(f'''<section class="tech-card card" id="{anchor}">
  <div class="card-body">
    <div class="tech-header d-flex align-items-center gap-2 mb-1">
      {rank_badge}<h2>{html.escape(it['name'])}</h2>
    </div>
    <p class="tech-desc">{html.escape(it.get('description', ''))}</p>
    {deepdive_html}
    {other_html}
  </div>
</section>''')

    body_html = f'<nav class="toc">{"".join(toc_links)}</nav>\n{"".join(cards)}'
    return mmd.html_page(
        title='2026 MIT 10대 기술 — R&D 전문성 매핑',
        heading='2026 MIT 10대 기술 — R&amp;D 필수 전문성 및 직무 딥다이브 매핑',
        subtitle='기술별 필요 직무·전문성 분석 (R&amp;D Project Specialist Agent)',
        body_html=body_html,
        extra_style=_EXTRA_STYLE,
    )


def process(use_llm: bool = False) -> bool:
    raw_path = os.path.join(RAW_DIR, MIT10_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {MIT10_FILE} 파일 없음')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_NAME not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_NAME}]\n'
            f'  process_mit10.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    items = []
    for _, row in df.iterrows():
        name = _clean(row.get(COL_NAME))
        if not name:
            continue
        rank_raw = _clean(row.get(COL_RANK)) if COL_RANK in df.columns else ''
        try:
            rank = int(float(rank_raw)) if rank_raw else None
        except ValueError:
            rank = None
        description = _clean(row.get(COL_DESC)) if COL_DESC in df.columns else ''
        items.append({
            'rank': rank,
            'name': name,
            'description': description,
            'expertise_analysis': '',
        })

    if use_llm:
        print(f'[process_mit10] 기술 {len(items)}건 전문성 분석 중 (사내 LLM)...')
        for item in items:
            item['expertise_analysis'] = mmd.analyze_expertise(item['name'], item['description'])
            status = 'OK' if item['expertise_analysis'] else '실패'
            print(f"    [{status}] {item['name']}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, '2026MITTech10.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f'[OK]   2026MITTech10.json 저장 ({len(items)}건)')

    html_path = os.path.join(OUT_DIR, '2026MITTech10.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(_build_html(items))
    print(f'[OK]   2026MITTech10.html 저장')

    return True


if __name__ == '__main__':
    process(use_llm='--llm' in sys.argv)
