"""
"보유 전문성" 페이지의 "조직 분석" 탭(2026-10, 전문성 심화 지표 ③④⑤).

pipeline/process_expertise_metrics.py 등이 만든 조직 단위 집계 산출물을
보여준다. 산출물이 없으면(파이프라인 미실행) 섹션마다 안내 문구만 표시한다.

  - 부서/과제간 협업(collaboration_edges.csv) — 최근 5년·현재 소속 기준 1단계/3단계부서명 간
    협업을 네트워크 그래프 + 히트맵으로(services/collab_graph.py). 모든 로그인 사용자.
  - 과제별 역량(project_competency_gap.json) — 플랫폼/그룹/과제 캐스케이딩으로 과제를 고르면
    필요 역량별 소속 과제원(유사도 구간)과 비소속 적합 임직원. 모든 로그인 사용자.
    (2026-10-08부터 하위 탭 3개: 과제별 역량 / 부서 간 협업 / 기술별 보유자 수)
  - 기술별 보유자 수(핵심인력 리스크, technology_holder_summary.csv) —
    개인 명단이 들어 있어 관리자(manage_users)에게만 보인다.
"""

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html

from services.data_store import read_processed, read_project_competency_gap

_RISK_STYLE = {
    'styleConditions': [
        {'condition': "params.value === '위험'", 'style': {'color': '#cf1322', 'fontWeight': 600}},
        {'condition': "params.value === '주의'", 'style': {'color': '#d46b08', 'fontWeight': 600}},
    ],
    'defaultStyle': {'textAlign': 'center'},
}


def _section(title: str, hint: str, body) -> html.Div:
    return html.Div([
        html.Div(title, className='fw-semibold mb-1'),
        html.Div(hint, className='text-muted mb-2', style={'fontSize': '0.75rem'}),
        body,
    ], className='mb-4')


def _empty(msg: str) -> html.Div:
    return html.Div(msg, className='text-muted small p-2 border rounded bg-light')


def _name_map() -> dict:
    df = read_processed('researchers')
    if df.empty or 'name' not in df.columns:
        return {}
    return dict(zip(df['researcher_id'], df['name'].astype(str)))


def _names(ids: str, name_map: dict) -> str:
    return ', '.join(name_map.get(x.zfill(8), x) for x in str(ids or '').split(';') if x)


def technology_holder_section() -> html.Div:
    hint = ('현재 재직자 기준. 고수준 = 핵심기술 등급 A 이상 / 보유기술 Lv 3 이상(강점분야는 해당 없음). '
            '위험 = 보유자 2명 이하, 주의 = 고수준 보유자 1명 이하. 표기만 다른 같은 기술은 하나로 통합("통합된 표기" 열).')
    df = read_processed('technology_holder_summary')
    if df.empty:
        return _section('기술별 보유자 수 (핵심인력 리스크)', hint,
                        _empty('데이터 없음 — pipeline/run_analysis.py(4/4 전문성 심화 지표) 실행 후 표시됩니다.'))
    name_map = _name_map()
    df = df.fillna('')
    rows = [{
        **{k: r.get(k, '') for k in ('source', 'technology', 'tech_field', 'risk_level', 'aliases')},
        'holder_count': int(float(r.get('holder_count') or 0)),
        'high_level_count': (int(float(r['high_level_count'])) if str(r.get('high_level_count', '')).strip() else None),
        'department_count': int(float(r.get('department_count') or 0)),
        'holders': _names(r.get('holder_ids'), name_map),
        'high_level_holders': _names(r.get('high_level_ids'), name_map),
    } for r in df.to_dict('records')]
    counts = df['risk_level'].value_counts().to_dict()
    summary = html.Div([
        dbc.Badge(f"위험 {counts.get('위험', 0)}", color='danger', className='me-1'),
        dbc.Badge(f"주의 {counts.get('주의', 0)}", color='warning', text_color='dark', className='me-1'),
        dbc.Badge(f"정상 {counts.get('정상', 0)}", color='secondary'),
    ], className='mb-2')
    text_filter = {'filter': 'agTextColumnFilter', 'floatingFilter': True}
    num_filter = {'filter': 'agNumberColumnFilter', 'floatingFilter': True}
    column_defs = [
        {'headerName': '리스크', 'field': 'risk_level', 'width': 90, 'cellStyle': _RISK_STYLE, **text_filter},
        {'headerName': '출처', 'field': 'source', 'width': 100, **text_filter},
        {'headerName': '기술', 'field': 'technology', 'minWidth': 160, 'flex': 1,
         'cellStyle': {'textAlign': 'left'}, 'tooltipField': 'technology', **text_filter},
        {'headerName': '통합된 표기', 'field': 'aliases', 'minWidth': 140, 'flex': 1,
         'cellStyle': {'textAlign': 'left'}, 'tooltipField': 'aliases', **text_filter},
        {'headerName': '분야', 'field': 'tech_field', 'width': 120, **text_filter},
        {'headerName': '보유자', 'field': 'holder_count', 'width': 90, **num_filter},
        {'headerName': '고수준', 'field': 'high_level_count', 'width': 90, **num_filter},
        {'headerName': '부서 수', 'field': 'department_count', 'width': 90, **num_filter},
        {'headerName': '보유자 명단', 'field': 'holders', 'minWidth': 200, 'flex': 1,
         'cellStyle': {'textAlign': 'left'}, 'tooltipField': 'holders', **text_filter},
        {'headerName': '고수준 보유자', 'field': 'high_level_holders', 'minWidth': 160, 'flex': 1,
         'cellStyle': {'textAlign': 'left'}, 'tooltipField': 'high_level_holders', **text_filter},
    ]
    grid = dag.AgGrid(
        id='org-tech-holder-grid',
        className='gs-ag-grid',
        columnDefs=column_defs,
        rowData=rows,
        defaultColDef={'resizable': True, 'sortable': True, 'wrapHeaderText': True, 'autoHeaderHeight': True,
                       'cellStyle': {'textAlign': 'center'}},
        dashGridOptions={'pagination': True, 'paginationPageSize': 20, 'domLayout': 'autoHeight',
                         'tooltipShowDelay': 0},
    )
    return _section('기술별 보유자 수 (핵심인력 리스크)', hint, html.Div([summary, grid]))


def _grid(grid_id: str, column_defs: list, rows: list, page_size: int = 15) -> dag.AgGrid:
    return dag.AgGrid(
        id=grid_id, className='gs-ag-grid', columnDefs=column_defs, rowData=rows,
        defaultColDef={'resizable': True, 'sortable': True, 'wrapHeaderText': True, 'autoHeaderHeight': True,
                       'cellStyle': {'textAlign': 'center'}},
        dashGridOptions={'pagination': True, 'paginationPageSize': page_size, 'domLayout': 'autoHeight',
                         'tooltipShowDelay': 0},
    )


def collaboration_section() -> html.Div:
    title = '부서/과제간 협업 (최근 5년 논문 공저·특허 공동발명)'
    hint = ('같은 논문 공저자 또는 같은 특허 공동발명자인 현재 재직 연구원 쌍을 협업 1건으로 보고, 현재 소속 기준으로 '
            '부서(1단계부서명) 간 / 과제(3단계부서명) 간으로 합산합니다. 최근 5년(올해 포함) 건만, 같은 단위 안의 협업은 제외. '
            '네트워크 그래프는 선이 굵을수록 협업이 많고, 히트맵은 진할수록 많습니다(마우스 오버로 건수 확인).')
    edges = read_processed('collaboration_edges')
    if edges.empty:
        return _section(title, hint, _empty('데이터 없음 — pipeline/run_analysis.py(4/4 전문성 심화 지표) 실행 후 표시됩니다.'))
    if not {'recent_count', 'level1_a', 'level3_a'} <= set(edges.columns):
        return _section(title, hint, _empty('협업 데이터가 구버전입니다 — pipeline/run_analysis.py(4/4 전문성 심화 지표)를 '
                                            '다시 실행한 뒤 DB 반영하면 표시됩니다.'))
    controls = dbc.Row([
        dbc.Col([dbc.Label('기준', className='small fw-semibold text-muted mb-1'),
                 dbc.RadioItems(id='org-collab-level', value='level1', inline=True,
                                options=[{'label': '부서(1단계부서명)', 'value': 'level1'},
                                         {'label': '과제(3단계부서명)', 'value': 'level3'}])], md=6),
        dbc.Col([dbc.Label('표시 단위 수(협업량 상위)', className='small fw-semibold text-muted mb-1'),
                 dcc.Dropdown(id='org-collab-topn', value=20, clearable=False,
                              options=[{'label': f'상위 {n}개', 'value': n} for n in (10, 20, 30, 50)])], md=3),
    ], className='g-2 mb-3')
    return _section(title, hint, html.Div([controls, html.Div(id='org-collab-body')]))


@callback(Output('org-collab-body', 'children'),
          Input('org-collab-level', 'value'), Input('org-collab-topn', 'value'))
def _collab_body(level, top_n):
    from services import collab_graph as cg

    edges = read_processed('collaboration_edges')
    pairs = cg.aggregate(edges, level or 'level1')
    unit = '부서' if level != 'level3' else '과제'
    net = cg.network_figure(pairs, int(top_n or 20))
    heat = cg.heatmap_figure(pairs, int(top_n or 20))
    if net is None or heat is None:
        return _empty(f'표시할 {unit} 간 협업이 없습니다(최근 5년, 현재 소속 기준).')
    return dbc.Row([
        dbc.Col([html.Div(f'{unit} 간 협업 네트워크', className='small text-muted mb-1'),
                 dcc.Graph(figure=net, config={'displaylogo': False})], lg=6),
        dbc.Col([html.Div(f'{unit} 간 협업 히트맵', className='small text-muted mb-1'),
                 dcc.Graph(figure=heat, config={'displaylogo': False})], lg=6),
    ], className='g-3')


# ── 과제별 역량(2026-10-08 개편) ────────────────────────────────────────────────
# 플랫폼(1단계부서명) → 그룹(2단계부서명) → 과제(3단계부서명) 캐스케이딩으로 과제를 고르면,
# 그 과제의 필요 역량을 행별로 보여주고 역량마다 (a) 소속 과제원을 임베딩 유사도 구간
# (0~0.25/0.25~0.5/0.5~0.75/0.75~1)별로, (b) 비소속이지만 전문성이 맞는 임직원
# (0.75 이상, 없으면 0.75 미만 대표 최대 5명)을 보여준다. 데이터는
# pipeline/process_project_competency_gap.py 산출물(project_competency_gap.json).

_NO_LEVEL = '(미분류)'


def _lv(it: dict, key: str) -> str:
    return str(it.get(key) or '').strip() or _NO_LEVEL


def _opts(values) -> list:
    return [{'label': v, 'value': v} for v in sorted(set(values))]


def _gap_items() -> list:
    return read_project_competency_gap() or []


def _org_map() -> dict:
    df = read_processed('researchers')
    if df.empty or 'org_code' not in df.columns:
        return {}
    return dict(zip(df['researcher_id'], df['org_code'].astype(str)))


def _evidence_text(x: dict) -> str:
    reason = str(x.get('reason') or '').strip()
    items = '; '.join(f"{t.get('item', '')}({float(t.get('score', 0)):.2f})" for t in x.get('top_items') or []) \
        or str(x.get('item') or '')
    lines = []
    if reason:
        lines.append(f'근거: {reason}')
    lines.append(f'가까운 보유 항목: {items}' if items else '')
    return '\n'.join(l for l in lines if l)


def _person_badge(x: dict, name_map: dict, color: str, org_map: dict | None = None) -> html.Span:
    """배지 = 이름 + 임베딩 유사도. 마우스 오버: (비과제원이면 1단계/3단계 부서명) + LLM 근거 + 가까운 보유 항목."""
    rid = x.get('researcher_id', '')
    tip = _evidence_text(x)
    if org_map is not None:
        from services import similarity_map as sm
        l1, _l2, l3 = sm.org_code_level_names(org_map.get(rid, ''))
        tip = f"1단계부서: {l1 or '-'}\n3단계부서: {l3 or '-'}\n" + tip
    return dbc.Badge(f"{name_map.get(rid, rid)} {float(x.get('score', 0)):.2f}", color=color, className='me-1 mb-1',
                     title=tip, text_color='dark' if color == 'warning' else None, style={'cursor': 'help'})


def _score_color(score: float) -> str:
    return 'success' if score >= 0.75 else 'primary' if score >= 0.5 else 'warning' if score >= 0.25 else 'secondary'


def _competency_table(item: dict) -> html.Div:
    name_map, org_map = _name_map(), _org_map()
    rows = []
    for c in item.get('competencies') or []:
        members = c.get('members')
        if members is None:   # 구버전 산출물(재실행 전) — 충족 인력만 있음
            members = c.get('covered_by') or []
        outsiders = c.get('outsiders')
        if outsiders is None:
            outsiders = c.get('candidates') or []
        mem_cell = html.Td([_person_badge(m, name_map, _score_color(float(m.get('score', 0)))) for m in members]
                           or html.Span('-', className='text-muted'), style={'verticalAlign': 'top'})
        out_cell = html.Td([_person_badge(x, name_map, _score_color(float(x.get('score', 0))), org_map)
                            for x in outsiders] or html.Span('-', className='text-muted'),
                           style={'verticalAlign': 'top'})
        rows.append(html.Tr([
            html.Td(html.Div(c.get('competency', ''), className='fw-semibold'), style={'verticalAlign': 'top'}),
            html.Td(c.get('description') or html.Span('(설명 없음 — 분석 재실행 필요)', className='text-muted'),
                    style={'verticalAlign': 'top'}),
            mem_cell, out_cell,
        ]))
    head = html.Thead(html.Tr([
        html.Th('필요 역량', style={'width': '15%'}),
        html.Th('설명', style={'width': '25%'}),
        html.Th([html.Div('과제원 맵핑', style={'fontSize': '0.65rem'}), '이름 + 임베딩 유사도'], style={'width': '30%'}),
        html.Th([html.Div('비과제원 맵핑(상위 10명)', style={'fontSize': '0.65rem'}), '이름 + 임베딩 유사도'],
                style={'width': '30%'}),
    ]))
    return dbc.Table([head, html.Tbody(rows)], bordered=True, size='sm', className='mb-0 align-middle',
                     style={'fontSize': '0.78rem', 'tableLayout': 'fixed'})


def _project_options(l1, l2) -> list:
    """플랫폼/그룹 선택에 속하는 과제 옵션. 연구원 프로필·연구원 명단과 같은 기준(팀/리더 참조의
    1/2/3단계부서명 칸 값 → org_code)으로 고른 뒤, 과제명(꼬리표·공백 제거)이 그 org_code와
    일치하는 분석 과제만 남긴다. 아무것도 선택하지 않으면 전체(팀/리더 참조에 없는 과제 포함)."""
    from pipeline.researcher_fit import normalize_org_code
    from services import similarity_map as sm

    items = _gap_items()
    codes = sm.org_codes_for_levels(l1, l2, None)
    if codes is not None:
        wanted = {normalize_org_code(c) for c in codes}
        items = [i for i in items if normalize_org_code(i.get('project_name', '')) in wanted]
    return sorted(({'label': i.get('project_name', ''), 'value': i.get('project_name', '')} for i in items),
                  key=lambda o: o['label'])


@callback(Output('org-gap-l2', 'options'), Output('org-gap-l2', 'value'),
          Input('org-gap-l1', 'value'))
def _gap_l2_options(l1):
    from services import similarity_map as sm
    return sm.level_filter_options(2, {1: l1} if l1 else None), None


@callback(Output('org-gap-project', 'options'), Output('org-gap-project', 'value'),
          Input('org-gap-l1', 'value'), Input('org-gap-l2', 'value'))
def _gap_project_options(l1, l2):
    return _project_options(l1, l2), None


@callback(Output('org-gap-detail', 'children'), Input('org-gap-project', 'value'))
def _gap_detail(project):
    if not project:
        return _empty('위에서 플랫폼 → 그룹 → 과제를 선택하면 그 과제의 필요 역량별 인력 현황이 표시됩니다.')
    item = next((i for i in _gap_items() if i.get('project_name') == project), None)
    if not item:
        return _empty('선택한 과제의 분석 결과가 없습니다.')
    comps = item.get('competencies') or []
    summary = html.Div([
        dbc.Badge(f"필요 역량 {len(comps)}개", color='primary', className='me-1'),
        dbc.Badge(f"과제원 {item.get('member_count', 0)}명(분석 {item.get('analyzed_member_count', 0)}명)",
                  color='secondary', className='me-1'),
        html.Span(item.get('project_name', ''), className='small text-muted ms-1'),
    ], className='mb-2')
    if not comps:
        return html.Div([summary, _empty('이 과제의 필요 역량이 없습니다.')])
    return html.Div([summary, _competency_table(item)])


def competency_gap_section() -> html.Div:
    title = '과제별 필요 역량'
    hint = ('과제 문서에서 LLM이 뽑은 필요 역량과 쉬운 설명, 소속 과제원의 임베딩 유사도, 소속은 아니지만 해당 역량을 가진 '
            '임직원 상위 10명을 보여줍니다. 배지 숫자는 유사도(0~1), 마우스를 올리면 LLM 근거(비과제원은 1·3단계 부서명 포함).')
    items = _gap_items()
    if not items:
        return _section(title, hint, _empty('데이터 없음 — pipeline/run_analysis.py(5/5 과제별 역량 갭) 실행 후 표시됩니다.'))
    from services import similarity_map as sm
    drop = lambda id_, label, opts: dbc.Col([
        dbc.Label(label, className='small fw-semibold text-muted mb-1'),
        dcc.Dropdown(id=id_, options=opts, placeholder='전체' if id_ != 'org-gap-project' else '과제 선택', clearable=True),
    ], md=4)
    controls = dbc.Row([
        drop('org-gap-l1', '플랫폼', sm.level_filter_options(1)),
        drop('org-gap-l2', '그룹', sm.level_filter_options(2)),
        drop('org-gap-project', '과제', _project_options(None, None)),
    ], className='g-2 mb-3')
    return _section(title, hint, html.Div([controls, html.Div(id='org-gap-detail')]))


def org_analysis_content() -> html.Div:
    from services.auth import can

    tabs = [dbc.Tab(competency_gap_section(), label='과제별 필요 역량', tab_id='org-sub-gap'),
            dbc.Tab(collaboration_section(), label='부서/과제간 협업', tab_id='org-sub-collab')]
    if can('manage_users'):
        tabs.append(dbc.Tab(technology_holder_section(), label='기술별 보유자 수', tab_id='org-sub-tech'))
    return dbc.Tabs(tabs, id='org-sub-tabs', active_tab='org-sub-gap', className='mt-2')
