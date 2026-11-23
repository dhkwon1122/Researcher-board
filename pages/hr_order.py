"""
업무 시나리오 > 인사발령(2026-11-19) — 인사발령 작성 양식(첨부파일)을 부서별 담당자에게 메일로 보낸다.
흐름·저장·권한·자동 발송은 services/hr_order_mail.py 참고.
"""
import base64
from datetime import date, datetime

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from components import mail_recipients as mr
from components import reply_inbox_ui as ri_ui
from components.rich_editor import register_rich_editor, rich_editor
from services import hr_order_mail as hom

dash.register_page(__name__, path='/hr-order', name='인사발령', title='인사발령')

# 받는 사람·참조 UI는 components/mail_recipients(업무분장과 공용, 명단은 각자 — 2026-11-20 분리)
HR_STORE = mr.RecipientStore(hom.load_contacts, hom.save_contacts, hom.recipient_settings, hom.save_recipient_settings)

_WD = '월화수목금토일'


def _md(d: date) -> str:
    return f'{d.month}월 {d.day}일({_WD[d.weekday()]})'


def _fmt_size(n: int) -> str:
    return f'{n / 1048576:.1f}MB' if n >= 1048576 else f'{max(1, n // 1024)}KB'


def _order_date_options() -> list:
    d, out = hom.next_order_date(), []
    for _ in range(6):
        out.append({'label': f'{d:%Y.%m.%d}자 (회신 {_md(hom.reply_due(d))})', 'value': d.isoformat()})
        d = hom.next_order_date(d)
    return out


def _file_list(files: list, del_type: str):
    if not files:
        return html.Span('첨부한 파일이 없습니다.', className='text-muted')
    total = sum(f['size'] for f in files)
    return html.Div([html.Div([html.I(className='bi bi-file-earmark me-1'), f"{f['name']} ({_fmt_size(f['size'])})",
                               html.Span(' ×', id={'type': del_type, 'i': i}, n_clicks=0, className='text-danger ms-1',
                                         style={'cursor': 'pointer'}, title='빼기')])
                     for i, f in enumerate(files)] + [html.Div(f'합계 {_fmt_size(total)}', className='text-muted')])


def _upload_box(upload_id: str, text: str):
    return dcc.Upload(id=upload_id, multiple=True, children=html.Div([html.I(className='bi bi-paperclip me-1'), text]),
                      className='border border-2 rounded text-center text-muted small py-3 mb-2',
                      style={'borderStyle': 'dashed', 'cursor': 'pointer'})


def _compose_card():
    contacts = hom.load_contacts()
    subject_t, body_t = hom.template()
    order_opts = _order_date_options()
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-envelope-paper me-1'), '양식 메일 보내기'], className='fw-semibold')),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([dbc.Label('발신 계정', className='small mb-1'),
                         dcc.Dropdown(id='hro-sender', options=hom.sender_options(), clearable=False)], md=6),
                dbc.Col([dbc.Label('발령일', className='small mb-1'),
                         dcc.Dropdown(id='hro-order-date', options=order_opts, value=order_opts[0]['value'],
                                      clearable=False)], md=6),
            ], className='g-2 mb-3'),
            dbc.Label('받을 부서 담당자(수신 TO)', className='small mb-1'),
            html.Div([
                dbc.Button('전체 선택', id='hro-all', color='link', size='sm', className='p-0 me-3'),
                dbc.Button('선택 해제', id='hro-none', color='link', size='sm', className='p-0'),
            ], className='mb-1'),
            dbc.Checklist(id='hro-recipients', options=mr.recipient_options(contacts), value=[],
                          className='small mb-1', style={'columns': '2'}),
            html.Div('아래 "부서별 담당자"에 먼저 등록하세요.' if not contacts else '', id='hro-recipients-hint',
                     className='small text-muted mb-3'),
            mr.cc_block('hro', HR_STORE),
            dbc.Row([
                dbc.Col([
                    html.Div([dbc.Label('제목·본문 템플릿', className='small mb-0 me-2'),
                              dbc.Button([html.I(className='bi bi-save me-1'), '템플릿 저장'], id='hro-tpl-save',
                                         color='secondary', outline=True, size='sm', className='py-0'),
                              html.Span(id='hro-tpl-msg', className='small ms-2')],
                             className='d-flex align-items-center mb-1'),
                    html.Div(['평소 쓰시는 제목·본문을 그대로 붙여 넣고(서식 유지, 그림은 빠짐), 날짜 자리에 ',
                              html.Code('{발령일}'), ' ', html.Code('{발령일_월일}'), ' ', html.Code('{회신일}'), ' ',
                              html.Code('{회신일_월일}'), ' ', html.Code('{메일 발송일}'), ' ', html.Code('{메일 발송일_월일}'),
                              '을 넣으면 발령일·메일 보내는 날에 맞춰 바뀝니다(예: 2026.12.16 / 12월 16일(수)). '
                              '저장하면 다음에도, 자동 발송에도 이 템플릿을 씁니다.'], className='small text-muted mb-2'),
                    dbc.Input(id='hro-subject', value=subject_t, size='sm', className='mb-2'),
                    rich_editor('hro', body_t),
                ], md=6),
                dbc.Col([
                    dbc.Label('미리보기(발령일 적용)', className='small mb-1'),
                    html.Div(id='hro-preview', className='border rounded p-2 small bg-light',
                             style={'minHeight': '260px'}),
                ], md=6),
            ], className='g-3 mb-3'),
            dbc.Label('첨부파일', className='small mb-1'),
            _upload_box('hro-upload', '클릭 또는 끌어다 놓아 첨부(여러 개 가능, 합계 20MB까지)'),
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


def _rcp_summary(rcp: dict) -> str:
    parts = []
    if rcp['cc']:
        parts.append(f"참조 {len(rcp['cc'])}명")
    if rcp['bcc']:
        parts.append(f"비밀참조 {len(rcp['bcc'])}명")
    parts.append('한 통으로' if rcp['mode'] == 'single' else '담당자별 따로')
    return ', ' + ', '.join(parts)


def _auto_status():
    cfg = hom.auto_settings()
    if not cfg['enabled']:
        return html.Span('자동 발송이 꺼져 있습니다.', className='text-muted')
    nxt = hom.next_auto_send()
    who = (cfg['sender'] or {}).get('label', '')
    lines = [html.Div([html.I(className='bi bi-check-circle text-success me-1'),
                       f'켜짐 — 발령일 워킹데이 {hom.send_workdays()}일 전 발송·회신 기한 {hom.reply_workdays()}일 전, '
                       f'발신 {who}, 담당자 {len(hom.load_contacts())}명 전체, 첨부 {len(cfg["files"])}개'
                       + _rcp_summary(hom.recipient_settings())])]
    if nxt:
        od, when = nxt
        lines.append(html.Div(f'다음 발송: {_md(when.date())} {when:%H:%M} — {od:%Y.%m.%d}자 발령분'
                              f'(회신 {_md(hom.reply_due(od))})', className='fw-semibold'))
    return html.Div(lines)


def _day_opts() -> list:
    return [{'label': f'{n}일 전', 'value': n} for n in range(1, hom.MAX_WORKDAYS + 1)]


def _days_preview(send, reply) -> list:
    """다음 발령일 기준 발송일·회신 기한 예시(설정 화면에서 바로 확인용)."""
    if not send or not reply:
        return []
    od = hom.next_order_date()
    s, r = hom.workdays_before(od, int(send)), hom.workdays_before(od, int(reply))
    warn = int(reply) >= int(send)
    return [html.Div(f'예) {od:%Y.%m.%d}자 발령 → 발송 {_md(s)}, 회신 기한 {_md(r)} '
                     f'(받는 사람에게 워킹데이 {max(int(send) - int(reply), 0)}일)'),
            html.Div('발송일이 회신 기한보다 앞서야 합니다.', className='text-danger') if warn else None]


def _auto_card():
    cfg = hom.auto_settings()
    files = [{'name': n, 'size': len(b)} for n, b in hom.auto_files()]
    sender_value = hom.SHARED_SENDER if cfg['sender'] and not cfg['sender'].get('user_id') else None
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-alarm me-1'), '자동 발송'], className='fw-semibold')),
        dbc.CardBody([
            html.Div(f'켜 두면 매월 1일·16일 발령일의 워킹데이 아래 설정한 일수 전, 지정한 시각에 위 "부서별 담당자" '
                     f'전체에게 저장된 템플릿·참조인·발송 방식과 아래 첨부로 보냅니다(발령일당 한 번). 워킹데이는 토·일, 공휴일(대체공휴일 포함), '
                     f'아래 회사 휴무일을 뺀 날입니다.', className='small text-muted mb-2'),
            dbc.Row([
                dbc.Col(dbc.Switch(id='hro-auto-on', label='자동 발송 사용', value=cfg['enabled']), md=3),
                dbc.Col([dbc.Label('발송 시각', className='small mb-1'),
                         dcc.Dropdown(id='hro-auto-hour', options=[{'label': f'{h:02d}:00', 'value': h} for h in range(7, 20)],
                                      value=cfg['hour'], clearable=False)], md=3),
                dbc.Col([dbc.Label('발신 계정', className='small mb-1'),
                         dcc.Dropdown(id='hro-auto-sender', options=hom.sender_options(), value=sender_value,
                                      clearable=False)], md=6),
            ], className='g-2 align-items-end mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('발송일 — 발령일의 워킹데이 며칠 전', className='small mb-1'),
                         dcc.Dropdown(id='hro-send-days', options=_day_opts(), value=hom.send_workdays(),
                                      clearable=False)], md=3),
                dbc.Col([dbc.Label('회신 기한 — 발령일의 워킹데이 며칠 전', className='small mb-1'),
                         dcc.Dropdown(id='hro-reply-days', options=_day_opts(), value=hom.reply_workdays(),
                                      clearable=False)], md=3),
                dbc.Col(html.Div(id='hro-days-preview', className='small text-muted'), md=6),
            ], className='g-2 align-items-end mb-2'),
            dbc.Label('자동 발송용 첨부(서버에 보관)', className='small mb-1'),
            _upload_box('hro-auto-upload', '클릭 또는 끌어다 놓아 첨부(여러 개 가능, 계속 추가됨 — 같은 이름이면 새 파일로 바뀜, 합계 20MB까지)'),
            html.Div(_file_list(files, 'hro-auto-file-del'), id='hro-auto-files', className='small mb-2'),
            dcc.Store(id='hro-auto-files-store', data=None),
            dbc.Label('회사 휴무일(공휴일 외, 예: 창립기념일) — YYYY-MM-DD, 줄바꿈이나 쉼표로 구분', className='small mb-1'),
            dbc.Textarea(id='hro-holidays', value='\n'.join(hom.company_holidays()), rows=2, className='small mb-1'),
            html.Div('' if hom.holidays_available() else
                     '공휴일 계산 패키지(holidays)가 설치되지 않아 지금은 주말·회사 휴무일만 뺍니다 — 서버 재빌드 필요.',
                     className='small text-danger mb-1'),
            dbc.Button([html.I(className='bi bi-save me-1'), '자동 발송 설정 저장'], id='hro-auto-save', color='primary',
                       size='sm', className='mt-1'),
            html.Div(id='hro-auto-msg', className='small mt-2'),
            html.Div(_auto_status(), id='hro-auto-status', className='small mt-2'),
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


def _reply_card():
    """회신 현황(2026-11-23) — 발령일별 부서 회신(비실명 계정 메일 자동 취합 + 직접 올리기)."""
    opts = ri_ui.period_options('hr_order')
    nxt = hom.next_order_date().isoformat()
    value = nxt if any(o['value'] == nxt for o in opts) else opts[0]['value']
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-inboxes me-1'), '회신 현황 — 부서별'], className='fw-semibold')),
        dbc.CardBody([
            html.Div('부서 담당자의 회신 메일이 아래 "받은 회신 메일"에서 자동으로 여기에 등록됩니다. 메일로 받지 못한 회신은 부서를 '
                     '고르고 직접 올리세요(같은 부서는 새 회신으로 바뀜).', className='small text-muted mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('발령일', className='small mb-1'),
                         dcc.Dropdown(id='hro-rep-date', options=opts, value=value, clearable=False)], md=3),
                dbc.Col([dbc.Label('부서(직접 올릴 때)', className='small mb-1'),
                         dcc.Dropdown(id='hro-rep-dept', options=hom.departments(), placeholder='부서')], md=3),
                dbc.Col(dcc.Upload(id='hro-rep-upload', multiple=True,
                                   children=html.Div([html.I(className='bi bi-upload me-1'), '회신 파일 직접 올리기(여러 개 가능)']),
                                   className='border border-2 rounded text-center text-muted small py-2',
                                   style={'borderStyle': 'dashed', 'cursor': 'pointer'}), md=6),
            ], className='g-2 align-items-end mb-2'),
            html.Div(id='hro-rep-msg', className='small mb-2'),
            html.Div(id='hro-rep-status'),
            dcc.Store(id='hro-rep-ver', data=0),
            dcc.Download(id='hro-rep-download'),
        ]),
    ], className='shadow-sm mb-4')


def _reply_table(order_date: str):
    rows = hom.reply_status(order_date)
    if not rows:
        return html.Div('부서별 담당자가 없습니다.', className='small text-muted')
    done = sum(1 for r in rows if r['replied'])
    body = []
    for r in rows:
        files = [html.Div(html.Span([html.I(className='bi bi-download me-1'), n],
                                    id={'type': 'hro-rep-dl', 'd': r['dept'], 'n': n}, n_clicks=0, className='text-primary',
                                    style={'cursor': 'pointer'})) for n in r['files']]
        body.append(html.Tr([
            html.Td(r['dept']), html.Td(r['contact']),
            html.Td(dbc.Badge('회신', color='success') if r['replied'] else dbc.Badge('미회신', color='secondary')),
            html.Td(files or ''), html.Td(r['at'].replace('T', ' ')[:16]),
            html.Td(('메일' + (f" ({r['sender']})" if r['sender'] else '')) if r['source'] == 'mail'
                    else ('직접 올림' if r['replied'] else '')),
            html.Td(html.Span(html.I(className='bi bi-trash'), id={'type': 'hro-rep-del', 'd': r['dept']}, n_clicks=0,
                              className='text-danger', style={'cursor': 'pointer'}, title='회신 지우기') if r['replied'] else ''),
        ]))
    return html.Div([
        html.Div(f'{order_date.replace("-", ".")}자 회신 {done}/{len(rows)}개 부서', className='small fw-semibold mb-1'),
        dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('부서', '담당자', '상태', '파일', '받은 시각', '경로', '')])),
                   html.Tbody(body)], size='sm', bordered=True, hover=True, className='small mb-0'),
    ])


def _log_card():
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-clock-history me-1'), '발송 이력(최근 50건)'],
                                 className='fw-semibold')),
        dbc.CardBody(html.Div(_log_table(), id='hro-log')),
    ], className='shadow-sm')


def _log_cc(e: dict) -> str:
    cc = ', '.join(p.get('name') or p.get('email', '') for p in e.get('cc') or [])
    bcc = ', '.join(p.get('name') or p.get('email', '') for p in e.get('bcc') or [])
    out = cc + (f' / 비밀참조 {bcc}' if bcc else '')
    if out and e.get('mode') == 'single':
        out += ' (한 통)'
    return out


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
            html.Td('자동' if e.get('kind') == 'auto' else '수동'),
            html.Td(e.get('order_date', '').replace('-', '.')),
            html.Td(e.get('by_name') or e.get('by')),
            html.Td(e.get('sender', '')),
            html.Td(e.get('subject', '')),
            html.Td(_log_cc(e)),
            html.Td(', '.join(f['name'] for f in e.get('files', []))),
            html.Td([html.Span(f'성공 {len(ok)}', className='text-success me-2'),
                     html.Span(f'실패 {len(fail)}', className='text-danger') if fail else None],
                    title='\n'.join(f"{r['dept']} {r['email']}: {r['error']}" for r in fail) or None),
        ]))
    return dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('시각', '구분', '발령일', '보낸 사람', '발신 계정', '제목',
                                                               '참조', '첨부', '결과')])),
                      html.Tbody(body)], size='sm', bordered=True, className='small mb-0')


def layout():
    if not hom.can_use():
        return dbc.Alert('인사발령 메뉴를 쓸 권한이 없습니다. 관리자에게 요청하세요.', color='warning', className='mt-3')
    return dbc.Container([
        html.H4([html.I(className='bi bi-envelope-paper me-2 text-primary'), '인사발령'], className='fw-bold mt-2'),
        html.P(f'매월 1일·16일 발령분 취합 양식을 부서별 담당자에게 메일로 보냅니다. 선택한 담당자(수신)에게 같은 첨부로 '
               f'보내고 참조·비밀참조를 따로 넣을 수 있으며, 회신일은 발령일의 워킹데이 {hom.reply_workdays()}일 전으로 자동 계산합니다'
               f'(아래 자동 발송 설정에서 변경).',
               className='text-muted small'),
        _compose_card(),
        mr.contacts_card('hro', HR_STORE),
        _reply_card(),
        ri_ui.card('hro', 'hr_order'),
        _auto_card(),
        _settings_card(),
        _log_card(),
    ], fluid=True, className='py-3')


# ── 콜백: 양식 메일 ─────────────────────────────────────────────────────────

@callback(Output('hro-sender', 'value'), Input('hro-sender', 'options'))
def _default_sender(options):
    return options[0]['value'] if options else None


def _body_frame(body: str, d: date, height: str = '300px'):
    """서식 본문 미리보기 — 정리(sanitize)한 HTML을 sandbox iframe에(스크립트 실행 없음, 화면 CSS와 분리)."""
    doc = ('<html><head><meta charset="utf-8"></head><body style="margin:8px">'
           + hom.body_html(hom.render(body or '', d)) + '</body></html>')
    return html.Iframe(srcDoc=doc, sandbox='', style={'width': '100%', 'height': height, 'border': '0',
                                                      'background': '#fff'})


register_rich_editor('hro')


@callback(Output('hro-preview', 'children'), Input('hro-order-date', 'value'), Input('hro-subject', 'value'),
          Input('hro-body', 'data'))
def _preview(od, subject, body):
    if not od:
        return ''
    d = date.fromisoformat(od)
    return html.Div([html.Div([html.B('제목: '), hom.render(subject, d)], className='mb-2'), _body_frame(body, d)])


@callback(Output('hro-tpl-msg', 'children'), Input('hro-tpl-save', 'n_clicks'), State('hro-subject', 'value'),
          State('hro-body', 'data'), prevent_initial_call=True)
def _save_template(n, subject, body):
    if not n:
        return no_update
    try:
        hom.save_template(subject, body)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger')
    return html.Span('저장했습니다.', className='text-success')


@callback(Output('hro-recipients', 'value'), Input('hro-all', 'n_clicks'), Input('hro-none', 'n_clicks'),
          State('hro-recipients', 'options'), prevent_initial_call=True)
def _select_all(_a, _n, options):
    return [o['value'] for o in options or []] if ctx.triggered_id == 'hro-all' else []


def _add_uploads(files, contents, filenames):
    files = list(files or [])
    for content, name in zip(contents or [], filenames or []):
        b64 = content.split(',', 1)[1]
        files.append({'name': name, 'b64': b64, 'size': len(base64.b64decode(b64))})
    return files


@callback(Output('hro-files-store', 'data'), Output('hro-upload', 'contents'),
          Input('hro-upload', 'contents'), Input({'type': 'hro-file-del', 'i': dash.ALL}, 'n_clicks'),
          State('hro-upload', 'filename'), State('hro-files-store', 'data'), prevent_initial_call=True)
def _files(contents, dels, filenames, files):
    if isinstance(ctx.triggered_id, dict):           # × 눌러 빼기
        if not any(dels or []):
            return no_update, no_update
        files = list(files or [])
        files.pop(ctx.triggered_id['i'])
        return files, no_update
    return _add_uploads(files, contents, filenames), None


@callback(Output('hro-files', 'children'), Input('hro-files-store', 'data'))
def _files_view(files):
    return _file_list(files, 'hro-file-del')


@callback(Output('hro-confirm', 'is_open'), Output('hro-confirm-body', 'children'), Output('hro-result', 'children'),
          Input('hro-send', 'n_clicks'), Input('hro-confirm-cancel', 'n_clicks'),
          State('hro-recipients', 'value'), State('hro-recipients', 'options'), State('hro-subject', 'value'),
          State('hro-body', 'data'), State('hro-order-date', 'value'),
          State('hro-files-store', 'data'), State('hro-sender', 'value'), State('hro-sender', 'options'),
          State('hro-cc', 'value'), State('hro-bcc', 'value'), State('hro-mode', 'value'),
          prevent_initial_call=True)
def _confirm(_send, _cancel, emails, options, subject, body, od, files, sender, sender_opts, cc, bcc, mode):
    if ctx.triggered_id == 'hro-confirm-cancel':
        return False, no_update, no_update
    problems = [m for ok, m in ((emails, '받을 담당자를 고르세요.'), ((subject or '').strip(), '제목을 입력하세요.'),
                                (files, '첨부파일을 올리세요.'), (sender, '발신 계정을 고르세요.'), (od, '발령일을 고르세요.'))
                if not ok]
    if problems:
        return False, no_update, dbc.Alert(' '.join(problems), color='warning', className='small py-2')
    try:
        cc_p, bcc_p = mr.cc_people(HR_STORE, cc, bcc)
    except ValueError as exc:
        return False, no_update, dbc.Alert(str(exc), color='warning', className='small py-2')
    d = date.fromisoformat(od)
    label = {o['value']: o['label'] for o in options or []}
    sender_label = next((o['label'] for o in sender_opts or [] if o['value'] == sender), sender)
    single = mode == 'single'
    n_mail = 1 if single else len(emails)
    return True, html.Div([
        html.Div([html.B('발신: '), sender_label], className='small mb-1'),
        html.Div([html.B('제목: '), hom.render(subject, d)], className='small mb-1'),
        html.Div([html.B('첨부: '), ', '.join(f['name'] for f in files)], className='small mb-2'),
        html.Div(_body_frame(body, d, '240px'), className='border rounded mb-2'),
        html.Div(html.B(f"수신(TO) {len(emails)}명 — " + ('한 통으로 발송' if single else '한 명씩 따로 발송')),
                 className='small'),
        html.Ul([html.Li(label.get(e, e)) for e in emails], className='small mb-2'),
        html.Div(html.B(f'참조(CC) {len(cc_p)}명'), className='small') if cc_p else None,
        html.Ul([html.Li(f"{p['name']} [{p['dept']}] · {p['email']}") for p in cc_p], className='small mb-2') if cc_p else None,
        html.Div(html.B(f'비밀참조(BCC) {len(bcc_p)}명'), className='small') if bcc_p else None,
        html.Ul([html.Li(f"{p['name']} [{p['dept']}] · {p['email']}") for p in bcc_p], className='small mb-2') if bcc_p else None,
        html.Div(f'참조인은 메일 {n_mail}통을 받습니다.', className='small text-muted') if (cc_p or bcc_p) else None,
    ]), no_update


@callback(Output('hro-result', 'children', allow_duplicate=True), Output('hro-confirm', 'is_open', allow_duplicate=True),
          Output('hro-log', 'children'),
          Input('hro-confirm-ok', 'n_clicks'),
          State('hro-recipients', 'value'), State('hro-subject', 'value'), State('hro-body', 'data'),
          State('hro-order-date', 'value'), State('hro-files-store', 'data'), State('hro-sender', 'value'),
          State('hro-cc', 'value'), State('hro-bcc', 'value'), State('hro-mode', 'value'),
          prevent_initial_call=True)
def _send(n, emails, subject, body, od, files, sender, cc, bcc, mode):
    if not n:
        return no_update, no_update, no_update
    d = date.fromisoformat(od)
    contacts = hom.contacts_for_emails(emails)            # 겸직이면 여러 행 — 발송 때 한 통으로 묶임
    attachments = [(f['name'], base64.b64decode(f['b64'])) for f in files or []]
    try:
        cc_p, bcc_p = mr.cc_people(HR_STORE, cc, bcc)
        results = hom.send(contacts, hom.render(subject, d), hom.render(body, d), attachments, sender, order_date=d,
                           cc=cc_p, bcc=bcc_p, mode=mode or 'each')
    except (PermissionError, ValueError) as exc:
        return dbc.Alert(str(exc), color='danger', className='small py-2'), False, no_update
    ok = [r for r in results if r['ok']]
    fail = [r for r in results if not r['ok']]
    items = [html.Div([html.I(className='bi bi-check-circle text-success me-1'), f'{len(ok)}명에게 보냈습니다.'])] if ok else []
    items += [html.Div([html.I(className='bi bi-x-circle text-danger me-1'), f"{r['dept']} {r['email']}: {r['error']}"])
              for r in fail]
    return (dbc.Alert(items, color='success' if not fail else 'warning', className='small py-2'), False, _log_table())



# ── 콜백: 자동 발송 ─────────────────────────────────────────────────────────

@callback(Output('hro-days-preview', 'children'), Input('hro-send-days', 'value'), Input('hro-reply-days', 'value'))
def _days_preview_cb(send, reply):
    return _days_preview(send, reply)


@callback(Output('hro-auto-sender', 'value'), Input('hro-auto-sender', 'options'), State('hro-auto-sender', 'value'))
def _default_auto_sender(options, value):
    return value or (options[0]['value'] if options else None)


@callback(Output('hro-auto-files', 'children'), Output('hro-auto-upload', 'contents'), Output('hro-auto-msg', 'children'),
          Input('hro-auto-upload', 'contents'), Input({'type': 'hro-auto-file-del', 'i': dash.ALL}, 'n_clicks'),
          State('hro-auto-upload', 'filename'), prevent_initial_call=True)
def _auto_files(contents, dels, filenames):
    current = hom.auto_files()
    try:
        if isinstance(ctx.triggered_id, dict):
            if not any(dels or []):
                return no_update, no_update, no_update
            i = ctx.triggered_id['i']
            if i < len(current):
                hom.remove_auto_file(current[i][0])
        else:
            new = [(n, base64.b64decode(c.split(',', 1)[1])) for c, n in zip(contents or [], filenames or [])]
            hom.add_auto_files(new)
    except (PermissionError, ValueError) as exc:
        return no_update, None, html.Span(str(exc), className='text-danger')
    files = [{'name': n, 'size': len(b)} for n, b in hom.auto_files()]
    return _file_list(files, 'hro-auto-file-del'), None, html.Span('자동 발송용 첨부를 저장했습니다.', className='text-success')


@callback(Output('hro-auto-msg', 'children', allow_duplicate=True), Output('hro-auto-status', 'children'),
          Input('hro-auto-save', 'n_clicks'),
          State('hro-auto-on', 'value'), State('hro-auto-hour', 'value'), State('hro-auto-sender', 'value'),
          State('hro-holidays', 'value'), State('hro-send-days', 'value'), State('hro-reply-days', 'value'),
          prevent_initial_call=True)
def _save_auto(n, enabled, hour, sender, holidays_text, send_days, reply_days):
    if not n:
        return no_update, no_update
    try:
        hom.set_workdays(send_days, reply_days)
        hom.set_company_holidays(holidays_text)
        hom.save_auto(bool(enabled), hour, sender)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), _auto_status()
    return html.Span(f'저장했습니다({datetime.now():%H:%M}).', className='text-success'), _auto_status()


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


mr.register('hro', HR_STORE, 'hro-auto-status', lambda: _auto_status())


# ── 콜백: 회신 현황 ─────────────────────────────────────────────────────────

def _clicks_of(trig: dict) -> int:
    for group in ctx.inputs_list:
        for item in group if isinstance(group, list) else [group]:
            if item.get('id') == trig:
                return item.get('value') or 0
    return 0


@callback(Output('hro-rep-status', 'children'), Input('hro-rep-date', 'value'), Input('hro-rep-ver', 'data'))
def _rep_status(order_date, _ver):
    return _reply_table(order_date) if order_date else ''


@callback(Output('hro-rep-msg', 'children'), Output('hro-rep-ver', 'data'), Output('hro-rep-upload', 'contents'),
          Input('hro-rep-upload', 'contents'), Input({'type': 'hro-rep-del', 'd': ALL}, 'n_clicks'),
          State('hro-rep-upload', 'filename'), State('hro-rep-date', 'value'), State('hro-rep-dept', 'value'),
          State('hro-rep-ver', 'data'), prevent_initial_call=True)
def _rep_edit(contents, _dels, filenames, order_date, dept, ver):
    trig = ctx.triggered_id
    try:
        if isinstance(trig, dict):
            if not _clicks_of(trig):
                return no_update, no_update, no_update
            hom.delete_reply(order_date, trig['d'])
            return html.Span(f"{trig['d']} 회신을 지웠습니다.", className='text-muted'), (ver or 0) + 1, no_update
        if not contents:
            return no_update, no_update, no_update
        if not dept:
            return html.Span('부서를 먼저 고르세요.', className='text-warning'), no_update, None
        files = [(n, base64.b64decode(c.split(',', 1)[1])) for c, n in zip(contents, filenames or [])]
        hom.save_reply(order_date, dept, files)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), no_update, None
    return html.Span(f'{dept} 회신을 저장했습니다({len(files)}개 파일).', className='text-success'), (ver or 0) + 1, None


@callback(Output('hro-rep-download', 'data'), Input({'type': 'hro-rep-dl', 'd': ALL, 'n': ALL}, 'n_clicks'),
          State('hro-rep-date', 'value'), prevent_initial_call=True)
def _rep_download(_n, order_date):
    trig = ctx.triggered_id
    if not isinstance(trig, dict) or not _clicks_of(trig) or not hom.can_use():
        return no_update
    f = hom.reply_file(order_date, trig['d'], trig['n'])
    return dcc.send_bytes(f[1], f[0]) if f else no_update


ri_ui.register('hro', 'hr_order', 'hro-rep-ver')
