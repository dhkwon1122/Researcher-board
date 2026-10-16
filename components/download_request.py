"""
엑셀 다운로드 요청 UI(2026-10-15, 2026-10-16 개정) — services/download_access.py.

  - request_ui(feature): 다운로드 버튼 옆에 두는 "다운로드 요청" 버튼 + 요청 모달.
    모달에는 요청에 함께 갈 구성(대상자 명단 + 헤더)을 보여 준다 — 조서 작성은 화면에서 구성한 열,
    JOB Market·보유 전문성은 그 엑셀의 헤더 중 고른 것. 대상 설명(선택)·사용목적(필수)을 적어 보낸다.
    화면 상태(대상자·열)는 각 페이지가 {'type': 'dlreq-ctx', 'f': feature} Store에 채운다.
    연구원 명단은 열이 고정이라 "조서 작성에서 요청" 버튼(표의 대상자를 조서 작성으로 넘김)만 둔다.
    엑셀 다운로드 권한이 있으면 Store만 그리고 버튼은 그리지 않는다.
  - spec_view(req): 요청의 헤더·대상자 구성 표시(요청 모달·관리자 탭·승인 알림 공용).
  - notice_modal(): app.layout에 한 번 두는 전역 알림 — 관리자가 요청을 승인/반려하면 다음 화면 이동 때 결과와
    "정보 관리 책임" 안내를 띄우고, 승인 건은 안내를 확인(체크)해야 1회 다운로드에 쓸 수 있다.
"""
import dash_bootstrap_components as dbc
from dash import MATCH, Input, Output, State, callback, dcc, html, no_update


def _ctx_store(feature):
    return dcc.Store(id={'type': 'dlreq-ctx', 'f': feature}, data=None)


def request_ui(feature: str, default_target: str = ''):
    from services import download_access as da
    if da.has_permission():
        return html.Span(_ctx_store(feature))
    if feature not in da.REQUESTABLE:      # 연구원 명단 → 조서 작성에서 요청
        return html.Span([
            _ctx_store(feature),
            dbc.Button([html.I(className='bi bi-envelope-paper me-1'), '조서 작성에서 요청'], id='dlreq-to-rb',
                       size='sm', color='warning', outline=True, className='ms-2',
                       title='엑셀 다운로드 권한이 없습니다 — 표에 보이는 대상자를 조서 작성으로 넘겨, 필요한 헤더를 구성한 뒤 '
                             '관리자에게 1회성 다운로드를 요청합니다(조서 작성 "기본 양식" = 연구원 명단 엑셀).'),
            dcc.Location(id='dlreq-redirect', refresh=True),
        ])
    from services.auth import get_current_user
    mine = [r for r in da.my_requests((get_current_user() or {}).get('user_id', '')) if r['feature'] == feature]
    latest = mine[0] if mine else None
    status = ''
    if latest:
        status = {'pending': '요청 승인 대기 중', 'approved': '승인됨 — 알림 확인 후 1회 다운로드 가능',
                  'rejected': '최근 요청 반려', 'used': '승인 건 사용 완료'}.get(latest['status'], '')
        if latest['status'] == 'approved' and latest.get('acknowledged_at'):
            status = f"승인됨 — {latest.get('expires_at', '')}까지 승인된 구성으로 1회 다운로드 가능"
    fixed = da.fixed_headers(feature)
    guide = ('조서 양식(2. 양식)에서 구성한 열과 1. 대상자에서 고른 사람이 그대로 요청에 붙습니다. '
             '승인되면 승인된 열·대상자로만 내려받습니다(요청 뒤 화면을 바꿔도 승인된 구성 기준).'
             if feature == 'report_builder' else
             '받을 헤더를 고르세요. 화면에서 고른 대상자 명단이 그대로 요청에 붙고, 승인되면 승인된 헤더·대상자로만 내려받습니다.')
    return html.Span([
        _ctx_store(feature),
        dbc.Button([html.I(className='bi bi-envelope-paper me-1'), '다운로드 요청'],
                   id={'type': 'dlreq-open', 'f': feature}, size='sm', color='warning', outline=True,
                   className='ms-2', title='엑셀 다운로드 권한이 없어 관리자에게 1회성 다운로드를 요청합니다'),
        html.Small(status, className='text-muted ms-2'),
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(f'엑셀 다운로드 요청 — {da.FEATURES.get(feature, feature)}')),
            dbc.ModalBody([
                html.Div('엑셀 다운로드 권한이 없습니다. ' + guide, className='small text-muted mb-2'),
                html.Div([
                    dbc.Label('받을 헤더', className='small fw-semibold'),
                    dbc.Checklist(id={'type': 'dlreq-headers', 'f': feature},
                                  options=[{'label': h, 'value': h} for h in fixed], value=list(fixed),
                                  className='small mb-2'),
                ], style={} if fixed else {'display': 'none'}),
                html.Div(id={'type': 'dlreq-summary', 'f': feature}, className='mb-2'),
                dbc.Label('대상 설명(선택)', className='small fw-semibold'),
                dbc.Textarea(id={'type': 'dlreq-target', 'f': feature}, value=default_target,
                             placeholder='예: AI플랫폼 로봇비전 과제원 — 대상자 명단은 자동으로 첨부됩니다', rows=2),
                dbc.Label('사용목적', className='small fw-semibold mt-2'),
                dbc.Textarea(id={'type': 'dlreq-purpose', 'f': feature},
                             placeholder='예: 하반기 과제 인력 재배치 검토 회의 자료', rows=3),
                html.Div(id={'type': 'dlreq-result', 'f': feature}, className='mt-2'),
            ]),
            dbc.ModalFooter(dbc.Button('요청 보내기', id={'type': 'dlreq-submit', 'f': feature}, color='primary')),
        ], id={'type': 'dlreq-modal', 'f': feature}, is_open=False, size='lg'),
    ])


def _names(ids: list) -> list:
    from services.data_store import read_processed
    df = read_processed('researchers')
    m = {}
    if not df.empty:
        d = df.drop_duplicates('researcher_id', keep='last').set_index('researcher_id')
        for rid in ids:
            if rid in d.index:
                m[rid] = f"{d.at[rid, 'name']}({d.at[rid, 'department'] or '-'})"
    return [m.get(rid, rid) for rid in ids]


def spec_view(feature: str, spec: dict, headers: list | None = None, show_people: bool = True):
    """요청 구성 — 헤더(조서 작성은 열별 항목·묶는 방식까지)와 대상자."""
    from services import report_builder as rb
    spec = spec or {}
    ids = spec.get('ids') or []
    parts = []
    if feature == 'report_builder' and spec.get('columns'):
        rows = [html.Tr([html.Td(i + 1, className='text-muted'), html.Td(c['header'], className='fw-semibold'),
                         html.Td(' + '.join(rb.FIELDS[f]['label'] if f in rb.FIELDS else f for f in c['fields'])),
                         html.Td(rb.JOINS.get(c.get('join'), '').split(':')[0] if len(c['fields']) > 1 else '')])
                for i, c in enumerate(spec['columns'])]
        parts.append(dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('#', '헤더', '항목', '묶는 방식')])),
                                html.Tbody(rows)], size='sm', bordered=True, className='mb-1',
                               style={'fontSize': '0.75rem'}))
        if spec.get('max_items'):
            parts.append(html.Div(f"여러 건 항목 최대 {spec['max_items']}건", className='small text-muted'))
    elif headers:
        parts.append(html.Div([html.Span('헤더: ', className='fw-semibold'),
                               ' · '.join(headers)], className='small'))
    people = html.Details([html.Summary(f'대상자 {len(ids)}명', className='small fw-semibold'),
                           html.Div(', '.join(_names(ids)), className='small text-muted',
                                    style={'maxHeight': '140px', 'overflowY': 'auto'})]) if ids and show_people else \
        html.Div(f'대상자 {len(ids)}명', className='small fw-semibold')
    parts.append(people)
    return html.Div(parts)


@callback(Output({'type': 'dlreq-modal', 'f': MATCH}, 'is_open'),
          Input({'type': 'dlreq-open', 'f': MATCH}, 'n_clicks'), prevent_initial_call=True)
def _open(n):
    return bool(n) or no_update


@callback(Output({'type': 'dlreq-summary', 'f': MATCH}, 'children'),
          Input({'type': 'dlreq-modal', 'f': MATCH}, 'is_open'),
          Input({'type': 'dlreq-ctx', 'f': MATCH}, 'data'),
          State({'type': 'dlreq-modal', 'f': MATCH}, 'id'), prevent_initial_call=True)
def _summary(is_open, context, modal_id):
    if not is_open:
        return no_update
    context = context or {}
    feature = modal_id['f']
    if not context.get('ids'):
        return dbc.Alert('화면에서 대상자를 먼저 고르세요 — 요청에 대상자 명단이 함께 갑니다.', color='warning',
                         className='py-2 small mb-0')
    if feature == 'report_builder':
        from services import report_builder as rb
        spec = {'ids': context['ids'], 'columns': rb.clean_columns(context.get('columns') or []),
                'max_items': context.get('max_items')}
        if not spec['columns']:
            return dbc.Alert('조서 양식에 항목이 들어 있는 열이 없습니다.', color='warning', className='py-2 small mb-0')
        return html.Div([html.Div('요청에 붙는 구성', className='small fw-semibold mb-1'), spec_view(feature, spec)])
    return spec_view(feature, {'ids': context['ids']})


@callback(Output({'type': 'dlreq-result', 'f': MATCH}, 'children'),
          Input({'type': 'dlreq-submit', 'f': MATCH}, 'n_clicks'),
          State({'type': 'dlreq-target', 'f': MATCH}, 'value'),
          State({'type': 'dlreq-purpose', 'f': MATCH}, 'value'),
          State({'type': 'dlreq-ctx', 'f': MATCH}, 'data'),
          State({'type': 'dlreq-headers', 'f': MATCH}, 'value'),
          State({'type': 'dlreq-submit', 'f': MATCH}, 'id'),
          prevent_initial_call=True)
def _submit(n, target, purpose, context, headers, btn_id):
    if not n:
        return no_update
    from services import download_access as da
    try:
        req = da.create_request(btn_id['f'], target, purpose, context, headers)
    except (ValueError, PermissionError) as exc:
        return dbc.Alert(str(exc), color='warning', className='mb-0 py-2 small')
    return dbc.Alert(f"요청을 보냈습니다(대상 {req['target_count']}명, 헤더 {len(req['headers'])}개). 관리자가 처리하면 "
                     '화면 알림(메일 설정 시 메일도)으로 결과를 알려드립니다.', color='success', className='mb-0 py-2 small')


# ─── 전역 승인 알림 ──────────────────────────────────────────────────────────

def notice_modal():
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle([html.I(className='bi bi-bell me-2'), '엑셀 다운로드 요청 결과'])),
        dbc.ModalBody(id='dlreq-notice-body'),
        dbc.ModalFooter([
            dbc.Checkbox(id='dlreq-notice-agree', value=False, label='위 정보 관리 책임 안내를 확인했습니다',
                         className='me-auto small'),
            dbc.Button('확인', id='dlreq-notice-ok', color='primary', disabled=True),
        ]),
    ], id='dlreq-notice-modal', is_open=False, backdrop='static', keyboard=False, size='lg')


@callback(Output('dlreq-notice-modal', 'is_open'), Output('dlreq-notice-body', 'children'),
          Output('dlreq-notice-agree', 'value'),
          Input('_pages_location', 'pathname'))
def _show_notices(_path):
    from services import download_access as da
    from services.auth import get_current_user
    user = get_current_user()
    if not user:
        return False, no_update, no_update
    items = da.notices(user['user_id'])
    if not items:
        return False, no_update, no_update
    rows = []
    for r in items:
        ok = r['status'] == 'approved'
        rows.append(dbc.Alert([
            html.Div([dbc.Badge('승인' if ok else '반려', color='success' if ok else 'secondary', className='me-2'),
                      html.B(r['feature_label']), html.Span(f" · 요청 {r['created_at']}", className='text-muted small')]),
            html.Div(f"대상: {r['target']}", className='small mt-1') if r.get('target') else None,
            html.Div(f"사용목적: {r['purpose']}", className='small'),
            html.Div(spec_view(r['feature'], r.get('spec'), r.get('headers'), show_people=False), className='mt-1'),
            html.Div(f"관리자 의견: {r['admin_comment']}", className='small') if r.get('admin_comment') else None,
            html.Div(f"{r['expires_at']}까지 해당 화면에서 승인된 구성으로 1회 다운로드할 수 있습니다.",
                     className='small fw-semibold') if ok else None,
        ], color='light', className='border mb-2'))
    has_approved = any(r['status'] == 'approved' for r in items)
    notice = dbc.Alert([html.I(className='bi bi-exclamation-triangle-fill me-2'), html.B(da.RESPONSIBILITY_NOTICE)],
                       color='danger', className='mb-0') if has_approved else None
    return True, [*rows, notice], False


@callback(Output('dlreq-notice-ok', 'disabled'), Input('dlreq-notice-agree', 'value'))
def _agree(v):
    return not v


@callback(Output('dlreq-notice-modal', 'is_open', allow_duplicate=True),
          Input('dlreq-notice-ok', 'n_clicks'), prevent_initial_call=True)
def _ack(n):
    if not n:
        return no_update
    from services import download_access as da
    from services.auth import get_current_user
    user = get_current_user() or {}
    ids = [r['id'] for r in da.notices(user.get('user_id', ''))]
    da.acknowledge(ids, user.get('user_id', ''))
    return False
