"""
화면 2: 연구원 개별 프로필
"""

from datetime import datetime

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, clientside_callback, dcc, html, no_update

from components import profile_print
from components.detail_tabs import llm_summary_block, owned_expertise_block
from components.profile_sections import (
    avatar,
    award_block,
    comments_block,
    education_block,
    evaluation_incentive_block,
    leadership_figure,
    leadership_year_options,
    nurturing_block,
    photo_block,
)
from components.timeline_view import timeline_view
from services.comments import upsert_comment
from services.data_store import (
    filter_current,
    read_expertise_profiles,
    read_processed,
    read_profile_tables,
    read_similar_researchers,
)
from services.evaluations import evaluation_years

dash.register_page(
    __name__,
    path='/',
    name='연구원 프로필',
    title='연구원 개별 프로필',
)

CURRENT_YEAR = datetime.now().year

# 좌(사진+정보 / 보유 전문성 / 인물 코멘트·리더십, 세로 스택)/우(타임라인) 영역의
# 절대 높이 — 좌측 3블록 합계와 우측 타임라인 카드 높이가 같아 하단이 맞도록 한다.
# 블록마다 각각 고정 높이를 갖고, 넘치는 내용은 내부 스크롤로 처리.
PHOTO_INFO_HEIGHT = 350
TABS_SECTION_HEIGHT = 350
COMMENTS_HEIGHT = 400
SECTION_HEIGHT = PHOTO_INFO_HEIGHT + TABS_SECTION_HEIGHT + COMMENTS_HEIGHT
TABS_CONTENT_HEIGHT = 260

# 우측 타임라인 카드 맨 위에 얹는 LLM 요약 블록의 고정 높이. 나머지는 타임라인이
# flex:1로 채운다(SECTION_HEIGHT 총합 자체는 바꾸지 않아 좌측 스택과 하단이 계속 맞음).
LLM_SUMMARY_HEIGHT = 150


def _locked_block(label: str = ''):
    """접근 권한 없음 플레이스홀더."""
    return html.Div(
        [
            html.I(className='bi bi-lock-fill me-2 text-secondary'),
            html.Span(
                f'{label} — 접근 권한이 없습니다.' if label else '접근 권한이 없습니다.',
                className='text-muted small',
            ),
        ],
        className='text-center py-3',
    )


def _opt(row):
    dept = str(row.get('department', '') or '').strip()
    org = str(row.get('org_code', '') or '').strip()
    tag = ' · '.join(v for v in (dept, org) if v)
    tag_suffix = f' [{tag}]' if tag else ''
    not_current = str(row.get('is_current', 'Y')) == 'N'
    suffix = ' — 현재 미소속' if not_current else ''
    return {
        'label': f'{row["name"]}{tag_suffix}  ({row["researcher_id"]}) — {row["position"]}{suffix}',
        'value': row['researcher_id'],
    }


def _load_selector_data(current_only: bool = True):
    """current_only=True(최신기준)면 현재 소속자만, False(누적기준)면 전배·퇴사
    등으로 최신 인력현황에 없는 사람까지 전부 포함해 검색 옵션을 만든다.
    dept_opts(조직 드롭다운)는 항상 전체(all-time) 부서 목록으로 만들어 모드가
    바뀌어도 그 자체는 다시 계산할 필요가 없게 한다."""
    try:
        full_df = read_processed('researchers').sort_values(['department', 'name'])
        if full_df.empty:
            return [], [], {}
        res_df = filter_current(full_df, current_only)

        all_opts = [_opt(row) for _, row in res_df.iterrows()]
        by_dept = {
            dept: [_opt(row) for _, row in grp.iterrows()]
            for dept, grp in res_df.groupby('department', sort=True)
        }
        dept_opts = [{'label': '전체', 'value': ''}] + [
            {'label': d, 'value': d} for d in sorted(full_df['department'].dropna().unique()) if d
        ]
        return dept_opts, all_opts, by_dept
    except Exception:
        return [], [], {}


def layout(id=None, **_kwargs):
    from services.auth import can
    show_eval = can('view_evaluation')
    show_comments = can('view_comments')

    default_mode = 'current'
    dept_opts, all_opts, by_dept = _load_selector_data(current_only=True)
    default_rid = all_opts[0]['value'] if all_opts else None
    default_dept = ''
    res_opts = all_opts

    if id is not None:
        # 딥링크로 들어온 id가 최신기준 목록에 없으면(예: 연구원 명단 누적기준
        # 화면에서 미소속자를 클릭해 넘어온 경우) 누적기준으로 다시 찾아본다 —
        # 안 그러면 그 사람 대신 엉뚱한 첫 번째 사람이 열린다.
        if not any(o['value'] == id for o in all_opts):
            dept_opts, all_opts, by_dept = _load_selector_data(current_only=False)
            if any(o['value'] == id for o in all_opts):
                default_mode = 'all'
        if any(o['value'] == id for o in all_opts):
            default_rid = id
            try:
                res_df = read_processed('researchers')
                match = res_df[res_df['researcher_id'] == id]
                if not match.empty:
                    default_dept = str(match.iloc[0].get('department', ''))
                    res_opts = by_dept.get(default_dept, all_opts)
            except Exception:
                pass

    return html.Div([
        html.Div([
            dbc.Row([
                dbc.Col(
                    html.H5(
                        [html.I(className='bi bi-person-badge-fill me-2 text-primary'), '연구원 개별 프로필'],
                        className='fw-bold mb-0 mt-1',
                    ),
                    className='d-flex align-items-center',
                ),
                dbc.Col(
                    dbc.Button(
                        [html.I(className='bi bi-printer me-1'), '인쇄 / PDF 출력'],
                        id='print-open-btn', color='secondary', outline=True, size='sm',
                        className='float-end',
                    ),
                    className='d-flex align-items-center justify-content-end',
                ),
            ], className='mb-3'),
            _selector_card(dept_opts, res_opts, default_dept, default_rid, default_mode),
            dbc.Row([
                _left_stack_col(show_eval, show_comments),
                _right_column(),
            ], className='g-3 mb-3'),
        ], className='no-print'),
        _print_modal(show_eval, show_comments),
        html.Div(id='print-sheet-container'),
        dcc.Store(id='print-fire', data=0),
        html.Div(id='print-fire-sink', style={'display': 'none'}),
    ])


def _print_modal(show_eval: bool, show_comments: bool):
    """출력 항목 선택 모달 — 상단(인사정보)/하단(전문성 이력) 체크리스트.
    평가·인물 코멘트는 열람 권한이 있을 때만 선택지로 노출한다(선택지 자체를
    숨기는 것과 별개로, handle_print_modal 콜백에서도 서버단에서 한 번 더
    권한을 재확인한다 — 클라이언트가 보낸 체크값을 그대로 믿지 않음)."""
    personnel_options = [
        {'label': label, 'value': key}
        for key, label, perm in profile_print.PERSONNEL_FIELDS
        if perm is None
        or (perm == 'view_evaluation' and show_eval)
        or (perm == 'view_comments' and show_comments)
    ]
    expertise_options = [{'label': label, 'value': key} for key, label, _perm in profile_print.EXPERTISE_FIELDS]
    default_personnel = [k for k in profile_print.DEFAULT_PERSONNEL
                          if any(o['value'] == k for o in personnel_options)]

    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle('인쇄 / PDF 출력 항목 선택')),
        dbc.ModalBody([
            dbc.Label('상단 — 인사정보', className='fw-semibold small text-muted mb-2'),
            dbc.Checklist(id='print-personnel-check', options=personnel_options,
                          value=default_personnel, switch=True, className='mb-3'),
            dbc.Label('하단 — 전문성 이력', className='fw-semibold small text-muted mb-2'),
            dbc.Checklist(id='print-expertise-check', options=expertise_options,
                          value=list(profile_print.DEFAULT_EXPERTISE), switch=True),
        ]),
        dbc.ModalFooter([
            dbc.Button('취소', id='print-cancel-btn', color='secondary', outline=True, size='sm'),
            dbc.Button([html.I(className='bi bi-printer me-1'), '출력'],
                       id='print-generate-btn', color='primary', size='sm'),
        ]),
    ], id='print-modal', is_open=False, size='lg', className='no-print')


def _selector_card(dept_opts, res_opts, default_dept, default_rid, default_mode='current'):
    return dbc.Card(
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    dbc.Label('검색 기준', className='fw-semibold small text-muted mb-1'),
                    dbc.RadioItems(
                        id='profile-search-mode',
                        options=[
                            {'label': '최신기준', 'value': 'current'},
                            {'label': '누적기준', 'value': 'all'},
                        ],
                        value=default_mode,
                        inline=True,
                        className='small',
                    ),
                ], width='auto'),
                dbc.Col([
                    dbc.Label('조직', className='fw-semibold small text-muted mb-1'),
                    dcc.Dropdown(
                        id='dept-select',
                        options=dept_opts,
                        value=default_dept or None,
                        clearable=True,
                        placeholder='전체',
                        style={'minWidth': '200px'},
                    ),
                ], width='auto'),
                dbc.Col([
                    dbc.Label('연구원  (이름 · 사번 검색)', className='fw-semibold small text-muted mb-1'),
                    dcc.Dropdown(
                        id='researcher-select',
                        options=res_opts,
                        value=default_rid,
                        clearable=False,
                        placeholder='이름 또는 사번으로 검색...',
                        style={'minWidth': '380px'},
                    ),
                ]),
            ], align='end', className='g-3'),
            html.Div(id='profile-current-status', className='small mt-2'),
            html.Div([
                html.Span('최근 검색', className='small fw-semibold text-muted me-2'),
                html.Div(id='researcher-history-chips', className='d-inline-flex flex-wrap'),
            ], className='mt-2 d-flex align-items-center flex-wrap'),
            # storage_type='local' — 브라우저 localStorage에 저장돼 새로고침/재방문
            # 후에도 남는다(로그인 체계가 없어 "나"는 이 브라우저 하나로 구분).
            dcc.Store(id='researcher-search-history', storage_type='local', data=[]),
        ]),
        className='mb-3 shadow-sm',
    )


def _left_stack_col(show_eval: bool = True, show_comments: bool = True):
    """사진+정보 / 보유 전문성 / 인물 코멘트·리더십 카드를 세로로 쌓은 왼쪽 묶음.
    셋 다 각각 절대값(PHOTO_INFO_HEIGHT / TABS_SECTION_HEIGHT / COMMENTS_HEIGHT,
    합계 SECTION_HEIGHT)으로 높이를 고정해, 오른쪽 타임라인 카드(전체 높이를 씀)와
    하단이 맞도록 한다. 넘치는 내용은 내부 스크롤."""
    return dbc.Col(
        html.Div([
            html.Div(_photo_info_card(show_eval),
                     style={'flex': '0 0 auto', 'height': f'{PHOTO_INFO_HEIGHT}px', 'overflow': 'hidden'}),
            html.Div(_owned_expertise_stack_card(),
                     style={'flex': '0 0 auto', 'height': f'{TABS_SECTION_HEIGHT}px', 'overflow': 'hidden'}),
            html.Div(_comments_card(show_comments),
                     style={'flex': '0 0 auto', 'height': f'{COMMENTS_HEIGHT}px', 'overflow': 'hidden'}),
        ], style={'height': f'{SECTION_HEIGHT}px', 'display': 'flex', 'flexDirection': 'column'}),
        md=6,
    )


def _photo_info_card(show_eval: bool = True):
    """사진(좌) + 학력/평가·인센티브/양성/시상(우) 정보를 세로선으로 구분한 하나의 카드."""
    return dbc.Card(
        dbc.CardBody(
            dbc.Row([
                dbc.Col(
                    html.Div(id='photo-block', className='d-flex flex-column align-items-center py-1'),
                    md=4, className='p-2',
                ),
                dbc.Col([
                    html.P('학력', className='section-label'),
                    html.Div(id='education-block'),
                    html.Hr(className='my-2'),
                    html.Div([
                        html.I(
                            className='bi bi-lock-fill me-1 text-secondary',
                            style={} if not show_eval else {'display': 'none'},
                        ),
                        html.Span('평가 / 인센티브 이력', className='section-label mb-0'),
                    ]),
                    html.Div(id='eval-incentive-block'),
                    html.Hr(className='my-2'),
                    html.P('양성 이력', className='section-label'),
                    html.Div(id='nurturing-block'),
                    html.Hr(className='my-2'),
                    html.P('시상 이력', className='section-label'),
                    html.Div(id='award-block'),
                ], md=8, className='p-3 border-start',
                   style={'maxHeight': f'{PHOTO_INFO_HEIGHT - 40}px', 'overflowY': 'auto'}),
            ], className='g-0 h-100'),
        ),
        className='shadow-sm profile-card h-100',
    )


def _owned_expertise_stack_card():
    return dbc.Card(
        dbc.CardBody([
            html.P('보유 전문성', style={'fontSize': '0.85rem', 'fontWeight': 600,
                                      'color': '#1d1d1f'}, className='mb-2'),
            html.Div(id='tab-expertise', style={'maxHeight': f'{TABS_CONTENT_HEIGHT}px', 'overflowY': 'auto'}),
        ]),
        className='shadow-sm profile-card h-100',
    )


def _right_column():
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.Div([
                    html.P('전문성 요약(LLM)', style={'fontSize': '0.85rem', 'fontWeight': 600,
                                            'color': '#1d1d1f'}, className='mb-1'),
                    html.Div(id='llm-summary-block', style={'maxHeight': f'{LLM_SUMMARY_HEIGHT - 28}px',
                                                             'overflowY': 'auto'}),
                ], style={'flex': '0 0 auto', 'height': f'{LLM_SUMMARY_HEIGHT}px',
                          'overflow': 'hidden', 'marginBottom': '8px'}),
                html.P('타임라인', style={'fontSize': '0.85rem', 'fontWeight': 600,
                                       'color': '#1d1d1f', 'flex': '0 0 auto'}, className='mb-2'),
                html.Div(id='tab-timeline', style={'flex': '1 1 auto', 'minHeight': '0', 'overflow': 'hidden'}),
            ], style={'height': '100%', 'display': 'flex', 'flexDirection': 'column'}),
            className='shadow-sm profile-card',
            style={'height': f'{SECTION_HEIGHT}px', 'overflow': 'hidden'},
        ),
        md=6,
    )


_COMMENTS_PANE_HEIGHT = COMMENTS_HEIGHT - 70   # 카드 패딩 + 탭 네비게이션 높이만큼 제외


def _comments_card(show_comments: bool = True):
    comments_pane = html.Div([
        html.Div(
            html.I(
                className='bi bi-lock-fill me-1 text-secondary',
                style={} if not show_comments else {'display': 'none'},
            ),
        ),
        html.Div(id='comments-block', style={'maxHeight': '200px', 'overflowY': 'auto'}),
        html.Hr(className='my-2'),
        dbc.Row([
            dbc.Col(
                dcc.Dropdown(
                    id='comment-year',
                    options=[{'label': str(y), 'value': y}
                             for y in range(CURRENT_YEAR, CURRENT_YEAR - 5, -1)],
                    value=CURRENT_YEAR,
                    clearable=False,
                    disabled=not show_comments,
                    style={'minWidth': '100px'},
                ),
                width='auto',
            ),
            dbc.Col(
                dcc.Dropdown(
                    id='comment-author-type',
                    options=[
                        {'label': '부서장', 'value': '부서장'},
                        {'label': '부서원', 'value': '부서원'},
                    ],
                    value='부서장',
                    clearable=False,
                    disabled=not show_comments,
                    style={'minWidth': '100px'},
                ),
                width='auto',
            ),
        ], className='g-2 mb-2'),
        dbc.Textarea(
            id='comment-text',
            placeholder='코멘트를 입력하세요...' if show_comments else '접근 권한이 없습니다.',
            rows=3,
            className='mb-2',
            disabled=not show_comments,
        ),
        dbc.Button(
            '저장',
            id='comment-save-btn',
            color='primary',
            size='sm',
            disabled=not show_comments,
        ),
        html.Div(id='comment-status', className='mt-2 small'),
    ], className='pt-3')

    leadership_pane = html.Div([
        dbc.Row([
            dbc.Col(html.P('타인평균 대비 리더십 진단', className='section-label mb-0')),
            dbc.Col(dcc.Dropdown(id='leadership-year', clearable=False,
                                 style={'width': '110px'}), width='auto'),
        ], align='center', className='mb-1 pt-3'),
        dcc.Graph(id='leadership-chart', style={'height': '260px'},
                  config={'displayModeBar': False}),
    ])

    return dbc.Card(
        dbc.CardBody(
            dbc.Tabs([
                dbc.Tab(comments_pane, label='인물 코멘트 (부서장 · 부서원)', tab_id='comments'),
                dbc.Tab(leadership_pane, label='리더십 진단', tab_id='leadership'),
            ], id='bottom-right-tabs', active_tab='comments'),
            style={'maxHeight': f'{_COMMENTS_PANE_HEIGHT}px', 'overflowY': 'auto'},
        ),
        className='shadow-sm profile-card h-100',
    )


def _card(children, *, body_class='p-2', card_class='shadow-sm profile-card mb-2', body_style=None):
    return dbc.Card(dbc.CardBody(children, className=body_class, style=body_style), className=card_class)


def _empty_profile_output():
    prompt = html.Div('연구원을 선택하세요.', className='text-muted p-3')
    return (
        avatar('?'), html.Div(), html.Div(), html.Div(), html.Div(),
        [], None, html.Div(), prompt, prompt, prompt, html.Div(),
    )


def _current_status_badge(researcher):
    """researchers.csv의 is_current/valid_year/valid_month로 "현재 미소속" 배지를
    만든다. is_current 컬럼이 없거나 'N'이 아니면(현재 소속이거나 판단 불가) 빈
    Div — 화면에 아무것도 안 보인다."""
    is_current = str(researcher.get('is_current', 'Y'))
    if is_current != 'N':
        return html.Div()
    yr = str(researcher.get('valid_year', '') or '').strip()
    mo = str(researcher.get('valid_month', '') or '').strip()
    period = f' (마지막 확인: {yr}-{mo})' if yr and mo else ''
    return dbc.Alert(
        f'현재 미소속(최신 인력현황에 없음){period} — 누적기준 검색으로 조회된 이력입니다.',
        color='secondary', className='py-1 px-2 mb-0 d-inline-block',
    )


@callback(
    Output('researcher-select', 'options'),
    Output('researcher-select', 'value'),
    Input('dept-select', 'value'),
    Input('profile-search-mode', 'value'),
    State('researcher-select', 'value'),
    prevent_initial_call=True,
)
def filter_by_dept(dept, mode, current_rid):
    _, all_opts, by_dept = _load_selector_data(current_only=(mode != 'all'))
    opts = by_dept.get(dept, all_opts) if dept else all_opts
    valid_ids = {o['value'] for o in opts}
    new_value = current_rid if current_rid in valid_ids else (opts[0]['value'] if opts else None)
    return opts, new_value


_HISTORY_LIMIT = 8  # "최근 검색" 칩 최대 개수(오래된 항목부터 밀려남)


@callback(
    Output('researcher-search-history', 'data'),
    Input('researcher-select', 'value'),
    State('researcher-search-history', 'data'),
    prevent_initial_call=True,
)
def _record_search_history(rid, history):
    """researcher-select 값이 바뀔 때마다(직접 검색이든, 최근 검색 칩 클릭이든)
    그 사람을 이력 맨 앞으로 올린다(이미 있던 항목은 지우고 다시 넣어 중복
    없이 최신순 유지). storage_type='local'이라 브라우저에 남아 새로고침/재방문
    후에도 이어서 볼 수 있다(로그인 체계가 없어 "나" = 이 브라우저)."""
    if not rid:
        return no_update
    history = [h for h in (history or []) if h.get('rid') != rid]
    res_df = read_processed('researchers')
    match = res_df[res_df['researcher_id'] == rid]
    if not match.empty:
        row = match.iloc[0]
        dept = str(row.get('department', '') or '').strip()
        name = str(row.get('name', '') or '') or rid
        label = f'{name} [{dept}]' if dept else name
    else:
        label = rid
    history.insert(0, {'rid': rid, 'label': label})
    return history[:_HISTORY_LIMIT]


@callback(
    Output('researcher-history-chips', 'children'),
    Input('researcher-search-history', 'data'),
)
def _render_history_chips(history):
    history = history or []
    if not history:
        return html.Span('아직 검색 이력이 없습니다.', className='text-muted small')
    return [
        dbc.Badge(
            h['label'], id={'type': 'researcher-history-chip', 'rid': h['rid']},
            color='light', text_color='dark', className='me-1 mb-1 border',
            style={'cursor': 'pointer', 'fontWeight': 'normal'},
        )
        for h in history if h.get('rid')
    ]


@callback(
    Output('dept-select', 'value'),
    Output('researcher-select', 'value', allow_duplicate=True),
    Input({'type': 'researcher-history-chip', 'rid': dash.ALL}, 'n_clicks'),
    State({'type': 'researcher-history-chip', 'rid': dash.ALL}, 'id'),
    prevent_initial_call=True,
)
def _select_from_history(n_clicks_list, ids):
    """"최근 검색" 칩을 누르면 그 사람의 부서로 조직 드롭다운을 같이 옮겨줘야
    (layout()의 id= 딥링크와 동일한 이유로) researcher-select 옵션 목록에 그
    사람이 실제로 들어있는 상태가 된다 — 부서만 안 맞추면 필터링된 옵션에서
    빠져 있어 선택이 무시될 수 있다."""
    triggered_id = dash.ctx.triggered_id
    if not triggered_id:
        return no_update, no_update
    idx = next((i for i, d in enumerate(ids) if d == triggered_id), None)
    if idx is None or not n_clicks_list[idx]:
        return no_update, no_update
    rid = triggered_id['rid']
    res_df = read_processed('researchers')
    match = res_df[res_df['researcher_id'] == rid]
    dept = str(match.iloc[0].get('department', '') or '') if not match.empty else None
    return (dept or None), rid


@callback(
    Output('photo-block', 'children'),
    Output('education-block', 'children'),
    Output('eval-incentive-block', 'children'),
    Output('nurturing-block', 'children'),
    Output('award-block', 'children'),
    Output('leadership-year', 'options'),
    Output('leadership-year', 'value'),
    Output('comments-block', 'children'),
    Output('llm-summary-block', 'children'),
    Output('tab-timeline', 'children'),
    Output('tab-expertise', 'children'),
    Output('profile-current-status', 'children'),
    Input('researcher-select', 'value'),
)
def update_profile(rid):
    import sys
    from services.auth import can, get_current_user

    if get_current_user() is None:
        return _empty_profile_output()

    show_eval = can('view_evaluation')
    show_comments = can('view_comments')

    if not rid:
        return _empty_profile_output()

    try:
        tables = read_profile_tables()
        researchers = tables['researchers']
        if researchers.empty:
            return _empty_profile_output()

        rid = str(rid).zfill(8)
        rows = researchers[researchers['researcher_id'] == rid]
        if rows.empty:
            return _empty_profile_output()
        researcher = rows.iloc[0]
        # 평가등급 표의 연도 열 — evaluations.csv가 생성될 때와 동일한 회계연도
        # 기준(매년 3월 시작, services.evaluations)이어야 CSV의 실제 컬럼과
        # 항상 맞아떨어진다(달력연도 CURRENT_YEAR를 그대로 쓰면 1~2월에 어긋남).
        salary_years, _half_years = evaluation_years()
        years = sorted(salary_years)
        leadership_options, leadership_default = leadership_year_options(tables['leadership'], rid)
        profile = read_expertise_profiles().get(rid)
        similar = read_similar_researchers().get(rid, {}).get('similar', [])
        name_map = researchers.set_index('researcher_id')['name'].to_dict()

        eval_content = (
            evaluation_incentive_block(tables['evaluations'], tables['incentive_selection'], rid, years)
            if show_eval
            else _locked_block()
        )
        comments_content = (
            comments_block(tables['comments'], rid)
            if show_comments
            else _locked_block()
        )

        return (
            photo_block(rid, str(researcher.get('name', '')), researcher, CURRENT_YEAR),
            education_block(tables['education'], rid),
            eval_content,
            nurturing_block(tables['nurturing'], rid),
            award_block(tables['awards'], rid),
            leadership_options,
            leadership_default,
            comments_content,
            llm_summary_block(profile, similar, name_map),
            timeline_view(tables['tasks'], tables['hr_orders'], tables['publications'],
                          tables['patents'], tables['job_profile'], tables['tasks_information'], rid),
            owned_expertise_block(tables['core_technology'], tables['tech_ownership'], rid),
            _current_status_badge(researcher),
        )
    except Exception as exc:
        import traceback
        print(f'[update_profile] ERROR for rid={rid!r}:', file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        err_div = html.Div(
            f'오류 발생: {exc}',
            className='text-danger small p-2',
        )
        return (
            avatar('?'), err_div, html.Div(), html.Div(), html.Div(),
            [], None, html.Div(), err_div, err_div, err_div, html.Div(),
        )


@callback(
    Output('leadership-chart', 'figure'),
    Input('researcher-select', 'value'),
    Input('leadership-year', 'value'),
)
def update_leadership(rid, year):
    rid = str(rid).zfill(8) if rid else rid
    return leadership_figure(read_processed('leadership'), rid, year)


@callback(
    Output('print-modal', 'is_open'),
    Output('print-sheet-container', 'children'),
    Output('print-fire', 'data'),
    Input('print-open-btn', 'n_clicks'),
    Input('print-cancel-btn', 'n_clicks'),
    Input('print-generate-btn', 'n_clicks'),
    State('researcher-select', 'value'),
    State('leadership-year', 'value'),
    State('print-personnel-check', 'value'),
    State('print-expertise-check', 'value'),
    State('print-fire', 'data'),
    prevent_initial_call=True,
)
def handle_print_modal(_open_clicks, _cancel_clicks, _gen_clicks, rid, leadership_year,
                        selected_personnel, selected_expertise, fire_count):
    from services.auth import can

    triggered = dash.ctx.triggered_id
    if triggered == 'print-open-btn':
        return True, no_update, no_update
    if triggered == 'print-cancel-btn':
        return False, no_update, no_update
    if triggered != 'print-generate-btn' or not rid:
        return False, no_update, no_update

    tables = read_profile_tables()
    researchers = tables['researchers']
    rid = str(rid).zfill(8)
    rows = researchers[researchers['researcher_id'] == rid]
    if rows.empty:
        return False, no_update, no_update

    # 클라이언트가 보낸 체크값을 그대로 믿지 않고, 평가/코멘트는 여기서 다시
    # 권한을 확인해 없으면 선택돼 있어도 제외한다.
    show_eval = can('view_evaluation')
    show_comments = can('view_comments')
    selected_personnel = [
        k for k in (selected_personnel or [])
        if not (k == 'evaluation' and not show_eval) and not (k == 'comments' and not show_comments)
    ]

    researcher_row = rows.iloc[0]
    profile = read_expertise_profiles().get(rid)
    similar = read_similar_researchers().get(rid, {}).get('similar', [])
    name_map = researchers.set_index('researcher_id')['name'].to_dict()

    sheet = profile_print.build_print_sheet(
        rid, researcher_row, tables, profile, similar, name_map, leadership_year,
        selected_personnel, selected_expertise or [],
    )
    return False, sheet, (fire_count or 0) + 1


clientside_callback(
    "function(n) { if (n) { window.print(); } return ''; }",
    Output('print-fire-sink', 'children'),
    Input('print-fire', 'data'),
    prevent_initial_call=True,
)


@callback(
    Output('comment-status', 'children'),
    Input('comment-save-btn', 'n_clicks'),
    State('researcher-select', 'value'),
    State('comment-year', 'value'),
    State('comment-author-type', 'value'),
    State('comment-text', 'value'),
    prevent_initial_call=True,
)
def save_comment(n_clicks, rid, year, author_type, text):
    from services.auth import can
    if not can('view_comments'):
        return dbc.Alert('코멘트 작성 권한이 없습니다.',
                         color='warning', className='py-1 px-2 mb-0')
    if not rid or not year or not text or not text.strip():
        return dbc.Alert('연구원, 연도, 코멘트를 모두 입력하세요.',
                         color='warning', className='py-1 px-2 mb-0')
    try:
        upsert_comment(rid, year, author_type, text.strip())
        return dbc.Alert('저장 완료', color='success', className='py-1 px-2 mb-0')
    except Exception as exc:
        return dbc.Alert(f'저장 실패: {exc}', color='danger', className='py-1 px-2 mb-0')
