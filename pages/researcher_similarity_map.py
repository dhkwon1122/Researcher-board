"""화면: 보유 전문성 (연구원/연구원↔연구원/전문성 MAP 3개 탭)

연구원/연구원↔연구원 2개 탭은 pipeline의 콘솔 스타일 HTML 리포트 렌더러
(build_html())를 DB/CSV에서 읽은 데이터로 그때그때 호출해 iframe(srcDoc)으로
띄운다 — data/processed에 누구나 열어볼 수 있는 완성된 리포트 사본을 미리
만들어두지 않기 위함(역할별 접근 제어는 이 화면을 거칠 때만 적용되는
애플리케이션 레벨이라, 파일로 저장해두면 그 보호를 우회해 원본을 그대로 볼
수 있었다). 1500명 규모 벤치마크에서 렌더링이 각각 수십~수백 ms로 충분히
빨라(탭을 열 때만 1회 계산되므로) 별도 캐싱은 두지 않았다 — 자세한 배경은
pipeline/process_researcher_expertise.py의 build_html()/_archive_html() 주석
참고. 전문성 MAP 탭은 UMAP 산점도와 관계 그래프(옵시디언 방식 노드-링크,
dash_cytoscape) 두 서브뷰를 버튼으로 전환할 수 있다 — 둘 다 무거운 계산
(UMAP은 numba JIT, 관계 그래프도 데이터 로딩)이 있어 실제 선택된 서브뷰만
계산하도록 지연 렌더링한다.

(예전에는 "연구원↔과제" 탭도 있었지만, 그 기반이 되던 과제↔연구원 매칭
기능 자체가 제거되면서 함께 삭제됐다 — data/processed/CLAUDE.md 참고.)
"""

from datetime import date

import numpy as np
import dash
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, Patch, State, callback, dcc, html

from components.detail_tabs import llm_summary_block
from pipeline.process_researcher_expertise import (
    build_html as _build_researcher_html,
    researcher_card_html as _historical_card_html,
)
from pipeline.process_researcher_similarity import build_html as _build_similarity_html
from pipeline.rd_specialist_markdown import mail_page as _historical_page_shell
from services import expertise_ondemand
from services.data_store import (
    filter_current, read_expertise_profiles, read_processed, read_similar_researchers,
)
from services.similarity_map import (
    build_expertise_similarity_workbook, build_similarity_graph_elements,
    individual_search_options, load_similarity_map, org_tree_options,
    researchers_under_departments, similarity_graph_department_classes,
    similarity_workbook_filename,
)

dash.register_page(__name__, path='/researcher-similarity-map', name='보유 전문성',
                    title='연구원 보유 전문성')

# 사용자 요청: "전문성 MAP"은 보여주기엔 좋으나 기능상 의미가 없어 탭 자체를
# 숨긴다(코드는 남겨두고 진입 경로만 차단 — pages/org_comparison.py,
# pages/jd_reconciliation.py와 동일한 _FEATURE_HIDDEN 관례, 재오픈 방법은
# data/processed/CLAUDE.md 참고). 숨긴 동안은 Tabs에서 '전문성 MAP' 항목을
# 빼고, highlight_researcher URL 쿼리(리포트 카드의 옛 '📍 전문성 MAP'
# 아이콘이 전달하던 값 — 그 아이콘도 함께 제거됨, rd_specialist_markdown.py
# 참고)로 진입해도 더 이상 map 탭으로 랜딩하지 않는다.
_MAP_TAB_HIDDEN = True

_REPORT_TABS = ('researcher', 'similarity')


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


def _render_report_html(report_key: str) -> str | None:
    """DB(우선)/JSON 파일에서 읽은 데이터로 콘솔형 HTML 리포트를 그때그때
    렌더링한다. 데이터가 없으면(해당 파이프라인 스크립트 미실행) None."""
    researchers_df = read_processed('researchers')
    if report_key == 'researcher':
        profiles = list(read_expertise_profiles().values())
        if not profiles:
            return None
        return _build_researcher_html(profiles, researchers_df)
    profile_by_id = read_expertise_profiles()
    similar = list(read_similar_researchers().values())
    if not similar:
        return None
    return _build_similarity_html(similar, researchers_df, profile_by_id)


def _iframe_tab(report_key: str, scroll_to: str | None = None):
    """지정된 리포트를 build_html()로 렌더링해 srcDoc으로 그대로 임베드.
    데이터가 없으면(해당 파이프라인 스크립트 미실행) 안내 Alert만 보여준다.
    scroll_to가 주어지면(예: 전문성 유사맵에서 점을 클릭해 이 탭으로 넘어온 경우)
    로드 직후 해당 id 카드로 자동 스크롤하는 스크립트를 붙인다 — srcDoc은 URL이
    아니라 인라인 문서라 #fragment로는 스크롤을 지정할 수 없어 스크립트로 처리."""
    content = _render_report_html(report_key)
    if content is None:
        return dbc.Alert(
            '분석 리포트가 없습니다. 관련 pipeline 스크립트를 먼저 실행하세요.',
            color='warning', className='mt-3',
        )
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


def _cumulative_person_options() -> list:
    """누적기준 검색 옵션 — 전배·퇴사 등으로 최신 인력현황에 없는 사람도
    포함(researchers.csv는 업서트로 적재돼 삭제되지 않으므로 filter_current로
    걸러내지만 않으면 됨). individual_search_options()과 표기 규칙은 같지만
    미소속자는 라벨에 표시를 붙인다."""
    researchers_df = read_processed('researchers')
    if researchers_df.empty:
        return []
    options = []
    for _, row in researchers_df.sort_values(['department', 'name']).iterrows():
        dept = str(row.get('department', '') or '').strip()
        dept_suffix = f' [{dept}]' if dept else ''
        not_current = str(row.get('is_current', 'Y')) == 'N'
        suffix = ' — 현재 미소속' if not_current else ''
        options.append({
            'label': f"{row.get('name', '')}{dept_suffix} ({row['researcher_id']}){suffix}",
            'value': row['researcher_id'],
        })
    return options


def _cumulative_search_panel(report_key: str):
    """누적기준: 정적 리포트(조직도 클릭 기반, 특정 파이프라인 실행 시점의
    "현재" 조직 구조를 전제로 함)를 그대로 재사용할 수 없어, 조직도 탐색
    대신 이름/사번 검색으로 고른 사람 한 명의 결과만 컴포넌트로 직접
    렌더링한다. "연구원"/"연구원 ↔ 연구원" 두 탭 모두 강점 분야·키워드·
    유사 연구원 배지를 함께 보여주는 llm_summary_block() 하나로 충분해
    같은 렌더러를 공유한다(둘의 차이는 안내 문구뿐)."""
    hint = (
        '연구원 개인의 보유 전문성 요약을 봅니다.' if report_key == 'researcher'
        else '연구원 개인의 보유 전문성과 함께, 그 사람과 유사한 연구원 목록도 함께 보여줍니다.'
    )
    return html.Div([
        dbc.Alert(
            '누적기준: 조직도 대신 이름/사번으로 검색합니다(전배·퇴사 등으로 '
            '최신 인력현황에 없는 사람도 포함) — 조직 구조가 바뀌면 조직도 위치가 '
            '더 이상 유효하지 않을 수 있어, 이 모드에서는 조직도 탐색을 지원하지 않습니다.',
            color='secondary', className='small mb-3',
        ),
        html.P(hint, className='text-muted small mb-2'),
        dcc.Dropdown(
            id={'type': 'expertise-cumulative-search', 'tab': report_key},
            options=_cumulative_person_options(),
            placeholder='이름 또는 사번으로 검색',
            clearable=True, searchable=True, style={'maxWidth': '420px'},
            className='mb-3',
        ),
        html.Div(id={'type': 'expertise-cumulative-result', 'tab': report_key}),
    ])


def _render_cumulative_result(rid: str | None):
    if not rid:
        return html.Div('연구원을 검색해 선택하세요.', className='text-muted small p-2')
    researchers = read_processed('researchers')
    match = researchers[researchers['researcher_id'] == rid]
    if match.empty:
        return html.Div('연구원 정보를 찾을 수 없습니다.', className='text-muted small p-2')
    researcher = match.iloc[0]
    name_map = researchers.set_index('researcher_id')['name'].to_dict()
    profile = read_expertise_profiles().get(rid)
    similar = read_similar_researchers().get(rid, {}).get('similar', [])
    # 조회 대상(rid)은 누적기준으로 미소속자도 허용하지만, 추천되는 유사
    # 연구원 후보는 실제로 협업 가능한 사람이어야 하므로 항상 현재 소속자로
    # 제한한다(설계 확정 — JOB Market과 같은 이유, 후보군만은 현재기준 고정).
    current_researchers = filter_current(researchers, True)
    current_ids = set(current_researchers['researcher_id'])
    similar = [s for s in similar if s.get('researcher_id') in current_ids]

    header = [html.Span(f"{researcher.get('name', '')} ({rid})", className='fw-semibold me-2')]
    if str(researcher.get('is_current', 'Y')) == 'N':
        header.append(dbc.Badge('현재 미소속', color='secondary'))
    header.append(html.Span(
        f" {researcher.get('department', '')} · {researcher.get('position', '')}",
        className='text-muted small',
    ))

    return dbc.Card(
        dbc.CardBody([
            html.Div(header, className='mb-2'),
            html.Div(llm_summary_block(profile, similar, name_map)),
            html.Div([
                dbc.Button(
                    [html.I(className='bi bi-person-badge-fill me-1'), '개별 프로필 열기'],
                    href=f'/?id={rid}', target='_top',
                    color='primary', outline=True, size='sm', className='mt-3 me-2',
                ),
                dbc.Button(
                    [html.I(className='bi bi-envelope me-1'), '메일로 보내기'],
                    id={'type': 'mail-open-btn', 'rid': rid},
                    color='secondary', outline=True, size='sm', className='mt-3',
                ),
            ]),
        ]),
        className='shadow-sm',
    )


@callback(
    Output({'type': 'expertise-cumulative-result', 'tab': dash.MATCH}, 'children'),
    Input({'type': 'expertise-cumulative-search', 'tab': dash.MATCH}, 'value'),
)
def _update_cumulative_result(rid):
    return _render_cumulative_result(rid)


# ── 과거 시점 온디맨드 전문성 분석(2026-08-29) ──────────────────────────────
# 기본은 process_researcher_expertise.py의 배치(현재 재직자 전체)만 자동
# 분석하고, 과거 시점 분석은 여기서 필요할 때만 시점+사번을 입력해 요청한다
# (사용자 확정). "연구원" 탭 전용 — "연구원 ↔ 연구원"(유사도)은 그 시점 기준
# 전체 후보 재계산이 필요해 범위 밖이다(_render_expertise_tab 참고).

def _historical_search_panel():
    return html.Div([
        dbc.Alert(
            [
                '과거 시점 기준으로 온디맨드 전문성 분석을 요청합니다. 학력·과제 문서 인력 매칭은 '
                '시점 이력이 없어 현재 값을 근사치로 사용하고, 나머지(직무 이력/핵심기술/보유기술/'
                '업무목표/과제·논문·특허)는 그 시점 데이터를 그대로 사용합니다. LLM을 실시간으로 '
                '호출하므로 사번당 수십초 정도 걸릴 수 있으며, 한 번 분석한 사번+시점은 저장되어 '
                '다음에 다시 요청하면 즉시 표시됩니다.',
            ],
            color='secondary', className='small mb-3',
        ),
        dbc.Row([
            dbc.Col([
                html.Label('기준 시점', className='small text-muted mb-1 d-block'),
                dcc.DatePickerSingle(
                    id='expertise-historical-date',
                    date=date.today().isoformat(),
                    display_format='YYYY-MM-DD',
                    max_date_allowed=date.today().isoformat(),
                ),
            ], md=3),
            dbc.Col([
                html.Label('사번(이름/사번 검색, 복수 선택 가능)', className='small text-muted mb-1 d-block'),
                dcc.Dropdown(
                    id='expertise-historical-researchers',
                    options=_cumulative_person_options(),
                    multi=True, placeholder='이름 또는 사번으로 검색',
                ),
            ], md=7),
            dbc.Col([
                html.Label(' ', className='small d-block mb-1'),
                dbc.Button('분석 요청', id='expertise-historical-run-btn', color='primary',
                           size='sm', n_clicks=0),
            ], md=2),
        ], className='g-2 mb-3 align-items-end'),
        dcc.Store(id='expertise-historical-poll-store'),
        dcc.Interval(id='expertise-historical-interval', interval=3000, disabled=True),
        html.Div(id='expertise-historical-result'),
    ])


def _render_historical_results(researcher_ids: list, valid_date: date):
    """expertise_ondemand 캐시에 있는 값을 카드로 렌더링. 에러/미완료 항목은
    Dash Alert로, 정상 분석 결과는 pipeline.process_researcher_expertise.
    researcher_card_html()(process()의 정적 리포트와 같은 카드 스타일)을
    한 iframe에 모아서 보여준다(_iframe_tab()과 동일한 srcDoc 임베드 방식) —
    as_of/computed_at은 둘 다 서버가 직접 만든 날짜/시각 문자열이라(사용자
    입력이 그대로 echo되는 값이 아님) 별도 이스케이프 없이 그대로 삽입한다."""
    results = expertise_ondemand.get_results(researcher_ids, valid_date)
    researchers_df = read_processed('researchers')
    name_map = researchers_df.set_index('researcher_id')['name'].to_dict() if not researchers_df.empty else {}

    alerts, card_parts = [], []
    for rid, r in zip(researcher_ids, results):
        label = f'{name_map.get(rid, rid)} ({rid})'
        if r is None:
            alerts.append(dbc.Alert(f'{label}: 분석 결과를 찾을 수 없습니다 — 다시 시도해 주세요.',
                                     color='danger', className='small mb-1'))
        elif r.get('error'):
            alerts.append(dbc.Alert(f"{label}: {r['error']}", color='warning', className='small mb-1'))
        else:
            meta = (f'<div style="color:#86868b;font-size:0.78rem;margin-bottom:4px;">'
                    f'시점: {r.get("as_of", "")} · 분석: {r.get("computed_at", "")}</div>')
            card_parts.append(meta + _historical_card_html(r, name_map, anchor='', include_links=True))

    if not alerts and not card_parts:
        return dbc.Alert('표시할 결과가 없습니다.', color='secondary', className='small')

    children = list(alerts)
    if card_parts:
        doc = _historical_page_shell(f'과거 시점 온디맨드 분석 ({valid_date.isoformat()})', ''.join(card_parts))
        children.append(html.Iframe(
            srcDoc=doc,
            style={'width': '100%', 'height': f'{min(340 * len(card_parts) + 40, 900)}px', 'border': 'none'},
        ))
    return html.Div(children)


@callback(
    Output('expertise-historical-result', 'children'),
    Output('expertise-historical-interval', 'disabled'),
    Output('expertise-historical-poll-store', 'data'),
    Input('expertise-historical-run-btn', 'n_clicks'),
    State('expertise-historical-date', 'date'),
    State('expertise-historical-researchers', 'value'),
    prevent_initial_call=True,
)
def _start_historical_analysis(n_clicks, date_str, researcher_ids):
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update
    if not researcher_ids:
        return dbc.Alert('사번을 1명 이상 선택하세요.', color='warning', className='small'), True, None
    valid_date = date.fromisoformat(date_str)
    status = expertise_ondemand.request_analysis(researcher_ids, valid_date)
    if status == 'busy':
        return (dbc.Alert('다른 과거 시점 분석이 진행 중입니다. 잠시 후 다시 시도해 주세요.',
                           color='warning', className='small'), True, None)
    poll_data = {'researcher_ids': researcher_ids, 'valid_date': date_str}
    if status == 'ready':
        return _render_historical_results(researcher_ids, valid_date), True, None
    # 'started' — 캐시에 없는 사번이 있어 백그라운드로 분석 중.
    return (
        dbc.Spinner(html.Div(
            f'{len(researcher_ids)}명 분석 중입니다(완료되면 자동으로 표시됩니다)...',
            className='text-muted small',
        ), size='sm', color='primary'),
        False, poll_data,
    )


@callback(
    Output('expertise-historical-result', 'children', allow_duplicate=True),
    Output('expertise-historical-interval', 'disabled', allow_duplicate=True),
    Input('expertise-historical-interval', 'n_intervals'),
    State('expertise-historical-poll-store', 'data'),
    prevent_initial_call=True,
)
def _poll_historical_analysis(_n_intervals, poll_data):
    if not poll_data:
        return dash.no_update, True
    if expertise_ondemand.lock_status() is not None:
        return dash.no_update, dash.no_update  # 아직 실행 중 — 계속 폴링
    valid_date = date.fromisoformat(poll_data['valid_date'])
    return _render_historical_results(poll_data['researcher_ids'], valid_date), True


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


def _mail_researcher_modal(mail_rid: str | None = None, mail_rid_name: str = ''):
    """연구원 개별 카드(정적 리포트 안 ✉ 아이콘, target="_top" 이동으로
    ?mail_rid=... 진입 / 누적기준 카드의 '메일로 보내기' 버튼) 양쪽에서
    쓰는 공용 발송 모달. 이 화면을 열 수 있는 사람 누구나 사용 가능(별도
    권한 게이트 없음 — 이미 이 화면에서 조회 가능한 정보이므로)."""
    title = f'{mail_rid_name} ({mail_rid}) — 메일로 보내기' if mail_rid else '메일로 보내기'
    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(title, id='mail-researcher-modal-title')),
        dbc.ModalBody([
            html.P(
                '이 연구원의 보유 전문성과 유사 연구원 매칭 결과를 메일로 보냅니다. '
                '화면에 저장되지 않고, 발송할 때마다 최신 데이터로 새로 만듭니다.',
                className='small text-muted mb-2',
            ),
            dbc.Input(
                id='mail-researcher-recipients', size='sm',
                placeholder='수신자 이메일(콤마로 구분, 비워두면 본인에게 발송)',
            ),
            html.Div(id='mail-researcher-alert', className='mt-2'),
        ]),
        dbc.ModalFooter([
            dbc.Button('닫기', id='mail-researcher-cancel', color='secondary', size='sm'),
            dbc.Button(
                [html.I(className='bi bi-send me-1'), '발송'],
                id='mail-researcher-send', color='primary', size='sm',
            ),
        ]),
    ], id='mail-researcher-modal', is_open=bool(mail_rid))


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
            '누적기준에서는 조직도가 최신 상태를 보장하지 않아 "부서 선택(조직도)"를 사용할 수 없습니다.',
            id='expertise-download-mode-hint', className='text-muted mb-2',
            style={'fontSize': '0.72rem', 'display': 'none'},
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


def layout(highlight_researcher=None, mail_rid=None, **_kwargs):
    """기본 진입 탭은 '연구원'. 다만 highlight_researcher가 있으면(URL 쿼리
    파라미터, 예: /researcher-similarity-map?highlight_researcher=00000001)
    그 연구원을 별 마커로 강조·확대해 보여줘야 하므로 예외적으로 '전문성 MAP'
    탭에 바로 랜딩한다 — 단, _MAP_TAB_HIDDEN이면 그 탭 자체가 없으므로
    항상 '연구원' 탭으로 진입한다.

    mail_rid가 있으면(정적 리포트 카드의 ✉ 아이콘이 target="_top"으로 전달한
    쿼리 파라미터, 예: ?mail_rid=00000001) 그 연구원의 메일 발송 모달을
    처음부터 열어 둔 채로 진입한다."""
    if _MAP_TAB_HIDDEN:
        highlight_researcher = None
    default_tab = 'map' if highlight_researcher else 'researcher'
    mail_rid_name = ''
    if mail_rid:
        researchers_df = read_processed('researchers')
        if not researchers_df.empty:
            match = researchers_df[researchers_df['researcher_id'] == mail_rid]
            if not match.empty:
                mail_rid_name = str(match.iloc[0].get('name', ''))
    initial_content = (
        _map_tab_content(highlighted_rid=highlight_researcher)
        if default_tab == 'map' else _iframe_tab('researcher')
    )
    tabs = [
        dbc.Tab(label='연구원', tab_id='researcher'),
        dbc.Tab(label='연구원 ↔ 연구원', tab_id='similarity'),
    ]
    if not _MAP_TAB_HIDDEN:
        tabs.append(dbc.Tab(label='전문성 MAP', tab_id='map'))
    return html.Div([
        html.H5(
            [html.I(className='bi bi-share-fill me-2 text-primary'), '보유 전문성'],
            className='fw-bold mb-3 mt-1',
        ),
        dbc.Tabs(
            tabs,
            id='expertise-tabs', active_tab=default_tab, className='mb-3',
        ),
        html.Div(
            dbc.RadioItems(
                id='expertise-search-mode',
                options=[
                    {'label': '최신기준 (조직도 탐색)', 'value': 'current'},
                    {'label': '누적기준 (이름/사번 검색만)', 'value': 'all'},
                    {'label': '과거 시점 조회 (온디맨드 분석, 연구원 탭 전용)', 'value': 'historical'},
                ],
                value='current', inline=True, className='small mb-2',
            ),
            id='expertise-search-mode-row',
            style={'display': 'none'} if default_tab == 'map' else {'display': 'block'},
        ),
        dcc.Loading(html.Div(
            id='expertise-tab-content',
            children=initial_content,
        )),
        _download_panel(),
        dcc.Store(id='expertise-pending-highlight', data=highlight_researcher),
        dcc.Store(id='expertise-scroll-target'),
        dcc.Store(id='mail-researcher-target-rid', data=mail_rid),
        _mail_researcher_modal(mail_rid, mail_rid_name),
    ])


@callback(
    Output('expertise-tab-content', 'children', allow_duplicate=True),
    Output('expertise-scroll-target', 'data', allow_duplicate=True),
    Input('expertise-tabs', 'active_tab'),
    Input('expertise-search-mode', 'value'),
    State('expertise-pending-highlight', 'data'),
    State('expertise-scroll-target', 'data'),
    prevent_initial_call=True,
)
def _render_expertise_tab(active_tab, mode, pending_highlight, scroll_target):
    """탭 전환·검색기준 전환마다 해당 탭 콘텐츠를 지연 렌더링한다. 최초 진입
    시(active_tab의 기본값 'map', mode의 기본값 'current') 콘텐츠는 layout()이
    이미 채워 두므로, 이 콜백은 prevent_initial_call로 첫 로드 시에는 실행되지
    않고 이후 탭/모드 클릭에만 반응한다."""
    if active_tab == 'map':
        return _map_tab_content(highlighted_rid=pending_highlight), dash.no_update
    if active_tab in _REPORT_TABS:
        if mode == 'historical':
            if active_tab != 'researcher':
                return (
                    dbc.Alert('과거 시점 온디맨드 분석은 "연구원" 탭에서만 지원합니다.',
                              color='secondary', className='mt-3'),
                    dash.no_update,
                )
            return _historical_search_panel(), dash.no_update
        if mode == 'all':
            return _cumulative_search_panel(active_tab), dash.no_update
        content = _iframe_tab(active_tab, scroll_to=scroll_target if active_tab == 'researcher' else None)
        # 한 번 스크롤에 쓰고 나면 비워서, 이후 수동으로 탭을 다시 눌러도 매번
        # 같은 위치로 재스크롤되지 않게 한다.
        return content, (None if scroll_target else dash.no_update)
    return dash.no_update, dash.no_update


@callback(
    Output('expertise-download-panel', 'style'),
    Output('expertise-search-mode-row', 'style'),
    Input('expertise-tabs', 'active_tab'),
    Input('expertise-search-mode', 'value'),
)
def _toggle_download_panel(active_tab, mode):
    """다운로드 패널·검색기준 토글은 "연구원"/"연구원 ↔ 연구원" 탭에서만
    의미가 있어(요청 범위) 전문성 MAP 탭에서는 숨긴다. 다운로드 패널은
    "과거 시점 조회" 모드에서도 숨긴다 — 그 패널이 내려받는 건 현재
    expertise_profiles/similar_researchers(배치 산출물)라 온디맨드 과거
    시점 결과와는 무관하기 때문(혼동 방지)."""
    show_mode_row = active_tab in _REPORT_TABS
    show_download = active_tab in _REPORT_TABS and mode != 'historical'
    return (
        {'display': 'block'} if show_download else {'display': 'none'},
        {'display': 'block'} if show_mode_row else {'display': 'none'},
    )


@callback(
    Output('expertise-download-individual-row', 'style'),
    Output('expertise-download-dept-row', 'style'),
    Input('expertise-download-mode', 'value'),
)
def _toggle_download_mode(mode):
    if mode == 'department':
        return {'display': 'none'}, {'display': 'block'}
    return {'display': 'block'}, {'display': 'none'}


# 누적기준에서는 "부서 선택(조직도)" 다운로드 방식을 막는다 — 조직도 자체가
# 최신 시점 구조를 전제로 해서 미소속자를 포함한 부서 단위 선택이 의미가
# 없어질 수 있다(보유 전문성 조직도 탭과 동일한 이유).
@callback(
    Output('expertise-download-mode', 'options'),
    Output('expertise-download-mode', 'value', allow_duplicate=True),
    Output('expertise-download-mode-hint', 'style'),
    Input('expertise-search-mode', 'value'),
    State('expertise-download-mode', 'value'),
    prevent_initial_call=True,
)
def _restrict_download_mode(search_mode, current_download_mode):
    is_cumulative = (search_mode == 'all')
    options = [
        {'label': '개인별 검색', 'value': 'individual'},
        {'label': '부서 선택(조직도)', 'value': 'department', 'disabled': is_cumulative},
    ]
    new_value = 'individual' if is_cumulative else dash.no_update
    hint_style = {'fontSize': '0.72rem', 'display': 'block' if is_cumulative else 'none'}
    return options, new_value, hint_style


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


# ── 콜백: 개별 연구원 메일 발송 모달 ─────────────────────────────────────────

@callback(
    Output('mail-researcher-modal', 'is_open', allow_duplicate=True),
    Output('mail-researcher-target-rid', 'data', allow_duplicate=True),
    Output('mail-researcher-modal-title', 'children', allow_duplicate=True),
    Output('mail-researcher-alert', 'children', allow_duplicate=True),
    Input({'type': 'mail-open-btn', 'rid': dash.ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def _open_mail_modal_from_card(n_clicks_list):
    """누적기준 검색 결과 카드의 '메일로 보내기' 버튼 — 정적 리포트 카드의
    ✉ 아이콘(target="_top" 페이지 이동)과 달리 이쪽은 이미 Dash 컴포넌트
    트리 안이라 콜백으로 곧바로 모달을 연다."""
    if not any(n for n in n_clicks_list if n):
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    triggered = dash.ctx.triggered_id
    if not triggered:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    rid = triggered['rid']
    name = ''
    researchers_df = read_processed('researchers')
    if not researchers_df.empty:
        match = researchers_df[researchers_df['researcher_id'] == rid]
        if not match.empty:
            name = str(match.iloc[0].get('name', ''))
    return True, rid, f'{name} ({rid}) — 메일로 보내기', []


@callback(
    Output('mail-researcher-modal', 'is_open', allow_duplicate=True),
    Input('mail-researcher-cancel', 'n_clicks'),
    prevent_initial_call=True,
)
def _close_mail_modal(_):
    return False


@callback(
    Output('mail-researcher-alert', 'children', allow_duplicate=True),
    Input('mail-researcher-send', 'n_clicks'),
    State('mail-researcher-target-rid', 'data'),
    State('mail-researcher-recipients', 'value'),
    prevent_initial_call=True,
)
def _send_researcher_mail(_, rid, recipients_raw):
    if not rid:
        return dbc.Alert('대상 연구원을 확인할 수 없습니다.', color='danger',
                         dismissable=True, className='py-2 small mb-0')
    recipients = [addr.strip() for addr in (recipients_raw or '').split(',') if addr.strip()]
    if not recipients:
        # 수신자를 비워두면 로그인한 본인(로그인 ID@samsung.com)에게 보낸다.
        from services.auth import current_user_mail_default
        self_mail = current_user_mail_default()
        if not self_mail:
            return dbc.Alert('수신자 이메일을 입력하세요.', color='warning',
                             dismissable=True, className='py-2 small mb-0')
        recipients = [self_mail]

    from services.similarity_map import build_researcher_mail_html
    html_out = build_researcher_mail_html(rid)
    if html_out is None:
        return dbc.Alert(
            '이 연구원의 보유 전문성 데이터가 없습니다. 먼저 파이프라인을 실행하세요.',
            color='warning', dismissable=True, className='py-2 small mb-0',
        )

    name = rid
    researchers_df = read_processed('researchers')
    if not researchers_df.empty:
        match = researchers_df[researchers_df['researcher_id'] == rid]
        if not match.empty:
            name = str(match.iloc[0].get('name', '')) or rid

    from pipeline.mailer import MailError, send_html_email
    try:
        send_html_email(recipients, f'{name}({rid}) 보유 전문성', html_out)
    except MailError as exc:
        return dbc.Alert(f'메일 발송 실패: {exc}', color='danger',
                         dismissable=True, className='py-2 small mb-0')
    return dbc.Alert(f"발송했습니다 ({', '.join(recipients)})", color='success',
                     dismissable=True, className='py-2 small mb-0')
