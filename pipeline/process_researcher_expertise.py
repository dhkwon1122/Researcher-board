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
  data/processed/publications.csv                    (저널 권위도는 LLM으로 별도 조회/캐시)
  data/processed/patents.csv
  data/processed/work_objective.csv                  (24~26년 업무목표, process_work_objective.py가 생성)

저널 권위도 캐시(journal_authority[.<profile>].json)는 평가 값이 실제로 채워진
저널은 건너뛰고, 값이 비어 있는(신규거나 이전 조회 실패로 남은) 저널만 매번
재조회한다. 캐시와 무관하게 전체 저널을 다시 확인하려면:
  python pipeline/process_researcher_expertise.py --refresh-journals

Output:
  data/processed/연구원 보유 전문성 분석[.<profile>].json
  data/processed/연구원 보유 전문성 분석[.<profile>].html  (연구원별 카드 리포트)
  data/processed/journal_authority[.<profile>].json  (저널명별 권위도 평가 캐시 — 누적 재사용)

※ 프롬프트에는 researcher_id/이름 등 개인 식별 정보를 절대 포함하지 않는다.
  이력 내용(과제/직무/기술/논문/특허)만 사내 LLM에 전달하고, 결과는 호출부에서
  researcher_id에 매핑한다.

두 사내 LLM 비교(profile 인자):
  python pipeline/process_researcher_expertise.py                    # 기존 LLM(profile='default')
  python pipeline/process_researcher_expertise.py --profile thinkingcap  # 2번째 LLM

이미 저장된 JSON을 LLM 재호출 없이 HTML로만 다시 만들기:
  python pipeline/process_researcher_expertise.py --html-only
  python pipeline/process_researcher_expertise.py --html-only --profile thinkingcap
  ※ default/thinkingcap 모두 _build_html() 하나로만 렌더링하므로 두 산출물의
    포맷은 항상 동일하다.

사용법:
  python pipeline/process_researcher_expertise.py [--profile thinkingcap] [--html-only] [--refresh-journals]
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
from llm_client import call_llm, extract_json  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402

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

_JOURNAL_SYSTEM_PROMPT = '당신은 학술 저널/학회의 권위도를 평가하는 전문가입니다. 요청한 JSON 형식만 출력하세요.'

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


def _unique_journals(pub_df: pd.DataFrame) -> list:
    if pub_df.empty or 'journal' not in pub_df.columns:
        return []
    return sorted({_clean(j) for j in pub_df['journal'] if _clean(j)})


def _journal_cache_path(profile: str) -> str:
    suffix = mmd.profile_suffix(profile)
    return os.path.join(OUT_DIR, f'journal_authority{suffix}.json')


def _load_journal_cache(profile: str = 'default') -> dict:
    path = _journal_cache_path(profile)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _save_journal_cache(cache: dict, profile: str = 'default'):
    with open(_journal_cache_path(profile), 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _update_journal_authority(journals: list, cache: dict, profile: str = 'default', force: bool = False) -> dict:
    """캐시에 실제 평가 값이 채워진 저널은 건너뛰고, 값이 비어 있는 저널(신규거나
    이전 조회가 실패해 빈 문자열로 남은 것)만 사내 LLM으로 재조회한다(누적 재사용,
    profile별 분리). 단순히 캐시에 키가 있는지가 아니라 값이 실제로 있는지로
    판단해야, 실패했던 저널이 캐시에 빈 값으로 영구히 박제되지 않는다.
    force=True(--refresh-journals)면 캐시 값과 무관하게 전달된 저널 전체를
    다시 조회한다."""
    targets = journals if force else [j for j in journals if not cache.get(j)]
    if not targets:
        return cache
    label = '전체 재조회' if force else '신규/미확인'
    print(f'[process_researcher_expertise] 저널 권위도 조회 중 ({label} {len(targets)}건, profile={profile})...')
    for j in targets:
        prompt = (
            f'학술지/저널명: {j}\n'
            f'이 저널의 SCI/SCIE 여부, 대략적인 impact factor 수준, 해당 분야에서의 '
            f'권위·명성 수준을 1~2문장으로 평가해 주세요. 확실하지 않으면 "확인 불가"라고 답하세요.\n'
            f'다음 JSON 형식으로만 출력하세요: {{"authority": "평가 내용"}}'
        )
        raw = call_llm(prompt, _JOURNAL_SYSTEM_PROMPT, max_tokens=300, profile=profile)
        authority = ''
        if raw:
            try:
                authority = json.loads(extract_json(raw)).get('authority', '')
            except json.JSONDecodeError:
                authority = ''
        cache[j] = authority
        print(f'    [{"OK" if authority else "실패"}] {j}')
    _save_journal_cache(cache, profile)
    return cache


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


def _analyze_researcher(prompt: str, profile: str = 'default') -> dict | None:
    raw = call_llm(prompt, _SYSTEM_PROMPT, temperature=0.2, max_tokens=2500, profile=profile)
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


def _skill_block_html(title: str, data: dict, labels: list) -> str:
    """hard_skills/domain_knowledge 중 하나를 job-field 카드 블록으로 렌더링.
    LLM이 근거 없다고 판단해 아예 생략한 키는 항목 자체를 표시하지 않는다."""
    items = [f'<li><strong>{label}:</strong> {html.escape(data[key])}</li>' for key, label in labels if data.get(key)]
    if not items:
        return ''
    return f'''<div class="job-field">
  <div class="field-label">{title}</div>
  <ul>{''.join(items)}</ul>
</div>'''


def _researcher_card_html(item: dict, name_map: dict, anchor: str) -> str:
    rid = item.get('researcher_id', '')
    name = name_map.get(rid, '')

    field_badges = ''.join(
        f'<span class="badge rounded-pill text-bg-dark me-1 mb-1">{html.escape(f)}</span>'
        for f in (item.get('strength_fields') or [])
    )
    strength_html = f'<p class="mb-2">{field_badges}</p>' if field_badges else ''
    strength_html += mmd.keyword_pills_html(item.get('strength_keywords') or [])
    if not strength_html:
        strength_html = '<p class="empty">강점 분야/키워드 데이터 없음</p>'

    body_html = (
        _skill_block_html('Hard Skills', item.get('hard_skills') or {}, _HARD_SKILL_LABELS)
        + _skill_block_html('Domain Knowledge', item.get('domain_knowledge') or {}, _DOMAIN_LABELS)
    )
    if not body_html:
        body_html = '<p class="empty">세부 항목 데이터 없음</p>'

    return f'''<section class="tech-card card" id="{anchor}">
  <div class="card-body">
    <div class="tech-header d-flex align-items-center gap-2 mb-1">
      <h2>{html.escape(rid)} {html.escape(name)}</h2>
    </div>
    <div class="tech-desc">{strength_html}</div>
    {body_html}
  </div>
</section>'''


def _build_html(results: list, profile: str, researchers_df: pd.DataFrame) -> str:
    """연구원 보유 전문성 분석[.profile].json → 사람이 보는 HTML 리포트.
    default/thinkingcap 어느 profile을 넘겨도 항상 이 한 함수로만 렌더링하므로
    두 산출물의 포맷은 항상 동일하다."""
    name_map = {}
    if not researchers_df.empty:
        name_map = researchers_df.set_index('researcher_id')['name'].to_dict()

    toc_links = []
    cards = []
    for i, item in enumerate(results, start=1):
        rid = item.get('researcher_id', '')
        anchor = f'researcher-{i}'
        label = f'{rid} {name_map.get(rid, "")}'.strip()
        toc_links.append(
            f'<a class="btn btn-sm btn-outline-primary rounded-pill" href="#{anchor}">{html.escape(label)}</a>'
        )
        cards.append(_researcher_card_html(item, name_map, anchor))

    profile_note = f' ({profile})' if profile != 'default' else ''
    body_html = f'<nav class="toc">{"".join(toc_links)}</nav>\n{"".join(cards)}'
    return mmd.html_page(
        title=f'연구원 보유 전문성 분석{profile_note}',
        heading=f'연구원 보유 전문성 분석{profile_note}',
        subtitle='연구원별 강점 분야·전문성 프로필 (R&amp;D Talent Profiling Agent)',
        body_html=body_html,
        extra_style=mmd.EXPERTISE_CARD_STYLE,
    )


def _write_html(results: list, profile: str, researchers_df: pd.DataFrame):
    suffix = mmd.profile_suffix(profile)
    html_out = _build_html(results, profile, researchers_df)
    html_path = os.path.join(OUT_DIR, f'연구원 보유 전문성 분석{suffix}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f'[OK]   연구원 보유 전문성 분석{suffix}.html 저장 ({len(results)}명)')


def render_html(profile: str = 'default') -> bool:
    """이미 저장된 연구원 보유 전문성 분석[.profile].json을 읽어 .html만 다시
    만든다(LLM 재호출 없음). 새로 분석하지 않고 기존 JSON을 리포트로 보고 싶을 때
    'python pipeline/process_researcher_expertise.py --html-only [--profile ...]'로 실행한다."""
    suffix = mmd.profile_suffix(profile)
    json_path = os.path.join(OUT_DIR, f'연구원 보유 전문성 분석{suffix}.json')
    if not os.path.exists(json_path):
        print(f'[process_researcher_expertise] 연구원 보유 전문성 분석{suffix}.json 없음 — 종료 '
              f'(python pipeline/process_researcher_expertise.py'
              f'{" --profile " + profile if profile != "default" else ""} 먼저 실행)')
        return False

    with open(json_path, encoding='utf-8') as f:
        results = json.load(f)

    researchers = _read_csv('researchers')
    _write_html(results, profile, researchers)
    return True


def process(profile: str = 'default', refresh_journals: bool = False) -> bool:
    researchers = _read_csv('researchers')
    if researchers.empty:
        print('[process_researcher_expertise] researchers.csv 없음 — 종료')
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

    journal_cache = _load_journal_cache(profile)
    journal_cache = _update_journal_authority(_unique_journals(publications), journal_cache, profile,
                                               force=refresh_journals)

    rids = researchers['researcher_id'].unique()
    results = []
    print(f'[process_researcher_expertise] 연구원 {len(rids)}명 전문성 분석 중 (profile={profile})...')
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
            continue

        prompt = _build_prompt(edu_text, task_text, job_text, core_text, tech_text, pub_text, pat_text, obj_text)
        analysis = _analyze_researcher(prompt, profile=profile)
        if analysis is None:
            print(f'    [{rid}] 분석 실패')
            continue

        results.append({'researcher_id': rid, **analysis})
        print(f'    [{rid}] 분석 완료')

    suffix = mmd.profile_suffix(profile)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f'연구원 보유 전문성 분석{suffix}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f'[OK]   연구원 보유 전문성 분석{suffix}.json 저장 ({len(results)}명)')

    _write_html(results, profile, researchers)
    return True


if __name__ == '__main__':
    _profile = mmd.parse_profile_arg(sys.argv)
    if '--html-only' in sys.argv:
        render_html(_profile)
    else:
        process(profile=_profile, refresh_journals='--refresh-journals' in sys.argv)
