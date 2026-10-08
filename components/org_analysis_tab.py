"""
"보유 전문성" 페이지의 "조직 분석" 탭(2026-10, 전문성 심화 지표 ③④⑤).

pipeline/process_expertise_metrics.py 등이 만든 조직 단위 집계 산출물을
보여준다. 산출물이 없으면(파이프라인 미실행) 섹션마다 안내 문구만 표시한다.

  - 부서 간 협업(collaboration_edges.csv) — 부서 쌍별 공동 논문·특허 건수와
    부서별 타부서 협업 비율. 모든 로그인 사용자.
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
            '위험 = 보유자 2명 이하, 주의 = 고수준 보유자 1명 이하.')
    df = read_processed('technology_holder_summary')
    if df.empty:
        return _section('기술별 보유자 수 (핵심인력 리스크)', hint,
                        _empty('데이터 없음 — pipeline/run_analysis.py(4/4 전문성 심화 지표) 실행 후 표시됩니다.'))
    name_map = _name_map()
    df = df.fillna('')
    rows = [{
        **{k: r.get(k, '') for k in ('source', 'technology', 'tech_field', 'risk_level')},
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
    title = '부서 간 협업 (논문 공저·특허 공동발명)'
    hint = ('같은 논문에 함께 이름을 올리거나 같은 특허의 공동발명자인 사내 연구원 쌍을 협업으로 집계. '
            '부서는 연구원 인사정보의 현재 부서 기준.')
    edges = read_processed('collaboration_edges')
    if edges.empty:
        return _section(title, hint, _empty('데이터 없음 — pipeline/run_analysis.py(4/4 전문성 심화 지표) 실행 후 표시됩니다.'))
    edges = edges.fillna('')
    edges['total_count'] = edges['total_count'].map(lambda v: int(float(v or 0)))
    edges = edges[(edges['department_a'] != '') & (edges['department_b'] != '')]

    # 부서별: 협업 관계 중 타부서 비율
    dept_rows = {}
    for r in edges.to_dict('records'):
        cross = r['department_a'] != r['department_b']
        for d in {r['department_a'], r['department_b']}:
            item = dept_rows.setdefault(d, {'department': d, 'pair_count': 0, 'cross_pair_count': 0})
            item['pair_count'] += 1
            item['cross_pair_count'] += int(cross)
    dept_list = sorted(dept_rows.values(), key=lambda x: -x['pair_count'])
    for item in dept_list:
        item['cross_ratio'] = round(item['cross_pair_count'] * 100.0 / item['pair_count'], 1) if item['pair_count'] else 0

    # 부서 쌍별(타부서만)
    cross = edges[edges['department_a'] != edges['department_b']].copy()
    pair_rows = []
    if not cross.empty:
        cross['_pair'] = cross.apply(lambda r: tuple(sorted((r['department_a'], r['department_b']))), axis=1)
        for (da, db), g in cross.groupby('_pair'):
            pair_rows.append({'department_a': da, 'department_b': db,
                              'pair_count': len(g), 'total_count': int(g['total_count'].sum())})
        pair_rows.sort(key=lambda x: -x['total_count'])

    num = {'filter': 'agNumberColumnFilter', 'floatingFilter': True, 'width': 120}
    txt = {'filter': 'agTextColumnFilter', 'floatingFilter': True, 'minWidth': 160, 'flex': 1,
           'cellStyle': {'textAlign': 'left'}}
    dept_grid = _grid('org-collab-dept-grid', [
        {'headerName': '부서', 'field': 'department', **txt},
        {'headerName': '협업 쌍', 'field': 'pair_count', **num},
        {'headerName': '타부서 협업 쌍', 'field': 'cross_pair_count', **num},
        {'headerName': '타부서 비율(%)', 'field': 'cross_ratio', **num},
    ], dept_list, page_size=10)
    pair_grid = (_grid('org-collab-pair-grid', [
        {'headerName': '부서 A', 'field': 'department_a', **txt},
        {'headerName': '부서 B', 'field': 'department_b', **txt},
        {'headerName': '연구원 쌍', 'field': 'pair_count', **num},
        {'headerName': '공동 논문+특허', 'field': 'total_count', **num},
    ], pair_rows, page_size=10) if pair_rows else _empty('타부서 협업 관계가 없습니다.'))
    return _section(title, hint, dbc.Row([
        dbc.Col([html.Div('부서별 타부서 협업 비율', className='small text-muted mb-1'), dept_grid], md=5),
        dbc.Col([html.Div('부서 쌍별 협업량(타부서만)', className='small text-muted mb-1'), pair_grid], md=7),
    ], className='g-3'))


# ── 과제별 역량(2026-10-08 개편) ────────────────────────────────────────────────
# 플랫폼(1단계부서명) → 그룹(2단계부서명) → 과제(3단계부서명) 캐스케이딩으로 과제를 고르면,
# 그 과제의 필요 역량을 행별로 보여주고 역량마다 (a) 소속 과제원을 임베딩 유사도 구간
# (0~0.25/0.25~0.5/0.5~0.75/0.75~1)별로, (b) 비소속이지만 전문성이 맞는 임직원
# (0.75 이상, 없으면 0.75 미만 대표 최대 5명)을 보여준다. 데이터는
# pipeline/process_project_competency_gap.py 산출물(project_competency_gap.json).

_BANDS = [(0.75, 1.01, '0.75~1', 'success'), (0.5, 0.75, '0.5~0.75', 'primary'),
          (0.25, 0.5, '0.25~0.5', 'warning'), (0.0, 0.25, '0~0.25', 'secondary')]
_NO_LEVEL = '(미분류)'


def _lv(it: dict, key: str) -> str:
    return str(it.get(key) or '').strip() or _NO_LEVEL


def _opts(values) -> list:
    return [{'label': v, 'value': v} for v in sorted(set(values))]


def _gap_items() -> list:
    return read_project_competency_gap() or []


def _person_badge(x: dict, name_map: dict, color: str) -> html.Span:
    rid = x.get('researcher_id', '')
    return dbc.Badge(f"{name_map.get(rid, rid)} {x.get('score', 0):.2f}", color=color, className='me-1 mb-1',
                     title=f"근거 항목: {x.get('item', '')}", text_color='dark' if color == 'warning' else None)


def _competency_table(item: dict) -> html.Div:
    name_map = _name_map()
    rows = []
    for c in item.get('competencies') or []:
        members = c.get('members')
        if members is None:   # 구버전 산출물(재실행 전) — 충족 인력만 있음
            members = c.get('covered_by') or []
        band_cells = []
        for lo, hi, _label, color in _BANDS:
            people = [m for m in members if lo <= float(m.get('score', 0)) < hi]
            band_cells.append(html.Td([_person_badge(m, name_map, color) for m in people] or
                                      html.Span('-', className='text-muted'), style={'verticalAlign': 'top'}))
        outsiders = c.get('outsiders')
        if outsiders is None:
            outsiders = c.get('candidates') or []
        low = bool(c.get('outsider_low'))
        out_cell = html.Td([
            *[_person_badge(x, name_map, 'secondary' if low else 'success') for x in outsiders],
            *([html.Div('0.75 미만 대표', className='text-muted', style={'fontSize': '0.68rem'})] if low and outsiders else []),
        ] or html.Span('-', className='text-muted'), style={'verticalAlign': 'top'})
        covered = bool(c.get('covered'))
        rows.append(html.Tr([
            html.Td([html.Div(c.get('competency', ''), className='fw-semibold'),
                     dbc.Badge('충족' if covered else '갭', color='success' if covered else 'danger', className='mt-1')],
                    style={'verticalAlign': 'top'}),
            *band_cells, out_cell,
        ]))
    head = html.Thead(html.Tr([
        html.Th('필요 역량', style={'width': '16%'}),
        *[html.Th([html.Div('소속 과제원', style={'fontSize': '0.65rem'}), f'{label}'], className='text-center',
                  style={'width': '13%'}) for _lo, _hi, label, _c in _BANDS],
        html.Th([html.Div('비소속 적합 임직원', style={'fontSize': '0.65rem'}), '0.75~1'], className='text-center',
                style={'width': '20%'}),
    ]))
    return dbc.Table([head, html.Tbody(rows)], bordered=True, size='sm', className='mb-0 align-middle',
                     style={'fontSize': '0.78rem', 'tableLayout': 'fixed'})


@callback(Output('org-gap-l2', 'options'), Output('org-gap-l2', 'value'),
          Input('org-gap-l1', 'value'))
def _gap_l2_options(l1):
    items = [i for i in _gap_items() if not l1 or _lv(i, 'level1') == l1]
    return _opts(_lv(i, 'level2') for i in items), None


@callback(Output('org-gap-project', 'options'), Output('org-gap-project', 'value'),
          Input('org-gap-l1', 'value'), Input('org-gap-l2', 'value'))
def _gap_project_options(l1, l2):
    items = [i for i in _gap_items()
             if (not l1 or _lv(i, 'level1') == l1) and (not l2 or _lv(i, 'level2') == l2)]
    opts = [{'label': (_lv(i, 'level3') if _lv(i, 'level3') != _NO_LEVEL else i.get('project_name', '')),
             'value': i.get('project_name', '')} for i in items]
    return sorted(opts, key=lambda o: o['label']), None


@callback(Output('org-gap-detail', 'children'), Input('org-gap-project', 'value'))
def _gap_detail(project):
    if not project:
        return _empty('위에서 플랫폼 → 그룹 → 과제를 선택하면 그 과제의 필요 역량별 인력 현황이 표시됩니다.')
    item = next((i for i in _gap_items() if i.get('project_name') == project), None)
    if not item:
        return _empty('선택한 과제의 분석 결과가 없습니다.')
    comps = item.get('competencies') or []
    summary = html.Div([
        dbc.Badge(f"충족률 {item.get('coverage_pct', 0)}%", color='primary', className='me-1'),
        dbc.Badge(f"갭 {item.get('gap_count', 0)}개", color='danger', className='me-1'),
        dbc.Badge(f"과제원 {item.get('member_count', 0)}명(분석 {item.get('analyzed_member_count', 0)}명)",
                  color='secondary', className='me-1'),
        html.Span(item.get('project_name', ''), className='small text-muted ms-1'),
    ], className='mb-2')
    if not comps:
        return html.Div([summary, _empty('이 과제의 필요 역량이 없습니다.')])
    return html.Div([summary, _competency_table(item)])


def competency_gap_section() -> html.Div:
    title = '과제별 역량'
    hint = ('과제 문서 분석에서 LLM이 뽑은 필요 역량을 행별로 보여주고, 역량마다 소속 과제원을 임베딩 유사도 구간별로, '
            '비소속 임직원은 유사도 0.75 이상(없으면 미만 대표 최대 5명)으로 보여줍니다. 배지 숫자는 유사도, 마우스를 올리면 근거 항목.')
    items = _gap_items()
    if not items:
        return _section(title, hint, _empty('데이터 없음 — pipeline/run_analysis.py(5/5 과제별 역량 갭) 실행 후 표시됩니다.'))
    drop = lambda id_, label, opts: dbc.Col([
        dbc.Label(label, className='small fw-semibold text-muted mb-1'),
        dcc.Dropdown(id=id_, options=opts, placeholder='전체' if id_ != 'org-gap-project' else '과제 선택', clearable=True),
    ], md=4)
    controls = dbc.Row([
        drop('org-gap-l1', '플랫폼', _opts(_lv(i, 'level1') for i in items)),
        drop('org-gap-l2', '그룹', _opts(_lv(i, 'level2') for i in items)),
        drop('org-gap-project', '과제', sorted(
            ({'label': (_lv(i, 'level3') if _lv(i, 'level3') != _NO_LEVEL else i.get('project_name', '')),
              'value': i.get('project_name', '')} for i in items), key=lambda o: o['label'])),
    ], className='g-2 mb-3')
    return _section(title, hint, html.Div([controls, html.Div(id='org-gap-detail')]))


def org_analysis_content() -> html.Div:
    from services.auth import can

    tabs = [dbc.Tab(competency_gap_section(), label='과제별 역량', tab_id='org-sub-gap'),
            dbc.Tab(collaboration_section(), label='부서 간 협업', tab_id='org-sub-collab')]
    if can('manage_users'):
        tabs.append(dbc.Tab(technology_holder_section(), label='기술별 보유자 수', tab_id='org-sub-tech'))
    return dbc.Tabs(tabs, id='org-sub-tabs', active_tab='org-sub-gap', className='mt-2')
