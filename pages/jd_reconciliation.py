"""
화면: 과제 직무/대상자 검증 — 업로드한 직무기술서(.docx)와 실제 인사데이터를
대조한다. 상세 로직은 services/jd_reconciliation.py 참고.
"""

import base64
import binascii

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from services import jd_reconciliation as jd

dash.register_page(
    __name__,
    path='/jd-reconciliation',
    name='과제 직무/대상자 검증',
    title='과제 직무/대상자 검증',
)

# 관리자/유저 구분(로그인·권한 체계)이 아직 없어 임시로 전체 사용자에게
# 숨겨둔 상태 — 나중에 권한 체계가 생기면 이 플래그를 False로 바꾸고
# app.py의 '과제 직무/대상자 검증' NavLink를 되살리면 된다
# (data/processed/CLAUDE.md 참고).
_FEATURE_HIDDEN = True


def _confidence_badge(confidence: str):
    color = {'상': 'success', '중': 'warning', '하': 'secondary'}.get(confidence, 'light')
    return dbc.Badge(confidence or '-', color=color, className='me-2')


def _person_row(person: dict):
    return html.Div([
        html.Div([
            html.Span(f"{person.get('name', '')}({person.get('researcher_id', '')})", className='fw-semibold me-2'),
            html.Span(person.get('department', ''), className='text-muted small me-2'),
            _confidence_badge(person.get('confidence', '')),
        ]),
        html.Div(person.get('evidence', '') or '(근거 없음)', className='text-muted small mb-2'),
    ], className='mb-2 pb-2 border-bottom')


def _role_card(role: dict):
    diff = role.get('diff', 0)
    if diff == 0:
        border = 'border-success'
    elif diff < 0:
        border = 'border-danger'
    else:
        border = 'border-warning'
    description = role.get('description', '')
    raw_description = role.get('raw_description', '')
    hiring_target = role.get('hiring_target', '')
    return dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Span(role.get('role_name', ''), className='fw-bold fs-6 me-2'),
                html.Span(
                    f"문서 {role.get('document_count', 0)}명 / 실제 매칭 {role.get('matched_count', 0)}명"
                    + (f" ({'+' if diff > 0 else ''}{diff})" if diff else ''),
                    className='text-muted',
                ),
            ], className='mb-2'),
            (html.Div([
                html.I(className='bi bi-info-circle me-1'),
                f'채용 목표(참고용, 비교 대상 아님): {hiring_target}',
            ], className='text-muted small fst-italic mb-2') if hiring_target else None),
            (html.Div(description, className='small mb-1') if description else None),
            (html.Div(f'원문: {raw_description}', className='text-muted small fst-italic mb-2')
             if raw_description and raw_description != description else None),
            html.Div([_person_row(p) for p in role.get('matched', [])]) if role.get('matched')
            else html.Div('매칭된 인원이 없습니다.', className='text-muted small'),
        ]),
        className=f'mb-3 {border}',
    )


def _render_report(report: dict):
    consistency_notes = report.get('consistency_notes') or []
    unmatched = report.get('unmatched') or []
    project_overview = report.get('project_overview') or ''
    return html.Div([
        dbc.Alert([
            html.Div(report.get('summary_text', ''), className='fw-semibold mb-1'),
            html.Div(f"실행 시각: {report.get('run_at', '')} · 문서: {report.get('doc_filename', '')} · "
                     f"과제: {report.get('project_name', '')}", className='small text-muted'),
        ], color='info', className='mb-3'),
        (dbc.Card(
            dbc.CardBody([
                html.Div('과제 개요 (컨플루언스 분석 기반)', className='fw-bold mb-2'),
                html.Div([html.Div(line) for line in project_overview.split('\n')], className='small'),
            ]),
            className='mb-3 border-primary',
        ) if report.get('confluence_available') and project_overview else None),
        (dbc.Alert(
            [html.Div('문서 내부 표/본문 불일치', className='fw-semibold'),
             html.Ul([html.Li(n) for n in consistency_notes])],
            color='warning', className='mb-3',
        ) if consistency_notes else None),
        html.Div([_role_card(r) for r in report.get('roles') or []]),
        (dbc.Card(
            dbc.CardBody([
                html.Div('어떤 직무와도 뚜렷이 맞지 않는 인원', className='fw-bold mb-2'),
                html.Div([_person_row(p) for p in unmatched]),
            ]),
            className='mb-3 border-secondary',
        ) if unmatched else None),
    ])


def _history_table():
    rows = jd.list_history()
    if not rows:
        return html.Div('검증 이력이 없습니다.', className='text-muted small')
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('실행일시'), html.Th('과제'), html.Th('문서'),
            html.Th('문서 총원'), html.Th('실제 배정'), html.Th(''),
        ])),
        html.Tbody([
            html.Tr([
                html.Td(r['run_at']), html.Td(r['project_name']), html.Td(r['doc_filename']),
                html.Td(str(r['document_total'])), html.Td(str(r['actual_total'])),
                html.Td(dbc.Button('보기', id={'type': 'jd-history-view', 'file': r['file']},
                                    color='link', size='sm', n_clicks=0)),
            ]) for r in rows
        ]),
    ], bordered=False, hover=True, size='sm', className='mb-0')


def layout(**_kwargs):
    if _FEATURE_HIDDEN:
        return dbc.Alert('이 기능은 현재 준비 중입니다.', color='secondary', className='mt-3')
    project_options = [{'label': p, 'value': p} for p in jd.list_project_names()]
    return html.Div([
        html.H5(
            [html.I(className='bi bi-file-earmark-check me-2 text-primary'), '과제 직무/대상자 검증'],
            className='fw-bold mb-1 mt-1',
        ),
        html.Div(
            '업로드한 직무기술서(.docx 또는 .pdf)의 직무별 인원수·요구사항을 컨플루언스 과제 요약과 '
            '함께 쉬운 말로 풀어서 보여주고, 실제 그 과제에 배정된 인원의 보유 전문성과 대조합니다.',
            className='text-muted small mb-3',
        ),
        dbc.Row([
            dbc.Col(dcc.Dropdown(
                id='jd-project-select', options=project_options, placeholder='과제 선택',
                clearable=True,
            ), md=4),
            dbc.Col(dcc.Upload(
                id='jd-doc-upload',
                children=html.Div(id='jd-doc-upload-label', children=[
                    html.I(className='bi bi-cloud-arrow-up me-1'),
                    '여기로 파일을 끌어다 놓거나 클릭해서 업로드 (.docx, .pdf)',
                ]),
                accept='.docx,.pdf',
                className='text-center rounded p-2 jd-upload-dropzone',
                style={'cursor': 'pointer', 'border': '2px dashed #adb5bd'},
                style_active={'borderColor': '#0d6efd', 'backgroundColor': '#e7f1ff'},
                style_reject={'borderColor': '#dc3545', 'backgroundColor': '#f8d7da'},
            ), md=5),
            dbc.Col(dbc.Button([html.I(className='bi bi-search me-1'), '검증 시작'],
                                id='jd-run-btn', color='primary', n_clicks=0, className='w-100'), md=3),
        ], className='g-2 mb-3'),
        dcc.Loading(html.Div(id='jd-result')),
        dcc.Store(id='jd-history-refresh', data=0),
        html.Hr(),
        html.H6('검증 이력', className='fw-bold mb-2'),
        html.Div(id='jd-history-table', children=_history_table()),
    ], className='mb-3')


@callback(
    Output('jd-doc-upload-label', 'children'),
    Input('jd-doc-upload', 'filename'),
    prevent_initial_call=True,
)
def _show_upload_filename(filename):
    if not filename:
        return dash.no_update
    icon = 'bi-file-earmark-pdf' if filename.lower().endswith('.pdf') else 'bi-file-earmark-word'
    return [html.I(className=f'bi {icon} me-1'), filename]


@callback(
    Output('jd-result', 'children'),
    Output('jd-history-refresh', 'data'),
    Input('jd-run-btn', 'n_clicks'),
    State('jd-project-select', 'value'),
    State('jd-doc-upload', 'contents'),
    State('jd-doc-upload', 'filename'),
    State('jd-history-refresh', 'data'),
    prevent_initial_call=True,
)
def _run(n_clicks, project_name, contents, filename, refresh_token):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not project_name:
        return dbc.Alert('과제를 선택해주세요.', color='warning'), dash.no_update
    if not contents:
        return dbc.Alert('직무기술서(.docx 또는 .pdf) 파일을 업로드해주세요.', color='warning'), dash.no_update

    try:
        _header, b64data = contents.split(',', 1)
        file_bytes = base64.b64decode(b64data)
    except (ValueError, binascii.Error):
        return dbc.Alert('첨부파일을 읽지 못했습니다. 파일이 손상되지 않았는지 확인해주세요.', color='danger'), dash.no_update

    try:
        report = jd.run_reconciliation(project_name, filename or '업로드 파일', file_bytes)
    except jd.DocumentReadError as exc:
        return dbc.Alert(str(exc), color='warning'), dash.no_update
    except Exception as exc:  # noqa: BLE001 — 업로드 파일 파싱은 외부 입력 경계라 방어적으로 처리
        return dbc.Alert(f'검증 중 오류가 발생했습니다: {exc}', color='danger'), dash.no_update

    return _render_report(report), (refresh_token or 0) + 1


@callback(
    Output('jd-history-table', 'children'),
    Input('jd-history-refresh', 'data'),
)
def _refresh_history_table(_refresh_token):
    return _history_table()


@callback(
    Output('jd-result', 'children', allow_duplicate=True),
    Input({'type': 'jd-history-view', 'file': dash.ALL}, 'n_clicks'),
    State({'type': 'jd-history-view', 'file': dash.ALL}, 'id'),
    prevent_initial_call=True,
)
def _view_history(n_clicks_list, ids):
    triggered_id = dash.ctx.triggered_id
    if not triggered_id:
        return dash.no_update
    idx = next((i for i, d in enumerate(ids) if d == triggered_id), None)
    if idx is None or not n_clicks_list[idx]:
        return dash.no_update
    report = jd.load_history(triggered_id['file'])
    if not report:
        return dbc.Alert('이력을 불러오지 못했습니다.', color='danger')
    return _render_report(report)
