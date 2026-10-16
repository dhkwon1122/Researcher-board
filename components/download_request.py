"""
엑셀 다운로드 요청 UI(2026-10-15) — services/download_access.py.

  - request_ui(feature): 다운로드 버튼 옆에 두는 "다운로드 요청" 버튼 + 요청 모달(대상·사용목적).
    엑셀 다운로드 권한이 있는 사용자에게는 아무것도 그리지 않는다.
  - notice_modal(): app.layout에 한 번 두는 전역 알림 — 관리자가 요청을 승인/반려하면 다음 화면 이동 때 결과와
    "정보 관리 책임" 안내를 띄우고, 승인 건은 안내를 확인(체크)해야 1회 다운로드에 쓸 수 있다.
"""
import dash_bootstrap_components as dbc
from dash import MATCH, Input, Output, State, callback, html, no_update


def request_ui(feature: str, default_target: str = ''):
    from services import download_access as da
    if da.has_permission():
        return html.Span()
    from services.auth import get_current_user
    mine = [r for r in da.my_requests((get_current_user() or {}).get('user_id', '')) if r['feature'] == feature]
    latest = mine[0] if mine else None
    status = ''
    if latest:
        status = {'pending': '요청 승인 대기 중', 'approved': '승인됨 — 알림 확인 후 1회 다운로드 가능',
                  'rejected': '최근 요청 반려', 'used': '승인 건 사용 완료'}.get(latest['status'], '')
        if latest['status'] == 'approved' and latest.get('acknowledged_at'):
            status = f"승인됨 — {latest.get('expires_at', '')}까지 1회 다운로드 가능"
    return html.Span([
        dbc.Button([html.I(className='bi bi-envelope-paper me-1'), '다운로드 요청'],
                   id={'type': 'dlreq-open', 'f': feature}, size='sm', color='warning', outline=True,
                   className='ms-2', title='엑셀 다운로드 권한이 없어 관리자에게 1회성 다운로드를 요청합니다'),
        html.Small(status, className='text-muted ms-2'),
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(f'엑셀 다운로드 요청 — {da.FEATURES.get(feature, feature)}')),
            dbc.ModalBody([
                html.Div('엑셀 다운로드 권한이 없습니다. 관리자가 승인하면 이 화면에서 1회 다운로드할 수 있습니다.',
                         className='small text-muted mb-2'),
                dbc.Label('대상', className='small fw-semibold'),
                dbc.Textarea(id={'type': 'dlreq-target', 'f': feature}, value=default_target,
                             placeholder='예: AI플랫폼 로봇비전 과제원 6명 / 연구원 명단 검색 결과 32명', rows=2),
                dbc.Label('사용목적', className='small fw-semibold mt-2'),
                dbc.Textarea(id={'type': 'dlreq-purpose', 'f': feature},
                             placeholder='예: 하반기 과제 인력 재배치 검토 회의 자료', rows=3),
                html.Div(id={'type': 'dlreq-result', 'f': feature}, className='mt-2'),
            ]),
            dbc.ModalFooter(dbc.Button('요청 보내기', id={'type': 'dlreq-submit', 'f': feature}, color='primary')),
        ], id={'type': 'dlreq-modal', 'f': feature}, is_open=False),
    ])


@callback(Output({'type': 'dlreq-modal', 'f': MATCH}, 'is_open'),
          Input({'type': 'dlreq-open', 'f': MATCH}, 'n_clicks'), prevent_initial_call=True)
def _open(n):
    return bool(n) or no_update


@callback(Output({'type': 'dlreq-result', 'f': MATCH}, 'children'),
          Input({'type': 'dlreq-submit', 'f': MATCH}, 'n_clicks'),
          State({'type': 'dlreq-target', 'f': MATCH}, 'value'),
          State({'type': 'dlreq-purpose', 'f': MATCH}, 'value'),
          State({'type': 'dlreq-submit', 'f': MATCH}, 'id'),
          prevent_initial_call=True)
def _submit(n, target, purpose, btn_id):
    if not n:
        return no_update
    from services import download_access as da
    try:
        da.create_request(btn_id['f'], target, purpose)
    except (ValueError, PermissionError) as exc:
        return dbc.Alert(str(exc), color='warning', className='mb-0 py-2 small')
    return dbc.Alert('요청을 보냈습니다. 관리자가 처리하면 화면 알림(메일 설정 시 메일도)으로 결과를 알려드립니다.',
                     color='success', className='mb-0 py-2 small')


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
            html.Div(f"대상: {r['target']}", className='small mt-1'),
            html.Div(f"사용목적: {r['purpose']}", className='small'),
            html.Div(f"관리자 의견: {r['admin_comment']}", className='small') if r.get('admin_comment') else None,
            html.Div(f"{r['expires_at']}까지 해당 화면에서 1회 다운로드할 수 있습니다.", className='small fw-semibold')
            if ok else None,
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
