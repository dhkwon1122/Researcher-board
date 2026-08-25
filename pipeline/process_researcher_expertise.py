"""
연구원 보유 전문성 분석 모듈 (사내 LLM)

한 연구원의 학력/전공, 과제 이력, 직무 이력, 핵심기술, 보유기술, 논문, 특허
데이터를 모두 모아 "R&D Talent Profiling Agent" 역할의 사내 LLM에게 분석을
맡기고, 결과를 구조화된 JSON과 사람이 보는 HTML 리포트로 저장한다.

Source:
  data/processed/researchers.csv
  data/processed/education.csv                      (degree, major)
  data/processed/tasks.csv + tasks_information.csv   (task_name 기준 조인)
  data/processed/project_personnel.csv               (과제 문서에서 뽑은 담당 업무,
                                                        process_project_expertise.py가 생성)
  data/processed/job_profile.csv                     (연구원별 직무 이력, wide)
  data/processed/job_profile_info_standard.json      (직무명 → 정의, 표준)
  data/processed/job_profile_info_sait.json          (직무명 → 세부직무/정의, 부서)
  data/processed/core_technology.csv                 (연구원당 1행: 분야/기술명/등급)
  data/processed/core_technology_grade_info.json     (등급 S/A/B 개요)
  data/processed/tech_ownership.csv                  (tech_1~5/lv_1~5/portion_1~5)
  data/processed/tech_ownership_lv_info.json         (Lv 1~5 개요)
  data/processed/publications.csv                    (저널 권위도는 journal_authority.py가 별도 조회/캐시)
  data/processed/patents.csv
  data/processed/work_objective.csv                  (24~26년 업무목표, process_work_objective.py가 생성)

저널 권위도 조회/캐시 로직은 pipeline/journal_authority.py로 분리되어 있다.
평가 값이 실제로 채워진 저널은 건너뛰고, 값이 비어 있는(신규거나 이전 조회
실패로 남은) 저널만 매번 재조회한다. 캐시와 무관하게 전체 저널을 다시
확인하려면(둘 다 동일하게 동작 — 이 파일 실행 시 자동으로 함께 호출됨):
  python pipeline/process_researcher_expertise.py --refresh-journals
  python pipeline/journal_authority.py --refresh-journals   (독립 실행)

Output:
  data/processed/연구원 보유 전문성 분석.json
  data/processed/연구원 보유 전문성 분석.html  (연구원별 카드 리포트)
  data/processed/journal_authority.json  (저널명별 권위도 평가 캐시 — 누적 재사용)

※ 프롬프트에는 researcher_id/이름 등 개인 식별 정보를 절대 포함하지 않는다.
  이력 내용(과제/직무/기술/논문/특허)만 사내 LLM에 전달하고, 결과는 호출부에서
  researcher_id에 매핑한다.

이미 저장된 JSON을 LLM 재호출 없이 HTML로만 다시 만들기:
  python pipeline/process_researcher_expertise.py --html-only

사용법:
  python pipeline/process_researcher_expertise.py [--html-only] [--refresh-journals]
"""

import html
import json
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean  # noqa: E402
from llm_client import (  # noqa: E402
    call_llm, extract_json, get_truncation_count, max_concurrency,
    reset_truncation_count, run_concurrent,
)
import journal_authority  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402
import result_archive  # noqa: E402

_SYSTEM_PROMPT = """# Role
당신은 R&D 인재 전문성 분석 전문가인 "R&D Talent Profiling Agent"입니다.
입력된 한 연구원의 학력, 과제 수행 이력, 직무 이력, 핵심기술, 보유기술, 논문,
특허, 업무목표 데이터를 정밀 분석하여, 이 연구원이 실제로 맡아온 역할·업무와
보유한 전문성을 오직 팩트(Fact) 기반으로 도출하는 역할을 수행합니다.

# Goal
HR 담당자와 R&D 부서장이 이 연구원이 "실제로 어떤 일을 해왔는지(역할·책임)"와
"무엇을 할 줄 아는지(전문지식·역량)"를 한눈에 파악하고, 향후 프로젝트 배치·
인력 매칭·채용 판단에 활용할 수 있도록 구조화된 전문성 프로필을 제공합니다.

# Guidelines & Constraints
1. 철저한 팩트 기반: 입력 데이터에 명시적으로 드러나지 않는 내용을 임의로
   추정하여 확정하지 마세요. 데이터로부터 합리적으로 추론 가능한 내용은
   근거와 함께 서술할 수 있습니다.
2. 판단 근거가 되는 데이터가 전혀 없는 항목은 빈 배열([])로 남기세요(지어낸
   내용을 채우지 마세요).
3. [업무목표] 항목은 연구원마다 작성 성실도·분량 차이가 커서, 내용이 소략하다는
   이유만으로 전문성을 낮게 판단하지 마세요. 다른 항목에 이미 충분한 근거가
   있다면 업무목표는 보조 참고 자료로만 활용하세요.
4. key_responsibilities(주요 역할과 책임/업무내용)는 [과제 수행 이력]의 각
   과제에서 실제로 맡았을 역할, [과제 내 담당 업무](과제 문서에 실제로 기록된
   구체적 담당 업무 — 있으면 가장 신뢰도 높은 근거로 우선 활용), [직무 이력]에
   기록된 직무명과 수행 기간, [업무목표]에 명시된 실제 수행 업무를 종합해
   도출하세요. 직무명이나 과제명을
   그대로 나열하지 말고, "실제로 무엇을 했는지/하고 있는지"가 드러나는 구체적
   행위 중심 표현으로 작성하세요 (예: "로봇 SLAM 알고리즘 설계 및 검증",
   "센서 캘리브레이션 파이프라인 구축", "신소재 내구성 평가 실험 설계"). 여러
   과제·직무에 걸쳐 반복되는 역할은 하나로 통합해서 쓰세요. 3~6개를
   권장하되, 근거가 그보다 적으면 억지로 채우지 마세요.
5. domain_knowledge_skill(전문지식 및 역량)은 [학력](전공), [핵심기술]/
   [보유기술](분야·등급·Lv·보유율), [논문]/[특허]를 근거로 이 연구원이 보유한
   전문지식·기술 역량을 도출하세요. 개발 언어/프레임워크/장비 등 실무적
   하드 스킬과, 이론적 배경/산업 표준 등 학술적 지식을 따로 구분하지 말고
   구체적인 항목으로 함께 나열하세요 (예: "PyTorch 기반 강화학습 모델 개발
   역량", "칼만 필터 기반 센서 융합 이론", "ISO 26262 기능안전 표준 이해").
   3~6개를 권장하되, 근거가 그보다 적으면 억지로 채우지 마세요.
6. key_responsibilities와 domain_knowledge_skill은 관점이 다릅니다 —
   전자는 "실제 수행 업무(무엇을 했는가)", 후자는 "보유 지식·역량(무엇을
   아는가/할 수 있는가)"입니다. 같은 내용을 두 필드에 중복해서 넣지 마세요.
7. 반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.

# Output Format (JSON)
{
  "strength_fields": ["강점 분야1", "강점 분야2"],
  "strength_keywords": ["키워드1", "키워드2", "키워드3"],
  "key_responsibilities": ["주요 역할/책임 1", "주요 역할/책임 2"],
  "domain_knowledge_skill": ["전문지식/역량 1", "전문지식/역량 2"]
}
"""

_PROFILE_LIST_FIELDS = ('strength_fields', 'strength_keywords', 'key_responsibilities', 'domain_knowledge_skill')


def _read_csv(name: str) -> pd.DataFrame:
    path = os.path.join(OUT_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    if 'researcher_id' in df.columns:
        df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def _read_json(name: str) -> list:
    path = os.path.join(OUT_DIR, f'{name}.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _job_slot_indices(columns) -> list:
    return sorted({
        int(c.rsplit('_', 1)[1]) for c in columns
        if c.startswith('job_profile_name_') and c.rsplit('_', 1)[1].isdigit()
    })


def _tech_slot_indices(columns) -> list:
    return sorted({
        int(c.rsplit('_', 1)[1]) for c in columns
        if re.match(r'^tech_\d+$', c)
    })


def _build_job_def_maps(standard_list, sait_list):
    std_map = {i.get('job_profile_standard', ''): i.get('explain_job_profile_standard', '') for i in standard_list}
    sait_map = {}
    for i in sait_list:
        key = i.get('job_profile_sait', '')
        sait_map.setdefault(key, []).append(
            (i.get('job_profile_detail_sait', ''), i.get('explain_job_profile_sait', ''))
        )
    return std_map, sait_map


def _education_text(edu_rows: pd.DataFrame) -> str:
    if edu_rows.empty:
        return '(데이터 없음)'
    lines = []
    for _, r in edu_rows.iterrows():
        degree, major = _clean(r.get('degree')), _clean(r.get('major'))
        if degree or major:
            lines.append(f'- {degree} {major}'.strip())
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _task_history_text(task_rows: pd.DataFrame, info_df: pd.DataFrame) -> str:
    if task_rows.empty:
        return '(데이터 없음)'
    info_by_name = info_df.drop_duplicates('task_name').set_index('task_name') if not info_df.empty else pd.DataFrame()
    lines = []
    for name in task_rows['task_name'].dropna().unique():
        name = _clean(name)
        if not name:
            continue
        block = [f'- 과제명: {name}']
        if not info_by_name.empty and name in info_by_name.index:
            info_row = info_by_name.loc[name]
            for label, col in (
                ('수행목적', 'task_goal'), ('가치', 'task_value'), ('확보전략', 'task_howtoget'),
                ('예상문제', 'task_expectissue'), ('활용계획', 'task_Activityplan'), ('향후활용계획', 'task_futureusage'),
            ):
                val = _clean(info_row.get(col, ''))
                if val:
                    block.append(f'  {label}: {val}')
        lines.append('\n'.join(block))
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _project_role_text(role_rows: pd.DataFrame) -> str:
    """project_personnel.csv(process_project_expertise.py가 과제 문서에서 뽑아
    researcher_id로 매핑해 둔 담당 업무)에서 이 연구원 몫만 추려 텍스트로
    구성. 같은 과제에 여러 행이 남아 있으면(문서 개정 등) 전부 보여준다."""
    if role_rows.empty:
        return '(데이터 없음)'
    lines = []
    for _, r in role_rows.iterrows():
        project_name = _clean(r.get('project_name'))
        role = _clean(r.get('role_description'))
        if not (project_name or role):
            continue
        lines.append(f'- [{project_name}] {role or "(담당 업무 확인 불가)"}')
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _job_history_text(job_row: pd.Series, std_map: dict, sait_map: dict) -> str:
    if job_row is None:
        return '(데이터 없음)'
    slot_idxs = _job_slot_indices(job_row.index)
    lines = []
    for i in slot_idxs:
        name = _clean(job_row.get(f'job_profile_name_{i}', ''))
        if not name:
            continue
        start = _clean(job_row.get(f'job_start_date_{i}', ''))
        end = _clean(job_row.get(f'job_end_date_{i}', '')) or '진행중'
        block = [f'- {name} ({start}~{end})']
        if name in std_map and std_map[name]:
            block.append(f'  표준 직무 정의: {std_map[name]}')
        if name in sait_map:
            for detail, explain in sait_map[name]:
                if detail or explain:
                    block.append(f'  세부직무({detail}): {explain}')
        lines.append('\n'.join(block))
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _core_technology_text(row, grade_map: dict) -> str:
    if row is None:
        return '(데이터 없음)'
    field, name, grade = _clean(row.get('tech_field')), _clean(row.get('tech_name')), _clean(row.get('tech_grade'))
    if not (field or name):
        return '(데이터 없음)'
    line = f'- 분야: {field}, 기술명: {name}, 등급: {grade or "-"}'
    if grade and grade in grade_map:
        line += f'\n  등급 개요: {grade_map[grade]}'
    return line


def _tech_ownership_text(row, lv_map: dict) -> str:
    if row is None:
        return '(데이터 없음)'
    slot_idxs = _tech_slot_indices(row.index)
    lines = []
    for i in slot_idxs:
        tech = _clean(row.get(f'tech_{i}', ''))
        if not tech:
            continue
        lv = _clean(row.get(f'lv_{i}', ''))
        portion = _clean(row.get(f'portion_{i}', ''))
        line = f'- {tech} (Lv {lv or "-"}, 보유율 {portion or "-"}%)'
        if lv and lv in lv_map:
            line += f'\n  Lv 개요: {lv_map[lv]}'
        lines.append(line)
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _publications_text(pub_rows: pd.DataFrame, journal_authority: dict) -> str:
    if pub_rows.empty:
        return '(데이터 없음)'
    lines = []
    for _, r in pub_rows.iterrows():
        title = _clean(r.get('title'))
        if not title:
            continue
        journal = _clean(r.get('journal'))
        year = _clean(r.get('pub_year'))
        author_type = _clean(r.get('author_type'))
        is_corr = str(r.get('is_corresponding', '')).strip().lower() in ('true', 'o', 'y', '1')
        line = f'- {title} ({year}, {journal or "-"}), 저자유형: {author_type or "-"}, 교신저자: {"O" if is_corr else "X"}'
        authority = journal_authority.get(journal, '')
        if authority:
            line += f'\n  저널 권위도: {authority}'
        lines.append(line)
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _patents_text(pat_rows: pd.DataFrame) -> str:
    if pat_rows.empty:
        return '(데이터 없음)'
    lines = []
    for _, r in pat_rows.iterrows():
        title = _clean(r.get('title')) or _clean(r.get('title_ko'))
        if not title:
            continue
        grade = _clean(r.get('patent_grade'))
        grade_a = _clean(r.get('patent_grade_a_sub'))
        is_lead = str(r.get('is_lead_inventor', '')).strip().upper() == 'Y'
        grade_disp = f'{grade}({grade_a})' if grade and grade_a and grade_a != '없음' else (grade or '-')
        line = f'- {title} (등급 {grade_disp}, {"대표발명자" if is_lead else "참여발명자"})'
        if grade_a == 'A1':
            line += '\n  A1은 그중 특히 우수하여 경영효과 기여가 예상되는 전략출원 특허임'
        lines.append(line)
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _work_objective_text(row) -> str:
    if row is None:
        return '(데이터 없음)'
    lines = []
    for year, col in (('2024', 'work_objective24'), ('2025', 'work_objective25'), ('2026', 'work_objective26')):
        val = _clean(row.get(col, ''))
        if val:
            lines.append(f'[{year}년]\n{val}')
    return '\n'.join(lines) if lines else '(데이터 없음)'


def _build_prompt(edu_text, task_text, role_text, job_text, core_text, tech_text, pub_text, pat_text, obj_text) -> str:
    return f"""아래는 한 연구원의 이력 데이터입니다. 개인 식별 정보(이름/사번 등)는 제외되어 있습니다.

[학력]
{edu_text}

[과제 수행 이력]
{task_text}

[과제 내 담당 업무 (과제 문서에 실제로 기록된 내용 — 있으면 가장 신뢰도 높은 근거)]
{role_text}

[직무 이력]
{job_text}

[핵심기술]
{core_text}

[보유기술]
{tech_text}

[논문]
{pub_text}

[특허]
{pat_text}

[업무목표 (24~26년, 참고용 — 작성 분량은 개인차가 크므로 보조 자료로만 활용)]
{obj_text}
"""


def _analyze_researcher(prompt: str) -> dict | None:
    # 추론형 모델의 사고 과정 토큰 소모를 감안해 여유 있게 잡는다(finish_reason=length 방지).
    # 입력(과제/논문/특허 이력 등)이 사람마다 길이 편차가 커서 사고 과정도 그만큼
    # 길어질 수 있어, 기본 배수(LLM2_MAX_TOKENS_MULTIPLIER)만으로 부족한 경우가
    # 있었다 — 4000 -> 6000으로 상향.
    raw = call_llm(prompt, _SYSTEM_PROMPT, temperature=0.2, max_tokens=6000)
    if not raw:
        return None
    try:
        result = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return None

    out = {}
    for key in _PROFILE_LIST_FIELDS:
        if isinstance(result.get(key), list):
            values = [str(v).strip() for v in result[key] if str(v).strip()]
            if values:
                out[key] = values

    return out if out else None


def _list_block_html(title: str, items: list) -> str:
    """key_responsibilities/domain_knowledge_skill 중 하나를 kv-block 스타일의
    불릿 목록으로 렌더링. LLM이 근거 없다고 판단해 빈 배열로 남긴 항목은
    블록 자체를 표시하지 않는다."""
    if not items:
        return ''
    lis = ''.join(f'<li>{html.escape(v)}</li>' for v in items)
    return f'<div class="kv-block"><div class="kv-title">{title}</div><ul class="kv-list">{lis}</ul></div>'


def researcher_card_html(item: dict, name_map: dict, anchor: str = '', include_links: bool = True) -> str:
    """연구원 한 명의 보유 전문성 카드(강점 칩 + 주요 역할·책임/전문지식 및
    역량). build_html()의 조직도 카드 나열뿐 아니라, 개별 연구원 메일 발송
    (services/similarity_map.py의 build_researcher_mail_html())에서도
    그대로 재사용한다 — anchor가 빈 문자열이면(메일 등 fragment 링크가
    필요 없는 컨텍스트) id 속성 없이 렌더링. include_links=False면
    프로필/메일 링크(target="_top" 상대경로라 앱 밖 메일 본문에서는 깨짐 —
    사용자 확인)를 아예 뺀다."""
    rid = item.get('researcher_id', '')
    name = name_map.get(rid, '')

    fields = item.get('strength_fields') or []
    keywords = item.get('strength_keywords') or []
    chip_row = mmd.strength_section_html(fields, keywords)

    kv_blocks = (
        _list_block_html('주요 역할·책임', item.get('key_responsibilities') or [])
        + _list_block_html('전문지식 및 역량', item.get('domain_knowledge_skill') or [])
    )
    body_html = f'<div class="kv-grid">{kv_blocks}</div>' if kv_blocks else '<p class="empty">세부 항목 데이터 없음</p>'

    icons_html = (
        f'<div class="card-icons">{mmd.profile_link_html(rid)}{mmd.mail_link_html(rid)}</div>'
        if include_links else ''
    )
    id_attr = f' id="{anchor}"' if anchor else ''
    return f'''<div class="card"{id_attr}>
  <div class="card-top"><h3>{html.escape(rid)} {html.escape(name)}</h3>
    {icons_html}
  </div>
  {chip_row}
  {body_html}
</div>'''


def build_html(results: list, researchers_df: pd.DataFrame) -> str:
    """연구원 보유 전문성 분석.json → 사람이 보는 콘솔형 HTML 리포트.

    researchers.csv의 department(현소속부서명) → '플랫폼/팀', org_code(비공식
    소속부서명) → '과제/파트'로 라벨링해 좌측 사이드바·본문 모두 2단계로
    그룹핑해 보여준다(JSON 구조 자체는 flat list 그대로 유지)."""
    name_map, dept_map, org_map = {}, {}, {}
    if not researchers_df.empty:
        indexed = researchers_df.set_index('researcher_id')
        name_map = indexed['name'].to_dict()
        dept_map = indexed['department'].to_dict()
        org_map = indexed['org_code'].to_dict()

    anchor_of = {item.get('researcher_id', ''): f'r-{item.get("researcher_id", "")}' for item in results}

    # 조직도(team_refer.csv)가 있으면 트리로, 없으면 기존 부서 평면 목록으로 폴백.
    analyzed_rids_by_org: dict = {}
    for it in results:
        rid = it.get('researcher_id', '')
        analyzed_rids_by_org.setdefault(org_map.get(rid, ''), []).append(rid)

    org_tree = mmd.build_org_tree(mmd.read_team_refer(OUT_DIR))
    if org_tree:
        def _leaf_researchers(node):
            items = [
                (f'#{anchor_of[rid]}', name_map.get(rid, rid), None)
                for rid in analyzed_rids_by_org.get(node.get('org_name_wd', ''), [])
            ]
            return mmd.nav_items_html(items)

        nav_groups = [mmd.org_tree_html(org_tree, _leaf_researchers)]
    else:
        nav_groups = []
        for dept, items in mmd.group_ordered(results, lambda it: dept_map.get(it.get('researcher_id', ''), '')):
            entries = ''.join(
                f'<a class="nav-item" href="#{anchor_of[it.get("researcher_id", "")]}">'
                f'<span>{html.escape(name_map.get(it.get("researcher_id", ""), it.get("researcher_id", "")))}</span></a>'
                for it in items
            )
            nav_groups.append(f'<div class="nav-group"><div class="nav-group-label">{html.escape(dept)}</div>{entries}</div>')

    # 사용자 요청으로 요약 카드를 "마지막 갱신" 하나만 남긴다(긴 직사각형으로
    # 표시 — .stat-row가 grid-template-columns: repeat(auto-fit, minmax(150px,1fr))
    # 라 카드가 1개면 자동으로 전체 폭을 채운다, CSS 변경 불필요).
    stats = mmd.stat_row_html([mmd.generated_at_stat()])

    sections = []
    for dept, dept_items in mmd.group_ordered(results, lambda it: dept_map.get(it.get('researcher_id', ''), '')):
        sections.append(f'<div class="dept-heading">{html.escape(dept)}</div>')
        for org, org_items in mmd.group_ordered(dept_items, lambda it: org_map.get(it.get('researcher_id', ''), '')):
            if org and org != '미분류':
                sections.append(f'<div class="org-heading">{html.escape(org)}</div>')
            for item in org_items:
                rid = item.get('researcher_id', '')
                sections.append(researcher_card_html(item, name_map, anchor_of[rid]))

    sidebar = (
        '<h1>연구원 전문성 콘솔</h1>'
        '<p class="tagline">학력·과제이력·직무이력·기술·논문·특허 종합 분석 (R&amp;D Talent Profiling Agent)</p>'
        f'{mmd.org_search_input_html()}'
        f'{"".join(nav_groups)}'
    )
    return mmd.console_page('연구원 보유 전문성 분석', sidebar, stats + ''.join(sections), detail_view=True)


def _archive_html(results: list, researchers_df: pd.DataFrame):
    """화면은 이제 이 HTML을 파일로 읽지 않고 build_html()을 그때그때 호출해
    직접 렌더링한다(pages/researcher_similarity_map.py) — data/processed에
    누구나 열어볼 수 있는 완성된 리포트 사본을 남기지 않기 위해서다. 다만
    실행 이력 아카이브(data/processed/result/, 파일 권한은 scripts/
    secure_data_permissions.sh로 잠금)에는 계속 스냅샷을 남긴다."""
    html_out = build_html(results, researchers_df)
    result_archive.archive_copy('02. 연구원분석', '연구원 보유 전문성 분석', 'html', html_out)


def render_html() -> bool:
    """이미 저장된 연구원 보유 전문성 분석.json을 읽어 아카이브용 .html 스냅샷만
    다시 만든다(LLM 재호출 없음). 새로 분석하지 않고 기존 JSON으로 스냅샷을
    남기고 싶을 때 'python pipeline/process_researcher_expertise.py --html-only'로
    실행한다 — 화면에 쓰이는 리포트는 항상 build_html()로 그때그때 렌더링되므로
    이 스냅샷을 갱신하지 않아도 화면 표시에는 영향이 없다."""
    json_path = os.path.join(OUT_DIR, '연구원 보유 전문성 분석.json')
    if not os.path.exists(json_path):
        print('[process_researcher_expertise] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(python pipeline/process_researcher_expertise.py 먼저 실행)')
        return False

    with open(json_path, encoding='utf-8') as f:
        results = json.load(f)

    researchers = _filter_eligible_researchers(_read_csv('researchers'))
    _archive_html(results, researchers)
    return True


def _filter_eligible_researchers(researchers: pd.DataFrame) -> pd.DataFrame:
    """team_refer(work_type=="R&D")에 매칭되는 org_code만, job_type='지원'
    (조직총괄/자문위원 예외)는 항상 제외해 분석 대상 연구원만 남긴다.
    process()와 render_html()이 같은 모수를 쓰도록 공유한다 — 커버리지 스탯
    (분석 완료/분석 대상)의 분모가 실행 경로에 따라 달라지면 안 되기 때문.

    예전에는 전문성 분석 부서.xlsx(process_analysis_dep.py, department 화이트
    리스트)로 분석 대상 부서를 걸렀지만, team_refer.xlsx에 조직 단위별 R&D
    여부(work_type)가 명시적으로 들어오면서 이 방식으로 완전히 대체됐다 —
    org_code(team_refer의 org_name_wd)가 매핑되지 않은 연구원은 R&D 여부를
    판단할 근거가 없어 분석 대상에서 제외된다(이전의 "매핑 실패해도 부서
    화이트리스트만 통과하면 포함"과 달리, 이제는 team_refer 매핑이 필수)."""
    team_refer_rows = mmd.read_team_refer(OUT_DIR)
    if team_refer_rows:
        rd_org_codes = {
            (r.get('org_name_wd') or '').strip() for r in team_refer_rows
            if str(r.get('work_type') or '').strip() == 'R&D'
        } - {''}
        before = len(researchers)
        researchers = researchers[researchers['org_code'].isin(rd_org_codes)]
        print(f'[process_researcher_expertise] 분석 대상 필터 적용(team_refer work_type=="R&D", '
              f'{len(rd_org_codes)}개 조직 단위): {before}명 → {len(researchers)}명')
    else:
        print('[process_researcher_expertise] team_refer 데이터 없음 — 부서 필터 없이 전체 연구원 분석 '
              '(python pipeline/process_team_refer.py로 생성 가능)')

    # 4직종(job_type)이 '지원'이면 분석 대상에서 제외한다. 단, 직무(job_function)가
    # '조직총괄' 또는 '자문위원'이면 지원 직종이어도 예외로 포함한다.
    if 'job_type' in researchers.columns:
        exclude_mask = researchers['job_type'] == '지원'
        if 'job_function' in researchers.columns:
            exclude_mask &= ~researchers['job_function'].isin(['조직총괄', '자문위원'])
        before = len(researchers)
        researchers = researchers[~exclude_mask]
        excluded = before - len(researchers)
        if excluded:
            print(f'[process_researcher_expertise] 직종 필터 적용(job_type=지원 제외, '
                  f'조직총괄/자문위원 예외 포함): {before}명 → {len(researchers)}명 ({excluded}명 제외)')
    return researchers


def process(refresh_journals: bool = False) -> bool:
    reset_truncation_count()
    researchers = _read_csv('researchers')
    if researchers.empty:
        print('[process_researcher_expertise] researchers.csv 없음 — 종료')
        return False

    researchers = _filter_eligible_researchers(researchers)
    if researchers.empty:
        print('[process_researcher_expertise] 필터 적용 후 대상 연구원 없음 — 종료')
        return False

    education = _read_csv('education')
    tasks = _read_csv('tasks')
    tasks_info = _read_csv('tasks_information')
    project_personnel = _read_csv('project_personnel')
    job_profile = _read_csv('job_profile')
    core_tech = _read_csv('core_technology')
    tech_ownership = _read_csv('tech_ownership')
    publications = _read_csv('publications')
    patents = _read_csv('patents')
    work_objective = _read_csv('work_objective')

    grade_info = _read_json('core_technology_grade_info')
    lv_info = _read_json('tech_ownership_lv_info')
    std_defs = _read_json('job_profile_info_standard')
    sait_defs = _read_json('job_profile_info_sait')

    grade_map = {i['grade']: i['definition'] for i in grade_info}
    lv_map = {str(i['lv']): i['definition'] for i in lv_info}
    std_map, sait_map = _build_job_def_maps(std_defs, sait_defs)

    journal_cache = journal_authority.load_cache()
    journal_cache = journal_authority.update_authority(
        journal_authority.unique_journals(publications), journal_cache, force=refresh_journals)

    rids = researchers['researcher_id'].unique()
    total = len(rids)
    results = []
    success_count = 0
    fail_count = 0
    skip_count = 0
    completed = 0

    def _progress_checkpoint():
        if completed % 10 == 0 or completed == total:
            print(f'    (완료인원 {completed}명/전체 {total}명, {success_count}명 성공, '
                  f'{fail_count}명 실패, {skip_count}명 건너뜀)')

    # 1단계: 연구원별 프롬프트 구성(로컬 데이터 처리, LLM 호출 없음) + 데이터
    # 없는 연구원은 이 단계에서 바로 건너뜀 처리한다.
    prepared = []  # [(rid, prompt), ...] — LLM 분석이 실제로 필요한 연구원만
    for rid in rids:
        edu_text = _education_text(education[education['researcher_id'] == rid]) if not education.empty else '(데이터 없음)'
        task_text = _task_history_text(
            tasks[tasks['researcher_id'] == rid] if not tasks.empty else pd.DataFrame(), tasks_info
        )
        role_text = _project_role_text(
            project_personnel[project_personnel['researcher_id'] == rid]
            if not project_personnel.empty else pd.DataFrame()
        )
        job_row = None
        if not job_profile.empty:
            rows = job_profile[job_profile['researcher_id'] == rid]
            job_row = rows.iloc[0] if not rows.empty else None
        job_text = _job_history_text(job_row, std_map, sait_map)

        core_row = None
        if not core_tech.empty:
            rows = core_tech[core_tech['researcher_id'] == rid]
            core_row = rows.iloc[0] if not rows.empty else None
        core_text = _core_technology_text(core_row, grade_map)

        tech_row = None
        if not tech_ownership.empty:
            rows = tech_ownership[tech_ownership['researcher_id'] == rid]
            tech_row = rows.iloc[0] if not rows.empty else None
        tech_text = _tech_ownership_text(tech_row, lv_map)

        pub_rows = publications[publications['researcher_id'] == rid] if not publications.empty else pd.DataFrame()
        pub_text = _publications_text(pub_rows, journal_cache)

        pat_rows = patents[patents['researcher_id'] == rid] if not patents.empty else pd.DataFrame()
        pat_text = _patents_text(pat_rows)

        obj_row = None
        if not work_objective.empty:
            rows = work_objective[work_objective['researcher_id'] == rid]
            obj_row = rows.iloc[0] if not rows.empty else None
        obj_text = _work_objective_text(obj_row)

        # 판단 근거가 될 데이터가 전혀 없으면 LLM 호출 자체를 건너뛴다.
        if all(t == '(데이터 없음)' for t in
               (edu_text, task_text, role_text, job_text, core_text, tech_text, pub_text, pat_text, obj_text)):
            print(f'    [{rid}] 데이터 없음 — 건너뜀')
            skip_count += 1
            completed += 1
            _progress_checkpoint()
            continue

        prompt = _build_prompt(edu_text, task_text, role_text, job_text, core_text, tech_text, pub_text, pat_text, obj_text)
        prepared.append((rid, prompt))

    # 2단계: 실제 LLM 분석은 동시 호출 허용치만큼 동시에 실행한다.
    # 개별 연구원 분석 중 예기치 못한 예외가 나도(run_concurrent가 잡아 반환)
    # 다른 연구원 분석은 계속 진행하고, 실패한 연구원만 에러와 함께 로그로
    # 남겨 추후 원인 파악·동시성 조정에 활용할 수 있게 한다.
    if prepared:
        workers = max_concurrency()
        print(f'[process_researcher_expertise] 연구원 {len(prepared)}명 LLM 분석 시작 '
              f'(전체 {total}명 중 {skip_count}명 건너뜀, 동시 {workers}건)...')

        # run_concurrent()는 제출된 작업을 전부 마칠 때까지 반환하지 않으므로,
        # 실시간 진행 상황(완료/성공/실패 수 갱신 + 체크포인트 출력)은 반드시
        # on_complete 콜백에서 처리해야 한다 — 반환값을 받은 뒤 순회하며
        # 출력하면 전체가 다 끝난 뒤에야 로그가 한꺼번에 찍힌다.
        def _on_analysis_complete(i, analysis, error):
            nonlocal completed, success_count, fail_count
            rid = prepared[i][0]
            completed += 1
            if error is not None:
                print(f'    [{rid}] 분석 오류: {type(error).__name__}: {error}')
                fail_count += 1
            elif analysis is None:
                print(f'    [{rid}] 분석 실패')
                fail_count += 1
            else:
                print(f'    [{rid}] 분석 완료')
                success_count += 1
            _progress_checkpoint()

        tasks_ = [(lambda p=prompt: _analyze_researcher(p)) for _, prompt in prepared]
        task_results = run_concurrent(tasks_, max_workers=workers, on_complete=_on_analysis_complete)

        # 위 콜백에서 이미 분류/출력을 끝냈으므로, 여기서는 결과만 원래 순서(rids
        # 순서)대로 다시 모은다(완료 순서는 스레드 스케줄링에 따라 달라지므로).
        for (rid, _), (analysis, _error) in zip(prepared, task_results):
            if analysis is not None:
                results.append({'researcher_id': rid, **analysis})

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, '연구원 보유 전문성 분석.json')
    json_text = json.dumps(results, ensure_ascii=False, indent=2)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json_text)

    print(f'[OK]   연구원 보유 전문성 분석.json 저장 ({len(results)}명)')
    truncation_count = get_truncation_count()
    if truncation_count:
        print(f'[알림] LLM 응답 content가 비어(주로 finish_reason=length) 대체 처리된 '
              f'횟수: {truncation_count}회 — 잦으면 max_tokens를 더 늘려야 할 수 있습니다.')
    result_archive.archive_copy('02. 연구원분석', '연구원 보유 전문성 분석', 'json', json_text)

    _archive_html(results, researchers)
    return True


if __name__ == '__main__':
    if '--html-only' in sys.argv:
        render_html()
    else:
        process(refresh_journals='--refresh-journals' in sys.argv)
