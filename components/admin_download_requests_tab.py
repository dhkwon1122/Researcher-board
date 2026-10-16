"""
관리자 > 다운로드 요청 탭(2026-10-15) — 엑셀 다운로드 권한이 없는 구성원의 1회성 다운로드 요청을 승인/반려한다
(services/download_access.py). 승인하면 요청자 화면에 결과와 "정보 관리 책임" 안내가 뜨고(메일 설정 시 메일도),
요청자가 안내를 확인하면 유효기간 안에 그 화면에서 1번 다운로드할 수 있다.
"""
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, html, no_update

_STATUS = {'pending': ('대기', 'warning'), 'approved': ('승인', 'success'), 'rejected': ('반려', 'secondary'),
           'used': ('사용 완료', 'info')}


def _rows():
    from services import download_access as da
    items = da.list_requests()   # 최신순
    items.sort(key=lambda r: r['status'] != 'pending')   # 대기 건을 맨 위로(안정 정렬이라 그 안은 최신순 유지)
    if not items:
        return html.Div('요청이 없습니다.', className='text-muted small p-2')
    th = {'fontSize': '0.8rem', 'textAlign': 'center', 'verticalAlign': 'middle', 'whiteSpace': 'nowrap'}
    body = []
    for r in items:
        label, color = _STATUS.get(r['status'], (r['status'], 'light'))
        if r['status'] == 'pending':
            action = html.Div([
                dbc.Input(id={'type': 'dlreq-admin-comment', 'id': r['id']}, size='sm', placeholder='의견(선택)',
                          className='mb-1'),
                dbc.Button('승인', id={'type': 'dlreq-approve', 'id': r['id']}, size='sm', color='success', className='me-1'),
                dbc.Button('반려', id={'type': 'dlreq-reject', 'id': r['id']}, size='sm', color='secondary', outline=True),
            ])
        else:
            extra = [f"{r.get('decided_by', '')} · {r.get('decided_at', '')}"]
            if r.get('admin_comment'):
                extra.append(f"의견: {r['admin_comment']}")
            if r['status'] == 'approved':
                extra.append(f"유효 {r.get('expires_at', '')}까지 · " + ('안내 확인함' if r.get('acknowledged_at') else '요청자 미확인'))
            if r.get('used_at'):
                extra.append(f"다운로드 {r['used_at']}")
            action = html.Div([html.Div(x) for x in extra], className='small text-muted')
        body.append(html.Tr([
            html.Td(r['created_at'], style={'whiteSpace': 'nowrap'}),
            html.Td([html.Div(r.get('display_name') or r['user_id']), html.Div(r['user_id'], className='text-muted')]),
            html.Td(r['feature_label']),
            html.Td(r['target'], style={'whiteSpace': 'pre-line'}),
            html.Td(r['purpose'], style={'whiteSpace': 'pre-line'}),
            html.Td(dbc.Badge(label, color=color, text_color='dark' if color == 'warning' else None), className='text-center'),
            html.Td(action, style={'minWidth': '190px'}),
        ]))
    return dbc.Table([
        html.Thead(html.Tr([html.Th(h, style=th) for h in ('요청일', '요청자', '화면', '대상', '사용목적', '상태', '처리')])),
        html.Tbody(body),
    ], bordered=True, hover=True, size='sm', style={'fontSize': '0.8rem'}, className='align-middle')


def _download_requests_tab():
    from services import download_access as da
    return html.Div([
        html.Div([
            html.Span('엑셀 다운로드 요청', className='fw-semibold me-2'),
            dbc.Button([html.I(className='bi bi-arrow-clockwise me-1'), '새로고침'], id='dlreq-admin-refresh',
                       size='sm', color='secondary', outline=True),
        ], className='d-flex align-items-center mb-2'),
        html.Ul([
            html.Li('엑셀 다운로드 권한은 "사용자/권한 관리" 표의 "엑셀" 열에서 계정별로 켜고 끕니다(역할 기본값은 허용).'),
            html.Li(f'권한이 없는 구성원이 화면에서 보낸 1회성 요청입니다. 승인하면 요청자가 "정보 관리 책임" 안내를 확인한 뒤 '
                    f'{da.GRANT_DAYS}일 안에 그 화면에서 1번 다운로드할 수 있습니다.'),
            html.Li('승인 안내: ' + da.RESPONSIBILITY_NOTICE),
        ], className='small text-muted mb-2'),
        html.Div(id='dlreq-admin-msg'),
        html.Div(_rows(), id='dlreq-admin-table'),
    ])


@callback(Output('dlreq-admin-table', 'children'), Output('dlreq-admin-msg', 'children'),
          Input('dlreq-admin-refresh', 'n_clicks'),
          Input({'type': 'dlreq-approve', 'id': ALL}, 'n_clicks'),
          Input({'type': 'dlreq-reject', 'id': ALL}, 'n_clicks'),
          State({'type': 'dlreq-admin-comment', 'id': ALL}, 'value'),
          State({'type': 'dlreq-admin-comment', 'id': ALL}, 'id'),
          prevent_initial_call=True)
def _decide(_refresh, _approves, _rejects, comments, comment_ids):
    from services import download_access as da
    trig = ctx.triggered[0] if ctx.triggered else {}
    tid = ctx.triggered_id
    if isinstance(tid, dict):
        if not trig.get('value'):
            return no_update, no_update
        comment = next((c for c, i in zip(comments, comment_ids) if i['id'] == tid['id']), '') or ''
        try:
            r = da.decide(tid['id'], tid['type'] == 'dlreq-approve', comment)
        except (ValueError, PermissionError) as exc:
            return _rows(), dbc.Alert(str(exc), color='warning', dismissable=True, className='py-2 small')
        word = '승인' if r['status'] == 'approved' else '반려'
        return _rows(), dbc.Alert(f"{r.get('display_name') or r['user_id']}님의 요청을 {word}했습니다 — 요청자 화면에 알림이 표시됩니다"
                                  + ('(메일 주소가 있으면 메일도 발송).' if r.get('email') else '.'),
                                  color='success', dismissable=True, duration=5000, className='py-2 small')
    return _rows(), None
