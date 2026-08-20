"""
화면 3: 연구원 명단 (정량 지표 테이블)
"""

from datetime import datetime
from urllib.parse import parse_qs

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, dash_table, dcc, html, no_update

from components.timeline_data import dedupe_patents
from services import researcher_profile_export
from services.data_store import filter_current, read_processed
from services.evaluations import evaluation_years, salary_grade_column

dash.register_page(
    __name__,
    path='/researcher-list',
    name='연구원 명단',
    title='연구원 명단',
)

_CURRENT_YEAR = datetime.now().year

# 평가등급 컬럼("'24평가" 등)의 연도 — evaluations.csv와 동일한 회계연도
# 기준(매년 3월 시작, services.evaluations)으로 오름차순(과거→최신) 계산.
_EVAL_SALARY_YEARS = sorted(evaluation_years()[0])
_EVAL_GRADE_COLUMNS = [f"'{str(y)[-2:]}평가" for y in _EVAL_SALARY_YEARS]
_INCENTIVE_COL = '인센티브'

# ── 학위 우선순위 ─────────────────────────────────────────────────────────────
_DEGREE_RANK = {'박사': 5, '석사': 4, '학사': 3, '전문대': 2, '고교': 1}


def _build_summary_df(current_only: bool = True) -> pd.DataFrame:
    """CSV들을 집계하여 연구원 1인 1행의 요약 DataFrame 반환.
    current_only=False(누적기준)면 전배·퇴사 등으로 최신 인력현황에 없는
    사람도 포함하고, 그 경우에만 '현재소속' 열을 추가로 붙인다(최신기준에서는
    전원이 '현재'라 의미가 없어 열 자체를 안 만든다)."""
    try:
        res  = read_processed('researchers')
        eva  = read_processed('evaluations')
        pub  = read_processed('publications')
        pat  = read_processed('patents')
        awd  = read_processed('awards')
        edu  = read_processed('education')
        inc  = read_processed('incentive_selection')
        team = read_processed('team_refer')
    except Exception:
        return pd.DataFrame()

    res = filter_current(res, current_only)

    # 직책 = team_refer.csv의 assignment_name(researcher_id 기준, 조직장급만
    # 등록돼 있어 나머지는 매핑이 없음 — 그 경우 "-").
    title_by_id = (
        dict(zip(team['researcher_id'], team['assignment_name']))
        if not team.empty and {'researcher_id', 'assignment_name'} <= set(team.columns) else {}
    )

    # 숫자 변환
    for col in ['pub_year', 'impact_factor', 'citation_count', 'contribution']:
        if col in pub.columns:
            pub[col] = pd.to_numeric(pub[col], errors='coerce')
    # pub_year가 없으면 pub_date 앞 4자리에서 파생
    if 'pub_year' not in pub.columns and 'pub_date' in pub.columns:
        pub['pub_year'] = pd.to_numeric(pub['pub_date'].str[:4], errors='coerce')
    if 'year' in inc.columns:
        inc['year'] = pd.to_numeric(inc['year'], errors='coerce')

    rows = []
    for _, r in res.iterrows():
        rid = r['researcher_id']

        # ── 평가 등급(연봉등급만 — 상/하반기업적은 이 표에 넣지 않음) ────────
        ev_rows = eva[eva['researcher_id'] == rid]
        ev = ev_rows.iloc[0] if not ev_rows.empty else None
        def _grade(yr):
            if ev is None:
                return '-'
            val = str(ev.get(salary_grade_column(yr), '') or '').strip()
            return val if val and val.lower() != 'nan' else '-'
        grades = {col: _grade(yr) for col, yr in zip(_EVAL_GRADE_COLUMNS, _EVAL_SALARY_YEARS)}

        # ── 인센티브 ───────────────────────────────────────────────────────
        sel = inc[inc['researcher_id'] == rid]
        # selected 열이 문자열일 수 있으므로 유연하게 처리
        if not sel.empty and 'selected' in sel.columns:
            sel_true = sel[sel['selected'].astype(str).str.lower().isin(['true', '1', 'yes'])]
        else:
            sel_true = pd.DataFrame()
        if not sel_true.empty:
            latest_inc = sel_true.sort_values('year').iloc[-1]
            inc_cat = str(latest_inc.get('category', '')).strip() or '-'
        else:
            inc_cat = '-'

        # ── 논문 ───────────────────────────────────────────────────────────
        pubs = pub[pub['researcher_id'] == rid]
        pub_total  = len(pubs)
        pub_3yr    = int((pubs['pub_year'] >= _CURRENT_YEAR - 2).sum()) if not pubs.empty and 'pub_year' in pubs.columns else 0
        avg_if     = round(pubs['impact_factor'].mean(), 2) if not pubs.empty and 'impact_factor' in pubs.columns and pubs['impact_factor'].notna().any() else '-'

        # ── 특허 ───────────────────────────────────────────────────────────
        # 타임라인과 동일하게 application_id 기준으로 중복(공동발명자 등) 제거 후 집계
        pats = pat[pat['researcher_id'] == rid]
        pats_dedup = dedupe_patents(pats) if not pats.empty else pats
        pat_app = int((pats_dedup['status'] == '출원').sum()) if not pats_dedup.empty else 0
        pat_reg = int((pats_dedup['status'] == '등록').sum()) if not pats_dedup.empty else 0

        # ── 수상 ───────────────────────────────────────────────────────────
        awd_cnt = len(awd[awd['researcher_id'] == rid])

        # ── 학력/전공 ───────────────────────────────────────────────────
        edu_r = edu[edu['researcher_id'] == rid]
        if not edu_r.empty and 'degree' in edu_r.columns:
            top_edu = edu_r.assign(_rank=edu_r['degree'].map(_DEGREE_RANK).fillna(0)) \
                           .sort_values('_rank').iloc[-1]
            highest = top_edu['degree']
            major = str(top_edu.get('major', '') or '').strip() or '-'
        else:
            highest = '-'
            major = '-'

        row = {
            'researcher_id': rid,
            '이름':           str(r.get('name', '')),
            '부서':           str(r.get('department', '')),
            '과제':           str(r.get('org_code', '')),
            '직급':           str(r.get('position', '')),
            '직책':           str(title_by_id.get(rid, '') or '').strip() or '-',
            '성별':           str(r.get('gender', '')),
            '재직상태':       str(r.get('employment_status', '') or '').strip() or '-',
            '학력':           highest,
            '전공':           major,
            **grades,
            _INCENTIVE_COL:   inc_cat,
            '논문(전체)':     pub_total,
            '논문(3년)':      pub_3yr,
            '평균IF':         avg_if,
            '특허(출원)':     pat_app,
            '특허(등록)':     pat_reg,
            '수상':           awd_cnt,
        }
        if not current_only:
            row['현재소속'] = '미소속' if str(r.get('is_current', 'Y')) == 'N' else '현재'
        rows.append(row)

    return pd.DataFrame(rows)


def _apply_permission_filter(df: pd.DataFrame, show_eval: bool, show_incentive: bool) -> pd.DataFrame:
    """평가/인센티브 열람 권한이 없으면 해당 컬럼을 통째로 제거한다."""
    drop = []
    if not show_eval:
        drop.extend(_EVAL_GRADE_COLUMNS)
    if not show_incentive:
        drop.append(_INCENTIVE_COL)
    if not drop:
        return df
    return df.drop(columns=[c for c in drop if c in df.columns])


def _filter_options(df: pd.DataFrame, col: str) -> list:
    if df.empty or col not in df.columns:
        return []
    vals = sorted(df[col].dropna().unique())
    return [{'label': v, 'value': v} for v in vals if str(v).strip()]


def _project_options(department=None) -> list:
    """과제(=researchers.csv의 org_code) 드롭다운 옵션. 부서를 지정하면 그
    부서 소속 연구원들의 org_code만 남긴다 — 이 페이지 자체 데이터만으로
    캐스케이딩을 구성한다(project_confl_address.csv의 dep_name 표기와 이
    페이지의 '부서'(researchers.csv department) 표기가 항상 일치한다는
    보장이 없어, 다른 화면의 과제 카탈로그와는 별도로 자기완결적으로 둔다)."""
    researchers = read_processed('researchers')
    if researchers.empty or 'org_code' not in researchers.columns:
        return []
    df = researchers
    if department:
        depts = {department} if isinstance(department, str) else {str(d) for d in department}
        df = df[df['department'].astype(str).isin(depts)]
    vals = sorted({str(v).strip() for v in df['org_code'] if str(v).strip()})
    return [{'label': v, 'value': v} for v in vals]


# ── 조건부 스타일 (평가등급 색상) ─────────────────────────────────────────────
_GRADE_COLOR = {
    '가': ('#d4edda', '#155724'),
    '나': ('#d1ecf1', '#0c5460'),
    '다': ('#fff3cd', '#856404'),
    '라': ('#fde8d8', '#7d3c00'),
    '마': ('#f8d7da', '#721c24'),
}
_GRADE_STYLES = [
    {'if': {'filter_query': f'{{{col}}} = {grade}', 'column_id': col},
     'backgroundColor': bg, 'color': fg}
    for col in _EVAL_GRADE_COLUMNS
    for grade, (bg, fg) in _GRADE_COLOR.items()
]


def _build_columns(df: pd.DataFrame) -> list:
    return [
        {'name': col, 'id': col,
         'type': 'numeric' if col in ('논문(전체)', '논문(3년)', '특허(출원)', '특허(등록)', '수상') else 'text'}
        for col in df.columns if col != 'researcher_id'
    ]
    # 평균IF도 혼합값(숫자/'-')이 있어 text로 유지


def layout():
    from services.auth import can
    show_eval = can('view_evaluation')
    show_incentive = can('view_incentive')

    df = _build_summary_df(current_only=True)
    display_df = _apply_permission_filter(df, show_eval, show_incentive)

    dept_opts     = _filter_options(df, '부서')
    project_opts  = _project_options()
    pos_opts      = _filter_options(df, '직급')
    title_opts    = _filter_options(df, '직책')
    gender_opts   = _filter_options(df, '성별')
    degree_opts   = _filter_options(df, '학력')
    major_opts    = _filter_options(df, '전공')
    employ_opts   = _filter_options(df, '재직상태')

    columns = _build_columns(display_df)
    grade_styles = _GRADE_STYLES if show_eval else []

    return html.Div([
        dcc.Location(id='list-url', refresh=True),
        dcc.Download(id='researcher-list-excel-download'),

        dbc.Row([
            dbc.Col(
                html.H5([html.I(className='bi bi-table me-2 text-primary'), '연구원 명단'],
                        className='fw-bold mb-0 mt-1'),
                className='d-flex align-items-center',
            ),
            dbc.Col(
                dbc.Button('필터 초기화', id='clear-filters-btn', color='secondary',
                           size='sm', outline=True, className='float-end'),
                className='d-flex align-items-center justify-content-end',
            ),
        ], className='mb-3'),

        # ── 상단 드롭다운 필터 ─────────────────────────────────────────────
        # 드롭다운 선택 자체는 바로 반영되지 않고, 검색 아이콘(또는 상세 필터
        # 모달의 '적용')을 눌러야 테이블에 적용된다(사용자 확정) — 드롭다운은
        # filter-*, 검색/엑셀 버튼은 아래 콜백에서 각각 Input/State로 분리해서
        # 처리한다. 자주 쓰는 부서/과제만 메인 화면에 남기고, 직급/직책/성별/
        # 학력/전공/재직상태는 화면이 복잡해지지 않도록 '필터' 모달로 옮겼다
        # (사용자 요청).
        dbc.Card(
            dbc.CardBody(
                dbc.Row([
                    dbc.Col([
                        dbc.Label('검색 기준', className='small fw-semibold text-muted mb-1'),
                        dbc.RadioItems(
                            id='list-search-mode',
                            options=[
                                {'label': '최신기준', 'value': 'current'},
                                {'label': '누적기준', 'value': 'all'},
                            ],
                            value='current',
                            inline=True,
                            className='small',
                        ),
                        html.Div(
                            '누적기준: 이름/사번 검색 중심 (부서·과제·직급·직책 필터 비활성화)',
                            className='text-muted', style={'fontSize': '0.72rem'},
                        ),
                    ], md=3),
                    dbc.Col([
                        dbc.Label('부서', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-dept', options=dept_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=3),
                    dbc.Col([
                        dbc.Label('과제', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-project', options=project_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=3),
                    dbc.Col([
                        dbc.Label(' ', className='small d-block mb-1'),  # 라벨 줄 높이 맞춤
                        dbc.ButtonGroup([
                            dbc.Button([html.I(className='bi bi-funnel me-1'), '필터'],
                                       id='open-filter-btn', color='secondary', outline=True,
                                       title='상세 필터(직급/직책/성별/학력/전공/재직상태)'),
                            dbc.Button(html.I(className='bi bi-search'), id='list-search-btn',
                                       color='primary', title='검색(필터 적용)'),
                            dbc.Button(html.I(className='bi bi-file-earmark-excel'), id='list-excel-btn',
                                       color='success', title='엑셀 다운로드(현재 화면에 보이는 대상)'),
                            dbc.Button(html.I(className='bi bi-printer'), id='list-bulk-print-btn',
                                       color='info',
                                       title='프로필 일괄 인쇄(체크한 사람, 없으면 현재 화면에 보이는 전체)'),
                        ], className='w-100'),
                        dbc.Checklist(
                            id='list-excel-options-check',
                            options=[
                                {'label': '보유 전문성 포함', 'value': 'expertise'},
                                {'label': '특허 포함', 'value': 'patents'},
                                {'label': '논문 포함', 'value': 'publications'},
                                {'label': '직무 포함', 'value': 'job_function'},
                                {'label': '직무이력 포함', 'value': 'job_profile'},
                                {'label': '재직상태 포함', 'value': 'employment_status'},
                            ],
                            value=[], switch=True,
                            className='small mt-1',
                        ),
                        html.Div(
                            '프로필 인쇄: 표에서 원하는 행을 체크하면 그 인원만, '
                            '체크가 없으면 현재 필터·검색 결과 전체를 인쇄합니다(과제/부서로 '
                            '필터해두면 그 풀 전체를 한 번에 인쇄할 수 있습니다).',
                            className='text-muted mt-1', style={'fontSize': '0.72rem'},
                        ),
                    ], md=3),
                ], className='g-3'),
            ),
            className='mb-3 shadow-sm',
        ),

        # ── 상세 필터 모달 ────────────────────────────────────────────────
        # 메인 화면에서 뺀 직급/직책/성별/학력/전공/재직상태를 별도 창(모달)
        # 으로 열어 선택한다(사용자 요청). '과제'는 메인 화면에 이미 있어
        # 중복 배치하지 않았다.
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle('상세 필터')),
                dbc.ModalBody(
                    dbc.Row([
                        dbc.Col([
                            dbc.Label('직급', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-pos', options=pos_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('직책', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-title', options=title_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('성별', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-gender', options=gender_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('학력', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-degree', options=degree_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('전공', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-major', options=major_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('재직상태', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-employment', options=employ_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                    ], className='g-2'),
                ),
                dbc.ModalFooter([
                    dbc.Button('초기화', id='filter-modal-clear-btn', color='secondary', outline=True, size='sm'),
                    dbc.Button('적용', id='filter-modal-apply-btn', color='primary', size='sm'),
                ]),
            ],
            id='filter-modal', is_open=False,
        ),

        # ── DataTable ─────────────────────────────────────────────────────
        dbc.Card(
            dbc.CardBody(
                dash_table.DataTable(
                    id='researcher-table',
                    columns=columns,
                    data=display_df.to_dict('records') if not display_df.empty else [],
                    # 필터 / 정렬
                    filter_action='native',
                    sort_action='native',
                    sort_mode='multi',
                    # 행 체크박스(프로필 일괄 인쇄용 — 없으면 화면에 보이는 전체를 인쇄)
                    row_selectable='multi',
                    selected_rows=[],
                    # 페이지
                    page_action='native',
                    page_size=30,
                    # 스타일
                    style_as_list_view=True,
                    style_table={'overflowX': 'auto'},
                    style_header={
                        'backgroundColor': '#1e3a5f',
                        'color': 'white',
                        'fontWeight': '600',
                        'fontSize': '0.8rem',
                        'textAlign': 'center',
                        'whiteSpace': 'normal',
                    },
                    style_filter={
                        'backgroundColor': '#f0f4f8',
                        'fontSize': '0.75rem',
                    },
                    style_cell={
                        'fontSize': '0.82rem',
                        'padding': '5px 10px',
                        'textAlign': 'center',
                        'minWidth': '55px',
                        'maxWidth': '160px',
                        'overflow': 'hidden',
                        'textOverflow': 'ellipsis',
                    },
                    style_cell_conditional=[
                        {'if': {'column_id': '이름'}, 'textAlign': 'left', 'minWidth': '80px',
                         'fontWeight': '600', 'cursor': 'pointer', 'color': '#1e3a5f'},
                        {'if': {'column_id': '부서'}, 'textAlign': 'left', 'minWidth': '100px'},
                        {'if': {'column_id': '과제'}, 'textAlign': 'left', 'minWidth': '100px'},
                    ],
                    # 순서 중요: style_data_conditional은 뒤에 오는 규칙이 같은 셀의
                    # 같은 속성을 덮어쓴다(나중에 매치되는 규칙이 우선) — 홀수행
                    # 줄무늬(row_index: 'odd')가 열 지정 없이 모든 셀에 적용되므로,
                    # grade_styles(평가등급 색상, 특정 열만 대상)보다 먼저 와야
                    # 홀수행에서도 등급 색이 줄무늬 배경에 덮이지 않고 살아남는다.
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#f9fbfd'},
                        {'if': {'state': 'active'}, 'backgroundColor': '#dbeafe',
                         'border': '1px solid #3b82f6'},
                    ] + grade_styles,
                    tooltip_header={col['id']: col['id'] for col in columns},
                    tooltip_delay=0,
                    tooltip_duration=None,
                ),
                className='p-0',
            ),
            className='shadow-sm',
        ),

        html.P(
            '행을 클릭하면 해당 연구원의 개별 프로필 화면으로 이동합니다.',
            className='text-muted small mt-2 mb-0',
        ),
    ])


# ── 콜백 1: 부서 선택 → 과제 드롭다운 옵션 캐스케이딩 ─────────────────────────
@callback(
    Output('filter-project', 'options'),
    Input('filter-dept', 'value'),
)
def update_project_options(dept):
    return _project_options(dept)


# ── 콜백 1-1: 검색 기준(현재/누적) → 부서·과제·직급·직책 필터 비활성화 ─────────
# 누적기준에서는 조직 배치(부서/과제/직급/직책)가 최신 시점 기준이 아닐 수 있어
# 혼란을 줄 수 있으므로 비활성화하고 값도 비운다 — 이름/사번(테이블 자체
# 필터 행)으로만 찾도록 유도한다. 성별/학력/전공/재직상태는 시점에 덜
# 민감해 그대로 둔다.
@callback(
    Output('filter-dept', 'disabled'),
    Output('filter-project', 'disabled'),
    Output('filter-pos', 'disabled'),
    Output('filter-title', 'disabled'),
    Output('filter-dept', 'value', allow_duplicate=True),
    Output('filter-project', 'value', allow_duplicate=True),
    Output('filter-pos', 'value', allow_duplicate=True),
    Output('filter-title', 'value', allow_duplicate=True),
    Input('list-search-mode', 'value'),
    prevent_initial_call=True,
)
def toggle_org_filters(mode):
    is_cumulative = (mode == 'all')
    if is_cumulative:
        return True, True, True, True, None, None, None, None
    return False, False, False, False, no_update, no_update, no_update, no_update


# ── 콜백 2: 검색 버튼(필터 적용) / 필터 초기화 버튼 → 테이블 데이터 갱신 ──────
# 드롭다운 값은 State로만 읽는다 — 선택하는 즉시가 아니라 검색 아이콘을 눌러야
# 테이블에 반영된다(사용자 확정). 필터 초기화 버튼은 이 콜백에도 함께 연결해,
# 눌렀을 때 드롭다운 값과 무관하게 항상 전체 목록으로 되돌아가게 한다.
@callback(
    Output('researcher-table', 'data'),
    Output('researcher-table', 'columns'),
    Output('researcher-table', 'tooltip_header'),
    Output('researcher-table', 'selected_rows'),
    Input('list-search-btn',   'n_clicks'),
    Input('filter-modal-apply-btn', 'n_clicks'),
    Input('clear-filters-btn', 'n_clicks'),
    Input('list-search-mode',  'value'),
    State('filter-dept',       'value'),
    State('filter-project',    'value'),
    State('filter-pos',        'value'),
    State('filter-title',      'value'),
    State('filter-gender',     'value'),
    State('filter-degree',     'value'),
    State('filter-major',      'value'),
    State('filter-employment', 'value'),
    prevent_initial_call=True,
)
def update_table(_search_clicks, _apply_clicks, _clear_clicks, mode, dept, project, pos, title,
                  gender, degree, major, employment):
    from services.auth import can
    show_eval = can('view_evaluation')
    show_incentive = can('view_incentive')

    current_only = (mode != 'all')
    df = _build_summary_df(current_only=current_only)
    display_df = _apply_permission_filter(df, show_eval, show_incentive)
    columns = _build_columns(display_df)
    tooltip_header = {c['id']: c['id'] for c in columns}
    if display_df.empty:
        return [], columns, tooltip_header, []

    triggered = dash.ctx.triggered_id
    # 모드 전환 자체가 트리거면(부서/과제/직급/직책 필터가 비활성화·초기화되는
    # 시점과 겹칠 수 있어) 조직 필터는 적용하지 않고 전체(해당 모드) 목록을 보여준다.
    if triggered in ('clear-filters-btn', 'list-search-mode'):
        return display_df.to_dict('records'), columns, tooltip_header, []

    if dept and current_only:
        display_df = display_df[display_df['부서'].isin(dept)]
    if project and current_only:
        display_df = display_df[display_df['과제'].isin(project)]
    if pos and current_only:
        display_df = display_df[display_df['직급'].isin(pos)]
    if title and current_only:
        display_df = display_df[display_df['직책'].isin(title)]
    if gender:
        display_df = display_df[display_df['성별'].isin(gender)]
    if degree:
        display_df = display_df[display_df['학력'].isin(degree)]
    if major:
        display_df = display_df[display_df['전공'].isin(major)]
    if employment:
        display_df = display_df[display_df['재직상태'].isin(employment)]
    return display_df.to_dict('records'), columns, tooltip_header, []


# ── 콜백 3: 필터 초기화 버튼 → 드롭다운 값 비우기(메인 화면 + 필터 모달) ─────
@callback(
    Output('filter-dept',       'value'),
    Output('filter-project',    'value'),
    Output('filter-pos',        'value'),
    Output('filter-title',      'value'),
    Output('filter-gender',     'value'),
    Output('filter-degree',     'value'),
    Output('filter-major',      'value'),
    Output('filter-employment', 'value'),
    Input('clear-filters-btn', 'n_clicks'),
    Input('filter-modal-clear-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def clear_filters(_clear_clicks, _modal_clear_clicks):
    return None, None, None, None, None, None, None, None


# ── 콜백 3-1: '필터' 버튼 → 상세 필터 모달 열기/닫기 ──────────────────────────
# 열기는 '필터' 버튼만, 닫기는 모달의 '적용'/'닫기'(X) 버튼 모두에 반응한다.
@callback(
    Output('filter-modal', 'is_open'),
    Input('open-filter-btn', 'n_clicks'),
    Input('filter-modal-apply-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def toggle_filter_modal(_open_clicks, _apply_clicks):
    return dash.ctx.triggered_id == 'open-filter-btn'


# ── 콜백 4: 엑셀 다운로드 — 지금 화면에 실제로 보이는(검색 필터 + 표 자체
# 열별 필터/정렬까지 반영된) 대상자들의 프로필을 다운로드 ───────────────────
@callback(
    Output('researcher-list-excel-download', 'data'),
    Input('list-excel-btn', 'n_clicks'),
    State('researcher-table', 'derived_virtual_data'),
    State('list-excel-options-check', 'value'),
    prevent_initial_call=True,
)
def download_excel(n_clicks, virtual_data, excel_options):
    if not n_clicks or not virtual_data:
        return no_update
    researcher_ids = [row['researcher_id'] for row in virtual_data if row.get('researcher_id')]
    if not researcher_ids:
        return no_update
    excel_options = excel_options or []
    data = researcher_profile_export.build_profile_workbook(
        researcher_ids,
        include_expertise='expertise' in excel_options,
        include_patents='patents' in excel_options,
        include_publications='publications' in excel_options,
        include_job_function='job_function' in excel_options,
        include_job_profile='job_profile' in excel_options,
        include_employment_status='employment_status' in excel_options,
    )
    return dcc.send_bytes(data, researcher_profile_export.default_filename())


# ── 콜백 5: 행 클릭 → 프로필 화면 이동 ──────────────────────────────────────
@callback(
    Output('list-url', 'href'),
    Input('researcher-table', 'active_cell'),
    State('researcher-table', 'derived_virtual_data'),
    prevent_initial_call=True,
)
def navigate_to_profile(active_cell, virtual_data):
    if not active_cell or not virtual_data:
        return no_update
    row_idx = active_cell.get('row')
    if row_idx is None or row_idx >= len(virtual_data):
        return no_update
    rid = virtual_data[row_idx].get('researcher_id')
    if not rid:
        return no_update
    return f'/?id={rid}'


# ── 콜백 6: 프로필 일괄 인쇄 버튼 → 여러 명 인쇄 화면으로 이동 ────────────────
# 체크한 행이 있으면 그 사람들만, 없으면 지금 화면에 보이는(검색 필터 +
# 표 자체 열별 필터/정렬까지 반영된, 엑셀 다운로드와 동일한 기준) 전체를
# 대상으로 삼는다 — 과제/부서로 필터해두고 그냥 누르면 그 풀 전체가,
# 체크박스로 일부만 고르면 그 인원만 인쇄 화면(/?ids=...)으로 넘어간다.
@callback(
    Output('list-url', 'href', allow_duplicate=True),
    Input('list-bulk-print-btn', 'n_clicks'),
    State('researcher-table', 'derived_virtual_data'),
    State('researcher-table', 'selected_rows'),
    prevent_initial_call=True,
)
def bulk_print_navigate(n_clicks, virtual_data, selected_rows):
    if not n_clicks or not virtual_data:
        return no_update
    if selected_rows:
        rows = [virtual_data[i] for i in selected_rows if i < len(virtual_data)]
    else:
        rows = virtual_data
    researcher_ids = [row['researcher_id'] for row in rows if row.get('researcher_id')]
    if not researcher_ids:
        return no_update
    return '/?ids=' + ','.join(researcher_ids)
