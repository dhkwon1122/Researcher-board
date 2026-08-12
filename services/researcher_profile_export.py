"""
"보유 전문성" 자연어 질문 결과에서 선택한 연구원들의 프로필을 엑셀로 내보낸다
(`pages/researcher_similarity_map.py`의 "엑셀 다운로드" 버튼 → 모달에서 사용).

컬럼 구성/표기 규칙은 사용자와의 인터뷰로 확정된 것을 그대로 코드화한 것 —
바꾸려면 아래 `_COLUMNS`와 각 `_col_*` 함수만 수정하면 된다. 규칙 요약:
  - 사번: researcher_id 8자리 0패딩(data_store.read_processed가 이미 패딩해 줌)
  - 값이 없으면 전부 "-" (다중 이력 필드는 이력이 하나도 없을 때 셀 전체가 "-")
  - 날짜는 대부분 'YY(2자리 연도, 예: '24)로 축약 표기 — 원본 협의 그대로
  - 학력/과제수행이력/양성이력/핵심이력은 한 셀 안에 줄바꿈(\\n)으로 여러 줄
"""
import io
import math
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from components.timeline_data import dedupe_patents, is_registered
from services import data_store

_FONT_NAME = '바탕체'
_FONT_SIZE = 11
_THIN = Side(style='thin', color='000000')
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_DEGREE_ORDER = ['박사', '석사', '학사']
_DEGREE_CODE = {'박사': '박', '석사': '석', '학사': '학'}

_PROMOTION_REF_BASE = date(2027, 3, 1)


def _s(v) -> str:
    """빈 값/NaN을 빈 문자열로 통일."""
    if v is None:
        return ''
    s = str(v).strip()
    return '' if s.lower() in ('', 'nan', 'none', 'nat') else s


def _or_dash(v) -> str:
    s = _s(v)
    return s if s else '-'


def _yy(date_str) -> str:
    s = _s(date_str)
    if len(s) >= 4 and s[:4].isdigit():
        return "'" + s[2:4]
    return ''


def _next_promotion_ref_date(today: date) -> date:
    """직급/년차 기준일 — 2027-03-01부터 시작해 오늘을 지나지 않은 첫 3/1."""
    ref = _PROMOTION_REF_BASE
    while ref < today:
        ref = ref.replace(year=ref.year + 1)
    return ref


def _floor1(x: float) -> float:
    return math.floor(x * 10) / 10


def _load_tables() -> dict:
    return {
        'researchers': data_store.read_processed('researchers'),
        'education': data_store.read_processed('education'),
        'evaluations': data_store.read_processed('evaluations'),
        'tasks': data_store.read_processed('tasks'),
        'nurturing': data_store.read_processed('nurturing'),
        'incentive_selection': data_store.read_processed('incentive_selection'),
        'team_refer': data_store.read_processed('team_refer'),
        'tech_ownership': data_store.read_processed('tech_ownership'),
        'patents': data_store.read_processed('patents'),
        'publications': data_store.read_processed('publications'),
        'expertise_profiles': data_store.read_expertise_profiles(),
    }


def _rows_for(df, researcher_id: str):
    if df is None or df.empty or 'researcher_id' not in df.columns:
        return []
    return df[df['researcher_id'] == researcher_id].to_dict('records')


def _df_for(df, researcher_id: str):
    """_rows_for()의 DataFrame 버전 — dedupe_patents()처럼 DataFrame을 그대로
    받아야 하는 헬퍼(특허 국가별 중복 합치기)에 넘길 때 사용."""
    if df is None or df.empty or 'researcher_id' not in df.columns:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    return df[df['researcher_id'] == researcher_id]


def _col_id(rid, _rows):
    return rid


def _col_knox(_rid, rows):
    return _or_dash(rows['researcher'].get('knox_id') if rows['researcher'] else None)


def _col_name_gender_age(_rid, rows):
    r = rows['researcher']
    if not r:
        return '-'
    name = _or_dash(r.get('name'))
    gender = _s(r.get('gender')) or '-'
    birth_year = _s(r.get('birth_year'))
    age = f'{datetime.now().year - int(birth_year)}세' if birth_year.isdigit() else '-'
    return f'{name}\n({gender}/{age})'


def _col_dept_task(_rid, rows):
    r = rows['researcher']
    if not r:
        return '-'
    dept = _or_dash(r.get('department'))
    org = _or_dash(r.get('org_code'))
    return f'{dept}\n({org})'


def _col_hire_date(_rid, rows):
    r = rows['researcher']
    hire_date = _s(r.get('hire_date')) if r else ''
    if not hire_date:
        return '-'
    hd = date.fromisoformat(hire_date[:10])
    tenure = round((date.today() - hd).days / 365, 1)
    return f"{hd.strftime('%Y%m%d')}\n({tenure}년)"


def _col_education(_rid, rows):
    by_degree = {}
    for e in rows['education']:
        deg = _s(e.get('degree'))
        if deg in _DEGREE_CODE:
            by_degree.setdefault(deg, e)
    lines = []
    for deg in _DEGREE_ORDER:
        e = by_degree.get(deg)
        if not e:
            continue
        code = _DEGREE_CODE[deg]
        school = _or_dash(e.get('school'))
        major = _or_dash(e.get('major'))
        lines.append(f'{code}){school} {major}')
    return '\n'.join(lines) if lines else '-'


def _col_evaluation(_rid, rows):
    grade_by_year = {_s(e.get('year')): _s(e.get('grade')) for e in rows['evaluations']}
    parts = [grade_by_year.get(str(y)) or '-' for y in (2024, 2025, 2026)]
    return '/'.join(parts)


def _col_position_year(_rid, rows):
    r = rows['researcher']
    if not r:
        return '-'
    position = _or_dash(r.get('position'))
    promo = _s(r.get('promotion_date'))
    if not promo:
        return position
    promo_dt = date.fromisoformat(promo[:10])
    ref = _next_promotion_ref_date(date.today())
    years = int(_floor1((ref - promo_dt).days / 365))
    return f'{position}-{years}'


def _col_position_title(_rid, rows):
    """직책 = team_refer.csv의 assignment_name(조직장급만 등록돼 있어 대부분
    매핑이 없음 — 그 경우 "-")."""
    team_rows = rows['team_refer']
    return _or_dash(team_rows[0].get('assignment_name')) if team_rows else '-'


def _col_tasks(_rid, rows):
    items = sorted(rows['tasks'], key=lambda t: _s(t.get('start_date')), reverse=True)
    lines = []
    for t in items:
        name = _s(t.get('task_name')) or '-'
        start = _yy(t.get('start_date')) or '-'
        end = _yy(t.get('end_date')) or '현재'
        lines.append(f'{name}({start} ~ {end})')
    return '\n'.join(lines) if lines else '-'


def _col_nurturing(_rid, rows):
    items = sorted(rows['nurturing'], key=lambda n: _s(n.get('start_date')))
    lines = []
    for n in items:
        start = _yy(n.get('start_date')) or '-'
        end = _yy(n.get('end_date')) or '-'
        subcategory = _or_dash(n.get('subcategory'))
        institution = _or_dash(n.get('institution'))
        lines.append(f"{start}~{end} / {subcategory} / {institution}")
    return '\n'.join(lines) if lines else '-'


def _col_incentive(_rid, rows):
    items = [i for i in rows['incentive_selection'] if _s(i.get('selected')).lower() in ('true', '1')]
    items.sort(key=lambda i: _s(i.get('year')))
    lines = [f"{_yy(i.get('year'))} : {_or_dash(i.get('category'))}" for i in items]
    return '\n'.join(lines) if lines else '-'


def _col_tech_ownership(_rid, rows):
    """보유기술 — components/detail_tabs.py의 _tech_ownership_table()과 동일하게
    tech_ownership.csv의 tech_1~5/lv_1~5/portion_1~5를 "전문분야(Lv N, 보유율 M%)"
    형태로 한 셀에 줄바꿈 나열한다(화면의 '보유기술' 표와 동일 항목, 데이터 없는
    슬롯은 건너뜀)."""
    tech_rows = rows['tech_ownership']
    if not tech_rows:
        return '-'
    tech_row = tech_rows[0]
    lines = []
    for i in range(1, 6):
        name = _s(tech_row.get(f'tech_{i}'))
        if not name:
            continue
        lv = _s(tech_row.get(f'lv_{i}')) or '-'
        portion = _s(tech_row.get(f'portion_{i}'))
        portion_disp = f'{portion}%' if portion else '-'
        lines.append(f'{name} (Lv {lv}, 보유율 {portion_disp})')
    return '\n'.join(lines) if lines else '-'


def expertise_field_lines(profile: dict | None, field: str) -> str:
    """보유 전문성(LLM) 프로필 dict에서 필드 하나(strength_fields 등)를 줄바꿈
    나열 문자열로 뽑는다. services/similarity_map.py의 조직도 기반 다운로드처럼
    _researcher_row_context() 없이 profile dict만 있는 호출부에서도 같은 서식을
    쓸 수 있도록 _expertise_field()의 내부 로직을 공개 함수로 분리했다."""
    items = (profile.get(field) if profile else None) or []
    return '\n'.join(items) if items else '-'


def _expertise_field(field: str):
    """보유 전문성(LLM)의 한 필드를 한 셀에 줄바꿈으로 나열하는 컬럼 함수를 만든다.
    components/detail_tabs.py의 llm_summary_block()과 동일한 4개 필드
    (strength_fields/strength_keywords/key_responsibilities/domain_knowledge_skill)를
    강점 분야/강점 키워드/주요 역할·책임/전문지식 및 역량 4개 컬럼으로 나눠 받고
    싶다는 요청에 따라 컬럼별 함수로 분리했다. 다운로드 시 선택 사항(옵트인)."""
    def _col(_rid, rows):
        return expertise_field_lines(rows.get('expertise_profile'), field)
    return _col


_EXPERTISE_COLUMNS = [
    ('보유전문성(강점 분야)', _expertise_field('strength_fields')),
    ('보유전문성(강점 키워드)', _expertise_field('strength_keywords')),
    ('보유전문성(주요 역할·책임)', _expertise_field('key_responsibilities')),
    ('보유전문성(전문지식 및 역량)', _expertise_field('domain_knowledge_skill')),
]


def _col_patents(_rid, rows):
    """특허 실적 — components/detail_tabs.py의 patents_tab()과 동일하게
    dedupe_patents()로 국가별 중복 출원 행을 하나로 합친 뒤, 출원일 내림차순으로
    "출원일 : 발명명칭 (상태, 대표발명자, 지분율%, 등급)"를 한 셀에 줄바꿈 나열."""
    pat = rows.get('patents_df')
    if pat is None or pat.empty:
        return '-'
    pat_dedup = dedupe_patents(pat)
    sort_col = 'application_date' if 'application_date' in pat_dedup.columns else pat_dedup.columns[0]
    lines = []
    for _, p in pat_dedup.sort_values(sort_col, ascending=False).iterrows():
        date = _s(p.get('application_date'))[:7] or '-'
        title = _s(p.get('title')) or _s(p.get('title_ko')) or '-'
        status = _s(p.get('status')) or '-'
        lead = '대표' if _s(p.get('is_lead_inventor')).lower() in ('y', '1', 'true') else ''
        share = _s(p.get('share_ratio'))
        share_disp = f'{share}%' if share else ''
        grade = _s(p.get('patent_grade'))
        grade_a = _s(p.get('patent_grade_a_sub'))
        grade_disp = grade + (f'({grade_a})' if grade_a else '') if grade else ''
        extras = ', '.join(v for v in (status, lead, share_disp, grade_disp) if v)
        lines.append(f'{date} : {title}' + (f' ({extras})' if extras else ''))
    return '\n'.join(lines) if lines else '-'


def _col_publications(_rid, rows):
    """논문 실적 — components/detail_tabs.py의 publications_tab()과 동일하게
    pub_date(없으면 pub_year) 내림차순으로 "발표일 : 제목 (게재처, 순위/총수,
    기여도%, 교신)"를 한 셀에 줄바꿈 나열."""
    items = rows.get('publications') or []
    if not items:
        return '-'
    items = sorted(items, key=lambda p: _s(p.get('pub_date')) or _s(p.get('pub_year')), reverse=True)
    lines = []
    for p in items:
        date = (_s(p.get('pub_date')) or _s(p.get('pub_year')))[:7] or '-'
        title = _s(p.get('title')) or '-'
        journal = _s(p.get('journal'))
        rank, total = _s(p.get('author_rank')), _s(p.get('total_authors'))
        rank_total = f'{rank}/{total}' if rank and total else ''
        contrib = _s(p.get('contribution'))
        contrib_disp = f'기여도 {contrib}%' if contrib else ''
        corr = '교신' if _s(p.get('is_corresponding')).lower() in ('true', '1', 'y', 'yes') else ''
        extras = ', '.join(v for v in (journal, rank_total, contrib_disp, corr) if v)
        lines.append(f'{date} : {title}' + (f' ({extras})' if extras else ''))
    return '\n'.join(lines) if lines else '-'


_PATENT_COLUMNS = [('특허 실적', _col_patents)]
_PUBLICATION_COLUMNS = [('논문 실적', _col_publications)]


# (헤더, 값 계산 함수) — 순서 = 엑셀 컬럼 순서
_COLUMNS = [
    ('사번', _col_id),
    ('Knox ID', _col_knox),
    ('성명\n(성별/나이)', _col_name_gender_age),
    ('부서\n(과제)', _col_dept_task),
    ('입사일', _col_hire_date),
    ('학력', _col_education),
    ("평가\n('24~'26)", _col_evaluation),
    ('CL/년차', _col_position_year),
    ('직책', _col_position_title),
    ('과제수행이력', _col_tasks),
    ('양성이력', _col_nurturing),
    ('핵심이력', _col_incentive),
    ('보유기술', _col_tech_ownership),
]


def _researcher_row_context(researcher_id: str, tables: dict) -> dict:
    researcher_rows = _rows_for(tables['researchers'], researcher_id)
    return {
        'researcher': researcher_rows[0] if researcher_rows else None,
        'education': _rows_for(tables['education'], researcher_id),
        'evaluations': _rows_for(tables['evaluations'], researcher_id),
        'tasks': _rows_for(tables['tasks'], researcher_id),
        'nurturing': _rows_for(tables['nurturing'], researcher_id),
        'incentive_selection': _rows_for(tables['incentive_selection'], researcher_id),
        'team_refer': _rows_for(tables['team_refer'], researcher_id),
        'tech_ownership': _rows_for(tables['tech_ownership'], researcher_id),
        'patents_df': _df_for(tables['patents'], researcher_id),
        'publications': _rows_for(tables['publications'], researcher_id),
        'expertise_profile': tables['expertise_profiles'].get(researcher_id),
    }


def researcher_name_map() -> dict:
    """researcher_id -> name 매핑(엑셀 다운로드 후보 라벨 생성용)."""
    df = data_store.read_processed('researchers')
    if df.empty or 'name' not in df.columns:
        return {}
    return dict(zip(df['researcher_id'], df['name']))


def candidate_label(researcher_id: str, name_map: dict | None = None) -> str:
    """모달 체크리스트에 보여줄 "이름 (사번)" 라벨. 이름 없으면 사번만."""
    name_map = name_map if name_map is not None else researcher_name_map()
    name = _s(name_map.get(researcher_id))
    return f'{name} ({researcher_id})' if name else researcher_id


# 자연어 질문(nl_query/open_data_query) 결과가 "사람에 대한 데이터"로 판단되면
# (결과에 researcher_id 컬럼이 있으면) 항상 맨 앞에 붙이는 7개 기본 컬럼.
# 값 계산 로직은 엑셀 다운로드와 동일한 걸 재사용(같은 사람은 어디서 봐도
# 같은 표기) — 학력은 엑셀처럼 전체 이력이 아니라 "최종 학력 1건만", CL/년차는
# _col_position_year()를 그대로 재사용(예: "CL4-17", 승격기준일 없으면 "CL4").
PERSON_BASE_COLUMNS = ['researcher_id', 'name', 'department', 'org_code', 'position_year', 'degree_major', 'age']

# _highest_degree_str() 전용 — 엑셀 다운로드의 _col_education()(박/석/학사만,
# 나머지 제외)과 달리 여기서는 전공만 필터에서 뺄 뿐 학력 자체는 전문대/고교
# 까지 전부 인정한다(process_education.py의 DEG_ORDER와 동일한 5단계 우선순위
# — education.csv 자체가 이미 "학사 이상이 있으면 전문대/고교 제외" 규칙으로
# 정리돼 있어서, 여기 남아 있는 전문대/고교는 그게 그 사람의 최종 학력이라는 뜻).
_DEGREE_ORDER_FULL = ['박사', '석사', '학사', '전문대', '고교']
_DEGREE_CODE_FULL = {'박사': '박', '석사': '석', '학사': '학', '전문대': '전', '고교': '고'}


def _highest_degree_str(education_rows: list) -> str:
    by_degree = {}
    for e in education_rows:
        deg = _s(e.get('degree'))
        if deg in _DEGREE_CODE_FULL:
            by_degree.setdefault(deg, e)
    for deg in _DEGREE_ORDER_FULL:
        e = by_degree.get(deg)
        if e:
            code = _DEGREE_CODE_FULL[deg]
            school = _or_dash(e.get('school'))
            major = _or_dash(e.get('major'))
            return f'{code}){school} {major}'
    return '-'


def person_base_table(researcher_ids: list) -> dict:
    """PERSON_BASE_COLUMNS 순서에 맞는 값 리스트를 researcher_id별로 반환.
    researchers.csv/education.csv를 한 번만 읽어 여러 명을 한꺼번에 처리한다
    (nl_query/open_data_query가 결과 테이블 렌더링 때마다 호출하므로 매번
    파일을 다시 읽지 않도록)."""
    researchers_df = data_store.read_processed('researchers')
    education_df = data_store.read_processed('education')
    researchers_by_id = (
        researchers_df.set_index('researcher_id').to_dict('index') if not researchers_df.empty else {}
    )
    current_year = datetime.now().year

    out = {}
    for rid in researcher_ids:
        r = researchers_by_id.get(rid)
        edu_rows = _rows_for(education_df, rid)
        degree_major = _highest_degree_str(edu_rows)
        if r:
            name = _or_dash(r.get('name'))
            department = _or_dash(r.get('department'))
            org_code = _or_dash(r.get('org_code'))
            position_year = _col_position_year(rid, {'researcher': r})
            birth_year = _s(r.get('birth_year'))
            age = str(current_year - int(birth_year)) if birth_year.isdigit() else '-'
        else:
            name = department = org_code = position_year = age = '-'
        out[rid] = [rid, name, department, org_code, position_year, degree_major, age]
    return out


_COLUMN_WIDTHS = [12, 14, 16, 18, 12, 26, 12, 12, 10, 34, 30, 22, 30]
_EXPERTISE_COLUMN_WIDTH = 26
_PATENT_COLUMN_WIDTH = 40
_PUBLICATION_COLUMN_WIDTH = 40


def build_profile_workbook(
    researcher_ids: list,
    include_expertise: bool = False,
    include_patents: bool = False,
    include_publications: bool = False,
) -> bytes:
    """선택된 researcher_id 목록으로 엑셀(xlsx) 바이트를 만들어 반환한다.
    양식: 바탕체 11pt, 전체 검정 테두리, 헤더만 볼드, 줄바꿈 셀은 자동 줄바꿈.
    include_expertise/include_patents/include_publications가 True인 항목만
    해당 옵트인 컬럼 그룹(_EXPERTISE_COLUMNS/_PATENT_COLUMNS/
    _PUBLICATION_COLUMNS)을 이 순서대로 맨 끝에 추가한다 — 전부 기본값은
    False(다운로드 화면 체크박스 기본 해제)이고, 켜져도 _COLUMNS 자체는
    건드리지 않고 이 함수 안에서만 로컬 사본에 덧붙인다."""
    tables = _load_tables()

    columns = list(_COLUMNS)
    widths = list(_COLUMN_WIDTHS)
    if include_patents:
        columns.extend(_PATENT_COLUMNS)
        widths.extend([_PATENT_COLUMN_WIDTH] * len(_PATENT_COLUMNS))
    if include_publications:
        columns.extend(_PUBLICATION_COLUMNS)
        widths.extend([_PUBLICATION_COLUMN_WIDTH] * len(_PUBLICATION_COLUMNS))
    # 보유 전문성(LLM 산출, 부서장/본인 컨펌을 거치지 않은 비객관적 정보)은
    # 다른 옵트인 컬럼과 무엇을 같이 선택하든 항상 맨 마지막 컬럼이 되도록
    # 다른 그룹 뒤에 붙인다.
    if include_expertise:
        columns.extend(_EXPERTISE_COLUMNS)
        widths.extend([_EXPERTISE_COLUMN_WIDTH] * len(_EXPERTISE_COLUMNS))

    wb = Workbook()
    ws = wb.active
    ws.title = '연구원 프로필'

    header_font = Font(name=_FONT_NAME, size=_FONT_SIZE, bold=True)
    body_font = Font(name=_FONT_NAME, size=_FONT_SIZE, bold=False)
    wrap_center = Alignment(wrap_text=True, vertical='center', horizontal='center')
    wrap_left = Alignment(wrap_text=True, vertical='center', horizontal='left')

    for col_idx, (header, _fn) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.border = _BORDER
        cell.alignment = wrap_center

    for row_idx, rid in enumerate(researcher_ids, start=2):
        ctx = _researcher_row_context(rid, tables)
        for col_idx, (_header, fn) in enumerate(columns, start=1):
            value = fn(rid, ctx)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = body_font
            cell.border = _BORDER
            cell.alignment = wrap_left

    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def default_filename() -> str:
    return f"연구원_프로필_{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
