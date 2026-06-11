"""
화면 2: 연구원 개별 프로필
"""

from datetime import datetime

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, no_update

from components.detail_tabs import (
    patents_tab,
    publications_tab,
    technology_transfer_tab,
)
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
    transfer_block,
)
from services.comments import upsert_comment
from services.data_store import read_processed, read_profile_tables

dash.register_page(
    __name__,
    path='/researcher-profile',
    name='연구원 프로필',
    title='연구원 개별 프로필',
)

CURRENT_YEAR = datetime.now().year


def layout():
    options, default = _researcher_options()

    return html.Div([
        dcc.Location(id='profile-url', refresh=False),
        html.H5(
            [html.I(className='bi bi-person-badge-fill me-2 text-primary'), '연구원 개별 프로필'],
            className='fw-bold mb-3 mt-1',
        ),
        _selector_card(options, default),
        dbc.Row([
            _left_column(),
            _middle_column(),
            _right_column(),
        ], className='g-3 mb-3'),
        _detail_tabs_card(),
    ])


def _researcher_options():
    try:
        res_df = read_processed('researchers')
        options = [
            {'label': f'{row["name"]}  ({row["department"]} / {row["position"]})',
             'value': row['researcher_id']}
            for _, row in res_df.sort_values('department').iterrows()
        ]
        return options, options[0]['value'] if options else None
    except Exception:
        return [], None


def _selector_card(options, default):
    return dbc.Card(
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
    )


def _left_column():
    return dbc.Col([
        _card(html.Div(id='photo-block', className='d-flex flex-column align-items-center py-1'), body_class='p-2'),
        _card([
            html.P('양성 이력', className='fw-semibold text-muted small mb-2'),
            html.Div(id='nurturing-block'),
            html.Hr(className='my-2'),
            html.P('시상 이력', className='fw-semibold text-muted small mb-2'),
            html.Div(id='award-block'),
        ], body_class='p-2', card_class='shadow-sm'),
    ], md=3)


def _middle_column():
    return dbc.Col([
        dbc.Row([
            dbc.Col(
                _card([
                    html.P('학력', className='fw-semibold text-muted small mb-2'),
                    html.Div(id='education-block'),
                ], body_class='p-3', card_class='shadow-sm h-100'),
                md=7,
            ),
            dbc.Col(
                _card([
                    html.P('평가 / 인센티브 이력', className='fw-semibold text-muted small mb-2'),
                    html.Div(id='eval-incentive-block'),
                ], body_class='p-3', card_class='shadow-sm h-100'),
                md=5,
            ),
        ], className='g-2 mb-2'),
        _card([
            html.P('사내 발령 이력 (프로젝트 수행 이력)', className='fw-semibold text-muted small mb-2'),
            html.Div(id='transfer-block'),
        ], body_class='p-3', card_class='shadow-sm'),
    ], md=4)


def _right_column():
    return dbc.Col([
        _card([
            dbc.Row([
                dbc.Col(html.P('리더십 진단 그래프', className='fw-semibold text-muted small mb-0')),
                dbc.Col(dcc.Dropdown(id='leadership-year', clearable=False,
                                     style={'width': '110px'}), width='auto'),
            ], align='center', className='mb-1'),
            dcc.Graph(id='leadership-chart', style={'height': '240px'},
                      config={'displayModeBar': False}),
        ], body_class='p-3'),
        _card([
            html.P('인물 코멘트 (부서장 / 부서원)', className='fw-semibold text-muted small mb-2'),
            html.Div(id='comments-block', style={'maxHeight': '220px', 'overflowY': 'auto'}),
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
        ], body_class='p-3', card_class='shadow-sm'),
    ], md=5)


def _detail_tabs_card():
    return dbc.Card(
        dbc.CardBody(
            dbc.Tabs([
                dbc.Tab(html.Div(id='tab-publications'), label='논문 실적', tab_id='pub'),
                dbc.Tab(html.Div(id='tab-patents'), label='특허 실적 (최근 3년)', tab_id='pat'),
                dbc.Tab(html.Div(id='tab-transfer'), label='기술 이전 실적', tab_id='tt'),
            ], id='detail-tabs', active_tab='pub', className='mb-2'),
        ),
        className='shadow-sm',
    )


def _card(children, *, body_class='p-2', card_class='shadow-sm mb-2'):
    return dbc.Card(dbc.CardBody(children, className=body_class), className=card_class)


def _empty_profile_output():
    prompt = html.Div('연구원을 선택하세요.', className='text-muted p-3')
    return (
        avatar('?'), html.Div(), html.Div(), html.Div(), html.Div(), html.Div(),
        [], None, html.Div(), prompt, prompt, prompt,
    )


@callback(
    Output('photo-block', 'children'),
    Output('education-block', 'children'),
    Output('eval-incentive-block', 'children'),
    Output('nurturing-block', 'children'),
    Output('award-block', 'children'),
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
    if not rid:
        return _empty_profile_output()

    tables = read_profile_tables()
    researchers = tables['researchers']
    if researchers.empty:
        return _empty_profile_output()

    rid = str(rid).zfill(8)
    rows = researchers[researchers['researcher_id'] == rid]
    if rows.empty:
        return _empty_profile_output()
    researcher = rows.iloc[0]
    years = [CURRENT_YEAR - 2, CURRENT_YEAR - 1, CURRENT_YEAR]
    leadership_options, leadership_default = leadership_year_options(tables['leadership'], rid)

    return (
        photo_block(rid, str(researcher.get('name', '')), researcher, CURRENT_YEAR),
        education_block(tables['education'], rid),
        evaluation_incentive_block(tables['evaluations'], tables['incentive_selection'], rid, years),
        nurturing_block(tables['nurturing'], rid),
        award_block(tables['awards'], rid),
        transfer_block(tables['transfers'], rid),
        leadership_options,
        leadership_default,
        comments_block(tables['comments'], rid),
        publications_tab(tables['publications'], rid),
        patents_tab(tables['patents'], rid),
        technology_transfer_tab(tables['technology_transfer'], rid),
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


@callback(
    Output('researcher-select', 'value'),
    Input('profile-url', 'search'),
)
def _set_researcher_from_url(search):
    """연구원 목록에서 행 클릭 시 ?id= 쿼리 파라미터로 연구원 자동 선택."""
    if not search:
        return no_update
    from urllib.parse import parse_qs
    params = parse_qs(search.lstrip('?'))
    rid = params.get('id', [None])[0]
    if not rid:
        return no_update
    try:
        res_df = read_processed('researchers')
        if rid in res_df['researcher_id'].values:
            return rid
    except Exception:
        pass
    return no_update
