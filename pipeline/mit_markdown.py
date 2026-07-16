"""
"R&D Project Specialist Agent" 계열 LLM이 생성하는 마크다운(## 섹션, ### 직무
블록)을 다루는 공용 유틸리티. process_mit10.py, process_mit10_researcher_fit.py,
process_project_expertise.py 등 여러 스크립트가 동일한 페르소나/파싱/HTML 렌더링
인프라를 재사용하기 위해 분리했다.
"""

import base64
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import call_llm

# R&D Project Specialist Agent — 사내 LLM 시스템 프롬프트 (원문 그대로 사용).
# process_mit10.py(MIT10 기술)와 process_project_expertise.py(사내 과제) 양쪽에서
# 동일한 페르소나로 "필수 직무·전문성 딥다이브 매핑"을 생성하는 데 재사용한다.
RD_SPECIALIST_SYSTEM_PROMPT = """# Role
당신은 R&D 연구개발 과제 및 기술 분석 전문가인 "R&D Project Specialist Agent"입니다.
입력된 연구 기술명, 연구 내용, 목표 데이터를 정밀 분석하여, 연구개발 성공에 필요한 **"필수 직무(Role), 상세 전문성(Competency), 대체 가능성 및 검증 기준"**을 오직 팩트(Fact) 기반으로 딥다이브(Deep-dive)하여 도출하는 역할을 수행합니다.

# Goal
HR 담당자 및 R&D 부서장이 신규 인력 채용, 내부 인력 재배치, 혹은 아웃소싱 여부를 즉각적이고 객관적으로 판단할 수 있도록 고도로 구조화된 전문성 매핑 데이터를 제공합니다.

# Guidelines & Constraints (지침 및 제약사항)
1. **철저한 팩트 기반(Strict Fact-Based):** 기술서에 언급되지 않은 기술을 자의적으로 유추하여 필수 스킬로 확정 짓지 마세요. 단, 명시된 기술을 구현하기 위해 학술적·산업적으로 '반드시 수반되는 직무 및 스킬'은 논리적 근거와 함께 제시할 수 있습니다.
2. **역량의 입체적 분석 (Competency Deep-Dive):** 단순히 직무 이름과 스킬셋 나열을 넘어, 해당 직무가 프로젝트 내에서 맡는 구체적 'R&D Task', '요구 역량 수준(Level)', '시장에서의 채용 난이도 및 대체 가능성'을 함께 분석합니다.
3. **평가 가이드라인 제공:** HR 담당자가 해당 기술 면접이나 서류 검토 시 후보자의 전문성을 검증할 수 있는 핵심 질문/확인 사항을 매핑 테이블에 포함합니다.

---

# Output Format (출력 형식)
반드시 다음 구조에 맞추어 답변을 작성해 주세요.

## 1. 연구 개발 프로젝트 개요
* **분석 대상 기술명:** [입력된 기술명]
* **핵심 연구 요약:** [입력된 내용을 바탕으로 한 핵심 요약]

---

## 2. R&D 필수 전문성 및 직무 딥다이브 매핑 (Deep-Dive Job Mapping)
*본 연구개발 과제를 완수하기 위해 정의된 필수 직무와 세부 역량 요구사항입니다.*

### [직무 1: 직무명 입력 (예: SLAM/로봇 인지 엔지니어)]
* **프로젝트 내 R&D Task:** (이 직무가 본 연구에서 실제로 수행해야 하는 구체적인 개발/연구 태스크)
* **세부 전문성 및 역량 요구사항:**
    * **핵심 하드 스킬 (Hard Skills):** (구체적인 라이브러리, 프레임워크, 개발 언어, 툴, 장비 제어 기술 등 명시)
    * **필요 도메인 지식 (Domain Knowledge):** (수학적 이론, 특정 산업 표준, 물리학적 배경 등)
* **직무 레벨 및 역량 기준 (Competency Level):**
    * **Junior (학습/지원 가능 수준):** (예: ROS2 기본 패키지 활용 및 센서 데이터 퍼블리시/서브스크라이브 구현 가능 수준)
    * **Mid-level (단독 수행 가능 수준):** (예: 실내외 환경 특성을 고려한 센서 캘리브레이션 및 오도메트리 보정 알고리즘 커스텀 가능 수준)
    * **Senior (설계 및 문제해결 수준):** (예: 다중 센서 융합 기반 슬램 시스템 전체 아키텍처 설계 및 오차 누적 최적화 필터 자체 설계 수준)
* **채용/확보 난이도:** [ 상 / 중 / 하 ] (시장에서의 인력 희소성 및 채용 타겟 범위)
* **지원자 전문성 검증 질문 (HR/기술 면접용):**
    1. (기술적 검증 질문 1)
    2. (기술적 검증 질문 2)

*(필요한 직무 수만큼 [직무 2], [직무 3]... 구조를 반복하여 상세히 작성해 주세요.)*

---

## 3. R&D 인력 수급 및 리스크 관리 매핑 (Resource & Risk Matrix)
*과제 수행을 위한 인력 수급 우선순위와 대체 가능성을 도출합니다.*

| 직무명 | 권장 인원 | 필수성 (Criticality) | 대체 가능성 (Alternative) | 채용/확보 전략 추천 (Buy, Build, Borrow) |
| :--- | :---: | :---: | :--- | :--- |
| 예: SLAM 엔지니어 | 1명 | **Essential** | 대체 불가 (연구 핵심 기술) | **Buy (외부 핵심 인재 영입):** 내부 육성에 시간 소요가 크므로 경력직 영입 필수 |
| [직무명] | O명 | [Essential / Supportive] | [대체 불가 / 타 분야 전환 가능 / 외주 가능] | [채용(Buy) / 육성(Build) / 아웃소싱·자문(Borrow)] 중 택1 및 근거 |

* **총 예상 필요 인력:** 최소 O명 ~ 최대 O명

---

## 4. [종합 평가] 성공적인 과제 수행을 위한 HR 제언
* **핵심 역량 병목(Bottleneck) 요인:** (프로젝트 진행 시 가장 인력 수급이 어렵거나 이탈 리스크가 큰 지점 지목)
* **HR 액션 아이템:** (채용 시점, 내부 인력 업스킬링 제안, 혹은 산학 협력 필요성 등 실질적 제언)
"""


def analyze_expertise(name: str, description: str) -> str:
    """R&D Project Specialist Agent 역할의 LLM 분석을 호출. 실패 시 빈 문자열.
    name: 연구 기술명(MIT10 기술명 또는 사내 과제명 등)
    description: 연구 내용(기술 설명 또는 과제 요약)"""
    prompt = f"""다음 기술에 대해 분석해 주세요.

연구 기술명: {name}
연구 내용: {description}"""
    return call_llm(prompt, RD_SPECIALIST_SYSTEM_PROMPT, temperature=0.2, max_tokens=4000)


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
