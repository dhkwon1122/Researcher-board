"""
화면 2: 연구원 개별 프로필
"""

from datetime import date, datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, clientside_callback, dcc, html, no_update

from components.detail_tabs import llm_summary_block, owned_expertise_block
from components.profile_sections import (
    avatar,
    award_block,
    comments_block,
    education_block,
    evaluation_incentive_block,
    evaluation_incentive_summary_text,
    leadership_figure,
    leadership_year_options,
    nurturing_block,
    photo_block,
)
from components.timeline_data import (
    cell,
    count_true,
    count_us_registered,
    dedupe_patents,
    is_registered,
    share_sum,
    task_points,
)
from components.timeline_view import filter_hr_rows, timeline_view
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


def layout(id=None, ids=None, **_kwargs):
    if ids:
        return _bulk_layout(ids)

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
        dbc.Row([
            dbc.Col(
                html.H5(
                    [html.I(className='bi bi-person-badge-fill me-2 text-primary'), '연구원 개별 프로필'],
                    className='fw-bold mb-0 mt-1',
                ),
            ),
            dbc.Col(
                html.Button(
                    [html.I(className='bi bi-printer me-1'), '프로필 인쇄 (A4)'],
                    id='profile-print-btn', n_clicks=0,
                    className='btn btn-outline-secondary btn-sm',
                ),
                width='auto', className='d-flex align-items-center',
            ),
        ], justify='between', align='center', className='mb-3 no-print'),
        html.Div(id='profile-print-dummy', style={'display': 'none'}),
        html.Div([
            _selector_card(dept_opts, res_opts, default_dept, default_rid, default_mode),
            dbc.Row([
                _left_stack_col(show_eval, show_comments),
                _right_column(),
            ], className='g-3 mb-3'),
        ], className='no-print'),
        html.Div(id='profile-print-content', className='profile-print-only'),
    ])


def _bulk_layout(ids_param):
    """연구원 명단 화면(과제/부서로 필터한 결과 전체, 또는 체크박스로 고른
    임의의 인원 풀)에서 "/?ids=00000001,00000002,..." 형태로 넘어온 다인
    일괄 인쇄 화면. 단일 프로필 화면과 달리 조회용 대시보드는 보여주지
    않고, 각자의 인쇄 콘텐츠(_build_print_block)를 인원 수만큼 이어붙여
    한 사람당 A4 1장씩 인쇄되게 한다(마지막 사람 뒤에는 break를 넣지
    않아 끝에 빈 페이지가 붙지 않는다)."""
    rid_list = []
    seen = set()
    for token in str(ids_param).split(','):
        token = token.strip()
        if not token:
            continue
        rid = token.zfill(8)
        if rid not in seen:
            seen.add(rid)
            rid_list.append(rid)

    researchers = read_processed('researchers')
    labels = []
    for rid in rid_list:
        match = researchers[researchers['researcher_id'] == rid] if not researchers.empty else pd.DataFrame()
        name = str(match.iloc[0].get('name', '')) if not match.empty else ''
        labels.append(f'{name}({rid})' if name else rid)

    return html.Div([
        dbc.Row([
            dbc.Col(
                html.H5(
                    [html.I(className='bi bi-people-fill me-2 text-primary'),
                     f'연구원 프로필 일괄 인쇄 ({len(rid_list)}명)'],
                    className='fw-bold mb-0 mt-1',
                ),
            ),
            dbc.Col(
                html.Button(
                    [html.I(className='bi bi-printer me-1'), '프로필 인쇄 (A4)'],
                    id='profile-print-btn', n_clicks=0,
                    className='btn btn-outline-secondary btn-sm',
                ),
                width='auto', className='d-flex align-items-center',
            ),
        ], justify='between', align='center', className='mb-3 no-print'),
        html.Div(id='profile-print-dummy', style={'display': 'none'}),
        html.Div([
            dbc.Alert([
                html.Div(f'{len(rid_list)}명의 프로필을 한 번에 인쇄합니다 (1인당 A4 1페이지, 사람마다 페이지가 나뉩니다).'),
                html.Div(', '.join(labels), className='small text-muted mt-1'),
            ], color='info', className='mb-3'),
            dcc.Link([html.I(className='bi bi-arrow-left me-1'), '연구원 명단으로 돌아가기'],
                     href='/researcher-list', className='small'),
        ], className='no-print'),
        dcc.Store(id='bulk-print-ids', data=rid_list),
        html.Div(id='profile-print-content', className='profile-print-only'),
    ])


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
        [], None, html.Div(), prompt, prompt, prompt, html.Div(), html.Div(),
    )


_PRINT_BOX_BORDER = '1px solid #1d1d1f'
_TASK_HR_RECENT_LIMIT = 10  # 과제 수행 + 인사 발령 합쳐서 인쇄본에 보여줄 최신 건수


def _print_box(title, children, *, breakable: bool = False):
    """A4 인쇄용 프로필의 테두리 박스 하나(피플팀이 준 손그림 양식 참고) — 왼쪽
    위에 굵은 제목, 그 아래 내용. breakable=False(기본)면 박스 도중에 페이지가
    갈라지지 않게 하고(assets/custom.css의 .print-section), 과제수행/인사발령
    이력처럼 길어질 수 있는 박스는 breakable=True로 페이지 경계에서 자연스럽게
    이어지게 한다."""
    body = [html.Div(title, className='fw-bold mb-2', style={'fontSize': '0.82rem'})] if title else []
    body.append(children)
    cls = 'print-box' + ('' if breakable else ' print-section')
    return html.Div(body, className=cls, style={'border': _PRINT_BOX_BORDER, 'borderRadius': '6px',
                                                  'padding': '10px 12px', 'marginBottom': '10px'})


def _print_box_cols(items):
    """_print_box 안에서 세로 구분선으로 나뉜 가로 단(예: 핵심기술 | 보유기술 |
    전문성 요약)을 만든다. items: [(flex_ratio, content), ...]. display:flex를
    Bootstrap의 .d-flex 유틸리티 클래스가 아니라 인라인 style로 직접 줘서,
    외부 CDN(부트스트랩) 로드 여부와 무관하게 항상 가로로 배치되게 한다."""
    cols = []
    for i, (ratio, content) in enumerate(items):
        style = {'flex': f'{ratio} {ratio} 0', 'minWidth': '0'}
        if i > 0:
            style.update({'borderLeft': '1px solid #d2d2d7', 'marginLeft': '10px', 'paddingLeft': '10px'})
        cols.append(html.Div(content, style=style))
    return html.Div(cols, style={'display': 'flex', 'alignItems': 'stretch'})


def _current_task_label(task_df, rid) -> str:
    """헤더의 "과제" 필드 — 진행중(종료일 없음)인 과제 중 가장 최근 시작 건을
    우선, 없으면 가장 최근에 시작한 과제명을 보여준다(components.timeline_data.
    task_points()가 이미 30일 이하 단기 참여 제외 등 화면 타임라인과 동일한
    필터를 적용해준다)."""
    filtered = task_df[task_df['researcher_id'] == rid] if not task_df.empty else task_df
    points = task_points(filtered) if filtered is not None else []
    if not points:
        return '-'
    ongoing = [p for p in points if p['end_label'] == '진행중']
    chosen = ongoing[-1] if ongoing else points[-1]
    return chosen['task_name'] or '-'


def _tenure_value(hire_date_str: str) -> str:
    """"X.X년 (YYYY년 MM월 DD일 입사)" — components/profile_sections.py의
    photo_block()과 동일한 근속연수 계산((오늘 - 입사일)/365, 소수 첫째자리).
    기본정보 표의 "근속" 행 값으로 쓴다(레이블은 표에서 따로 붙는다)."""
    s = str(hire_date_str or '').strip()
    if not s or s.lower() in ('nan', 'none', 'nat'):
        return '정보 없음'
    try:
        hd = date.fromisoformat(s[:10])
    except ValueError:
        return '정보 없음'
    tenure = round((date.today() - hd).days / 365, 1)
    return f'{tenure}년 ({hd.year}년 {hd.month:02d}월 {hd.day:02d}일 입사)'


def _print_task_hr_timeline(task_df, hr_df, rid, *, limit: int | None = None):
    """과제 수행 이력과 인사 발령 이력을 표/섹션은 물론 "과제"/"인사발령" 같은
    구분자도 없이 하나의 시계열 목록으로 합쳐 날짜 내림차순으로 보여준다(각
    줄의 내용 자체로 무엇인지 알아볼 수 있다는 전제). limit이 주어지면 둘을
    합친 목록 기준으로 최신 limit건만 담고, 잘린 나머지 건수를 안내한다."""
    filtered_task = task_df[task_df['researcher_id'] == rid] if not task_df.empty else task_df
    task_entries = task_points(filtered_task) if filtered_task is not None else []
    hr_rows = filter_hr_rows(hr_df, rid)  # 이미 order_date 내림차순

    def _c(v):
        s = str(v).strip() if v is not None else ''
        return s if s and s.lower() not in ('nan', 'none', 'nat', '-') else ''

    entries = []
    for t in task_entries:
        end = t['end_label'] if t['end_label'] == '진행중' else t['end_label'][:7]
        entries.append({
            'date': t['start'],
            'text': f"{t['start_label'][:7]} ~ {end}  {t['task_name']}",
        })
    for _, row in hr_rows.iterrows():
        d = pd.to_datetime(row.get('order_date'), errors='coerce')
        if pd.isna(d):
            continue
        detail = ' / '.join(p for p in (_c(row.get('order_dep')), _c(row.get('order_cl')),
                                         _c(row.get('order_assignment'))) if p)
        text = f"{d.date().isoformat()}  {_c(row.get('order_name')) or '-'}"
        if detail:
            text += f" ({detail})"
        entries.append({'date': d, 'text': text})

    entries.sort(key=lambda e: e['date'], reverse=True)
    total = len(entries)
    if limit:
        entries = entries[:limit]

    if not entries:
        return html.Div('과제 수행 / 인사 발령 이력 없음', className='text-muted small')

    result = html.Ul([html.Li(e['text'], className='small') for e in entries], className='ps-3 mb-0')
    if limit and total > limit:
        return html.Div([result, html.Div(f'외 {total - limit}건 더', className='text-muted small mt-1')])
    return result


def _print_publication_summary(pub_df, rid):
    """논문 실적 요약 — components/detail_tabs.py의 publications_tab()과 같은
    집계(총 논문 수/교신저자 수)만 "논문 실적 ~건" 한 줄로 보여주고, 개별 논문
    목록(제목/게재처 등 세부 내역)과 별도 소제목은 인쇄본에서는 생략한다."""
    pub = pub_df[pub_df['researcher_id'] == rid] if not pub_df.empty else pub_df
    if pub is None or pub.empty:
        return html.Div('논문 실적 없음', className='small')
    total = len(pub)
    corr = int(pub.get('is_corresponding', pd.Series(dtype=str)).astype(str).str.lower()
               .isin(['true', '1', 'y', 'yes']).sum())
    return html.Div(f'논문 실적 {total}건 (교신저자 {corr}건)', className='small')


def _print_patent_summary(pat_df, rid):
    """특허 실적 요약 — components/detail_tabs.py의 patents_tab()과 같은
    집계(전체/등록/대표발명/전략출원/미국등록/지분율합계)만 "특허 실적 ~건" 한
    줄로 보여주고, 개별 특허 목록(발명 명칭 등 세부 내역)과 별도 소제목은
    인쇄본에서는 생략한다."""
    pat = pat_df[pat_df['researcher_id'] == rid] if not pat_df.empty else pat_df
    if pat is None or pat.empty:
        return html.Div('특허 실적 없음', className='small')
    pat_dedup = dedupe_patents(pat)
    total_cnt = len(pat_dedup)
    reg_cnt = int(pat_dedup['status'].apply(is_registered).sum()) if 'status' in pat_dedup.columns else 0
    lead_cnt = count_true(pat_dedup, 'is_lead_inventor')
    strat_cnt = int((pat_dedup.get('patent_grade_a_sub', pd.Series(dtype=str)).astype(str).str.strip()
                     == '전략출원').sum())
    us_reg_cnt = count_us_registered(pat_dedup)
    share_sum_val = share_sum(pat_dedup)
    return html.Div(
        f'특허 실적 {total_cnt}건 (등록 {reg_cnt} · 출원중 {total_cnt - reg_cnt}) · '
        f'대표발명 {lead_cnt}건 · 전략출원 {strat_cnt}건 · 미국등록 {us_reg_cnt}건 · 지분율 합계 {share_sum_val}',
        className='small',
    )


_PRINT_TABLE_TH_STYLE = {'padding': '3px 6px', 'borderBottom': f'1px solid {_PRINT_BOX_BORDER.split()[-1]}',
                          'textAlign': 'left', 'fontWeight': '600', 'whiteSpace': 'nowrap'}
_PRINT_TABLE_TD_STYLE = {'padding': '3px 6px', 'borderBottom': '1px solid #d2d2d7', 'verticalAlign': 'top'}


def _year_label(row, year_col='pub_year', date_col='pub_date'):
    """연도를 "2025.0" 같은 소수점 없이 "2025"로 표시한다 — CSV 값이 실수
    (float64)로 읽혀도(결측 섞인 컬럼이 pandas에서 float로 캐스팅되는 흔한
    사례) int로 정리해 텍스트로 보여준다."""
    y = row.get(year_col, '')
    try:
        if y not in (None, '') and not (isinstance(y, float) and pd.isna(y)):
            return str(int(float(y)))
    except (TypeError, ValueError):
        pass
    d = str(row.get(date_col, '') or '')[:4]
    return d if d.isdigit() else '-'


def _publication_priority_key(row):
    """1저자(순위 1) 또는 교신저자를 우선(0), 그다음 impact factor 내림차순 —
    실적이 많을 때 "최근순"이 아니라 대표 실적 위주로 추리기 위한 정렬 키."""
    r = str(row.get('author_rank', '')).strip()
    is_first_author = r not in ('', 'nan') and r == '1'
    is_corr = str(row.get('is_corresponding', '')).lower() in ('true', '1', 'y', 'yes')
    tier = 0 if (is_first_author or is_corr) else 1
    try:
        impact_factor = float(row.get('impact_factor', 0) or 0)
    except (TypeError, ValueError):
        impact_factor = 0.0
    return (tier, -impact_factor)


def _print_publication_detail_table(pub_df, rid):
    """논문 실적 상세 목록 — components/detail_tabs.py의 publications_tab()과
    같은 컬럼에 IF를 더해 보여준다. 실적이 많으면 1저자/교신저자 및 impact
    factor가 큰 논문 위주로 우선순위를 매겨 정렬한다(최근순이 아닐 수 있음).
    행 수는 여기서 자르지 않고 전부 렌더링한다 — 실제로 몇 건이 한 페이지에
    들어가는지는 제목 줄바꿈 등 실제 렌더링 결과에 달려 있어 서버 쪽에서
    미리 정확히 알 수 없다. 대신 .print-autofit-table 마커를 달아, 인쇄
    버튼을 누를 때(클라이언트사이드 콜백) 실제 렌더링된 높이를 재서 한
    페이지에 안 들어가는 뒤쪽 행을 동적으로 숨기고 "외 N건 더"를 채운다."""
    pub = pub_df[pub_df['researcher_id'] == rid].copy() if not pub_df.empty else pd.DataFrame()
    if pub.empty:
        return html.Div('논문 실적 없음', className='small text-muted')
    pub['_priority'] = pub.apply(_publication_priority_key, axis=1)
    pub = pub.sort_values('_priority')

    rows = []
    for _, row in pub.iterrows():
        is_corr = str(row.get('is_corresponding', '')).lower() in ('true', '1', 'y', 'yes')
        contrib = str(row.get('contribution', '')).strip()
        contrib_label = f'{contrib}%' if contrib and contrib not in ('nan', '') else '-'
        r = str(row.get('author_rank', '')).strip()
        t = str(row.get('total_authors', '')).strip()
        rank_total = f'{r}/{t}' if r and t and r not in ('nan', '') and t not in ('nan', '') else '-'
        try:
            impact_factor = float(row.get('impact_factor', '') or '')
            if_label = f'{impact_factor:.1f}'
        except (TypeError, ValueError):
            if_label = '-'
        rows.append(html.Tr([
            html.Td(_year_label(row), style={**_PRINT_TABLE_TD_STYLE, 'whiteSpace': 'nowrap'}),
            html.Td(cell(row, 'title'), style=_PRINT_TABLE_TD_STYLE),
            html.Td(cell(row, 'journal'), style=_PRINT_TABLE_TD_STYLE),
            html.Td(if_label, style={**_PRINT_TABLE_TD_STYLE, 'textAlign': 'center', 'whiteSpace': 'nowrap'}),
            html.Td(rank_total, style={**_PRINT_TABLE_TD_STYLE, 'textAlign': 'center', 'whiteSpace': 'nowrap'}),
            html.Td('교신' if is_corr else '-',
                    style={**_PRINT_TABLE_TD_STYLE, 'textAlign': 'center', 'whiteSpace': 'nowrap'}),
            html.Td(contrib_label, style={**_PRINT_TABLE_TD_STYLE, 'textAlign': 'center', 'whiteSpace': 'nowrap'}),
        ]))

    table = html.Table([
        html.Thead(html.Tr([
            html.Th('연도', style=_PRINT_TABLE_TH_STYLE),
            html.Th('제목', style=_PRINT_TABLE_TH_STYLE),
            html.Th('게재처', style=_PRINT_TABLE_TH_STYLE),
            html.Th('IF', style={**_PRINT_TABLE_TH_STYLE, 'textAlign': 'center'}),
            html.Th('순위/총수', style={**_PRINT_TABLE_TH_STYLE, 'textAlign': 'center'}),
            html.Th('교신', style={**_PRINT_TABLE_TH_STYLE, 'textAlign': 'center'}),
            html.Th('기여도', style={**_PRINT_TABLE_TH_STYLE, 'textAlign': 'center'}),
        ])),
        html.Tbody(rows, className='print-autofit-body'),
    ], className='print-autofit-table', style={'width': '100%', 'borderCollapse': 'collapse'})
    return html.Div([table, html.Div('', className='print-autofit-note text-muted small mt-1',
                                      style={'display': 'none'})])


def _patent_priority_key(row):
    """전략출원 > 등록 > 출원 순으로 우선하고, 그 안에서는 대표발명(리드
    인벤터)을 우선, 그다음 지분율 내림차순 — 실적이 많을 때 "최근순"이
    아니라 기여도가 높은 특허 위주로 추리기 위한 정렬 키."""
    grade_a = str(row.get('patent_grade_a_sub', '')).strip()
    is_strategic = grade_a == '전략출원'
    status_val = str(row.get('status', ''))
    is_reg = is_registered(status_val)
    tier = 0 if is_strategic else (1 if is_reg else 2)
    lead = str(row.get('is_lead_inventor', '')).strip().lower() in ('y', '1', 'true', 'yes')
    try:
        share = float(row.get('share_ratio', 0) or 0)
    except (TypeError, ValueError):
        share = 0.0
    return (tier, 0 if lead else 1, -share)


def _print_patent_detail_table(pat_df, rid):
    """특허 실적 상세 목록 — components/detail_tabs.py의 patents_tab()과 같은
    컬럼(중복 발명자 등록 dedupe_patents()로 제거)을 보여준다. 실적이 많으면
    전략출원 > 등록 > 출원 순, 그 안에서는 대표발명·지분율이 높은 특허
    위주로 우선순위를 매겨 정렬한다. 행 수는 여기서 자르지 않고 전부
    렌더링한다 — _print_publication_detail_table과 마찬가지로
    .print-autofit-table 마커를 달아 인쇄 시점에 실제 렌더링 높이 기준으로
    동적으로 자른다(발명 명칭 길이에 따라 몇 건이 들어갈지 서버에서는 정확히
    알 수 없음)."""
    pat = pat_df[pat_df['researcher_id'] == rid].copy() if not pat_df.empty else pd.DataFrame()
    if pat.empty:
        return html.Div('특허 실적 없음', className='small text-muted')
    pat_dedup = dedupe_patents(pat)
    pat_dedup['_priority'] = pat_dedup.apply(_patent_priority_key, axis=1)
    pat_dedup = pat_dedup.sort_values('_priority')

    rows = []
    for _, row in pat_dedup.iterrows():
        status_val = str(row.get('status', ''))
        status_label = '등록' if is_registered(status_val) else (status_val or '출원')
        grade_a = str(row.get('patent_grade_a_sub', '')).strip()
        if grade_a == '전략출원':
            status_label += '(전략)'
        lead = str(row.get('is_lead_inventor', ''))
        lead_label = '대표' if lead in ('Y', 'y', '1', 'True', 'true') else '-'
        share_val = row.get('share_ratio', '')
        share_str = f'{share_val}%' if str(share_val).replace('.', '').isdigit() else '-'
        date_label = cell(row, 'application_date')[:7]
        rows.append(html.Tr([
            html.Td(date_label, style={**_PRINT_TABLE_TD_STYLE, 'whiteSpace': 'nowrap'}),
            html.Td(cell(row, 'title', 'title_ko'), style=_PRINT_TABLE_TD_STYLE),
            html.Td(status_label, style={**_PRINT_TABLE_TD_STYLE, 'textAlign': 'center', 'whiteSpace': 'nowrap'}),
            html.Td(lead_label, style={**_PRINT_TABLE_TD_STYLE, 'textAlign': 'center', 'whiteSpace': 'nowrap'}),
            html.Td(share_str, style={**_PRINT_TABLE_TD_STYLE, 'textAlign': 'center', 'whiteSpace': 'nowrap'}),
            html.Td(cell(row, 'country'), style={**_PRINT_TABLE_TD_STYLE, 'whiteSpace': 'nowrap'}),
        ]))

    table = html.Table([
        html.Thead(html.Tr([
            html.Th('출원일', style=_PRINT_TABLE_TH_STYLE),
            html.Th('발명 명칭', style=_PRINT_TABLE_TH_STYLE),
            html.Th('상태', style={**_PRINT_TABLE_TH_STYLE, 'textAlign': 'center'}),
            html.Th('대표발명', style={**_PRINT_TABLE_TH_STYLE, 'textAlign': 'center'}),
            html.Th('지분율', style={**_PRINT_TABLE_TH_STYLE, 'textAlign': 'center'}),
            html.Th('출원국가', style=_PRINT_TABLE_TH_STYLE),
        ])),
        html.Tbody(rows, className='print-autofit-body'),
    ], className='print-autofit-table', style={'width': '100%', 'borderCollapse': 'collapse'})
    return html.Div([table, html.Div('', className='print-autofit-note text-muted small mt-1',
                                      style={'display': 'none'})])


def _print_pub_patent_detail_page(name, rid, tables):
    """2페이지: 논문·특허 실적 상세를 합쳐서 한 페이지 안에 담는다(제한
    사항). 두 표 모두 .print-autofit-table 마커를 달아 같은 .print-page-block
    안에 두면, 클라이언트사이드 오토핏 로직(아래 print 콜백)이 이 블록
    전체(논문+특허 합계) 높이를 기준으로 판단해 두 표에서 균형 있게 행을
    줄여 한 페이지에 맞춘다. 여러 명을 이어붙이는 일괄 인쇄에서도 이
    페이지가 누구 것인지 알 수 있도록 이름/사번을 다시 적어둔다."""
    return html.Div([
        html.Div(f'{name}({rid}) — 논문 · 특허 실적 상세', className='print-page2-title',
                 style={'fontSize': '16px', 'fontWeight': 700, 'marginBottom': '10px'}),
        _print_box('논문 실적 (주요 실적 우선 — 1저자·교신저자, IF 우선)',
                   _print_publication_detail_table(tables['publications'], rid)),
        _print_box('특허 실적 (전략출원 > 등록 > 출원, 대표발명·지분율 우선)',
                   _print_patent_detail_table(tables['patents'], rid)),
    ], className='print-page-block', style={'breakBefore': 'page'})


def _print_profile_content(rid, researcher, tables, profile, name_map,
                            print_eval_content, comments_content, current_status):
    """A4 인쇄 전용 콘텐츠 — 화면의 카드형 대시보드(고정 높이 + 내부 스크롤)는
    인쇄에 부적합해(넘치는 내용이 잘림) 재사용하지 않고, 같은 데이터/블록 함수를
    피플팀이 준 손그림 양식(사진+기본정보 / 근속·평가·양성·시상 / 보유역량 3단 /
    논문·특허 / 과제수행·인사발령)에 맞춰 테두리 박스로 재배치한다.
    print_eval_content/comments_content는 update_profile()이 권한(view_evaluation/
    view_comments)까지 반영해 이미 만들어둔 것(_locked_block() 포함)을 그대로
    받아써 권한 판정을 중복하지 않는다."""
    # 성별/나이·직급-년차는 사진 아래 캡션(photo_block())에 이미 나오므로
    # 기본정보 표에서는 중복 표시하지 않는다.
    name = str(researcher.get('name', '') or '')
    dept = str(researcher.get('department', '') or '-')
    knox_id = str(researcher.get('knox_id', '') or '-')
    nationality = str(researcher.get('nationality', '') or '').strip() or '-'
    # birth_date(YYYY-MM-DD, pipeline/process_researchers.py가 법적생년월일성별
    # 6자리(YYMMDD)에서 파싱)가 있으면 "YYYY년 M월 D일"로, 그 전에 처리된 옛
    # 데이터라 birth_date가 없으면(파이프라인 재실행 전) birth_year만으로
    # "YYYY년생"으로 폴백.
    birth_date_str = str(researcher.get('birth_date', '') or '').strip()
    if birth_date_str and birth_date_str.lower() not in ('nan', 'none', 'nat'):
        bd = date.fromisoformat(birth_date_str[:10])
        birth_label = f'{bd.year}년 {bd.month}월 {bd.day}일'
    else:
        birth_year = str(researcher.get('birth_year', '') or '').strip()
        birth_label = f'{birth_year}년생' if birth_year.isdigit() else '-'
    current_task = _current_task_label(tables['tasks'], rid)

    info_rows = [
        ('사번', rid), ('성명', name or '-'), ('소속부서', dept), ('과제', current_task),
        ('근속', _tenure_value(researcher.get('hire_date'))),
        ('생년월일', birth_label), ('국적', nationality), ('Knox ID', knox_id),
    ]
    info_table = html.Table(html.Tbody([
        html.Tr([
            html.Td(label, className='text-muted small pe-3',
                    style={'whiteSpace': 'nowrap', 'verticalAlign': 'top'}),
            html.Td(value, className='small', style={'wordBreak': 'break-word'}),
        ])
        for label, value in info_rows
    ]))

    # 평가·인센티브·양성·시상 이력을 한 박스에 담아 header_row 우측 최상단에
    # 사진/기본정보와 나란히 붙인다(빈 공간이 남지 않도록 photo/info와 같은
    # 줄에서 flex:1로 폭을 나눠 가짐).
    support_box = _print_box(None, html.Div([
        print_eval_content,
        html.Div('양성 이력', className='small fw-semibold text-muted mt-2 mb-1'),
        nurturing_block(tables['nurturing'], rid),
        html.Div('시상 이력', className='small fw-semibold text-muted mt-2 mb-1'),
        award_block(tables['awards'], rid, limit=3, single_line=True),
    ]))

    # display:flex를 인라인 style로 직접 준다(.d-flex 유틸리티 클래스 대신) —
    # 사진 오른쪽에 기본정보 박스가 나란히 붙어야 하는 핵심 레이아웃이라,
    # 외부 CDN(부트스트랩)이 느리거나 막혀 있어도 항상 가로 배치되게 한다.
    # 사진 박스가 기본정보(사번~Knox ID) 영역과 높이가 맞도록 alignItems를
    # stretch로 줘 옆의 정보 영역 높이만큼 늘어나게 하고, 사진 박스 안에서는
    # justifyContent:center로 내용을 세로 중앙에 둬 위(그리고 아래)에 여백이
    # 자연스럽게 생기게 한다.
    photo_info_row = html.Div([
        html.Div(photo_block(rid, name, researcher, CURRENT_YEAR, hide_normal_employment_status=True),
                 className='print-section',
                 style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center',
                        'justifyContent': 'center', 'width': '120px', 'flex': '0 0 120px',
                        'border': _PRINT_BOX_BORDER, 'borderRadius': '6px', 'padding': '8px'}),
        html.Div([info_table, current_status], style={'flex': '1 1 0', 'paddingLeft': '12px', 'minWidth': '0'}),
    ], style={'display': 'flex', 'alignItems': 'stretch'})

    # 학력은 사진+기본정보를 합친 폭(좌측 열 전체)만큼 아래에 붙이고, 그
    # 옆(우측 열)에 평가·인센티브(+양성/시상) 박스를 최상단부터 배치한다 —
    # 좌측 열(사진+정보 / 학력, 세로 스택)과 우측 열(평가·인센티브)이
    # 자연스럽게 나란히(병렬로) 배치된다.
    left_col = html.Div([
        photo_info_row,
        html.Div(_print_box('학력', education_block(tables['education'], rid, plain_degree=True)),
                 style={'marginTop': '8px'}),
    ], style={'flex': '2 1 0', 'minWidth': '0'})

    header_row = html.Div([
        left_col,
        html.Div(support_box, style={'flex': '1 1 0', 'minWidth': '0', 'marginLeft': '12px'}),
    ], style={'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '10px'})

    # 핵심기술/보유기술은 좌우 대신 세로로 쌓고(stacked=True), 그만큼 넓어진
    # 여유를 전문성 요약(LLM) 쪽에 몰아준다 — 비율을 1:2로 줘서 핵심기술/보유기술
    # 열보다 전문성 요약 열이 2배 넓어지게 한다. 전문성 요약은 지면이 좁은
    # 인쇄본 특성상 주요 역할·책임/유사 연구원은 빼고(강점 분야·키워드·전문지식
    # 및 역량만) 보여준다.
    capability_box = _print_box('보유 전문성 · 보유 기술 · 전문성 요약(LLM)', _print_box_cols([
        (1, owned_expertise_block(tables['core_technology'], tables['tech_ownership'], rid,
                                   stacked=True, show_tech_index=False, show_info_hover=False)),
        (2, html.Div([
            html.Div('전문성 요약(LLM)', className='small fw-semibold text-muted mb-1'),
            # llm_summary_block()은 데이터가 있으면 컴포넌트 "리스트"를 그대로
            # 반환한다(화면에서는 Output.children으로 바로 받아 문제 없음) —
            # 여기서는 그 리스트를 다른 리스트([...]) 안에 그대로 끼워 넣으면
            # 중첩 리스트가 되어 Dash가 이 서브트리를 통째로 빈 화면으로
            # 렌더링해버린다. html.Div로 한 번 더 감싸 평평하게 만든다.
            html.Div(llm_summary_block(profile, name_map=name_map, include_responsibilities=False)),
        ])),
    ]))

    # 박스 제목("논문 / 특허") 없이 "논문 실적 ~건"/"특허 실적 ~건" 두 줄만
    # 바로 보여준다(_print_publication_summary/_print_patent_summary가 각자
    # 라벨을 포함해서 반환).
    pub_patent_box = _print_box(None, html.Div([
        _print_publication_summary(tables['publications'], rid),
        _print_patent_summary(tables['patents'], rid),
    ]))

    task_hr_box = _print_box(
        '과제 수행 / 인사 발령 이력 (합쳐서 최근 10건, 시계열순)',
        _print_task_hr_timeline(tables['tasks'], tables['hr_orders'], rid, limit=_TASK_HR_RECENT_LIMIT),
        breakable=True,
    )

    return html.Div([
        html.Div('연구원 프로필', className='print-title',
                 style={'fontSize': '30px', 'fontWeight': 700,
                        'textAlign': 'center', 'marginBottom': '8px'}),
        header_row,
        capability_box,
        pub_patent_box,
        task_hr_box,
        _print_box('인물 코멘트', comments_content, breakable=True),
        html.Div(f'출력일 {datetime.now():%Y-%m-%d}', className='text-muted small text-end mt-2'),
        _print_pub_patent_detail_page(name, rid, tables),
    ])


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


def _build_print_block(rid, tables, researchers, name_map, show_eval, show_comments):
    """한 연구원의 인쇄용 콘텐츠(_print_profile_content) 하나를 만든다.
    update_profile()(단일 조회)과 build_bulk_print_content()(명단 화면에서
    넘어온 여러 명 일괄 인쇄)가 permission 판정(print_eval_content/
    comments_content 계산 포함)을 중복 없이 공유하기 위한 헬퍼."""
    rows = researchers[researchers['researcher_id'] == rid]
    if rows.empty:
        return None
    researcher = rows.iloc[0]
    profile = read_expertise_profiles().get(rid)
    salary_years, _half_years = evaluation_years()
    years = sorted(salary_years)

    print_eval_content = (
        evaluation_incentive_summary_text(tables['evaluations'], tables['incentive_selection'], rid, years)
        if show_eval
        else _locked_block('평가 · 인센티브 이력')
    )
    comments_content = (
        comments_block(tables['comments'], rid)
        if show_comments
        else _locked_block()
    )
    current_status = _current_status_badge(researcher)

    return _print_profile_content(rid, researcher, tables, profile, name_map,
                                   print_eval_content, comments_content, current_status)


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
    Output('profile-print-content', 'children'),
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

        current_status = _current_status_badge(researcher)

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
            current_status,
            _build_print_block(rid, tables, researchers, name_map, show_eval, show_comments),
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
            [], None, html.Div(), err_div, err_div, err_div, html.Div(), html.Div(),
        )


@callback(
    Output('profile-print-content', 'children', allow_duplicate=True),
    Input('bulk-print-ids', 'data'),
    prevent_initial_call='initial_duplicate',
)
def build_bulk_print_content(rid_list):
    import sys
    import traceback
    from services.auth import can, get_current_user

    if not rid_list or get_current_user() is None:
        return no_update

    show_eval = can('view_evaluation')
    show_comments = can('view_comments')

    try:
        tables = read_profile_tables()
        researchers = tables['researchers']
        if researchers.empty:
            return html.Div('연구원 정보를 찾을 수 없습니다.', className='text-muted p-3')
        name_map = researchers.set_index('researcher_id')['name'].to_dict()

        blocks = []
        for i, rid in enumerate(rid_list):
            block = _build_print_block(rid, tables, researchers, name_map, show_eval, show_comments)
            if block is None:
                continue
            # 마지막 사람 뒤에는 break를 넣지 않아야 끝에 빈 페이지가 안 붙는다
            # (assets/custom.css의 unnamed @page A4 오버라이드와 같은 이유).
            style = {} if i == len(rid_list) - 1 else {'breakAfter': 'page'}
            blocks.append(html.Div(block, style=style))
        return html.Div(blocks) if blocks else html.Div('선택한 연구원 정보를 찾을 수 없습니다.', className='text-muted p-3')
    except Exception as exc:
        print('[build_bulk_print_content] ERROR:', file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return html.Div(f'오류 발생: {exc}', className='text-danger small p-2')


@callback(
    Output('leadership-chart', 'figure'),
    Input('researcher-select', 'value'),
    Input('leadership-year', 'value'),
)
def update_leadership(rid, year):
    rid = str(rid).zfill(8) if rid else rid
    return leadership_figure(read_processed('leadership'), rid, year)


clientside_callback(
    """
    function(n) {
        if (n > 0) {
            // assets/custom.css의 이름 없는(unnamed) @page는 조직별 비교(A3
            // landscape) 화면 전용이라, 이 페이지를 인쇄하는 동안만 <style>을
            // head 맨 뒤에 추가해 같은 unnamed @page를 A4로 임시 덮어쓴다
            // (소스 순서상 나중 규칙이 이겨 A3보다 우선 적용됨). 인쇄 대화상자가
            // 닫히면(취소 포함) afterprint에서 제거해 다른 화면 인쇄에 영향이
            // 남지 않게 한다.
            var STYLE_ID = 'profile-print-a4-page-size';
            var existing = document.getElementById(STYLE_ID);
            if (existing) { existing.remove(); }
            var style = document.createElement('style');
            style.id = STYLE_ID;
            style.textContent = '@media print { @page { size: A4 portrait; margin: 14mm 16mm; } }';
            document.head.appendChild(style);

            // 버튼 클릭 직후 Dash가 콜백 처리 중 표시하는 "Updating..."
            // 문서 제목이 브라우저 인쇄 머리글에 그대로 찍히는 문제가
            // 있어, 인쇄 직전에 제목을 고정해두고 인쇄 후 원래 제목으로
            // 되돌린다.
            var originalTitle = document.title;
            document.title = '연구원 프로필';

            // 논문/특허 실적 상세(제목이 길면 줄바꿈되는 표)가 한 페이지를
            // 넘지 않도록, 인쇄 직전에 각 .print-page-block의 실제 렌더링
            // 높이를 재서 페이지 예산을 넘으면 표 뒤쪽 행부터 순서대로
            // 숨기고 "외 N건 더"를 채운다. 서버(파이썬)에서는 제목 줄바꿈
            // 등을 미리 정확히 알 수 없어 행 수를 고정으로 자르지 않고,
            // 이렇게 실측 기반으로 동적으로 결정한다.
            //
            // .profile-print-only는 화면에서 display:none이라 평소에는
            // 실제 렌더링 높이를 잴 수 없고, beforeprint 시점에도(적어도
            // 헤드리스 크로미움에서는 실측 결과 0으로 확인됨) 인쇄 레이아웃이
            // 아직 적용되지 않는다. 그래서 인쇄용 폰트 크기(10.5px 등,
            // assets/custom.css @media print 규칙과 동일)를 흉내낸 임시
            // <style>을 붙이고, 컨테이너를 화면 밖(왼쪽 -99999px)에 실제
            // 페이지 폭으로 잠깐 표시해 진짜 레이아웃으로 측정한 뒤 원래
            // 상태로 되돌린다 — 화면에는 전혀 보이지 않는다. 재인쇄해도 항상
            // 전체 행을 먼저 다시 보이는 상태로 되돌린 뒤 다시 계산해(멱등)
            // 반복 클릭에 따라 누적으로 더 잘려나가지 않게 한다.
            var container = document.getElementById('profile-print-content');
            if (container) {
                var PAGE_CONTENT_WIDTH_PX = (210 - 16 * 2) * 96 / 25.4;
                // 화면 밖에 임시로 렌더링해 재는 높이가 실제 인쇄 결과보다
                // 살짝(실측 30~50px 안팎) 작게 나오는 오차가 있어(오프스크린
                // 렌더링과 실제 인쇄 파이프라인의 미세한 레이아웃 차이로
                // 추정), 안전 여백을 넉넉히 빼서 경계선에서 한 페이지를
                // 넘기지 않게 한다.
                var PAGE_HEIGHT_SAFETY_MARGIN_PX = 80;
                var PAGE_HEIGHT_PX = (297 - 14 * 2) * 96 / 25.4 - PAGE_HEIGHT_SAFETY_MARGIN_PX;

                var MEASURE_STYLE_ID = 'profile-print-measure-style';
                var existingMeasureStyle = document.getElementById(MEASURE_STYLE_ID);
                if (existingMeasureStyle) { existingMeasureStyle.remove(); }
                var measureStyle = document.createElement('style');
                measureStyle.id = MEASURE_STYLE_ID;
                measureStyle.textContent =
                    '#profile-print-content.__pp-measuring, #profile-print-content.__pp-measuring * {' +
                    'font-size:10.5px !important; line-height:1.45 !important;}' +
                    '#profile-print-content.__pp-measuring .print-title{font-size:30px !important;}' +
                    '#profile-print-content.__pp-measuring .print-page2-title{font-size:16px !important;}' +
                    '#profile-print-content.__pp-measuring{display:block !important; position:fixed !important;' +
                    'left:-99999px !important; top:0 !important; width:' + PAGE_CONTENT_WIDTH_PX + 'px !important;}';
                document.head.appendChild(measureStyle);
                container.classList.add('__pp-measuring');

                document.querySelectorAll('.print-page-block').forEach(function(block) {
                    // 논문·특허 표가 한 블록(페이지)을 같이 쓰므로(제한 사항:
                    // 합쳐서 1페이지), 표별로 각자 맞추는 게 아니라 블록
                    // 전체(둘 합계) 높이가 예산을 넘지 않을 때까지, 그 순간
                    // 행이 더 많이 남은 표에서 한 줄씩 줄여 균형 있게 맞춘다.
                    var entries = [];
                    block.querySelectorAll('.print-autofit-table').forEach(function(table) {
                        var tbody = table.querySelector('.print-autofit-body');
                        var note = table.parentElement ? table.parentElement.querySelector('.print-autofit-note') : null;
                        if (!tbody) { return; }
                        var rows = tbody.rows;
                        for (var i = 0; i < rows.length; i++) { rows[i].style.display = ''; }
                        if (note) { note.style.display = 'none'; note.textContent = ''; }
                        entries.push({rows: rows, visible: rows.length, note: note});
                    });
                    if (!entries.length) { return; }

                    while (block.getBoundingClientRect().height > PAGE_HEIGHT_PX) {
                        var target = null;
                        for (var e = 0; e < entries.length; e++) {
                            if (entries[e].visible > 1 && (!target || entries[e].visible > target.visible)) {
                                target = entries[e];
                            }
                        }
                        if (!target) { break; }
                        target.rows[target.visible - 1].style.display = 'none';
                        target.visible--;
                    }

                    entries.forEach(function(entry) {
                        var removedCount = entry.rows.length - entry.visible;
                        if (removedCount > 0 && entry.note) {
                            entry.note.textContent = '외 ' + removedCount + '건 더';
                            entry.note.style.display = '';
                        }
                    });
                });

                container.classList.remove('__pp-measuring');
                measureStyle.remove();
            }

            var cleanup = function() {
                var el = document.getElementById(STYLE_ID);
                if (el) { el.remove(); }
                document.title = originalTitle;
                window.removeEventListener('afterprint', cleanup);
            };
            window.addEventListener('afterprint', cleanup);

            window.print();
        }
        return '';
    }
    """,
    Output('profile-print-dummy', 'children'),
    Input('profile-print-btn', 'n_clicks'),
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
