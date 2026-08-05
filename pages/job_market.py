"""
화면: JOB Market — 과제가 종료된다는 가정하에, 그 과제원(또는 개인 1명)이
보유 전문성 기준으로 어떤 다른 과제에 참여 가능한지 추천한다. 상세 로직은
services/job_market.py 참고.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from services import job_market as jm

dash.register_page(
    __name__,
    path='/job-market',
    name='JOB Market',
    title='JOB Market',
)

_MODE_PROJECT = 'project'
_MODE_INDIVIDUAL = 'individual'


def _score_badge(label: str, score):
    if score is None:
        return dbc.Badge(f'{label}: 데이터 없음', color='light', text_color='muted', className='me-1 border')
    return dbc.Badge(f'{label}: {round(score * 100)}%', color='info', className='me-1')


def _recommendation_row(rec: dict):
    return html.Div([
        html.Div([
            html.Span(rec.get('project_name', ''), className='fw-semibold me-2'),
            html.Span(rec.get('dep_name', ''), className='text-muted small me-2'),
            _score_badge('A', rec.get('score_a')),
            _score_badge('B', rec.get('score_b')),
        ]),
        html.Div(rec.get('reason', '') or '(근거 없음)', className='text-muted small mb-2'),
    ], className='mb-2 pb-2 border-bottom')


def _person_card(person: dict, result: dict):
    recs = result.get('recommendations') or []
    note = result.get('note') or ''
    if recs:
        body = html.Div([_recommendation_row(r) for r in recs])
    else:
        body = html.Div(note or '참여 가능한 과제를 찾지 못했습니다.', className='text-muted small')
    return dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Span(f"{person.get('name', '')}({person.get('researcher_id', '')})",
                          className='fw-bold me-2'),
                html.Span(f"{person.get('department', '')} · {person.get('org_code', '')}",
                          className='text-muted small'),
            ], className='mb-2'),
            body,
        ]),
        className='mb-3',
    )


def _roster_table(roster: list):
    if not roster:
        return html.Div('명단이 없습니다.', className='text-muted small')
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('사번'), html.Th('성명'), html.Th('부서'), html.Th('과제'),
            html.Th('CL/년차'), html.Th('학력/전공'), html.Th('나이'),
        ])),
        html.Tbody([
            html.Tr([
                html.Td(p['researcher_id']), html.Td(p['name']), html.Td(p['department']),
                html.Td(p['org_code']), html.Td(p['position_year']), html.Td(p['degree_major']),
                html.Td(p['age']),
            ]) for p in roster
        ]),
    ], bordered=False, hover=True, size='sm', className='mb-3')


def _render_result(result: dict):
    if result.get('error'):
        return dbc.Alert(result['error'], color='warning')
    roster = result.get('roster') or []
    results = result.get('results') or {}
    by_id = {p['researcher_id']: p for p in roster}
    project_names = result.get('project_names') or []
    header_line = (
        f"선택한 과제({', '.join(project_names)})를 기준으로, " if project_names else ''
    ) + (
        f"후보 과제 {result.get('candidates_considered', 0)}건을 대상으로 비교했습니다"
        f"(A: 과제 분석 기반, B: 배정 인력 전문성 기반 — 데이터가 없는 쪽은 개별 표시)."
    )
    run_at = result.get('run_at', '')
    return html.Div([
        dbc.Alert([
            html.Div(header_line),
            (html.Div(f'실행 시각: {run_at}', className='small text-muted') if run_at else None),
        ], color='info', className='mb-3'),
        html.H6('대상 인원', className='fw-bold mb-2'),
        _roster_table(roster),
        html.H6('추천 결과', className='fw-bold mb-2'),
        html.Div([_person_card(by_id.get(rid, {'researcher_id': rid}), res) for rid, res in results.items()]),
    ])


def _history_table():
    rows = jm.list_history()
    if not rows:
        return html.Div('검색 이력이 없습니다.', className='text-muted small')
    mode_label = {'project': '과제 단위', 'individual': '개인별'}
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('실행일시'), html.Th('구분'), html.Th('대상'),
            html.Th('인원'), html.Th('후보 과제'), html.Th(''),
        ])),
        html.Tbody([
            html.Tr([
                html.Td(r['run_at']), html.Td(mode_label.get(r['mode'], r['mode'])), html.Td(r['label']),
                html.Td(str(r['target_count'])), html.Td(str(r['candidates_considered'])),
                html.Td(dbc.Button('보기', id={'type': 'jm-history-view', 'file': r['file']},
                                    color='link', size='sm', n_clicks=0)),
            ]) for r in rows
        ]),
    ], bordered=False, hover=True, size='sm', className='mb-0')


def layout(**_kwargs):
    department_options = [{'label': d, 'value': d} for d in jm.list_departments()]
    return html.Div([
        html.H5(
            [html.I(className='bi bi-signpost-split me-2 text-primary'), 'JOB Market'],
            className='fw-bold mb-1 mt-1',
        ),
        html.Div(
            '특정 과제가 종료된다고 가정할 때, 그 과제원(또는 개인 1명)이 보유 전문성 기준으로 '
            '참여 가능한 다른 과제를 추천합니다.',
            className='text-muted small mb-3',
        ),

        dbc.RadioItems(
            id='jm-mode', inline=True, value=_MODE_PROJECT,
            options=[
                {'label': '종료 예정 과제 단위', 'value': _MODE_PROJECT},
                {'label': '개인별 검색', 'value': _MODE_INDIVIDUAL},
            ],
            className='mb-2',
        ),

        html.Div(
            dbc.Row([
                dbc.Col(dcc.Dropdown(id='jm-project-dept', options=department_options,
                                      placeholder='부서(플랫폼/팀) 선택(복수 선택 가능)', multi=True), md=4),
                dbc.Col(dcc.Dropdown(id='jm-project-select', options=[],
                                      placeholder='종료 예정 과제 선택(복수 선택 가능)', multi=True), md=8),
            ], className='g-2 mb-2'),
            id='jm-project-mode-row',
        ),
        html.Div(
            dbc.Row([
                dbc.Col(dcc.Input(id='jm-individual-query', type='text', placeholder='이름 또는 사번',
                                   className='form-control'), md=12),
            ], className='g-2 mb-2'),
            id='jm-individual-mode-row', style={'display': 'none'},
        ),

        html.Div('참여 가능한 과제에서 제외', className='fw-bold small mb-1 mt-2'),
        dbc.Row([
            dbc.Col(dcc.Dropdown(id='jm-exclude-dept', options=department_options,
                                  placeholder='제외할 부서(복수 선택)', multi=True), md=6),
            dbc.Col(dcc.Dropdown(id='jm-exclude-project', options=[],
                                  placeholder='제외할 과제(복수 선택)', multi=True), md=6),
        ], className='g-2 mb-3'),

        dbc.Button([html.I(className='bi bi-search me-1'), '검색'],
                   id='jm-run-btn', color='primary', n_clicks=0, className='mb-3'),

        dcc.Loading(html.Div(id='jm-result')),
        dcc.Store(id='jm-history-refresh', data=0),
        html.Hr(),
        html.H6('검색 이력', className='fw-bold mb-2'),
        html.Div(id='jm-history-table', children=_history_table()),
    ], className='mb-3')


@callback(
    Output('jm-project-mode-row', 'style'),
    Output('jm-individual-mode-row', 'style'),
    Input('jm-mode', 'value'),
)
def _toggle_mode(mode):
    if mode == _MODE_INDIVIDUAL:
        return {'display': 'none'}, {'display': 'block'}
    return {'display': 'block'}, {'display': 'none'}


@callback(
    Output('jm-project-select', 'options'),
    Input('jm-project-dept', 'value'),
)
def _update_project_options(department):
    return [{'label': p, 'value': p} for p in jm.list_projects(department)]


@callback(
    Output('jm-exclude-project', 'options'),
    Input('jm-exclude-dept', 'value'),
)
def _update_exclude_project_options(excluded_dept):
    # "종료 예정 과제" 선택과 동일하게, 부서를 고르면 그 부서의 과제만 보이도록
    # 좁힌다. 부서 자체를 제외 조건으로 쓰는 것과는 별개(services/job_market.py의
    # _expand_excluded_projects — 부서 제외와 개별 과제 제외는 계속 독립적으로
    # 합쳐진다), 여기서는 드롭다운에 보여줄 옵션만 좁힌다.
    return [{'label': p, 'value': p} for p in jm.list_projects(excluded_dept)]


@callback(
    Output('jm-result', 'children'),
    Output('jm-history-refresh', 'data'),
    Input('jm-run-btn', 'n_clicks'),
    State('jm-mode', 'value'),
    State('jm-project-select', 'value'),
    State('jm-individual-query', 'value'),
    State('jm-exclude-dept', 'value'),
    State('jm-exclude-project', 'value'),
    State('jm-history-refresh', 'data'),
    prevent_initial_call=True,
)
def _run(n_clicks, mode, project_names, individual_query, excluded_depts, excluded_projects, refresh_token):
    if not n_clicks:
        return dash.no_update, dash.no_update
    excluded_depts = excluded_depts or []
    excluded_projects = excluded_projects or []
    project_names = project_names or []

    if mode == _MODE_INDIVIDUAL:
        if not (individual_query or '').strip():
            return dbc.Alert('이름 또는 사번을 입력해주세요.', color='warning'), dash.no_update
        result = jm.run_individual_search(individual_query.strip(), excluded_depts, excluded_projects)
    else:
        if not project_names:
            return dbc.Alert('종료 예정 과제를 선택해주세요.', color='warning'), dash.no_update
        result = jm.run_project_search(project_names, excluded_depts, excluded_projects)

    refresh = (refresh_token or 0) + 1 if not result.get('error') else dash.no_update
    return _render_result(result), refresh


@callback(
    Output('jm-history-table', 'children'),
    Input('jm-history-refresh', 'data'),
)
def _refresh_history_table(_refresh_token):
    return _history_table()


@callback(
    Output('jm-result', 'children', allow_duplicate=True),
    Input({'type': 'jm-history-view', 'file': dash.ALL}, 'n_clicks'),
    State({'type': 'jm-history-view', 'file': dash.ALL}, 'id'),
    prevent_initial_call=True,
)
def _view_history(n_clicks_list, ids):
    triggered_id = dash.ctx.triggered_id
    if not triggered_id:
        return dash.no_update
    idx = next((i for i, d in enumerate(ids) if d == triggered_id), None)
    if idx is None or not n_clicks_list[idx]:
        return dash.no_update
    result = jm.load_history(triggered_id['file'])
    if not result:
        return dbc.Alert('이력을 불러오지 못했습니다.', color='danger')
    return _render_result(result)
