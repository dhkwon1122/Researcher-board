"""
전역 자연어 질문 바 — "특정 전문성 보유자 찾기"/"과제에 적합한 사람 찾기"/
"연구원에게 맞는 과제 찾기"(구조화 조회) + 그 밖의 원천 데이터 개방형 질문
(services.open_data_query, SQL 생성)을 4개 intent 모두 같은 표 형태
(columns/labels/rows)로 받아 하나의 렌더러로 보여준다. 자세한 아키텍처는
services/nl_query.py, services/open_data_query.py 모듈 docstring 참고.

원래 "보유 전문성" 탭(pages/researcher_similarity_map.py) 안에만 있었는데,
전 탭에서 상시 노출되도록 app.py의 최상위 레이아웃(네비게이션 바로 아래)으로
옮겼다 — 이전 페이지 전용 "연구원 목록" 탭의 AI 검색(services/text2sql.py
기반, PostgreSQL 전용)을 대체하는 단일 전역 검색으로 통합.

Dash 콜백 설계 메모(재발 방지 — data/processed/CLAUDE.md에도 기록):
매 렌더링마다 새로 나타나는 컴포넌트(정렬/필터 드롭다운, 행 체크박스 등)에
건 콜백은, Dash가 "새로 나타난 컴포넌트"를 클릭 없이 한 번 더 실행시키는
현상(팬텀 트리거)이 있다. 이번엔 그 컴포넌트를 고정시키는 대신, 모든
관련 콜백을 "현재 표시된 값들로부터 다음 상태를 그대로 계산"하는 순수
함수로 짜서(토글/증가가 아니라 대입) 팬텀 트리거가 와도 상태가 그대로
유지되게 했다 — 유일한 예외인 n_clicks 기반 콜백(엑셀 다운로드, 정렬/필터
초기화)은 `if not n_clicks: return dash.no_update`로 직접 방어한다.
"""

import json

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, dcc, html

from services import nl_query
from services import query_settings
from services import researcher_profile_export


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


def render() -> html.Div:
    """전역 자연어 질문 바 레이아웃 — app.py가 네비게이션 바로 아래에 한 번만
    삽입해 모든 탭에서 항상 보이게 한다."""
    return html.Div([
        html.Div([
            html.H5(
                [html.I(className='bi bi-robot me-2 text-primary'), 'AI 검색',
                 html.Small(' 자연어로 물어보면 원천 데이터를 조회합니다', className='text-muted fw-normal')],
                className='fw-bold mb-0 mt-1',
            ),
            dbc.Button(
                [html.I(className='bi bi-gear me-1'), '규칙 설정'],
                id='nl-query-rules-toggle-btn', color='link', size='sm',
                className='text-decoration-none', n_clicks=0,
            ),
        ], className='d-flex justify-content-between align-items-center mb-1'),
        dbc.Collapse(
            dbc.Card(
                dbc.CardBody([
                    html.Div(
                        '용어 정의나 답변 형식을 직접 지시할 수 있습니다. 예: '
                        '"상위평가는 가 또는 나 등급을 의미한다", '
                        '"인원수를 물으면 항상 표 아래에 합계를 같이 보여줘"',
                        className='text-muted small mb-2',
                    ),
                    dcc.Textarea(
                        id='nl-query-rules-textarea',
                        value='', placeholder='추가 규칙을 한 줄에 하나씩 입력하세요.',
                        style={'width': '100%', 'height': '100px'},
                        className='mb-2',
                    ),
                    html.Div([
                        dbc.Button('저장', id='nl-query-rules-save-btn', color='primary',
                                   size='sm', n_clicks=0),
                        html.Span(id='nl-query-rules-save-msg', className='ms-2'),
                    ]),
                ]),
                className='mb-2',
            ),
            id='nl-query-rules-collapse', is_open=False,
        ),
        dbc.InputGroup([
            dbc.Input(
                id='nl-query-input', type='text', debounce=False,
                placeholder='예: "로봇 제어 전문가 찾아줘", "차세대로봇제어 과제에 적합한 사람은?", '
                            '"물리학 전공한 사람 찾아줘"',
            ),
            dbc.Button([html.I(className='bi bi-search me-1'), '질문하기'],
                       id='nl-query-submit', color='primary', n_clicks=0),
            dbc.Button([html.I(className='bi bi-x-circle me-1'), '초기화'],
                       id='nl-query-reset-btn', color='secondary', outline=True, n_clicks=0),
        ], className='mb-2'),
        dcc.Loading(html.Div([
            html.Div(id='nl-query-result'),
            # 토글 버튼은 레이아웃에 상시 존재(숨김/라벨만 콜백으로 갱신) — 모듈
            # docstring의 팬텀 트리거 메모 참고.
            dbc.Button('', id='nl-query-toggle-btn', color='link', size='sm',
                       className='p-0 mt-1', style={'display': 'none'}, n_clicks=0),
            dcc.Store(id='nl-query-full-result'),
            dcc.Store(id='nl-query-filters', data={}),
            dcc.Store(id='nl-query-sort', data={}),
            dcc.Store(id='nl-query-expanded', data=False),
            dcc.Store(id='nl-query-selected', data=[]),
        ])),
        html.Div([
            dbc.Button('', id='nl-query-excel-btn', color='success', outline=True, size='sm',
                       className='mt-2 me-2', style={'display': 'none'}, n_clicks=0, disabled=True),
            dbc.Checklist(
                id='nl-query-excel-options-check',
                options=[
                    {'label': '보유 전문성 포함', 'value': 'expertise'},
                    {'label': '특허 포함', 'value': 'patents'},
                    {'label': '논문 포함', 'value': 'publications'},
                ],
                value=[], switch=True, inline=True,
                className='mt-2 small', style={'display': 'none'},
            ),
        ], className='d-flex align-items-center'),
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


def _answer_block(answer: str):
    return dbc.Alert([
        html.Div([html.I(className='bi bi-robot me-2'), html.Span('AI 답변', className='fw-semibold')],
                 className='mb-1'),
        html.Div(answer, className='small', style={'whiteSpace': 'pre-wrap'}),
    ], color='primary', className='mb-2')


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
    """선택된 행에서 researcher_id를 뽑는다. 한 질문의 결과에 같은 연구원이
    여러 행(예: 과제/논문/특허별로 한 행씩)으로 나올 수 있어, 그중 여러 행을
    선택하면 같은 사람이 중복으로 잡힐 수 있다 — 처음 나온 순서를 유지하며
    중복을 제거해 "선택 N명" 표시와 엑셀 다운로드 둘 다 같은 사람의 프로필이
    여러 번 나오지 않게 한다."""
    columns = (full_result or {}).get('columns') or []
    if 'researcher_id' not in columns or not selected:
        return []
    idx = columns.index('researcher_id')
    rows = (full_result or {}).get('rows') or []
    seen = set()
    out = []
    for i in selected:
        if i < len(rows) and idx < len(rows[i]) and rows[i][idx]:
            rid = str(rows[i][idx]).strip().zfill(8)
            if rid not in seen:
                seen.add(rid)
                out.append(rid)
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
    Output('nl-query-rules-collapse', 'is_open'),
    Output('nl-query-rules-textarea', 'value'),
    Input('nl-query-rules-toggle-btn', 'n_clicks'),
    State('nl-query-rules-collapse', 'is_open'),
    prevent_initial_call=True,
)
def _toggle_rules_panel(n_clicks, is_open):
    """열 때마다 디스크에서 최신 규칙을 다시 읽는다 — render()가 앱 시작
    시점에 한 번만 호출되므로(다른 세션이 그 사이 저장한 내용을 못 보는
    문제 방지), 텍스트를 layout에 미리 심어 두지 않고 여기서 매번 갱신."""
    if not n_clicks:
        return dash.no_update, dash.no_update
    next_open = not is_open
    if next_open:
        return True, query_settings.read_rules()
    return False, dash.no_update


@callback(
    Output('nl-query-rules-save-msg', 'children'),
    Input('nl-query-rules-save-btn', 'n_clicks'),
    State('nl-query-rules-textarea', 'value'),
    prevent_initial_call=True,
)
def _save_rules(n_clicks, text):
    if not n_clicks:
        return dash.no_update
    query_settings.write_rules(text or '')
    return html.Span([html.I(className='bi bi-check-circle-fill me-1'), '저장되었습니다.'],
                      className='text-success small')


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
        # 초기화 버튼이 full_result를 None으로 비웠을 때 화면도 실제로
        # 비워야 하므로(no_update면 이전 결과가 그대로 남음) 빈 children을
        # 명시적으로 반환한다.
        return None, '', {'display': 'none'}
    expanded = bool(expanded)
    children, total_filtered = _render_table_body(full_result, filters, sort, expanded, selected)
    answer = full_result.get('answer')
    if answer:
        children = html.Div([_answer_block(answer), children])
    if total_filtered > _PAGE_SIZE:
        label = '접기' if expanded else f'전체 {total_filtered}건 보기'
        style = {'display': 'inline-block'}
    else:
        label, style = '', {'display': 'none'}
    return children, label, style


@callback(
    Output('nl-query-input', 'value'),
    Output('nl-query-full-result', 'data', allow_duplicate=True),
    Output('nl-query-filters', 'data', allow_duplicate=True),
    Output('nl-query-sort', 'data', allow_duplicate=True),
    Output('nl-query-expanded', 'data', allow_duplicate=True),
    Output('nl-query-selected', 'data', allow_duplicate=True),
    Input('nl-query-reset-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def _reset_query(n_clicks):
    """검색창/답변/명단을 전부 초기 상태로 되돌린다(사용자 확정: 검색어
    텍스트까지 포함해 완전 초기화)."""
    if not n_clicks:
        return (dash.no_update,) * 6
    return '', None, {}, {}, False, []


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
    Output('nl-query-excel-options-check', 'style'),
    Input('nl-query-full-result', 'data'),
    Input('nl-query-selected', 'data'),
    prevent_initial_call=True,
)
def _update_excel_button(full_result, selected):
    columns = (full_result or {}).get('columns') or []
    if 'researcher_id' not in columns:
        return dash.no_update, {'display': 'none'}, dash.no_update, {'display': 'none'}
    n = len(_selected_researcher_ids(full_result, selected))
    label = [html.I(className='bi bi-file-earmark-excel me-1'),
              f'선택 {n}명 엑셀 다운로드' if n else '엑셀 다운로드 (행을 선택하세요)']
    return label, {'display': 'inline-block'}, n == 0, {'display': 'inline-block'}


@callback(
    Output('nl-query-excel-download', 'data'),
    Input('nl-query-excel-btn', 'n_clicks'),
    State('nl-query-full-result', 'data'),
    State('nl-query-selected', 'data'),
    State('nl-query-excel-options-check', 'value'),
    prevent_initial_call=True,
)
def _download_excel(n_clicks, full_result, selected, excel_options):
    if not n_clicks:
        return dash.no_update
    researcher_ids = _selected_researcher_ids(full_result, selected)
    if not researcher_ids:
        return dash.no_update
    excel_options = excel_options or []
    data = researcher_profile_export.build_profile_workbook(
        researcher_ids,
        include_expertise='expertise' in excel_options,
        include_patents='patents' in excel_options,
        include_publications='publications' in excel_options,
    )
    return dcc.send_bytes(data, researcher_profile_export.default_filename())
