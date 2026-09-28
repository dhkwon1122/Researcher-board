"""
관리자 페이지 "사용자/권한 관리" 탭 — pages/admin.py 분할 리팩터링
(2026-09-28)으로 신설. 계정 추가/수정/삭제, 인라인 권한 체크박스, 엑셀
일괄 추가를 담당한다.
"""
import base64

import dash_bootstrap_components as dbc
from dash import ALL, MATCH, Input, Output, State, callback, ctx, dcc, html, no_update

from components.admin_shared import _alert
from config.auth_config import ROLE_LABELS, ROLE_PERMISSIONS

_ROLES = [{'label': v, 'value': k} for k, v in ROLE_LABELS.items()]

# 계정별로 개별 조정 가능한 4개 권한(2026-08-31, config/auth_config.py의
# ROLE_PERMISSIONS와 동일한 키) — 라벨은 사용자 관리 모달 체크박스에 쓴다.
_PERMISSION_LABELS = {
    'view_evaluation': '평가등급 열람',
    'view_incentive':  '인센티브(핵심이력) 열람',
    'view_comments':   '인물 코멘트 열람',
    'view_grade':      '리더십/승계 열람(AI 검색)',
}
_PERMISSION_KEYS = list(_PERMISSION_LABELS.keys())

# 2026-09-04: 기본 표에 인라인 체크박스로 노출하는 6개 권한 관련 컬럼
# (관리자 권한 1개 + 개별 권한 4개 + People팀 평가제외 1개) — 컬럼 헤더는
# 좁은 표에 맞춰 짧게 쓰고, 전체 설명은 title 속성(네이티브 브라우저 툴팁)으로.
_INLINE_PERM_COLUMNS = [
    ('is_admin', '관리자', '관리자 권한 (사용자 관리 페이지 접근 — 역할과 무관하게 이 계정에만 적용)'),
    ('view_evaluation', '평가등급', _PERMISSION_LABELS['view_evaluation']),
    ('exclude_people_team', 'People제외',
     'People팀 평가등급 제외 (People팀·하위 과제/파트 소속 연구원의 평가등급만 가림)'),
    ('view_incentive', '인센티브', _PERMISSION_LABELS['view_incentive']),
    ('view_comments', '코멘트', _PERMISSION_LABELS['view_comments']),
    ('view_grade', '리더십', _PERMISSION_LABELS['view_grade']),
]
# 정렬 가능한 전체 컬럼(신분 정보 5개 + 권한 6개) — '관리' 액션 컬럼은 제외.
_SORTABLE_COLUMNS = [
    ('user_id', '아이디'), ('display_name', '이름'), ('role', '역할'),
    ('email', '이메일'), ('status', '상태'),
] + [(key, label) for key, label, _hint in _INLINE_PERM_COLUMNS]


def _effective_permissions(user: dict) -> dict:
    """이 계정에 지금 실제로 적용되는 권한 6개(관리자 + 개별 4개 +
    People팀 제외 여부)를 계산한다 — 개별 권한은 계정별 재정의(override)가
    있으면 그 값, 없으면(None) 역할 기본값(ROLE_PERMISSIONS)을 따른다
    (기존 '수정' 모달이 체크박스 초기값을 계산하던 것과 동일한 규칙)."""
    role_defaults = ROLE_PERMISSIONS.get(user.get('role', ''), {})
    overrides = user.get('permissions') or {}
    result = {
        key: (overrides.get(key) if overrides.get(key) is not None else role_defaults.get(key, False))
        for key in _PERMISSION_KEYS
    }
    result['is_admin'] = bool(user.get('is_admin'))
    result['exclude_people_team'] = bool(user.get('eval_excluded_dep_ids'))
    return result


def _sort_key_value(user: dict, col: str):
    if col == 'user_id':
        return user.get('user_id', '').lower()
    if col == 'display_name':
        return user.get('display_name', '').lower()
    if col == 'role':
        return ROLE_LABELS.get(user.get('role', ''), user.get('role', '')).lower()
    if col == 'email':
        return (user.get('email') or '').lower()
    if col == 'status':
        return bool(user.get('must_change_password'))
    return _effective_permissions(user).get(col, False)


def _build_user_rows(users: list, sort_state: dict | None) -> list:
    sort_state = sort_state or {}
    col = sort_state.get('column')
    if col:
        users = sorted(users, key=lambda u: _sort_key_value(u, col),
                        reverse=(sort_state.get('direction') == 'desc'))
    return [_user_row(u) for u in users]


def _sort_th(col: str, label: str, sort_state: dict | None, title_attr: str | None = None):
    sort_state = sort_state or {}
    active = sort_state.get('column') == col
    direction = sort_state.get('direction') if active else None
    icon_class = {'asc': 'bi-caret-up-fill', 'desc': 'bi-caret-down-fill'}.get(direction, 'bi-filter')
    th_kwargs = {'title': title_attr} if title_attr else {}
    return html.Th(
        html.Span(
            [label, html.I(className=f'bi {icon_class} ms-1',
                            style={'fontSize': '0.7rem', 'opacity': '1' if active else '0.35'})],
            id={'type': 'user-sort-th', 'col': col}, n_clicks=0,
            style={'cursor': 'pointer', 'userSelect': 'none', 'whiteSpace': 'nowrap'},
        ),
        **th_kwargs,
    )


def _perm_checkbox_cell(user: dict, key: str, effective: dict):
    """권한 관련 6개 컬럼 공용 셀 — 체크박스 하나 + (컬럼당 하나씩만) 저장
    상태를 잠깐 보여주는 작은 아이콘(user_id로 그룹화된 콜백이 채움).

    주의: row-admin-status/row-perm-status는 각각 관리자 콜백/개별권한
    콜백의 유일한 Output이라 행(user_id)당 정확히 1개의 DOM 요소만 이 id를
    가져야 한다 — 개별 권한 5개 컬럼(4개 권한 + People팀 제외) 전부에 이
    상태 span을 넣으면 같은 id가 한 행에 5번 중복되어 Dash가 "이 MATCH
    그룹에 Output 대상이 여럿"이라며 콜백 자체를 포기해버린다(직접
    재현·확인한 버그, 2026-09-04) — 그래서 개별 권한 쪽은 대표로
    view_evaluation 컬럼에만 상태 아이콘을 둔다."""
    user_id = user['user_id']
    value = bool(effective.get(key))
    status = None
    if key == 'is_admin':
        checkbox_id = {'type': 'row-admin-check', 'user_id': user_id}
        status = html.Span(id={'type': 'row-admin-status', 'user_id': user_id}, className='small')
    elif key == 'exclude_people_team':
        checkbox_id = {'type': 'row-perm-exclude', 'user_id': user_id}
    else:
        checkbox_id = {'type': 'row-perm-check', 'field': key, 'user_id': user_id}
        if key == 'view_evaluation':
            status = html.Span(id={'type': 'row-perm-status', 'user_id': user_id}, className='small')
    children = [dbc.Checkbox(id=checkbox_id, value=value, className='du-check-box')]
    if status is not None:
        children.append(status)
    return html.Td(
        html.Div(children, className='d-flex align-items-center justify-content-center gap-1'),
        className='align-middle text-center',
    )


def _user_row(user: dict):
    status = (
        dbc.Badge('임시 비밀번호', color='warning', text_color='dark', className='fw-normal')
        if user.get('must_change_password')
        else dbc.Badge('정상', color='light', text_color='secondary', className='fw-normal border')
    )
    effective = _effective_permissions(user)
    user_id = user['user_id']
    perm_cells = [_perm_checkbox_cell(user, key, effective) for key, _label, _hint in _INLINE_PERM_COLUMNS]
    return html.Tr([
        html.Td(user_id, className='align-middle font-monospace small'),
        html.Td(user['display_name'], className='align-middle'),
        html.Td(ROLE_LABELS.get(user['role'], user['role']), className='align-middle small'),
        html.Td(user.get('email', ''), className='align-middle small text-muted'),
        html.Td(status, className='align-middle'),
        *perm_cells,
        html.Td(
            dbc.ButtonGroup([
                dbc.Button(
                    [html.I(className='bi bi-pencil me-1'), '수정'],
                    id={'type': 'btn-edit', 'user_id': user_id},
                    color='outline-primary', size='sm',
                ),
                dbc.Button(
                    [html.I(className='bi bi-trash me-1'), '삭제'],
                    id={'type': 'btn-delete', 'user_id': user_id},
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
            # 관리자 권한/개별 권한(2026-09-04)은 이 모달에서 뺐다 — 기본
            # 테이블에 컬럼으로 노출된 체크박스로 그 자리에서 바로 켜고 끄며
            # 즉시 저장하도록 변경(사용자 확정) — 이 모달은 신분 정보(아이디/
            # 이름/역할/이메일)와 비밀번호 재설정만 담당한다.
            html.Hr(className='my-2'),
            # 신규 계정(추가)은 비밀번호를 관리자가 입력하지 않는다 — 항상
            # DEFAULT_TEMP_PASSWORD로 시작하고 최초 로그인 시 강제로 바꾸게
            # 한다(사용자 확정 2026-08-31). 이 섹션은 "수정" 때만 보여서
            # 필요하면 기존 계정의 비밀번호를 관리자가 재설정할 수 있다
            # (그 경우엔 지금 정책 그대로 검증됨 — save_user() 참고).
            html.Div(
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
                id='modal-password-section',
            ),
            html.Div(
                id='modal-new-password-note', className='small text-muted mb-2',
            ),
            html.Div(id='user-modal-alert'),
        ]),
        dbc.ModalFooter([
            dbc.Button('취소', id='btn-modal-cancel', color='secondary', size='sm'),
            dbc.Button('저장', id='btn-modal-save', color='primary', size='sm'),
        ]),
    ], id='user-modal', is_open=False, backdrop='static')


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


def _bulk_user_upload_modal():
    """엑셀/CSV로 초기 사용자를 한 번에 추가하는 모달(2026-08-31 신설).
    컬럼 스키마·검증은 services/bulk_user_import.py를 그대로 쓴다(CLI
    스크립트 scripts/bulk_create_users.py와 동일 기준 — REQUIRED_COLUMNS/
    OPTIONAL_COLUMNS도 거기서 가져와 안내문과 어긋나지 않게 한다).
    업로드하면 바로 만들지 않고 미리보기(생성될 계정/건너뛸 항목)를 먼저
    보여준 뒤 "생성"을 눌러야 실제로 만든다 — 여러 계정을 한 번에
    만드는 동작이라 되돌리기 어려우므로 확인 단계를 둔다."""
    from services.bulk_user_import import OPTIONAL_COLUMNS, REQUIRED_COLUMNS

    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle('엑셀로 사용자 일괄 추가')),
        dbc.ModalBody([
            dbc.Alert([
                html.Div([html.Strong('필수 컬럼: '), ', '.join(REQUIRED_COLUMNS)]),
                html.Div([
                    html.Strong('선택 컬럼: '), ', '.join(OPTIONAL_COLUMNS),
                    ' (관리자는 예/아니오, 비워두면 아니오)',
                ], className='mt-1'),
                html.Div(
                    '권한 컬럼에는 정해진 역할명만 입력할 수 있습니다 — 아래 템플릿을 '
                    '내려받으면 드롭다운으로 고를 수 있습니다. 이미 있는 아이디는 '
                    '건너뜁니다(수정은 "수정" 버튼으로 개별 진행).',
                    className='mt-1',
                ),
            ], color='light', className='small border py-2'),
            dbc.Button(
                [html.I(className='bi bi-download me-1'), '템플릿 다운로드'],
                id='btn-download-user-template', color='secondary', outline=True, size='sm',
                className='mb-3',
            ),
            dcc.Download(id='user-template-download'),
            dcc.Upload(
                id='bulk-user-upload',
                children=html.Div([
                    html.I(className='bi bi-cloud-arrow-up me-1'),
                    '클릭 또는 드래그해 엑셀/CSV 업로드',
                ], className='small text-muted'),
                style={
                    'padding': '20px', 'border': '1px dashed #adb5bd', 'borderRadius': '4px',
                    'textAlign': 'center', 'cursor': 'pointer',
                },
                multiple=False,
            ),
            dcc.Store(id='bulk-user-upload-parsed', data=None),
            html.Div(id='bulk-user-upload-preview', className='mt-3'),
        ]),
        dbc.ModalFooter([
            dbc.Button('닫기', id='btn-bulk-upload-cancel', color='secondary', size='sm'),
            dbc.Button('생성', id='btn-bulk-upload-confirm', color='primary', size='sm', disabled=True),
        ]),
    ], id='bulk-user-upload-modal', is_open=False, backdrop='static', size='lg')


# ── 레이아웃 ──────────────────────────────────────────────────────────────────

_DEFAULT_USER_SORT = {'column': None, 'direction': 'asc'}


def _user_management_tab() -> html.Div:
    from services.auth import list_users

    users = list_users()

    # 권한 관련 6개 헤더는 title 속성(네이티브 브라우저 툴팁)으로 전체 설명을 붙인다.
    perm_hint_by_col = {key: hint for key, _label, hint in _INLINE_PERM_COLUMNS}
    header_cells = [
        _sort_th(col, label, _DEFAULT_USER_SORT, title_attr=perm_hint_by_col.get(col))
        for col, label in _SORTABLE_COLUMNS
    ]
    header_cells.append(html.Th('관리'))

    table = dbc.Table(
        [
            html.Thead(html.Tr(header_cells)),
            html.Tbody(_build_user_rows(users, _DEFAULT_USER_SORT), id='user-table-body'),
        ],
        bordered=True, hover=True, responsive=True, size='sm',
        className='mb-0 admin-table user-mgmt-table',
    )

    return html.Div([
        dcc.Store(id='user-refresh-counter', data=0),
        dcc.Store(id='user-list-store', data=users),
        dcc.Store(id='user-sort-state', data=_DEFAULT_USER_SORT),

        dbc.Card([
            dbc.CardHeader(
                dbc.Row([
                    dbc.Col(
                        html.Span(f'총 {len(users)}명', className='small text-muted'),
                        className='d-flex align-items-center',
                    ),
                    dbc.Col(
                        dbc.ButtonGroup([
                            dbc.Button(
                                [html.I(className='bi bi-file-earmark-excel me-1'), '엑셀로 추가'],
                                id='btn-open-bulk-upload', color='secondary', outline=True, size='sm',
                                title='엑셀/CSV 명단으로 초기 사용자를 한 번에 추가',
                            ),
                            dbc.Button(
                                [html.I(className='bi bi-person-plus me-1'), '사용자 추가'],
                                id='btn-add-user', color='primary', size='sm',
                            ),
                        ]),
                        className='text-end',
                    ),
                ], align='center'),
            ),
            dbc.CardBody(table, className='p-0'),
        ], className='shadow-sm'),

        html.Div(id='admin-page-alert', className='mt-3'),

        _user_modal(),
        _delete_modal(),
        _bulk_user_upload_modal(),
    ], className='pt-3')


# ── 콜백: 사용자 목록 갱신 ────────────────────────────────────────────────────

@callback(
    Output('user-list-store', 'data'),
    Input('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def refresh_user_table(_counter):
    from services.auth import can, list_users
    if not can('manage_users'):
        return []
    return list_users()


# ── 콜백: 정렬 헤더 클릭 ──────────────────────────────────────────────────────

@callback(
    Output('user-sort-state', 'data'),
    Input({'type': 'user-sort-th', 'col': ALL}, 'n_clicks'),
    State('user-sort-state', 'data'),
    prevent_initial_call=True,
)
def toggle_user_sort(n_clicks_list, sort_state):
    if not any(n for n in n_clicks_list if n):
        return no_update
    triggered = ctx.triggered_id
    if not triggered:
        return no_update
    col = triggered['col']
    sort_state = sort_state or {}
    direction = 'desc' if sort_state.get('column') == col and sort_state.get('direction') == 'asc' else 'asc'
    return {'column': col, 'direction': direction}


# ── 콜백: 표 본문 렌더링(정렬 상태 또는 목록이 바뀔 때마다) ────────────────────

@callback(
    Output('user-table-body', 'children'),
    Input('user-sort-state', 'data'),
    Input('user-list-store', 'data'),
)
def render_user_table_body(sort_state, users):
    return _build_user_rows(users or [], sort_state)


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
    Output('modal-password-section', 'style', allow_duplicate=True),
    Output('modal-new-password-note', 'children', allow_duplicate=True),
    Output('user-modal-alert', 'children', allow_duplicate=True),
    Input('btn-add-user', 'n_clicks'),
    prevent_initial_call=True,
)
def open_add_modal(_):
    from services.auth import DEFAULT_TEMP_PASSWORD
    return (
        True, '사용자 추가', None,
        '', False,          # user_id, disabled
        '',                 # display_name
        _ROLES[0]['value'], # role default
        '',                 # email
        '', '',             # passwords(안 씀 — 아래 modal-password-section 자체를 숨김)
        '',                 # modal-pw-label(안 보이므로 내용 무의미)
        # 비밀번호 입력란은 신규 추가 시 숨기고(관리자가 직접 입력하지 않음
        # — 사용자 확정 2026-08-31), 고정 임시 비밀번호 안내만 보여준다.
        # 관리자 권한/개별 권한(2026-09-04)은 이 모달에서 완전히 빠졌다 —
        # 계정을 만든 뒤 기본 표의 체크박스로 그 자리에서 바로 설정한다.
        {'display': 'none'},
        f'신규 계정은 임시 비밀번호 "{DEFAULT_TEMP_PASSWORD}"로 생성되며, '
        f'최초 로그인 후 반드시 새 비밀번호로 변경해야 합니다. '
        f'관리자 권한·개별 권한은 계정 생성 후 표에서 바로 설정할 수 있습니다.',
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
    Output('modal-password-section', 'style', allow_duplicate=True),
    Output('modal-new-password-note', 'children', allow_duplicate=True),
    Output('user-modal-alert', 'children', allow_duplicate=True),
    Input({'type': 'btn-edit', 'user_id': ALL}, 'n_clicks'),
    State('user-list-store', 'data'),
    prevent_initial_call=True,
)
def open_edit_modal(n_clicks_list, users):
    from services.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
    n_outputs = 14
    if not any(n for n in n_clicks_list if n):
        return [no_update] * n_outputs
    triggered = ctx.triggered_id
    if triggered is None:
        return [no_update] * n_outputs
    u = next((x for x in (users or []) if x['user_id'] == triggered['user_id']), None)
    if u is None:
        return [no_update] * n_outputs
    return (
        True, '사용자 수정', u['user_id'],
        u['user_id'], True,              # user_id readonly
        u.get('display_name', ''),
        u.get('role', _ROLES[0]['value']),
        u.get('email', ''),
        '', '',
        f'새 비밀번호 (변경 시에만 입력 — {MIN_PASSWORD_LENGTH}~{MAX_PASSWORD_LENGTH}자, 영문/숫자/특수문자 조합)',
        {},   # modal-password-section: 수정 화면에서는 보이도록
        '',   # modal-new-password-note: 수정 때는 안 씀
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
    State('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def save_user(_, editing_id, user_id, display_name, role, email, password, pw_confirm, counter):
    # 관리자 권한/개별 권한(2026-09-04)은 이 모달이 더 이상 다루지 않는다 —
    # 기본 표의 인라인 체크박스 콜백(save_row_admin/save_row_permissions)이
    # 전담한다. 이 함수는 신분 정보(아이디/이름/역할/이메일)와 비밀번호
    # 재설정만 처리.
    from services.auth import (
        DEFAULT_TEMP_PASSWORD, can, change_password, create_user,
        password_validation_error, update_user,
    )
    if not can('manage_users'):
        return _alert('권한이 없습니다.', 'danger'), no_update, no_update

    user_id = (user_id or '').strip()
    display_name = (display_name or '').strip()
    email = (email or '').strip()
    password = password or ''
    pw_confirm = pw_confirm or ''

    if not display_name or not role:
        return _alert('이름과 역할은 필수입니다.', 'warning'), no_update, no_update

    is_new = editing_id is None

    if is_new:
        if not user_id:
            return _alert('아이디는 필수입니다.', 'warning'), no_update, no_update
        # 신규 계정은 항상 고정 임시 비밀번호로 시작하고(관리자가 직접
        # 입력하지 않음 — 사용자 확정 2026-08-31) must_change_password=True로
        # 잠근다. 이 값 자체는 비밀번호 정책을 만족하지 않으므로
        # password_validation_error() 검증을 여기서는 건너뛴다 — 정책은
        # 계정 소유자가 최초 로그인 후 본인 비밀번호로 바꿀 때부터 적용된다
        # (app.py의 /change-password, DEFAULT_TEMP_PASSWORD 독스트링 참고).
        # is_admin은 항상 False로 시작 — 표의 "관리자" 체크박스로 나중에 부여.
        try:
            create_user(user_id, DEFAULT_TEMP_PASSWORD, display_name, role, email,
                        must_change_password=True, is_admin=False)
        except ValueError as exc:
            return _alert(str(exc), 'danger'), no_update, no_update
    else:
        if password:
            password_error = password_validation_error(password)
            if password_error:
                return _alert(password_error, 'warning'), no_update, no_update
            if password != pw_confirm:
                return _alert('비밀번호가 일치하지 않습니다.', 'warning'), no_update, no_update
            change_password(editing_id, password)
        update_user(editing_id, display_name=display_name, role=role, email=email)

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
    Input({'type': 'btn-delete', 'user_id': ALL}, 'n_clicks'),
    State('user-list-store', 'data'),
    prevent_initial_call=True,
)
def open_delete_modal(n_clicks_list, users):
    if not any(n for n in n_clicks_list if n):
        return no_update, no_update, no_update
    triggered = ctx.triggered_id
    if triggered is None:
        return no_update, no_update, no_update
    u = next((x for x in (users or []) if x['user_id'] == triggered['user_id']), None)
    if u is None:
        return no_update, no_update, no_update
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


# ── 콜백: 표 안 "관리자" 체크박스 — 클릭 즉시 저장 ─────────────────────────────

@callback(
    Output({'type': 'row-admin-status', 'user_id': MATCH}, 'children'),
    Output({'type': 'row-admin-check', 'user_id': MATCH}, 'value', allow_duplicate=True),
    Input({'type': 'row-admin-check', 'user_id': MATCH}, 'value'),
    prevent_initial_call=True,
)
def save_row_admin(is_admin):
    """"관리자" 컬럼 체크박스 — 클릭한 순간 바로 update_user()로 저장한다
    (사용자 확정 2026-09-04, 모달의 "저장" 버튼을 거치지 않음). 표
    재렌더링(정렬 클릭 등)으로 이 체크박스가 새로 마운트될 때도 같은
    콜백이 한 번 더 불릴 수 있는데(이 코드베이스가 이미 여러 번 겪은
    "패턴매칭 컴포넌트 재마운트 시 유령 트리거" 현상), 그때 넘어오는 값은
    항상 방금 그 시점의 실제 값이라 다시 저장해도(멱등) 데이터가 틀어지지
    않는다."""
    from services.auth import can, get_current_user, update_user
    user_id = ctx.outputs_list[0]['id']['user_id']
    if not can('manage_users'):
        return html.I(className='bi bi-x-circle text-danger', title='권한이 없습니다.'), no_update
    current = get_current_user()
    if current and current['user_id'] == user_id and not is_admin:
        # 자기 자신의 관리자 권한은 스스로 해제할 수 없다(기존 모달 저장
        # 로직에 있던 규칙을 그대로 유지) — 체크박스를 다시 켜진 상태로
        # 되돌리고 이유를 보여준다.
        return (
            html.I(className='bi bi-exclamation-triangle text-warning',
                   title='자기 자신의 관리자 권한은 해제할 수 없습니다. 다른 관리자가 대신 해제해야 합니다.'),
            True,
        )
    update_user(user_id, is_admin=bool(is_admin))
    return html.I(className='bi bi-check-circle text-success', title='저장되었습니다.'), no_update


# ── 콜백: 표 안 개별 권한 체크박스(4개 + People팀 제외) — 클릭 즉시 저장 ────────

@callback(
    Output({'type': 'row-perm-status', 'user_id': MATCH}, 'children'),
    Input({'type': 'row-perm-check', 'field': 'view_evaluation', 'user_id': MATCH}, 'value'),
    Input({'type': 'row-perm-check', 'field': 'view_incentive', 'user_id': MATCH}, 'value'),
    Input({'type': 'row-perm-check', 'field': 'view_comments', 'user_id': MATCH}, 'value'),
    Input({'type': 'row-perm-check', 'field': 'view_grade', 'user_id': MATCH}, 'value'),
    Input({'type': 'row-perm-exclude', 'user_id': MATCH}, 'value'),
    prevent_initial_call=True,
)
def save_row_permissions(view_evaluation, view_incentive, view_comments, view_grade, exclude_people_team):
    """개별 권한 4개 + People팀 평가제외 체크박스 — 하나라도 바뀌면 그 행의
    5개 값을 한꺼번에 읽어(MATCH로 같은 user_id 그룹만) update_permissions()
    로 즉시 저장한다. 이 API는 4개 권한을 부분 업데이트가 아니라 항상 전부
    함께 저장해야 해서(services/auth.py update_permissions 독스트링 참고),
    Input 5개를 한 콜백에 모아 매번 완전한 상태로 저장한다. save_row_admin과
    동일한 이유로 재마운트에 의한 재실행도 멱등이라 안전하다."""
    from services.auth import can, update_permissions
    from services.similarity_map import people_team_dep_ids
    user_id = ctx.outputs_list['id']['user_id']
    if not can('manage_users'):
        return html.I(className='bi bi-x-circle text-danger', title='권한이 없습니다.')
    permissions = {
        'view_evaluation': bool(view_evaluation),
        'view_incentive': bool(view_incentive),
        'view_comments': bool(view_comments),
        'view_grade': bool(view_grade),
    }
    excluded_dep_ids = list(people_team_dep_ids()) if exclude_people_team else []
    update_permissions(user_id, permissions, excluded_dep_ids)
    return html.I(className='bi bi-check-circle text-success', title='저장되었습니다.')


# ── 콜백: 엑셀로 사용자 일괄 추가 ─────────────────────────────────────────────

def _bulk_upload_row_table(rows: list, columns: list) -> dbc.Table:
    return dbc.Table([
        html.Thead(html.Tr([html.Th(c) for c in columns])),
        html.Tbody([html.Tr([html.Td(str(v)) for v in r]) for r in rows]),
    ], bordered=True, hover=True, size='sm', className='mb-2')


def _bulk_upload_preview(result: dict) -> list:
    """업로드 파싱 결과(services.bulk_user_import.parse_rows 반환값)를
    "생성될 계정 / 이미 존재해 건너뜀 / 형식 오류로 건너뜀" 3단으로
    요약한다 — 아직 계정을 만들지 않은 상태의 미리보기 화면."""
    from config.auth_config import ROLE_LABELS

    parts = []
    rows = result['rows']
    if rows:
        parts.append(html.Div(f'생성될 계정 {len(rows)}명', className='fw-semibold small mb-1'))
        parts.append(_bulk_upload_row_table(
            [[u['user_id'], u['display_name'], ROLE_LABELS.get(u['role'], u['role']),
              u['email'] or '-', '예' if u['is_admin'] else '']
             for u in rows],
            ['아이디', '이름', '역할', '이메일', '관리자'],
        ))
    else:
        parts.append(_alert('생성할 계정이 없습니다 — 아래 건너뜀 목록을 확인하세요.', 'warning'))

    if result['skipped_existing']:
        parts.append(html.Div(
            f"이미 존재해서 건너뜀 ({len(result['skipped_existing'])}명): "
            f"{', '.join(result['skipped_existing'])}",
            className='small text-muted mb-1',
        ))
    if result['skipped_invalid']:
        parts.append(html.Div('형식 오류로 건너뜀:', className='small text-muted mb-1'))
        parts.append(html.Ul([
            html.Li(f'{uid}: {reason}', className='small text-muted')
            for uid, reason in result['skipped_invalid']
        ], className='mb-1'))
    return parts


@callback(
    Output('bulk-user-upload-modal', 'is_open', allow_duplicate=True),
    Input('btn-open-bulk-upload', 'n_clicks'),
    prevent_initial_call=True,
)
def open_bulk_upload_modal(_):
    return True


@callback(
    Output('bulk-user-upload-modal', 'is_open', allow_duplicate=True),
    Output('bulk-user-upload', 'contents'),
    Output('bulk-user-upload-parsed', 'data', allow_duplicate=True),
    Output('bulk-user-upload-preview', 'children', allow_duplicate=True),
    Output('btn-bulk-upload-confirm', 'disabled', allow_duplicate=True),
    Input('btn-bulk-upload-cancel', 'n_clicks'),
    prevent_initial_call=True,
)
def close_bulk_upload_modal(_):
    # 업로드 상태를 전부 비워서, 다음에 다시 열었을 때 이전 파일의 미리보기가
    # 남아있지 않게 한다.
    return False, None, None, None, True


@callback(
    Output('user-template-download', 'data'),
    Input('btn-download-user-template', 'n_clicks'),
    prevent_initial_call=True,
)
def download_user_template(n_clicks):
    from services.auth import can
    if not n_clicks or not can('manage_users'):
        return no_update
    from services.bulk_user_import import build_template_bytes
    return dcc.send_bytes(build_template_bytes(), '사용자_일괄추가_템플릿.xlsx')


@callback(
    Output('bulk-user-upload-parsed', 'data', allow_duplicate=True),
    Output('bulk-user-upload-preview', 'children', allow_duplicate=True),
    Output('btn-bulk-upload-confirm', 'disabled', allow_duplicate=True),
    Input('bulk-user-upload', 'contents'),
    State('bulk-user-upload', 'filename'),
    prevent_initial_call=True,
)
def parse_bulk_upload(contents, filename):
    from services.auth import can, list_users
    if not can('manage_users'):
        return None, _alert('권한이 없습니다.', 'danger'), True
    if not contents:
        return None, None, True

    try:
        _header, b64data = contents.split(',', 1)
        file_bytes = base64.b64decode(b64data, validate=True)
    except (ValueError, TypeError):
        return None, _alert('파일을 읽지 못했습니다.', 'danger'), True

    from services.bulk_user_import import MAX_UPLOAD_BYTES, parse_rows, read_upload
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return None, _alert(f'파일이 너무 큽니다(최대 {limit_mb}MB).', 'danger'), True

    try:
        df = read_upload(file_bytes, filename or '')
    except Exception as exc:
        return None, _alert(f'파일을 읽지 못했습니다: {exc}', 'danger'), True

    existing_ids = {u['user_id'] for u in list_users()}
    result = parse_rows(df, existing_ids)

    if result['missing_columns']:
        msg = f"필수 컬럼을 찾을 수 없습니다: {', '.join(result['missing_columns'])}"
        return None, _alert(msg, 'danger'), True

    return result, _bulk_upload_preview(result), not result['rows']


@callback(
    Output('bulk-user-upload-preview', 'children', allow_duplicate=True),
    Output('user-refresh-counter', 'data', allow_duplicate=True),
    Output('btn-bulk-upload-confirm', 'disabled', allow_duplicate=True),
    Input('btn-bulk-upload-confirm', 'n_clicks'),
    State('bulk-user-upload-parsed', 'data'),
    State('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def confirm_bulk_create(n_clicks, parsed, counter):
    from services.auth import DEFAULT_TEMP_PASSWORD, can, create_user
    if not can('manage_users'):
        return _alert('권한이 없습니다.', 'danger'), no_update, True
    if not parsed or not parsed.get('rows'):
        return no_update, no_update, True

    # 여기서도(화면 미리보기 이후) 다시 아이디 중복 등을 걸러낸다 —
    # create_user() 자체가 생성 시점에 다시 확인하므로 미리보기 이후
    # 다른 관리자가 같은 아이디를 먼저 만들었어도 안전하게 건너뛴다.
    ok, failed = [], []
    for u in parsed['rows']:
        try:
            create_user(u['user_id'], DEFAULT_TEMP_PASSWORD, u['display_name'], u['role'],
                        u['email'], must_change_password=True, is_admin=u['is_admin'])
            ok.append(u['user_id'])
        except Exception as exc:
            failed.append((u['user_id'], str(exc)))

    parts = [_alert(
        f'{len(ok)}명 생성 완료. 임시 비밀번호 "{DEFAULT_TEMP_PASSWORD}"를 안전한 방법으로 '
        f'전달하세요 — 최초 로그인 시 반드시 새 비밀번호로 변경해야 합니다.',
        'success' if ok else 'warning',
    )]
    if failed:
        parts.append(html.Div('생성 실패:', className='small text-muted mb-1'))
        parts.append(html.Ul([
            html.Li(f'{uid}: {err}', className='small text-muted') for uid, err in failed
        ]))
    return parts, (counter or 0) + 1, True
