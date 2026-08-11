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
from services.data_store import read_processed

dash.register_page(
    __name__,
    path='/researcher-list',
    name='연구원 명단',
    title='연구원 명단',
)

_CURRENT_YEAR = datetime.now().year

# ── 학위 우선순위 ─────────────────────────────────────────────────────────────
_DEGREE_RANK = {'박사': 5, '석사': 4, '학사': 3, '전문대': 2, '고교': 1}


def _build_summary_df() -> pd.DataFrame:
    """CSV들을 집계하여 연구원 1인 1행의 요약 DataFrame 반환."""
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
    if 'year' in eva.columns:
        eva['year'] = pd.to_numeric(eva['year'], errors='coerce')
    if 'year' in inc.columns:
        inc['year'] = pd.to_numeric(inc['year'], errors='coerce')

    rows = []
    for _, r in res.iterrows():
        rid = r['researcher_id']

        # ── 평가 등급 ──────────────────────────────────────────────────────
        ev = eva[eva['researcher_id'] == rid]
        def _grade(yr):
            s = ev[ev['year'] == yr]
            return s.iloc[0]['grade'] if not s.empty else '-'
        g24, g25, g26 = _grade(2024), _grade(2025), _grade(2026)

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

        # ── 학력(최종)/전공 ───────────────────────────────────────────────────
        edu_r = edu[edu['researcher_id'] == rid]
        if not edu_r.empty and 'degree' in edu_r.columns:
            top_edu = edu_r.assign(_rank=edu_r['degree'].map(_DEGREE_RANK).fillna(0)) \
                           .sort_values('_rank').iloc[-1]
            highest = top_edu['degree']
            major = str(top_edu.get('major', '') or '').strip() or '-'
        else:
            highest = '-'
            major = '-'

        rows.append({
            'researcher_id': rid,
            '이름':           str(r.get('name', '')),
            '부서':           str(r.get('department', '')),
            '과제':           str(r.get('org_code', '')),
            '직급':           str(r.get('position', '')),
            '직책':           str(title_by_id.get(rid, '') or '').strip() or '-',
            '성별':           str(r.get('gender', '')),
            '학력(최종)':     highest,
            '전공':           major,
            "'24평가":        g24,
            "'25평가":        g25,
            "'26평가":        g26,
            '인센티브':       inc_cat,
            '논문(전체)':     pub_total,
            '논문(3년)':      pub_3yr,
            '평균IF':         avg_if,
            '특허(출원)':     pat_app,
            '특허(등록)':     pat_reg,
            '수상':           awd_cnt,
        })

    return pd.DataFrame(rows)


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
    for col in ["'24평가", "'25평가", "'26평가"]
    for grade, (bg, fg) in _GRADE_COLOR.items()
]


def layout():
    df = _build_summary_df()

    dept_opts    = _filter_options(df, '부서')
    project_opts = _project_options()
    pos_opts     = _filter_options(df, '직급')
    degree_opts  = _filter_options(df, '학력(최종)')
    inc_opts     = _filter_options(df, '인센티브')

    columns = [
        {'name': col, 'id': col,
         'type': 'numeric' if col in ('논문(전체)', '논문(3년)', '특허(출원)', '특허(등록)', '수상') else 'text'}
        for col in df.columns if col != 'researcher_id'
    ]
    # 평균IF도 혼합값(숫자/'-')이 있어 text로 유지

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
        # 드롭다운 선택 자체는 바로 반영되지 않고, 검색 아이콘을 눌러야 테이블에
        # 적용된다(사용자 확정) — 드롭다운은 filter-*, 검색/엑셀 버튼은 아래
        # 콜백에서 각각 Input/State로 분리해서 처리한다.
        dbc.Card(
            dbc.CardBody(
                dbc.Row([
                    dbc.Col([
                        dbc.Label('부서', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-dept', options=dept_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2),
                    dbc.Col([
                        dbc.Label('과제', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-project', options=project_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2),
                    dbc.Col([
                        dbc.Label('직급', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-pos', options=pos_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2),
                    dbc.Col([
                        dbc.Label('학력(최종)', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-degree', options=degree_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2),
                    dbc.Col([
                        dbc.Label('인센티브', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-incentive', options=inc_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2),
                    dbc.Col([
                        dbc.Label(' ', className='small d-block mb-1'),  # 라벨 줄 높이 맞춤
                        dbc.ButtonGroup([
                            dbc.Button(html.I(className='bi bi-search'), id='list-search-btn',
                                       color='primary', title='검색(필터 적용)'),
                            dbc.Button(html.I(className='bi bi-file-earmark-excel'), id='list-excel-btn',
                                       color='success', title='엑셀 다운로드(현재 화면에 보이는 대상)'),
                        ], className='w-100'),
                        dbc.Checklist(
                            id='list-excel-options-check',
                            options=[
                                {'label': '보유 전문성 포함', 'value': 'expertise'},
                                {'label': '특허 포함', 'value': 'patents'},
                                {'label': '논문 포함', 'value': 'publications'},
                            ],
                            value=[], switch=True,
                            className='small mt-1',
                        ),
                    ], md=2),
                ], className='g-3'),
            ),
            className='mb-3 shadow-sm',
        ),

        # ── DataTable ─────────────────────────────────────────────────────
        dbc.Card(
            dbc.CardBody(
                dash_table.DataTable(
                    id='researcher-table',
                    columns=columns,
                    data=df.to_dict('records') if not df.empty else [],
                    # 필터 / 정렬
                    filter_action='native',
                    sort_action='native',
                    sort_mode='multi',
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
                    style_data_conditional=_GRADE_STYLES + [
                        {'if': {'row_index': 'odd'}, 'backgroundColor': '#f9fbfd'},
                        {'if': {'state': 'active'}, 'backgroundColor': '#dbeafe',
                         'border': '1px solid #3b82f6'},
                    ],
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


# ── 콜백 2: 검색 버튼(필터 적용) / 필터 초기화 버튼 → 테이블 데이터 갱신 ──────
# 드롭다운 값은 State로만 읽는다 — 선택하는 즉시가 아니라 검색 아이콘을 눌러야
# 테이블에 반영된다(사용자 확정). 필터 초기화 버튼은 이 콜백에도 함께 연결해,
# 눌렀을 때 드롭다운 값과 무관하게 항상 전체 목록으로 되돌아가게 한다.
@callback(
    Output('researcher-table', 'data'),
    Input('list-search-btn',   'n_clicks'),
    Input('clear-filters-btn', 'n_clicks'),
    State('filter-dept',      'value'),
    State('filter-project',   'value'),
    State('filter-pos',       'value'),
    State('filter-degree',    'value'),
    State('filter-incentive', 'value'),
    prevent_initial_call=True,
)
def update_table(_search_clicks, _clear_clicks, dept, project, pos, degree, incentive):
    df = _build_summary_df()
    if df.empty:
        return []
    if dash.ctx.triggered_id == 'clear-filters-btn':
        return df.to_dict('records')
    if dept:
        df = df[df['부서'].isin(dept)]
    if project:
        df = df[df['과제'].isin(project)]
    if pos:
        df = df[df['직급'].isin(pos)]
    if degree:
        df = df[df['학력(최종)'].isin(degree)]
    if incentive:
        df = df[df['인센티브'].isin(incentive)]
    return df.to_dict('records')


# ── 콜백 3: 필터 초기화 버튼 → 드롭다운 값 비우기 ────────────────────────────
@callback(
    Output('filter-dept',      'value'),
    Output('filter-project',   'value'),
    Output('filter-pos',       'value'),
    Output('filter-degree',    'value'),
    Output('filter-incentive', 'value'),
    Input('clear-filters-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def clear_filters(_):
    return None, None, None, None, None


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
    return f'/researcher-profile?id={rid}'
