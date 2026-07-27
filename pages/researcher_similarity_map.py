"""화면: 보유 전문성 (연구원/연구원↔연구원/연구원↔과제/전문성 유사맵/과제 5개 탭)

연구원/연구원↔연구원/연구원↔과제/과제 4개 탭은 pipeline이 생성한 정적 콘솔 스타일
HTML 리포트를 그대로 iframe(srcDoc)으로 띄운다 — 별도 Dash 컴포넌트로 재구현하지
않고 기존 리포트 렌더링을 재사용하기 위함. 전문성 유사맵 탭만 기존 UMAP 산점도
그대로 유지하며, UMAP 계산(numba JIT)이 무겁기 때문에 탭이 실제 선택될 때만
계산하도록 지연 렌더링한다.
"""

import os

import numpy as np
import dash
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html

from services.data_store import DATA_DIR
from services.similarity_map import load_similarity_map

dash.register_page(__name__, path='/researcher-similarity-map', name='보유 전문성',
                    title='연구원 보유 전문성')

_REPORT_FILES = {
    'researcher': '연구원 보유 전문성 분석.html',
    'similarity': 'researcher_similarity.html',
    'fit': 'project_researcher_fit.html',
    'project': 'project_expertise_analysis.html',
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


def _iframe_tab(report_key: str):
    """지정된 리포트 파일(data/processed 아래 정적 HTML)을 srcDoc으로 그대로 임베드.
    파일이 없으면(해당 파이프라인 스크립트 미실행) 안내 Alert만 보여준다."""
    filename = _REPORT_FILES[report_key]
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return dbc.Alert(
            f'"{filename}" 리포트가 없습니다. 관련 pipeline 스크립트를 먼저 실행하세요.',
            color='warning', className='mt-3',
        )
    with open(path, encoding='utf-8') as f:
        content = f.read()
    return html.Iframe(
        srcDoc=content,
        style={'width': '100%', 'height': '85vh', 'border': 'none'},
    )


def _map_tab_content():
    df, missing = load_similarity_map()
    if df.empty or 'x' not in df.columns:
        return _missing_data_alert()

    df = df.copy()
    df['strength_fields_str'] = df['strength_fields'].apply(lambda v: ', '.join(v) if v else '-')
    df['strength_keywords_str'] = df['strength_keywords'].apply(lambda v: ', '.join(v) if v else '-')
    df['label'] = df['researcher_id'] + ' ' + df['name']
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

    return html.Div([
        html.H4('연구원 전문성 유사도 지도', className='mb-1'),
        html.P(
            'BGE-M3 임베딩(1024차원)을 UMAP으로 2D에 투영한 지도입니다 — 가까이 모인 점일수록 '
            '실제 보유 전문성이 유사합니다(과제명과 무관). 점을 클릭하면 해당 연구원 프로필로 이동합니다.',
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
        dcc.Store(id='similarity-map-points', data=df[['researcher_id', 'x', 'y']].to_dict('records')),
        dcc.Location(id='similarity-map-url', refresh=True),
    ])


def layout(**_kwargs):
    return html.Div([
        html.H5(
            [html.I(className='bi bi-share-fill me-2 text-primary'), '보유 전문성'],
            className='fw-bold mb-3 mt-1',
        ),
        dbc.Tabs(
            [
                dbc.Tab(label='연구원', tab_id='researcher'),
                dbc.Tab(label='연구원 <-> 연구원', tab_id='similarity'),
                dbc.Tab(label='연구원 <-> 과제', tab_id='fit'),
                dbc.Tab(label='전문성 유사맵', tab_id='map'),
                dbc.Tab(label='과제', tab_id='project'),
            ],
            id='expertise-tabs', active_tab='map', className='mb-3',
        ),
        dcc.Loading(html.Div(id='expertise-tab-content')),
    ])


@callback(
    Output('expertise-tab-content', 'children'),
    Input('expertise-tabs', 'active_tab'),
)
def _render_expertise_tab(active_tab):
    if active_tab == 'map':
        return _map_tab_content()
    if active_tab in _REPORT_FILES:
        return _iframe_tab(active_tab)
    return dash.no_update


@callback(
    Output('similarity-map-url', 'href'),
    Input('similarity-map-graph', 'clickData'),
    prevent_initial_call=True,
)
def _go_to_profile(click_data):
    if not click_data:
        return dash.no_update
    rid = click_data['points'][0]['customdata'][0]
    return f'/researcher-profile?id={rid}'


_SEARCH_HIGHLIGHT_NAME = '__search_highlight__'


@callback(
    Output('similarity-map-graph', 'figure', allow_duplicate=True),
    Input('similarity-map-graph', 'relayoutData'),
    State('similarity-map-graph', 'figure'),
    State('similarity-map-points', 'data'),
    prevent_initial_call=True,
)
def _toggle_small_tier_by_zoom(relayout_data, current_fig, points):
    """사용자가 확대/축소·리셋할 때마다 보이는 x/y 범위를 전체 데이터 범위와
    비교해, _ZOOM_REVEAL_RATIO 이상 확대된 상태에서만 소규모(meta.tier='small')
    경계를 노출한다(visible + 호버텍스트 활성화). 그 외 relayout 이벤트(범위 변화가
    없는 경우)는 무시한다."""
    if not relayout_data or not points:
        return dash.no_update

    has_range = 'xaxis.range[0]' in relayout_data and 'xaxis.range[1]' in relayout_data
    is_autorange = bool(relayout_data.get('xaxis.autorange') or relayout_data.get('yaxis.autorange'))
    if not has_range and not is_autorange:
        return dash.no_update

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
        return dash.no_update

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
    return fig


@callback(
    Output('similarity-map-graph', 'figure', allow_duplicate=True),
    Input('similarity-map-search', 'value'),
    State('similarity-map-graph', 'figure'),
    State('similarity-map-points', 'data'),
    prevent_initial_call=True,
)
def _highlight_search_result(selected_rid, current_fig, points):
    """검색으로 연구원을 선택하면 지도 위 해당 점 주변에 빨간 링을 그리고
    그 지점으로 확대·포커스한다(프로필 이동은 기존처럼 점 클릭으로 처리).
    선택 해제 시 하이라이트를 지우고 전체 보기로 되돌린다."""
    fig = go.Figure(current_fig)
    fig.data = tuple(t for t in fig.data if t.name != _SEARCH_HIGHLIGHT_NAME)

    match = next((p for p in (points or []) if p['researcher_id'] == selected_rid), None)
    if not selected_rid or match is None:
        fig.update_layout(xaxis=dict(autorange=True), yaxis=dict(autorange=True))
        return fig

    x, y = match['x'], match['y']
    xs = [p['x'] for p in points]
    ys = [p['y'] for p in points]
    pad_x = max((max(xs) - min(xs)) * 0.08, 0.5)
    pad_y = max((max(ys) - min(ys)) * 0.08, 0.5)

    fig.add_trace(go.Scatter(
        x=[x], y=[y], mode='markers',
        marker=dict(size=24, color='rgba(0,0,0,0)', line=dict(width=3, color='#ff3b30')),
        hoverinfo='skip', showlegend=False, name=_SEARCH_HIGHLIGHT_NAME,
    ))
    fig.update_layout(
        xaxis=dict(range=[x - pad_x, x + pad_x]),
        yaxis=dict(range=[y - pad_y, y + pad_y]),
    )
    return fig
