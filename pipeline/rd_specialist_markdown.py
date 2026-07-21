"""
"R&D Project Specialist Agent" 계열 LLM이 생성하는 마크다운(## 섹션, ### 직무
블록)을 다루는 공용 유틸리티. process_project_expertise.py, process_researcher_expertise.py,
process_project_researcher_fit.py, process_llm_compare.py 등 여러 스크립트가 동일한
페르소나/파싱/HTML 렌더링 인프라를 재사용하기 위해 분리했다.
"""

import base64
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import call_llm


def profile_suffix(profile: str) -> str:
    """출력/캐시 파일명에 붙일 접미사. 'default' profile은 기존 파일명을 그대로
    유지(하위 호환)하고, 그 외 profile은 '.<profile>'을 붙인다."""
    return '' if profile == 'default' else f'.{profile}'


def parse_profile_arg(argv: list, default: str = 'default') -> str:
    """CLI 인자에서 '--profile NAME' 형태를 파싱. 없으면 default 반환."""
    if '--profile' in argv:
        idx = argv.index('--profile')
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return default


# R&D Project Specialist Agent — 사내 LLM 시스템 프롬프트 (원문 그대로 사용).
# process_project_expertise.py(사내 과제) 등 여러 스크립트가 동일한 페르소나로
# "필수 직무·전문성 딥다이브 매핑"을 생성하는 데 재사용한다.
RD_SPECIALIST_SYSTEM_PROMPT = """# Role
당신은 R&D 연구개발 과제 및 기술 분석 전문가인 "R&D Project Specialist Agent"입니다.
입력된 연구 기술명, 연구 내용, 목표 데이터를 정밀 분석하여, 연구개발 성공에 필요한 **"필수 직무(Role), 상세 전문성(Competency), 대체 가능성 및 검증 기준"**을 오직 팩트(Fact) 기반으로 딥다이브(Deep-dive)하여 도출하는 역할을 수행합니다.

# Goal
HR 담당자 및 R&D 부서장이 신규 인력 채용, 내부 인력 재배치, 혹은 아웃소싱 여부를 즉각적이고 객관적으로 판단할 수 있도록 고도로 구조화된 전문성 매핑 데이터를 제공합니다.

# Guidelines & Constraints (지침 및 제약사항)
1. **철저한 팩트 기반(Strict Fact-Based):** 기술서에 언급되지 않은 기술을 자의적으로 유추하여 필수 스킬로 확정 짓지 마세요. 단, 명시된 기술을 구현하기 위해 학술적·산업적으로 '반드시 수반되는 직무 및 스킬'은 논리적 근거와 함께 제시할 수 있습니다.
2. **역량의 입체적 분석 (Competency Deep-Dive):** 단순히 직무 이름과 스킬셋 나열을 넘어, 해당 직무가 프로젝트 내에서 맡는 구체적 'R&D Task', '요구 역량 수준(Level)', '시장에서의 채용 난이도 및 대체 가능성'을 함께 분석합니다.
3. **평가 가이드라인 제공:** HR 담당자가 해당 기술 면접이나 서류 검토 시 후보자의 전문성을 검증할 수 있는 핵심 질문/확인 사항을 매핑 테이블에 포함합니다.
4. **선행연구소 특성 반영(양산 직무 제외 원칙):** 분석 대상 조직은 완제품 양산(Mass Production)이 목표가 아니라, 실현 가능성(Feasibility)을 검증하는 선행연구소입니다. 신뢰성(Reliability) 엔지니어링, 품질보증/품질관리(QA/QC), 양산 스케일업을 위한 생산기술·공정 엔지니어링, 수율/설비 개선 등 "완제품 양산 단계"에만 필요한 직무는 필수 직무에서 제외하세요. 단, 개념 검증(PoC)이나 시제품 제작 수준에서 실현 가능성을 확인하기 위해 최소한으로 필요한 생산기술·공정 엔지니어링 직무는 포함할 수 있습니다(양산 최적화가 아니라 "이 기술이 실제로 동작하는지 검증"하는 목적일 때만). 원천기술 확보, 이론/알고리즘 개발, 선행 실험·연구 등 선행연구 성격의 직무를 우선적으로 선정하세요.
5. **직무 개수 제한(최대 5개, 상한이지 목표치가 아님):** 딥다이브 매핑에 포함하는 직무는 최대 5개까지만 선정하세요. 위 4번 기준(선행연구 우선, 양산 단계 제외)을 통과하는 후보가 5개를 초과하면 연구 성공에 가장 핵심적인 직무 5개만 남기고 우선순위가 낮은 직무는 생략하세요. 반대로 후보가 5개 미만이면 억지로 5개를 채우지 말고 실제 해당하는 개수만큼만(예: 3개) 작성하세요.
6. **연구개발 직접 수행 직무만 선정(관리·기획·행정 직무 제외):** 프로젝트 매니저(PM), 사업 기획/기획 담당, 학술 기획 연구원, 행정 지원 등 연구개발을 직접 수행하지 않고 관리·기획·조율·행정 역할을 맡는 직무는 필수 직무에서 제외하세요. 딥다이브 매핑에는 실제로 연구·설계·구현·실험 등 기술적 R&D 작업을 손으로 직접 수행하는 기술 직무만 포함합니다.

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

*(위 선정 기준에 따라 최대 5개까지 [직무 2], [직무 3]... 구조를 반복해 작성하세요. 기준을 통과하는 직무가 5개보다 적으면 그 개수만큼만 작성하고 억지로 채우지 마세요.)*

---

## 3. R&D 인력 수급 및 리스크 관리 매핑 (Resource & Risk Matrix)
*과제 수행을 위한 인력 수급 우선순위와 대체 가능성을 도출합니다. 위 2번에서 선정한 직무(최대 5개)와
동일한 목록을 대상으로 하며, 여기서 새로운 직무를 추가하지 않습니다.*

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


def analyze_expertise(name: str, description: str, profile: str = 'default') -> str:
    """R&D Project Specialist Agent 역할의 LLM 분석을 호출. 실패 시 빈 문자열.
    name: 연구 기술명(사내 과제명 등)
    description: 연구 내용(기술 설명 또는 과제 요약)
    profile: 'default'(기존 사내 LLM) 또는 'thinkingcap'(2번째 사내 LLM, 비교용)"""
    prompt = f"""다음 기술에 대해 분석해 주세요.

연구 기술명: {name}
연구 내용: {description}"""
    return call_llm(prompt, RD_SPECIALIST_SYSTEM_PROMPT, temperature=0.2, max_tokens=4000, profile=profile)


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


# 키워드 pill 배지에 순환 적용할 색상 팔레트(다양한 색으로 구분). process_project_expertise.py,
# process_researcher_expertise.py 등 키워드를 pill로 보여주는 모든 리포트가 공유한다.
KEYWORD_PILL_COLORS = [
    '#0071e3', '#c9822e', '#3f8f57', '#c46b6b', '#7b6fb0', '#0c9aa8', '#c07d97', '#5f7a3d',
]


def keyword_pills_html(keywords: list) -> str:
    """키워드 목록을 색상이 순환되는 타원형(pill) 배지 목록 HTML로 렌더링. 빈 목록이면 빈 문자열."""
    if not keywords:
        return ''
    pills = ''.join(
        f'<span class="kw-pill" style="background-color:{KEYWORD_PILL_COLORS[i % len(KEYWORD_PILL_COLORS)]}">'
        f'{html.escape(kw)}</span>'
        for i, kw in enumerate(keywords)
    )
    return f'<div class="kw-pill-row">{pills}</div>'


def b64_encode(text: str) -> str:
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def _strip_label(text: str) -> str:
    return re.sub(r'\*\*', '', text).strip().strip('*').strip()


def parse_job_fields(body: str) -> dict:
    """직무 딥다이브 블록 본문에서 R&D Task/Hard Skills/Domain Knowledge/Junior/
    Mid/Senior/검증 질문을 파싱한다. LLM 응답마다 마크다운 표현 스타일이 달라도
    카드가 항상 같은 구조로 보이도록, 고정 라벨(영문 앵커: R&D Task, Hard Skills,
    Domain Knowledge, Junior, Mid-level, Senior)을 기준으로 값만 뽑아낸다.
    못 찾은 필드는 빈 값/빈 리스트로 둔다(지어내지 않음)."""
    fields = {
        'rd_task': '', 'hard_skills': '', 'domain_knowledge': '',
        'junior': '', 'mid': '', 'senior': '', 'questions': [],
    }
    in_questions = False
    for raw_line in body.split('\n'):
        line = raw_line.strip()
        if not line:
            continue

        if in_questions:
            m = re.match(r'^(?:\d+[.\)]|[*\-])\s+(.+)', line)
            if m and not re.search(r'\*\*[^*]+\*\*\s*[:：]', m.group(1)):
                fields['questions'].append(_strip_label(m.group(1)))
                continue
            in_questions = False  # 목록이 끝났으니 아래에서 다른 필드로 재검사

        m = re.search(r'R&D\s*Task\)?[^:：]*[:：]\*{0,2}\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['rd_task'] = _strip_label(m.group(1))
            continue
        m = re.search(r'Hard\s*Skills\)[^:：]*[:：]\*{0,2}\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['hard_skills'] = _strip_label(m.group(1))
            continue
        m = re.search(r'Domain\s*Knowledge\)[^:：]*[:：]\*{0,2}\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['domain_knowledge'] = _strip_label(m.group(1))
            continue
        m = re.search(r'Junior[^:：]*[:：]\*{0,2}\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['junior'] = _strip_label(m.group(1))
            continue
        m = re.search(r'Mid[\s\-]?level[^:：]*[:：]\*{0,2}\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['mid'] = _strip_label(m.group(1))
            continue
        m = re.search(r'Senior[^:：]*[:：]\*{0,2}\s*(.+)', line, re.IGNORECASE)
        if m:
            fields['senior'] = _strip_label(m.group(1))
            continue
        if re.search(r'검증\s*질문|면접', line):
            in_questions = True
            continue

    return fields


_FIELD_EMPTY_TEXT = '정보 없음'


def _field_text(value: str) -> str:
    return html.escape(value) if value else _FIELD_EMPTY_TEXT


def render_job_fields_html(fields: dict) -> str:
    """parse_job_fields() 결과를 항상 동일한 구조의 고정 템플릿으로 렌더링한다.
    과제/직무마다 LLM 응답 스타일이 달라 일부 항목이 파싱되지 않더라도, 4개
    소항목(R&D Task / 세부 전문성 및 역량 요구사항 / 직무 레벨 및 역량 기준 /
    지원자 전문성 검증 질문)을 항상 같은 순서로 표시하고(값이 없으면 안내 문구로
    채움), 섹션 자체를 생략하지 않는다 — 모든 과제·모든 직무 카드가 항상 동일한
    포맷으로 보이도록 하기 위함이다."""
    rd_task_block = f'''<div class="job-field">
  <div class="field-label">R&amp;D Task</div>
  <p>{_field_text(fields['rd_task'])}</p>
</div>'''

    skill_items = (
        f"<li><strong>Hard Skills:</strong> {_field_text(fields['hard_skills'])}</li>"
        f"<li><strong>Domain Knowledge:</strong> {_field_text(fields['domain_knowledge'])}</li>"
    )
    skill_block = f'''<div class="job-field">
  <div class="field-label">세부 전문성 및 역량 요구사항</div>
  <ul>{skill_items}</ul>
</div>'''

    level_items = (
        f"<li><strong>Junior:</strong> {_field_text(fields['junior'])}</li>"
        f"<li><strong>Mid-level:</strong> {_field_text(fields['mid'])}</li>"
        f"<li><strong>Senior:</strong> {_field_text(fields['senior'])}</li>"
    )
    level_block = f'''<div class="job-field">
  <div class="field-label">직무 레벨 및 역량 기준</div>
  <ul>{level_items}</ul>
</div>'''

    if fields['questions']:
        q_items = ''.join(f'<li>{html.escape(q)}</li>' for q in fields['questions'])
    else:
        q_items = f'<li>{_FIELD_EMPTY_TEXT}</li>'
    questions_block = f'''<div class="job-field">
  <div class="field-label">지원자 전문성 검증 질문</div>
  <ol>{q_items}</ol>
</div>'''

    return '\n'.join([rd_task_block, skill_block, level_block, questions_block])


# expertise_analysis(R&D Project Specialist Agent 출력)를 카드로 렌더링할 때
# 공통으로 쓰는 CSS. process_project_expertise.py 등 여러 스크립트가 공유한다.
EXPERTISE_CARD_STYLE = """
  .tech-card {
    max-width: 900px; margin: 0 auto 32px; border: 1px solid var(--gs-border);
    border-radius: 18px; background: var(--gs-surface); box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .tech-card .card-body { padding: 28px 32px; }
  .tech-header .badge { font-size: 0.7rem; }
  .tech-header h2 { font-size: 1.2rem; font-weight: 700; margin: 0; }
  .tech-desc { color: #444; font-size: 0.86rem; margin: 6px 0 22px; }
  .tech-desc p { margin: 0 0 4px; }
  .tech-desc p:last-child { margin-bottom: 0; }
  .kw-pill-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .kw-pill {
    display: inline-block; border-radius: 999px; padding: 3px 12px;
    font-size: 0.72rem; font-weight: 600; color: #fff; white-space: nowrap;
  }
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
  .job-field { margin-bottom: 10px; }
  .job-field:last-child { margin-bottom: 0; }
  .job-field .field-label {
    font-size: 0.68rem; font-weight: 700; color: var(--gs-accent); text-transform: uppercase;
    letter-spacing: 0.03em; margin-bottom: 3px;
  }
  .job-field p { font-size: 0.82rem; margin: 0; color: #333; }
  .job-field ul, .job-field ol { font-size: 0.82rem; margin: 0; padding-left: 18px; color: #333; }
  .job-field li { margin: 2px 0; }
  .other-sections .accordion-button {
    font-size: 0.82rem; font-weight: 600; color: var(--gs-muted); background: var(--gs-bg);
  }
  .other-sections .accordion-button:not(.collapsed) { color: var(--gs-text); background: var(--gs-bg); box-shadow: none; }
  .other-sections .accordion-button:focus { box-shadow: none; }
"""


def render_expertise_html(analysis_text: str, anchor: str, *, empty_message: str) -> tuple:
    """expertise_analysis 마크다운에서 딥다이브 매핑 카드 HTML과 나머지 섹션
    아코디언 HTML을 만들어 (deepdive_html, other_html) 튜플로 반환한다.
    process_project_expertise.py 등 여러 스크립트가 공유한다."""
    sections = split_top_sections(analysis_text)
    deepdive_idx = next((idx for idx, s in enumerate(sections) if is_deepdive_section(s)), None)

    if deepdive_idx is None:
        deepdive_html = (
            '<p class="deepdive-title"><i class="bi bi-diagram-3-fill"></i> '
            'R&amp;D 필수 전문성 및 직무 딥다이브 매핑</p>'
            f'<p class="empty">{empty_message}</p>'
        )
        return deepdive_html, ''

    deepdive_section = sections[deepdive_idx]
    other_sections = sections[:deepdive_idx] + sections[deepdive_idx + 1:]
    # 섹션 자체의 '## 2. ...' 헤더 행은 별도 타이틀로 그리므로 본문에서 제외
    deepdive_body = deepdive_section.split('\n', 1)[1] if '\n' in deepdive_section else ''
    intro_raw, job_blocks_raw = split_job_blocks(deepdive_body)

    deepdive_lead = (
        f'<p class="deepdive-lead md-render" data-md-b64="{b64_encode(intro_raw)}"></p>'
        if intro_raw.strip() else ''
    )
    job_cards = []
    for jb in job_blocks_raw:
        title = html.escape(extract_job_title(jb))
        diff = extract_difficulty(jb)
        diff_badge = (
            f'<span class="badge rounded-pill {DIFFICULTY_BADGE.get(diff, "text-bg-secondary")}">'
            f'채용난이도 {diff}</span>'
        ) if diff else ''
        body_fields = parse_job_fields(job_body(jb))
        body_html = render_job_fields_html(body_fields)
        job_cards.append(f'''<div class="col-md-6">
  <div class="job-card card">
    <div class="card-body">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
        <p class="job-title mb-0">{title}</p>
        {diff_badge}
      </div>
      {body_html}
    </div>
  </div>
</div>''')
    deepdive_html = f'''<p class="deepdive-title"><i class="bi bi-diagram-3-fill"></i> R&amp;D 필수 전문성 및 직무 딥다이브 매핑</p>
{deepdive_lead}
<div class="row row-cols-1 row-cols-lg-2 g-3">{''.join(job_cards)}</div>'''

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
      <div class="accordion-body md-render" data-md-b64="{b64_encode(other_raw)}"></div>
    </div>
  </div>
</div>'''

    return deepdive_html, other_html


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
