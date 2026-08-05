"""화면: 보유 전문성 (연구원/연구원↔연구원/연구원↔과제/전문성 MAP 4개 탭)

연구원/연구원↔연구원/연구원↔과제 3개 탭은 pipeline이 생성한 정적 콘솔 스타일
HTML 리포트를 그대로 iframe(srcDoc)으로 띄운다 — 별도 Dash 컴포넌트로 재구현하지
않고 기존 리포트 렌더링을 재사용하기 위함. 전문성 MAP 탭만 기존 UMAP 산점도
그대로 유지하며, UMAP 계산(numba JIT)이 무겁기 때문에 탭이 실제 선택될 때만
계산하도록 지연 렌더링한다.

"과제 전문성"(구 project_expertise_analysis.html, 예전엔 별도 5번째 탭)은
연구원↔과제 탭(project_researcher_fit.html) 안의 "과제 기준"/"인별 기준"
탭 전환 영역에 세 번째 탭으로 통합됐다(researcher_fit.py의 build_fit_html
참고) — 별도 Dash 탭이 아니라 그 리포트 안의 라디오 탭 중 하나다.
"""

import json
import os

import numpy as np
import dash
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import ALL, Input, Output, Patch, State, callback, dcc, html

from services import nl_query
from services import researcher_profile_export
from services.data_store import DATA_DIR
from services.similarity_map import load_similarity_map

dash.register_page(__name__, path='/researcher-similarity-map', name='보유 전문성',
                    title='연구원 보유 전문성')

_REPORT_FILES = {
    'researcher': '연구원 보유 전문성 분석.html',
    'similarity': 'researcher_similarity.html',
    'fit': 'project_researcher_fit.html',
}


def _missing_data_alert() -> dbc.Alert:
    return dbc.Alert(
        [
            '유사도 지도를 표시할 데이터가 없습니다. 아래 순서로 먼저 실행하세요.',
            html.Ul([
                html.Li('python pipeline/process_researcher_expertise.py'),
                html.Li('python pipeline/process_researcher_similarity.py '
                        '(또는 process_project_researcher_fit.py — 둘 다 임베딩 캐시를 채웁니다)'),
            ], className='mb-0 mt-2'),
        ],
        color='warning', className='mt-3',
    )


def _hull_polygon(pts: np.ndarray) -> tuple:
    """점 3개 이상이면 convex hull을 살짝 부풀려 경계 폴리곤 좌표를 반환하고,
    2개 이하면 중심점 주변에 작은 원을 대신 그린다(hull을 만들 수 없으므로)."""
    centroid = pts.mean(axis=0)
    if len(pts) >= 3:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(pts)
        hull_pts = pts[hull.vertices]
        inflated = centroid + (hull_pts - centroid) * 1.15
        xs = list(inflated[:, 0]) + [inflated[0, 0]]
        ys = list(inflated[:, 1]) + [inflated[0, 1]]
    else:
        theta = np.linspace(0, 2 * np.pi, 30)
        spread = float(np.linalg.norm(pts - centroid, axis=1).max()) if len(pts) > 1 else 0.0
        r = max(spread * 1.5, 1.0)
        xs = (centroid[0] + r * np.cos(theta)).tolist()
        ys = (centroid[1] + r * np.sin(theta)).tolist()
    return xs, ys


# 인접한 경계끼리 구분되도록 순환 배정하는 파스텔 팔레트.
_PASTEL_PALETTE = [
    '#8ecae6',  # 하늘색
    '#f4a6c6',  # 핑크
    '#f7dd72',  # 노랑
    '#95d5b2',  # 민트
    '#c9a8f5',  # 라벤더
    '#f8b88b',  # 피치
    '#7fdbda',  # 라이트 틸
    '#b8c4e0',  # 라이트 블루그레이
]

# 확대 시 소규모 경계를 드러내는 기준 — 보이는 x/y 범위가 전체 범위의 이 비율
# 미만으로 좁아지면(대략 2배 이상 확대) "확대됨"으로 간주한다.
_ZOOM_REVEAL_RATIO = 0.5


def _pastel_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip('#')
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f'rgba({r}, {g}, {b}, {alpha})'


def _boundary_trace(xs, ys, label: str, color_hex: str, tier: str, visible: bool = True):
    """경계 하나(hull 폴리곤)를 트레이스로 만든다. 라벨은 add_annotation으로 항상
    그리지 않고 호버텍스트로만 노출해 기본 화면의 텍스트 혼잡을 없앤다. tier는
    'medium'(항상 표시)/'small'(확대 시에만 표시, _toggle_small_tier_by_zoom이
    meta.tier로 식별해 visible/hoverinfo를 토글) 구분용 메타데이터."""
    # hoveron='fills'로 채워진 영역 전체에 호버가 걸리게 하면, Plotly는 포인트별
    # hovertext가 아니라 트레이스의 name을 라벨로 사용한다 — 그래서 라벨을
    # hovertext 대신 name에 넣고 hovertemplate에서 %{fullData.name}으로 참조한다.
    return go.Scatter(
        x=xs, y=ys, fill='toself', mode='lines', hoveron='fills',
        fillcolor=_pastel_rgba(color_hex, 0.22),
        line=dict(color=_pastel_rgba(color_hex, 0.65), width=1.5 if tier == 'medium' else 1.2),
        hoverinfo='text' if visible else 'skip',
        name=label, hovertemplate='%{fullData.name}<extra></extra>',
        showlegend=False, visible=visible, meta={'tier': tier},
    )


def _add_cluster_overlays(fig, df):
    """소규모(1차 HDBSCAN)·중규모(소규모 클러스터 중심 재클러스터링) 2단계 경계를
    그린다. 중규모 경계(및 어디에도 묶이지 못한 고립 소규모 경계)는 항상 보이고
    파스텔 색으로만 인접 영역을 구분하며, 소규모 경계는 기본적으로 숨겨져 있다가
    사용자가 확대하면(_toggle_small_tier_by_zoom 콜백) 나타난다. 경계 트레이스는
    연구원 점보다 먼저 그려지도록 fig.data 맨 앞에 삽입해, 점이 항상 경계 위에
    보이게 한다."""
    always_traces = []
    color_i = 0
    for _, group in df[df['medium_cluster'] != -1].groupby('medium_cluster'):
        label = group['medium_cluster_label'].iloc[0]
        pts = group[['x', 'y']].to_numpy()
        xs, ys = _hull_polygon(pts)
        always_traces.append(_boundary_trace(xs, ys, label, _PASTEL_PALETTE[color_i % len(_PASTEL_PALETTE)], 'medium'))
        color_i += 1

    # 다른 소규모 클러스터와 묶이지 못한 고립 클러스터는 자기 자신을 상위 경계처럼
    # 취급해 항상 표시한다(중규모 경계가 하나도 없으면 지도에 아무 경계도 안 보이는
    # 것을 방지).
    orphan_ids = sorted(set(df.loc[df['medium_cluster'] == -1, 'cluster'].unique()) - {-1})
    for cid in orphan_ids:
        group = df[df['cluster'] == cid]
        label = group['cluster_label'].iloc[0]
        pts = group[['x', 'y']].to_numpy()
        xs, ys = _hull_polygon(pts)
        always_traces.append(_boundary_trace(xs, ys, label, _PASTEL_PALETTE[color_i % len(_PASTEL_PALETTE)], 'medium'))
        color_i += 1

    small_traces = []
    for cid, group in df[(df['cluster'] != -1) & (df['medium_cluster'] != -1)].groupby('cluster'):
        label = group['cluster_label'].iloc[0]
        pts = group[['x', 'y']].to_numpy()
        xs, ys = _hull_polygon(pts)
        color = _PASTEL_PALETTE[int(cid) % len(_PASTEL_PALETTE)]
        small_traces.append(_boundary_trace(xs, ys, label, color, 'small', visible=False))

    boundary_traces = always_traces + small_traces
    if boundary_traces:
        existing = list(fig.data)
        fig.data = ()
        for t in boundary_traces:
            fig.add_trace(t)
        for t in existing:
            fig.add_trace(t)


def _iframe_tab(report_key: str, scroll_to: str | None = None):
    """지정된 리포트 파일(data/processed 아래 정적 HTML)을 srcDoc으로 그대로 임베드.
    파일이 없으면(해당 파이프라인 스크립트 미실행) 안내 Alert만 보여준다.
    scroll_to가 주어지면(예: 전문성 유사맵에서 점을 클릭해 이 탭으로 넘어온 경우)
    로드 직후 해당 id 카드로 자동 스크롤하는 스크립트를 붙인다 — srcDoc은 URL이
    아니라 인라인 문서라 #fragment로는 스크롤을 지정할 수 없어 스크립트로 처리."""
    filename = _REPORT_FILES[report_key]
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return dbc.Alert(
            f'"{filename}" 리포트가 없습니다. 관련 pipeline 스크립트를 먼저 실행하세요.',
            color='warning', className='mt-3',
        )
    with open(path, encoding='utf-8') as f:
        content = f.read()
    if scroll_to:
        import json as _json
        script = (
            f'<script>document.addEventListener("DOMContentLoaded",function(){{'
            f'var el=document.getElementById({_json.dumps(scroll_to)});'
            f'if(el){{el.scrollIntoView({{block:"start"}});'
            f'el.style.outline="2px solid #4453d6";el.style.outlineOffset="2px";}}'
            f'}});</script>'
        )
        content = content.replace('</body>', script + '</body>') if '</body>' in content else content + script
    return html.Iframe(
        srcDoc=content,
        style={'width': '100%', 'height': '85vh', 'border': 'none'},
    )


_SEARCH_HIGHLIGHT_NAME = '__search_highlight__'
_BLINK_OPACITY = (1.0, 0.25)  # 별 마커가 매 tick마다 번갈아 쓰는 두 불투명도(눈에 띄는 점멸)


def _star_highlight_trace(x: float, y: float) -> go.Scatter:
    """찾는 연구원 위치에 눈에 띄는 별 모양 마커를 그린다(금색 채움 + 빨간
    테두리) — 점멸(blink)은 _blink_highlight 콜백이 이 트레이스의 opacity를
    주기적으로 토글해서 만든다."""
    return go.Scatter(
        x=[x], y=[y], mode='markers',
        marker=dict(symbol='star', size=28, color='#ffd60a', line=dict(width=2.5, color='#ff3b30')),
        hoverinfo='skip', showlegend=False, name=_SEARCH_HIGHLIGHT_NAME,
    )


def _apply_highlight(fig, rid: str | None, points: list):
    """검색으로 선택되었거나(URL의 highlight_researcher로 진입한 경우 포함)
    연구원을 지도 위 별 마커로 표시하고 그 지점으로 확대·포커스한다. rid가
    없거나 지도에 없으면 하이라이트를 지우고 전체 보기로 되돌린다. 반환값은
    하이라이트가 실제로 적용됐는지(블링크 Interval을 켤지 여부에 사용)."""
    fig.data = tuple(t for t in fig.data if t.name != _SEARCH_HIGHLIGHT_NAME)

    match = next((p for p in (points or []) if p['researcher_id'] == rid), None)
    if not rid or match is None:
        fig.update_layout(xaxis=dict(autorange=True), yaxis=dict(autorange=True))
        return False

    x, y = match['x'], match['y']
    xs = [p['x'] for p in points]
    ys = [p['y'] for p in points]
    pad_x = max((max(xs) - min(xs)) * 0.08, 0.5)
    pad_y = max((max(ys) - min(ys)) * 0.08, 0.5)

    fig.add_trace(_star_highlight_trace(x, y))
    fig.update_layout(
        xaxis=dict(range=[x - pad_x, x + pad_x]),
        yaxis=dict(range=[y - pad_y, y + pad_y]),
    )
    return True


def _map_tab_content(highlighted_rid: str | None = None):
    df, missing = load_similarity_map()
    if df.empty or 'x' not in df.columns:
        return _missing_data_alert()

    df = df.copy()
    df['strength_fields_str'] = df['strength_fields'].apply(lambda v: ', '.join(v) if v else '-')
    df['strength_keywords_str'] = df['strength_keywords'].apply(lambda v: ', '.join(v) if v else '-')
    # E직군/R직군 표기는 components/detail_tabs.py의 _e_support_pill()과 동일한 규칙
    # (원본 값이 'E'가 아니면 — 빈 값 포함 — 전부 'R직군')을 따른다.
    e_support_label = df['e_support'].apply(lambda v: 'E직군' if str(v).strip().upper() == 'E' else 'R직군')
    df['label'] = df['name'] + '(' + df['researcher_id'] + ')(' + e_support_label + ')'
    df['cluster_area'] = df['cluster_label'].replace('', '미분류(경계 없음)')

    fig = px.scatter(
        df, x='x', y='y', color='department',
        hover_name='label',
        hover_data={
            'org_code': True, 'strength_fields_str': True, 'strength_keywords_str': True,
            'cluster_area': True,
            'x': False, 'y': False, 'department': False,
        },
        custom_data=['researcher_id'],
        labels={
            'org_code': '과제/파트', 'strength_fields_str': '강점 분야', 'strength_keywords_str': '강점 키워드',
            'department': '플랫폼/팀', 'cluster_area': '유사 전문성 영역',
        },
    )
    fig.update_traces(marker=dict(size=11, opacity=0.85, line=dict(width=1, color='white')))
    _add_cluster_overlays(fig, df)
    fig.update_layout(
        height=680,
        legend_title_text='플랫폼/팀',
        dragmode='pan',
        xaxis_title=None, yaxis_title=None,
        xaxis=dict(showticklabels=False, zeroline=False, showgrid=False),
        yaxis=dict(showticklabels=False, zeroline=False, showgrid=False),
        margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor='white',
    )

    missing_note = (
        dbc.Alert(
            f'임베딩 캐시가 없어 지도에서 제외된 연구원 {missing}명 — '
            'process_researcher_similarity.py를 실행하면 함께 표시됩니다.',
            color='secondary', className='mb-3',
        )
        if missing else None
    )

    search_options = [
        {
            'label': f"{row['name']}({row['researcher_id']}) : {row['department']} - {row['org_code']}",
            'value': row['researcher_id'],
        }
        for _, row in df.iterrows()
    ]

    points = df[['researcher_id', 'x', 'y']].to_dict('records')
    blink_enabled = _apply_highlight(fig, highlighted_rid, points)

    return html.Div([
        html.H4('연구원 전문성 유사도 지도', className='mb-1'),
        html.P(
            'BGE-M3 임베딩(1024차원)을 UMAP으로 2D에 투영한 지도입니다 — 가까이 모인 점일수록 '
            '실제 보유 전문성이 유사합니다(과제명과 무관). 점을 클릭하면 "연구원" 탭의 해당 카드로 이동합니다.',
            className='text-muted small mb-3',
        ),
        missing_note,
        dbc.Card(
            dbc.CardBody(
                html.Div([
                    html.Div(
                        dcc.Dropdown(
                            id='similarity-map-search',
                            options=search_options,
                            value=highlighted_rid,
                            placeholder='이름 또는 사번으로 검색',
                            clearable=True,
                            searchable=True,
                            style={'width': '320px'},
                        ),
                        style={
                            'position': 'absolute', 'top': '10px', 'left': '10px', 'zIndex': 10,
                            'backgroundColor': 'rgba(255,255,255,0.95)', 'borderRadius': '6px',
                            'boxShadow': '0 1px 4px rgba(0,0,0,0.15)',
                        },
                    ),
                    dcc.Graph(
                        id='similarity-map-graph', figure=fig,
                        config={'displayModeBar': False, 'scrollZoom': True},
                    ),
                ], style={'position': 'relative'}),
            ),
        ),
        dcc.Store(id='similarity-map-points', data=points),
        dcc.Interval(id='similarity-map-blink-interval', interval=550, n_intervals=0, disabled=not blink_enabled),
    ])


def _fit_score_badge(score: str):
    color = {'상': 'success', '중': 'warning', '하': 'secondary'}.get(score, 'light')
    return dbc.Badge(score or '-', color=color, className='me-1')


_PAGE_SIZE = 30

# "건재순" — 부서(department) 컬럼 전용 정렬 기준(사용자 확정 순서). 목록에
# 없는 부서명은 이 뒤에 이름 오름차순으로 붙는다.
_DEPT_ORDER = [
    'advanced device platform(sait)',
    'photonics platform(sait)',
    'ai system platform(sait)',
    'material ai platform(sait)',
    'display solution platform(sait)',
    'air science platform(sait)',
    'future tech platform(sait)',
]

_SORT_OPTIONS = [{'label': '오름차순', 'value': 'asc'}, {'label': '내림차순', 'value': 'desc'}]
_DEPT_SORT_OPTIONS = _SORT_OPTIONS + [{'label': '건재순', 'value': 'custom'}]


def _nl_query_bar() -> html.Div:
    """자연어 질문 입력창 — "특정 전문성 보유자 찾기"/"과제에 적합한 사람 찾기"/
    "연구원에게 맞는 과제 찾기"(구조화 조회) + 그 밖의 원천 데이터 개방형 질문
    (services.open_data_query, SQL 생성)을 4개 intent 모두 같은 표 형태
    (columns/labels/rows)로 받아 하나의 렌더러로 보여준다. 자세한 아키텍처는
    services/nl_query.py, services/open_data_query.py 모듈 docstring 참고.

    Dash 콜백 설계 메모(재발 방지 — data/processed/CLAUDE.md에도 기록):
    매 렌더링마다 새로 나타나는 컴포넌트(정렬/필터 드롭다운, 행 체크박스 등)에
    건 콜백은, Dash가 "새로 나타난 컴포넌트"를 클릭 없이 한 번 더 실행시키는
    현상(팬텀 트리거)이 있다. 이번엔 그 컴포넌트를 고정시키는 대신, 모든
    관련 콜백을 "현재 표시된 값들로부터 다음 상태를 그대로 계산"하는 순수
    함수로 짜서(토글/증가가 아니라 대입) 팬텀 트리거가 와도 상태가 그대로
    유지되게 했다 — 유일한 예외인 n_clicks 기반 콜백(엑셀 다운로드, 정렬/필터
    초기화)은 `if not n_clicks: return dash.no_update`로 직접 방어한다."""
    return html.Div([
        dbc.InputGroup([
            dbc.Input(
                id='nl-query-input', type='text', debounce=False,
                placeholder='예: "로봇 제어 전문가 찾아줘", "차세대로봇제어 과제에 적합한 사람은?", '
                            '"물리학 전공한 사람 찾아줘"',
            ),
            dbc.Button([html.I(className='bi bi-search me-1'), '질문하기'],
                       id='nl-query-submit', color='primary', n_clicks=0),
        ], className='mb-2'),
        dcc.Loading(html.Div([
            html.Div(id='nl-query-result'),
            # 토글 버튼은 레이아웃에 상시 존재(숨김/라벨만 콜백으로 갱신) — 아래
            # docstring의 팬텀 트리거 메모 참고.
            dbc.Button('', id='nl-query-toggle-btn', color='link', size='sm',
                       className='p-0 mt-1', style={'display': 'none'}, n_clicks=0),
            dcc.Store(id='nl-query-full-result'),
            dcc.Store(id='nl-query-filters', data={}),
            dcc.Store(id='nl-query-sort', data={}),
            dcc.Store(id='nl-query-expanded', data=False),
            dcc.Store(id='nl-query-selected', data=[]),
        ])),
        dbc.Button('', id='nl-query-excel-btn', color='success', outline=True, size='sm',
                   className='mt-2', style={'display': 'none'}, n_clicks=0, disabled=True),
        dcc.Download(id='nl-query-excel-download'),
    ], className='mb-3')


# 식별자 성격이라 필터가 의미 없는 컬럼(정렬은 그대로 허용).
_NO_FILTER_COLUMNS = {'researcher_id', 'name', 'age'}

# degree_major는 "박)학교 전공" 형태라 원문 그대로 필터 목록을 만들면 사실상
# 학교/전공까지 다 다른 값이 되어 필터가 무의미해진다 — 전공만 필터에서 빼고
# 학력 구분(박/석/학/전문대/고교, services.researcher_profile_export의
# _DEGREE_ORDER_FULL과 동일한 5단계)은 전부 남긴다.
_DEGREE_FILTER_OPTIONS = [
    {'label': '박사', 'value': '박'},
    {'label': '석사', 'value': '석'},
    {'label': '학사', 'value': '학'},
    {'label': '전문대', 'value': '전'},
    {'label': '고교', 'value': '고'},
]


def _degree_prefix(value) -> str:
    s = '' if value is None else str(value)
    return s.split(')', 1)[0] if ')' in s else ''


def _column_options(columns: list, rows: list, col: str) -> list:
    if col == 'degree_major':
        return _DEGREE_FILTER_OPTIONS
    idx = columns.index(col)
    values = sorted({('' if r[idx] is None else str(r[idx])) for r in rows if idx < len(r)})
    return [{'label': v if v else '(빈값)', 'value': v} for v in values]


def _passes_filters(row: list, columns: list, filters: dict) -> bool:
    for col, allowed in (filters or {}).items():
        if not allowed or col not in columns:
            continue
        idx = columns.index(col)
        val = row[idx] if idx < len(row) else None
        if col == 'degree_major':
            if _degree_prefix(val) not in allowed:
                return False
            continue
        if ('' if val is None else str(val)) not in allowed:
            return False
    return True


def _sort_key_value(v):
    if v is None:
        return (2, '')
    s = str(v).strip()
    if s in ('', '-'):
        return (2, '')
    try:
        return (0, float(s))
    except ValueError:
        return (1, s)


def _dept_sort_key(v):
    s = '' if v is None else str(v)
    return (0, _DEPT_ORDER.index(s)) if s in _DEPT_ORDER else (1, s)


def _display_order(columns: list, rows: list, filters: dict, sort: dict) -> list:
    """필터 통과 + 정렬까지 적용한 뒤, rows 안에서의 원래 인덱스 목록을
    반환한다(체크박스 선택 상태는 이 원래 인덱스를 키로 관리 — 정렬/필터가
    바뀌어도 선택은 유지됨)."""
    order = [i for i, row in enumerate(rows) if _passes_filters(row, columns, filters)]
    sort_col, sort_mode = (sort or {}).get('column'), (sort or {}).get('mode')
    if sort_col and sort_col in columns and sort_mode:
        idx = columns.index(sort_col)
        if sort_mode == 'custom':
            order.sort(key=lambda i: _dept_sort_key(rows[i][idx] if idx < len(rows[i]) else None))
        elif sort_mode in ('asc', 'desc'):
            order.sort(key=lambda i: _sort_key_value(rows[i][idx] if idx < len(rows[i]) else None),
                       reverse=(sort_mode == 'desc'))
    return order


def _render_cell(col: str, value):
    if col == 'fit_score' and value:
        return _fit_score_badge(str(value))
    return '' if value is None else str(value)


def _render_table_body(full_result: dict, filters: dict, sort: dict, expanded: bool, selected: list):
    """반환: (화면에 넣을 컴포넌트, 필터 적용 후 전체 건수 — 0이면 "전체 보기"
    버튼을 숨긴다는 뜻으로도 쓰인다)."""
    intent = full_result.get('intent')
    note = full_result.get('note', '')
    if intent in ('error', 'unsupported'):
        return dbc.Alert(note, color='warning', className='mb-0'), 0

    columns = full_result.get('columns') or []
    labels = full_result.get('labels') or columns
    rows = full_result.get('rows') or []
    sql = full_result.get('sql', '')
    if not rows:
        return dbc.Alert(note or '검색 결과가 없습니다.', color='light', className='mb-0 border'), 0

    order = _display_order(columns, rows, filters, sort)
    total_filtered = len(order)
    visible = order if expanded else order[:_PAGE_SIZE]
    selected_set = set(selected or [])
    sort_col, sort_mode = (sort or {}).get('column'), (sort or {}).get('mode')

    header_cells = [html.Th(
        dbc.Checkbox(id='nl-query-selectall-check',
                     value=bool(visible) and all(i in selected_set for i in visible)),
        style={'width': '30px'},
    )]
    for col, label in zip(columns, labels):
        arrow = {'asc': ' ▲', 'desc': ' ▼', 'custom': ' ★'}.get(sort_mode, '') if col == sort_col else ''
        sort_opts = _DEPT_SORT_OPTIONS if col == 'department' else _SORT_OPTIONS
        controls = [
            dcc.Dropdown(
                id={'type': 'nl-sort-dd', 'col': col}, options=sort_opts, value=None,
                placeholder='정렬', clearable=False, style={'minWidth': '92px', 'fontSize': '12px'},
            ),
        ]
        if col not in _NO_FILTER_COLUMNS:
            controls.append(dcc.Dropdown(
                id={'type': 'nl-filter-dd', 'col': col}, options=_column_options(columns, rows, col),
                value=(filters or {}).get(col) or [], multi=True, placeholder='필터',
                style={'minWidth': '120px', 'fontSize': '12px'},
            ))
        header_cells.append(html.Th([
            html.Div(label + arrow, className='small fw-semibold mb-1'),
            html.Div(controls, className='d-flex gap-1'),
        ], style={'whiteSpace': 'nowrap', 'verticalAlign': 'top'}))

    body_rows = [
        html.Tr(
            [html.Td(dbc.Checkbox(id={'type': 'nl-row-check', 'idx': i}, value=i in selected_set))]
            + [html.Td(_render_cell(col, rows[i][j] if j < len(rows[i]) else None))
               for j, col in enumerate(columns)]
        )
        for i in visible
    ]

    table = dbc.Table(
        [html.Thead(html.Tr(header_cells)), html.Tbody(body_rows)],
        bordered=False, hover=True, size='sm', responsive=True, className='mt-2',
    )

    count_text = f'총 {total_filtered}건'
    if total_filtered != len(rows):
        count_text += f' (필터 적용 전 {len(rows)}건)'
    top_row = [html.Span(count_text, className='small text-muted fw-semibold')]
    if sort_col:
        top_row.append(html.A('정렬 해제', id='nl-query-sort-reset-btn', n_clicks=0,
                               className='small ms-2', href='#'))
    if filters:
        top_row.append(html.A('필터 초기화', id='nl-query-filter-reset-btn', n_clicks=0,
                               className='small ms-2', href='#'))

    children = [html.Div(top_row, className='mb-1')]
    if note:
        children.append(html.Div(note, className='small text-muted mb-2'))
    children.append(table)
    if sql:
        children.append(html.Details([
            html.Summary('실행된 SQL', className='small text-muted mt-2'),
            html.Pre(sql, className='small bg-light p-2 mt-1', style={'whiteSpace': 'pre-wrap'}),
        ]))
    return html.Div(children), total_filtered


def _selected_researcher_ids(full_result: dict, selected: list) -> list:
    columns = (full_result or {}).get('columns') or []
    if 'researcher_id' not in columns or not selected:
        return []
    idx = columns.index('researcher_id')
    rows = (full_result or {}).get('rows') or []
    out = []
    for i in selected:
        if i < len(rows) and idx < len(rows[i]) and rows[i][idx]:
            out.append(str(rows[i][idx]).strip().zfill(8))
    return out


@callback(
    Output('nl-query-full-result', 'data'),
    Output('nl-query-filters', 'data'),
    Output('nl-query-sort', 'data'),
    Output('nl-query-expanded', 'data'),
    Output('nl-query-selected', 'data'),
    Input('nl-query-submit', 'n_clicks'),
    Input('nl-query-input', 'n_submit'),
    State('nl-query-input', 'value'),
    prevent_initial_call=True,
)
def _run_nl_query(_n_clicks, _n_submit, question):
    """실제 LLM 호출/SQL 실행을 여기서 한 번만 하고 dcc.Store에 담아 둔다 —
    정렬/필터/펼치기/선택은 이 데이터를 다시 조회하지 않고 화면에서만
    처리한다. 새 질문마다 정렬/필터/펼침/선택 상태를 전부 초기화한다."""
    empty = {'intent': 'unsupported', 'columns': [], 'labels': [], 'rows': [], 'total_rows': 0, 'note': ''}
    if not question or not question.strip():
        return {**empty, 'note': '질문을 입력해주세요.'}, {}, {}, False, []
    result = nl_query.answer_question(question)
    return result, {}, {}, False, []


@callback(
    Output('nl-query-result', 'children'),
    Output('nl-query-toggle-btn', 'children'),
    Output('nl-query-toggle-btn', 'style'),
    Input('nl-query-full-result', 'data'),
    Input('nl-query-filters', 'data'),
    Input('nl-query-sort', 'data'),
    Input('nl-query-expanded', 'data'),
    State('nl-query-selected', 'data'),
    prevent_initial_call=True,
)
def _render_nl_query_store(full_result, filters, sort, expanded, selected):
    if not full_result:
        return dash.no_update, dash.no_update, dash.no_update
    expanded = bool(expanded)
    children, total_filtered = _render_table_body(full_result, filters, sort, expanded, selected)
    if total_filtered > _PAGE_SIZE:
        label = '접기' if expanded else f'전체 {total_filtered}건 보기'
        style = {'display': 'inline-block'}
    else:
        label, style = '', {'display': 'none'}
    return children, label, style


@callback(
    Output('nl-query-expanded', 'data', allow_duplicate=True),
    Input('nl-query-toggle-btn', 'n_clicks'),
    State('nl-query-expanded', 'data'),
    prevent_initial_call=True,
)
def _toggle_nl_query_expand(n_clicks, expanded):
    if not n_clicks:
        return dash.no_update
    return not expanded


@callback(
    Output('nl-query-sort', 'data', allow_duplicate=True),
    Input({'type': 'nl-sort-dd', 'col': ALL}, 'value'),
    State({'type': 'nl-sort-dd', 'col': ALL}, 'id'),
    prevent_initial_call=True,
)
def _set_sort(values, ids):
    """정렬 드롭다운은 값을 저장하지 않고(매 렌더링마다 value=None으로 새로
    그려짐) 항상 "고르면 그 컬럼/방향으로 확정" 트리거로만 쓴다 — 팬텀
    트리거가 와도 value는 초기값 None 그대로라 아래서 걸러진다."""
    triggered = dash.callback_context.triggered
    if not triggered:
        return dash.no_update
    try:
        comp_id = json.loads(triggered[0]['prop_id'].rsplit('.', 1)[0])
    except (ValueError, IndexError):
        return dash.no_update
    col = comp_id.get('col')
    value = next((v for v, i in zip(values, ids) if i.get('col') == col), None)
    if not value:
        return dash.no_update
    return {'column': col, 'mode': value}


@callback(
    Output('nl-query-sort', 'data', allow_duplicate=True),
    Input('nl-query-sort-reset-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def _reset_sort(n_clicks):
    if not n_clicks:
        return dash.no_update
    return {}


@callback(
    Output('nl-query-filters', 'data', allow_duplicate=True),
    Input({'type': 'nl-filter-dd', 'col': ALL}, 'value'),
    State({'type': 'nl-filter-dd', 'col': ALL}, 'id'),
    State('nl-query-filters', 'data'),
    prevent_initial_call=True,
)
def _set_filters(values, ids, current):
    triggered = dash.callback_context.triggered
    if not triggered:
        return dash.no_update
    try:
        comp_id = json.loads(triggered[0]['prop_id'].rsplit('.', 1)[0])
    except (ValueError, IndexError):
        return dash.no_update
    col = comp_id.get('col')
    if col is None:
        return dash.no_update
    value = next((v for v, i in zip(values, ids) if i.get('col') == col), None)
    filters = dict(current or {})
    if value:
        filters[col] = value
    else:
        filters.pop(col, None)
    return filters


@callback(
    Output('nl-query-filters', 'data', allow_duplicate=True),
    Input('nl-query-filter-reset-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def _reset_filters(n_clicks):
    if not n_clicks:
        return dash.no_update
    return {}


@callback(
    Output('nl-query-selected', 'data', allow_duplicate=True),
    Input({'type': 'nl-row-check', 'idx': ALL}, 'value'),
    State({'type': 'nl-row-check', 'idx': ALL}, 'id'),
    State('nl-query-selected', 'data'),
    prevent_initial_call=True,
)
def _sync_selected(values, ids, current):
    """현재 화면에 보이는 행들의 체크 상태로부터 선택 목록을 다시 계산한다
    (토글이 아니라 대입 — 팬텀 트리거가 와도 렌더링 시점 값 그대로라 안전).
    필터/펼치기로 화면에서 잠시 사라진 행의 선택은 유지한다."""
    visible_idx = {i['idx'] for i in ids}
    now_checked = {i['idx'] for i, v in zip(ids, values) if v}
    kept = [i for i in (current or []) if i not in visible_idx]
    return kept + list(now_checked)


@callback(
    Output({'type': 'nl-row-check', 'idx': ALL}, 'value'),
    Input('nl-query-selectall-check', 'value'),
    State({'type': 'nl-row-check', 'idx': ALL}, 'id'),
    prevent_initial_call=True,
)
def _toggle_selectall(checked, ids):
    if not ids:
        return dash.no_update
    return [bool(checked)] * len(ids)


@callback(
    Output('nl-query-excel-btn', 'children'),
    Output('nl-query-excel-btn', 'style'),
    Output('nl-query-excel-btn', 'disabled'),
    Input('nl-query-full-result', 'data'),
    Input('nl-query-selected', 'data'),
    prevent_initial_call=True,
)
def _update_excel_button(full_result, selected):
    columns = (full_result or {}).get('columns') or []
    if 'researcher_id' not in columns:
        return dash.no_update, {'display': 'none'}, dash.no_update
    n = len(_selected_researcher_ids(full_result, selected))
    label = [html.I(className='bi bi-file-earmark-excel me-1'),
              f'선택 {n}명 엑셀 다운로드' if n else '엑셀 다운로드 (행을 선택하세요)']
    return label, {'display': 'inline-block'}, n == 0


@callback(
    Output('nl-query-excel-download', 'data'),
    Input('nl-query-excel-btn', 'n_clicks'),
    State('nl-query-full-result', 'data'),
    State('nl-query-selected', 'data'),
    prevent_initial_call=True,
)
def _download_excel(n_clicks, full_result, selected):
    if not n_clicks:
        return dash.no_update
    researcher_ids = _selected_researcher_ids(full_result, selected)
    if not researcher_ids:
        return dash.no_update
    data = researcher_profile_export.build_profile_workbook(researcher_ids)
    return dcc.send_bytes(data, researcher_profile_export.default_filename())


def layout(highlight_researcher=None, **_kwargs):
    """highlight_researcher: URL 쿼리 파라미터(예: /researcher-similarity-map
    ?highlight_researcher=00000001) — 리포트 카드의 '📍 유사맵' 아이콘이
    target="_top"으로 이 URL을 열면, 전문성 유사맵 탭이 그 연구원을 별 마커로
    강조·확대한 상태로 바로 보이도록 pending-highlight Store에 태워 둔다."""
    return html.Div([
        html.H5(
            [html.I(className='bi bi-share-fill me-2 text-primary'), '보유 전문성'],
            className='fw-bold mb-3 mt-1',
        ),
        _nl_query_bar(),
        dbc.Tabs(
            [
                dbc.Tab(label='연구원', tab_id='researcher'),
                dbc.Tab(label='연구원 ↔ 연구원', tab_id='similarity'),
                dbc.Tab(label='연구원 ↔ 과제', tab_id='fit'),
                dbc.Tab(label='전문성 MAP', tab_id='map'),
            ],
            id='expertise-tabs', active_tab='map', className='mb-3',
        ),
        dcc.Loading(html.Div(
            id='expertise-tab-content',
            children=_map_tab_content(highlighted_rid=highlight_researcher),
        )),
        dcc.Store(id='expertise-pending-highlight', data=highlight_researcher),
        dcc.Store(id='expertise-scroll-target'),
    ])


@callback(
    Output('expertise-tab-content', 'children', allow_duplicate=True),
    Output('expertise-scroll-target', 'data', allow_duplicate=True),
    Input('expertise-tabs', 'active_tab'),
    State('expertise-pending-highlight', 'data'),
    State('expertise-scroll-target', 'data'),
    prevent_initial_call=True,
)
def _render_expertise_tab(active_tab, pending_highlight, scroll_target):
    """탭 전환마다 해당 탭 콘텐츠를 지연 렌더링한다. 최초 진입 시(active_tab의
    기본값 'map') 콘텐츠는 layout()이 이미 채워 두므로, 이 콜백은 prevent_initial_call
    로 첫 로드 시에는 실행되지 않고 이후 탭 클릭에만 반응한다."""
    if active_tab == 'map':
        return _map_tab_content(highlighted_rid=pending_highlight), dash.no_update
    if active_tab in _REPORT_FILES:
        content = _iframe_tab(active_tab, scroll_to=scroll_target if active_tab == 'researcher' else None)
        # 한 번 스크롤에 쓰고 나면 비워서, 이후 수동으로 탭을 다시 눌러도 매번
        # 같은 위치로 재스크롤되지 않게 한다.
        return content, (None if scroll_target else dash.no_update)
    return dash.no_update, dash.no_update


@callback(
    Output('expertise-tabs', 'active_tab'),
    Output('expertise-scroll-target', 'data', allow_duplicate=True),
    Output('similarity-map-blink-interval', 'disabled', allow_duplicate=True),
    Input('similarity-map-graph', 'clickData'),
    prevent_initial_call=True,
)
def _go_to_researcher_card(click_data):
    """지도에서 점을 클릭하면(과거처럼 별도 프로필 페이지로 이동하지 않고)
    같은 '보유 전문성' 화면 안에서 '연구원' 탭으로 전환하고, 그 탭의 iframe이
    렌더링될 때 해당 연구원 카드로 자동 스크롤한다. 탭을 벗어나면 지도 자체가
    사라지며 Interval도 함께 사라지지만, 명시적으로도 꺼서 점멸이 즉시 멈추게
    한다."""
    if not click_data:
        return dash.no_update, dash.no_update, dash.no_update
    rid = click_data['points'][0]['customdata'][0]
    return 'researcher', f'r-{rid}', True


@callback(
    Output('similarity-map-graph', 'figure', allow_duplicate=True),
    Output('similarity-map-blink-interval', 'disabled', allow_duplicate=True),
    Input('similarity-map-graph', 'relayoutData'),
    State('similarity-map-graph', 'figure'),
    State('similarity-map-points', 'data'),
    prevent_initial_call=True,
)
def _toggle_small_tier_by_zoom(relayout_data, current_fig, points):
    """사용자가 확대/축소·리셋할 때마다 보이는 x/y 범위를 전체 데이터 범위와
    비교해, _ZOOM_REVEAL_RATIO 이상 확대된 상태에서만 소규모(meta.tier='small')
    경계를 노출한다(visible + 호버텍스트 활성화). 그 외 relayout 이벤트(범위 변화가
    없는 경우)는 무시한다. 사용자가 지도를 드래그·확대/축소하면(이 콜백이 반응할
    수 있는 이벤트라면 전부) 점멸 중이던 하이라이트도 함께 멈춘다."""
    if not relayout_data or not points:
        return dash.no_update, dash.no_update

    has_range = 'xaxis.range[0]' in relayout_data and 'xaxis.range[1]' in relayout_data
    is_autorange = bool(relayout_data.get('xaxis.autorange') or relayout_data.get('yaxis.autorange'))
    if not has_range and not is_autorange:
        return dash.no_update, dash.no_update

    xs = [p['x'] for p in points]
    ys = [p['y'] for p in points]
    full_x_span = (max(xs) - min(xs)) or 1.0
    full_y_span = (max(ys) - min(ys)) or 1.0

    if is_autorange:
        zoomed_in = False
    else:
        cur_x_span = relayout_data['xaxis.range[1]'] - relayout_data['xaxis.range[0]']
        cur_y_span = relayout_data.get('yaxis.range[1]', 0) - relayout_data.get('yaxis.range[0]', 0)
        zoomed_in = (cur_x_span / full_x_span < _ZOOM_REVEAL_RATIO) or (cur_y_span / full_y_span < _ZOOM_REVEAL_RATIO)

    fig = go.Figure(current_fig)
    changed = False
    new_hoverinfo = 'text' if zoomed_in else 'skip'
    for trace in fig.data:
        if (trace.meta or {}).get('tier') != 'small':
            continue
        if trace.visible != zoomed_in or trace.hoverinfo != new_hoverinfo:
            trace.visible = zoomed_in
            trace.hoverinfo = new_hoverinfo
            changed = True
    if not changed:
        return dash.no_update, True

    # State('figure')는 사용자의 실시간 확대/축소를 반영하지 않으므로(relayoutData만
    # 갱신됨), 여기서 현재 확대 상태를 명시적으로 다시 반영하지 않으면 새 figure를
    # 반환하는 순간 화면이 전체보기로 리셋돼 버린다.
    if is_autorange:
        fig.update_layout(xaxis=dict(autorange=True), yaxis=dict(autorange=True))
    else:
        fig.update_layout(
            xaxis=dict(range=[relayout_data['xaxis.range[0]'], relayout_data['xaxis.range[1]']]),
            yaxis=dict(range=[relayout_data.get('yaxis.range[0]'), relayout_data.get('yaxis.range[1]')]),
        )
    return fig, True


@callback(
    Output('similarity-map-graph', 'figure', allow_duplicate=True),
    Output('similarity-map-blink-interval', 'disabled', allow_duplicate=True),
    Output('similarity-map-blink-interval', 'n_intervals', allow_duplicate=True),
    Input('similarity-map-search', 'value'),
    State('similarity-map-graph', 'figure'),
    State('similarity-map-points', 'data'),
    prevent_initial_call=True,
)
def _highlight_search_result(selected_rid, current_fig, points):
    """검색으로 연구원을 선택하면 지도 위 해당 점에 별 마커를 그리고 그
    지점으로 확대·포커스하며 점멸(blink) Interval을 켠다(다른 연구원을
    선택하거나 검색을 지우기 전까지 계속 깜빡임 — '다른 곳을 클릭하기 전까지'
    를 이 화면에서는 '다른 검색 결과를 고르거나 지우기 전까지'로 구현했다:
    지도 클릭은 이제 연구원 탭으로 이동하는 동작이라 지도 위에서 강조 대상을
    바꾸는 유일한 방법은 검색뿐이다). 선택 해제 시 하이라이트/점멸을 끄고
    전체 보기로 되돌린다."""
    fig = go.Figure(current_fig)
    blink_on = _apply_highlight(fig, selected_rid, points)
    return fig, not blink_on, 0


@callback(
    Output('similarity-map-graph', 'figure', allow_duplicate=True),
    Input('similarity-map-blink-interval', 'n_intervals'),
    prevent_initial_call=True,
)
def _blink_highlight(n_intervals):
    """블링크 Interval이 틱마다 별 마커의 불투명도만 Patch로 부분 갱신한다.
    이전엔 go.Figure(current_fig)로 전체를 다시 만들어 반환했는데, 그러면
    Plotly가 모든 트레이스를 다시 그려 화면 전체가 깜빡이는 것처럼 보였다
    (실제로 재현해 확인한 문제). _apply_highlight()가 항상 하이라이트
    트레이스를 fig.data 맨 끝에 추가하므로, data[-1]만 콕 집어 바꾸면 된다."""
    patch = Patch()
    patch['data'][-1]['marker']['opacity'] = _BLINK_OPACITY[n_intervals % 2]
    return patch
