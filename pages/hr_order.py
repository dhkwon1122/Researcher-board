"""
업무 시나리오 > 인사발령(2026-11-19) — 인사발령 작성 양식(첨부파일)을 부서별 담당자에게 메일로 보낸다.
흐름·저장·권한·자동 발송은 services/hr_order_mail.py 참고.
"""
import base64
import io
from datetime import date, datetime

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
_WD = '월화수목금토일'


def _md(d: date) -> str:
    return f'{d.month}월 {d.day}일({_WD[d.weekday()]})'


def _contact_option(c: dict) -> dict:
    who = f" · {c['name']}" if c.get('name') else ''
    return {'label': f"{c['dept']}{who} <{c['email']}>", 'value': c['email']}


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


_FONTS = [('맑은 고딕', "'Malgun Gothic'"), ('굴림', 'Gulim'), ('돋움', 'Dotum'), ('바탕', 'Batang'), ('궁서', 'Gungsuh'),
          ('Arial', 'Arial'), ('Times New Roman', "'Times New Roman'"), ('Courier New', "'Courier New'")]
_SIZES = [('10', '1'), ('13', '2'), ('16', '3'), ('18', '4'), ('24', '5'), ('32', '6')]


def _tb_btn(icon: str, cmd: str, tip: str, val: str | None = None):
    kw = {'data-hro-cmd': cmd}
    if val:
        kw['data-hro-val'] = val
    return html.Button(html.I(className=f'bi bi-{icon}'), type='button', title=tip,
                       className='btn btn-sm btn-light border px-2 py-0', **kw)


def _editor_toolbar():
    """본문 서식 도구 모음 — 실제 동작은 assets/hr_order_editor.js(document.execCommand)."""
    select_cls = 'form-select form-select-sm d-inline-block w-auto py-0'
    return html.Div([
        html.Select([html.Option('글꼴', value='')] + [html.Option(n, value=v) for n, v in _FONTS],
                    className=select_cls, title='글꼴', **{'data-hro-cmd': 'fontName'}),
        html.Select([html.Option('크기', value='')] + [html.Option(f'{n}px', value=v) for n, v in _SIZES],
                    className=select_cls, title='글자 크기', **{'data-hro-cmd': 'fontSize'}),
        html.Span(className='vr mx-1'),
        _tb_btn('type-bold', 'bold', '굵게(Ctrl+B)'),
        _tb_btn('type-italic', 'italic', '기울임(Ctrl+I)'),
        _tb_btn('type-underline', 'underline', '밑줄(Ctrl+U)'),
        _tb_btn('type-strikethrough', 'strikeThrough', '취소선'),
        html.Span(className='vr mx-1'),
        html.Label([html.I(className='bi bi-fonts me-1'), html.Span('글자색', className='small'),
                    html.Div(className='hro-color', **{'data-hro-cmd': 'foreColor', 'data-hro-color': '#d00000'})],
                   className='d-inline-flex align-items-center mb-0 me-1', title='글자색'),
        html.Label([html.I(className='bi bi-paint-bucket me-1'), html.Span('바탕색', className='small'),
                    html.Div(className='hro-color', **{'data-hro-cmd': 'hiliteColor', 'data-hro-color': '#ffff00'})],
                   className='d-inline-flex align-items-center mb-0 me-1', title='바탕색(형광펜)'),
        html.Span(className='vr mx-1'),
        _tb_btn('list-ul', 'insertUnorderedList', '글머리 기호'),
        _tb_btn('list-ol', 'insertOrderedList', '번호 매기기'),
        _tb_btn('text-left', 'justifyLeft', '왼쪽 정렬'),
        _tb_btn('text-center', 'justifyCenter', '가운데 정렬'),
        html.Span(className='vr mx-1'),
        _tb_btn('arrow-counterclockwise', 'undo', '되돌리기(Ctrl+Z)'),
        _tb_btn('eraser', 'removeFormat', '서식 지우기'),
    ], className='d-flex flex-wrap align-items-center gap-1 border border-bottom-0 rounded-top bg-light px-2 py-1')


def _cc_options(saved: list) -> list:
    """참조 선택 옵션 — 현재 인력현황 + 이미 저장된 사람(인력현황에서 빠졌어도 유지)."""
    opts = hom.person_options()
    have = {o['value'] for o in opts}
    extra = [{'label': f"{p.get('name', '')} [{p.get('dept', '')}] ({p['rid']})", 'value': p['rid']}
             for p in saved if p.get('rid') and p['rid'] not in have]
    return extra + opts


def _cc_block():
    rcp = hom.recipient_settings()
    opts = _cc_options(rcp['cc'] + rcp['bcc'])
    return html.Div([
        dbc.Row([
            dbc.Col([dbc.Label('참조(CC) — 우리 부서 동료 등', className='small mb-1'),
                     dcc.Dropdown(id='hro-cc', options=opts, value=[p['rid'] for p in rcp['cc'] if p.get('rid')],
                                  multi=True, placeholder='인력현황에서 이름/사번 검색')], md=6),
            dbc.Col([dbc.Label('비밀참조(BCC)', className='small mb-1'),
                     dcc.Dropdown(id='hro-bcc', options=opts, value=[p['rid'] for p in rcp['bcc'] if p.get('rid')],
                                  multi=True, placeholder='필요할 때만')], md=6),
        ], className='g-2 mb-2'),
        dbc.Label('발송 방식', className='small mb-0'),
        dbc.RadioItems(id='hro-mode', value=rcp['mode'], className='small', options=[
            {'label': '담당자별 따로 — 부서끼리 주소가 안 보임, 참조인은 담당자 수만큼 받음', 'value': 'each'},
            {'label': '한 통으로 — 담당자 전원을 수신(TO)에 넣어 한 번, 참조인도 한 통만 받음', 'value': 'single'},
        ]),
        html.Div([dbc.Button([html.I(className='bi bi-save me-1'), '참조·발송 방식 저장'], id='hro-rcp-save',
                             color='secondary', outline=True, size='sm', className='py-0'),
                  html.Span('저장하면 다음에도, 자동 발송에도 이 참조인·방식을 씁니다.', className='small text-muted ms-2'),
                  html.Span(id='hro-rcp-msg', className='small ms-2')], className='d-flex align-items-center mt-1'),
    ], className='border rounded p-2 mb-3')


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
            dbc.Checklist(id='hro-recipients', options=[_contact_option(c) for c in contacts], value=[],
                          className='small mb-1', style={'columns': '2'}),
            html.Div('아래 "부서별 담당자"에 먼저 등록하세요.' if not contacts else '', id='hro-recipients-hint',
                     className='small text-muted mb-3'),
            _cc_block(),
            dbc.Row([
                dbc.Col([
                    html.Div([dbc.Label('제목·본문 템플릿', className='small mb-0 me-2'),
                              dbc.Button([html.I(className='bi bi-save me-1'), '템플릿 저장'], id='hro-tpl-save',
                                         color='secondary', outline=True, size='sm', className='py-0'),
                              html.Span(id='hro-tpl-msg', className='small ms-2')],
                             className='d-flex align-items-center mb-1'),
                    html.Div(['평소 쓰시는 제목·본문을 그대로 붙여 넣고(서식 유지, 그림은 빠짐), 날짜 자리에 ',
                              html.Code('{발령일}'), ' ', html.Code('{발령일_월일}'), ' ', html.Code('{회신일}'), ' ',
                              html.Code('{회신일_월일}'), '을 넣으면 발령일에 맞춰 바뀝니다(예: 2026.12.16 / 12월 16일(수)). '
                              '저장하면 다음에도, 자동 발송에도 이 템플릿을 씁니다.'], className='small text-muted mb-2'),
                    dbc.Input(id='hro-subject', value=subject_t, size='sm', className='mb-2'),
                    _editor_toolbar(),
                    html.Div(id='hro-body-editor', contentEditable='true', className='form-control hro-editor',
                             style={'minHeight': '260px', 'maxHeight': '480px', 'overflowY': 'auto',
                                    'fontFamily': "'Malgun Gothic', sans-serif", 'fontSize': '14px', 'lineHeight': '1.7',
                                    'borderTopLeftRadius': 0, 'borderTopRightRadius': 0}),
                    dcc.Store(id='hro-body', data=body_t),
                    dcc.Store(id='hro-editor-init'),
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


def _contacts_card():
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-people me-1'), '부서별 담당자'], className='fw-semibold')),
        dbc.CardBody([
            dbc.Row([
                dbc.Col(dcc.Dropdown(id='hro-person', options=hom.person_options(),
                                     placeholder='인력현황에서 이름·사번 검색해 추가(이메일 = Knox ID@samsung.com)'), md=8),
                dbc.Col(dbc.Button([html.I(className='bi bi-person-plus me-1'), '담당자로 추가'], id='hro-person-add',
                                   color='primary', outline=True, size='sm'), md=4),
            ], className='g-2 align-items-center mb-2'),
            html.Div([
                dbc.Button([html.I(className='bi bi-plus me-1'), '빈 행 추가'], id='hro-row-add', color='secondary',
                           outline=True, size='sm', className='me-1'),
                dbc.Button([html.I(className='bi bi-trash me-1'), '선택 삭제'], id='hro-row-del', color='danger',
                           outline=True, size='sm', className='me-1'),
                dbc.Button([html.I(className='bi bi-save me-1'), '저장'], id='hro-row-save', color='primary', size='sm',
                           className='me-2'),
                dcc.Upload(id='hro-contacts-upload', children=dbc.Button(
                    [html.I(className='bi bi-file-earmark-excel me-1'), '엑셀로 불러오기'], color='success', outline=True,
                    size='sm'), accept='.xlsx,.xls,.csv'),
                html.Span('추가·수정 뒤 저장을 눌러야 반영됩니다(엑셀 열: 부서 · 담당자 · 이메일)', className='small text-muted ms-2'),
            ], className='d-flex align-items-center flex-wrap mb-2'),
            dag.AgGrid(id='hro-contacts', columnDefs=_CONTACT_COLUMNS, rowData=hom.load_contacts(),
                       dashGridOptions={'rowSelection': 'multiple', 'singleClickEdit': True,
                                        'stopEditingWhenCellsLoseFocus': True},
                       style={'height': '320px'}, className='ag-theme-alpine'),
            html.Div(id='hro-contacts-msg', className='small mt-2'),
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
        _contacts_card(),
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


# 편집기 첫 내용 채우기(저장된 템플릿 HTML) — 이후 입력은 assets/hr_order_editor.js가 hro-body로 올려 보냄
dash.clientside_callback(
    """function(data) {
        const ed = document.getElementById('hro-body-editor');
        if (ed && typeof data === 'string' && ed.innerHTML !== data) { ed.innerHTML = data; }
        return window.dash_clientside.no_update;
    }""",
    Output('hro-editor-init', 'data'), Input('hro-body', 'data'))


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


@callback(Output('hro-rcp-msg', 'children'), Output('hro-auto-status', 'children', allow_duplicate=True),
          Input('hro-rcp-save', 'n_clicks'), State('hro-cc', 'value'), State('hro-bcc', 'value'),
          State('hro-mode', 'value'), prevent_initial_call=True)
def _save_rcp(n, cc, bcc, mode):
    if not n:
        return no_update, no_update
    try:
        rcp = hom.save_recipient_settings(cc or [], bcc or [], mode or 'each')
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), no_update
    return (html.Span(f"저장했습니다(참조 {len(rcp['cc'])}명, 비밀참조 {len(rcp['bcc'])}명).", className='text-success'),
            _auto_status())


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
        cc_p, bcc_p = _cc_people(cc, bcc)
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


def _cc_people(cc, bcc):
    saved = hom.recipient_settings()
    pool = saved['cc'] + saved['bcc']
    cc_p = hom.people_for(cc or [], pool)
    cc_e = {p['email'].lower() for p in cc_p}
    bcc_p = [p for p in hom.people_for(bcc or [], pool) if p['email'].lower() not in cc_e]
    return cc_p, bcc_p


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
    by_email = {c['email']: c for c in hom.load_contacts()}
    contacts = [by_email[e] for e in emails or [] if e in by_email]
    attachments = [(f['name'], base64.b64decode(f['b64'])) for f in files or []]
    try:
        cc_p, bcc_p = _cc_people(cc, bcc)
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


# ── 콜백: 부서별 담당자 ─────────────────────────────────────────────────────

@callback(Output('hro-contacts', 'rowData'), Output('hro-contacts-msg', 'children'),
          Input('hro-row-add', 'n_clicks'), Input('hro-row-del', 'n_clicks'), Input('hro-contacts-upload', 'contents'),
          Input('hro-person-add', 'n_clicks'),
          State('hro-contacts-upload', 'filename'), State('hro-contacts', 'rowData'), State('hro-contacts', 'selectedRows'),
          State('hro-person', 'value'), prevent_initial_call=True)
def _edit_contacts(_add, _del, content, _padd, filename, rows, selected, person):
    rows = list(rows or [])
    trig = ctx.triggered_id
    if trig == 'hro-person-add':
        if not person:
            return no_update, html.Span('추가할 사람을 먼저 검색해 고르세요.', className='text-warning')
        try:
            c = hom.contact_for_person(person)
        except ValueError as exc:
            return no_update, html.Span(str(exc), className='text-danger')
        if c['email'] and any(str(r.get('email', '')).lower() == c['email'].lower() for r in rows):
            return no_update, html.Span(f"{c['name']}님은 이미 목록에 있습니다.", className='text-warning')
        note = '' if c['email'] else ' — Knox ID가 없어 이메일을 직접 입력해야 합니다.'
        return rows + [c], html.Span(f"{c['name']}({c['dept']})을 추가했습니다{note} — 저장을 눌러야 반영됩니다.",
                                     className='text-warning' if note else 'text-muted')
    if trig == 'hro-row-add':
        return rows + [{'dept': '', 'name': '', 'email': ''}], ''
    if trig == 'hro-row-del':
        if not selected:
            return no_update, html.Span('삭제할 행을 체크하세요.', className='text-warning')
        return [r for r in rows if r not in selected], html.Span('삭제했습니다 — 저장을 눌러야 반영됩니다.', className='text-muted')
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
