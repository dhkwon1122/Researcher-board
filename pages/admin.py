"""
관리자 페이지: 사용자 계정 관리 (추가 / 수정 / 삭제)
manage_users 권한이 있는 계정만 접근 가능.
"""
import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, dcc, html, no_update

from config.auth_config import ROLE_LABELS

dash.register_page(__name__, path='/admin', name='관리자', title='사용자 관리')

_ROLES = [{'label': v, 'value': k} for k, v in ROLE_LABELS.items()]

# ── 공통 UI 조각 ─────────────────────────────────────────────────────────────

def _access_denied():
    return dbc.Container(
        dbc.Alert(
            [html.I(className='bi bi-shield-lock me-2'), '접근 권한이 없습니다.'],
            color='danger', className='mt-4',
        ),
        className='py-4',
    )


def _user_row(user: dict, idx: int):
    status = (
        dbc.Badge('임시 비밀번호', color='warning', text_color='dark', className='fw-normal')
        if user.get('must_change_password')
        else dbc.Badge('정상', color='light', text_color='secondary', className='fw-normal border')
    )
    name_cell = [user['display_name']]
    if user.get('is_admin'):
        name_cell.append(dbc.Badge(
            [html.I(className='bi bi-shield-lock-fill me-1'), '관리자'],
            color='primary', className='fw-normal ms-2',
        ))
    return html.Tr([
        html.Td(user['user_id'], className='align-middle font-monospace small'),
        html.Td(name_cell, className='align-middle'),
        html.Td(ROLE_LABELS.get(user['role'], user['role']), className='align-middle small'),
        html.Td(user.get('email', ''), className='align-middle small text-muted'),
        html.Td(status, className='align-middle'),
        html.Td(
            dbc.ButtonGroup([
                dbc.Button(
                    [html.I(className='bi bi-pencil me-1'), '수정'],
                    id={'type': 'btn-edit', 'index': idx},
                    color='outline-primary', size='sm',
                ),
                dbc.Button(
                    [html.I(className='bi bi-trash me-1'), '삭제'],
                    id={'type': 'btn-delete', 'index': idx},
                    color='outline-danger', size='sm',
                ),
            ]),
            className='align-middle',
        ),
    ])


def _user_modal():
    """추가 / 수정 겸용 모달."""
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id='user-modal-title')),
        dbc.ModalBody([
            dcc.Store(id='editing-user-id', data=None),
            dbc.Row([
                dbc.Col([
                    dbc.Label('아이디 *', html_for='modal-user-id', size='sm'),
                    dbc.Input(id='modal-user-id', placeholder='예: hong.gildong',
                              autocomplete='off', size='sm'),
                ], md=6),
                dbc.Col([
                    dbc.Label('이름 *', html_for='modal-display-name', size='sm'),
                    dbc.Input(id='modal-display-name', placeholder='예: 홍길동',
                              autocomplete='off', size='sm'),
                ], md=6),
            ], className='mb-2'),
            dbc.Row([
                dbc.Col([
                    dbc.Label('역할 *', html_for='modal-role', size='sm'),
                    dbc.Select(id='modal-role', options=_ROLES, size='sm'),
                ], md=6),
                dbc.Col([
                    dbc.Label('이메일', html_for='modal-email', size='sm'),
                    dbc.Input(id='modal-email', type='email',
                              placeholder='예: hong@company.com',
                              autocomplete='off', size='sm'),
                ], md=6),
            ], className='mb-2'),
            dbc.Checklist(
                id='modal-is-admin',
                options=[{'label': ' 관리자 권한 부여 (사용자 관리 페이지 접근 — 역할과 무관하게 이 계정에만 적용)',
                          'value': 'admin'}],
                value=[], switch=True, className='mb-2 small',
            ),
            html.Hr(className='my-2'),
            dbc.Row([
                dbc.Col([
                    dbc.Label(id='modal-pw-label', size='sm'),
                    dbc.Input(id='modal-password', type='password',
                              autocomplete='new-password', size='sm'),
                ], md=6),
                dbc.Col([
                    dbc.Label('비밀번호 확인', html_for='modal-password-confirm', size='sm'),
                    dbc.Input(id='modal-password-confirm', type='password',
                              autocomplete='new-password', size='sm'),
                ], md=6),
            ], className='mb-2'),
            html.Div(id='user-modal-alert'),
        ]),
        dbc.ModalFooter([
            dbc.Button('취소', id='btn-modal-cancel', color='secondary', size='sm'),
            dbc.Button('저장', id='btn-modal-save', color='primary', size='sm'),
        ]),
    ], id='user-modal', is_open=False, backdrop='static')


def _mail_report_card():
    """"과제 전문성 분석" 리포트는 앱 화면이 아니라 앱 밖(다른 부서 등)으로
    공유해야 할 때가 있는데, data/processed에 완성된 HTML 파일로 남기지
    않고(서버 파일시스템에 접근 가능한 누구나 열어볼 수 있는 사본이 되므로)
    그때그때 다시 만들어 메일로만 보낸다(pipeline/process_project_expertise.py의
    email_report(), pipeline/mailer.py). 사용자 관리와 마찬가지로 관리자만
    접근 가능."""
    return dbc.Card([
        dbc.CardHeader(
            html.Span([html.I(className='bi bi-envelope me-2'), '과제 전문성 분석 리포트 메일 발송']),
        ),
        dbc.CardBody([
            html.P(
                '이 리포트는 화면에 저장되지 않습니다 — 발송할 때마다 최신 분석 결과로 '
                '새로 만들어 메일로만 보냅니다.',
                className='small text-muted mb-2',
            ),
            dbc.Row([
                dbc.Col(
                    dbc.Input(
                        id='mail-report-recipients', size='sm',
                        placeholder='수신자 이메일(콤마로 구분, 예: a@samsung.com,b@samsung.com)',
                    ),
                    md=9,
                ),
                dbc.Col(
                    dbc.Button(
                        [html.I(className='bi bi-send me-1'), '발송'],
                        id='btn-mail-report', color='primary', size='sm', className='w-100',
                    ),
                    md=3,
                ),
            ], className='g-2'),
            html.Div(id='mail-report-alert', className='mt-2'),
        ]),
    ], className='shadow-sm mt-3')


def _delete_modal():
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle('사용자 삭제')),
        dbc.ModalBody([
            dcc.Store(id='deleting-user-id', data=None),
            html.P(id='delete-confirm-msg', className='mb-0'),
        ]),
        dbc.ModalFooter([
            dbc.Button('취소', id='btn-delete-cancel', color='secondary', size='sm'),
            dbc.Button('삭제', id='btn-delete-confirm', color='danger', size='sm'),
        ]),
    ], id='delete-modal', is_open=False)


# ── 레이아웃 ──────────────────────────────────────────────────────────────────

def layout():
    from services.auth import can, list_users
    if not can('manage_users'):
        return _access_denied()

    users = list_users()

    rows = [_user_row(u, i) for i, u in enumerate(users)]

    table = dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th('아이디'),
                html.Th('이름'),
                html.Th('역할'),
                html.Th('이메일'),
                html.Th('상태'),
                html.Th(''),
            ])),
            html.Tbody(rows, id='user-table-body'),
        ],
        bordered=True, hover=True, responsive=True, size='sm', className='mb-0',
    )

    return dbc.Container([
        dcc.Store(id='user-refresh-counter', data=0),
        dcc.Store(id='user-list-store', data=users),

        dbc.Row(
            dbc.Col([
                html.H5(
                    [html.I(className='bi bi-people me-2'), '사용자 관리'],
                    className='mb-0',
                ),
            ]),
            className='mb-3 align-items-center',
        ),

        dbc.Card([
            dbc.CardHeader(
                dbc.Row([
                    dbc.Col(
                        html.Span(f'총 {len(users)}명', className='small text-muted'),
                        className='d-flex align-items-center',
                    ),
                    dbc.Col(
                        dbc.Button(
                            [html.I(className='bi bi-person-plus me-1'), '사용자 추가'],
                            id='btn-add-user', color='primary', size='sm',
                        ),
                        className='text-end',
                    ),
                ], align='center'),
            ),
            dbc.CardBody(table, className='p-0'),
        ], className='shadow-sm'),

        html.Div(id='admin-page-alert', className='mt-3'),

        _mail_report_card(),

        _user_modal(),
        _delete_modal(),
    ], className='py-4')


# ── 콜백: 사용자 목록 갱신 ────────────────────────────────────────────────────

@callback(
    Output('user-table-body', 'children'),
    Output('user-list-store', 'data'),
    Input('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def refresh_user_table(_counter):
    from services.auth import list_users
    users = list_users()
    rows = [_user_row(u, i) for i, u in enumerate(users)]
    return rows, users


# ── 콜백: 추가 버튼 → 모달 열기 ───────────────────────────────────────────────

@callback(
    Output('user-modal', 'is_open', allow_duplicate=True),
    Output('user-modal-title', 'children', allow_duplicate=True),
    Output('editing-user-id', 'data', allow_duplicate=True),
    Output('modal-user-id', 'value', allow_duplicate=True),
    Output('modal-user-id', 'disabled', allow_duplicate=True),
    Output('modal-display-name', 'value', allow_duplicate=True),
    Output('modal-role', 'value', allow_duplicate=True),
    Output('modal-email', 'value', allow_duplicate=True),
    Output('modal-password', 'value', allow_duplicate=True),
    Output('modal-password-confirm', 'value', allow_duplicate=True),
    Output('modal-pw-label', 'children', allow_duplicate=True),
    Output('modal-is-admin', 'value', allow_duplicate=True),
    Output('user-modal-alert', 'children', allow_duplicate=True),
    Input('btn-add-user', 'n_clicks'),
    prevent_initial_call=True,
)
def open_add_modal(_):
    return (
        True, '사용자 추가', None,
        '', False,          # user_id, disabled
        '',                 # display_name
        _ROLES[0]['value'], # role default
        '',                 # email
        '', '',             # passwords
        '비밀번호 * (8자 이상)',
        [],                 # is_admin: 기본 미부여
        [],
    )


# ── 콜백: 수정 버튼 → 모달 열기 ───────────────────────────────────────────────

@callback(
    Output('user-modal', 'is_open', allow_duplicate=True),
    Output('user-modal-title', 'children', allow_duplicate=True),
    Output('editing-user-id', 'data', allow_duplicate=True),
    Output('modal-user-id', 'value', allow_duplicate=True),
    Output('modal-user-id', 'disabled', allow_duplicate=True),
    Output('modal-display-name', 'value', allow_duplicate=True),
    Output('modal-role', 'value', allow_duplicate=True),
    Output('modal-email', 'value', allow_duplicate=True),
    Output('modal-password', 'value', allow_duplicate=True),
    Output('modal-password-confirm', 'value', allow_duplicate=True),
    Output('modal-pw-label', 'children', allow_duplicate=True),
    Output('modal-is-admin', 'value', allow_duplicate=True),
    Output('user-modal-alert', 'children', allow_duplicate=True),
    Input({'type': 'btn-edit', 'index': ALL}, 'n_clicks'),
    State('user-list-store', 'data'),
    prevent_initial_call=True,
)
def open_edit_modal(n_clicks_list, users):
    from dash import ctx
    if not any(n for n in n_clicks_list if n):
        return [no_update] * 13
    triggered = ctx.triggered_id
    if triggered is None:
        return [no_update] * 13
    idx = triggered['index']
    if idx >= len(users):
        return [no_update] * 13
    u = users[idx]
    return (
        True, '사용자 수정', u['user_id'],
        u['user_id'], True,              # user_id readonly
        u.get('display_name', ''),
        u.get('role', _ROLES[0]['value']),
        u.get('email', ''),
        '', '',
        '새 비밀번호 (변경 시에만 입력)',
        ['admin'] if u.get('is_admin') else [],
        [],
    )


# ── 콜백: 모달 저장 ───────────────────────────────────────────────────────────

@callback(
    Output('user-modal-alert', 'children', allow_duplicate=True),
    Output('user-modal', 'is_open', allow_duplicate=True),
    Output('user-refresh-counter', 'data', allow_duplicate=True),
    Input('btn-modal-save', 'n_clicks'),
    State('editing-user-id', 'data'),
    State('modal-user-id', 'value'),
    State('modal-display-name', 'value'),
    State('modal-role', 'value'),
    State('modal-email', 'value'),
    State('modal-password', 'value'),
    State('modal-password-confirm', 'value'),
    State('modal-is-admin', 'value'),
    State('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def save_user(_, editing_id, user_id, display_name, role, email, password, pw_confirm,
              is_admin_value, counter):
    from services.auth import can, change_password, create_user, get_current_user, update_user
    if not can('manage_users'):
        return _alert('권한이 없습니다.', 'danger'), no_update, no_update

    user_id = (user_id or '').strip()
    display_name = (display_name or '').strip()
    email = (email or '').strip()
    password = password or ''
    pw_confirm = pw_confirm or ''
    is_admin = 'admin' in (is_admin_value or [])

    if not display_name or not role:
        return _alert('이름과 역할은 필수입니다.', 'warning'), no_update, no_update

    is_new = editing_id is None

    if is_new:
        if not user_id:
            return _alert('아이디는 필수입니다.', 'warning'), no_update, no_update
        if not password:
            return _alert('비밀번호는 필수입니다.', 'warning'), no_update, no_update
        if len(password) < 8:
            return _alert('비밀번호는 8자 이상이어야 합니다.', 'warning'), no_update, no_update
        if password != pw_confirm:
            return _alert('비밀번호가 일치하지 않습니다.', 'warning'), no_update, no_update
        try:
            create_user(user_id, password, display_name, role, email, is_admin=is_admin)
        except ValueError as exc:
            return _alert(str(exc), 'danger'), no_update, no_update
    else:
        current = get_current_user()
        if current and current['user_id'] == editing_id and not is_admin:
            return _alert('자기 자신의 관리자 권한은 해제할 수 없습니다. '
                          '다른 관리자가 대신 해제해야 합니다.', 'warning'), no_update, no_update
        if password:
            if len(password) < 8:
                return _alert('비밀번호는 8자 이상이어야 합니다.', 'warning'), no_update, no_update
            if password != pw_confirm:
                return _alert('비밀번호가 일치하지 않습니다.', 'warning'), no_update, no_update
            change_password(editing_id, password)
        update_user(editing_id, display_name=display_name, role=role, email=email, is_admin=is_admin)

    return [], False, (counter or 0) + 1


# ── 콜백: 모달 취소 ───────────────────────────────────────────────────────────

@callback(
    Output('user-modal', 'is_open', allow_duplicate=True),
    Input('btn-modal-cancel', 'n_clicks'),
    prevent_initial_call=True,
)
def cancel_modal(_):
    return False


# ── 콜백: 삭제 버튼 → 확인 모달 ──────────────────────────────────────────────

@callback(
    Output('delete-modal', 'is_open', allow_duplicate=True),
    Output('deleting-user-id', 'data'),
    Output('delete-confirm-msg', 'children'),
    Input({'type': 'btn-delete', 'index': ALL}, 'n_clicks'),
    State('user-list-store', 'data'),
    prevent_initial_call=True,
)
def open_delete_modal(n_clicks_list, users):
    from dash import ctx
    if not any(n for n in n_clicks_list if n):
        return no_update, no_update, no_update
    triggered = ctx.triggered_id
    if triggered is None:
        return no_update, no_update, no_update
    idx = triggered['index']
    if idx >= len(users):
        return no_update, no_update, no_update
    u = users[idx]
    msg = [
        f"'{u['display_name']} ({u['user_id']})' 계정을 삭제하시겠습니까?",
        html.Br(),
        html.Small('이 작업은 되돌릴 수 없습니다.', className='text-danger'),
    ]
    return True, u['user_id'], msg


# ── 콜백: 삭제 확인 ───────────────────────────────────────────────────────────

@callback(
    Output('delete-modal', 'is_open', allow_duplicate=True),
    Output('user-refresh-counter', 'data', allow_duplicate=True),
    Output('admin-page-alert', 'children'),
    Input('btn-delete-confirm', 'n_clicks'),
    State('deleting-user-id', 'data'),
    State('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def confirm_delete(_, user_id, counter):
    from services.auth import can, delete_user, get_current_user
    if not can('manage_users'):
        return False, no_update, _alert('권한이 없습니다.', 'danger')
    current = get_current_user()
    if current and current['user_id'] == user_id:
        return False, no_update, _alert('자기 자신은 삭제할 수 없습니다.', 'warning')
    delete_user(user_id)
    return False, (counter or 0) + 1, _alert(f'{user_id} 계정이 삭제되었습니다.', 'success')


# ── 콜백: 삭제 취소 ───────────────────────────────────────────────────────────

@callback(
    Output('delete-modal', 'is_open', allow_duplicate=True),
    Input('btn-delete-cancel', 'n_clicks'),
    prevent_initial_call=True,
)
def cancel_delete(_):
    return False


# ── 콜백: 과제 전문성 분석 리포트 메일 발송 ──────────────────────────────────

@callback(
    Output('mail-report-alert', 'children'),
    Input('btn-mail-report', 'n_clicks'),
    State('mail-report-recipients', 'value'),
    prevent_initial_call=True,
)
def send_mail_report(_, recipients_raw):
    from services.auth import can
    if not can('manage_users'):
        return _alert('권한이 없습니다.', 'danger')

    recipients = [addr.strip() for addr in (recipients_raw or '').split(',') if addr.strip()]
    if not recipients:
        return _alert('수신자 이메일을 입력하세요.', 'warning')

    # process_project_expertise.py는 pipeline/ 디렉터리를 sys.path에 얹어
    # bare `from mailer import MailError`로 읽으므로, 여기서 `pipeline.mailer`
    # (dotted 경로)로 따로 import하면 이름은 같아도 다른 클래스 객체가 돼
    # except가 안 걸린다 — 반드시 이 모듈이 실제로 쓰는 것과 동일한 참조를
    # process_project_expertise 쪽에서 그대로 가져와야 한다.
    from pipeline.process_project_expertise import MailError, email_report
    try:
        sent = email_report(recipients)
    except MailError as exc:
        return _alert(f'메일 발송 실패: {exc}', 'danger')
    if not sent:
        return _alert(
            '분석 데이터가 없습니다. 먼저 python pipeline/process_project_expertise.py를 실행하세요.',
            'warning',
        )
    return _alert(f'{len(recipients)}명에게 리포트를 발송했습니다.', 'success')


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _alert(msg: str, color: str):
    return dbc.Alert(msg, color=color, dismissable=True, className='py-2 small mb-0')
