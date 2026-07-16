"""
"R&D Project Specialist Agent" 계열 LLM이 생성하는 마크다운(## 섹션, ### 직무
블록)을 다루는 공용 유틸리티. process_mit10.py와 process_mit10_researcher_fit.py
양쪽에서 동일한 파싱/HTML 렌더링 인프라를 재사용하기 위해 분리했다.
"""

import base64
import re

# ── 마크다운 섹션/직무 블록 파싱 ────────────────────────────────────────────


def split_top_sections(text: str) -> list:
    """'## ' 최상위 헤더 기준으로 전체 마크다운을 섹션 단위로 분리한다(헤더 행도
    각 청크에 포함). 첫 '## ' 이전에 다른 텍스트가 있으면 별도 청크로 남는다."""
    if not text:
        return []
    parts = re.split(r'(?m)^(?=##\s+)', text)
    return [p.strip() for p in parts if p.strip()]


def is_deepdive_section(section_text: str) -> bool:
    first_line = section_text.split('\n', 1)[0]
    return bool(re.match(r'^##\s*2[.\)]', first_line)) or '딥다이브' in first_line or 'Deep-Dive' in first_line


def split_job_blocks(section_text: str) -> tuple:
    """섹션 본문(맨 위 '## ...' 헤더는 제외하고 넘겨야 함)을 '### ' 헤더 기준으로
    인트로 문단과 직무별 블록으로 분리."""
    intro_lines = []
    jobs = []
    current = None
    for line in section_text.split('\n'):
        if re.match(r'^###\s+', line.rstrip()):
            current = [line]
            jobs.append(current)
        elif current is not None:
            current.append(line)
        else:
            intro_lines.append(line)
    return '\n'.join(intro_lines), ['\n'.join(j) for j in jobs]


DIFFICULTY_BADGE = {'상': 'text-bg-danger', '중': 'text-bg-warning', '하': 'text-bg-success'}


def extract_difficulty(job_block_text: str):
    m = re.search(r'채용.{0,6}난이도[^:：]*[:：]\*{0,2}\s*\[?\s*(상|중|하)', job_block_text)
    return m.group(1) if m else None


def extract_job_title(job_block_text: str) -> str:
    first_line = job_block_text.split('\n', 1)[0]
    m = re.match(r'^#{2,4}\s*\[?(.+?)\]?\s*$', first_line.strip())
    return m.group(1).strip() if m else first_line.strip('# ').strip()


def job_body(job_block_text: str) -> str:
    """### 헤더 첫 줄을 뗀 나머지 본문(마크다운 렌더용)."""
    lines = job_block_text.split('\n', 1)
    return lines[1] if len(lines) > 1 else ''


def deepdive_jobs(analysis_text: str) -> list:
    """expertise_analysis 전체 텍스트에서 딥다이브 매핑 섹션의 직무 블록만 뽑아
    [{'title', 'difficulty', 'body_raw'}, ...] 형태로 반환. 없으면 빈 리스트."""
    sections = split_top_sections(analysis_text)
    deepdive_idx = next((idx for idx, s in enumerate(sections) if is_deepdive_section(s)), None)
    if deepdive_idx is None:
        return []
    deepdive_section = sections[deepdive_idx]
    deepdive_body = deepdive_section.split('\n', 1)[1] if '\n' in deepdive_section else ''
    _, job_blocks_raw = split_job_blocks(deepdive_body)
    return [
        {'title': extract_job_title(jb), 'difficulty': extract_difficulty(jb), 'body_raw': job_body(jb)}
        for jb in job_blocks_raw
    ]


def b64_encode(text: str) -> str:
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


# ── 공용 HTML 인프라(Bootstrap 5 + marked.js/DOMPurify) ─────────────────────
# 연구원 개별 프로필(app.py)과 동일한 CDN 버전을 사용해 톤을 맞춘다.
BOOTSTRAP_CSS = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.6/dist/css/bootstrap.min.css'
BOOTSTRAP_ICONS_CSS = 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css'
BOOTSTRAP_JS = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.6/dist/js/bootstrap.bundle.min.js'
MARKED_JS = 'https://cdn.jsdelivr.net/npm/marked@4/marked.min.js'
DOMPURIFY_JS = 'https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js'

# 연구원 개별 프로필(assets/custom.css)과 동일한 애플 스타일 팔레트를 그대로 사용
BASE_HTML_STYLE = """
  :root {
    --gs-bg:        #f5f5f7;
    --gs-surface:   #ffffff;
    --gs-border:    #e8e8ed;
    --gs-border-2:  #d2d2d7;
    --gs-text:      #1d1d1f;
    --gs-muted:     #6e6e73;
    --gs-label:     #86868b;
    --gs-accent:    #0071e3;
    --gs-font: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text',
               'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
  }
  body {
    font-family: var(--gs-font); color: var(--gs-text); background-color: var(--gs-bg);
    -webkit-font-smoothing: antialiased; letter-spacing: -0.011em;
    padding: 48px 16px 96px;
  }
  h1, h2, h3, h4, h5, h6 { font-family: var(--gs-font); letter-spacing: -0.02em; }
  .page-header { text-align: center; margin-bottom: 32px; }
  .page-header h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 6px; }
  .page-header p { color: var(--gs-muted); font-size: 0.86rem; }
  .toc { max-width: 900px; margin: 0 auto 40px; display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
  .toc a { text-decoration: none; }
  .md-render { font-size: 0.82rem; color: #333; }
  .md-render h1, .md-render h2, .md-render h3, .md-render h4 { font-size: 0.86rem; margin: 10px 0 4px; color: var(--gs-text); }
  .md-render p { margin: 4px 0; }
  .md-render ul, .md-render ol { padding-left: 20px; margin: 4px 0 8px; }
  .md-render li { margin: 2px 0; }
  .md-render table { width: 100%; border-collapse: collapse; font-size: 0.78rem; margin: 8px 0; }
  .md-render th, .md-render td { border: 1px solid var(--gs-border); padding: 6px 8px; text-align: left; }
  .md-render th { background: var(--gs-bg); font-weight: 600; color: var(--gs-muted); }
  .empty { color: #98989d; font-size: 0.82rem; font-style: italic; }
"""

RENDER_SCRIPT = """
document.querySelectorAll('.md-render[data-md-b64]').forEach(function (el) {
  var raw = decodeURIComponent(escape(atob(el.dataset.mdB64)));
  var parsed = marked.parse(raw);
  el.innerHTML = (window.DOMPurify ? DOMPurify.sanitize(parsed) : parsed);
});
"""


def html_page(title: str, heading: str, subtitle: str, body_html: str, extra_style: str = '') -> str:
    """Bootstrap+marked.js 기반 공용 리포트 페이지 뼈대."""
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{BOOTSTRAP_CSS}">
<link rel="stylesheet" href="{BOOTSTRAP_ICONS_CSS}">
<style>{BASE_HTML_STYLE}{extra_style}</style>
</head>
<body>
<div class="page-header">
  <h1>{heading}</h1>
  <p>{subtitle}</p>
</div>
{body_html}
<script src="{MARKED_JS}"></script>
<script src="{DOMPURIFY_JS}"></script>
<script src="{BOOTSTRAP_JS}"></script>
<script>{RENDER_SCRIPT}</script>
</body>
</html>'''
