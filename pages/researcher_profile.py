"""
화면 2: 연구원 개별 프로필
레이아웃: 사진+기본정보 | 학력+평가/인센티브표+발령이력 | 리더십그래프+코멘트
하단: 논문 / 특허 / 기술이전 실적 탭
"""

import csv
import os
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, html, dcc

dash.register_page(__name__, path='/researcher-profile', name='연구원 프로필', title='연구원 개별 프로필')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')
RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')

DEGREE_ORDER = ['박사', '석사', '학사']
GRADE_COLOR = {
    '가': '#f5a623',  # 금색 — 최우수
    '나': '#52c41a',  # 초록
    '다': '#1890ff',  # 파랑
    '라': '#8c8c8c',  # 회색
    '마': '#ff4d4f',  # 빨강 — 최하
    '-': '#aaa',
}
LEADERSHIP_DIMS = {
    'vision': '비전제시',
    'communication': '소통·협력',
    'execution': '실행력',
    'collaboration': '협업·팀워크',
    'development': '인재육성',
}
TRANSFER_BADGE = {
    '부서발령': 'primary',
    '프로젝트파견': 'success',
    '해외파견': 'info',
    '공동연구': 'secondary',
}
CURRENT_YEAR = datetime.now().year


# ─── 데이터 헬퍼 ─────────────────────────────────────────────────────────────

def _r(name):
    path = os.path.join(DATA_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, encoding='utf-8-sig', dtype={'researcher_id': str})


def _avatar(name: str, size: int = 88):
    initial = name[0] if name else '?'
    return html.Div(
        initial,
        style={
            'width': f'{size}px', 'height': f'{size}px', 'borderRadius': '50%',
            'backgroundColor': '#1e3a5f', 'color': 'white',
            'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center',
            'fontSize': f'{int(size * 0.45)}px', 'fontWeight': 'bold',
        },
    )


# ─── 탭 콘텐츠 헬퍼 ──────────────────────────────────────────────────────────

def _pub_tab(pub_df, rid):
    if pub_df.empty:
        return html.Div('논문 데이터 없음', className='text-muted p-3')
    pub = pub_df[pub_df['researcher_id'] == rid].sort_values('pub_year', ascending=False)
    total = len(pub)
    corr = int((pub['is_corresponding'] == True).sum())
    summary = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(str(total), className='fw-bold text-primary mb-0'),
            html.Small('총 논문 수', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=2),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(str(corr), className='fw-bold text-warning mb-0'),
            html.Small('교신저자', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=2),
    ], className='mb-3')
    rows = [html.Tr([
        html.Td(str(int(r['pub_year']))),
        html.Td(r['title'], style={'maxWidth': '340px', 'wordBreak': 'break-word'}),
        html.Td(r['journal'], className='small text-muted'),
        html.Td(f"{r['impact_factor']:.2f}"),
        html.Td(str(int(r['citation_count']))),
        html.Td(dbc.Badge('교신', color='warning', text_color='dark')
                if r.get('is_corresponding') else ''),
    ]) for _, r in pub.iterrows()]
    table = dbc.Table([
        html.Thead(html.Tr([html.Th('연도'), html.Th('제목'), html.Th('저널'),
                            html.Th('IF'), html.Th('피인용'), html.Th('')])),
        html.Tbody(rows),
    ], bordered=False, hover=True, responsive=True, size='sm')
    return html.Div([summary, table])


def _pat_tab(pat_df, rid):
    if pat_df.empty:
        return html.Div('특허 데이터 없음', className='text-muted p-3')
    pat = pat_df[pat_df['researcher_id'] == rid].copy()
    if pat.empty:
        return html.Div('특허 실적 없음', className='text-muted p-3')

    def _is_reg(s):
        return '등록' in str(s)

    def _cell(row, *keys, default='-'):
        for k in keys:
            v = str(row.get(k, ''))
            if v and v not in ('', 'nan', 'None'):
                return v
        return default

    # ── 접수ID 기준 중복 제거 (같은 접수ID = 같은 특허, 국가는 합산) ──────────
    id_col = 'application_id' if 'application_id' in pat.columns else None

    if id_col:
        def _merge_countries(series):
            vals = [str(v).strip() for v in series if str(v).strip() not in ('', 'nan', 'None', '-')]
            seen = {}
            for v in vals:
                for part in v.split(','):
                    p = part.strip()
                    if p:
                        seen[p] = None
            return ', '.join(seen.keys()) if seen else '-'

        agg_dict = {c: 'first' for c in pat.columns if c not in (id_col, 'researcher_id', 'country')}
        if 'country' in pat.columns:
            agg_dict['country'] = _merge_countries
        pat_dedup = pat.groupby(id_col, sort=False).agg(agg_dict).reset_index()
    else:
        pat_dedup = pat.copy()

    # ── 요약 집계 ──────────────────────────────────────────────────────────────
    total_cnt = len(pat_dedup)
    reg_cnt   = int(pat_dedup['status'].apply(_is_reg).sum()) if 'status' in pat_dedup.columns else 0

    # 대표발명 수
    lead_cnt = 0
    if 'is_lead_inventor' in pat_dedup.columns:
        lead_cnt = int(pat_dedup['is_lead_inventor'].astype(str)
                       .isin(['Y', 'y', '1', 'True', 'true']).sum())

    # 전략 출원 — patent_grade 가 'S' 또는 'A'인 특허
    # (실제 등급 체계에 맞게 조정 필요)
    strat_cnt = 0
    if 'patent_grade' in pat_dedup.columns:
        strat_cnt = int(pat_dedup['patent_grade'].astype(str)
                        .isin(['S', 'A', 'A1', 'A2']).sum())

    # 미국 등록 특허 — country 에 '미국'/'US'/'USA' 포함 + status 가 등록
    us_reg_cnt = 0
    if 'country' in pat_dedup.columns and 'status' in pat_dedup.columns:
        us_mask = pat_dedup['country'].astype(str).str.contains('미국|USA|US', case=False, na=False)
        us_reg_cnt = int((us_mask & pat_dedup['status'].apply(_is_reg)).sum())

    def _summary_card(main_val, main_label, sub_val=None, sub_label=None, color='text-dark'):
        body = [
            html.H4(str(main_val), className=f'fw-bold {color} mb-0'),
            html.Small(main_label, className='text-muted d-block'),
        ]
        if sub_val is not None:
            body.append(html.Small(f'{sub_label} {sub_val}건',
                                   className='text-muted fw-semibold'))
        return dbc.Card(dbc.CardBody(body, className='text-center p-2'),
                        className='border-0 bg-light h-100')

    summary = dbc.Row([
        dbc.Col(_summary_card(total_cnt,  '전체 발명',
                              sub_val=lead_cnt, sub_label='대표발명',
                              color='text-dark'),   md=3),
        dbc.Col(_summary_card(total_cnt,  '출원',
                              sub_val=reg_cnt, sub_label='이 중 등록',
                              color='text-primary'), md=3),
        dbc.Col(_summary_card(strat_cnt,  '전략 출원', color='text-warning'), md=3),
        dbc.Col(_summary_card(us_reg_cnt, '미국 등록', color='text-info'),    md=3),
    ], className='mb-3')

    # ── 테이블 ──────────────────────────────────────────────────────────────────
    sort_col = 'application_date' if 'application_date' in pat_dedup.columns else pat_dedup.columns[0]
    rows = []
    for _, r in pat_dedup.sort_values(sort_col, ascending=False).iterrows():
        status_val = str(r.get('status', ''))
        status_badge = (dbc.Badge('등록', color='success') if _is_reg(status_val)
                        else dbc.Badge(status_val or '출원', color='primary'))
        lead = str(r.get('is_lead_inventor', ''))
        grade = str(r.get('patent_grade', ''))
        grade_a = str(r.get('patent_grade_a_sub', ''))
        grade_str = grade + (f'({grade_a})' if grade_a and grade_a not in ('', 'nan') else '')
        share_val = r.get('share_ratio', '')
        share_str = (f'{share_val}%' if str(share_val).replace('.', '').isdigit() else '-')

        rows.append(html.Tr([
            html.Td(_cell(r, 'application_date')[:7]),
            html.Td(_cell(r, 'title', 'title_ko'),
                    style={'maxWidth': '280px', 'wordBreak': 'break-word'}),
            html.Td(status_badge),
            html.Td(_cell(r, 'application_id', 'application_no')),
            html.Td(dbc.Badge('대표', color='warning', text_color='dark')   # 대표발명자 먼저
                    if lead in ('Y', 'y', '1', 'True', 'true') else ''),
            html.Td(share_str),                                              # 지분율 나중에
            html.Td(grade_str or '-'),
            html.Td(_cell(r, 'country')),
        ]))

    table = dbc.Table([
        html.Thead(html.Tr([
            html.Th('출원일'), html.Th('발명 명칭'), html.Th('상태'),
            html.Th('접수ID/출원번호'), html.Th('대표발명자'), html.Th('지분율'),
            html.Th('등급'), html.Th('출원 국가'),
        ])),
        html.Tbody(rows),
    ], bordered=False, hover=True, responsive=True, size='sm')
    return html.Div([summary, table])


def _tt_tab(tt_df, rid):
    if tt_df.empty:
        return html.Div('기술 이전 데이터 없음', className='text-muted p-3')
    tt = tt_df[tt_df['researcher_id'] == rid].sort_values('transfer_date', ascending=False)
    if tt.empty:
        return html.Div('기술 이전 실적 없음', className='text-muted p-3')
    summary = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(str(len(tt)), className='fw-bold text-primary mb-0'),
            html.Small('총 건수', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=2),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(f"{int(tt['amount'].sum()):,}만원", className='fw-bold text-success mb-0'),
            html.Small('누적 금액', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=3),
    ], className='mb-3')
    rows = [html.Tr([
        html.Td(str(r['transfer_date'])[:10]),
        html.Td(r['tech_name']),
        html.Td(r['recipient']),
        html.Td(r['transfer_type']),
        html.Td(f"{int(r['amount']):,}만원", className='text-end'),
    ]) for _, r in tt.iterrows()]
    table = dbc.Table([
        html.Thead(html.Tr([html.Th('이전일'), html.Th('기술명'), html.Th('거래처'),
                            html.Th('유형'), html.Th('금액', className='text-end')])),
        html.Tbody(rows),
    ], bordered=False, hover=True, responsive=True, size='sm')
    return html.Div([summary, table])


# ─── 레이아웃 ─────────────────────────────────────────────────────────────────

def layout():
    try:
        res_df = _r('researchers')
        options = [
            {'label': f'{row["name"]}  ({row["department"]} / {row["position"]})',
             'value': row['researcher_id']}
            for _, row in res_df.sort_values('department').iterrows()
        ]
        default = options[0]['value'] if options else None
    except Exception:
        options, default = [], None

    return html.Div([
        html.H5(
            [html.I(className='bi bi-person-badge-fill me-2 text-primary'), '연구원 개별 프로필'],
            className='fw-bold mb-3 mt-1',
        ),

        # 연구원 선택 바
        dbc.Card(
            dbc.CardBody(
                dbc.Row([
                    dbc.Col(
                        dbc.Label('연구원 선택', className='fw-semibold small text-muted mb-0'),
                        width='auto',
                        className='d-flex align-items-center pe-0',
                    ),
                    dbc.Col(
                        dcc.Dropdown(
                            id='researcher-select',
                            options=options,
                            value=default,
                            clearable=False,
                            placeholder='이름 또는 부서로 검색...',
                            style={'minWidth': '400px'},
                        ),
                    ),
                ], align='center', className='g-2'),
            ),
            className='mb-3 shadow-sm',
        ),

        # ── 상단 3열 레이아웃 ──────────────────────────────────────────────────
        dbc.Row([

            # 열 1: 사진 + 기본정보
            dbc.Col([
                dbc.Card(
                    dbc.CardBody(
                        html.Div(id='photo-block',
                                 className='d-flex flex-column align-items-center py-1'),
                        className='p-2',
                    ),
                    className='shadow-sm mb-2',
                ),
                dbc.Card(
                    dbc.CardBody(html.Div(id='basic-info-block'), className='p-2'),
                    className='shadow-sm',
                ),
            ], md=2),

            # 열 2: 학력 + 평가/인센티브 표 + 발령이력
            dbc.Col([
                dbc.Row([
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.P('학력', className='fw-semibold text-muted small mb-2'),
                                html.Div(id='education-block'),
                            ], className='p-3'),
                            className='shadow-sm h-100',
                        ),
                        md=7,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.P('평가 / 인센티브 이력',
                                       className='fw-semibold text-muted small mb-2'),
                                html.Div(id='eval-incentive-block'),
                            ], className='p-3'),
                            className='shadow-sm h-100',
                        ),
                        md=5,
                    ),
                ], className='g-2 mb-2'),
                dbc.Card(
                    dbc.CardBody([
                        html.P('사내 발령 이력 (프로젝트 수행 이력)',
                               className='fw-semibold text-muted small mb-2'),
                        html.Div(id='transfer-block'),
                    ], className='p-3'),
                    className='shadow-sm',
                ),
            ], md=5),

            # 열 3: 리더십 진단 + 인물 코멘트
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col(
                                html.P('리더십 진단 그래프',
                                       className='fw-semibold text-muted small mb-0'),
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id='leadership-year',
                                    clearable=False,
                                    style={'width': '110px'},
                                ),
                                width='auto',
                            ),
                        ], align='center', className='mb-1'),
                        dcc.Graph(id='leadership-chart', style={'height': '240px'},
                                  config={'displayModeBar': False}),
                    ], className='p-3'),
                    className='shadow-sm mb-2',
                ),
                dbc.Card(
                    dbc.CardBody([
                        html.P('인물 코멘트 (부서장 / 부서원)',
                               className='fw-semibold text-muted small mb-2'),
                        # 기존 코멘트 목록
                        html.Div(id='comments-block',
                                 style={'maxHeight': '220px', 'overflowY': 'auto'}),
                        html.Hr(className='my-2'),
                        # 코멘트 입력 폼
                        dbc.Row([
                            dbc.Col(
                                dcc.Dropdown(
                                    id='comment-year',
                                    options=[{'label': str(y), 'value': y}
                                             for y in range(CURRENT_YEAR, CURRENT_YEAR - 5, -1)],
                                    value=CURRENT_YEAR,
                                    clearable=False,
                                    style={'minWidth': '100px'},
                                ),
                                width='auto',
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id='comment-author-type',
                                    options=[
                                        {'label': '부서장', 'value': '부서장'},
                                        {'label': '부서원', 'value': '부서원'},
                                    ],
                                    value='부서장',
                                    clearable=False,
                                    style={'minWidth': '100px'},
                                ),
                                width='auto',
                            ),
                        ], className='g-2 mb-2'),
                        dbc.Textarea(
                            id='comment-text',
                            placeholder='코멘트를 입력하세요...',
                            rows=3,
                            className='mb-2',
                        ),
                        dbc.Button('저장', id='comment-save-btn', color='primary', size='sm'),
                        html.Div(id='comment-status', className='mt-2 small'),
                    ], className='p-3'),
                    className='shadow-sm',
                ),
            ], md=5),

        ], className='g-3 mb-3'),

        # ── 하단: 논문 / 특허 / 기술이전 탭 ──────────────────────────────────
        dbc.Card(
            dbc.CardBody(
                dbc.Tabs([
                    dbc.Tab(html.Div(id='tab-publications'), label='논문 실적', tab_id='pub'),
                    dbc.Tab(html.Div(id='tab-patents'), label='특허 실적 (최근 3년)', tab_id='pat'),
                    dbc.Tab(html.Div(id='tab-transfer'), label='기술 이전 실적', tab_id='tt'),
                ],
                id='detail-tabs',
                active_tab='pub',
                className='mb-2',
                ),
            ),
            className='shadow-sm',
        ),
    ])


# ─── 콜백: 프로필 전체 갱신 ──────────────────────────────────────────────────

@callback(
    Output('photo-block', 'children'),
    Output('basic-info-block', 'children'),
    Output('education-block', 'children'),
    Output('eval-incentive-block', 'children'),
    Output('transfer-block', 'children'),
    Output('leadership-year', 'options'),
    Output('leadership-year', 'value'),
    Output('comments-block', 'children'),
    Output('tab-publications', 'children'),
    Output('tab-patents', 'children'),
    Output('tab-transfer', 'children'),
    Input('researcher-select', 'value'),
)
def update_profile(rid):
    none_out = (
        _avatar('?'), html.Div(), html.Div(), html.Div(), html.Div(),
        [], None, html.Div(),
        html.Div('연구원을 선택하세요.', className='text-muted p-3'),
        html.Div('연구원을 선택하세요.', className='text-muted p-3'),
        html.Div('연구원을 선택하세요.', className='text-muted p-3'),
    )
    if not rid:
        return none_out

    res_df = _r('researchers')
    eva_df = _r('evaluations')
    edu_df = _r('education')
    inc_df = _r('incentive_selection')
    lea_df = _r('leadership')
    tra_df = _r('transfers')
    cmt_df = _r('comments')
    pub_df = _r('publications')
    pat_df = _r('patents')
    tt_df = _r('technology_transfer')

    if res_df.empty:
        return none_out
    r_row = res_df[res_df['researcher_id'] == rid]
    if r_row.empty:
        return none_out
    r = r_row.iloc[0]

    # ── 사진 블록 ──────────────────────────────────────────────────────────
    name = str(r['name'])
    rid_str = str(r['researcher_id'])
    photo_el = None
    for ext in ('png', 'jpg', 'jpeg'):
        photo_file = os.path.join(RAW_DIR, f'{rid_str}.{ext}')
        if os.path.exists(photo_file):
            import base64, mimetypes
            mime = mimetypes.guess_type(photo_file)[0] or f'image/{ext}'
            with open(photo_file, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
            photo_el = html.Img(
                src=f'data:{mime};base64,{encoded}',
                style={'width': '100%', 'maxHeight': '200px',
                       'objectFit': 'contain', 'borderRadius': '8px',
                       'display': 'block'},
            )
            break
    if photo_el is None:
        photo_el = _avatar(name, size=90)

    photo_block = [
        photo_el,
        html.P(name, className='fw-bold mt-2 mb-0 text-center small'),
    ]

    # ── 기본정보 블록 ───────────────────────────────────────────────────────
    gender = str(r.get('gender', ''))
    birth_year = int(r.get('birth_year', CURRENT_YEAR - 30))
    hire_year = int(r.get('hire_year', CURRENT_YEAR))
    age = CURRENT_YEAR - birth_year
    tenure = CURRENT_YEAR - hire_year

    basic_info_block = html.Table(
        html.Tbody([
            html.Tr([
                html.Td(lbl, className='text-muted pe-2',
                        style={'fontSize': '0.78rem', 'fontWeight': '600',
                               'whiteSpace': 'nowrap', 'verticalAlign': 'top'}),
                html.Td(val, style={'fontSize': '0.8rem'}),
            ])
            for lbl, val in [
                ('성별', gender),
                ('나이', f'{age}세'),
                ('직급', str(r.get('position', ''))),
                ('직급연차', f'{tenure}년차'),
                ('근속', f'{tenure}년'),
            ]
        ]),
        className='w-100 mb-0',
    )

    # ── 학력 블록 ──────────────────────────────────────────────────────────
    edu_rows = edu_df[edu_df['researcher_id'] == rid] if not edu_df.empty else pd.DataFrame()
    edu_items = []
    for deg in DEGREE_ORDER:
        d = edu_rows[edu_rows['degree'] == deg]
        if not d.empty:
            e = d.iloc[0]
            color = 'primary' if deg == '박사' else ('secondary' if deg == '석사' else 'light')
            text_color = 'dark' if deg == '학사' else 'white'
            edu_items.append(html.Div([
                dbc.Badge(deg, color=color, text_color=text_color, className='me-1'),
                html.Span(f"{e['school']}", className='small fw-semibold'),
                html.Br(),
                html.Span(f"{e['major']} ({int(e['graduation_year'])})",
                          className='small text-muted', style={'marginLeft': '0.5rem'}),
            ], className='mb-2'))
    education_block = (
        html.Div(edu_items) if edu_items
        else html.Div('학력 정보 없음', className='text-muted small')
    )

    # ── 평가/인센티브 연도별 표 ────────────────────────────────────────────
    years3 = [CURRENT_YEAR - 2, CURRENT_YEAR - 1, CURRENT_YEAR]

    inc = inc_df[inc_df['researcher_id'] == rid] if not inc_df.empty else pd.DataFrame()
    eva = eva_df[eva_df['researcher_id'] == rid] if not eva_df.empty else pd.DataFrame()

    def _inc_label(yr):
        if inc.empty:
            return '-'
        row_ = inc[inc['year'] == yr]
        if row_.empty:
            return '-'
        sel = str(row_.iloc[0].get('selected', '')).lower()
        if sel in ('true', '1', 'yes'):
            cat = str(row_.iloc[0].get('category', '선정'))
            return '최우수' if '최우수' in cat else ('우수' if '우수' in cat else cat[:4])
        return '-'

    def _grade(yr):
        if eva.empty:
            return '-'
        row_ = eva[eva['year'] == yr]
        return str(row_.iloc[0].get('grade', '-')) if not row_.empty else '-'

    def _grade_td(g):
        color = GRADE_COLOR.get(g, '#aaa')
        return html.Td(
            html.Span(g, style={'color': color, 'fontWeight': '700', 'fontSize': '0.9rem'}),
            className='text-center',
        )

    eval_incentive_block = dbc.Table([
        html.Thead(
            html.Tr(
                [html.Th('구분', style={'fontSize': '0.72rem', 'width': '55px'})] +
                [html.Th(f"'{str(y)[-2:]}", className='text-center',
                         style={'fontSize': '0.72rem'})
                 for y in years3]
            ),
            className='table-light',
        ),
        html.Tbody([
            html.Tr(
                [html.Td('인센티브', className='small text-muted',
                         style={'whiteSpace': 'nowrap', 'fontSize': '0.75rem'})] +
                [html.Td(_inc_label(y), className='text-center small') for y in years3]
            ),
            html.Tr(
                [html.Td('평가등급', className='small text-muted',
                         style={'whiteSpace': 'nowrap', 'fontSize': '0.75rem'})] +
                [_grade_td(_grade(y)) for y in years3]
            ),
        ]),
    ], bordered=True, size='sm', className='mb-0', style={'fontSize': '0.8rem'})

    # ── 발령/프로젝트 이력 ─────────────────────────────────────────────────
    tra = (tra_df[tra_df['researcher_id'] == rid].sort_values('date', ascending=False)
           if not tra_df.empty else pd.DataFrame())

    if tra.empty:
        transfer_block = html.Div('발령 / 프로젝트 이력 없음', className='text-muted small')
    else:
        t_rows = [
            html.Tr([
                html.Td(str(t.get('date', ''))[:7], className='small text-muted',
                        style={'whiteSpace': 'nowrap'}),
                html.Td(
                    dbc.Badge(str(t.get('type', '')),
                              color=TRANSFER_BADGE.get(str(t.get('type', '')), 'light'),
                              className='small'),
                ),
                html.Td(str(t.get('description', '')), className='small'),
            ])
            for _, t in tra.iterrows()
        ]
        transfer_block = dbc.Table([
            html.Thead(html.Tr([
                html.Th('시기', style={'fontSize': '0.72rem'}),
                html.Th('유형', style={'fontSize': '0.72rem'}),
                html.Th('내용', style={'fontSize': '0.72rem'}),
            ]), className='table-light'),
            html.Tbody(t_rows),
        ], bordered=False, hover=True, responsive=True, size='sm',
           className='mb-0',
           style={'maxHeight': '130px', 'overflowY': 'auto', 'display': 'block'})

    # ── 리더십 연도 옵션 ────────────────────────────────────────────────────
    lea_years = (
        sorted(lea_df[lea_df['researcher_id'] == rid]['year'].unique(), reverse=True)
        if not lea_df.empty else []
    )
    lea_options = [{'label': str(y), 'value': y} for y in lea_years]
    lea_default = lea_years[0] if lea_years else None

    # ── 코멘트 목록 ────────────────────────────────────────────────────────
    if not cmt_df.empty:
        cmts = cmt_df[cmt_df['researcher_id'] == rid]
        sort_cols = (['year', 'commenter_type'] if 'commenter_type' in cmt_df.columns
                     else ['year'])
        cmts = cmts.sort_values(sort_cols, ascending=False)
    else:
        cmts = pd.DataFrame()

    cmt_cards = []
    for _, c in cmts.iterrows():
        c_type = str(c.get('commenter_type', '부서장'))
        badge_color = 'danger' if c_type == '부서장' else 'info'
        cmt_cards.append(
            dbc.Card(
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col(
                            html.Span(f'{int(c["year"])}년', className='fw-bold small'),
                            width='auto',
                        ),
                        dbc.Col(
                            dbc.Badge(c_type, color=badge_color, className='small'),
                            width='auto',
                        ),
                    ], className='mb-1 g-1'),
                    html.P(str(c.get('comment_summary', '')),
                           className='small mb-1', style={'lineHeight': '1.5'}),
                    html.Small(
                        ['강점: ', html.Span(str(c.get('strengths', '')),
                                            className='text-muted')],
                        className='d-block',
                    ) if c.get('strengths') else None,
                ], className='py-2 px-3'),
                className='mb-2 border',
            )
        )
    comments_block = (
        html.Div(cmt_cards) if cmt_cards
        else html.Div('코멘트 없음', className='text-muted small')
    )

    return (
        photo_block, basic_info_block, education_block, eval_incentive_block,
        transfer_block, lea_options, lea_default, comments_block,
        _pub_tab(pub_df, rid), _pat_tab(pat_df, rid), _tt_tab(tt_df, rid),
    )


# ─── 콜백: 리더십 레이더 차트 ─────────────────────────────────────────────────

@callback(
    Output('leadership-chart', 'figure'),
    Input('researcher-select', 'value'),
    Input('leadership-year', 'value'),
)
def update_leadership(rid, year):
    fig = go.Figure()
    if not rid or not year:
        return fig
    lea_df = _r('leadership')
    if lea_df.empty:
        return fig
    row = lea_df[(lea_df['researcher_id'] == rid) & (lea_df['year'] == year)]
    if row.empty:
        return fig
    row = row.iloc[0]
    dims = list(LEADERSHIP_DIMS.keys())
    labels = list(LEADERSHIP_DIMS.values())
    vals = [float(row.get(d, 0)) for d in dims]
    vals_c = vals + [vals[0]]
    labels_c = labels + [labels[0]]
    fig.add_trace(go.Scatterpolar(
        r=vals_c, theta=labels_c,
        fill='toself',
        fillcolor='rgba(30,58,95,0.15)',
        line=dict(color='#1e3a5f', width=2),
        hovertemplate='%{theta}: %{r:.0f}점<extra></extra>',
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=8)),
            angularaxis=dict(tickfont=dict(size=11, color='#333')),
        ),
        showlegend=False,
        margin=dict(l=50, r=50, t=15, b=15),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# ─── 콜백: 코멘트 저장 ────────────────────────────────────────────────────────

@callback(
    Output('comment-status', 'children'),
    Input('comment-save-btn', 'n_clicks'),
    State('researcher-select', 'value'),
    State('comment-year', 'value'),
    State('comment-author-type', 'value'),
    State('comment-text', 'value'),
    prevent_initial_call=True,
)
def save_comment(n_clicks, rid, year, author_type, text):
    if not rid or not year or not text or not text.strip():
        return dbc.Alert('연구원, 연도, 코멘트를 모두 입력하세요.',
                         color='warning', className='py-1 px-2 mb-0')
    path = os.path.join(DATA_DIR, 'comments.csv')
    try:
        cols = ['researcher_id', 'year', 'commenter_type', 'comment_raw',
                'comment_summary', 'strengths', 'improvements']
        df = pd.read_csv(path, encoding='utf-8-sig', dtype={'researcher_id': str}) if os.path.exists(path) else pd.DataFrame(columns=cols)
        if 'commenter_type' not in df.columns:
            df['commenter_type'] = '부서장'

        mask = ((df['researcher_id'] == rid) & (df['year'] == year) &
                (df['commenter_type'] == author_type))
        summary = text[:120] + ('...' if len(text) > 120 else '')
        new_row = {
            'researcher_id': rid, 'year': year, 'commenter_type': author_type,
            'comment_raw': text, 'comment_summary': summary,
            'strengths': '', 'improvements': '',
        }
        if mask.any():
            for k, v in new_row.items():
                df.loc[mask, k] = v
        else:
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

        df.to_csv(path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
        return dbc.Alert('저장 완료', color='success', className='py-1 px-2 mb-0')
    except Exception as e:
        return dbc.Alert(f'저장 실패: {e}', color='danger', className='py-1 px-2 mb-0')
