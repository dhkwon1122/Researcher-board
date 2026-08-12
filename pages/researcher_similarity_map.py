"""화면: 보유 전문성 (연구원/연구원↔연구원/전문성 MAP 3개 탭)

연구원/연구원↔연구원 2개 탭은 pipeline이 생성한 정적 콘솔 스타일 HTML
리포트를 그대로 iframe(srcDoc)으로 띄운다 — 별도 Dash 컴포넌트로 재구현하지
않고 기존 리포트 렌더링을 재사용하기 위함. 전문성 MAP 탭은 UMAP 산점도와
관계 그래프(옵시디언 방식 노드-링크, dash_cytoscape) 두 서브뷰를 버튼으로
전환할 수 있다 — 둘 다 무거운 계산(UMAP은 numba JIT, 관계 그래프도 데이터
로딩)이 있어 실제 선택된 서브뷰만 계산하도록 지연 렌더링한다.

(예전에는 "연구원↔과제" 탭도 있었지만, 그 기반이 되던 과제↔연구원 매칭
기능 자체가 제거되면서 함께 삭제됐다 — data/processed/CLAUDE.md 참고.)
"""

import os

import numpy as np
import dash
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, Patch, State, callback, dcc, html

from services.data_store import DATA_DIR
from services.similarity_map import (
    build_expertise_similarity_workbook, build_similarity_graph_elements,
    individual_search_options, load_similarity_map, org_tree_options,
    researchers_under_departments, similarity_graph_department_classes,
    similarity_workbook_filename,
)

dash.register_page(__name__, path='/researcher-similarity-map', name='보유 전문성',
                    title='연구원 보유 전문성')

_REPORT_FILES = {
    'researcher': '연구원 보유 전문성 분석.html',
    'similarity': 'researcher_similarity.html',
}


def _missing_data_alert() -> dbc.Alert:
    return dbc.Alert(
        [
            '유사도 지도를 표시할 데이터가 없습니다. 아래 순서로 먼저 실행하세요.',
            html.Ul([
                html.Li('python pipeline/process_researcher_expertise.py'),
                html.Li('python pipeline/process_researcher_similarity.py'),
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
        # detail-view 리포트(연구원/연구원↔연구원 — rd_specialist_markdown.py의
        # console_page(detail_view=True))는 조직도 클릭 전까지 카드를 전부
        # 숨겨 두므로, UMAP 점 클릭 등으로 특정 카드에 바로 스크롤해야 할 때는
        # 사이드바 클릭 핸들러(_CONSOLE_SCRIPT)와 동일하게 .detail-active를
        # 먼저 옮겨 붙여야 그 카드가 실제로 보인다(안 그러면 숨겨진 요소로
        # scrollIntoView만 호출되고 화면엔 아무것도 안 보임).
        script = (
            f'<script>document.addEventListener("DOMContentLoaded",function(){{'
            f'var el=document.getElementById({_json.dumps(scroll_to)});'
            f'if(el){{'
            f'if(document.body.classList.contains("detail-view")){{'
            f'document.querySelectorAll(".content .card.detail-active").forEach(function(c){{c.classList.remove("detail-active");}});'
            f'if(el.classList.contains("card")){{el.classList.add("detail-active");'
            f'var ph=document.querySelector(".detail-placeholder");if(ph)ph.style.display="none";}}'
            f'}}'
            f'el.scrollIntoView({{block:"start"}});'
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


def _uirevision_for(rid: str | None) -> str:
    """이 그래프의 uirevision 값 — 검색 대상(rid)이 바뀔 때만 값이 달라지게
    해서, 검색으로 특정 지점에 확대·포커스하는 "의도된" 확대는 실제로
    반영되면서도, 그 상태에서 사용자가 직접 확대/축소하는 동안에는(같은
    rid가 유지되는 한) Plotly가 그 확대 상태를 그대로 유지하게 한다
    (uirevision이 안 바뀌면 Plotly가 사용자의 현재 확대/이동을 새 figure
    prop보다 우선해서 유지 — 공식 권장 방식)."""
    return f'highlight:{rid or "none"}'


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


_SUBVIEW_UMAP = 'umap'
_SUBVIEW_GRAPH = 'graph'


def _subview_toggle():
    """UMAP 산점도 ↔ 관계 그래프(옵시디언 방식 노드-링크) 전환 버튼. 다시
    "전문성 MAP" 탭으로 돌아오면(_render_expertise_tab이 매번 새로 만듦)
    항상 UMAP 기본값으로 초기화된다 — 다른 탭 전환 시 상태가 리셋되는 이
    화면의 기존 관례와 동일."""
    return dbc.RadioItems(
        id='similarity-map-subview-toggle',
        options=[
            {'label': 'UMAP 지도', 'value': _SUBVIEW_UMAP},
            {'label': '관계 그래프', 'value': _SUBVIEW_GRAPH},
        ],
        value=_SUBVIEW_UMAP, inline=True, className='mb-2',
        inputClassName='btn-check', labelClassName='btn btn-outline-primary btn-sm me-1',
        labelCheckedClassName='active',
    )


def _map_tab_content(highlighted_rid: str | None = None):
    """전문성 MAP 탭 전체 — 헤더 + 서브뷰 전환 버튼 + 서브뷰 콘텐츠(기본
    UMAP). highlighted_rid(URL 쿼리로 진입한 강조 대상)는 최초 진입 시의
    UMAP 서브뷰에만 적용된다."""
    return html.Div([
        html.H4('연구원 전문성 유사도 지도', className='mb-1'),
        html.P(
            'BGE-M3 임베딩(1024차원)을 UMAP으로 2D에 투영한 지도, 또는 연구원↔연구원 '
            '유사도 판정을 노드-링크 관계 그래프로 볼 수 있습니다.',
            className='text-muted small mb-2',
        ),
        _subview_toggle(),
        html.Div(id='similarity-map-subview-content', children=_umap_subview_content(highlighted_rid)),
    ])


def _umap_subview_content(highlighted_rid: str | None = None):
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
        uirevision=_uirevision_for(highlighted_rid),
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
        html.P(
            '가까이 모인 점일수록 실제 보유 전문성이 유사합니다(과제명과 무관). '
            '점을 클릭하면 "연구원" 탭의 해당 카드로 이동합니다.',
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


_CYTO_BASE_STYLESHEET = [
    {'selector': 'node', 'style': {
        'label': 'data(label)', 'font-size': '9px', 'width': 22, 'height': 22,
        'color': '#333', 'text-valign': 'bottom', 'text-margin-y': 4,
        'border-width': 1, 'border-color': '#ffffff', 'background-color': '#8ecae6',
    }},
    {'selector': 'node:selected', 'style': {'border-width': 3, 'border-color': '#ff3b30'}},
    {'selector': 'edge', 'style': {
        'width': 'mapData(score, 0, 1, 1, 6)', 'opacity': 0.55, 'curve-style': 'bezier',
        'line-color': '#adb5bd',
    }},
    # 판정 레벨(상/중/하)별 엣지 색·진하기 — 근거가 뚜렷할수록 진하게.
    {'selector': '.level-상', 'style': {'line-color': '#1d4ed8', 'opacity': 0.75}},
    {'selector': '.level-중', 'style': {'line-color': '#60a5fa', 'opacity': 0.55}},
    {'selector': '.level-하', 'style': {'line-color': '#cbd5e1', 'opacity': 0.35}},
]


def _graph_subview_content():
    """옵시디언 방식 노드-링크 관계 그래프 서브뷰. UMAP과 달리 점(노드)
    위치는 임베딩 거리가 아니라 cytoscape의 힘-기반(cose) 레이아웃이
    엣지(연구원↔연구원 유사도) 연결 관계만으로 그때그때 계산한다."""
    elements = build_similarity_graph_elements()
    if not elements:
        return dbc.Alert(
            [
                '관계 그래프를 표시할 데이터가 없습니다. 아래 순서로 먼저 실행하세요.',
                html.Ul([
                    html.Li('python pipeline/process_researcher_expertise.py'),
                    html.Li('python pipeline/process_researcher_similarity.py'),
                ], className='mb-0 mt-2'),
            ],
            color='warning', className='mt-3',
        )
    stylesheet = _CYTO_BASE_STYLESHEET + similarity_graph_department_classes()
    return html.Div([
        html.P(
            '노드를 클릭하면 "연구원" 탭의 해당 카드로 이동합니다. 선(엣지)은 연구원↔연구원 '
            '유사도 판정 근거가 있는 쌍만 연결하며, 굵고 진할수록 유사도가 높습니다.',
            className='text-muted small mb-3',
        ),
        dbc.Card(
            dbc.CardBody(
                cyto.Cytoscape(
                    id='similarity-graph-cyto',
                    elements=elements,
                    layout={'name': 'cose', 'animate': True, 'padding': 30,
                            'nodeRepulsion': 8000, 'idealEdgeLength': 80, 'gravity': 40},
                    style={'width': '100%', 'height': '680px'},
                    stylesheet=stylesheet,
                    minZoom=0.2, maxZoom=3,
                ),
            ),
        ),
    ])


@callback(
    Output('similarity-map-subview-content', 'children'),
    Input('similarity-map-subview-toggle', 'value'),
    prevent_initial_call=True,
)
def _switch_map_subview(subview):
    if subview == _SUBVIEW_GRAPH:
        return _graph_subview_content()
    return _umap_subview_content()


@callback(
    Output('expertise-tabs', 'active_tab', allow_duplicate=True),
    Output('expertise-scroll-target', 'data', allow_duplicate=True),
    Input('similarity-graph-cyto', 'tapNodeData'),
    prevent_initial_call=True,
)
def _go_to_researcher_card_from_graph(node_data):
    """관계 그래프에서 노드를 클릭해도 UMAP 지도의 점 클릭과 동일하게
    '연구원' 탭으로 이동해 해당 카드로 스크롤한다(_go_to_researcher_card와
    동일한 동작 — 입력 컴포넌트만 다름)."""
    if not node_data or not node_data.get('id'):
        return dash.no_update, dash.no_update
    return 'researcher', f"r-{node_data['id']}"


def _download_panel():
    """"연구원"/"연구원 ↔ 연구원" 탭 아래(전문성 MAP 탭에서는 숨김)에 붙는
    보유 전문성·유사 연구원 명단 엑셀 다운로드 패널. 개인별 검색 또는
    조직도 부서 단위(하위부서 포함 옵션)로 대상을 고른다 — 특허/논문
    다운로드(연구원 명단 탭)처럼 이 화면 안에서도 완결되는 별도 패널로 둔다."""
    return html.Div([
        html.Hr(),
        html.Div([
            html.I(className='bi bi-file-earmark-excel me-2 text-success'),
            html.Span('보유 전문성 · 유사 연구원 명단 엑셀 다운로드', className='fw-semibold small'),
        ], className='mb-2'),
        dbc.RadioItems(
            id='expertise-download-mode', inline=True, value='individual',
            options=[
                {'label': '개인별 검색', 'value': 'individual'},
                {'label': '부서 선택(조직도)', 'value': 'department'},
            ],
            className='mb-2 small',
        ),
        html.Div(
            dcc.Dropdown(
                id='expertise-download-individual', options=individual_search_options(),
                multi=True, placeholder='이름 또는 사번으로 검색(복수 선택 가능)',
            ),
            id='expertise-download-individual-row',
        ),
        html.Div(
            dbc.Row([
                dbc.Col(dcc.Dropdown(
                    id='expertise-download-dept', options=org_tree_options(),
                    multi=True, placeholder='조직도에서 부서 선택(복수 선택 가능)',
                ), md=8),
                dbc.Col(dbc.Checklist(
                    id='expertise-download-include-children',
                    options=[{'label': '하위부서 포함', 'value': 'include'}],
                    value=['include'], switch=True, className='mt-2',
                ), md=4),
            ], className='g-2'),
            id='expertise-download-dept-row', style={'display': 'none'},
        ),
        dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '엑셀 다운로드'],
                   id='expertise-download-btn', color='success', outline=True, size='sm',
                   className='mt-2', n_clicks=0),
        html.Div(id='expertise-download-msg', className='small text-danger mt-1'),
        dcc.Download(id='expertise-download-download'),
    ], id='expertise-download-panel')


def layout(highlight_researcher=None, **_kwargs):
    """기본 진입 탭은 '연구원'. 다만 highlight_researcher가 있으면(URL 쿼리
    파라미터, 예: /researcher-similarity-map?highlight_researcher=00000001 —
    리포트 카드의 '📍 유사맵' 아이콘이 target="_top"으로 이 URL을 열 때 전달됨)
    그 연구원을 별 마커로 강조·확대해 보여줘야 하므로 예외적으로 '전문성 MAP'
    탭에 바로 랜딩한다."""
    default_tab = 'map' if highlight_researcher else 'researcher'
    initial_content = (
        _map_tab_content(highlighted_rid=highlight_researcher)
        if default_tab == 'map' else _iframe_tab('researcher')
    )
    return html.Div([
        html.H5(
            [html.I(className='bi bi-share-fill me-2 text-primary'), '보유 전문성'],
            className='fw-bold mb-3 mt-1',
        ),
        dbc.Tabs(
            [
                dbc.Tab(label='연구원', tab_id='researcher'),
                dbc.Tab(label='연구원 ↔ 연구원', tab_id='similarity'),
                dbc.Tab(label='전문성 MAP', tab_id='map'),
            ],
            id='expertise-tabs', active_tab=default_tab, className='mb-3',
        ),
        dcc.Loading(html.Div(
            id='expertise-tab-content',
            children=initial_content,
        )),
        _download_panel(),
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
    Output('expertise-download-panel', 'style'),
    Input('expertise-tabs', 'active_tab'),
)
def _toggle_download_panel(active_tab):
    """다운로드 패널은 "연구원"/"연구원 ↔ 연구원" 탭에서만 의미가 있어(요청
    범위) 전문성 MAP 탭에서는 숨긴다."""
    return {'display': 'block'} if active_tab in _REPORT_FILES else {'display': 'none'}


@callback(
    Output('expertise-download-individual-row', 'style'),
    Output('expertise-download-dept-row', 'style'),
    Input('expertise-download-mode', 'value'),
)
def _toggle_download_mode(mode):
    if mode == 'department':
        return {'display': 'none'}, {'display': 'block'}
    return {'display': 'block'}, {'display': 'none'}


@callback(
    Output('expertise-download-download', 'data'),
    Output('expertise-download-msg', 'children'),
    Input('expertise-download-btn', 'n_clicks'),
    State('expertise-download-mode', 'value'),
    State('expertise-download-individual', 'value'),
    State('expertise-download-dept', 'value'),
    State('expertise-download-include-children', 'value'),
    prevent_initial_call=True,
)
def _download_expertise_similarity(n_clicks, mode, individual_ids, dept_ids, include_children):
    if not n_clicks:
        return dash.no_update, dash.no_update
    if mode == 'department':
        dept_ids = dept_ids or []
        if not dept_ids:
            return dash.no_update, '부서를 선택해주세요.'
        researcher_ids = researchers_under_departments(dept_ids, include_children='include' in (include_children or []))
        if not researcher_ids:
            return dash.no_update, '선택한 부서에 소속된 연구원이 없습니다.'
    else:
        researcher_ids = individual_ids or []
        if not researcher_ids:
            return dash.no_update, '대상자를 검색해서 선택해주세요.'

    data = build_expertise_similarity_workbook(researcher_ids)
    return dcc.send_bytes(data, similarity_workbook_filename()), ''


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
    수 있는 이벤트라면 전부) 점멸 중이던 하이라이트도 함께 멈춘다.

    확대 상태 자체는 여기서 손대지 않는다 — 그래프 layout의 uirevision이
    (검색 대상이 안 바뀌는 한) 고정돼 있어, Plotly가 사용자의 현재 확대/이동을
    새로 받은 figure보다 우선해서 그대로 유지해 준다(_uirevision_for() 참고).
    예전엔 relayoutData에서 읽은 범위를 매번 수동으로 다시 적용했는데, 빠르게
    연속으로 확대할 때 서버 왕복 지연으로 뒤늦게 도착한 relayoutData가 이미
    더 확대된 화면을 예전 범위로 덮어써 순간적으로 "리셋되는 것처럼" 보이는
    레이스컨디션이 있었다 — uirevision으로 대체해 이 문제 자체를 없앴다."""
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
    전체 보기로 되돌린다.

    uirevision을 selected_rid 기준으로 명시적으로 바꿔서(_uirevision_for()),
    직전까지 사용자가 수동으로 확대해 둔 상태가 있어도 이 "의도된" 포커스
    이동이 실제로 반영되게 한다(uirevision이 그대로면 Plotly가 이전 확대
    상태를 그대로 유지해 버려 검색 포커스가 무시될 수 있다)."""
    fig = go.Figure(current_fig)
    blink_on = _apply_highlight(fig, selected_rid, points)
    fig.update_layout(uirevision=_uirevision_for(selected_rid))
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
