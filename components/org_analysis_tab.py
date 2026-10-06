"""
"보유 전문성" 페이지의 "조직 분석" 탭(2026-10, 전문성 심화 지표 ③④⑤).

pipeline/process_expertise_metrics.py 등이 만든 조직 단위 집계 산출물을
보여준다. 산출물이 없으면(파이프라인 미실행) 섹션마다 안내 문구만 표시한다.

  - 기술별 보유자 수(핵심인력 리스크, technology_holder_summary.csv) —
    개인 명단이 들어 있어 관리자(manage_users)에게만 보인다.
"""

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import html

from services.data_store import read_processed

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


def org_analysis_content() -> html.Div:
    from services.auth import can

    sections = []
    if can('manage_users'):
        sections.append(technology_holder_section())
    if not sections:
        sections.append(_empty('표시할 조직 분석 항목이 없습니다.'))
    return html.Div(sections)
