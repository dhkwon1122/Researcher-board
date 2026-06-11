"""
화면 3: 연구원 목록 (정량 지표 테이블)
"""

from datetime import datetime
from urllib.parse import parse_qs

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, callback, dash_table, dcc, html, no_update

from services.data_store import read_processed

dash.register_page(
    __name__,
    path='/researcher-list',
    name='연구원 목록',
    title='연구원 목록',
)

_CURRENT_YEAR = datetime.now().year

# ── 학위 우선순위 ─────────────────────────────────────────────────────────────
_DEGREE_RANK = {'박사': 5, '석사': 4, '학사': 3, '전문대': 2, '고교': 1}

# ── 리더십 차원 (실제 데이터 기준) ────────────────────────────────────────────
_LEA_DIMS = ['미래통찰', '성과창출', '몰입촉진', '인재육성', '자기관리']


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

    # 숫자 변환
    for col in ['pub_year', 'impact_factor', 'citation_count']:
        if col in pub.columns:
            pub[col] = pd.to_numeric(pub[col], errors='coerce')
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
        pub_3yr    = int((pubs['pub_year'] >= _CURRENT_YEAR - 2).sum()) if not pubs.empty else 0
        avg_if     = round(pubs['impact_factor'].mean(), 2) if not pubs.empty and pubs['impact_factor'].notna().any() else '-'

        # ── 특허 ───────────────────────────────────────────────────────────
        pats = pat[pat['researcher_id'] == rid]
        pat_app = int((pats['status'] == '출원').sum()) if not pats.empty else 0
        pat_reg = int((pats['status'] == '등록').sum()) if not pats.empty else 0

        # ── 리더십 ─────────────────────────────────────────────────────────
        ldf = lea[(lea['researcher_id'] == rid)]
        # 타인평균 우선, 없으면 전체 평균
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

        # ── TOEIC ──────────────────────────────────────────────────────────
        toeic = cert[(cert['researcher_id'] == rid) & (cert['cert_name'] == 'TOEIC')]
        if not toeic.empty and 'score' in toeic.columns:
            valid = toeic[toeic['score'].notna()]
            toeic_score = int(valid.sort_values('date_obtained').iloc[-1]['score']) if not valid.empty else '-'
        else:
            toeic_score = '-'

        # ── 수상 ───────────────────────────────────────────────────────────
        awd_cnt = len(awd[awd['researcher_id'] == rid])

        # ── 최종학위 ───────────────────────────────────────────────────────
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

    dept_opts   = _filter_options(df, '부서')
    pos_opts    = _filter_options(df, '직급')
    degree_opts = _filter_options(df, '최종학위')
    inc_opts    = _filter_options(df, '인센티브')

    columns = [
        {'name': col, 'id': col,
         'type': 'numeric' if col in ('논문(전체)', '논문(3년)', '특허(출원)', '특허(등록)', '수상') else 'text'}
        for col in df.columns if col != 'researcher_id'
    ]
    # 평균IF, 리더십, TOEIC도 숫자형으로 설정 (혼합값 있으므로 text 유지)

    return html.Div([
        dcc.Location(id='list-url', refresh=True),
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

        # ── 상단 드롭다운 필터 ─────────────────────────────────────────────
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
                    dbc.Col([
                        dbc.Label('인센티브', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-incentive', options=inc_opts, multi=True,
                                     placeholder='전체', clearable=True),
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
                    data=df.drop(columns=['researcher_id']).to_dict('records') if not df.empty else [],
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


# ── 콜백 1: 상단 드롭다운 필터 → 테이블 데이터 갱신 ─────────────────────────
@callback(
    Output('researcher-table', 'data'),
    Input('filter-dept',      'value'),
    Input('filter-pos',       'value'),
    Input('filter-degree',    'value'),
    Input('filter-incentive', 'value'),
)
def update_table(dept, pos, degree, incentive):
    df = _build_summary_df()
    if df.empty:
        return []
    if dept:
        df = df[df['부서'].isin(dept)]
    if pos:
        df = df[df['직급'].isin(pos)]
    if degree:
        df = df[df['최종학위'].isin(degree)]
    if incentive:
        df = df[df['인센티브'].isin(incentive)]
    return df.drop(columns=['researcher_id']).to_dict('records')


# ── 콜백 2: 필터 초기화 버튼 ─────────────────────────────────────────────────
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


# ── 콜백 3: 행 클릭 → 프로필 화면 이동 ──────────────────────────────────────
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
    # researcher_id는 테이블 data에 없으므로 이름으로 역조회
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
