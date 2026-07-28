"""
연구원 보유 전문성 분석 모듈 (사내 LLM)

한 연구원의 학력/전공, 과제 이력, 직무 이력, 핵심기술, 보유기술, 논문, 특허
데이터를 모두 모아 "R&D Talent Profiling Agent" 역할의 사내 LLM에게 분석을
맡기고, 결과를 구조화된 JSON과 사람이 보는 HTML 리포트로 저장한다.

Source:
  data/processed/researchers.csv
  data/processed/education.csv                      (degree, major)
  data/processed/tasks.csv + tasks_information.csv   (task_name 기준 조인)
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
from llm_client import call_llm, extract_json, max_concurrency, run_concurrent  # noqa: E402
import journal_authority  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402
import result_archive  # noqa: E402

_SYSTEM_PROMPT = """# Role
당신은 R&D 인재 전문성 분석 전문가인 "R&D Talent Profiling Agent"입니다.
입력된 한 연구원의 학력, 과제 수행 이력, 직무 이력, 보유 기술/등급, 논문, 특허
데이터를 정밀 분석하여, 이 연구원이 실제로 보유한 전문성을 오직 팩트(Fact)
기반으로 도출하는 역할을 수행합니다.

# Goal
HR 담당자와 R&D 부서장이 이 연구원의 전문성을 객관적으로 파악하고, 향후 프로젝트
배치·인력 매칭·채용 판단에 활용할 수 있도록 구조화된 전문성 프로필을 제공합니다.

# Guidelines & Constraints
1. 철저한 팩트 기반: 입력 데이터에 명시적으로 드러나지 않는 기술/지식을 임의로
   추정하여 확정하지 마세요. 데이터로부터 합리적으로 추론 가능한 내용은
   근거와 함께 서술할 수 있습니다.
2. 판단 근거가 있지만 확신이 부족하면 해당 값에 "확인 불가"라고 쓰세요.
3. 판단 근거가 되는 데이터가 전혀 없는 항목은 그 키 자체를 결과 JSON에서
   생략하세요(빈 문자열이나 지어낸 내용을 넣지 마세요).
4. [업무목표] 항목은 연구원마다 작성 성실도·분량 차이가 커서, 내용이 소략하다는
   이유만으로 전문성을 낮게 판단하지 마세요. 다른 항목에 이미 충분한 근거가
   있다면 업무목표는 보조 참고 자료로만 활용하세요.
5. 반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.

# Output Format (JSON)
{
  "strength_fields": ["강점 분야1", "강점 분야2"],
  "strength_keywords": ["키워드1", "키워드2", "키워드3"],
  "hard_skills": {
    "languages_frameworks": "개발 언어 및 프레임워크 (예: C/C++, Python, PyTorch, ROS2 등) 또는 '확인 불가'",
    "hardware_equipment_control": "하드웨어 및 장비 제어 (예: MCU, LiDAR 센서 제어, 오실로스코프 활용 등) 또는 '확인 불가'",
    "analysis_simulation_tools": "분석 및 시뮬레이션 툴 (예: MATLAB, ANSYS, CAD 등) 또는 '확인 불가'"
  },
  "domain_knowledge": {
    "academic_theoretical_background": "학술적/이론적 배경 (예: 선형대수학, 칼만 필터 이론, 신호처리 이론 등) 또는 '확인 불가'",
    "industry_standards": "산업/기술 표준 및 규격 (예: ISO 26262, ISO 13485 등) 또는 '확인 불가'",
    "patent_trend_understanding": "해당 분야의 선행 특허 및 최신 논문 동향 분석력 또는 '확인 불가'"
  }
}
※ hard_skills/domain_knowledge의 하위 항목은 판단 근거가 전혀 없으면 키를 생략하세요.
"""

_HARD_SKILL_KEYS = ['languages_frameworks', 'hardware_equipment_control', 'analysis_simulation_tools']
_DOMAIN_KEYS = ['academic_theoretical_background', 'industry_standards', 'patent_trend_understanding']

# HTML 리포트에서 hard_skills/domain_knowledge 하위 키를 표시할 때 쓰는 한글 라벨
_HARD_SKILL_LABELS = [
    ('languages_frameworks', '개발 언어 및 프레임워크'),
    ('hardware_equipment_control', '하드웨어 및 장비 제어'),
    ('analysis_simulation_tools', '분석 및 시뮬레이션 툴'),
]
_DOMAIN_LABELS = [
    ('academic_theoretical_background', '학술적/이론적 배경'),
    ('industry_standards', '산업/기술 표준 및 규격'),
    ('patent_trend_understanding', '특허 및 트렌드 이해도'),
]


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


def _build_prompt(edu_text, task_text, job_text, core_text, tech_text, pub_text, pat_text, obj_text) -> str:
    return f"""아래는 한 연구원의 이력 데이터입니다. 개인 식별 정보(이름/사번 등)는 제외되어 있습니다.

[학력]
{edu_text}

[과제 수행 이력]
{task_text}

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
    raw = call_llm(prompt, _SYSTEM_PROMPT, temperature=0.2, max_tokens=4000)
    if not raw:
        return None
    try:
        result = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return None

    out = {}
    if isinstance(result.get('strength_fields'), list):
        out['strength_fields'] = result['strength_fields']
    if isinstance(result.get('strength_keywords'), list):
        out['strength_keywords'] = result['strength_keywords']

    hard_skills = result.get('hard_skills', {})
    if isinstance(hard_skills, dict):
        filtered = {k: v for k, v in hard_skills.items() if k in _HARD_SKILL_KEYS and v}
        if filtered:
            out['hard_skills'] = filtered

    domain_knowledge = result.get('domain_knowledge', {})
    if isinstance(domain_knowledge, dict):
        filtered = {k: v for k, v in domain_knowledge.items() if k in _DOMAIN_KEYS and v}
        if filtered:
            out['domain_knowledge'] = filtered

    return out if out else None


def _kv_block_html(title: str, data: dict, labels: list) -> str:
    """hard_skills/domain_knowledge 중 하나를 kv-block으로 렌더링. LLM이 근거
    없다고 판단해 아예 생략한 키는 항목 자체를 표시하지 않는다."""
    items = [f'<dt>{label}</dt><dd>{html.escape(data[key])}</dd>' for key, label in labels if data.get(key)]
    if not items:
        return ''
    return f'<div class="kv-block"><div class="kv-title">{title}</div><dl class="kv">{"".join(items)}</dl></div>'


def _researcher_card_html(item: dict, name_map: dict, anchor: str) -> str:
    rid = item.get('researcher_id', '')
    name = name_map.get(rid, '')

    fields = item.get('strength_fields') or []
    keywords = item.get('strength_keywords') or []
    if fields or keywords:
        chip_row = (
            ''.join(f'<span class="chip">{html.escape(f)}</span>' for f in fields)
            + ''.join(f'<span class="chip kw">{html.escape(k)}</span>' for k in keywords)
        )
        chip_row = f'<div class="chip-row">{chip_row}</div>'
    else:
        chip_row = '<p class="empty">강점 분야/키워드 데이터 없음</p>'

    kv_blocks = (
        _kv_block_html('Hard Skills', item.get('hard_skills') or {}, _HARD_SKILL_LABELS)
        + _kv_block_html('Domain Knowledge', item.get('domain_knowledge') or {}, _DOMAIN_LABELS)
    )
    body_html = f'<div class="kv-grid">{kv_blocks}</div>' if kv_blocks else '<p class="empty">세부 항목 데이터 없음</p>'

    return f'''<div class="card" id="{anchor}">
  <div class="card-top"><h3>{html.escape(rid)} {html.escape(name)}</h3>{mmd.map_link_html(rid)}</div>
  {chip_row}
  {body_html}
</div>'''


def _build_html(results: list, researchers_df: pd.DataFrame) -> str:
    """연구원 보유 전문성 분석.json → 사람이 보는 콘솔형 HTML 리포트.

    researchers.csv의 department(현소속부서명) → '플랫폼/팀', org_code(비공식
    소속부서명) → '과제/파트'로 라벨링해 좌측 사이드바·본문 모두 2단계로
    그룹핑해 보여준다(JSON 구조 자체는 그대로 flat list — process_project_researcher_fit.py
    등이 이 JSON을 그대로 읽으므로 하위 호환 유지)."""
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
                for rid in analyzed_rids_by_org.get(node.get('project_name', ''), [])
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

    total = len(results)
    hard_count = sum(1 for it in results if it.get('hard_skills'))
    domain_count = sum(1 for it in results if it.get('domain_knowledge'))
    stats = mmd.stat_row_html([
        (total, '분석 대상 연구원'),
        (hard_count, 'Hard Skills 데이터 보유'),
        (domain_count, 'Domain Knowledge 데이터 보유'),
    ])

    sections = []
    for dept, dept_items in mmd.group_ordered(results, lambda it: dept_map.get(it.get('researcher_id', ''), '')):
        sections.append(f'<div class="dept-heading">{html.escape(dept)}</div>')
        for org, org_items in mmd.group_ordered(dept_items, lambda it: org_map.get(it.get('researcher_id', ''), '')):
            if org and org != '미분류':
                sections.append(f'<div class="org-heading">{html.escape(org)}</div>')
            for item in org_items:
                rid = item.get('researcher_id', '')
                sections.append(_researcher_card_html(item, name_map, anchor_of[rid]))

    sidebar = (
        '<h1>연구원 전문성 콘솔</h1>'
        '<p class="tagline">학력·과제이력·직무이력·기술·논문·특허 종합 분석 (R&amp;D Talent Profiling Agent)</p>'
        f'{"".join(nav_groups)}'
    )
    return mmd.console_page('연구원 보유 전문성 분석', sidebar, stats + ''.join(sections))


def _write_html(results: list, researchers_df: pd.DataFrame):
    html_out = _build_html(results, researchers_df)
    html_path = os.path.join(OUT_DIR, '연구원 보유 전문성 분석.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f'[OK]   연구원 보유 전문성 분석.html 저장 ({len(results)}명)')
    result_archive.archive_copy('02. 연구원분석', '연구원 보유 전문성 분석', 'html', html_out)


def render_html() -> bool:
    """이미 저장된 연구원 보유 전문성 분석.json을 읽어 .html만 다시 만든다(LLM
    재호출 없음). 새로 분석하지 않고 기존 JSON을 리포트로 보고 싶을 때
    'python pipeline/process_researcher_expertise.py --html-only'로 실행한다."""
    json_path = os.path.join(OUT_DIR, '연구원 보유 전문성 분석.json')
    if not os.path.exists(json_path):
        print('[process_researcher_expertise] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(python pipeline/process_researcher_expertise.py 먼저 실행)')
        return False

    with open(json_path, encoding='utf-8') as f:
        results = json.load(f)

    researchers = _read_csv('researchers')
    _write_html(results, researchers)
    return True


def process(refresh_journals: bool = False) -> bool:
    researchers = _read_csv('researchers')
    if researchers.empty:
        print('[process_researcher_expertise] researchers.csv 없음 — 종료')
        return False

    analysis_dep = _read_csv('analysis_dep')
    if not analysis_dep.empty and 'department' in analysis_dep.columns:
        allowed_depts = set(analysis_dep['department'])
        before = len(researchers)
        researchers = researchers[researchers['department'].isin(allowed_depts)]
        print(f'[process_researcher_expertise] 분석 대상 부서 필터 적용(analysis_dep.csv, '
              f'{len(allowed_depts)}개 부서): {before}명 → {len(researchers)}명')
        if researchers.empty:
            print('[process_researcher_expertise] 필터 적용 후 대상 연구원 없음 — 종료')
            return False
    else:
        print('[process_researcher_expertise] analysis_dep.csv 없음 — 부서 필터 없이 전체 연구원 분석 '
              '(python pipeline/process_analysis_dep.py로 생성 가능)')

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
        if researchers.empty:
            print('[process_researcher_expertise] 필터 적용 후 대상 연구원 없음 — 종료')
            return False

    education = _read_csv('education')
    tasks = _read_csv('tasks')
    tasks_info = _read_csv('tasks_information')
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
               (edu_text, task_text, job_text, core_text, tech_text, pub_text, pat_text, obj_text)):
            print(f'    [{rid}] 데이터 없음 — 건너뜀')
            skip_count += 1
            completed += 1
            _progress_checkpoint()
            continue

        prompt = _build_prompt(edu_text, task_text, job_text, core_text, tech_text, pub_text, pat_text, obj_text)
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
    result_archive.archive_copy('02. 연구원분석', '연구원 보유 전문성 분석', 'json', json_text)

    _write_html(results, researchers)
    return True


if __name__ == '__main__':
    if '--html-only' in sys.argv:
        render_html()
    else:
        process(refresh_journals='--refresh-journals' in sys.argv)
