"""
관리자 페이지: 사용자 계정 관리 (추가 / 수정 / 삭제)
manage_users 권한이 있는 계정만 접근 가능.
"""
import base64
import os
from datetime import date

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, dash_table, dcc, html, no_update

from config.auth_config import ROLE_LABELS, ROLE_PERMISSIONS
from services import similarity_map, team_refer_store
from services import web_pipeline_runner as wpr

dash.register_page(__name__, path='/admin', name='관리자', title='사용자/권한 관리')

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
            html.Div(
                [
                    html.Hr(className='my-2'),
                    dbc.Label('개별 권한 (역할 기본값을 계정 단위로 재정의 — 미체크해도 삭제되지 않고, '
                              '저장 시점 값이 이 계정에 고정됩니다)', size='sm', className='fw-semibold'),
                    dbc.Checklist(
                        id='modal-permissions',
                        options=[{'label': f' {label}', 'value': key}
                                 for key, label in _PERMISSION_LABELS.items()],
                        value=[], switch=True, className='mb-2 small',
                    ),
                    dbc.Label('평가등급 열람 제외 부서 (체크해도 이 부서 소속 연구원의 평가만은 가립니다)',
                              html_for='modal-eval-excluded-depts', size='sm'),
                    dcc.Dropdown(
                        id='modal-eval-excluded-depts', options=similarity_map.org_tree_options(), value=[],
                        multi=True, placeholder='제외할 부서 없음', className='small mb-2',
                    ),
                ],
                id='modal-permissions-section',
            ),
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
                        placeholder='수신자 이메일(콤마로 구분, 비워두면 본인에게 발송)',
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

def _user_management_tab() -> html.Div:
    from services.auth import list_users

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

    return html.Div([
        dcc.Store(id='user-refresh-counter', data=0),
        dcc.Store(id='user-list-store', data=users),

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

        _mail_report_card(),

        _user_modal(),
        _delete_modal(),
        _bulk_user_upload_modal(),
    ], className='pt-3')


def _sort_key(value):
    """정렬용 키 — 숫자로 보이는 값(조직 레벨/사번/부서ID/상위부서ID 등)은
    숫자로, 아니면 문자열로 비교한다. 빈 값은 항상 맨 뒤로 보낸다."""
    s = str(value or '').strip()
    if not s:
        return (2, '')
    try:
        return (0, int(s))
    except ValueError:
        return (1, s)


def _renumbered(rows: list) -> list:
    """현재 순서(정렬/추가/삭제 반영 후) 그대로 1부터 번호를 다시 매긴다 —
    '_no'는 화면 표시 전용이라 저장 대상 데이터에는 포함되지 않는다."""
    for i, r in enumerate(rows, start=1):
        r['_no'] = i
    return rows


def _team_refer_tab() -> html.Div:
    """팀/리더 참조 웹 CRUD 탭. 컬럼은 팀참조시트.xlsx 원본 헤더명을 그대로
    쓴다(pipeline.process_team_refer._COL_MAP 재사용, services.team_refer_store
    참고) — 행 추가/삭제로 조직 단위를 직접 편집하고, 저장하면 지정한 날짜로
    누적된다(같은 날 재저장은 그날 값을 덮어씀)."""
    rows = team_refer_store.list_editable_rows()
    loaded_dep_ids = sorted({r.get('부서ID', '') for r in rows if r.get('부서ID')})
    rows = _renumbered(rows)

    # 'No.' 는 화면 표시 전용 — 저장 대상 컬럼(KOREAN_COLUMNS)에는 없으므로
    # team_refer_store.save_snapshot()이 그대로 무시한다(_COL_MAP에 없는 키).
    columns = [{'name': 'No.', 'id': '_no', 'editable': False}] + [
        {'name': col, 'id': col, 'editable': True}
        for col in team_refer_store.KOREAN_COLUMNS
    ]

    return html.Div([
        dcc.Store(id='team-refer-loaded-dep-ids', data=loaded_dep_ids),

        dbc.Alert(
            [
                html.I(className='bi bi-info-circle me-2'),
                '조직 레벨/부서ID가 비어 있는 행은 저장되지 않습니다. 상위부서ID는 '
                '실제 존재하는 부서ID를 가리켜야 하며, 없으면 최상위 조직으로 취급됩니다.',
            ],
            color='light', className='small border mb-3',
        ),

        dbc.Row([
            dbc.Col([
                dbc.Label('입력 날짜', className='small fw-semibold text-muted mb-1'),
                dcc.DatePickerSingle(
                    id='team-refer-valid-date', date=date.today().isoformat(),
                    display_format='YYYY-MM-DD', className='d-block',
                ),
                html.Div(
                    '기본값은 오늘 — 과거 데이터를 소급 입력할 때만 바꾸세요.',
                    className='text-muted', style={'fontSize': '0.72rem'},
                ),
            ], md='auto'),
            dbc.Col([
                dbc.Label(' ', className='small d-block mb-1'),
                dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-plus-lg me-1'), '행 추가'],
                               id='team-refer-add-row-btn', color='secondary', outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-save me-1'), '저장'],
                               id='team-refer-save-btn', color='primary', size='sm'),
                ]),
            ], md='auto'),
        ], className='mb-2 align-items-end'),

        dash_table.DataTable(
            id='team-refer-table',
            columns=columns,
            data=rows,
            editable=True,
            row_deletable=True,
            page_action='none',  # 페이지 나누지 않고 전체 행을 한 번에 표시
            sort_action='custom',  # 헤더 클릭 정렬 — team_refer_sort 콜백이 처리(No.도 같이 갱신)
            sort_by=[],
            style_table={'overflowX': 'auto'},
            # 전체 가운데 정렬 + 좁은 폭에서도 최대한 좌우 스크롤 없이 한 화면에
            # 들어오도록 폰트/여백을 줄이고, 그래도 안 들어가는 내용은 말줄임
            # 처리 후 마우스 오버로 전체를 보여준다(tooltip_data, 사용자 확정
            # — 안 들어가면 스크롤이 남는 것도 허용).
            style_cell={
                'fontSize': '0.72rem', 'padding': '3px 6px', 'textAlign': 'center',
                'minWidth': '55px', 'maxWidth': '160px',
                'overflow': 'hidden', 'textOverflow': 'ellipsis',
            },
            style_cell_conditional=[{'if': {'column_id': '_no'}, 'width': '40px', 'textAlign': 'center'}],
            style_header={'fontWeight': '600', 'backgroundColor': '#f1f3f5',
                          'textAlign': 'center', 'fontSize': '0.72rem'},
            tooltip_delay=0,
            tooltip_duration=None,
            # DataTable에는 컬럼 너비 드래그 조절 기능이 없어(구버전 dash_table),
            # 헤더 텍스트를 감싸는 요소에 브라우저 네이티브 CSS resize를 적용해
            # 우측 하단 모서리를 드래그해 너비를 조절할 수 있게 한다.
            css=[{
                'selector': '.column-header-name',
                'rule': ('display: inline-block; resize: horizontal; overflow: auto; '
                         'min-width: 40px; max-width: 600px; vertical-align: bottom;'),
            }],
        ),

        html.Div(id='team-refer-save-msg', className='mt-2'),

        # 저장한 행들 안에 부서ID(dep_id)가 중복되면(업서트 자연키 충돌로
        # 일부 행이 조용히 사라지는 원인) 별도 창으로 바로 보여준다(사용자
        # 요청) — data/processed/CLAUDE.md 참고.
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle([
                    html.I(className='bi bi-exclamation-triangle-fill text-warning me-2'),
                    '부서ID(dep_id) 중복 발견',
                ])),
                dbc.ModalBody(id='team-refer-dupe-modal-body'),
                dbc.ModalFooter(dbc.Button('확인', id='team-refer-dupe-modal-close', size='sm')),
            ],
            id='team-refer-dupe-modal', is_open=False, size='lg',
        ),
    ], className='pt-3')


_STATUS_COLORS = {'성공': 'success', '실패': 'danger', '실행중': 'info'}


def _upload_box(key: str, slot: str, small_label: str = '', multiple: bool = False) -> html.Div:
    """단일 업로드 드롭존. slot: 'single'(대부분) | 'legacy'/'new'(직무이력 전용).
    multiple=True(대량 백필 대상 항목만, needs_valid_date 참고)면 파일을
    여러 개 한 번에 선택할 수 있다 — 파일명이 "_YYYYMM"으로 끝나는 것만
    백필로 인식되고(pipeline/backfill_utils.py), 그 외는 무시된다."""
    return dcc.Upload(
        id={'type': 'du-upload', 'key': key, 'slot': slot},
        children=html.Div([
            html.I(className='bi bi-cloud-arrow-up me-1'),
            small_label or '클릭 또는 드래그해 업로드',
        ], className='small text-muted'),
        style={
            'padding': '4px 8px', 'border': '1px dashed #adb5bd', 'borderRadius': '4px',
            'textAlign': 'center', 'cursor': 'pointer',
        },
        multiple=multiple,
    )


def _data_update_row(row: dict) -> html.Tr:
    key = row['key']

    if row['mode'] == 'dual':
        upload_cell = html.Div([
            html.Div('① 구버전 이력(선택, 최초 1회)', className='small text-muted mb-1'),
            _upload_box(key, 'legacy', '업로드'),
            html.Div('② 내 리포트(필수)', className='small text-muted mt-2 mb-1'),
            _upload_box(key, 'new', '업로드'),
        ])
    else:
        upload_cell = _upload_box(key, 'single', multiple=row['needs_valid_date'])

    filenames = row['uploaded_filenames']
    filenames_view = (
        html.Div([html.Div(f, className='small') for f in filenames], className='mt-1')
        if filenames else html.Div('업로드된 파일 없음', className='small text-muted mt-1')
    )

    # 대량 백필 대기 파일(파일명이 "_YYYYMM"으로 끝나는 것들, 2026-08-28) —
    # 실행을 누르면 오래된 시점부터 순서대로 전부 반영된다.
    backfill_view = None
    if row['needs_valid_date'] and row.get('backfill_files'):
        bf = row['backfill_files']
        backfill_view = html.Div([
            html.Div(
                [html.I(className='bi bi-layers me-1'), f'백필 대기 {len(bf)}건 ({bf[0][1]} ~ {bf[-1][1]})'],
                className='small text-info fw-semibold mt-1',
            ),
            html.Div(
                '한 파일에 "_YYYYMM"(예: _202305)을 붙여 여러 개를 한 번에 올리면, '
                '실행 시 오래된 시점부터 순서대로 전부 반영됩니다.',
                className='text-muted', style={'fontSize': '0.68rem'},
            ),
        ])

    status = row['status']
    status_badge = (
        dbc.Badge([html.I(className='bi bi-arrow-repeat me-1'), '실행중'], color='info')
        if status == '실행중'
        else dbc.Badge(status or '-', color=_STATUS_COLORS.get(status, 'secondary'))
    )

    api_btn = dbc.Button(
        [html.I(className='bi bi-cloud-arrow-down me-1'),
         'API로 가져오기' if row['has_api'] else 'API 연동 예정'],
        id={'type': 'du-api', 'key': key},
        color='primary' if row['has_api'] else 'secondary',
        outline=True, size='sm', className='mt-2 py-0 px-1',
        style={'fontSize': '0.68rem'},
    )

    # "현재상태" 성격 항목(evaluations/tech_ownership/job_profile/work_objective_*)은
    # 이번 업로드분이 어느 시점 기준인지(연/월) 지정해야 한다 — 과거 시점으로
    # 잘못 지정하면 process_*.py가 기존 최신 값을 보호하려고 그 사람 행을
    # 건너뛴다(정상 동작, 실행결과 메시지로 안내). 기본값은 오늘.
    valid_date_picker = (
        html.Div([
            dbc.Label('기준 연/월', className='small text-muted mb-0', style={'fontSize': '0.68rem'}),
            dcc.DatePickerSingle(
                id={'type': 'du-valid-date', 'key': key}, date=date.today().isoformat(),
                display_format='YYYY-MM', className='d-block',
            ),
            html.Div(
                '파일명이 "_YYYYMM"으로 끝나는 백필 업로드에는 적용되지 않습니다(파일명의 날짜를 그대로 씀).',
                className='text-muted', style={'fontSize': '0.65rem'},
            ),
        ], className='mt-2')
        if row['needs_valid_date'] else None
    )

    return html.Tr([
        html.Td(dbc.Checkbox(id={'type': 'du-check', 'key': key}, value=False), className='align-middle text-center'),
        html.Td([html.Div(row['label'], className='fw-semibold'),
                 html.Div(row['hint'], className='text-muted', style={'fontSize': '0.72rem'}),
                 api_btn, valid_date_picker],
                className='align-middle'),
        html.Td([upload_cell, filenames_view, backfill_view], className='align-middle', style={'minWidth': '220px'}),
        html.Td([
            dbc.Button(html.I(className='bi bi-download'), id={'type': 'du-download', 'key': key},
                       color='link', size='sm', disabled=not row['has_upload'], className='p-0'),
            html.Div(row['uploaded_at'] or '-', className='small text-muted'),
        ], className='align-middle text-center'),
        html.Td(row['last_run_at'] or '-', className='align-middle small text-center'),
        html.Td([status_badge, html.Div(row['message'], className='small text-muted mt-1',
                                         title=row['message'])],
                className='align-middle', style={'minWidth': '200px'}),
    ])


def _data_update_table() -> dbc.Table:
    rows = wpr.snapshot()
    header = html.Thead(html.Tr([
        html.Th('', style={'width': '36px'}), html.Th('구분'), html.Th('업로드'),
        html.Th('이전 Data'), html.Th('최종실행이력'), html.Th('실행결과'),
    ]))
    body = html.Tbody([_data_update_row(r) for r in rows])
    return dbc.Table([header, body], bordered=True, hover=True, responsive=True, size='sm',
                      className='align-middle mb-0')


def _db_status_view() -> html.Span:
    s = wpr.db_load_status()
    if not s.get('last_run_at'):
        return html.Span('DB 반영: 아직 실행한 적 없음', className='text-muted small')
    color = _STATUS_COLORS.get(s['status'], 'secondary')
    return html.Span([
        html.Span('DB 반영 ', className='small text-muted'),
        dbc.Badge(s['status'] or '-', color=color, className='me-2'),
        html.Span(s['last_run_at'], className='text-muted small me-2'),
        html.Span(s.get('message', ''), className='small'),
    ])


def _data_update_tab() -> html.Div:
    """매니페스트 등록 파일 중 20개(리더십진단·comments 제외)를 웹에서 직접
    업로드→실행할 수 있는 탭. 실제 실행/락/로그는 services/web_pipeline_runner.py.
    전제: 업로드 전 사용자가 DRM을 해제한 사본을 올린다(사용자 확정)."""
    return html.Div([
        dcc.Download(id='data-update-download'),
        dcc.Interval(id='data-update-interval', interval=3000, disabled=not wpr.any_running()),

        dbc.Alert(
            [
                html.I(className='bi bi-info-circle me-2'),
                '원본 엑셀이 사내 DRM으로 보호돼 있다면, 업로드 전 자신의 PC에서 '
                'Excel로 열어 "다른 이름으로 저장"으로 DRM이 풀린 사본을 만들어 '
                '올려주세요. "전체 업데이트"는 파일이 업로드된 항목만 실행합니다. '
                '각 항목의 "API 연동 예정" 아이콘은 추후 사내 API 연동 시 사용할 '
                '자리로, 현재는 눌러도 동작하지 않습니다.',
            ],
            color='light', className='small border mb-3',
        ),

        dbc.Row([
            dbc.Col(html.Div(id='data-update-status-msg'), md=True),
            dbc.Col(
                dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-database-up me-1'), 'DB 반영'],
                               id='data-update-db-btn', color='secondary', outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-check2-square me-1'), '선택 업데이트'],
                               id='data-update-selected-btn', color='primary', outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-arrow-repeat me-1'), '전체 업데이트'],
                               id='data-update-all-btn', color='primary', size='sm'),
                ]),
                md='auto',
            ),
        ], className='mb-2 align-items-start'),

        html.Div(_db_status_view(), id='data-update-db-status', className='mb-2'),

        html.Div(_data_update_table(), id='data-update-table-container'),
    ], className='pt-3')


def _dev_update_week_card(week: dict) -> dbc.Card:
    body = [html.Div(week['range_label'], className='fw-bold mb-2', style={'fontSize': '0.95rem'})]
    if week.get('major'):
        body.append(html.Div('주요 업데이트', className='text-uppercase text-muted fw-semibold',
                              style={'fontSize': '0.68rem', 'letterSpacing': '0.04em'}))
        body.append(html.Ul([html.Li(m, className='mb-1') for m in week['major']],
                             className='mb-2', style={'fontSize': '0.88rem'}))
    if week.get('detail'):
        body.append(html.Div('세부사항', className='text-uppercase text-muted fw-semibold',
                              style={'fontSize': '0.68rem', 'letterSpacing': '0.04em'}))
        body.append(html.Ul([html.Li(d, className='mb-1') for d in week['detail']],
                             className='mb-0 text-muted', style={'fontSize': '0.82rem'}))
    return dbc.Card(dbc.CardBody(body), className='shadow-sm mb-3')


def _dev_updates_tab() -> html.Div:
    """이 앱 자체의 기능 변경 이력을 주 단위 개조식으로 보여주는 탭 — 콘텐츠는
    services/dev_updates.py에서 관리한다(웹 CRUD 아님, 코드로 유지 — 매주
    금요일 기능 업데이트가 있으면 Claude가 이 파일에 추가할 내용을 제안하도록
    예약돼 있다. 사용자 확정)."""
    from services import dev_updates
    return html.Div([
        dbc.Alert(
            [html.I(className='bi bi-info-circle me-2'),
             '이 화면에 보이는 기능 개발 이력입니다(원천 데이터/DB 갱신은 포함하지 않습니다). '
             '최신 주가 맨 위에 옵니다.'],
            color='light', className='small border mb-3',
        ),
        html.Div([_dev_update_week_card(w) for w in dev_updates.WEEKS]),
    ], className='pt-3')


def layout():
    from services.auth import can
    if not can('manage_users'):
        return _access_denied()

    return dbc.Container([
        dbc.Tabs([
            dbc.Tab(_user_management_tab(), label='사용자/권한 관리',
                    tab_id='tab-users', label_style={'fontWeight': '600'}),
            dbc.Tab(_team_refer_tab(), label='팀/리더 참조',
                    tab_id='tab-team-refer', label_style={'fontWeight': '600'}),
            dbc.Tab(_data_update_tab(), label='데이터 업데이트',
                    tab_id='tab-data-update', label_style={'fontWeight': '600'}),
            dbc.Tab(_dev_updates_tab(), label='개발업데이트 이력',
                    tab_id='tab-dev-updates', label_style={'fontWeight': '600'}),
        ], id='admin-tabs', active_tab='tab-users'),
    ], className='py-4')


# ── 콜백: 사용자 목록 갱신 ────────────────────────────────────────────────────

@callback(
    Output('user-table-body', 'children'),
    Output('user-list-store', 'data'),
    Input('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def refresh_user_table(_counter):
    from services.auth import can, list_users
    if not can('manage_users'):
        return [], []
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
    Output('modal-permissions-section', 'style', allow_duplicate=True),
    Output('modal-permissions', 'value', allow_duplicate=True),
    Output('modal-eval-excluded-depts', 'value', allow_duplicate=True),
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
        [],                 # is_admin: 기본 미부여
        # 새 계정은 역할 기본값을 그대로 따르는 상태(NULL)로 시작 — 개별 권한은
        # 만든 뒤 "수정"에서 조정한다(계정을 만들면서 바로 고정값을 심지
        # 않기 위해, 이 섹션 자체를 새 계정 추가 시에는 숨긴다).
        {'display': 'none'},
        [], [],
        # 비밀번호 입력란은 신규 추가 시 숨기고(관리자가 직접 입력하지 않음
        # — 사용자 확정 2026-08-31), 고정 임시 비밀번호 안내만 보여준다.
        {'display': 'none'},
        f'신규 계정은 임시 비밀번호 "{DEFAULT_TEMP_PASSWORD}"로 생성되며, '
        f'최초 로그인 후 반드시 새 비밀번호로 변경해야 합니다.',
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
    Output('modal-permissions-section', 'style', allow_duplicate=True),
    Output('modal-permissions', 'value', allow_duplicate=True),
    Output('modal-eval-excluded-depts', 'value', allow_duplicate=True),
    Output('modal-password-section', 'style', allow_duplicate=True),
    Output('modal-new-password-note', 'children', allow_duplicate=True),
    Output('user-modal-alert', 'children', allow_duplicate=True),
    Input({'type': 'btn-edit', 'index': ALL}, 'n_clicks'),
    State('user-list-store', 'data'),
    prevent_initial_call=True,
)
def open_edit_modal(n_clicks_list, users):
    from dash import ctx
    from services.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
    n_outputs = 18
    if not any(n for n in n_clicks_list if n):
        return [no_update] * n_outputs
    triggered = ctx.triggered_id
    if triggered is None:
        return [no_update] * n_outputs
    idx = triggered['index']
    if idx >= len(users):
        return [no_update] * n_outputs
    u = users[idx]
    # 체크박스는 "지금 이 계정에 실제로 적용되는 값"을 보여준다 — 개별
    # 재정의(override)가 있으면 그 값, 없으면(None) 역할 기본값(ROLE_PERMISSIONS)을
    # 보여준다. 다만 저장을 누르면(save_user) 항상 명시값으로 고정된다
    # (services/user_store.py update_permissions 독스트링 참고).
    role_defaults = ROLE_PERMISSIONS.get(u.get('role', ''), {})
    overrides = u.get('permissions') or {}
    perm_values = [
        key for key in _PERMISSION_KEYS
        if (overrides.get(key) if overrides.get(key) is not None else role_defaults.get(key, False))
    ]
    return (
        True, '사용자 수정', u['user_id'],
        u['user_id'], True,              # user_id readonly
        u.get('display_name', ''),
        u.get('role', _ROLES[0]['value']),
        u.get('email', ''),
        '', '',
        f'새 비밀번호 (변경 시에만 입력 — {MIN_PASSWORD_LENGTH}~{MAX_PASSWORD_LENGTH}자, 영문/숫자/특수문자 조합)',
        ['admin'] if u.get('is_admin') else [],
        {},
        perm_values,
        list(u.get('eval_excluded_dep_ids') or []),
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
    State('modal-is-admin', 'value'),
    State('modal-permissions', 'value'),
    State('modal-eval-excluded-depts', 'value'),
    State('user-refresh-counter', 'data'),
    prevent_initial_call=True,
)
def save_user(_, editing_id, user_id, display_name, role, email, password, pw_confirm,
              is_admin_value, permissions_value, excluded_depts_value, counter):
    from services.auth import (
        DEFAULT_TEMP_PASSWORD, can, change_password, create_user, get_current_user,
        password_validation_error, update_permissions, update_user,
    )
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
        # 신규 계정은 항상 고정 임시 비밀번호로 시작하고(관리자가 직접
        # 입력하지 않음 — 사용자 확정 2026-08-31) must_change_password=True로
        # 잠근다. 이 값 자체는 비밀번호 정책을 만족하지 않으므로
        # password_validation_error() 검증을 여기서는 건너뛴다 — 정책은
        # 계정 소유자가 최초 로그인 후 본인 비밀번호로 바꿀 때부터 적용된다
        # (app.py의 /change-password, DEFAULT_TEMP_PASSWORD 독스트링 참고).
        try:
            create_user(user_id, DEFAULT_TEMP_PASSWORD, display_name, role, email,
                        must_change_password=True, is_admin=is_admin)
        except ValueError as exc:
            return _alert(str(exc), 'danger'), no_update, no_update
    else:
        current = get_current_user()
        if current and current['user_id'] == editing_id and not is_admin:
            return _alert('자기 자신의 관리자 권한은 해제할 수 없습니다. '
                          '다른 관리자가 대신 해제해야 합니다.', 'warning'), no_update, no_update
        if password:
            password_error = password_validation_error(password)
            if password_error:
                return _alert(password_error, 'warning'), no_update, no_update
            if password != pw_confirm:
                return _alert('비밀번호가 일치하지 않습니다.', 'warning'), no_update, no_update
            change_password(editing_id, password)
        update_user(editing_id, display_name=display_name, role=role, email=email, is_admin=is_admin)
        # 이 모달에서 저장을 누르는 순간 4개 권한 전부 명시값으로 고정된다
        # (역할이 나중에 바뀌어도 유지 — 사용자 확정, services/user_store.py
        # update_permissions 독스트링 참고). 새로 만드는 계정(is_new)은 이
        # 섹션 자체가 숨겨져 있어 여기로 오지 않는다 — 역할 기본값을 그대로
        # 따르는 상태(NULL)로 남는다.
        permissions_value = permissions_value or []
        permissions = {key: (key in permissions_value) for key in _PERMISSION_KEYS}
        update_permissions(editing_id, permissions, excluded_depts_value or [])

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


# ── 콜백: 과제 전문성 분석 리포트 메일 발송 ──────────────────────────────────

@callback(
    Output('mail-report-alert', 'children'),
    Input('btn-mail-report', 'n_clicks'),
    State('mail-report-recipients', 'value'),
    prevent_initial_call=True,
)
def send_mail_report(_, recipients_raw):
    from services.auth import can, current_user_mail_default
    if not can('manage_users'):
        return _alert('권한이 없습니다.', 'danger')

    recipients = [addr.strip() for addr in (recipients_raw or '').split(',') if addr.strip()]
    if not recipients:
        # 수신자를 비워두면 로그인한 본인(로그인 ID@samsung.com)에게 보낸다.
        self_mail = current_user_mail_default()
        if not self_mail:
            return _alert('수신자 이메일을 입력하세요.', 'warning')
        recipients = [self_mail]

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
    return _alert(f"리포트를 발송했습니다 ({', '.join(recipients)})", 'success')


# ── 콜백: 팀/리더 참조 — 행 추가 ─────────────────────────────────────────────
# 클릭(선택)해둔 셀이 있으면 그 행 바로 다음에 삽입하고, 선택된 셀이 없으면
# 맨 뒤에 추가한다(사용자 요청: 항상 맨 뒤가 아니라 원하는 위치에 끼워 넣기).
@callback(
    Output('team-refer-table', 'data', allow_duplicate=True),
    Input('team-refer-add-row-btn', 'n_clicks'),
    State('team-refer-table', 'data'),
    State('team-refer-table', 'active_cell'),
    prevent_initial_call=True,
)
def team_refer_add_row(n_clicks, rows, active_cell):
    if not n_clicks:
        return no_update
    rows = list(rows or [])
    new_row = {col: '' for col in team_refer_store.KOREAN_COLUMNS}
    insert_at = active_cell['row'] + 1 if active_cell else len(rows)
    rows.insert(insert_at, new_row)
    return _renumbered(rows)


# ── 콜백: 팀/리더 참조 — 헤더 클릭 정렬(오름차순/내림차순) ────────────────────
# sort_action='custom'이라 DataTable이 데이터를 직접 재정렬하지 않고
# sort_by(정렬 기준)만 갱신한다 — 여기서 실제로 재정렬하고, 'No.' 열도
# 새 순서에 맞게 다시 매긴다("정렬순에 따라 동적으로 맵핑").
@callback(
    Output('team-refer-table', 'data', allow_duplicate=True),
    Input('team-refer-table', 'sort_by'),
    State('team-refer-table', 'data'),
    prevent_initial_call=True,
)
def team_refer_sort(sort_by, rows):
    if not sort_by:
        return no_update
    rows = list(rows or [])
    for spec in reversed(sort_by):
        col = spec['column_id']
        rows.sort(key=lambda r: _sort_key(r.get(col)), reverse=(spec['direction'] == 'desc'))
    return _renumbered(rows)


# ── 콜백: 팀/리더 참조 — 행 삭제 직후 No. 즉시 재번호 ─────────────────────────
# row_deletable(행 삭제)은 DataTable이 클라이언트에서 바로 처리해 data가
# 곧장 줄어드는데, 그때는 team_refer_add_row/team_refer_sort 같은 명시적
# 콜백이 안 걸린다. 그래서 data 자체를 Input으로 지켜보다가 'No.'가 현재
# 순서(1..N)와 어긋나 있으면(=삭제로 빠짐) 바로 다시 매긴다. Output도 같은
# data라 자기 자신을 다시 트리거하지만, 이미 맞게 매겨진 상태에서는
# no_update를 반환해 루프가 멈춘다(idempotent) — 편집(셀 값 변경)처럼
# 순서가 안 바뀌는 변경에서도 한 번 더 불리지만 즉시 no_update로 끝난다.
@callback(
    Output('team-refer-table', 'data', allow_duplicate=True),
    Input('team-refer-table', 'data'),
    prevent_initial_call=True,
)
def team_refer_renumber_on_change(rows):
    if not rows:
        return no_update
    if [r.get('_no') for r in rows] == list(range(1, len(rows) + 1)):
        return no_update
    return _renumbered(list(rows))


# ── 콜백: 팀/리더 참조 — 셀 툴팁을 항상 최신 데이터로 유지 ─────────────────────
# 말줄임(...) 처리된 셀도 마우스를 올리면 전체 내용을 볼 수 있게(사용자
# 확정) — 행 추가/삭제/정렬/편집 등 data를 바꾸는 콜백이 여러 개라 그때마다
# 각자 tooltip_data를 다시 계산하게 하는 대신, data 자체를 지켜보다가 한
# 곳에서만 갱신한다.
@callback(
    Output('team-refer-table', 'tooltip_data'),
    Input('team-refer-table', 'data'),
)
def team_refer_sync_tooltip(rows):
    if not rows:
        return []
    return [{k: str(v) if v is not None else '' for k, v in row.items()} for row in rows]


# ── 콜백: 팀/리더 참조 — 저장 ─────────────────────────────────────────────────
# 행 삭제(row_deletable) 자체는 DataTable이 클라이언트에서 바로 처리하므로
# 별도 저장 로직은 없다 — 저장 시점에 team-refer-loaded-dep-ids(그리드를
# 처음 불러올 때의 부서ID 목록)와 현재 그리드의 부서ID를 비교해 사라진
# 것을 삭제로 판단한다.
@callback(
    Output('team-refer-save-msg', 'children'),
    Output('team-refer-loaded-dep-ids', 'data', allow_duplicate=True),
    Output('team-refer-dupe-modal', 'is_open', allow_duplicate=True),
    Output('team-refer-dupe-modal-body', 'children'),
    Input('team-refer-save-btn', 'n_clicks'),
    State('team-refer-table', 'data'),
    State('team-refer-valid-date', 'date'),
    State('team-refer-loaded-dep-ids', 'data'),
    prevent_initial_call=True,
)
def team_refer_save(n_clicks, rows, valid_date_str, loaded_dep_ids):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 저장할 수 있습니다.', 'danger'), no_update, no_update, no_update
    if not n_clicks:
        return no_update, no_update, no_update, no_update
    if not valid_date_str:
        return _alert('입력 날짜를 선택해주세요.', 'warning'), no_update, no_update, no_update

    valid_date = date.fromisoformat(valid_date_str[:10])
    rows = rows or []

    valid_rows = [r for r in rows if str(r.get('부서ID') or '').strip()]
    skipped = len(rows) - len(valid_rows)

    current_dep_ids = {str(r.get('부서ID')).strip() for r in valid_rows}
    deleted_dep_ids = [d for d in (loaded_dep_ids or []) if d not in current_dep_ids]

    # upper_dep_id(상위부서ID) 존재성 검증 — 저장은 진행하되 경고만 표시한다
    # (build_org_tree()는 존재하지 않는 upper_dep_id를 조용히 최상위로 취급
    # 하므로, 오타를 그냥 두면 트리 구조가 의도와 다르게 만들어질 수 있다).
    warnings = []
    for r in valid_rows:
        updep = str(r.get('상위부서ID') or '').strip()
        if updep and updep not in current_dep_ids:
            warnings.append(f"부서ID {r.get('부서ID')}({r.get('과제/파트', '')})의 상위부서ID "
                             f"'{updep}'가 존재하지 않아 최상위 조직으로 취급됩니다")

    result = team_refer_store.save_snapshot(valid_rows, deleted_dep_ids, valid_date)
    team_refer_store.export_snapshot_xlsx(valid_rows, valid_date)

    parts = [
        f"저장 완료 — 이번 저장 {result['saved_rows']}행 반영"
        + ('' if result['db_ok'] else ' (DB 미반영, CSV에는 반영됨)') + '.',
    ]
    if deleted_dep_ids:
        parts.append(f'{len(deleted_dep_ids)}개 조직이 삭제 처리됐습니다.')
    if skipped:
        parts.append(f'부서ID가 비어 있어 {skipped}행은 저장에서 제외됐습니다.')

    dupes = result.get('duplicate_dep_ids') or []
    if dupes:
        parts.append(f'부서ID가 중복된 항목이 {len(dupes)}건 있어 일부 행이 저장되지 '
                      '않았을 수 있습니다 — 아래 창을 확인해주세요.')

    alert_color = 'warning' if (warnings or dupes) else 'success'
    body = [html.Div(p) for p in parts]
    if warnings:
        body.append(html.Div('경고: ' + ' / '.join(warnings[:5])
                              + (f' 외 {len(warnings) - 5}건' if len(warnings) > 5 else '')))

    msg = dbc.Alert(body, color=alert_color, dismissable=True, className='py-2 small mb-0')
    return msg, sorted(current_dep_ids), bool(dupes), _dupe_modal_body(dupes)


def _dupe_modal_body(dupes: list[dict]):
    """부서ID(dep_id) 중복 그룹 리스트를 별도 창(모달)에 보여줄 표로 렌더링.
    dupes: pipeline.process_team_refer.find_duplicate_dep_ids()의 반환값."""
    if not dupes:
        return None
    header = html.Thead(html.Tr([
        html.Th('부서ID'), html.Th('조직코드'), html.Th('과제/파트'), html.Th('부서'),
        html.Th('상위부서ID'), html.Th('사번'), html.Th('성명'),
    ]))
    body_rows = []
    for g in dupes:
        for row in g['rows']:
            body_rows.append(html.Tr([
                html.Td(g['dep_id'], className='fw-semibold'),
                html.Td(row['dep_code']), html.Td(row['pjt_part_name']), html.Td(row['dep_name']),
                html.Td(row['upper_dep_id']), html.Td(row['researcher_id']), html.Td(row['name']),
            ]))
    return html.Div([
        html.Div(
            f"같은 부서ID를 가진 행이 {len(dupes)}개 부서ID에서 발견됐습니다 — 같은 "
            '부서ID로는 하나만 저장되고 나머지는 사라지니, 부서ID를 다르게 고쳐서 '
            '다시 저장해주세요.',
            className='small text-muted mb-2',
        ),
        dbc.Table([header, html.Tbody(body_rows)], bordered=True, hover=True, size='sm',
                   responsive=True, className='mb-0'),
    ])


@callback(
    Output('team-refer-dupe-modal', 'is_open', allow_duplicate=True),
    Input('team-refer-dupe-modal-close', 'n_clicks'),
    prevent_initial_call=True,
)
def team_refer_close_dupe_modal(n_clicks):
    if not n_clicks:
        return no_update
    return False


# ── 콜백: 데이터 업데이트 — 파일 업로드 ────────────────────────────────────────
@callback(
    Output('data-update-table-container', 'children', allow_duplicate=True),
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Input({'type': 'du-upload', 'key': ALL, 'slot': ALL}, 'contents'),
    State({'type': 'du-upload', 'key': ALL, 'slot': ALL}, 'filename'),
    State({'type': 'du-upload', 'key': ALL, 'slot': ALL}, 'id'),
    prevent_initial_call=True,
)
def data_update_on_upload(all_contents, all_filenames, all_ids):
    from services.auth import can
    if not can('manage_users'):
        return no_update, _alert('관리자만 업로드할 수 있습니다.', 'danger')

    trig = dash.callback_context.triggered_id
    if trig is None:
        return no_update, no_update
    idx = next((i for i, cid in enumerate(all_ids) if cid == trig), None)
    if idx is None or not all_contents[idx]:
        return no_update, no_update

    # needs_valid_date 항목의 대량 백필 업로드는 dcc.Upload(multiple=True)라
    # contents/filename이 리스트로 온다 — 그 외(기존 단일 업로드)는 문자열
    # 그대로 온다. 둘 다 아래에서 같은 방식으로 처리하도록 리스트로 통일한다.
    raw_contents = all_contents[idx]
    raw_filenames = all_filenames[idx]
    if isinstance(raw_contents, list):
        contents_list, filenames_list = raw_contents, raw_filenames
    else:
        contents_list, filenames_list = [raw_contents], [raw_filenames]

    slot = None if trig['slot'] == 'single' else trig['slot']
    ok_count, errors = 0, []
    for filename, contents in zip(filenames_list, contents_list):
        try:
            _header, b64data = contents.split(',', 1)
            file_bytes = base64.b64decode(b64data, validate=True)
        except (ValueError, TypeError):
            errors.append(f'{filename}: 파일을 읽지 못했습니다.')
            continue
        if len(file_bytes) > wpr.MAX_UPLOAD_BYTES:
            limit_mb = wpr.MAX_UPLOAD_BYTES // (1024 * 1024)
            errors.append(f'{filename}: 파일이 너무 큽니다(최대 {limit_mb}MB).')
            continue
        wpr.save_upload(trig['key'], filename, file_bytes, slot=slot)
        ok_count += 1

    if ok_count and not errors:
        msg, color = f'{ok_count}개 파일 업로드 완료.' if ok_count > 1 else f'{filenames_list[0]} 업로드 완료.', 'success'
    elif ok_count and errors:
        msg, color = f'{ok_count}개 업로드 완료, {len(errors)}개 실패({"; ".join(errors[:3])})', 'warning'
    else:
        msg, color = '; '.join(errors[:3]) or '업로드에 실패했습니다.', 'danger'
    return _data_update_table(), _alert(msg, color)


# ── 콜백: 데이터 업데이트 — 전체/선택 실행 ─────────────────────────────────────
@callback(
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input('data-update-all-btn', 'n_clicks'),
    Input('data-update-selected-btn', 'n_clicks'),
    State({'type': 'du-check', 'key': ALL}, 'value'),
    State({'type': 'du-check', 'key': ALL}, 'id'),
    State({'type': 'du-valid-date', 'key': ALL}, 'date'),
    State({'type': 'du-valid-date', 'key': ALL}, 'id'),
    prevent_initial_call=True,
)
def data_update_run(_all_clicks, _sel_clicks, check_values, check_ids, valid_dates, valid_date_ids):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True

    trig = dash.callback_context.triggered_id
    if trig == 'data-update-all-btn':
        keys = wpr.runnable_keys()
        if not keys:
            return _alert('업로드된 파일이 있는 항목이 없습니다.', 'warning'), True
    elif trig == 'data-update-selected-btn':
        keys = [cid['key'] for cid, v in zip(check_ids, check_values) if v]
        if not keys:
            return _alert('선택된 항목이 없습니다.', 'warning'), True
        missing = [k for k in keys if not wpr.has_upload(k)]
        if missing:
            labels = [wpr._BY_KEY[k]['label'] for k in missing]
            return (_alert(f"업로드되지 않은 항목이 선택됐습니다: {', '.join(labels)}"
                            ' — 업로드 후 다시 시도해주세요.', 'warning'), True)
    else:
        return no_update, no_update

    # needs_valid_date 항목(evaluations/tech_ownership/job_profile/work_objective_*)만
    # 화면에 기준 연/월 DatePicker가 렌더링되므로, id-value를 매칭해 그 항목만
    # valid_dates 딕셔너리로 모은다. 지정 안 된 항목은 process_*.py 기본값(오늘).
    valid_dates_by_key = {}
    for cid, d in zip(valid_date_ids, valid_dates):
        if d:
            valid_dates_by_key[cid['key']] = date.fromisoformat(d)

    if not wpr.start_run(keys, valid_dates=valid_dates_by_key):
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False
    return (_alert(f'{len(keys)}개 항목 실행을 시작했습니다. 브라우저를 닫아도 서버에서 계속 '
                    '진행되며, 화면은 자동으로 갱신됩니다.', 'info'), False)


# ── 콜백: 데이터 업데이트 — 항목별 "API로 가져오기" 아이콘 ─────────────────────
# 사내 API 연동은 아직 없다(services/web_pipeline_runner.py의 register_api_fetch()
# 참고) — 지금 눌러도 파일 업로드 실행과 완전히 같은 경로(락/로그/폴링)를 타되,
# 실행결과 칸에 "아직 연동되지 않음"이 그대로 표시된다. 연동을 붙이는 시점에
# register_api_fetch()만 호출하면 이 아이콘이 화면 변경 없이 바로 동작한다.
@callback(
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input({'type': 'du-api', 'key': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def data_update_run_via_api(n_clicks_list):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True

    trig = dash.callback_context.triggered_id
    if not trig or not any(n_clicks_list):
        return no_update, no_update

    key = trig['key']
    if not wpr.start_run_via_api([key]):
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False
    return _alert(f"{wpr._BY_KEY[key]['label']} 항목의 API 연동을 시도합니다.", 'info'), False


# ── 콜백: 데이터 업데이트 — DB 반영 ────────────────────────────────────────────
@callback(
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input('data-update-db-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def data_update_db_load(n_clicks):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True
    if not n_clicks:
        return no_update, no_update
    if not wpr.start_db_load():
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False
    return _alert('DB 반영을 시작했습니다. 완료되면 아래 상태가 갱신됩니다.', 'info'), False


# ── 콜백: 데이터 업데이트 — 진행 상황 폴링(브라우저를 새로 열어도 최신 상태) ────
@callback(
    Output('data-update-table-container', 'children', allow_duplicate=True),
    Output('data-update-db-status', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input('data-update-interval', 'n_intervals'),
    prevent_initial_call=True,
)
def data_update_poll(_n):
    return _data_update_table(), _db_status_view(), not wpr.any_running()


# ── 콜백: 데이터 업데이트 — "이전 Data" 다운로드 ───────────────────────────────
@callback(
    Output('data-update-download', 'data'),
    Input({'type': 'du-download', 'key': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def data_update_download(_n_clicks_list):
    trig = dash.callback_context.triggered_id
    if not trig:
        return no_update
    files = wpr.uploaded_files(trig['key'])
    if not files:
        return no_update
    path = max(files, key=os.path.getmtime)
    return dcc.send_file(path)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _alert(msg: str, color: str):
    return dbc.Alert(msg, color=color, dismissable=True, className='py-2 small mb-0')
