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
    tasks_block,
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


def _load_selector_data():
    try:
        res_df = read_processed('researchers').sort_values(['department', 'name'])
        if res_df.empty:
            return [], [], {}

        def _opt(row):
            return {
                'label': f'{row["name"]}  ({row["researcher_id"]}) — {row["position"]}',
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
            _left_column(),
            _middle_column(),
            _right_column(),
        ], className='g-3 mb-3'),
        dbc.Row([
            _detail_tabs_col(),
            _comments_col(),
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
            html.P('과제 수행 이력', className='fw-semibold text-muted small mb-2'),
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
        ], body_class='p-3', card_class='shadow-sm mb-0'),
    ], md=5)


def _detail_tabs_col():
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                dbc.Tabs([
                    dbc.Tab(html.Div(id='tab-publications'), label='논문 실적', tab_id='pub'),
                    dbc.Tab(html.Div(id='tab-patents'), label='특허 실적 (최근 3년)', tab_id='pat'),
                    dbc.Tab(html.Div(id='tab-transfer'), label='기술 이전 실적', tab_id='tt'),
                ], id='detail-tabs', active_tab='pub', className='mb-2'),
            ),
            className='shadow-sm h-100',
        ),
        md=7,
    )


def _comments_col():
    return dbc.Col(
        _card([
            html.P('인물 코멘트 (부서장 / 부서원)', className='fw-semibold text-muted small mb-2'),
            html.Div(id='comments-block', style={'maxHeight': '280px', 'overflowY': 'auto'}),
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
        ], body_class='p-3', card_class='shadow-sm mb-0 h-100'),
        md=5,
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
        years = [CURRENT_YEAR - 2, CURRENT_YEAR - 1, CURRENT_YEAR]
        leadership_options, leadership_default = leadership_year_options(tables['leadership'], rid)

        return (
            photo_block(rid, str(researcher.get('name', '')), researcher, CURRENT_YEAR),
            education_block(tables['education'], rid),
            evaluation_incentive_block(tables['evaluations'], tables['incentive_selection'], rid, years),
            nurturing_block(tables['nurturing'], rid),
            award_block(tables['awards'], rid),
            tasks_block(tables['tasks'], rid) if not tables['tasks'].empty
            else transfer_block(tables['transfers'], rid),
            leadership_options,
            leadership_default,
            comments_block(tables['comments'], rid),
            publications_tab(tables['publications'], rid),
            patents_tab(tables['patents'], rid),
            technology_transfer_tab(tables['technology_transfer'], rid),
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
            avatar('?'), err_div, html.Div(), html.Div(), html.Div(), html.Div(),
            [], None, html.Div(), err_div, html.Div(), html.Div(),
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
