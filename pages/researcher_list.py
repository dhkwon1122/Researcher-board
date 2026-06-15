"""
화면 3: 연구원 목록 (정량 지표 테이블)
"""

from datetime import datetime
from urllib.parse import parse_qs

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, dash_table, dcc, html, no_update

from components.detail_tabs import _is_registered
from services.data_store import read_processed
from services.db import db_enabled
from services.text2sql import run_query

dash.register_page(
    __name__,
    path='/researcher-list',
    name='연구원 목록',
    title='연구원 목록',
)

_CURRENT_YEAR = datetime.now().year

_DEGREE_RANK = {'박사': 5, '석사': 4, '학사': 3, '전문대': 2, '고교': 1}
_LEA_DIMS = ['미래통찰', '성과창출', '몰입촉진', '인재육성', '자기관리']

# 평가 관련 컬럼 (권한 없으면 제외)
_EVAL_COLS = ["'24평가", "'25평가", "'26평가"]
_INCENTIVE_COL = '인센티브'


def _build_summary_df() -> pd.DataFrame:
    """CSV들을 집계하여 연구원 1인 1행의 요약 DataFrame 반환."""
    try:
        res  = read_processed('researchers')
        eva  = read_processed('evaluations')
        pub  = read_processed('publications')
        pat  = read_processed('patents')
        lea  = read_processed('leadership')
        cert = read_processed('certifications')
        awd  = read_processed('awards')
        edu  = read_processed('education')
        inc  = read_processed('incentive_selection')
    except Exception:
        return pd.DataFrame()

    for col in ['pub_year', 'impact_factor', 'citation_count', 'contribution']:
        if col in pub.columns:
            pub[col] = pd.to_numeric(pub[col], errors='coerce')
    if 'pub_year' not in pub.columns and 'pub_date' in pub.columns:
        pub['pub_year'] = pd.to_numeric(pub['pub_date'].str[:4], errors='coerce')
    for col in _LEA_DIMS + ['overall_score']:
        if col in lea.columns:
            lea[col] = pd.to_numeric(lea[col], errors='coerce')
    if 'score' in cert.columns:
        cert['score'] = pd.to_numeric(cert['score'], errors='coerce')
    if 'year' in eva.columns:
        eva['year'] = pd.to_numeric(eva['year'], errors='coerce')
    if 'year' in inc.columns:
        inc['year'] = pd.to_numeric(inc['year'], errors='coerce')

    rows = []
    for _, r in res.iterrows():
        rid = r['researcher_id']

        ev = eva[eva['researcher_id'] == rid]
        def _grade(yr):
            s = ev[ev['year'] == yr]
            return s.iloc[0]['grade'] if not s.empty else '-'
        g24, g25, g26 = _grade(2024), _grade(2025), _grade(2026)

        sel = inc[inc['researcher_id'] == rid]
        if not sel.empty and 'selected' in sel.columns:
            sel_true = sel[sel['selected'].astype(str).str.lower().isin(['true', '1', 'yes'])]
        else:
            sel_true = pd.DataFrame()
        if not sel_true.empty:
            latest_inc = sel_true.sort_values('year').iloc[-1]
            inc_cat = str(latest_inc.get('category', '')).strip() or '-'
        else:
            inc_cat = '-'

        pubs = pub[pub['researcher_id'] == rid]
        pub_total  = len(pubs)
        pub_3yr    = int((pubs['pub_year'] >= _CURRENT_YEAR - 2).sum()) if not pubs.empty and 'pub_year' in pubs.columns else 0
        avg_if     = round(pubs['impact_factor'].mean(), 2) if not pubs.empty and 'impact_factor' in pubs.columns and pubs['impact_factor'].notna().any() else '-'

        # ── 특허 (프로필 상세와 동일 기준) ─────────────────────────────────
        #   출원 = 특허 수(application_id 기준 중복 제거), 등록 = status 에 '등록' 포함
        pats = pat[pat['researcher_id'] == rid]
        if pats.empty:
            pat_app = pat_reg = 0
        elif 'application_id' in pats.columns:
            grp = pats.groupby('application_id')
            pat_app = grp.ngroups
            pat_reg = (int(grp['status'].apply(
                lambda s: s.apply(_is_registered).any()).sum())
                if 'status' in pats.columns else 0)
        else:
            pat_app = len(pats)
            pat_reg = (int(pats['status'].apply(_is_registered).sum())
                       if 'status' in pats.columns else 0)

        ldf = lea[(lea['researcher_id'] == rid)]
        grp_col = 'evaluator_group' if 'evaluator_group' in ldf.columns else None
        if grp_col:
            ldf = ldf[ldf[grp_col] == '타인평균']
        if not ldf.empty:
            if 'year' in ldf.columns:
                ldf = ldf.sort_values('year')
            latest_lea = ldf.iloc[-1]
            if 'overall_score' in latest_lea and pd.notna(latest_lea['overall_score']):
                lea_score = round(float(latest_lea['overall_score']), 1)
            else:
                dims_vals = [latest_lea[d] for d in _LEA_DIMS if d in latest_lea and pd.notna(latest_lea[d])]
                lea_score = round(sum(dims_vals) / len(dims_vals), 1) if dims_vals else '-'
        else:
            lea_score = '-'

        toeic = cert[(cert['researcher_id'] == rid) & (cert['cert_name'] == 'TOEIC')]
        if not toeic.empty and 'score' in toeic.columns:
            valid = toeic[toeic['score'].notna()]
            toeic_score = int(valid.sort_values('date_obtained').iloc[-1]['score']) if not valid.empty else '-'
        else:
            toeic_score = '-'

        awd_cnt = len(awd[awd['researcher_id'] == rid])

        edu_r = edu[edu['researcher_id'] == rid]
        if not edu_r.empty and 'degree' in edu_r.columns:
            highest = edu_r.assign(_rank=edu_r['degree'].map(_DEGREE_RANK).fillna(0)) \
                           .sort_values('_rank').iloc[-1]['degree']
        else:
            highest = '-'

        rows.append({
            'researcher_id': rid,
            '이름':           str(r.get('name', '')),
            '부서':           str(r.get('department', '')),
            '직급':           str(r.get('position', '')),
            '성별':           str(r.get('gender', '')),
            '최종학위':       highest,
            "'24평가":        g24,
            "'25평가":        g25,
            "'26평가":        g26,
            '인센티브':       inc_cat,
            '논문(전체)':     pub_total,
            '논문(3년)':      pub_3yr,
            '평균IF':         avg_if,
            '특허(출원)':     pat_app,
            '특허(등록)':     pat_reg,
            '리더십':         lea_score,
            'TOEIC':          toeic_score,
            '수상':           awd_cnt,
        })

    return pd.DataFrame(rows)


def _filter_options(df: pd.DataFrame, col: str) -> list:
    if df.empty or col not in df.columns:
        return []
    vals = sorted(df[col].dropna().unique())
    return [{'label': v, 'value': v} for v in vals if str(v).strip()]


def _build_display_df(df: pd.DataFrame, show_eval: bool, show_incentive: bool) -> pd.DataFrame:
    """권한에 따라 제한 컬럼을 제거한 DataFrame 반환."""
    drop = ['researcher_id']
    if not show_eval:
        drop.extend(_EVAL_COLS)
    if not show_incentive:
        drop.append(_INCENTIVE_COL)
    return df.drop(columns=[c for c in drop if c in df.columns])


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
    for col in _EVAL_COLS
    for grade, (bg, fg) in _GRADE_COLOR.items()
]


def layout():
    from services.auth import can
    show_eval = can('view_evaluation')
    show_incentive = can('view_incentive')

    df = _build_summary_df()
    display_df = _build_display_df(df, show_eval, show_incentive)

    dept_opts   = _filter_options(df, '부서')
    pos_opts    = _filter_options(df, '직급')
    degree_opts = _filter_options(df, '최종학위')
    inc_opts    = _filter_options(df, '인센티브')

    numeric_cols = {'논문(전체)', '논문(3년)', '특허(출원)', '특허(등록)', '수상'}
    columns = [
        {'name': col, 'id': col,
         'type': 'numeric' if col in numeric_cols else 'text'}
        for col in display_df.columns
    ]

    grade_styles = _GRADE_STYLES if show_eval else []

    return html.Div([
        dcc.Location(id='list-url', refresh=True),

        # ── AI 검색 (자연어 → SQL) ─────────────────────────────────────────
        dbc.Card(
            dbc.CardBody([
                html.H5(
                    [html.I(className='bi bi-robot me-2 text-primary'),
                     'AI 검색 ', html.Small('자연어로 물어보면 DB를 조회합니다',
                                            className='text-muted fw-normal')],
                    className='fw-bold mb-2 mt-1',
                ),
                dbc.InputGroup([
                    dbc.Input(
                        id='t2s-input',
                        placeholder='예) AI 부서에서 논문이 가장 많은 연구원 5명',
                        type='text',
                        n_submit=0,
                    ),
                    dbc.Button([html.I(className='bi bi-search me-1'), '검색'],
                               id='t2s-btn', color='primary', n_clicks=0),
                ]),
                html.Div(
                    '예시: “특허 등록이 3건 이상인 연구원”, “부서별 평균 논문 수”, '
                    '“2024년 평가등급이 가”인 연구원 이름”',
                    className='text-muted small mt-2',
                ),
                dcc.Loading(
                    html.Div(id='t2s-result', className='mt-3'),
                    type='dot', color='#1e3a5f',
                ),
            ]),
            className='mb-3 shadow-sm',
        ),

        dbc.Row([
            dbc.Col(
                html.H5([html.I(className='bi bi-table me-2 text-primary'), '연구원 목록'],
                        className='fw-bold mb-0 mt-1'),
                className='d-flex align-items-center',
            ),
            dbc.Col(
                dbc.Button('필터 초기화', id='clear-filters-btn', color='secondary',
                           size='sm', outline=True, className='float-end'),
                className='d-flex align-items-center justify-content-end',
            ),
        ], className='mb-3'),

        dbc.Card(
            dbc.CardBody(
                dbc.Row([
                    dbc.Col([
                        dbc.Label('부서', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-dept', options=dept_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=3),
                    dbc.Col([
                        dbc.Label('직급', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-pos', options=pos_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2),
                    dbc.Col([
                        dbc.Label('최종학위', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-degree', options=degree_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2),
                    # 인센티브 필터 — 권한 없으면 숨김 (컴포넌트는 존재해야 콜백 작동)
                    dbc.Col([
                        dbc.Label('인센티브', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-incentive', options=inc_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=2, style={} if show_incentive else {'display': 'none'}),
                ], className='g-3'),
            ),
            className='mb-3 shadow-sm',
        ),

        dbc.Card(
            dbc.CardBody(
                dash_table.DataTable(
                    id='researcher-table',
                    columns=columns,
                    data=display_df.to_dict('records') if not display_df.empty else [],
                    filter_action='native',
                    sort_action='native',
                    sort_mode='multi',
                    page_action='native',
                    page_size=30,
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
                    ],
                    style_data_conditional=grade_styles + [
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


@callback(
    Output('researcher-table', 'data'),
    Input('filter-dept',      'value'),
    Input('filter-pos',       'value'),
    Input('filter-degree',    'value'),
    Input('filter-incentive', 'value'),
)
def update_table(dept, pos, degree, incentive):
    from services.auth import can
    show_eval = can('view_evaluation')
    show_incentive = can('view_incentive')

    df = _build_summary_df()
    if df.empty:
        return []
    if dept:
        df = df[df['부서'].isin(dept)]
    if pos:
        df = df[df['직급'].isin(pos)]
    if degree:
        df = df[df['최종학위'].isin(degree)]
    if incentive and show_incentive:
        df = df[df['인센티브'].isin(incentive)]

    display_df = _build_display_df(df, show_eval, show_incentive)
    return display_df.to_dict('records')


@callback(
    Output('filter-dept',      'value'),
    Output('filter-pos',       'value'),
    Output('filter-degree',    'value'),
    Output('filter-incentive', 'value'),
    Input('clear-filters-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def clear_filters(_):
    return None, None, None, None


@callback(
    Output('list-url', 'href'),
    Input('researcher-table', 'active_cell'),
    Input('researcher-table', 'derived_virtual_data'),
    prevent_initial_call=True,
)
def navigate_to_profile(active_cell, virtual_data):
    if not active_cell or not virtual_data:
        return no_update
    row_idx = active_cell.get('row')
    if row_idx is None or row_idx >= len(virtual_data):
        return no_update
    name = virtual_data[row_idx].get('이름', '')
    if not name:
        return no_update
    try:
        df_all = _build_summary_df()
        match = df_all[df_all['이름'] == name]
        if match.empty:
            return no_update
        rid = match.iloc[0]['researcher_id']
        return f'/researcher-profile?id={rid}'
    except Exception:
        return no_update


# ── 콜백 4: AI 검색 (자연어 → SQL → 결과) ───────────────────────────────────
def _sql_block(sql: str):
    """생성된 SQL 을 접기 가능한 코드 블록으로."""
    return dbc.Card(
        dbc.CardBody([
            html.Div([html.I(className='bi bi-code-slash me-1'),
                      html.Small('실행된 SQL', className='text-muted')],
                     className='mb-1'),
            html.Pre(sql, className='mb-0',
                     style={'whiteSpace': 'pre-wrap', 'fontSize': '0.78rem',
                            'background': '#f6f8fa', 'padding': '8px 10px',
                            'borderRadius': '6px', 'margin': 0}),
        ], className='py-2'),
        className='mb-2 border-0', style={'background': 'transparent'},
    )


@callback(
    Output('t2s-result', 'children'),
    Input('t2s-btn',   'n_clicks'),
    Input('t2s-input', 'n_submit'),
    State('t2s-input', 'value'),
    prevent_initial_call=True,
)
def ai_search(n_clicks, n_submit, question):
    if not question or not question.strip():
        return dbc.Alert('질문을 입력하세요.', color='secondary', className='mb-0')

    if not db_enabled():
        return dbc.Alert(
            [html.I(className='bi bi-info-circle me-2'),
             'AI 검색은 PostgreSQL 연결이 필요합니다. DATABASE_URL 을 설정하세요.'],
            color='warning', className='mb-0',
        )

    res = run_query(question)

    if res['error']:
        children = [dbc.Alert(
            [html.I(className='bi bi-exclamation-triangle me-2'), res['error']],
            color='danger', className='mb-2')]
        if res.get('sql'):
            children.append(_sql_block(res['sql']))
        return children

    cols = res['columns']
    rows = res['rows']

    # 컬럼 헤더 한국어 라벨 (키는 유지)
    _labels = {'researcher_id': '사번', 'name': '이름'}
    clickable = 'researcher_id' in cols   # 프로필 이동 가능 여부

    table = dash_table.DataTable(
        id='t2s-table',
        columns=[{'name': _labels.get(c, c), 'id': c} for c in cols],
        data=[dict(zip(cols, r)) for r in rows],
        page_action='native',
        page_size=20,
        sort_action='native',
        style_as_list_view=True,
        style_table={'overflowX': 'auto'},
        style_header={'backgroundColor': '#1e3a5f', 'color': 'white',
                      'fontWeight': '600', 'fontSize': '0.8rem', 'textAlign': 'center'},
        style_cell={'fontSize': '0.82rem', 'padding': '5px 10px',
                    'textAlign': 'left', 'maxWidth': '260px',
                    'overflow': 'hidden', 'textOverflow': 'ellipsis',
                    'cursor': 'pointer' if clickable else 'default'},
        style_cell_conditional=[
            {'if': {'column_id': 'name'}, 'fontWeight': '600', 'color': '#1e3a5f'},
        ],
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': '#f9fbfd'},
            {'if': {'state': 'active'}, 'backgroundColor': '#dbeafe',
             'border': '1px solid #3b82f6'},
        ],
    )
    count = html.Div(f'{len(rows)}건', className='text-muted small mb-2')
    if not rows:
        count = dbc.Alert('조건에 맞는 결과가 없습니다.', color='secondary', className='mb-2')

    children = [_sql_block(res['sql']), count, table]
    if clickable and rows:
        children.append(html.P(
            [html.I(className='bi bi-hand-index me-1'),
             '행을 클릭하면 해당 연구원 프로필로 이동합니다.'],
            className='text-muted small mt-2 mb-0'))
    return children


# ── 콜백 5: AI 검색 결과 행 클릭 → 프로필 이동 ──────────────────────────────
@callback(
    Output('list-url', 'href', allow_duplicate=True),
    Input('t2s-table', 'active_cell'),
    State('t2s-table', 'derived_virtual_data'),
    prevent_initial_call=True,
)
def t2s_row_click(active_cell, data):
    if not active_cell or not data:
        return no_update
    row_idx = active_cell.get('row')
    if row_idx is None or row_idx >= len(data):
        return no_update
    rid = data[row_idx].get('researcher_id')
    if not rid:
        return no_update
    return f'/researcher-profile?id={str(rid).zfill(8)}'
