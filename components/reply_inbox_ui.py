"""
받은 회신 메일 카드(2026-11-23) — 비실명 계정 POP3로 가져온 회신(services/reply_inbox)을 보여 주고, 자동 연결이 안 된 메일을
직접 지정·무시하고, 첨부를 내려받는다. 인사발령('hro')·업무분장('wa') 화면이 접두어로 같은 카드를 쓴다.
register(p, scenario, ver_id): 등록·가져오기 뒤 ver_id(dcc.Store data 숫자)를 올려 그 화면의 회신·제출 현황을 다시 그리게 한다.
"""
from datetime import date

import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from services import hr_order_mail as hom
from services import reply_inbox as ri

_BADGE = {'registered': 'success', 'review': 'warning', 'ignored': 'secondary', 'no_attachment': 'secondary'}


def _md(d: date) -> str:
    return f"{d.month}월 {d.day}일({'월화수목금토일'[d.weekday()]})"


def period_options(scenario: str) -> list:
    """업무분장: 대상월(지난 3개월~다음 2개월), 인사발령: 발령일(지난 2개월~다음 1개월의 1일·16일)."""
    today = date.today()
    if scenario == 'work_assign':
        from services import work_assign as wa
        return [{'label': f'{wa.target_label(t)}분', 'value': t} for t in (wa.target_of(today, k) for k in range(2, -4, -1))]
    out = []
    y, m = today.year, today.month
    for k in range(-2, 2):
        idx = y * 12 + (m - 1) + k
        yy, mm = idx // 12, idx % 12 + 1
        for dd in (1, 16):
            out.append(date(yy, mm, dd))
    return [{'label': f'{d:%Y.%m.%d}자', 'value': d.isoformat()} for d in sorted(out, reverse=True)]


def _status_line():
    cfg = ri.config_summary()
    if not cfg['configured']:
        return html.Div(['비실명 계정 POP3가 설정되지 않았습니다 — 서버 .env에 ', html.Code('MAIL_POP3_HOST'), ', ',
                         html.Code('MAIL_POP3_USER'), ', ', html.Code('MAIL_POP3_PASSWORD'),
                         '(필요하면 MAIL_POP3_PORT·MAIL_POP3_SSL)를 넣고 앱을 다시 시작하세요.'], className='small text-danger')
    lr = ri.last_run()
    last = ''
    if lr:
        last = (f" · 마지막 확인 {lr.get('at', '')}: " + (f"새 메일 {lr.get('new', 0)}통(등록 {lr.get('registered', 0)}, "
                                                          f"확인 필요 {lr.get('review', 0)})" if lr.get('ok')
                                                          else f"실패 — {lr.get('error', '')}"))
    return html.Div([html.I(className='bi bi-inbox me-1'), f"{cfg['account']} · {cfg['minutes']}분마다 확인{last}"],
                    className='small text-muted')


def _mail_table(p: str, scenario: str):
    rows = ri.list_mails(scenario, limit=50)
    if not rows:
        return html.Div('아직 받은 회신이 없습니다.', className='small text-muted')
    body = []
    for m in rows:
        sc = ri.SCENARIOS.get(m.get('scenario') or '', '')
        files = [html.Div(html.Span([html.I(className='bi bi-download me-1'), f['name']],
                                    id={'type': f'{p}-ri-dl', 'm': m['id'], 'f': i}, n_clicks=0, className='text-primary',
                                    style={'cursor': 'pointer'}))
                 for i, f in enumerate(m.get('files', []))]
        body.append(html.Tr([
            html.Td(m.get('mail_date') or m.get('received_at', '')[:16].replace('T', ' '), className='text-nowrap'),
            html.Td(m.get('sender', '')), html.Td(m.get('subject', '')), html.Td(files or '-'),
            html.Td([dbc.Badge(ri.STATUS.get(m['status'], m['status']), color=_BADGE.get(m['status'], 'light'),
                               className='me-1'),
                     html.Span(f"{sc} {m.get('period', '')}".strip(), className='me-1'),
                     html.Div(m.get('note', ''), className='text-muted')]),
        ], className='table-warning' if m['status'] == 'review' else None))
    return dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('받은 때', '보낸 사람', '제목', '첨부', '처리')])),
                      html.Tbody(body)], size='sm', bordered=True, className='small mb-0')


def _review_options(scenario: str) -> list:
    return [{'label': f"#{m['id']} {m.get('sender', '')} — {m.get('subject', '')[:60]}", 'value': m['id']}
            for m in ri.list_mails(scenario, limit=200) if m['status'] in ('review', 'no_attachment')]


def _dept_options(scenario: str) -> list:
    from services import work_assign as wa
    return wa.departments() if scenario == 'work_assign' else hom.departments()


def card(p: str, scenario: str):
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-envelope-arrow-down me-1'),
                                  f'받은 회신 메일 — 비실명 계정(POP3) 자동 취합'], className='fw-semibold')),
        dbc.CardBody([
            html.Div('부서 담당자가 회신한 메일을 비실명 계정에서 주기적으로 읽어 첨부를 내려받고, 제목(보낸 메일 제목과 대조)과 보낸 '
                     '사람·파일 이름으로 시나리오·기간·부서를 정해 자동으로 등록합니다. 개인 계정으로 보낸 메일의 회신은 개인 메일함으로 '
                     '가므로, 회신을 받으려면 발신 계정을 팀 공용(비실명) 계정으로 보내세요.', className='small text-muted mb-2'),
            html.Div([html.Div(_status_line(), id=f'{p}-ri-status', className='me-2'),
                      dbc.Button([html.I(className='bi bi-arrow-repeat me-1'), '지금 가져오기'], id=f'{p}-ri-fetch',
                                 color='secondary', outline=True, size='sm', className='py-0')],
                     className='d-flex align-items-center flex-wrap gap-1 mb-2'),
            html.Div(id=f'{p}-ri-msg', className='small mb-2'),
            html.Div(_mail_table(p, scenario), id=f'{p}-ri-table', className='mb-3'),
            html.Div('자동으로 못 정한 메일 직접 지정', className='small fw-semibold mb-1'),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id=f'{p}-ri-mail', options=_review_options(scenario), placeholder='확인 필요 메일'), md=5),
                dbc.Col(dcc.Dropdown(id=f'{p}-ri-period', options=period_options(scenario),
                                     placeholder='대상월' if scenario == 'work_assign' else '발령일'), md=2),
                dbc.Col(dcc.Dropdown(id=f'{p}-ri-dept', options=_dept_options(scenario), placeholder='부서'), md=2),
                dbc.Col([dbc.Button('등록', id=f'{p}-ri-apply', color='primary', size='sm', className='me-1'),
                         dbc.Button('무시', id=f'{p}-ri-ignore', color='secondary', outline=True, size='sm')], md=3),
            ], className='g-2 align-items-center'),
            dcc.Download(id=f'{p}-ri-download'),
        ]),
    ], className='shadow-sm mb-4')


def _clicks(trig: dict) -> int:
    for group in ctx.inputs_list:
        for item in group if isinstance(group, list) else [group]:
            if item.get('id') == trig:
                return item.get('value') or 0
    return 0


def register(p: str, scenario: str, ver_id: str) -> None:
    @callback(Output(f'{p}-ri-msg', 'children'), Output(f'{p}-ri-table', 'children'), Output(f'{p}-ri-status', 'children'),
              Output(f'{p}-ri-mail', 'options'), Output(f'{p}-ri-mail', 'value'), Output(ver_id, 'data', allow_duplicate=True),
              Input(f'{p}-ri-fetch', 'n_clicks'), Input(f'{p}-ri-apply', 'n_clicks'), Input(f'{p}-ri-ignore', 'n_clicks'),
              State(f'{p}-ri-mail', 'value'), State(f'{p}-ri-period', 'value'), State(f'{p}-ri-dept', 'value'),
              State(ver_id, 'data'), prevent_initial_call=True)
    def _act(_f, _a, _i, mail_id, period, dept, ver):
        trig = ctx.triggered_id
        if not hom.can_use():
            return html.Span('권한이 없습니다.', className='text-danger'), no_update, no_update, no_update, no_update, no_update
        try:
            if trig == f'{p}-ri-fetch':
                st = ri.run_once()
                msg = (html.Span('다른 곳에서 가져오는 중입니다 — 잠시 후 다시 누르세요.', className='text-warning') if st.get('busy')
                       else html.Span(f"새 메일 {st.get('new', 0)}통 — 등록 {st.get('registered', 0)}, 확인 필요 "
                                      f"{st.get('review', 0)}", className='text-success') if st.get('ok')
                       else html.Span(f"가져오기 실패: {st.get('error', '')}", className='text-danger'))
            else:
                if not mail_id:
                    raise ValueError('메일을 고르세요.')
                if trig == f'{p}-ri-ignore':
                    ri.ignore(mail_id)
                    msg = html.Span(f'#{mail_id} 메일을 무시했습니다.', className='text-muted')
                else:
                    r = ri.assign(mail_id, scenario, period, dept) or {}
                    msg = html.Span(f"#{mail_id}: {ri.STATUS.get(r.get('status'), '')} — {r.get('note', '')}",
                                    className='text-success' if r.get('status') == 'registered' else 'text-warning')
        except (PermissionError, ValueError) as exc:
            return html.Span(str(exc), className='text-danger'), no_update, no_update, no_update, no_update, no_update
        return msg, _mail_table(p, scenario), _status_line(), _review_options(scenario), None, (ver or 0) + 1

    @callback(Output(f'{p}-ri-download', 'data'), Input({'type': f'{p}-ri-dl', 'm': ALL, 'f': ALL}, 'n_clicks'),
              prevent_initial_call=True)
    def _download(_n):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not _clicks(trig) or not hom.can_use():
            return no_update
        files = ri.mail_files(trig['m'])
        if trig['f'] >= len(files):
            return no_update
        name, content = files[trig['f']]
        return dcc.send_bytes(content, name)
