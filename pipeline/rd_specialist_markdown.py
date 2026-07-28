"""
"R&D Project Specialist Agent" 계열 LLM이 생성하는 마크다운(## 섹션, ### 직무
블록)을 다루는 공용 유틸리티. process_project_expertise.py, process_researcher_expertise.py,
process_project_researcher_fit.py 등 여러 스크립트가 동일한 페르소나/파싱 로직과,
그 결과를 보여주는 "콘솔"형 HTML 리포트 공용 인프라(CONSOLE_STYLE/console_page/
stat_row_html)를 재사용하기 위해 분리했다. 네 개 리포트(연구원 유사도/과제 전문성/
연구원 전문성/과제-연구원 매칭)가 모두 이 공용 인프라 위에서 렌더링되므로, 색상
토큰이나 사이드바·카드 스타일을 바꾸려면 이 파일만 고치면 된다.
"""

import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import call_llm


def group_ordered(items: list, key_fn) -> list:
    """items를 key_fn(item) 그룹 키 기준으로 묶어 [(key, [item, ...]), ...]로 반환.
    HTML 리포트를 부서/조직 등 기준으로 시각적으로 묶어 보여줄 때 사용
    (process_researcher_expertise.py, process_project_expertise.py 등). 그룹은
    키 문자열 기준 정렬하되, 빈 키('미분류')는 항상 맨 뒤로 보낸다."""
    groups: dict = {}
    for item in items:
        key = key_fn(item) or '미분류'
        groups.setdefault(key, []).append(item)
    keys = sorted(groups.keys(), key=lambda k: (k == '미분류', k))
    return [(k, groups[k]) for k in keys]


# ── 조직도(팀참조시트/team_refer.csv 기반) ──────────────────────────────────
# "보유 전문성" 콘솔의 연구원/연구원↔연구원/연구원↔과제 3개 리포트가 좌측
# 사이드바에 공통으로 쓰는 확장/축소 가능한 조직도 트리 인프라.


def read_team_refer(out_dir: str) -> list:
    """team_refer.csv를 dict 리스트로 반환한다(build_org_tree()가 dep_id/
    upper_dep_id로 부모-자식 관계를 판단하므로 행 순서는 무관). 파일이 없으면
    빈 리스트(호출부가 조직도 없이 기존 방식으로 폴백할 수 있도록)."""
    path = os.path.join(out_dir, 'team_refer.csv')
    if not os.path.exists(path):
        return []
    import pandas as pd
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    return df.to_dict('records')


def build_org_tree(rows: list) -> list:
    """team_refer.csv 행들을 dep_id(자신의 조직 ID)/upper_dep_id(상위 조직의
    dep_id) 기준으로 계층화한다 — 각 행이 자신의 부모를 명시적으로 갖고 있으므로
    파일에 적힌 행 순서와 무관하게 정확한 계층을 구성한다(예전 team_layer
    스택 방식은 엑셀이 계층 순서대로 적혀 있다는 전제가 깨지면 잘못된 트리가
    만들어졌음). upper_dep_id가 비어 있거나, 가리키는 dep_id가 데이터에 없으면
    최상위 노드로 취급한다. 각 노드의 자식들은 code3(조직 위계·표시 순서 코드)
    오름차순으로 정렬한다.
    반환: 최상위 노드 리스트, 각 노드는
      {project_name, end_name, team_layer(int), researcher_id, name,
       assignment_name, code3, dep_id, upper_dep_id, children: [...]}"""
    nodes: list = []
    nodes_by_id: dict = {}
    for row in rows:
        try:
            layer = int(row.get('team_layer') or 0)
        except (TypeError, ValueError):
            continue
        if layer <= 0:
            continue
        node = {**row, 'team_layer': layer, 'children': []}
        nodes.append(node)
        dep_id = (row.get('dep_id') or '').strip()
        if dep_id:
            nodes_by_id[dep_id] = node

    roots: list = []
    for node in nodes:
        upper_dep_id = (node.get('upper_dep_id') or '').strip()
        parent = nodes_by_id.get(upper_dep_id) if upper_dep_id else None
        (parent['children'] if parent is not None else roots).append(node)

    def _sort(items: list):
        items.sort(key=lambda n: n.get('code3', ''))
        for n in items:
            _sort(n['children'])

    _sort(roots)
    return roots


def nav_items_html(items: list) -> str:
    """[(href, label, count|None), ...] -> nav-item 링크 목록 HTML. 조직도
    리프 노드에 붙는 연구원/과제·직무 목록에 재사용한다."""
    if not items:
        return ''
    rows = ''.join(
        f'<a class="nav-item" href="{href}"><span>{html.escape(label)}</span>'
        + (f'<span class="n-count">{count}</span>' if count is not None else '')
        + '</a>'
        for href, label, count in items
    )
    return f'<div class="org-node-people">{rows}</div>'


def org_tree_html(tree: list, node_content_fn=None) -> str:
    """조직도를 <details>/<summary> 중첩 구조로 렌더링한다(JS 없이 클릭으로
    확장/축소). 라벨은 '{과제명통일}({직책} {성명})' 형식(예: '기계시스템연구팀
    (PL 정재원)'). node_content_fn(node) -> str|None: 해당 조직 노드에 붙일
    추가 콘텐츠(nav_items_html로 만든 연구원/과제 목록 등) — 없으면 생략.
    team_layer 1~2(상위 조직)는 기본으로 펼쳐서 보여준다."""
    def _label(node: dict) -> str:
        head = html.escape(node.get('end_name') or node.get('project_name') or '')
        assignment = (node.get('assignment_name') or '').strip()
        person = (node.get('name') or '').strip()
        who = f'{assignment} {person}'.strip()
        who_html = f' <span class="org-node-who">({html.escape(who)})</span>' if who else ''
        return f'<span class="org-node-head">{head}</span>{who_html}'

    def _node_html(node: dict) -> str:
        extra = (node_content_fn(node) if node_content_fn else '') or ''
        children_html = ''.join(_node_html(c) for c in node['children'])
        body = f'{extra}{children_html}'
        if not body:
            return f'<div class="org-node-leaf">{_label(node)}</div>'
        open_attr = ' open' if node['team_layer'] <= 2 else ''
        return f'<details class="org-node"{open_attr}><summary>{_label(node)}</summary>{body}</details>'

    return f'<div class="org-tree">{"".join(_node_html(n) for n in tree)}</div>'


def map_link_html(researcher_id: str) -> str:
    """연구원 카드 우측 상단에 붙는 '전문성 유사맵으로 이동' 아이콘. iframe
    안에서 그대로 클릭하면 부모(top) 문서를 이동시켜야 하므로 target="_top"
    필수 — 그래야 iframe 안이 아니라 실제 대시보드가 전문성 유사맵 탭으로
    전환된다."""
    href = f'/researcher-similarity-map?highlight_researcher={researcher_id}'
    return (
        f'<a class="map-link" href="{href}" target="_top" title="전문성 유사맵에서 위치 보기">'
        f'📍 유사맵</a>'
    )


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


def analyze_expertise(name: str, description: str) -> str:
    """R&D Project Specialist Agent 역할의 LLM 분석을 호출. 실패 시 빈 문자열.
    name: 연구 기술명(사내 과제명 등)
    description: 연구 내용(기술 설명 또는 과제 요약)"""
    prompt = f"""다음 기술에 대해 분석해 주세요.

연구 기술명: {name}
연구 내용: {description}"""
    # 추론형 모델의 사고 과정 토큰 소모를 감안해 여유 있게 잡는다(finish_reason=length 방지).
    return call_llm(prompt, RD_SPECIALIST_SYSTEM_PROMPT, temperature=0.2, max_tokens=6000)


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


def extract_difficulty(job_block_text: str):
    m = re.search(r'채용.{0,6}난이도[^:：]*[:：]\*{0,2}\s*\[?\s*(상|중|하)', job_block_text)
    return m.group(1) if m else None


def extract_job_title(job_block_text: str) -> str:
    first_line = job_block_text.split('\n', 1)[0]
    m = re.match(r'^#{2,4}\s*\[?(.+?)\]?\s*$', first_line.strip())
    return m.group(1).strip() if m else first_line.strip('# ').strip()


def job_body(job_block_text: str) -> str:
    """### 헤더 첫 줄을 뗀 나머지 본문."""
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


# ── 과제/직무 카드 HTML (process_project_expertise.py, researcher_fit.py의
#    "과제 전문성" 탭이 공유) ─────────────────────────────────────────────────

DIFF_VARIANT = {'상': 'danger', '중': 'warn', '하': 'good'}


def job_card_html(job: dict) -> str:
    """deepdive_jobs()가 뽑은 직무 블록 하나를 job-card로 렌더링. R&D Task/Hard
    Skills/Domain Knowledge/역량 기준은 parse_job_fields()로 파싱한 값만 표시하고
    (못 찾은 필드는 생략), 검증 질문은 <details>로 접어서 보여준다(JS 불필요)."""
    fields = parse_job_fields(job['body_raw'])
    diff = job.get('difficulty')
    diff_pill = (
        f'<span class="pill {DIFF_VARIANT.get(diff, "low")}">채용난이도 {html.escape(diff)}</span>'
        if diff else ''
    )

    kv_items = []
    if fields['rd_task']:
        kv_items.append(f"<dt>R&amp;D Task</dt><dd>{html.escape(fields['rd_task'])}</dd>")
    if fields['hard_skills']:
        kv_items.append(f"<dt>Hard Skills</dt><dd>{html.escape(fields['hard_skills'])}</dd>")
    if fields['domain_knowledge']:
        kv_items.append(f"<dt>Domain Knowledge</dt><dd>{html.escape(fields['domain_knowledge'])}</dd>")
    levels = [
        f'{label} — {html.escape(fields[key])}'
        for key, label in (('junior', 'Junior'), ('mid', 'Mid'), ('senior', 'Senior'))
        if fields[key]
    ]
    if levels:
        kv_items.append(f"<dt>역량 기준</dt><dd>{'<br>'.join(levels)}</dd>")
    kv_html = f'<dl class="kv">{"".join(kv_items)}</dl>' if kv_items else '<p class="empty">세부 항목 데이터 없음</p>'

    questions_html = ''
    if fields['questions']:
        q_items = ''.join(f'<li>{html.escape(q)}</li>' for q in fields['questions'])
        questions_html = f'<details class="more"><summary>전문성 검증 질문</summary><ol>{q_items}</ol></details>'

    return f'''<div class="job-card">
  <div class="job-top"><h4>{html.escape(job['title'])}</h4>{diff_pill}</div>
  {kv_html}
  {questions_html}
</div>'''


def project_card_html(item: dict, jobs: list, anchor: str) -> str:
    keywords = (item.get('keywords_kr') or []) + (item.get('keywords_en') or [])
    overview = (
        f"<b>핵심 기술</b> {html.escape(item.get('core_tech') or '확인 불가')} · "
        f"<b>산출물</b> {html.escape(item.get('deliverable') or '확인 불가')} · "
        f"<b>기술적 난제</b> {html.escape(item.get('challenge') or '확인 불가')}"
    )
    chip_row = ''.join(f'<span class="chip">{html.escape(k)}</span>' for k in keywords)

    if jobs:
        jobs_html = f'<div class="job-grid">{"".join(job_card_html(j) for j in jobs)}</div>'
    else:
        jobs_html = '<p class="empty">전문성 분석 데이터 없음 (python pipeline/process_project_expertise.py 실행 필요)</p>'

    # 딥다이브 매핑 외 나머지 섹션(프로젝트 개요/인력 수급 매트릭스/HR 제언)은
    # 자유 형식 마크다운이라, 외부 마크다운 파서 없이 원문 그대로 접어서 보여준다.
    analysis_text = item.get('expertise_analysis', '')
    other_sections = [s for s in split_top_sections(analysis_text) if not is_deepdive_section(s)]
    other_html = ''
    if other_sections:
        raw = html.escape('\n\n'.join(other_sections))
        other_html = (
            '<details class="more"><summary>프로젝트 개요·인력 수급 매트릭스·HR 제언 (원문)</summary>'
            f'<pre class="raw-md">{raw}</pre></details>'
        )

    return f'''<div class="card" id="{anchor}">
  <div class="card-top"><h3>{html.escape(item['project_name'])}</h3></div>
  <p class="card-sub">{overview}</p>
  <div class="chip-row">{chip_row}</div>
  {jobs_html}
  {other_html}
</div>'''


# ── 콘솔형 리포트 공용 CSS/셸 ────────────────────────────────────────────────
# 외부 CDN(Bootstrap/marked.js) 없이 완전히 독립적인 정적 페이지. 연구원 유사도/
# 과제 전문성/연구원 전문성/과제-연구원 매칭 4개 리포트가 모두 동일한 색상
# 토큰과 사이드바+요약통계+카드 문법을 공유해 한 가족처럼 보이도록 한다.
CONSOLE_STYLE = """
  :root {
    --bg: #f3f4f7; --sidebar: #ffffff; --panel: #ffffff; --line: #e2e4ea;
    --ink: #1a1d29; --ink-soft: #6b7080;
    --accent: #4453d6; --accent-weak: rgba(68,83,214,0.08);
    --good: #1f8a5f; --good-weak: rgba(31,138,95,0.1);
    --warn: #a3720a; --warn-weak: rgba(163,114,10,0.1);
    --low: #6b7080; --low-weak: rgba(107,112,128,0.1);
    --danger: #b23b3b; --danger-weak: rgba(178,59,59,0.1);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #101218; --sidebar: #171a22; --panel: #171a22; --line: #272b36;
      --ink: #e7e8ee; --ink-soft: #8b8fa3;
      --accent: #8b97f5; --accent-weak: rgba(139,151,245,0.12);
      --good: #5fbf90; --good-weak: rgba(95,191,144,0.12);
      --warn: #d1a444; --warn-weak: rgba(209,164,68,0.12);
      --low: #8b8fa3; --low-weak: rgba(139,143,163,0.12);
      --danger: #d9776e; --danger-weak: rgba(217,119,110,0.12);
    }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; display: flex; min-height: 100vh;
  }
  .sidebar {
    width: 250px; flex-shrink: 0; background: var(--sidebar); border-right: 1px solid var(--line);
    padding: 22px 16px; position: sticky; top: 0; height: 100vh; overflow-y: auto;
  }
  .sidebar h1 { font-size: 0.98rem; font-weight: 800; margin: 4px 6px 2px; letter-spacing: -0.01em; }
  .sidebar .tagline { font-size: 0.72rem; color: var(--ink-soft); margin: 0 6px 20px; line-height: 1.5; }
  .nav-group { margin-bottom: 4px; }
  .nav-group-label {
    font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--ink-soft); font-weight: 700; padding: 10px 6px 4px;
  }
  .nav-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 8px; border-radius: 6px; font-size: 0.82rem;
    text-decoration: none; color: var(--ink);
  }
  .nav-item:hover { background: var(--accent-weak); }
  .nav-item .n-count { font-size: 0.68rem; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
  /* 조직도(팀참조시트 기반) — JS 없이 <details>/<summary> 중첩으로 확장/축소 */
  .org-tree { margin-bottom: 4px; }
  details.org-node { margin: 1px 0; }
  details.org-node > summary {
    cursor: pointer; list-style: none; padding: 6px 8px; border-radius: 6px;
    font-size: 0.8rem; font-weight: 600; color: var(--ink); display: flex; align-items: baseline; gap: 4px;
  }
  details.org-node > summary::-webkit-details-marker { display: none; }
  details.org-node > summary::before { content: '▸'; color: var(--ink-soft); font-size: 0.7rem; }
  details.org-node[open] > summary::before { content: '▾'; }
  details.org-node > summary:hover { background: var(--accent-weak); }
  .org-node-head { font-weight: 700; }
  .org-node-who { color: var(--ink-soft); font-weight: 500; }
  .org-node-body { padding-left: 12px; border-left: 1px solid var(--line); margin-left: 8px; }
  .org-node-leaf {
    padding: 6px 8px; margin-left: 14px; font-size: 0.8rem; color: var(--ink-soft);
  }
  .org-node-people { padding-left: 12px; border-left: 1px solid var(--line); margin: 0 0 4px 8px; }
  main { flex: 1; min-width: 0; padding: 32px 40px 100px; }
  .content { max-width: 960px; }
  .stat-row { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; margin-bottom: 28px; }
  .stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
  .stat .num { font-size: 1.5rem; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
  .stat .lbl { font-size: 0.72rem; color: var(--ink-soft); margin-top: 2px; }
  .dept-heading {
    font-size: 0.78rem; font-weight: 700; color: var(--ink-soft); text-transform: uppercase;
    letter-spacing: 0.06em; margin: 32px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line);
  }
  .dept-heading:first-of-type { margin-top: 0; }
  .org-heading { font-size: 0.72rem; color: var(--ink-soft); margin: 16px 0 8px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; margin-bottom: 14px; }
  .card-top { display: flex; align-items: center; gap: 10px; margin-bottom: 3px; }
  .card-top h3 { margin: 0; font-size: 1rem; font-weight: 700; }
  .map-link {
    margin-left: auto; flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px;
    font-size: 0.72rem; font-weight: 600; color: var(--ink-soft); text-decoration: none;
    border: 1px solid var(--line); border-radius: 999px; padding: 3px 10px 3px 8px;
  }
  .map-link:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-weak); }
  .card-sub { font-size: 0.78rem; color: var(--ink-soft); margin-bottom: 12px; }
  .badge { font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
  .badge.senior { background: var(--accent-weak); color: var(--accent); }
  .badge.junior { background: var(--low-weak); color: var(--ink-soft); }
  .chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 14px; }
  .chip { font-size: 0.7rem; padding: 3px 9px; border-radius: 6px; background: var(--accent-weak); color: var(--accent); font-weight: 600; }
  .chip.kw { background: var(--bg); color: var(--ink-soft); border: 1px solid var(--line); }
  .table-wrap { overflow-x: auto; }
  table.match-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  table.match-table th {
    text-align: left; font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--ink-soft); font-weight: 700; padding: 6px 8px; border-bottom: 1px solid var(--line);
  }
  table.match-table td { padding: 9px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  table.match-table tr:last-child td { border-bottom: none; }
  .m-name { font-weight: 700; }
  .m-dept { font-size: 0.72rem; color: var(--ink-soft); }
  .m-score { font-variant-numeric: tabular-nums; font-weight: 700; white-space: nowrap; }
  .pill { display: inline-block; font-size: 0.68rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
  .pill.good { background: var(--good-weak); color: var(--good); }
  .pill.warn { background: var(--warn-weak); color: var(--warn); }
  .pill.low { background: var(--low-weak); color: var(--low); }
  .pill.danger { background: var(--danger-weak); color: var(--danger); }
  .m-ev, .m-ev-text { margin: 0; padding-left: 16px; color: var(--ink-soft); font-size: 0.78rem; }
  .m-ev-text { padding-left: 0; }
  .m-ev li { margin: 1px 0; }
  .m-warn { color: var(--danger); font-size: 0.74rem; margin-top: 2px; }
  .empty { color: var(--ink-soft); font-size: 0.82rem; font-style: italic; }
  .kv-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px,1fr)); gap: 16px; margin-top: 4px; }
  .kv-block { background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
  .kv-block .kv-title {
    font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent);
    font-weight: 700; margin-bottom: 6px;
  }
  dl.kv { margin: 0; font-size: 0.78rem; }
  dl.kv dt { color: var(--ink-soft); font-weight: 600; margin-top: 6px; }
  dl.kv dt:first-child { margin-top: 0; }
  dl.kv dd { margin: 1px 0 0; color: var(--ink); }
  .job-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px,1fr)); gap: 12px; margin-top: 4px; }
  .job-card { background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; }
  .job-top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 8px; }
  .job-top h4 { margin: 0; font-size: 0.9rem; font-weight: 700; }
  details.more { font-size: 0.78rem; margin-top: 6px; }
  details.more summary { cursor: pointer; color: var(--accent); font-weight: 600; }
  details.more ol, details.more ul { margin: 6px 0 0; padding-left: 18px; color: var(--ink-soft); }
  details.more pre.raw-md {
    margin: 8px 0 0; padding: 12px; background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.72rem; color: var(--ink-soft);
    white-space: pre-wrap; word-break: break-word;
  }
  /* CSS 전용 탭 (JS 없이 radio + :checked 형제 선택자) */
  .tabs input { display: none; }
  .tab-bar { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--line); }
  .tab-bar label {
    padding: 9px 16px; font-size: 0.84rem; font-weight: 600; color: var(--ink-soft);
    cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
  }
  .panel-a, .panel-b, .panel-c { display: none; }
  #tab-a:checked ~ .panel-a { display: block; }
  #tab-b:checked ~ .panel-b { display: block; }
  #tab-c:checked ~ .panel-c { display: block; }
  #tab-a:checked ~ .tab-bar label[for="tab-a"],
  #tab-b:checked ~ .tab-bar label[for="tab-b"],
  #tab-c:checked ~ .tab-bar label[for="tab-c"] {
    color: var(--accent); border-bottom-color: var(--accent);
  }
  /* CSS 전용 표시 개수 토글(연구원 ↔ 연구원 리포트, JS 없이 radio + 형제 선택자로
     행을 숨김/표시 — 데이터는 이미 서버에서 최대 개수까지 저장돼 있음) */
  input.cnt-radio { display: none; }
  .count-bar {
    display: flex; align-items: center; justify-content: flex-end; gap: 6px;
    margin-bottom: 16px; position: sticky; top: 0; background: var(--bg);
    padding: 6px 0; z-index: 3;
  }
  .count-bar span { font-size: 0.72rem; color: var(--ink-soft); margin-right: 2px; }
  .count-bar label {
    padding: 4px 12px; font-size: 0.78rem; font-weight: 600; color: var(--ink-soft);
    border: 1px solid var(--line); border-radius: 999px; cursor: pointer;
  }
  #count-3:checked ~ .count-bar label[for="count-3"],
  #count-5:checked ~ .count-bar label[for="count-5"],
  #count-10:checked ~ .count-bar label[for="count-10"] {
    background: var(--accent); border-color: var(--accent); color: #fff;
  }
  #count-3:checked ~ .sim-sections table.match-table tbody tr:nth-child(n+4) { display: none; }
  #count-5:checked ~ .sim-sections table.match-table tbody tr:nth-child(n+6) { display: none; }
  @media (max-width: 820px) {
    .sidebar { display: none; }
    main { padding: 24px 18px 80px; }
  }
"""


def console_page(title: str, sidebar_html: str, body_html: str) -> str:
    """콘솔형 리포트 공용 페이지 셸. 외부 CDN 없이 완전히 독립적인 정적 HTML
    문서를 만든다(연구원 유사도/과제 전문성/연구원 전문성/매칭 4개 리포트가
    공유)."""
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CONSOLE_STYLE}</style>
</head>
<body>
<nav class="sidebar">{sidebar_html}</nav>
<main><div class="content">{body_html}</div></main>
</body>
</html>'''


def stat_row_html(stats: list) -> str:
    """[(값, 라벨), ...] -> 요약 통계 카드 행 HTML."""
    cells = ''.join(
        f'<div class="stat"><div class="num">{v}</div><div class="lbl">{html.escape(l)}</div></div>'
        for v, l in stats
    )
    return f'<div class="stat-row">{cells}</div>'
