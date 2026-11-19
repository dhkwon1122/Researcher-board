"""
업무 시나리오 > 인사발령(2026-11-19) — 인사발령 작성 양식(첨부파일)을 부서별 담당자에게 메일로 보낸다.
흐름·저장·권한은 services/hr_order_mail.py 참고.
"""
import base64
import io
from datetime import date

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from services import hr_order_mail as hom

dash.register_page(__name__, path='/hr-order', name='인사발령', title='인사발령')

_CONTACT_COLUMNS = [
    {'field': 'dept', 'headerName': '부서', 'editable': True, 'checkboxSelection': True, 'headerCheckboxSelection': True,
     'flex': 1},
    {'field': 'name', 'headerName': '담당자', 'editable': True, 'flex': 1},
    {'field': 'email', 'headerName': '이메일', 'editable': True, 'flex': 2},
]


def _contact_option(c: dict) -> dict:
    who = f" · {c['name']}" if c.get('name') else ''
    return {'label': f"{c['dept']}{who} <{c['email']}>", 'value': c['email']}


def _fmt_size(n: int) -> str:
    return f'{n / 1048576:.1f}MB' if n >= 1048576 else f'{max(1, n // 1024)}KB'


def _compose_card():
    order_date = hom.next_order_date()
    contacts = hom.load_contacts()
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-envelope-paper me-1'), '양식 메일 보내기'], className='fw-semibold')),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([dbc.Label('발신 계정', className='small mb-1'),
                         dcc.Dropdown(id='hro-sender', options=hom.sender_options(), clearable=False)], md=7),
                dbc.Col([dbc.Label('발령일', className='small mb-1 d-block'),
                         dcc.DatePickerSingle(id='hro-order-date', date=order_date.isoformat(), display_format='YYYY-MM-DD')],
                        md=3),
            ], className='g-2 mb-3'),
            dbc.Label('받을 부서 담당자', className='small mb-1'),
            html.Div([
                dbc.Button('전체 선택', id='hro-all', color='link', size='sm', className='p-0 me-3'),
                dbc.Button('선택 해제', id='hro-none', color='link', size='sm', className='p-0'),
            ], className='mb-1'),
            dbc.Checklist(id='hro-recipients', options=[_contact_option(c) for c in contacts], value=[],
                          className='small mb-1', style={'columns': '2'}),
            html.Div('아래 "부서별 담당자"에 먼저 등록하세요.' if not contacts else '', id='hro-recipients-hint',
                     className='small text-muted mb-3'),
            dbc.Label('제목', className='small mb-1'),
            dbc.Input(id='hro-subject', value=hom.default_subject(order_date), size='sm', className='mb-2'),
            dbc.Label('본문', className='small mb-1'),
            dbc.Textarea(id='hro-body', value=hom.default_body(order_date), rows=8, className='mb-2 small'),
            dbc.Label('첨부파일', className='small mb-1'),
            dcc.Upload(id='hro-upload', multiple=True, children=html.Div(
                [html.I(className='bi bi-paperclip me-1'), '클릭 또는 끌어다 놓아 첨부(여러 개 가능, 합계 20MB까지)']),
                className='border border-2 rounded text-center text-muted small py-3 mb-2',
                style={'borderStyle': 'dashed', 'cursor': 'pointer'}),
            html.Div(id='hro-files', className='small mb-3'),
            dbc.Button([html.I(className='bi bi-send me-1'), '메일 보내기'], id='hro-send', color='primary'),
            html.Div(id='hro-result', className='mt-3'),
            dcc.Store(id='hro-files-store', data=[]),
            dbc.Modal([
                dbc.ModalHeader(dbc.ModalTitle('메일을 보낼까요?')),
                dbc.ModalBody(id='hro-confirm-body'),
                dbc.ModalFooter([dbc.Button('취소', id='hro-confirm-cancel', color='secondary', size='sm'),
                                 dbc.Button('보내기', id='hro-confirm-ok', color='primary', size='sm')]),
            ], id='hro-confirm', is_open=False),
        ]),
    ], className='shadow-sm mb-4')


def _contacts_card():
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-people me-1'), '부서별 담당자'], className='fw-semibold')),
        dbc.CardBody([
            html.Div([
                dbc.Button([html.I(className='bi bi-plus me-1'), '행 추가'], id='hro-row-add', color='secondary',
                           outline=True, size='sm', className='me-1'),
                dbc.Button([html.I(className='bi bi-trash me-1'), '선택 삭제'], id='hro-row-del', color='danger',
                           outline=True, size='sm', className='me-1'),
                dbc.Button([html.I(className='bi bi-save me-1'), '저장'], id='hro-row-save', color='primary', size='sm',
                           className='me-2'),
                dcc.Upload(id='hro-contacts-upload', children=dbc.Button(
                    [html.I(className='bi bi-file-earmark-excel me-1'), '엑셀로 불러오기'], color='success', outline=True,
                    size='sm'), accept='.xlsx,.xls,.csv'),
                html.Span('열: 부서 · 담당자 · 이메일 — 불러온 뒤 저장을 눌러야 반영', className='small text-muted ms-2'),
            ], className='d-flex align-items-center flex-wrap mb-2'),
            dag.AgGrid(id='hro-contacts', columnDefs=_CONTACT_COLUMNS, rowData=hom.load_contacts(),
                       dashGridOptions={'rowSelection': 'multiple', 'singleClickEdit': True, 'stopEditingWhenCellsLoseFocus': True},
                       style={'height': '320px'}, className='ag-theme-alpine'),
            html.Div(id='hro-contacts-msg', className='small mt-2'),
        ]),
    ], className='shadow-sm mb-4')


def _settings_card():
    from config.auth_config import ROLE_LABELS
    from services.auth import can
    if not can('manage_users'):
        return html.Div()
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-shield-lock me-1'), '사용 권한(관리자)'], className='fw-semibold')),
        dbc.CardBody([
            html.Div('관리자 계정은 항상 쓸 수 있고, 아래에서 고른 역할도 이 메뉴를 쓸 수 있습니다.',
                     className='small text-muted mb-2'),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id='hro-roles', multi=True, value=hom.allowed_roles(),
                                     options=[{'label': v, 'value': k} for k, v in ROLE_LABELS.items()],
                                     placeholder='허용할 역할 선택(비우면 관리자만)'), md=9),
                dbc.Col(dbc.Button('저장', id='hro-roles-save', color='primary', size='sm'), md=3),
            ], className='g-2 align-items-center'),
            html.Div(id='hro-roles-msg', className='small mt-2'),
        ]),
    ], className='shadow-sm mb-4')


def _log_card():
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-clock-history me-1'), '발송 이력(최근 50건)'],
                                 className='fw-semibold')),
        dbc.CardBody(html.Div(_log_table(), id='hro-log')),
    ], className='shadow-sm')


def _log_table():
    rows = hom.read_log()
    if not rows:
        return html.Div('아직 보낸 메일이 없습니다.', className='small text-muted')
    body = []
    for e in rows:
        ok = [r for r in e.get('results', []) if r.get('ok')]
        fail = [r for r in e.get('results', []) if not r.get('ok')]
        body.append(html.Tr([
            html.Td(e.get('at', '').replace('T', ' ')[:16], className='text-nowrap'),
            html.Td(f"{e.get('by_name') or e.get('by')}"),
            html.Td(e.get('sender', '')),
            html.Td(e.get('subject', '')),
            html.Td(', '.join(f['name'] for f in e.get('files', []))),
            html.Td([html.Span(f'성공 {len(ok)}', className='text-success me-2'),
                     html.Span(f'실패 {len(fail)}', className='text-danger') if fail else None],
                    title='\n'.join(f"{r['dept']} {r['email']}: {r['error']}" for r in fail) or None),
        ]))
    return dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('시각', '보낸 사람', '발신 계정', '제목', '첨부', '결과')])),
                      html.Tbody(body)], size='sm', bordered=True, className='small mb-0')


def layout():
    if not hom.can_use():
        return dbc.Alert('인사발령 메뉴를 쓸 권한이 없습니다. 관리자에게 요청하세요.', color='warning', className='mt-3')
    return dbc.Container([
        html.H4([html.I(className='bi bi-envelope-paper me-2 text-primary'), '인사발령'], className='fw-bold mt-2'),
        html.P('매월 1일·16일 발령분 취합 양식을 부서별 담당자에게 메일로 보냅니다. 선택한 담당자에게 같은 첨부로 한 명씩 '
               '따로 발송됩니다.', className='text-muted small'),
        _compose_card(),
        _contacts_card(),
        _settings_card(),
        _log_card(),
    ], fluid=True, className='py-3')


# ── 콜백 ───────────────────────────────────────────────────────────────────

@callback(Output('hro-sender', 'value'), Input('hro-sender', 'options'))
def _default_sender(options):
    return options[0]['value'] if options else None


@callback(Output('hro-subject', 'value'), Output('hro-body', 'value'), Input('hro-order-date', 'date'),
          prevent_initial_call=True)
def _date_changed(d):
    if not d:
        return no_update, no_update
    od = date.fromisoformat(d[:10])
    return hom.default_subject(od), hom.default_body(od)


@callback(Output('hro-recipients', 'value'), Input('hro-all', 'n_clicks'), Input('hro-none', 'n_clicks'),
          State('hro-recipients', 'options'), prevent_initial_call=True)
def _select_all(_a, _n, options):
    return [o['value'] for o in options or []] if ctx.triggered_id == 'hro-all' else []


@callback(Output('hro-files-store', 'data'), Output('hro-upload', 'contents'),
          Input('hro-upload', 'contents'), Input({'type': 'hro-file-del', 'i': dash.ALL}, 'n_clicks'),
          State('hro-upload', 'filename'), State('hro-files-store', 'data'), prevent_initial_call=True)
def _files(contents, _dels, filenames, files):
    files = list(files or [])
    trig = ctx.triggered_id
    if isinstance(trig, dict):                       # × 눌러 빼기
        if not any(_dels or []):
            return no_update, no_update
        files.pop(trig['i'])
        return files, no_update
    for content, name in zip(contents or [], filenames or []):
        b64 = content.split(',', 1)[1]
        files.append({'name': name, 'b64': b64, 'size': len(base64.b64decode(b64))})
    return files, None


@callback(Output('hro-files', 'children'), Input('hro-files-store', 'data'))
def _files_view(files):
    if not files:
        return html.Span('첨부한 파일이 없습니다.', className='text-muted')
    total = sum(f['size'] for f in files)
    return html.Div([html.Div([html.I(className='bi bi-file-earmark me-1'), f"{f['name']} ({_fmt_size(f['size'])})",
                               html.Span(' ×', id={'type': 'hro-file-del', 'i': i}, n_clicks=0, className='text-danger ms-1',
                                         style={'cursor': 'pointer'}, title='빼기')])
                     for i, f in enumerate(files)]
                    + [html.Div(f'합계 {_fmt_size(total)}', className='text-muted')])


@callback(Output('hro-confirm', 'is_open'), Output('hro-confirm-body', 'children'), Output('hro-result', 'children'),
          Input('hro-send', 'n_clicks'), Input('hro-confirm-cancel', 'n_clicks'),
          State('hro-recipients', 'value'), State('hro-recipients', 'options'), State('hro-subject', 'value'),
          State('hro-files-store', 'data'), State('hro-sender', 'value'), State('hro-sender', 'options'),
          prevent_initial_call=True)
def _confirm(_send, _cancel, emails, options, subject, files, sender, sender_opts):
    if ctx.triggered_id == 'hro-confirm-cancel':
        return False, no_update, no_update
    problems = [m for ok, m in ((emails, '받을 담당자를 고르세요.'), ((subject or '').strip(), '제목을 입력하세요.'),
                                (files, '첨부파일을 올리세요.'), (sender, '발신 계정을 고르세요.')) if not ok]
    if problems:
        return False, no_update, dbc.Alert(' '.join(problems), color='warning', className='small py-2')
    label = {o['value']: o['label'] for o in options or []}
    sender_label = next((o['label'] for o in sender_opts or [] if o['value'] == sender), sender)
    return True, html.Div([
        html.Div([html.B('발신: '), sender_label], className='small mb-1'),
        html.Div([html.B('제목: '), subject], className='small mb-1'),
        html.Div([html.B('첨부: '), ', '.join(f['name'] for f in files)], className='small mb-2'),
        html.Div(html.B(f'받는 사람 {len(emails)}명(한 명씩 따로 발송)'), className='small'),
        html.Ul([html.Li(label.get(e, e)) for e in emails], className='small mb-0'),
    ]), no_update


@callback(Output('hro-result', 'children', allow_duplicate=True), Output('hro-confirm', 'is_open', allow_duplicate=True),
          Output('hro-log', 'children'),
          Input('hro-confirm-ok', 'n_clicks'),
          State('hro-recipients', 'value'), State('hro-subject', 'value'), State('hro-body', 'value'),
          State('hro-files-store', 'data'), State('hro-sender', 'value'), prevent_initial_call=True)
def _send(n, emails, subject, body, files, sender):
    if not n:
        return no_update, no_update, no_update
    by_email = {c['email']: c for c in hom.load_contacts()}
    contacts = [by_email[e] for e in emails or [] if e in by_email]
    attachments = [(f['name'], base64.b64decode(f['b64'])) for f in files or []]
    try:
        results = hom.send(contacts, subject, body, attachments, sender)
    except (PermissionError, ValueError) as exc:
        return dbc.Alert(str(exc), color='danger', className='small py-2'), False, no_update
    ok = [r for r in results if r['ok']]
    fail = [r for r in results if not r['ok']]
    items = [html.Div([html.I(className='bi bi-check-circle text-success me-1'), f'{len(ok)}명에게 보냈습니다.'])] if ok else []
    items += [html.Div([html.I(className='bi bi-x-circle text-danger me-1'), f"{r['dept']} {r['email']}: {r['error']}"])
              for r in fail]
    return (dbc.Alert(items, color='success' if not fail else 'warning', className='small py-2'), False, _log_table())


@callback(Output('hro-contacts', 'rowData'), Output('hro-contacts-msg', 'children'),
          Input('hro-row-add', 'n_clicks'), Input('hro-row-del', 'n_clicks'), Input('hro-contacts-upload', 'contents'),
          State('hro-contacts-upload', 'filename'), State('hro-contacts', 'rowData'), State('hro-contacts', 'selectedRows'),
          prevent_initial_call=True)
def _edit_contacts(_add, _del, content, filename, rows, selected):
    rows = list(rows or [])
    if ctx.triggered_id == 'hro-row-add':
        return rows + [{'dept': '', 'name': '', 'email': ''}], ''
    if ctx.triggered_id == 'hro-row-del':
        if not selected:
            return no_update, html.Span('삭제할 행을 체크하세요.', className='text-warning')
        drop = [r for r in selected]
        return [r for r in rows if r not in drop], html.Span('삭제했습니다 — 저장을 눌러야 반영됩니다.', className='text-muted')
    if content:
        try:
            raw = base64.b64decode(content.split(',', 1)[1])
            df = pd.read_csv(io.BytesIO(raw)) if (filename or '').lower().endswith('.csv') else pd.read_excel(io.BytesIO(raw))
            new = hom.contacts_from_table(df)
        except Exception as exc:  # noqa: BLE001
            return no_update, html.Span(f'불러오지 못했습니다: {exc}', className='text-danger')
        return new, html.Span(f'{len(new)}행을 불러왔습니다 — 확인 후 저장을 누르세요.', className='text-muted')
    return no_update, no_update


@callback(Output('hro-contacts-msg', 'children', allow_duplicate=True), Output('hro-recipients', 'options'),
          Output('hro-recipients-hint', 'children'),
          Input('hro-row-save', 'n_clicks'), State('hro-contacts', 'rowData'), prevent_initial_call=True)
def _save_contacts(n, rows):
    if not n:
        return no_update, no_update, no_update
    try:
        saved, errors = hom.save_contacts(rows)
    except PermissionError as exc:
        return html.Span(str(exc), className='text-danger'), no_update, no_update
    if errors:
        return html.Div([html.Div(e, className='text-danger') for e in errors]), no_update, no_update
    return (html.Span(f'{len(saved)}명 저장했습니다.', className='text-success'),
            [_contact_option(c) for c in saved], '' if saved else '아래 "부서별 담당자"에 먼저 등록하세요.')


@callback(Output('hro-roles-msg', 'children'), Input('hro-roles-save', 'n_clicks'), State('hro-roles', 'value'),
          prevent_initial_call=True)
def _save_roles(n, roles):
    if not n:
        return no_update
    try:
        saved = hom.set_allowed_roles(roles or [])
    except PermissionError as exc:
        return html.Span(str(exc), className='text-danger')
    return html.Span(f'저장했습니다({len(saved)}개 역할 허용).', className='text-success')
