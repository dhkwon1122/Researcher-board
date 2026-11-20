"""
업무 시나리오 > 업무분장(2026-11-20) — 매월 업무분장표 작성 양식을 부서별 담당자에게 메일로 보내고(수동·자동),
회신받은 업무분장표를 올려 부서별 제출 현황과 통합표로 관리한다. 받는 사람·참조인·발송 방식은 인사발령과 공유.
흐름·저장·일정 계산은 services/work_assign.py 참고.
"""
import base64
from datetime import date, datetime

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from components.rich_editor import register_rich_editor, rich_editor
from pages.hr_order import _contact_option, _file_list, _md, _rcp_summary, _upload_box
from services import hr_order_mail as hom
from services import work_assign as wa

dash.register_page(__name__, path='/work-assign', name='업무분장', title='업무분장')


def _target_options() -> list:
    out = []
    for t in wa.target_options():
        out.append({'label': f"{wa.target_label(t)}분 (자동 발송 예정 {_md(wa.send_date(t))})", 'value': t})
    return out


def _sub_target_options() -> list:
    today = date.today()
    return [{'label': f'{wa.target_label(t)}분', 'value': t} for t in (wa.target_of(today, k) for k in range(2, -7, -1))]


def _rcp_text():
    rcp = hom.recipient_settings()
    cc = ', '.join(p['name'] for p in rcp['cc']) or '없음'
    bcc = ', '.join(p['name'] for p in rcp['bcc'])
    mode = '한 통으로' if rcp['mode'] == 'single' else '담당자별 따로'
    return html.Div([html.B('참조(CC): '), cc, (html.Span([' · ', html.B('비밀참조: '), bcc]) if bcc else ''),
                     ' · ', html.B('발송 방식: '), mode, ' — ',
                     dcc.Link('인사발령 화면에서 변경', href='/hr-order')], className='small border rounded p-2 mb-3 bg-light')


def _body_frame(body: str, target: str, reply: date, height: str = '300px'):
    doc = ('<html><head><meta charset="utf-8"></head><body style="margin:8px">'
           + hom.body_html(wa.render(body or '', target, reply)) + '</body></html>')
    return html.Iframe(srcDoc=doc, sandbox='', style={'width': '100%', 'height': height, 'border': '0', 'background': '#fff'})


def _manual_reply() -> date:
    """수동 발송의 회신 기한 = 오늘(보내는 날)로부터 워킹데이 K일 후."""
    return wa.workdays_after(date.today(), wa.reply_workdays())


# ── 카드: 양식 메일 ─────────────────────────────────────────────────────────

def _compose_card():
    contacts = hom.load_contacts()
    subject_t, body_t = wa.template()
    opts = _target_options()
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-envelope-paper me-1'), '업무분장 작성 요청 메일'],
                                 className='fw-semibold')),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([dbc.Label('발신 계정', className='small mb-1'),
                         dcc.Dropdown(id='wa-sender', options=hom.sender_options(), clearable=False)], md=6),
                dbc.Col([dbc.Label('대상월', className='small mb-1'),
                         dcc.Dropdown(id='wa-target', options=opts, value=opts[1]['value'], clearable=False)], md=6),
            ], className='g-2 mb-3'),
            dbc.Label('받을 부서 담당자(수신 TO) — 인사발령과 같은 명단', className='small mb-1'),
            html.Div([
                dbc.Button('전체 선택', id='wa-all', color='link', size='sm', className='p-0 me-3'),
                dbc.Button('선택 해제', id='wa-none', color='link', size='sm', className='p-0 me-3'),
                dbc.Button('미제출 부서만', id='wa-unsub', color='link', size='sm', className='p-0'),
            ], className='mb-1'),
            dbc.Checklist(id='wa-recipients', options=[_contact_option(c) for c in contacts], value=[],
                          className='small mb-1', style={'columns': '2'}),
            html.Div(['부서별 담당자가 없습니다 — ', dcc.Link('인사발령 화면', href='/hr-order'), '에서 먼저 등록하세요.']
                     if not contacts else '', className='small text-muted mb-2'),
            _rcp_text(),
            dbc.Row([
                dbc.Col([
                    html.Div([dbc.Label('제목·본문 템플릿', className='small mb-0 me-2'),
                              dbc.Button([html.I(className='bi bi-save me-1'), '템플릿 저장'], id='wa-tpl-save',
                                         color='secondary', outline=True, size='sm', className='py-0'),
                              html.Span(id='wa-tpl-msg', className='small ms-2')],
                             className='d-flex align-items-center mb-1'),
                    html.Div(['평소 쓰시는 문구를 붙여 넣고(서식 유지), ', html.Code('{대상월}'), ' ', html.Code('{대상월_숫자}'),
                              ' ', html.Code('{회신일}'), ' ', html.Code('{회신일_월일}'),
                              '을 넣으면 대상월·회신 기한에 맞춰 바뀝니다(예: 2026년 12월 / 2026.12 / 11월 30일(월)). '
                              '회신 기한은 보내는 날로부터 워킹데이 아래 "자동 발송"에서 정한 일수 후입니다.'],
                             className='small text-muted mb-2'),
                    dbc.Input(id='wa-subject', value=subject_t, size='sm', className='mb-2'),
                    rich_editor('wa', body_t),
                ], md=6),
                dbc.Col([
                    dbc.Label('미리보기(지금 보낼 때)', className='small mb-1'),
                    html.Div(id='wa-preview', className='border rounded p-2 small bg-light', style={'minHeight': '260px'}),
                ], md=6),
            ], className='g-3 mb-3'),
            dbc.Label('첨부파일(업무분장 양식)', className='small mb-1'),
            _upload_box('wa-upload', '클릭 또는 끌어다 놓아 첨부(여러 개 가능, 합계 20MB까지)'),
            html.Div(id='wa-files', className='small mb-3'),
            dbc.Button([html.I(className='bi bi-send me-1'), '메일 보내기'], id='wa-send', color='primary'),
            html.Div(id='wa-result', className='mt-3'),
            dcc.Store(id='wa-files-store', data=[]),
            dbc.Modal([
                dbc.ModalHeader(dbc.ModalTitle('메일을 보낼까요?')),
                dbc.ModalBody(id='wa-confirm-body'),
                dbc.ModalFooter([dbc.Button('취소', id='wa-confirm-cancel', color='secondary', size='sm'),
                                 dbc.Button('보내기', id='wa-confirm-ok', color='primary', size='sm')]),
            ], id='wa-confirm', is_open=False, size='lg'),
        ]),
    ], className='shadow-sm mb-4')


# ── 카드: 회신 관리 ─────────────────────────────────────────────────────────

def _submit_card():
    opts = _sub_target_options()
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-inboxes me-1'), '회신 업무분장표 — 부서별 제출 현황·통합표'],
                                 className='fw-semibold')),
        dbc.CardBody([
            html.Div('메일로 회신받은 업무분장표(엑셀·CSV)를 올리면 부서별 제출 현황에 표시되고, 아래 통합표에 양식의 열 그대로 '
                     '"부서" 열을 붙여 합쳐집니다. 파일 이름에 부서명이 들어 있으면 여러 개를 한 번에 올려도 부서가 자동으로 '
                     '연결되고, 아니면 부서를 고른 뒤 한 개씩 올리세요. 같은 부서에 다시 올리면 새 파일로 바뀝니다.',
                     className='small text-muted mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('대상월', className='small mb-1'),
                         dcc.Dropdown(id='wa-sub-target', options=opts, value=opts[1]['value'], clearable=False)], md=3),
                dbc.Col([dbc.Label('부서(파일 1개 올릴 때 선택)', className='small mb-1'),
                         dcc.Dropdown(id='wa-sub-dept', options=wa.departments(), placeholder='파일 이름으로 자동 연결')],
                        md=3),
                dbc.Col(dcc.Upload(id='wa-sub-upload', multiple=True,
                                   children=html.Div([html.I(className='bi bi-upload me-1'), '회신 파일 올리기(여러 개 가능)']),
                                   className='border border-2 rounded text-center text-muted small py-2',
                                   style={'borderStyle': 'dashed', 'cursor': 'pointer'}), md=6),
            ], className='g-2 align-items-end mb-2'),
            html.Div(id='wa-sub-msg', className='small mb-2'),
            html.Div(id='wa-sub-status', className='mb-3'),
            html.Div([html.Span('통합표', className='fw-semibold small me-2'),
                      dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '다운로드 (엑셀)'], id='wa-merged-dl',
                                 color='success', outline=True, size='sm', className='py-0')],
                     className='d-flex align-items-center mb-1'),
            dag.AgGrid(id='wa-merged', rowData=[], columnDefs=[], className='ag-theme-alpine',
                       defaultColDef={'resizable': True, 'sortable': True, 'filter': True, 'minWidth': 90},
                       dashGridOptions={'enableCellTextSelection': True}, style={'height': '420px'}),
            dcc.Store(id='wa-sub-ver', data=0),
            dcc.Download(id='wa-download'),
        ]),
    ], className='shadow-sm mb-4')


def _status_table(target: str):
    rows = wa.status(target)
    if not rows:
        return html.Div(['부서별 담당자가 없습니다 — ', dcc.Link('인사발령 화면', href='/hr-order'), '에서 먼저 등록하세요.'],
                        className='small text-muted')
    done = sum(1 for r in rows if r['submitted'])
    body = []
    for r in rows:
        body.append(html.Tr([
            html.Td(r['dept']), html.Td(r['contact']),
            html.Td(dbc.Badge('제출', color='success') if r['submitted'] else dbc.Badge('미제출', color='secondary')),
            html.Td(r['name']), html.Td(r['rows']), html.Td(r['at'].replace('T', ' ')[:16]), html.Td(r['by_name']),
            html.Td([
                html.Span(html.I(className='bi bi-download'), id={'type': 'wa-sub-dl', 'dept': r['dept']}, n_clicks=0,
                          className='text-primary me-3', style={'cursor': 'pointer'}, title='원본 파일 받기'),
                html.Span(html.I(className='bi bi-trash'), id={'type': 'wa-sub-del', 'dept': r['dept']}, n_clicks=0,
                          className='text-danger', style={'cursor': 'pointer'}, title='제출 취소(파일 삭제)'),
            ] if r['submitted'] else ''),
        ]))
    return html.Div([
        html.Div(f'{wa.target_label(target)}분 제출 {done}/{len(rows)}개 부서', className='small fw-semibold mb-1'),
        dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('부서', '담당자', '상태', '파일', '행 수', '올린 시각', '올린 사람', '')])),
                   html.Tbody(body)], size='sm', bordered=True, hover=True, className='small mb-0'),
    ])


# ── 카드: 자동 발송 ─────────────────────────────────────────────────────────

def _auto_status():
    cfg = wa.auto_settings()
    if not cfg['enabled']:
        return html.Span('자동 발송이 꺼져 있습니다.', className='text-muted')
    nxt = wa.next_auto_send()
    who = (cfg['sender'] or {}).get('label', '')
    lines = [html.Div([html.I(className='bi bi-check-circle text-success me-1'),
                       f'켜짐 — 매월 마지막 워킹데이 {wa.send_workdays()}일 전 발송·회신 기한 발송 후 {wa.reply_workdays()}일, '
                       f'발신 {who}, 담당자 {len(hom.load_contacts())}명 전체, 첨부 {len(cfg["files"])}개'
                       + _rcp_summary(hom.recipient_settings())])]
    if nxt:
        t, when = nxt
        lines.append(html.Div(f'다음 발송: {_md(when.date())} {when:%H:%M} — {wa.target_label(t)}분'
                              f'(회신 {_md(wa.reply_due(t, when.date()))})', className='fw-semibold'))
    return html.Div(lines)


def _days_preview(send, reply):
    if send is None or not reply:
        return []
    t = wa.target_of(date.today(), 1)
    base = wa.base_date(t)
    sd = hom.workdays_before(base, int(send))
    rd = wa.workdays_after(sd, int(reply))
    return [html.Div(f'예) {wa.target_label(t)}분: 마지막 워킹데이 {_md(base)} → 발송 {_md(sd)}, 회신 기한 {_md(rd)}')]


def _auto_card():
    cfg = wa.auto_settings()
    files = [{'name': n, 'size': len(b)} for n, b in wa.auto_files()]
    sender_value = hom.SHARED_SENDER if cfg['sender'] and not cfg['sender'].get('user_id') else None
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-alarm me-1'), '자동 발송'], className='fw-semibold')),
        dbc.CardBody([
            html.Div('켜 두면 매월 마지막 워킹데이의 아래 일수 전, 지정한 시각에 부서별 담당자 전체에게 저장된 템플릿·참조인·'
                     '발송 방식과 아래 첨부로 다음 달 업무분장을 요청합니다(대상월당 한 번). 워킹데이는 토·일, 공휴일, 인사발령 '
                     '화면의 회사 휴무일을 뺀 날입니다.', className='small text-muted mb-2'),
            dbc.Row([
                dbc.Col(dbc.Switch(id='wa-auto-on', label='자동 발송 사용', value=cfg['enabled']), md=3),
                dbc.Col([dbc.Label('발송 시각', className='small mb-1'),
                         dcc.Dropdown(id='wa-auto-hour', options=[{'label': f'{h:02d}:00', 'value': h} for h in range(7, 20)],
                                      value=cfg['hour'], clearable=False)], md=3),
                dbc.Col([dbc.Label('발신 계정', className='small mb-1'),
                         dcc.Dropdown(id='wa-auto-sender', options=hom.sender_options(), value=sender_value,
                                      clearable=False)], md=6),
            ], className='g-2 align-items-end mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('발송일 — 매월 마지막 워킹데이 며칠 전', className='small mb-1'),
                         dcc.Dropdown(id='wa-send-days', value=wa.send_workdays(), clearable=False,
                                      options=[{'label': '당일(마지막 워킹데이)' if n == 0 else f'{n}일 전', 'value': n}
                                               for n in range(0, wa.MAX_DAYS + 1)])], md=3),
                dbc.Col([dbc.Label('회신 기한 — 발송일로부터 워킹데이', className='small mb-1'),
                         dcc.Dropdown(id='wa-reply-days', value=wa.reply_workdays(), clearable=False,
                                      options=[{'label': f'{n}일 후', 'value': n} for n in range(1, wa.MAX_DAYS + 1)])], md=3),
                dbc.Col(html.Div(id='wa-days-preview', className='small text-muted'), md=6),
            ], className='g-2 align-items-end mb-2'),
            dbc.Label('자동 발송용 첨부(서버에 보관)', className='small mb-1'),
            _upload_box('wa-auto-upload', '클릭 또는 끌어다 놓아 첨부(여러 개 가능, 계속 추가됨 — 같은 이름이면 새 파일로 바뀜)'),
            html.Div(_file_list(files, 'wa-auto-file-del'), id='wa-auto-files', className='small mb-2'),
            dbc.Button([html.I(className='bi bi-save me-1'), '자동 발송 설정 저장'], id='wa-auto-save', color='primary',
                       size='sm', className='mt-1'),
            html.Div(id='wa-auto-msg', className='small mt-2'),
            html.Div(_auto_status(), id='wa-auto-status', className='small mt-2'),
        ]),
    ], className='shadow-sm mb-4')


# ── 카드: 발송 이력 ─────────────────────────────────────────────────────────

def _log_table():
    from pages.hr_order import _log_cc
    rows = wa.read_log()
    if not rows:
        return html.Div('아직 보낸 메일이 없습니다.', className='small text-muted')
    body = []
    for e in rows:
        ok = [r for r in e.get('results', []) if r.get('ok')]
        fail = [r for r in e.get('results', []) if not r.get('ok')]
        target = e.get('target', '')
        body.append(html.Tr([
            html.Td(e.get('at', '').replace('T', ' ')[:16], className='text-nowrap'),
            html.Td('자동' if e.get('kind') == 'auto' else '수동'),
            html.Td(wa.target_label(target) if target else ''),
            html.Td(e.get('by_name') or e.get('by')), html.Td(e.get('sender', '')), html.Td(e.get('subject', '')),
            html.Td(_log_cc(e)), html.Td(', '.join(f['name'] for f in e.get('files', []))),
            html.Td([html.Span(f'성공 {len(ok)}', className='text-success me-2'),
                     html.Span(f'실패 {len(fail)}', className='text-danger') if fail else None],
                    title='\n'.join(f"{r['dept']} {r['email']}: {r['error']}" for r in fail) or None),
        ]))
    return dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('시각', '구분', '대상월', '보낸 사람', '발신 계정', '제목',
                                                               '참조', '첨부', '결과')])),
                      html.Tbody(body)], size='sm', bordered=True, className='small mb-0')


def layout():
    if not wa.can_use():
        return dbc.Alert('업무분장 메뉴를 쓸 권한이 없습니다. 관리자에게 요청하세요.', color='warning', className='mt-3')
    return dbc.Container([
        html.H4([html.I(className='bi bi-list-task me-2 text-primary'), '업무분장'], className='fw-bold mt-2'),
        html.P('매월 업무분장표 작성 양식을 부서별 담당자에게 메일로 보내고, 회신받은 업무분장표를 올려 제출 현황과 통합표로 '
               '관리합니다. 받는 사람·참조인·발송 방식과 사용 권한은 인사발령 화면 설정을 함께 씁니다.',
               className='text-muted small'),
        _compose_card(),
        _submit_card(),
        _auto_card(),
        dbc.Card([dbc.CardHeader(html.Span([html.I(className='bi bi-clock-history me-1'), '발송 이력(최근 50건)'],
                                           className='fw-semibold')),
                  dbc.CardBody(html.Div(_log_table(), id='wa-log'))], className='shadow-sm mb-4'),
    ], fluid=True, className='py-3')


# ── 콜백: 작성 요청 메일 ─────────────────────────────────────────────────────

register_rich_editor('wa')


@callback(Output('wa-sender', 'value'), Input('wa-sender', 'options'))
def _default_sender(options):
    return options[0]['value'] if options else None


@callback(Output('wa-preview', 'children'), Input('wa-target', 'value'), Input('wa-subject', 'value'),
          Input('wa-body', 'data'))
def _preview(target, subject, body):
    if not target:
        return ''
    reply = _manual_reply()
    return html.Div([html.Div([html.B('제목: '), wa.render(subject, target, reply)], className='mb-2'),
                     _body_frame(body, target, reply)])


@callback(Output('wa-tpl-msg', 'children'), Input('wa-tpl-save', 'n_clicks'), State('wa-subject', 'value'),
          State('wa-body', 'data'), prevent_initial_call=True)
def _save_template(n, subject, body):
    if not n:
        return no_update
    try:
        wa.save_template(subject, body)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger')
    return html.Span('저장했습니다.', className='text-success')


@callback(Output('wa-recipients', 'value'), Input('wa-all', 'n_clicks'), Input('wa-none', 'n_clicks'),
          Input('wa-unsub', 'n_clicks'), State('wa-recipients', 'options'), State('wa-target', 'value'),
          prevent_initial_call=True)
def _select(_a, _n, _u, options, target):
    if ctx.triggered_id == 'wa-none':
        return []
    if ctx.triggered_id == 'wa-unsub':
        submitted = set(wa.submissions(target or ''))
        return [c['email'] for c in hom.load_contacts() if c['dept'] not in submitted]
    return [o['value'] for o in options or []]


@callback(Output('wa-files-store', 'data'), Output('wa-upload', 'contents'),
          Input('wa-upload', 'contents'), Input({'type': 'wa-file-del', 'i': ALL}, 'n_clicks'),
          State('wa-upload', 'filename'), State('wa-files-store', 'data'), prevent_initial_call=True)
def _files(contents, dels, filenames, files):
    files = list(files or [])
    if isinstance(ctx.triggered_id, dict):
        if not any(dels or []):
            return no_update, no_update
        files.pop(ctx.triggered_id['i'])
        return files, no_update
    for content, name in zip(contents or [], filenames or []):
        b64 = content.split(',', 1)[1]
        files.append({'name': name, 'b64': b64, 'size': len(base64.b64decode(b64))})
    return files, None


@callback(Output('wa-files', 'children'), Input('wa-files-store', 'data'))
def _files_view(files):
    return _file_list(files, 'wa-file-del')


@callback(Output('wa-confirm', 'is_open'), Output('wa-confirm-body', 'children'), Output('wa-result', 'children'),
          Input('wa-send', 'n_clicks'), Input('wa-confirm-cancel', 'n_clicks'),
          State('wa-recipients', 'value'), State('wa-recipients', 'options'), State('wa-subject', 'value'),
          State('wa-body', 'data'), State('wa-target', 'value'), State('wa-files-store', 'data'),
          State('wa-sender', 'value'), State('wa-sender', 'options'), prevent_initial_call=True)
def _confirm(_send, _cancel, emails, options, subject, body, target, files, sender, sender_opts):
    if ctx.triggered_id == 'wa-confirm-cancel':
        return False, no_update, no_update
    problems = [m for ok, m in ((emails, '받을 담당자를 고르세요.'), ((subject or '').strip(), '제목을 입력하세요.'),
                                (files, '첨부파일을 올리세요.'), (sender, '발신 계정을 고르세요.'), (target, '대상월을 고르세요.'))
                if not ok]
    if problems:
        return False, no_update, dbc.Alert(' '.join(problems), color='warning', className='small py-2')
    rcp = hom.recipient_settings()
    reply = _manual_reply()
    label = {o['value']: o['label'] for o in options or []}
    sender_label = next((o['label'] for o in sender_opts or [] if o['value'] == sender), sender)
    single = rcp['mode'] == 'single'
    people = lambda ps: html.Ul([html.Li(f"{p['name']} [{p['dept']}] · {p['email']}") for p in ps], className='small mb-2')  # noqa: E731
    return True, html.Div([
        html.Div([html.B('발신: '), sender_label], className='small mb-1'),
        html.Div([html.B('제목: '), wa.render(subject, target, reply)], className='small mb-1'),
        html.Div([html.B('첨부: '), ', '.join(f['name'] for f in files)], className='small mb-2'),
        html.Div(_body_frame(body, target, reply, '240px'), className='border rounded mb-2'),
        html.Div(html.B(f"수신(TO) {len(emails)}명 — " + ('한 통으로 발송' if single else '한 명씩 따로 발송')),
                 className='small'),
        html.Ul([html.Li(label.get(e, e)) for e in emails], className='small mb-2'),
        html.Div(html.B(f"참조(CC) {len(rcp['cc'])}명"), className='small') if rcp['cc'] else None,
        people(rcp['cc']) if rcp['cc'] else None,
        html.Div(html.B(f"비밀참조(BCC) {len(rcp['bcc'])}명"), className='small') if rcp['bcc'] else None,
        people(rcp['bcc']) if rcp['bcc'] else None,
    ]), no_update


@callback(Output('wa-result', 'children', allow_duplicate=True), Output('wa-confirm', 'is_open', allow_duplicate=True),
          Output('wa-log', 'children'),
          Input('wa-confirm-ok', 'n_clicks'),
          State('wa-recipients', 'value'), State('wa-subject', 'value'), State('wa-body', 'data'),
          State('wa-target', 'value'), State('wa-files-store', 'data'), State('wa-sender', 'value'),
          prevent_initial_call=True)
def _send(n, emails, subject, body, target, files, sender):
    if not n:
        return no_update, no_update, no_update
    reply = _manual_reply()
    by_email = {c['email']: c for c in hom.load_contacts()}
    contacts = [by_email[e] for e in emails or [] if e in by_email]
    attachments = [(f['name'], base64.b64decode(f['b64'])) for f in files or []]
    rcp = hom.recipient_settings()
    try:
        results = wa.send(contacts, wa.render(subject, target, reply), wa.render(body, target, reply), attachments, sender,
                          target, cc=rcp['cc'], bcc=rcp['bcc'], mode=rcp['mode'])
    except (PermissionError, ValueError) as exc:
        return dbc.Alert(str(exc), color='danger', className='small py-2'), False, no_update
    ok = [r for r in results if r['ok']]
    fail = [r for r in results if not r['ok']]
    items = [html.Div([html.I(className='bi bi-check-circle text-success me-1'), f'{len(ok)}명에게 보냈습니다.'])] if ok else []
    items += [html.Div([html.I(className='bi bi-x-circle text-danger me-1'), f"{r['dept']} {r['email']}: {r['error']}"])
              for r in fail]
    return dbc.Alert(items, color='success' if not fail else 'warning', className='small py-2'), False, _log_table()


# ── 콜백: 회신 관리 ─────────────────────────────────────────────────────────

@callback(Output('wa-sub-msg', 'children'), Output('wa-sub-ver', 'data'), Output('wa-sub-upload', 'contents'),
          Input('wa-sub-upload', 'contents'), Input({'type': 'wa-sub-del', 'dept': ALL}, 'n_clicks'),
          State('wa-sub-upload', 'filename'), State('wa-sub-target', 'value'), State('wa-sub-dept', 'value'),
          State('wa-sub-ver', 'data'), prevent_initial_call=True)
def _submit(contents, dels, filenames, target, dept, ver):
    try:
        if isinstance(ctx.triggered_id, dict):
            if not any(dels or []):
                return no_update, no_update, no_update
            d = ctx.triggered_id['dept']
            wa.delete_submission(target, d)
            return html.Span(f'{d} 제출을 취소했습니다.', className='text-muted'), (ver or 0) + 1, no_update
        files = [(n, base64.b64decode(c.split(',', 1)[1])) for c, n in zip(contents or [], filenames or [])]
        if not files:
            return no_update, no_update, None
        done, errors = wa.save_uploads(target, files, dept)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), no_update, None
    items = [html.Div([html.I(className='bi bi-check-circle text-success me-1'),
                       f'{len(done)}개 저장: ' + ', '.join(f'{d}({n})' for d, n in done)])] if done else []
    items += [html.Div([html.I(className='bi bi-exclamation-triangle text-warning me-1'), e]) for e in errors]
    return html.Div(items), (ver or 0) + 1, None


@callback(Output('wa-sub-status', 'children'), Output('wa-merged', 'rowData'), Output('wa-merged', 'columnDefs'),
          Input('wa-sub-target', 'value'), Input('wa-sub-ver', 'data'))
def _status(target, _ver):
    if not target:
        return '', [], []
    df = wa.merged(target)
    cols = [{'field': c, 'headerName': c, 'pinned': 'left' if i == 0 else None} for i, c in enumerate(df.columns)]
    return _status_table(target), df.to_dict('records'), cols


@callback(Output('wa-download', 'data'), Input('wa-merged-dl', 'n_clicks'),
          Input({'type': 'wa-sub-dl', 'dept': ALL}, 'n_clicks'), State('wa-sub-target', 'value'),
          prevent_initial_call=True)
def _download(_m, dls, target):
    if not wa.can_use() or not target:
        return no_update
    if isinstance(ctx.triggered_id, dict):
        if not any(dls or []):
            return no_update
        f = wa.submission_file(target, ctx.triggered_id['dept'])
        return dcc.send_bytes(f[1], f[0]) if f else no_update
    if wa.merged(target).empty:
        return no_update
    return dcc.send_bytes(wa.merged_excel(target), f'업무분장_통합_{target}.xlsx')


# ── 콜백: 자동 발송 ─────────────────────────────────────────────────────────

@callback(Output('wa-days-preview', 'children'), Input('wa-send-days', 'value'), Input('wa-reply-days', 'value'))
def _days(send, reply):
    return _days_preview(send, reply)


@callback(Output('wa-auto-sender', 'value'), Input('wa-auto-sender', 'options'), State('wa-auto-sender', 'value'))
def _default_auto_sender(options, value):
    return value or (options[0]['value'] if options else None)


@callback(Output('wa-auto-files', 'children'), Output('wa-auto-upload', 'contents'), Output('wa-auto-msg', 'children'),
          Input('wa-auto-upload', 'contents'), Input({'type': 'wa-auto-file-del', 'i': ALL}, 'n_clicks'),
          State('wa-auto-upload', 'filename'), prevent_initial_call=True)
def _auto_files(contents, dels, filenames):
    current = wa.auto_files()
    try:
        if isinstance(ctx.triggered_id, dict):
            if not any(dels or []):
                return no_update, no_update, no_update
            i = ctx.triggered_id['i']
            if i < len(current):
                wa.remove_auto_file(current[i][0])
        else:
            new = [(n, base64.b64decode(c.split(',', 1)[1])) for c, n in zip(contents or [], filenames or [])]
            wa.add_auto_files(new)
    except (PermissionError, ValueError) as exc:
        return no_update, None, html.Span(str(exc), className='text-danger')
    files = [{'name': n, 'size': len(b)} for n, b in wa.auto_files()]
    return _file_list(files, 'wa-auto-file-del'), None, html.Span('자동 발송용 첨부를 저장했습니다.', className='text-success')


@callback(Output('wa-auto-msg', 'children', allow_duplicate=True), Output('wa-auto-status', 'children'),
          Output('wa-target', 'options'),
          Input('wa-auto-save', 'n_clicks'),
          State('wa-auto-on', 'value'), State('wa-auto-hour', 'value'), State('wa-auto-sender', 'value'),
          State('wa-send-days', 'value'), State('wa-reply-days', 'value'), prevent_initial_call=True)
def _save_auto(n, enabled, hour, sender, send_days, reply_days):
    if not n:
        return no_update, no_update, no_update
    try:
        wa.set_workdays(send_days, reply_days)
        wa.save_auto(bool(enabled), hour, sender)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), _auto_status(), no_update
    return (html.Span(f'저장했습니다({datetime.now():%H:%M}).', className='text-success'), _auto_status(),
            _target_options())
