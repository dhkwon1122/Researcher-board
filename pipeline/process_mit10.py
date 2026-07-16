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

        deepdive_html, other_html = mmd.render_expertise_html(
            it.get('expertise_analysis', ''), anchor,
            empty_message='전문성 분석 데이터 없음 (python pipeline/process_mit10.py --llm 실행 필요)',
        )

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
        extra_style=mmd.EXPERTISE_CARD_STYLE,
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
