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
    return html.Div([
        dbc.Alert(
            f"후보 과제 {result.get('candidates_considered', 0)}건을 대상으로 비교했습니다"
            f"(A: 과제 분석 기반, B: 배정 인력 전문성 기반 — 데이터가 없는 쪽은 개별 표시).",
            color='info', className='mb-3',
        ),
        html.H6('대상 인원', className='fw-bold mb-2'),
        _roster_table(roster),
        html.H6('추천 결과', className='fw-bold mb-2'),
        html.Div([_person_card(by_id.get(rid, {'researcher_id': rid}), res) for rid, res in results.items()]),
    ])


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
                                      placeholder='부서(플랫폼/팀) 선택', clearable=True), md=4),
                dbc.Col(dcc.Dropdown(id='jm-project-select', options=[],
                                      placeholder='종료 예정 과제 선택', clearable=True), md=8),
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
def _update_exclude_project_options(_excluded_dept):
    # 제외 과제 목록은 전체 과제(부서 선택과 무관) — 부서 제외와 개별 과제
    # 제외는 서로 독립적인 조건으로 합쳐진다(services/job_market.py 참고).
    return [{'label': p, 'value': p} for p in jm.list_projects()]


@callback(
    Output('jm-result', 'children'),
    Input('jm-run-btn', 'n_clicks'),
    State('jm-mode', 'value'),
    State('jm-project-select', 'value'),
    State('jm-individual-query', 'value'),
    State('jm-exclude-dept', 'value'),
    State('jm-exclude-project', 'value'),
    prevent_initial_call=True,
)
def _run(n_clicks, mode, project_name, individual_query, excluded_depts, excluded_projects):
    if not n_clicks:
        return dash.no_update
    excluded_depts = excluded_depts or []
    excluded_projects = excluded_projects or []

    if mode == _MODE_INDIVIDUAL:
        if not (individual_query or '').strip():
            return dbc.Alert('이름 또는 사번을 입력해주세요.', color='warning')
        result = jm.run_individual_search(individual_query.strip(), excluded_depts, excluded_projects)
    else:
        if not project_name:
            return dbc.Alert('종료 예정 과제를 선택해주세요.', color='warning')
        result = jm.run_project_search(project_name, excluded_depts, excluded_projects)

    return _render_result(result)
