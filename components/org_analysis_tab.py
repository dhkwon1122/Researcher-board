"""
"보유 전문성" 페이지의 "조직 분석" 탭(2026-10, 전문성 심화 지표 ③④⑤).

pipeline/process_expertise_metrics.py 등이 만든 조직 단위 집계 산출물을
보여준다. 산출물이 없으면(파이프라인 미실행) 섹션마다 안내 문구만 표시한다.

  - 부서 간 협업(collaboration_edges.csv) — 부서 쌍별 공동 논문·특허 건수와
    부서별 타부서 협업 비율. 모든 로그인 사용자.
  - 과제별 역량 갭(project_competency_gap.json) — 과제 필요 역량 대비 현재
    인력 충족 여부와 갭 역량의 사내 후보. 모든 로그인 사용자.
  - 기술별 보유자 수(핵심인력 리스크, technology_holder_summary.csv) —
    개인 명단이 들어 있어 관리자(manage_users)에게만 보인다.
"""

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import html

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


_STATUS_STYLE = {
    'styleConditions': [
        {'condition': "params.value === '갭'", 'style': {'color': '#cf1322', 'fontWeight': 600}},
        {'condition': "params.value === '충족'", 'style': {'color': '#389e0d'}},
    ],
    'defaultStyle': {'textAlign': 'center'},
}


def competency_gap_section() -> html.Div:
    title = '과제별 역량 갭'
    hint = ('과제 문서 분석 결과에서 LLM이 뽑은 필요 역량을 과제 현재 인력의 보유 역량(강점 분야·키워드·전문지식)과 '
            '임베딩 유사도로 대조. 유사도 0.75 이상이면 충족. 갭 역량은 과제 밖 재직자 중 유사도 상위 3명을 사내 후보로 표시.')
    items = read_project_competency_gap()
    if not items:
        return _section(title, hint, _empty('데이터 없음 — pipeline/run_analysis.py(5/5 과제별 역량 갭) 실행 후 표시됩니다.'))
    name_map = _name_map()

    def _people(lst):
        return ', '.join(f"{name_map.get(x.get('researcher_id', ''), x.get('researcher_id', ''))}"
                         f"({x.get('item', '')})" for x in lst or [])

    proj_rows, comp_rows = [], []
    for it in items:
        proj_rows.append({
            'project_name': it.get('project_name', ''), 'dep_name': it.get('dep_name', ''),
            'member_count': it.get('member_count', 0), 'coverage_pct': it.get('coverage_pct', 0),
            'gap_count': it.get('gap_count', 0),
            'gaps': ', '.join(c.get('competency', '') for c in it.get('competencies') or [] if not c.get('covered')),
        })
        for c in it.get('competencies') or []:
            comp_rows.append({
                'project_name': it.get('project_name', ''),
                'competency': c.get('competency', ''),
                'status': '충족' if c.get('covered') else '갭',
                'best_score': c.get('best_score', 0),
                'covered_by': _people(c.get('covered_by')),
                'candidates': _people(c.get('candidates')),
            })
    num = {'filter': 'agNumberColumnFilter', 'floatingFilter': True, 'width': 100}
    txt = {'filter': 'agTextColumnFilter', 'floatingFilter': True, 'minWidth': 150, 'flex': 1,
           'cellStyle': {'textAlign': 'left'}}
    proj_grid = _grid('org-gap-project-grid', [
        {'headerName': '과제', 'field': 'project_name', 'tooltipField': 'project_name', **txt},
        {'headerName': '부서', 'field': 'dep_name', **txt},
        {'headerName': '인력', 'field': 'member_count', **num},
        {'headerName': '충족률(%)', 'field': 'coverage_pct', **num},
        {'headerName': '갭 수', 'field': 'gap_count', **num},
        {'headerName': '갭 역량', 'field': 'gaps', 'tooltipField': 'gaps', **txt},
    ], proj_rows, page_size=10)
    comp_grid = _grid('org-gap-competency-grid', [
        {'headerName': '과제', 'field': 'project_name', 'tooltipField': 'project_name', **txt},
        {'headerName': '필요 역량', 'field': 'competency', 'tooltipField': 'competency', **txt},
        {'headerName': '상태', 'field': 'status', 'width': 80, 'cellStyle': _STATUS_STYLE,
         'filter': 'agTextColumnFilter', 'floatingFilter': True},
        {'headerName': '최고 유사도', 'field': 'best_score', **num},
        {'headerName': '충족 인력(근거)', 'field': 'covered_by', 'tooltipField': 'covered_by', **txt},
        {'headerName': '사내 후보(근거)', 'field': 'candidates', 'tooltipField': 'candidates', **txt},
    ], comp_rows, page_size=15)
    return _section(title, hint, html.Div([
        html.Div('과제별 요약 (충족률 낮은 순)', className='small text-muted mb-1'), proj_grid,
        html.Div('역량별 상세', className='small text-muted mt-3 mb-1'), comp_grid,
    ]))


def org_analysis_content() -> html.Div:
    from services.auth import can

    sections = [competency_gap_section(), collaboration_section()]
    if can('manage_users'):
        sections.append(technology_holder_section())
    if not sections:
        sections.append(_empty('표시할 조직 분석 항목이 없습니다.'))
    return html.Div(sections)
