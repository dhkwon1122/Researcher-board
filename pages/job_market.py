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


def _candidate_row(c: dict):
    return html.Div([
        html.Span(f"{c['name']}({c['researcher_id']})", className='me-2'),
        html.Span(f"{c['department']} · {c['org_code']}", className='text-muted small me-2'),
        dbc.Button('추가', id={'type': 'jm-add-candidate', 'rid': c['researcher_id']},
                   color='link', size='sm', n_clicks=0, className='py-0'),
    ], className='d-flex align-items-center mb-1')


def _selected_chip(c: dict):
    return dbc.Badge([
        f"{c['name']}({c['researcher_id']})",
        html.Span('×', id={'type': 'jm-remove-selected', 'rid': c['researcher_id']}, n_clicks=0,
                   className='ms-2', style={'cursor': 'pointer'}),
    ], color='secondary', className='p-2 me-1 mb-1')


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
        html.Div([
            dbc.Row([
                dbc.Col(dcc.Input(id='jm-individual-search-input', type='text', placeholder='이름 또는 사번 검색',
                                   className='form-control'), md=9),
                dbc.Col(dbc.Button('찾기', id='jm-individual-search-btn', color='secondary',
                                    n_clicks=0, className='w-100'), md=3),
            ], className='g-2 mb-2'),
            html.Div(id='jm-individual-candidates', className='mb-2'),
            html.Div('선택된 대상자', className='fw-bold small mb-1'),
            html.Div(id='jm-individual-selected-list',
                      children=html.Div('선택된 대상자가 없습니다. 위에서 검색해 추가해주세요.',
                                         className='text-muted small'),
                      className='mb-2'),
            dcc.Store(id='jm-individual-candidates-store', data=[]),
            dcc.Store(id='jm-individual-selected-store', data=[]),
        ], id='jm-individual-mode-row', style={'display': 'none'}),

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
    Output('jm-individual-candidates', 'children'),
    Output('jm-individual-candidates-store', 'data'),
    Input('jm-individual-search-btn', 'n_clicks'),
    Input('jm-individual-search-input', 'n_submit'),
    State('jm-individual-search-input', 'value'),
    prevent_initial_call=True,
)
def _search_candidates(_n_clicks, _n_submit, query):
    """1단계 — 이름/사번으로 대상자를 검색해 후보 목록을 보여준다(아직
    선택 목록에 추가되지는 않음, "추가" 버튼을 눌러야 확정)."""
    query = (query or '').strip()
    if not query:
        return dbc.Alert('검색어를 입력해주세요.', color='warning', className='py-1 px-2 mb-0 small'), []
    candidates = jm.search_researchers(query)
    if not candidates:
        return html.Div(f'"{query}"에 해당하는 연구원을 찾지 못했습니다.', className='text-muted small'), []
    return html.Div([_candidate_row(c) for c in candidates]), candidates


@callback(
    Output('jm-individual-selected-store', 'data'),
    Input({'type': 'jm-add-candidate', 'rid': dash.ALL}, 'n_clicks'),
    Input({'type': 'jm-remove-selected', 'rid': dash.ALL}, 'n_clicks'),
    State({'type': 'jm-add-candidate', 'rid': dash.ALL}, 'id'),
    State({'type': 'jm-remove-selected', 'rid': dash.ALL}, 'id'),
    State('jm-individual-candidates-store', 'data'),
    State('jm-individual-selected-store', 'data'),
    prevent_initial_call=True,
)
def _update_selected(add_clicks, remove_clicks, add_ids, remove_ids, candidates, selected):
    """1단계에서 "추가"를 누르면 그 사람을 선택 목록에 더하고(중복은 무시),
    선택 목록의 "×"를 누르면 뺀다 — 여러 번 검색해 여러 명을 하나씩
    누적할 수 있다."""
    triggered_id = dash.ctx.triggered_id
    if not triggered_id:
        return dash.no_update
    selected = list(selected or [])

    if triggered_id.get('type') == 'jm-add-candidate':
        idx = next((i for i, d in enumerate(add_ids) if d == triggered_id), None)
        if idx is None or not add_clicks[idx]:
            return dash.no_update
        rid = triggered_id['rid']
        cand = next((c for c in (candidates or []) if c['researcher_id'] == rid), None)
        if cand and not any(s['researcher_id'] == rid for s in selected):
            selected.append(cand)
        return selected

    if triggered_id.get('type') == 'jm-remove-selected':
        idx = next((i for i, d in enumerate(remove_ids) if d == triggered_id), None)
        if idx is None or not remove_clicks[idx]:
            return dash.no_update
        rid = triggered_id['rid']
        return [s for s in selected if s['researcher_id'] != rid]

    return dash.no_update


@callback(
    Output('jm-individual-selected-list', 'children'),
    Input('jm-individual-selected-store', 'data'),
)
def _render_selected(selected):
    selected = selected or []
    if not selected:
        return html.Div('선택된 대상자가 없습니다. 위에서 검색해 추가해주세요.', className='text-muted small')
    return html.Div([_selected_chip(c) for c in selected], className='d-flex flex-wrap')


@callback(
    Output('jm-result', 'children'),
    Output('jm-history-refresh', 'data'),
    Input('jm-run-btn', 'n_clicks'),
    State('jm-mode', 'value'),
    State('jm-project-select', 'value'),
    State('jm-individual-selected-store', 'data'),
    State('jm-exclude-dept', 'value'),
    State('jm-exclude-project', 'value'),
    State('jm-history-refresh', 'data'),
    prevent_initial_call=True,
)
def _run(n_clicks, mode, project_names, selected_individuals, excluded_depts, excluded_projects, refresh_token):
    if not n_clicks:
        return dash.no_update, dash.no_update
    excluded_depts = excluded_depts or []
    excluded_projects = excluded_projects or []
    project_names = project_names or []
    selected_individuals = selected_individuals or []

    try:
        if mode == _MODE_INDIVIDUAL:
            if not selected_individuals:
                return dbc.Alert('대상자를 검색해서 추가해주세요.', color='warning'), dash.no_update
            researcher_ids = [c['researcher_id'] for c in selected_individuals]
            result = jm.run_individual_search(researcher_ids, excluded_depts, excluded_projects)
        else:
            if not project_names:
                return dbc.Alert('종료 예정 과제를 선택해주세요.', color='warning'), dash.no_update
            result = jm.run_project_search(project_names, excluded_depts, excluded_projects)
    except Exception as exc:  # noqa: BLE001 — 어떤 원인이든 화면에 아무 반응도
        # 없는 것보다는, 오류를 눈에 보이게 알려주는 게 낫다(외부 입력/실데이터
        # 경계). services/job_market.py 내부의 개별 안전망(run_concurrent 등)이
        # 못 잡는 예외(예: 명단 구성, 후보 조회 단계)까지 여기서 최종적으로 잡는다.
        return dbc.Alert(f'검색 중 오류가 발생했습니다: {exc}', color='danger'), dash.no_update

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
