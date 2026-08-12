"""
화면 2: 연구원 개별 프로필
"""

from datetime import datetime

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, no_update

from components.detail_tabs import llm_summary_block, owned_expertise_block
from components.profile_sections import (
    avatar,
    award_block,
    comments_block,
    education_block,
    evaluation_incentive_block,
    leadership_figure,
    leadership_year_options,
    nurturing_block,
    photo_block,
)
from components.timeline_view import timeline_view
from services.comments import upsert_comment
from services.data_store import (
    read_expertise_profiles,
    read_processed,
    read_profile_tables,
    read_similar_researchers,
)
from services.evaluations import evaluation_years

dash.register_page(
    __name__,
    path='/researcher-profile',
    name='연구원 프로필',
    title='연구원 개별 프로필',
)

CURRENT_YEAR = datetime.now().year

# 좌(사진+정보 / 보유 전문성 / 인물 코멘트·리더십, 세로 스택)/우(타임라인) 영역의
# 절대 높이 — 좌측 3블록 합계와 우측 타임라인 카드 높이가 같아 하단이 맞도록 한다.
# 블록마다 각각 고정 높이를 갖고, 넘치는 내용은 내부 스크롤로 처리.
PHOTO_INFO_HEIGHT = 350
TABS_SECTION_HEIGHT = 350
COMMENTS_HEIGHT = 400
SECTION_HEIGHT = PHOTO_INFO_HEIGHT + TABS_SECTION_HEIGHT + COMMENTS_HEIGHT
TABS_CONTENT_HEIGHT = 260

# 우측 타임라인 카드 맨 위에 얹는 LLM 요약 블록의 고정 높이. 나머지는 타임라인이
# flex:1로 채운다(SECTION_HEIGHT 총합 자체는 바꾸지 않아 좌측 스택과 하단이 계속 맞음).
LLM_SUMMARY_HEIGHT = 150


def _load_selector_data():
    try:
        res_df = read_processed('researchers').sort_values(['department', 'name'])
        if res_df.empty:
            return [], [], {}

        def _opt(row):
            dept = str(row.get('department', '') or '').strip()
            dept_suffix = f' [{dept}]' if dept else ''
            return {
                'label': f'{row["name"]}{dept_suffix}  ({row["researcher_id"]}) — {row["position"]}',
                'value': row['researcher_id'],
            }

        all_opts = [_opt(row) for _, row in res_df.iterrows()]
        by_dept = {
            dept: [_opt(row) for _, row in grp.iterrows()]
            for dept, grp in res_df.groupby('department', sort=True)
        }
        dept_opts = [{'label': '전체', 'value': ''}] + [
            {'label': d, 'value': d} for d in sorted(by_dept)
        ]
        return dept_opts, all_opts, by_dept
    except Exception:
        return [], [], {}


def layout(id=None, **_kwargs):
    dept_opts, all_opts, by_dept = _load_selector_data()
    default_rid = all_opts[0]['value'] if all_opts else None
    default_dept = ''
    res_opts = all_opts

    if id is not None and any(o['value'] == id for o in all_opts):
        default_rid = id
        try:
            res_df = read_processed('researchers')
            match = res_df[res_df['researcher_id'] == id]
            if not match.empty:
                default_dept = str(match.iloc[0].get('department', ''))
                res_opts = by_dept.get(default_dept, all_opts)
        except Exception:
            pass

    return html.Div([
        html.H5(
            [html.I(className='bi bi-person-badge-fill me-2 text-primary'), '연구원 개별 프로필'],
            className='fw-bold mb-3 mt-1',
        ),
        _selector_card(dept_opts, res_opts, default_dept, default_rid),
        dbc.Row([
            _left_stack_col(),
            _right_column(),
        ], className='g-3 mb-3'),
    ])


def _selector_card(dept_opts, res_opts, default_dept, default_rid):
    return dbc.Card(
        dbc.CardBody(
            dbc.Row([
                dbc.Col([
                    dbc.Label('조직', className='fw-semibold small text-muted mb-1'),
                    dcc.Dropdown(
                        id='dept-select',
                        options=dept_opts,
                        value=default_dept or None,
                        clearable=True,
                        placeholder='전체',
                        style={'minWidth': '200px'},
                    ),
                ], width='auto'),
                dbc.Col([
                    dbc.Label('연구원  (이름 · 사번 검색)', className='fw-semibold small text-muted mb-1'),
                    dcc.Dropdown(
                        id='researcher-select',
                        options=res_opts,
                        value=default_rid,
                        clearable=False,
                        placeholder='이름 또는 사번으로 검색...',
                        style={'minWidth': '380px'},
                    ),
                ]),
            ], align='end', className='g-3'),
        ),
        className='mb-3 shadow-sm',
    )


def _left_stack_col():
    """사진+정보 / 보유 전문성 / 인물 코멘트·리더십 카드를 세로로 쌓은 왼쪽 묶음.
    셋 다 각각 절대값(PHOTO_INFO_HEIGHT / TABS_SECTION_HEIGHT / COMMENTS_HEIGHT,
    합계 SECTION_HEIGHT)으로 높이를 고정해, 오른쪽 타임라인 카드(전체 높이를 씀)와
    하단이 맞도록 한다. 넘치는 내용은 내부 스크롤."""
    return dbc.Col(
        html.Div([
            html.Div(_photo_info_card(),
                     style={'flex': '0 0 auto', 'height': f'{PHOTO_INFO_HEIGHT}px', 'overflow': 'hidden'}),
            html.Div(_owned_expertise_stack_card(),
                     style={'flex': '0 0 auto', 'height': f'{TABS_SECTION_HEIGHT}px', 'overflow': 'hidden'}),
            html.Div(_comments_card(),
                     style={'flex': '0 0 auto', 'height': f'{COMMENTS_HEIGHT}px', 'overflow': 'hidden'}),
        ], style={'height': f'{SECTION_HEIGHT}px', 'display': 'flex', 'flexDirection': 'column'}),
        md=6,
    )


def _photo_info_card():
    """사진(좌) + 학력/평가·인센티브/양성/시상(우) 정보를 세로선으로 구분한 하나의 카드."""
    return dbc.Card(
        dbc.CardBody(
            dbc.Row([
                dbc.Col(
                    html.Div(id='photo-block', className='d-flex flex-column align-items-center py-1'),
                    md=4, className='p-2',
                ),
                dbc.Col([
                    html.P('학력', className='section-label'),
                    html.Div(id='education-block'),
                    html.Hr(className='my-2'),
                    html.P('평가 / 인센티브 이력', className='section-label'),
                    html.Div(id='eval-incentive-block'),
                    html.Hr(className='my-2'),
                    html.P('양성 이력', className='section-label'),
                    html.Div(id='nurturing-block'),
                    html.Hr(className='my-2'),
                    html.P('시상 이력', className='section-label'),
                    html.Div(id='award-block'),
                ], md=8, className='p-3 border-start',
                   style={'maxHeight': f'{PHOTO_INFO_HEIGHT - 40}px', 'overflowY': 'auto'}),
            ], className='g-0 h-100'),
        ),
        className='shadow-sm profile-card h-100',
    )


def _owned_expertise_stack_card():
    return dbc.Card(
        dbc.CardBody([
            html.P('보유 전문성', style={'fontSize': '0.85rem', 'fontWeight': 600,
                                      'color': '#1d1d1f'}, className='mb-2'),
            html.Div(id='tab-expertise', style={'maxHeight': f'{TABS_CONTENT_HEIGHT}px', 'overflowY': 'auto'}),
        ]),
        className='shadow-sm profile-card h-100',
    )


def _right_column():
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.Div([
                    html.P('전문성 요약(LLM)', style={'fontSize': '0.85rem', 'fontWeight': 600,
                                            'color': '#1d1d1f'}, className='mb-1'),
                    html.Div(id='llm-summary-block', style={'maxHeight': f'{LLM_SUMMARY_HEIGHT - 28}px',
                                                             'overflowY': 'auto'}),
                ], style={'flex': '0 0 auto', 'height': f'{LLM_SUMMARY_HEIGHT}px',
                          'overflow': 'hidden', 'marginBottom': '8px'}),
                html.P('타임라인', style={'fontSize': '0.85rem', 'fontWeight': 600,
                                       'color': '#1d1d1f', 'flex': '0 0 auto'}, className='mb-2'),
                html.Div(id='tab-timeline', style={'flex': '1 1 auto', 'minHeight': '0', 'overflow': 'hidden'}),
            ], style={'height': '100%', 'display': 'flex', 'flexDirection': 'column'}),
            className='shadow-sm profile-card',
            style={'height': f'{SECTION_HEIGHT}px', 'overflow': 'hidden'},
        ),
        md=6,
    )


_COMMENTS_PANE_HEIGHT = COMMENTS_HEIGHT - 70   # 카드 패딩 + 탭 네비게이션 높이만큼 제외


def _comments_card():
    comments_pane = html.Div([
        html.Div(id='comments-block', style={'maxHeight': '200px', 'overflowY': 'auto'}),
        html.Hr(className='my-2'),
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
        dbc.Textarea(id='comment-text', placeholder='코멘트를 입력하세요...',
                     rows=3, className='mb-2'),
        dbc.Button('저장', id='comment-save-btn', color='primary', size='sm'),
        html.Div(id='comment-status', className='mt-2 small'),
    ], className='pt-3')

    leadership_pane = html.Div([
        dbc.Row([
            dbc.Col(html.P('타인평균 대비 리더십 진단', className='section-label mb-0')),
            dbc.Col(dcc.Dropdown(id='leadership-year', clearable=False,
                                 style={'width': '110px'}), width='auto'),
        ], align='center', className='mb-1 pt-3'),
        dcc.Graph(id='leadership-chart', style={'height': '260px'},
                  config={'displayModeBar': False}),
    ])

    return dbc.Card(
        dbc.CardBody(
            dbc.Tabs([
                dbc.Tab(comments_pane, label='인물 코멘트 (부서장 · 부서원)', tab_id='comments'),
                dbc.Tab(leadership_pane, label='리더십 진단', tab_id='leadership'),
            ], id='bottom-right-tabs', active_tab='comments'),
            style={'maxHeight': f'{_COMMENTS_PANE_HEIGHT}px', 'overflowY': 'auto'},
        ),
        className='shadow-sm profile-card h-100',
    )


def _card(children, *, body_class='p-2', card_class='shadow-sm profile-card mb-2', body_style=None):
    return dbc.Card(dbc.CardBody(children, className=body_class, style=body_style), className=card_class)


def _empty_profile_output():
    prompt = html.Div('연구원을 선택하세요.', className='text-muted p-3')
    return (
        avatar('?'), html.Div(), html.Div(), html.Div(), html.Div(),
        [], None, html.Div(), prompt, prompt, prompt,
    )


@callback(
    Output('researcher-select', 'options'),
    Output('researcher-select', 'value'),
    Input('dept-select', 'value'),
    State('researcher-select', 'value'),
    prevent_initial_call=True,
)
def filter_by_dept(dept, current_rid):
    _, all_opts, by_dept = _load_selector_data()
    opts = by_dept.get(dept, all_opts) if dept else all_opts
    valid_ids = {o['value'] for o in opts}
    new_value = current_rid if current_rid in valid_ids else (opts[0]['value'] if opts else None)
    return opts, new_value


@callback(
    Output('photo-block', 'children'),
    Output('education-block', 'children'),
    Output('eval-incentive-block', 'children'),
    Output('nurturing-block', 'children'),
    Output('award-block', 'children'),
    Output('leadership-year', 'options'),
    Output('leadership-year', 'value'),
    Output('comments-block', 'children'),
    Output('llm-summary-block', 'children'),
    Output('tab-timeline', 'children'),
    Output('tab-expertise', 'children'),
    Input('researcher-select', 'value'),
)
def update_profile(rid):
    import sys
    if not rid:
        return _empty_profile_output()

    try:
        tables = read_profile_tables()
        researchers = tables['researchers']
        if researchers.empty:
            return _empty_profile_output()

        rid = str(rid).zfill(8)
        rows = researchers[researchers['researcher_id'] == rid]
        if rows.empty:
            return _empty_profile_output()
        researcher = rows.iloc[0]
        # 평가등급 표의 연도 열 — evaluations.csv가 생성될 때와 동일한 회계연도
        # 기준(매년 3월 시작, services.evaluations)이어야 CSV의 실제 컬럼과
        # 항상 맞아떨어진다(달력연도 CURRENT_YEAR를 그대로 쓰면 1~2월에 어긋남).
        salary_years, _half_years = evaluation_years()
        years = sorted(salary_years)
        leadership_options, leadership_default = leadership_year_options(tables['leadership'], rid)
        profile = read_expertise_profiles().get(rid)
        similar = read_similar_researchers().get(rid, {}).get('similar', [])
        name_map = researchers.set_index('researcher_id')['name'].to_dict()

        return (
            photo_block(rid, str(researcher.get('name', '')), researcher, CURRENT_YEAR),
            education_block(tables['education'], rid),
            evaluation_incentive_block(tables['evaluations'], tables['incentive_selection'], rid, years),
            nurturing_block(tables['nurturing'], rid),
            award_block(tables['awards'], rid),
            leadership_options,
            leadership_default,
            comments_block(tables['comments'], rid),
            llm_summary_block(profile, similar, name_map),
            timeline_view(tables['tasks'], tables['hr_orders'], tables['publications'],
                          tables['patents'], tables['job_profile'], tables['tasks_information'], rid),
            owned_expertise_block(tables['core_technology'], tables['tech_ownership'], rid),
        )
    except Exception as exc:
        import traceback
        print(f'[update_profile] ERROR for rid={rid!r}:', file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        err_div = html.Div(
            f'오류 발생: {exc}',
            className='text-danger small p-2',
        )
        return (
            avatar('?'), err_div, html.Div(), html.Div(), html.Div(),
            [], None, html.Div(), err_div, err_div, err_div,
        )


@callback(
    Output('leadership-chart', 'figure'),
    Input('researcher-select', 'value'),
    Input('leadership-year', 'value'),
)
def update_leadership(rid, year):
    rid = str(rid).zfill(8) if rid else rid
    return leadership_figure(read_processed('leadership'), rid, year)


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
    try:
        upsert_comment(rid, year, author_type, text.strip())
        return dbc.Alert('저장 완료', color='success', className='py-1 px-2 mb-0')
    except Exception as exc:
        return dbc.Alert(f'저장 실패: {exc}', color='danger', className='py-1 px-2 mb-0')
