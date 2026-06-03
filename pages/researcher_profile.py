"""
화면 2: 연구원 개별 프로필
"""

import os
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, html, dcc

dash.register_page(__name__, path='/researcher-profile', name='연구원 프로필', title='연구원 개별 프로필')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

DEGREE_ORDER = ['학사', '석사', '박사']
GRADE_COLOR = {'S': '#f5a623', 'A': '#52c41a', 'B': '#1890ff', 'C': '#8c8c8c', '-': '#d9d9d9'}
GRADE_BADGE_COLOR = {'S': 'warning', 'A': 'success', 'B': 'primary', 'C': 'secondary'}

LEADERSHIP_DIMS = {
    'vision': '비전제시',
    'communication': '소통·협력',
    'execution': '실행력',
    'collaboration': '협업·팀워크',
    'development': '인재육성',
}


# ─── 데이터 로드 ─────────────────────────────────────────────────────────────

def _r(name):
    path = os.path.join(DATA_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, encoding='utf-8-sig')


# ─── 아바타 ──────────────────────────────────────────────────────────────────

def _avatar(name: str):
    initial = name[0] if name else '?'
    return html.Div(
        initial,
        style={
            'width': '72px', 'height': '72px', 'borderRadius': '50%',
            'backgroundColor': '#1e3a5f', 'color': 'white',
            'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center',
            'fontSize': '2rem', 'fontWeight': 'bold', 'flexShrink': '0',
        },
    )


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

    return html.Div(
        [
            html.H5(
                [html.I(className='bi bi-person-badge-fill me-2 text-primary'), '연구원 개별 프로필'],
                className='fw-bold mb-3 mt-1',
            ),

            # 연구원 선택
            dbc.Card(
                dbc.CardBody(
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Label('연구원 선택', className='fw-semibold small text-muted mb-1'),
                                width='auto',
                                className='d-flex align-items-end pe-0',
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id='researcher-select',
                                    options=options,
                                    value=default,
                                    clearable=False,
                                    placeholder='이름 또는 부서로 검색...',
                                    style={'minWidth': '380px'},
                                ),
                            ),
                        ],
                        align='center',
                        className='g-2',
                    )
                ),
                className='mb-3 shadow-sm',
            ),

            # 프로필 헤더
            dbc.Card(id='profile-header', className='mb-3 shadow-sm'),

            # 평가 + 인센티브
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.P('최근 5년 평가 추이',
                                           className='fw-semibold text-muted small mb-1'),
                                    dcc.Graph(id='eval-chart', style={'height': '260px'},
                                              config={'displayModeBar': False}),
                                ]
                            ),
                            className='shadow-sm h-100',
                        ),
                        md=7,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.P('인센티브 인력 선정 이력 (최근 3년)',
                                           className='fw-semibold text-muted small mb-2'),
                                    html.Div(id='incentive-cards'),
                                ]
                            ),
                            className='shadow-sm h-100',
                        ),
                        md=5,
                    ),
                ],
                className='g-3 mb-3',
            ),

            # 리더십 진단
            dbc.Card(
                dbc.CardBody(
                    [
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.P('리더십 진단 결과',
                                           className='fw-semibold text-muted small mb-0'),
                                ),
                                dbc.Col(
                                    dcc.Dropdown(
                                        id='leadership-year',
                                        clearable=False,
                                        style={'width': '120px'},
                                    ),
                                    width='auto',
                                ),
                            ],
                            align='center',
                            className='mb-2',
                        ),
                        dcc.Graph(id='leadership-chart', style={'height': '300px'},
                                  config={'displayModeBar': False}),
                    ]
                ),
                className='mb-3 shadow-sm',
            ),

            # 상세 탭
            dbc.Card(
                dbc.CardBody(
                    dbc.Tabs(
                        [
                            dbc.Tab(html.Div(id='tab-patents'), label='특허 실적 (최근 3년)',
                                    tab_id='patents'),
                            dbc.Tab(html.Div(id='tab-publications'), label='논문 실적',
                                    tab_id='publications'),
                            dbc.Tab(html.Div(id='tab-transfer'), label='기술 이전 실적',
                                    tab_id='transfer'),
                            dbc.Tab(html.Div(id='tab-comments'), label='부서장 코멘트',
                                    tab_id='comments'),
                        ],
                        id='detail-tabs',
                        active_tab='patents',
                        className='mb-2',
                    )
                ),
                className='shadow-sm',
            ),
        ]
    )


# ─── 콜백: 프로필 헤더 + 평가차트 + 인센티브 ────────────────────────────────

@callback(
    Output('profile-header', 'children'),
    Output('eval-chart', 'figure'),
    Output('incentive-cards', 'children'),
    Output('leadership-year', 'options'),
    Output('leadership-year', 'value'),
    Input('researcher-select', 'value'),
)
def update_profile(rid):
    if not rid:
        empty = go.Figure()
        return dbc.CardBody('연구원을 선택하세요.'), empty, html.Div(), [], None

    res_df = _r('researchers')
    eva_df = _r('evaluations')
    edu_df = _r('education')
    inc_df = _r('incentive_selection')
    lea_df = _r('leadership')

    row = res_df[res_df['researcher_id'] == rid].iloc[0] if not res_df.empty else None
    if row is None:
        empty = go.Figure()
        return dbc.CardBody('데이터 없음'), empty, html.Div(), [], None

    # ── 프로필 헤더 ──
    edu_rows = edu_df[edu_df['researcher_id'] == rid] if not edu_df.empty else pd.DataFrame()
    edu_items = []
    for deg in DEGREE_ORDER:
        d = edu_rows[edu_rows['degree'] == deg]
        if not d.empty:
            e = d.iloc[0]
            edu_items.append(
                html.Li(
                    f'{deg} — {e["major"]}, {e["school"]} ({int(e["graduation_year"])})',
                    className='small text-muted mb-0',
                )
            )

    header_body = dbc.CardBody(
        dbc.Row(
            [
                dbc.Col(_avatar(row['name']), width='auto', className='pe-3'),
                dbc.Col(
                    [
                        html.H5(row['name'], className='fw-bold mb-1'),
                        html.Div(
                            [
                                dbc.Badge(row['department'], color='primary', className='me-1'),
                                dbc.Badge(row['position'], color='secondary', className='me-1'),
                                dbc.Badge(f"입사 {int(row['hire_year'])}년", color='light',
                                          text_color='dark'),
                            ],
                            className='mb-2',
                        ),
                        html.Ul(edu_items, className='ps-3 mb-0', style={'listStyle': 'none'}),
                    ]
                ),
            ],
            align='center',
        )
    )

    # ── 평가 차트 ──
    ev = eva_df[eva_df['researcher_id'] == rid].sort_values('year') if not eva_df.empty else pd.DataFrame()
    eval_fig = go.Figure()
    if not ev.empty:
        bar_colors = [GRADE_COLOR.get(g, '#aaa') for g in ev['grade']]
        eval_fig.add_trace(go.Bar(
            x=ev['year'].astype(str),
            y=ev['score'],
            marker_color=bar_colors,
            text=ev.apply(lambda r: f"{r['score']:.0f}({r['grade']})", axis=1),
            textposition='outside',
            hovertemplate='%{x}년: %{y}점<extra></extra>',
        ))
        eval_fig.update_layout(
            yaxis=dict(range=[0, 110], gridcolor='#eeeeee', title='점수'),
            xaxis_title=None,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=40, r=10, t=10, b=30),
            bargap=0.4,
            showlegend=False,
        )
        # 등급 범례 주석
        for grade, color in GRADE_COLOR.items():
            if grade == '-':
                continue
            eval_fig.add_annotation(
                text=f'<span style="color:{color}">■</span> {grade}등급',
                xref='paper', yref='paper', x=1, y=1.05,
                showarrow=False, font=dict(size=9), align='right',
            )

    # ── 인센티브 ──
    inc = inc_df[inc_df['researcher_id'] == rid].sort_values('year', ascending=False) \
        if not inc_df.empty else pd.DataFrame()
    inc_items = []
    for year in [2024, 2023, 2022]:
        yr_row = inc[inc['year'] == year]
        if yr_row.empty:
            inc_items.append(
                dbc.Card(
                    dbc.CardBody(
                        dbc.Row([
                            dbc.Col(html.Span(f'{year}년', className='fw-semibold'), width='auto'),
                            dbc.Col(dbc.Badge('미선정', color='light', text_color='muted'),
                                    className='text-end'),
                        ], justify='between'),
                    ),
                    className='mb-2 border',
                )
            )
        else:
            r2 = yr_row.iloc[0]
            selected = r2.get('selected', False)
            if str(selected).lower() in ('true', '1', 'yes'):
                badge = dbc.Badge(r2.get('category', '선정'), color='success')
                note = r2.get('note', '')
            else:
                badge = dbc.Badge('미선정', color='light', text_color='muted')
                note = ''
            inc_items.append(
                dbc.Card(
                    dbc.CardBody(
                        dbc.Row([
                            dbc.Col(html.Span(f'{year}년', className='fw-semibold'), width='auto'),
                            dbc.Col([badge, html.Small(f' {note}', className='text-muted ms-1')],
                                    className='text-end'),
                        ], justify='between'),
                    ),
                    className='mb-2 border',
                )
            )

    # ── 리더십 연도 옵션 ──
    lea_years = sorted(lea_df[lea_df['researcher_id'] == rid]['year'].unique(), reverse=True) \
        if not lea_df.empty else []
    lea_options = [{'label': str(y), 'value': y} for y in lea_years]
    lea_default = lea_years[0] if lea_years else None

    return header_body, eval_fig, html.Div(inc_items), lea_options, lea_default


# ─── 콜백: 리더십 레이더 ─────────────────────────────────────────────────────

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
    vals = [row.get(d, 0) for d in dims]
    vals_c = vals + [vals[0]]
    labels_c = labels + [labels[0]]

    fig.add_trace(go.Scatterpolar(
        r=vals_c,
        theta=labels_c,
        fill='toself',
        fillcolor='rgba(30,58,95,0.15)',
        line=dict(color='#1e3a5f', width=2),
        hovertemplate='%{theta}: %{r:.0f}점<extra></extra>',
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=9)),
            angularaxis=dict(tickfont=dict(size=12, color='#333')),
        ),
        showlegend=False,
        margin=dict(l=60, r=60, t=20, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig


# ─── 콜백: 탭 콘텐츠 ────────────────────────────────────────────────────────

@callback(
    Output('tab-patents', 'children'),
    Output('tab-publications', 'children'),
    Output('tab-transfer', 'children'),
    Output('tab-comments', 'children'),
    Input('researcher-select', 'value'),
)
def update_tabs(rid):
    if not rid:
        empty = html.Div('연구원을 선택하세요.', className='text-muted p-3')
        return empty, empty, empty, empty

    # ── 특허 (최근 3년) ──
    pat_df = _r('patents')
    cutoff_year = str(datetime.now().year - 3 + 1)
    if not pat_df.empty:
        pat = pat_df[pat_df['researcher_id'] == rid].copy()
        pat_recent = pat[pat['application_date'].astype(str).str[:4] >= cutoff_year]
        app_cnt = len(pat_recent[pat_recent['status'] == '출원'])
        reg_cnt = len(pat_recent[pat_recent['status'] == '등록'])
        summary = dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H4(str(app_cnt), className='fw-bold text-primary mb-0'),
                html.Small('출원', className='text-muted'),
            ]), className='text-center border-0 bg-light'), md=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H4(str(reg_cnt), className='fw-bold text-success mb-0'),
                html.Small('등록', className='text-muted'),
            ]), className='text-center border-0 bg-light'), md=3),
        ], className='mb-3')
        rows = [html.Tr([
            html.Td(r['application_date'][:7] if r['application_date'] else '-'),
            html.Td(r['title']),
            html.Td(dbc.Badge('등록', color='success') if r['status'] == '등록'
                    else dbc.Badge('출원', color='primary')),
            html.Td(r['country']),
            html.Td(r['registration_date'][:7] if r.get('registration_date') else '-'),
        ]) for _, r in pat_recent.sort_values('application_date', ascending=False).iterrows()]
        table = dbc.Table([
            html.Thead(html.Tr([html.Th('출원일'), html.Th('발명 명칭'), html.Th('상태'),
                                html.Th('국내/해외'), html.Th('등록일')])),
            html.Tbody(rows),
        ], bordered=False, hover=True, responsive=True, size='sm', className='mb-0')
        patent_content = html.Div([summary, table])
    else:
        patent_content = html.Div('특허 데이터 없음', className='text-muted p-3')

    # ── 논문 ──
    pub_df = _r('publications')
    if not pub_df.empty:
        pub = pub_df[pub_df['researcher_id'] == rid].sort_values('pub_year', ascending=False)
        total = len(pub)
        corr = len(pub[pub['is_corresponding'] == True])
        pub_summary = dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H4(str(total), className='fw-bold text-primary mb-0'),
                html.Small('총 논문 수', className='text-muted'),
            ]), className='text-center border-0 bg-light'), md=3),
            dbc.Col(dbc.Card(dbc.CardBody([
                html.H4(str(corr), className='fw-bold text-warning mb-0'),
                html.Small('교신저자', className='text-muted'),
            ]), className='text-center border-0 bg-light'), md=3),
        ], className='mb-3')
        pub_rows = [html.Tr([
            html.Td(str(int(r['pub_year']))),
            html.Td(r['title'], style={'maxWidth': '340px', 'wordBreak': 'break-word'}),
            html.Td(r['journal'], className='small text-muted'),
            html.Td(f"{r['impact_factor']:.2f}"),
            html.Td(str(int(r['citation_count']))),
            html.Td(dbc.Badge('교신', color='warning', text_color='dark')
                    if r.get('is_corresponding') else ''),
        ]) for _, r in pub.iterrows()]
        pub_table = dbc.Table([
            html.Thead(html.Tr([html.Th('연도'), html.Th('제목'), html.Th('저널'),
                                html.Th('IF'), html.Th('피인용'), html.Th('')])),
            html.Tbody(pub_rows),
        ], bordered=False, hover=True, responsive=True, size='sm')
        pub_content = html.Div([pub_summary, pub_table])
    else:
        pub_content = html.Div('논문 데이터 없음', className='text-muted p-3')

    # ── 기술 이전 ──
    tt_df = _r('technology_transfer')
    if not tt_df.empty:
        tt = tt_df[tt_df['researcher_id'] == rid].sort_values('transfer_date', ascending=False)
        if tt.empty:
            tt_content = html.Div('기술 이전 실적 없음', className='text-muted p-3')
        else:
            total_amount = tt['amount'].sum()
            tt_summary = dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H4(str(len(tt)), className='fw-bold text-primary mb-0'),
                    html.Small('총 건수', className='text-muted'),
                ]), className='text-center border-0 bg-light'), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H4(f'{int(total_amount):,}만원', className='fw-bold text-success mb-0'),
                    html.Small('누적 금액', className='text-muted'),
                ]), className='text-center border-0 bg-light'), md=4),
            ], className='mb-3')
            tt_rows = [html.Tr([
                html.Td(str(r['transfer_date'])[:10]),
                html.Td(r['tech_name']),
                html.Td(r['recipient']),
                html.Td(r['transfer_type']),
                html.Td(f"{int(r['amount']):,}만원", className='text-end'),
            ]) for _, r in tt.iterrows()]
            tt_table = dbc.Table([
                html.Thead(html.Tr([html.Th('이전일'), html.Th('기술명'), html.Th('거래처'),
                                    html.Th('유형'), html.Th('금액', className='text-end')])),
                html.Tbody(tt_rows),
            ], bordered=False, hover=True, responsive=True, size='sm')
            tt_content = html.Div([tt_summary, tt_table])
    else:
        tt_content = html.Div('기술 이전 데이터 없음', className='text-muted p-3')

    # ── 코멘트 ──
    cmt_df = _r('comments')
    if not cmt_df.empty:
        cmts = cmt_df[cmt_df['researcher_id'] == rid].sort_values('year', ascending=False)
    else:
        cmts = pd.DataFrame()

    comment_cards = []
    for _, c in cmts.iterrows():
        comment_cards.append(
            dbc.Card(
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col(html.Span(f'{int(c["year"])}년', className='fw-bold'), width='auto'),
                        dbc.Col(
                            [
                                dbc.Badge('강점: ', color='success', className='me-1'),
                                html.Small(str(c.get('strengths', '')), className='text-muted'),
                            ],
                        ),
                    ], align='center', className='mb-2'),
                    html.P(str(c.get('comment_summary', '')), className='small mb-1'),
                    html.Small(
                        ['개선점: ', html.Span(str(c.get('improvements', '')), className='text-muted')],
                        className='fst-italic',
                    ),
                ]),
                className='mb-2 border',
            )
        )

    # 코멘트 직접 입력 폼
    comment_form = dbc.Card(
        dbc.CardBody([
            html.P('코멘트 직접 입력', className='fw-semibold small text-muted mb-2'),
            dbc.Row([
                dbc.Col(
                    dcc.Dropdown(
                        id='comment-year',
                        options=[{'label': str(y), 'value': y} for y in range(2024, 2019, -1)],
                        value=2024,
                        clearable=False,
                        style={'width': '120px'},
                    ),
                    width='auto',
                ),
            ], className='mb-2'),
            dbc.Textarea(
                id='comment-text',
                placeholder='부서장 코멘트를 입력하세요...',
                rows=4,
                className='mb-2',
            ),
            dbc.Button('저장', id='comment-save-btn', color='primary', size='sm'),
            html.Div(id='comment-status', className='mt-2 small'),
        ]),
        className='border-0 bg-light',
    )

    cmt_content = html.Div([html.Div(comment_cards), html.Hr(), comment_form])

    return patent_content, pub_content, tt_content, cmt_content


# ─── 콜백: 코멘트 저장 ──────────────────────────────────────────────────────

@callback(
    Output('comment-status', 'children'),
    Input('comment-save-btn', 'n_clicks'),
    State('researcher-select', 'value'),
    State('comment-year', 'value'),
    State('comment-text', 'value'),
    prevent_initial_call=True,
)
def save_comment(n_clicks, rid, year, text):
    if not rid or not year or not text or not text.strip():
        return dbc.Alert('연구원, 연도, 코멘트를 모두 입력하세요.', color='warning', className='py-1 px-2 mb-0')

    path = os.path.join(DATA_DIR, 'comments.csv')
    try:
        if os.path.exists(path):
            df = pd.read_csv(path, encoding='utf-8-sig')
        else:
            df = pd.DataFrame(columns=['researcher_id', 'year', 'comment_raw',
                                       'comment_summary', 'strengths', 'improvements'])

        mask = (df['researcher_id'] == rid) & (df['year'] == year)
        summary = text[:120] + ('...' if len(text) > 120 else '')
        new_row = {
            'researcher_id': rid, 'year': year,
            'comment_raw': text, 'comment_summary': summary,
            'strengths': '', 'improvements': '',
        }
        if mask.any():
            for k, v in new_row.items():
                df.loc[mask, k] = v
        else:
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

        df.to_csv(path, index=False, encoding='utf-8-sig')
        return dbc.Alert('저장 완료', color='success', className='py-1 px-2 mb-0')
    except Exception as e:
        return dbc.Alert(f'저장 실패: {e}', color='danger', className='py-1 px-2 mb-0')
