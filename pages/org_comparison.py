"""
리포팅 > 석세션 플랜 — 전체 조직 조직장 석세션 후보 카드(조직별 우수
연구원 비교) + 데이터 입력 패널. 조회·편집 둘 다 임원조직 담당자만
가능하다(services.auth.can_view_succession_plan() 참고, 사용자 요청).

2026-10-07: "석세션 데이터를 입력할 방법이 없다"는 요청으로 편집 패널
추가(services/succession_store.py) — 부서를 고르면 그 부서 소속 연구원
중에서 Ready Now/Ready Later 순위(1·2위)와 코멘트를 지정해 저장한다.
"""

import math
import os
from datetime import date, datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import (
    ClientsideFunction, Input, Output, State, callback, clientside_callback,
    dcc, html, no_update,
)

from components.profile_sections import load_photo_src

dash.register_page(__name__, path='/succession-plan', name='석세션 플랜', title='석세션 플랜')

# 한동안 사용하지 않는 화면이라 숨겨뒀었는데(_FEATURE_HIDDEN=True), 사용자
# 요청으로 "리포팅 > 석세션 플랜" 메뉴로 되살렸다 — app.py의 네비게이션 바
# "리포팅" 드롭다운이 can_view_succession_plan()일 때만 이 경로로 가는
# 링크를 보여준다. 혹시 다시 숨겨야 하면 이 플래그를 True로 되돌리면 된다
# (docs/CLAUDE.md 참고).
_FEATURE_HIDDEN = False

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

CURRENT_YEAR = datetime.now().year

RANK_META = {
    ('Ready Now',   1): ('Ready Now 1순위',   'danger'),
    ('Ready Now',   2): ('Ready Now 2순위',   'warning'),
    ('Ready Later', 1): ('Ready Later 1순위', 'info'),
    ('Ready Later', 2): ('Ready Later 2순위', 'secondary'),
}

AWARD_TYPES = {'그룹표창', '대표이사표창', '대표이사표창(시상금미포함)', '부문표창'}


# ─── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _r(name):
    # 데이터 소스 추상화 계층 경유 (DB 설정 시 PostgreSQL, 아니면 CSV 폴백)
    from services.data_store import read_processed
    return read_processed(name, dtype=str)




def _avatar(name, size=64):
    colors = ['#4a90e2', '#e25757', '#52c41a', '#f5a623', '#9b59b6', '#1abc9c']
    color = colors[hash(name) % len(colors)]
    return html.Div(
        name[:2] if name else '?',
        style={
            'width': f'{size}px', 'height': f'{size}px', 'borderRadius': '50%',
            'background': color, 'color': '#fff', 'display': 'flex',
            'alignItems': 'center', 'justifyContent': 'center',
            'fontWeight': 'bold', 'fontSize': f'{size // 3}px', 'margin': '0 auto',
        },
    )


def _section(title, body):
    return html.Div([
        html.P(title, className='fw-bold small text-primary mb-1'),
        body,
    ], className='bg-light rounded p-2')


def _pad_li_slots(items: list, n: int = 3) -> list:
    """목록 항목을 최소 n개 슬롯으로 맞춘다 — 실제 항목이 n개보다 적으면
    보이지 않는(visibility: hidden) 빈 <li>로 채워 칸을 고정한다(2026-10-08,
    사용자 요청 — 학력·시상이력 줄 수가 카드마다 다르면 그 위의 사진 위치도
    카드마다 달라져, 항상 n줄만큼 높이를 차지하게 한다)."""
    padded = list(items)
    while len(padded) < n:
        padded.append(html.Li(' ', className='small', style={'visibility': 'hidden'}))
    return padded


def _parse_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ('', 'nan', 'None', 'NaT'):
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _info_lines(r_info):
    """1줄: 성명(성별/나이)   2줄: 직급-직급년차년차"""
    name = str(r_info.get('name', '-'))
    gender = str(r_info.get('gender', '')).strip()
    try:
        age_str = f'{CURRENT_YEAR - int(float(r_info["birth_year"]))}세'
    except (TypeError, ValueError, KeyError):
        age_str = '-'
    position = str(r_info.get('position', '')).strip()

    promo_dt = _parse_date(r_info.get('promotion_date'))
    position_year = math.ceil((date(2027, 3, 1) - promo_dt).days / 365) if promo_dt else None

    line1 = f'{name}({gender}/{age_str})' if gender else f'{name}({age_str})'
    if position:
        line2 = f'{position}-{position_year}년차' if position_year is not None else position
    else:
        line2 = ''
    return line1, line2


def _eval_string(r_eva):
    """최근 3년(회계연도 기준) 연봉등급을 '가나다' 형태로 연결. 없으면 'O'.

    2026-10-07 수정: evaluations.csv는 이미 오래전에 researcher_id당 1행인
    와이드 스키마({연도}_salary_grade 등, services/evaluations.py 참고)로
    바뀌었는데, 이 함수는 옛 롱 포맷(researcher_id/year/grade)을 그대로
    참조하고 있어 실제 평가 데이터가 있으면 KeyError: 'year'로 이
    페이지(/succession-plan) 전체가 500 에러로 죽었다 — 석세션 데이터
    입력 기능을 추가하면서(저장 후 조회 화면을 다시 그리는 경로가 새로
    생겨) 이 잠재 버그가 실제로 터지는 것을 확인해 바로잡았다. 연구원
    명단(pages/researcher_list.py) 등 다른 화면이 이미 쓰는 것과 동일하게
    services.evaluations의 회계연도 계산을 재사용한다."""
    from services.evaluations import evaluation_years, salary_grade_column
    years = sorted(evaluation_years()[0])
    if r_eva.empty:
        return 'O' * len(years)
    row = r_eva.iloc[0]
    chars = []
    for yr in years:
        g = str(row.get(salary_grade_column(yr), '') or '').strip()
        chars.append(g if g and g not in ('nan', '-', '') else 'O')
    return ''.join(chars)


def _incentive_string(r_inc):
    """최근 3년 인센티브 등급(S/A/B/C)을 한 글자씩 연결. 없으면 '-'."""
    def _char(row):
        cat = str(row.get('category', '')).strip().upper()
        if cat in ('S', 'A', 'B', 'C'):
            return cat
        return '-'

    chars = []
    for yr in ['2024', '2025', '2026']:
        row = r_inc[r_inc['year'].astype(str) == yr] if not r_inc.empty else pd.DataFrame()
        chars.append(_char(row.iloc[0]) if not row.empty else '-')
    return ''.join(chars)


# ─── 후보 카드 빌더 ─────────────────────────────────────────────────────────────

def _candidate_card(r_info, rank_type, rank_order, eva, edu, awd, nur, inc,
                    show_eval: bool = True, show_incentive: bool = True):
    rid    = str(r_info['researcher_id'])
    name   = str(r_info.get('name', '-'))

    label, badge_color = RANK_META.get(
        (rank_type, rank_order),
        (f'{rank_type} {rank_order}순위', 'secondary'),
    )

    # 사진
    src = load_photo_src(rid)
    photo_el = (
        html.Img(src=src,
                 style={'width': '100%', 'maxHeight': '130px',
                        'objectFit': 'contain', 'borderRadius': '6px'})
        if src else _avatar(name, 70)
    )

    # 학력
    r_edu = edu[edu['researcher_id'] == rid] if not edu.empty else pd.DataFrame()
    edu_items = []
    for deg in ['박사', '석사', '학사', '전문대', '고교']:
        row = r_edu[r_edu['degree'] == deg]
        if not row.empty:
            r0 = row.iloc[0]
            edu_items.append(html.Li(
                f"{deg}  {r0.get('school', '-')}  {r0.get('major', '-')}",
                className='small',
            ))
    if not edu_items:
        edu_items = [html.Li('데이터 없음', className='small text-muted')]
    edu_section = _section('학력', html.Ul(
        _pad_li_slots(edu_items),
        className='ps-3 mb-0 small',
    ))

    # 주요 시상이력
    r_awd = awd[awd['researcher_id'] == rid].copy() if not awd.empty else pd.DataFrame()
    if not r_awd.empty:
        r_awd = r_awd[r_awd['award_type'].astype(str).str.strip().isin(AWARD_TYPES)]
        r_awd = r_awd.sort_values('award_date', ascending=False).head(3)
    award_items = []
    for _, aw in r_awd.iterrows():
        yr    = str(aw.get('year', str(aw.get('award_date', ''))[:4])).strip()
        aname = str(aw.get('award_name', '')).strip()
        desc  = str(aw.get('description', '')).strip()
        yr_label = f"'{yr[-2:]}" if len(yr) >= 2 else yr
        parts = [p for p in [yr_label, aname, desc] if p and p not in ('nan',)]
        # line-clamp 스타일을 <li>에 직접 주면 display:-webkit-box가 기본
        # list-item 표시를 덮어써 목록 점(•)이 사라진다 — 안쪽 <span>에만
        # 적용해 <li>는 기본 표시를 유지하도록 분리한다(2026-10-08 수정).
        award_items.append(html.Li(
            html.Span(
                ' / '.join(parts) if parts else '-',
                style={
                    'display': '-webkit-box',
                    'WebkitLineClamp': '1',
                    'WebkitBoxOrient': 'vertical',
                    'overflow': 'hidden',
                    'textOverflow': 'ellipsis',
                },
            ),
            className='small',
        ))
    if not award_items:
        award_items = [html.Li('해당 없음', className='small text-muted')]
    award_section = _section('주요 시상이력', html.Ul(
        _pad_li_slots(award_items),
        className='ps-3 mb-0 small',
    ))

    # 기본인적사항
    line1, line2 = _info_lines(r_info)
    r_eva = eva[eva['researcher_id'] == rid] if not eva.empty else pd.DataFrame()
    r_inc = inc[inc['researcher_id'] == rid] if not inc.empty else pd.DataFrame()

    eval_str = _eval_string(r_eva) if show_eval else None
    inc_str  = _incentive_string(r_inc) if show_incentive else None

    grade_items = []
    if show_eval and eval_str is not None:
        grade_items.append(
            html.Span(eval_str, className='small fw-bold me-3',
                      style={'letterSpacing': '0.15em'}),
        )
    if show_incentive and inc_str is not None:
        grade_items.append(
            html.Span(inc_str, className='small fw-bold',
                      style={'letterSpacing': '0.15em'}),
        )
    if not grade_items:
        grade_items = [
            html.I(className='bi bi-lock-fill me-1 text-secondary'),
            html.Span('평가/인센티브 정보 — 접근 권한 없음',
                      className='text-muted small'),
        ]

    basic_section = html.Div([
        html.P(line1, className='small fw-bold mb-0 text-center'),
        html.P(line2, className='small text-muted mb-2 text-center'),
        html.Div(grade_items, className='d-flex flex-wrap align-items-center justify-content-center'),
    ], className='bg-light rounded p-2')

    # 주요 양성이력
    r_nur = nur[nur['researcher_id'] == rid] if not nur.empty else pd.DataFrame()
    if not r_nur.empty:
        sort_col = 'start_date' if 'start_date' in r_nur.columns else (
                   'year' if 'year' in r_nur.columns else r_nur.columns[0])
        r_nur = r_nur.sort_values(sort_col, ascending=False).head(3)
    nur_items = []
    for _, nr in r_nur.iterrows():
        start = str(nr.get('start_date', '')).strip()
        end   = str(nr.get('end_date', '')).strip()
        sy    = start[:4] if len(start) >= 4 else ''
        ey    = end[:4]   if len(end)   >= 4 else ''
        if sy:
            yr_label = f"'{sy[-2:]}"
            if ey and ey > sy:
                yr_label += f"~'{ey[-2:]}"
        else:
            yr_label = ''
        sub     = str(nr.get('subcategory', '')).strip()
        country = str(nr.get('country', '')).strip()
        inst    = str(nr.get('institution', '')).strip()
        loc_parts = [p for p in [country, inst] if p and p not in ('nan',)]
        loc = ' '.join(loc_parts) if loc_parts else ''
        parts = [p for p in [yr_label, sub, loc] if p and p not in ('nan',)]
        nur_items.append(html.Li(
            ' / '.join(parts) if parts else '-',
            className='small',
        ))
    nur_section = _section('주요 양성이력', html.Ul(
        nur_items or [html.Li('해당 없음', className='small text-muted')],
        className='ps-3 mb-0 small',
    ))

    card = dbc.Card([
        dbc.CardHeader(
            dbc.Badge(label, color=badge_color, className='fs-6 px-3 py-2'),
            className='text-center bg-white border-bottom-0 pb-1',
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col(photo_el, width=4,
                        className='d-flex align-items-center justify-content-center'),
                dbc.Col([edu_section, html.Div(className='mb-2'), award_section], width=8),
            ], className='g-2 mb-2'),
            dbc.Row([
                dbc.Col(basic_section, width=4),
                dbc.Col(nur_section, width=8),
            ], className='g-2'),
        ], className='p-2'),
    ], className='shadow-sm h-100 border-0')

    return html.A(
        card,
        href=f'/?id={rid}',
        style={'textDecoration': 'none', 'color': 'inherit',
               'display': 'block', 'height': '100%'},
    )


# ─── 부서 섹션 빌더 ─────────────────────────────────────────────────────────────

def _dept_section(dept_name, suc_dept, res, eva, edu, awd, nur, inc,
                  show_eval: bool = True, show_incentive: bool = True):
    """동일 현소속부서명 소속 우수 연구원을 한 행(섹션)으로 표시.
    표시 순서 고정: Ready Now 1→2, Ready Later 1→2 (최대 4명).
    """
    if suc_dept.empty:
        return None

    s = suc_dept.copy()
    s['rank_order'] = pd.to_numeric(s['rank_order'], errors='coerce').fillna(99).astype(int)
    # rank_type 원본 표기 편차(대소문자/공백)에 흔들리지 않도록 정규화 키로 매칭
    s['_rank_type_norm'] = s['rank_type'].astype(str).str.strip().str.lower()

    SLOTS = [
        ('Ready Now',   1),
        ('Ready Now',   2),
        ('Ready Later', 1),
        ('Ready Later', 2),
    ]

    cards = []
    unmatched_ids = []
    for rank_type, rank_order in SLOTS:
        matched = s[(s['_rank_type_norm'] == rank_type.lower()) & (s['rank_order'] == rank_order)]
        if matched.empty:
            continue
        srow = matched.iloc[0]
        rid = str(srow['researcher_id'])
        r_rows = res[res['researcher_id'] == rid]
        if r_rows.empty:
            unmatched_ids.append(rid)
            continue
        card = _candidate_card(
            r_rows.iloc[0], rank_type, rank_order,
            eva, edu, awd, nur, inc,
            show_eval=show_eval, show_incentive=show_incentive,
        )
        cards.append(dbc.Col(card, lg=3, md=6, className='mb-2'))

    if not cards:
        # succession 행은 있지만 카드가 하나도 만들어지지 않은 경우 — rank_type 표기가
        # 'Ready Now'/'Ready Later'와 다르거나 researcher_id가 researchers.csv에 없는
        # 것이 원인일 수 있어, 조용히 사라지는 대신 원인을 화면에 남긴다.
        raw_rank_types = sorted(s['rank_type'].astype(str).unique())
        reasons = []
        if not any(rt.strip().lower() in ('ready now', 'ready later') for rt in raw_rank_types):
            reasons.append(f"rank_type 값이 'Ready Now'/'Ready Later'와 일치하지 않습니다 "
                            f"(원본 값: {', '.join(raw_rank_types)})")
        if unmatched_ids:
            reasons.append(f"researcher_id가 researchers 데이터에 없습니다 "
                            f"({', '.join(unmatched_ids)})")
        if not reasons:
            reasons.append('일치하는 후보를 찾지 못했습니다.')
        return html.Div([
            html.Div([
                html.I(className='bi bi-building me-2 text-primary'),
                html.Span(dept_name, className='fw-bold fs-6'),
            ], className='mb-2 pb-1 border-bottom border-primary border-2'),
            dbc.Alert(
                [html.Strong(f'{dept_name}: 카드를 표시하지 못했습니다. ')] +
                [html.Span(r) for r in reasons],
                color='warning', className='mb-2 py-2 small',
            ),
        ], className='mb-4 org-section')

    return html.Div([
        html.Div([
            html.I(className='bi bi-building me-2 text-primary'),
            html.Span(dept_name, className='fw-bold fs-6'),
        ], className='mb-2 pb-1 border-bottom border-primary border-2'),
        dbc.Row(cards, className='g-3'),
    ], className='mb-4 org-section')


# ─── 레이아웃 ────────────────────────────────────────────────────────────────────

def _department_order_map() -> dict:
    """부서 섹션을 "조직 건제순"(조직도 상 순서)으로 정렬하기 위한
    department명 → dep_code(조직코드) 매핑(2026-10-08, 사용자 요청).

    이 화면이 그룹화 기준으로 쓰는 researchers.csv의 department(원본 헤더
    "현소속부서명")는 team_refer.csv 3단계 부서 체계에서 2단계부서명
    (dep_2nd_name)에 해당한다(docs/CLAUDE.md 2026-09-11 (4) 항목 — 1단계가
    4개 루트 마커가 아닌 일반 조직이면 2단계부서명이 곧 현소속부서명).
    그래서 team_refer의 2단계(team_layer=='2') 행에서 dep_2nd_name →
    dep_code를 모아, 그 조직코드 오름차순으로 부서 섹션을 정렬한다
    (services/similarity_map.py의 department_filter_options()가 1단계에
    대해 쓰는 것과 같은 원리). team_refer 데이터가 없으면 빈 dict를
    반환해 호출부가 가나다순으로 폴백하게 한다."""
    try:
        from pipeline.rd_specialist_markdown import read_team_refer
        from services.data_store import DATA_DIR
        rows = read_team_refer(DATA_DIR)
    except Exception:
        return {}
    order: dict[str, str] = {}
    for r in rows:
        if str(r.get('team_layer') or '').strip() != '2':
            continue
        name = str(r.get('dep_2nd_name') or '').strip()
        code = str(r.get('dep_code') or '').strip()
        if not name or not code:
            continue
        if name not in order or code < order[name]:
            order[name] = code
    return order


def _render_dashboard():
    """석세션 플랜 조회 콘텐츠(H5 제목 + A3 인쇄 버튼 + 부서별 카드) — layout()
    최초 렌더와, 편집 패널에서 "저장" 성공 후 즉시 갱신하는 콜백
    (_refresh_succession_view()) 양쪽이 공유한다."""
    from services.auth import can
    show_eval = can('view_evaluation')
    show_incentive = can('view_incentive')

    try:
        res = _r('researchers')
        eva = _r('evaluations')
        edu = _r('education')
        awd = _r('awards')
        nur = _r('nurturing')
        suc = _r('succession')
        inc = _r('incentive_selection')
    except Exception as e:
        return html.P(f'데이터 로드 실패: {e}', className='text-danger p-3')

    if suc.empty:
        return html.Div([
            html.H5([html.I(className='bi bi-people-fill me-2 text-primary'),
                     '석세션 플랜 (조직별 조직장 승계 후보)'],
                    className='fw-bold mb-3 mt-1'),
            dbc.Alert(
                'succession 데이터가 없습니다. '
                'python pipeline/generate_sample_data.py 로 샘플 데이터를 생성하세요.',
                color='warning',
            ),
        ])

    # year 컬럼 문자열 통일
    for df in (eva, nur):
        if not df.empty and 'year' in df.columns:
            df['year'] = df['year'].astype(str)

    # 현소속부서명(researchers.department) 기준으로 그룹화
    if not res.empty and 'department' in res.columns:
        dept_map = (res[['researcher_id', 'department']]
                    .drop_duplicates('researcher_id')
                    .set_index('researcher_id')['department'].to_dict())
    else:
        dept_map = {}
    suc = suc.copy()
    suc['department'] = suc['researcher_id'].astype(str).map(dept_map).fillna('(소속부서 미상)')

    order_map = _department_order_map()
    # 조직도에서 못 찾은 부서(team_refer 미설정 등)는 뒤로 보내되, 그런
    # 부서끼리는 가나다순으로 안정적으로 정렬되게 이름을 2차 정렬키로 둔다.
    dept_names = sorted(
        suc['department'].unique(),
        key=lambda n: (order_map.get(n, '9999'), n),
    )

    sections = []
    for dept_name in dept_names:
        suc_dept = suc[suc['department'] == dept_name]
        sec = _dept_section(dept_name, suc_dept, res, eva, edu, awd, nur, inc,
                            show_eval=show_eval, show_incentive=show_incentive)
        if sec:
            sections.append(sec)

    # 인쇄용: 3개 섹션씩 한 페이지로 묶기
    page_groups = []
    for i in range(0, len(sections), 3):
        group = sections[i:i + 3]
        is_last = (i + 3 >= len(sections))
        page_groups.append(
            html.Div(group, className='print-page' + (' print-page-last' if is_last else ''))
        )

    return html.Div([
        dbc.Row([
            dbc.Col(
                html.H5(
                    [html.I(className='bi bi-people-fill me-2 text-primary'),
                     '석세션 플랜 (조직별 조직장 승계 후보)'],
                    className='fw-bold mb-0 mt-1',
                ),
            ),
            dbc.Col(
                html.Button(
                    [html.I(className='bi bi-printer me-1'), 'A3 인쇄'],
                    id='print-btn',
                    n_clicks=0,
                    className='btn btn-outline-secondary btn-sm no-print',
                ),
                width='auto',
                className='d-flex align-items-center',
            ),
        ], justify='between', align='center', className='mb-4 no-print'),
        html.Div(id='_print-dummy', style={'display': 'none'}),
        *page_groups,
    ])


# ─── 석세션 데이터 입력(2026-10-07, 사용자 요청) ────────────────────────────────
# 조회 권한과 동일하게 임원조직 담당자(can_view_succession_plan())만 입력할 수
# 있다. 저장 단위는 "부서(현재 소속 기준) × 연도 × 4슬롯"(services/
# succession_store.py의 SLOTS — Ready Now/Ready Later × 1/2순위, 조회 화면이
# 실제로 카드를 그리는 조합과 정확히 같다) — services/succession_store.py
# docstring 참고.

_SLOT_SPECS = [
    ('rn1', 'Ready Now 1순위', 'Ready Now', 1),
    ('rn2', 'Ready Now 2순위', 'Ready Now', 2),
    ('rl1', 'Ready Later 1순위', 'Ready Later', 1),
    ('rl2', 'Ready Later 2순위', 'Ready Later', 2),
]


def _succession_slot_row(slot_key, label):
    return dbc.Row([
        dbc.Col(html.Div(label, className='small fw-bold text-muted'), width=2,
                className='d-flex align-items-center'),
        dbc.Col(
            dcc.Dropdown(id=f'succession-slot-{slot_key}-researcher', options=[],
                         placeholder='연구원 선택(비워두면 해당 순위 없음)', clearable=True),
            width=4,
        ),
        dbc.Col(
            dbc.Textarea(id=f'succession-slot-{slot_key}-comment', placeholder='코멘트(선택)',
                        size='sm', style={'height': '38px', 'resize': 'vertical'}),
            width=6,
        ),
    ], className='mb-2 g-2 align-items-center')


def _succession_edit_panel():
    from services import succession_store
    dept_options = [{'label': d, 'value': d} for d in succession_store.list_departments()]

    return html.Div([
        dbc.Button(
            [html.I(className='bi bi-pencil-square me-1'), '석세션 데이터 입력'],
            id='succession-edit-toggle-btn', color='primary', outline=True, size='sm',
            className='mb-2',
        ),
        dcc.Store(id='succession-edit-refresh-tick', data=0),
        dbc.Collapse(
            dbc.Card(dbc.CardBody([
                html.P(
                    '조회 화면은 각 연구원의 "현재 소속 부서" 기준으로 카드를 그립니다 — '
                    '부서를 고르면 그 부서 소속 연구원 중에서 Ready Now/Ready Later 순위와 '
                    '코멘트를 지정할 수 있습니다.',
                    className='small text-muted',
                ),
                dbc.Row([
                    dbc.Col([
                        dbc.Label('부서', className='small fw-bold'),
                        dcc.Dropdown(id='succession-edit-dept', options=dept_options,
                                     placeholder='부서 선택'),
                    ], md=5),
                    dbc.Col([
                        dbc.Label('연도', className='small fw-bold'),
                        dbc.Input(id='succession-edit-year', type='number',
                                  value=CURRENT_YEAR, placeholder='예: 2026'),
                    ], md=3),
                    dbc.Col([
                        dbc.Label(' ', className='small d-block'),
                        dbc.Button('불러오기', id='succession-edit-load-btn',
                                   color='secondary', outline=True, size='sm'),
                    ], md=2, className='d-flex align-items-end'),
                ], className='g-2 mb-3'),

                *[_succession_slot_row(key, label) for key, label, _, _ in _SLOT_SPECS],

                dbc.Button([html.I(className='bi bi-save me-1'), '저장'],
                           id='succession-edit-save-btn', color='primary', size='sm',
                           className='mt-2'),
                html.Div(id='succession-edit-msg', className='mt-2'),
            ]), className='shadow-sm mb-3'),
            id='succession-edit-collapse', is_open=False,
        ),
    ], className='no-print')


@callback(
    Output('succession-edit-collapse', 'is_open'),
    Input('succession-edit-toggle-btn', 'n_clicks'),
    State('succession-edit-collapse', 'is_open'),
    prevent_initial_call=True,
)
def _toggle_succession_edit(n_clicks, is_open):
    if not n_clicks:
        return no_update
    return not is_open


@callback(
    [Output(f'succession-slot-{key}-researcher', 'options', allow_duplicate=True) for key, _, _, _ in _SLOT_SPECS],
    Input('succession-edit-dept', 'value'),
    prevent_initial_call='initial_duplicate',
)
def _update_succession_slot_options(department):
    from services import succession_store
    options = succession_store.department_researcher_options(department) if department else []
    return [options] * len(_SLOT_SPECS)


@callback(
    [Output(f'succession-slot-{key}-researcher', 'options', allow_duplicate=True) for key, _, _, _ in _SLOT_SPECS]
    + [Output(f'succession-slot-{key}-researcher', 'value') for key, _, _, _ in _SLOT_SPECS]
    + [Output(f'succession-slot-{key}-comment', 'value') for key, _, _, _ in _SLOT_SPECS]
    + [Output('succession-edit-msg', 'children', allow_duplicate=True)],
    Input('succession-edit-load-btn', 'n_clicks'),
    State('succession-edit-dept', 'value'),
    State('succession-edit-year', 'value'),
    prevent_initial_call=True,
)
def _load_succession_slots(n_clicks, department, year):
    """"불러오기" — 값뿐 아니라 각 연구원 드롭다운의 옵션 목록도 이 콜백이
    직접 다시 채운다(departament 변경 시 옵션을 갱신하는
    _update_succession_slot_options()에만 맡기지 않음). 옵션이 비어있는
    상태에서 값만 설정하면 드롭다운이 "목록에 없는 값"으로 보고 조용히
    빈 칸으로 보일 수 있어, 불러오기 한 번으로 옵션+값이 항상 같이
    맞아떨어지도록 한다."""
    from services import succession_store
    from services.auth import can_view_succession_plan
    n = len(_SLOT_SPECS)
    blank = [no_update] * (n * 3)
    if not n_clicks:
        return blank + [no_update]
    if not can_view_succession_plan():
        return blank + [dbc.Alert('임원조직 담당자만 입력할 수 있습니다.', color='danger',
                                   className='py-2 small mb-0')]
    if not department or not year:
        return blank + [dbc.Alert('부서와 연도를 먼저 선택해주세요.', color='warning',
                                   className='py-2 small mb-0')]

    try:
        options = succession_store.department_researcher_options(department)
        option_lists = [options] * n
        slots = succession_store.load_slots(department, year)
        researcher_vals = [slots.get((rt, ro), {}).get('researcher_id') for _, _, rt, ro in _SLOT_SPECS]
        comment_vals = [slots.get((rt, ro), {}).get('comment', '') for _, _, rt, ro in _SLOT_SPECS]

        opt_labels = {o['value']: o['label'] for o in options}
        found_labels = [opt_labels.get(v, v) for v in researcher_vals if v]
        msg = dbc.Alert(
            f'{department} {year}년 — {len(found_labels)}개 순위를 불러왔습니다: '
            + ', '.join(found_labels) if found_labels
            else f'{department} {year}년에 저장된 데이터가 없습니다. 새로 입력할 수 있습니다.',
            color='info', className='py-2 small mb-0',
        )
    except Exception as exc:
        return blank + [dbc.Alert(f'불러오기 중 오류가 발생했습니다: {exc}', color='danger',
                                   className='py-2 small mb-0')]
    return option_lists + researcher_vals + comment_vals + [msg]


@callback(
    Output('succession-edit-msg', 'children', allow_duplicate=True),
    Output('succession-edit-refresh-tick', 'data'),
    Input('succession-edit-save-btn', 'n_clicks'),
    State('succession-edit-dept', 'value'),
    State('succession-edit-year', 'value'),
    State('succession-edit-refresh-tick', 'data'),
    *[State(f'succession-slot-{key}-researcher', 'value') for key, _, _, _ in _SLOT_SPECS],
    *[State(f'succession-slot-{key}-comment', 'value') for key, _, _, _ in _SLOT_SPECS],
    prevent_initial_call=True,
)
def _save_succession_slots(n_clicks, department, year, tick, *slot_values):
    from services import succession_store
    from services.auth import can_view_succession_plan
    if not n_clicks:
        return no_update, no_update
    if not can_view_succession_plan():
        return (dbc.Alert('임원조직 담당자만 입력할 수 있습니다.', color='danger',
                           className='py-2 small mb-0'), no_update)
    if not department or not year:
        return (dbc.Alert('부서와 연도를 먼저 선택해주세요.', color='warning',
                           className='py-2 small mb-0'), no_update)

    n = len(_SLOT_SPECS)
    researcher_values = slot_values[:n]
    comment_values = slot_values[n:]
    assignments = {
        (rt, ro): {'researcher_id': researcher_values[i], 'comment': comment_values[i]}
        for i, (_, _, rt, ro) in enumerate(_SLOT_SPECS)
    }

    # 2026-10-07: 이 콜백이 예상 못 한 예외로 끝까지 못 가면(운영 모드
    # debug=False) Output이 아예 갱신되지 않아 "저장을 눌러도 아무 반응이
    # 없는" 것처럼 보인다(이 저장소에 이미 같은 증상으로 기록된 사례 —
    # JOB Market 2026-08-21 "검색 콜백 전체를 감싸는 최종 안전망" 항목과
    # 동일한 원인·해법). ValueError(부서/연도 누락)만 잡던 좁은 처리를
    # Exception 전체로 넓혀, 원인이 무엇이든 최소한 에러 문구는 항상
    # 화면에 뜨게 한다.
    try:
        result = succession_store.save_slots(department, year, assignments)

        # 저장 직후 실제로 무엇이 반영됐는지 슬롯별로 명시해, 드롭다운
        # 선택이 제대로 안 됐는데 "저장 완료"만 보고 넘어가는 혼란을
        # 막는다(예: 연구원을 못 고른 채 저장하면 그 슬롯은 "(비움)"으로
        # 그대로 표시된다).
        options = succession_store.department_researcher_options(department)
        opt_labels = {o['value']: o['label'] for o in options}
        slot_summary = ', '.join(
            f"{label}: {opt_labels.get(researcher_values[i], researcher_values[i]) if researcher_values[i] else '(비움)'}"
            for i, (_, label, _, _) in enumerate(_SLOT_SPECS)
        )
        # CSV/DB 저장을 서로 독립적으로 시도하므로(services/succession_store.py
        # save_slots() 참고), 어느 한쪽이 실패해도 다른 쪽이 성공했으면 저장은
        # 전체적으로 성공한 것이다 — 실패한 쪽만 괄호로 알려준다.
        caveats = []
        if not result['csv_ok']:
            caveats.append('CSV 파일 저장 실패(권한 문제일 수 있음)')
        if not result['db_ok']:
            caveats.append('DB 미반영')
        caveat_text = f" ({', '.join(caveats)}, 나머지 저장소에는 반영됨)" if caveats else ''
        msg = (
            f"저장 완료 — {department} {year}년 {result['saved_rows']}건 반영"
            f"({result['cleared_rows']}건 교체){caveat_text}. [{slot_summary}]"
        )
    except ValueError as exc:
        return (dbc.Alert(str(exc), color='warning', className='py-2 small mb-0'), no_update)
    except Exception as exc:
        return (dbc.Alert(f'저장 중 오류가 발생했습니다: {exc}', color='danger',
                           className='py-2 small mb-0'), no_update)

    return (dbc.Alert(msg, color='success', dismissable=True, className='py-2 small mb-0'),
            (tick or 0) + 1)


@callback(
    Output('succession-view-content', 'children'),
    Input('succession-edit-refresh-tick', 'data'),
    prevent_initial_call=True,
)
def _refresh_succession_view(_tick):
    try:
        return _render_dashboard()
    except Exception as exc:
        return dbc.Alert(f'조회 화면을 다시 그리는 중 오류가 발생했습니다: {exc}',
                          color='danger', className='mt-3')


def layout():
    if _FEATURE_HIDDEN:
        return dbc.Alert('이 기능은 현재 준비 중입니다.', color='secondary', className='mt-3')
    from services.auth import can_view_succession_plan
    # 메뉴(app.py의 "리포팅" 드롭다운)는 can_view_succession_plan()일 때만
    # 노출되지만, URL(/succession-plan)을 직접 입력하면 메뉴를 거치지 않고도
    # 들어올 수 있어 여기서도 반드시 다시 확인해야 한다(사용자 요청 —
    # "임원조직 담당자만 조회 가능한").
    if not can_view_succession_plan():
        return dbc.Alert('이 페이지는 임원조직 담당자만 조회할 수 있습니다.',
                          color='warning', className='mt-3')
    return html.Div([
        _succession_edit_panel(),
        html.Div(id='succession-view-content', children=_render_dashboard()),
    ])


clientside_callback(
    "function(n) { if (n > 0) { window.print(); } return ''; }",
    Output('_print-dummy', 'children'),
    Input('print-btn', 'n_clicks'),
    prevent_initial_call=True,
)
