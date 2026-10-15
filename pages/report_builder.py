"""
업무 시나리오 > 조서 작성(2026-10-15, 사용자 요청) — 엑셀 열을 직접 구성해 내려받는 화면.

대상자(플랫폼/과제/개별 연구원) → 양식(열마다 헤더 이름 + 넣을 항목 1개 이상 + 묶는 방식) → 미리보기(첫 3명) →
엑셀 다운로드. 양식은 이름을 붙여 저장·불러오기(개인 양식, 관리자는 공용 양식도). 로직은 services/report_builder.py.

열 편집기 구조: rb-columns(Store)는 "열 구조"(추가·삭제·순서 바꾸기·양식 불러오기)가 바뀔 때만 갱신하고 그때만 편집기를
다시 그린다 — 헤더 입력처럼 값만 바뀔 때마다 다시 그리면 입력 중 포커스가 사라지므로, 값은 미리보기·저장·다운로드 때
화면의 입력값(State ALL)에서 직접 읽는다.
"""
import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

dash.register_page(__name__, path='/report-builder', name='조서 작성', title='조서 작성')

_MAX_PREVIEW = 3


def _user():
    from services.auth import can, get_current_user
    u = get_current_user() or {}
    return u.get('user_id', ''), bool(u.get('is_admin')), {'view_evaluation': can('view_evaluation'),
                                                            'view_incentive': can('view_incentive')}


def _template_options(user_id: str) -> list:
    from services import report_builder as rb
    out = []
    for t in rb.list_templates(user_id):
        tag = '기본' if t.get('builtin') else ('공용' if t.get('shared') else '내 양식')
        out.append({'label': f"[{tag}] {t['name']}", 'value': t['id']})
    return out


def _column_row(i: int, n: int, col: dict, field_options: list, join_options: list):
    return dbc.Row([
        dbc.Col(html.Span(f'{i + 1}', className='fw-bold text-muted'), width='auto', className='pt-2'),
        dbc.Col(dbc.Input(id={'type': 'rb-h', 'index': i}, value=col.get('header', ''), size='sm',
                          placeholder='헤더 이름(비우면 항목 이름으로)'), md=3),
        dbc.Col(dcc.Dropdown(id={'type': 'rb-f', 'index': i}, options=field_options, value=col.get('fields') or [],
                             multi=True, placeholder='넣을 항목(여러 개 선택 시 아래 방식으로 묶음)'), md=5),
        dbc.Col(dcc.Dropdown(id={'type': 'rb-j', 'index': i}, options=join_options, value=col.get('join') or 'paren',
                             clearable=False), md=2),
        dbc.Col(html.Div([
            dbc.Button(html.I(className='bi bi-arrow-up'), id={'type': 'rb-up', 'index': i}, size='sm',
                       color='light', className='me-1 border', disabled=i == 0, title='위로'),
            dbc.Button(html.I(className='bi bi-arrow-down'), id={'type': 'rb-down', 'index': i}, size='sm',
                       color='light', className='me-1 border', disabled=i == n - 1, title='아래로'),
            dbc.Button(html.I(className='bi bi-x-lg'), id={'type': 'rb-del', 'index': i}, size='sm',
                       color='light', className='border text-danger', title='열 삭제'),
        ], className='d-flex'), width='auto'),
    ], className='g-2 mb-2 align-items-start')


def layout(**_kwargs):
    from services import report_builder as rb
    from services import similarity_map as sm
    from services.data_store import filter_current, read_processed
    user_id, is_admin, perms = _user()
    res = filter_current(read_processed('researchers'))
    people = [{'label': f"{r.get('name', '')} ({r['researcher_id']}) · {r.get('department', '')}", 'value': r['researcher_id']}
              for r in res.fillna('').to_dict('records')] if not res.empty else []
    default = rb.default_template()
    return html.Div([
        html.H5([html.I(className='bi bi-file-earmark-spreadsheet me-2 text-primary'), '조서 작성'],
                className='fw-bold mb-1 mt-1'),
        html.Div('엑셀 열을 직접 구성해 내려받습니다 — 열마다 헤더 이름, 넣을 항목, 묶는 방식을 정하고 양식으로 저장해 다시 쓸 수 있습니다.',
                 className='text-muted small mb-3'),
        dcc.Store(id='rb-columns', data=default['columns']),
        dcc.Store(id='rb-template-id', data=default['id']),
        dcc.Store(id='rb-field-options', data=rb.field_options(perms)),
        html.Div(id='rb-alert'),

        dbc.Card(dbc.CardBody([
            html.Div('1. 대상자', className='fw-semibold mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('플랫폼', className='small text-muted mb-1'),
                         dcc.Dropdown(id='rb-l1', options=sm.level_filter_options(1), multi=True, placeholder='선택')], md=4),
                dbc.Col([dbc.Label('과제', className='small text-muted mb-1'),
                         dcc.Dropdown(id='rb-l3', options=sm.level_filter_options(3), multi=True, placeholder='선택')], md=4),
                dbc.Col([dbc.Label('개별 연구원', className='small text-muted mb-1'),
                         dcc.Dropdown(id='rb-people', options=people, multi=True, placeholder='이름 또는 사번')], md=4),
            ], className='g-2'),
            html.Div(id='rb-target-count', className='small text-muted mt-2'),
        ]), className='mb-3'),

        dbc.Card(dbc.CardBody([
            html.Div('2. 양식', className='fw-semibold mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('양식 불러오기', className='small text-muted mb-1'),
                         dcc.Dropdown(id='rb-template', options=_template_options(user_id), value=default['id'],
                                      clearable=False)], md=5),
                dbc.Col([dbc.Label('양식 이름', className='small text-muted mb-1'),
                         dbc.Input(id='rb-name', value='', size='sm', placeholder='저장할 이름')], md=3),
                dbc.Col([html.Label('여러 건 항목 최대', className='small text-muted mb-1 d-block',
                                    title='과제수행이력·논문·특허 등 한 칸에 여러 줄이 들어가는 항목을 화면 표시 순서대로 N건까지만(비우면 전부)'),
                         dbc.Input(id='rb-max', type='number', min=1, value=None, size='sm', placeholder='전부')], md=2),
                dbc.Col(dbc.Checkbox(id='rb-shared', label='공용 양식', value=False, disabled=not is_admin,
                                     className='mt-4 small'), md=2),
            ], className='g-2 mb-2'),
            html.Div([
                dbc.Button('저장', id='rb-save', size='sm', color='primary', className='me-1'),
                dbc.Button('다른 이름으로 저장', id='rb-save-as', size='sm', color='primary', outline=True, className='me-1'),
                dbc.Button('삭제', id='rb-delete', size='sm', color='danger', outline=True, className='me-1'),
                dbc.Button('새 양식(빈 열)', id='rb-new', size='sm', color='secondary', outline=True),
            ], className='mb-3'),
            dbc.Row([
                dbc.Col(width='auto'), dbc.Col(html.Small('헤더 이름', className='text-muted'), md=3),
                dbc.Col(html.Small('넣을 항목', className='text-muted'), md=5),
                dbc.Col(html.Small('묶는 방식', className='text-muted'), md=2),
            ], className='g-2'),
            html.Div(id='rb-editor'),
            dbc.Button([html.I(className='bi bi-plus-lg me-1'), '열 추가'], id='rb-add', size='sm',
                       color='secondary', outline=True, className='mt-1'),
        ]), className='mb-3'),

        dbc.Card(dbc.CardBody([
            html.Div([html.Span('3. 미리보기', className='fw-semibold me-2'),
                      html.Small(f'(대상자 중 처음 {_MAX_PREVIEW}명)', className='text-muted')], className='mb-2'),
            html.Div(id='rb-preview', style={'overflowX': 'auto'}),
            dbc.Button([html.I(className='bi bi-file-earmark-arrow-down me-1'), '엑셀 다운로드'], id='rb-download-btn',
                       color='success', className='mt-2'),
            dcc.Download(id='rb-download'),
        ]), className='mb-4'),
    ])


def _join_options():
    from services import report_builder as rb
    return [{'label': v, 'value': k} for k, v in rb.JOINS.items()]


@callback(Output('rb-editor', 'children'), Input('rb-columns', 'data'), State('rb-field-options', 'data'))
def _render_editor(columns, field_options):
    columns = columns or []
    if not columns:
        return html.Div('열이 없습니다 — "열 추가"를 누르세요.', className='text-muted small mb-2')
    jo = _join_options()
    return [_column_row(i, len(columns), c, field_options or [], jo) for i, c in enumerate(columns)]


def _current(headers, fields, joins) -> list:
    return [{'header': h or '', 'fields': f or [], 'join': j or 'paren'} for h, f, j in zip(headers, fields, joins)]


@callback(Output('rb-columns', 'data'),
          Input('rb-add', 'n_clicks'), Input('rb-new', 'n_clicks'),
          Input({'type': 'rb-del', 'index': ALL}, 'n_clicks'),
          Input({'type': 'rb-up', 'index': ALL}, 'n_clicks'),
          Input({'type': 'rb-down', 'index': ALL}, 'n_clicks'),
          State({'type': 'rb-h', 'index': ALL}, 'value'),
          State({'type': 'rb-f', 'index': ALL}, 'value'),
          State({'type': 'rb-j', 'index': ALL}, 'value'),
          prevent_initial_call=True)
def _structure(_add, _new, _dels, _ups, _downs, headers, fields, joins):
    trig = ctx.triggered[0] if ctx.triggered else {}
    if not trig.get('value'):          # 편집기를 다시 그리면서 생긴 버튼(n_clicks=None) — 무시
        return no_update
    cols = _current(headers, fields, joins)
    tid = ctx.triggered_id
    if tid == 'rb-add':
        cols.append({'header': '', 'fields': [], 'join': 'paren'})
    elif tid == 'rb-new':
        cols = [{'header': '', 'fields': [], 'join': 'paren'}]
    elif isinstance(tid, dict):
        i = tid['index']
        if tid['type'] == 'rb-del' and 0 <= i < len(cols):
            cols.pop(i)
        elif tid['type'] == 'rb-up' and 0 < i < len(cols):
            cols[i - 1], cols[i] = cols[i], cols[i - 1]
        elif tid['type'] == 'rb-down' and 0 <= i < len(cols) - 1:
            cols[i + 1], cols[i] = cols[i], cols[i + 1]
    return cols


@callback(Output('rb-columns', 'data', allow_duplicate=True), Output('rb-template-id', 'data'),
          Output('rb-name', 'value'), Output('rb-max', 'value'), Output('rb-shared', 'value'),
          Input('rb-template', 'value'), prevent_initial_call=True)
def _load_template(template_id):
    from services import report_builder as rb
    user_id, _admin, _perms = _user()
    t = rb.get_template(template_id, user_id) if template_id else None
    if not t:
        return no_update, no_update, no_update, no_update, no_update
    return (t['columns'], t['id'], '' if t.get('builtin') else t['name'], t.get('max_items'),
            bool(t.get('shared')) and not t.get('builtin'))


@callback(Output('rb-target-count', 'children'),
          Input('rb-l1', 'value'), Input('rb-l3', 'value'), Input('rb-people', 'value'))
def _target_count(l1, l3, people):
    from services import report_builder as rb
    n = len(rb.resolve_targets(l1, l3, people))
    return f'대상 {n}명 (현재 재직자, 선택 조건의 합집합)' if n else '플랫폼·과제·개별 연구원 중 하나 이상 선택하세요.'


@callback(Output('rb-preview', 'children'),
          Input({'type': 'rb-h', 'index': ALL}, 'value'),
          Input({'type': 'rb-f', 'index': ALL}, 'value'),
          Input({'type': 'rb-j', 'index': ALL}, 'value'),
          Input('rb-max', 'value'), Input('rb-l1', 'value'), Input('rb-l3', 'value'), Input('rb-people', 'value'))
def _preview(headers, fields, joins, max_items, l1, l3, people):
    from services import report_builder as rb
    ids = rb.resolve_targets(l1, l3, people)
    cols = rb.clean_columns(_current(headers, fields, joins))
    if not cols:
        return html.Div('항목을 고른 열이 없습니다.', className='text-muted small')
    if not ids:
        return html.Div('대상자를 선택하면 미리보기가 표시됩니다.', className='text-muted small')
    from services.researcher_profile_export import prepare_rows
    ordered, _ctx, _p = prepare_rows(ids)
    head, rows, _ = rb.build_table(ordered[:_MAX_PREVIEW], cols, max_items)
    cell = {'whiteSpace': 'pre-line', 'fontSize': '0.75rem', 'verticalAlign': 'middle'}
    return dbc.Table([
        html.Thead(html.Tr([html.Th(h, style={**cell, 'textAlign': 'center', 'background': '#F3F5F9'}) for h in head])),
        html.Tbody([html.Tr([html.Td(v, style=cell) for v in r]) for r in rows]),
    ], bordered=True, size='sm', className='mb-0')


@callback(Output('rb-download', 'data'), Output('rb-alert', 'children', allow_duplicate=True),
          Input('rb-download-btn', 'n_clicks'),
          State({'type': 'rb-h', 'index': ALL}, 'value'),
          State({'type': 'rb-f', 'index': ALL}, 'value'),
          State({'type': 'rb-j', 'index': ALL}, 'value'),
          State('rb-max', 'value'), State('rb-l1', 'value'), State('rb-l3', 'value'), State('rb-people', 'value'),
          State('rb-name', 'value'), prevent_initial_call=True)
def _download(_n, headers, fields, joins, max_items, l1, l3, people, name):
    from services import report_builder as rb
    ids = rb.resolve_targets(l1, l3, people)
    cols = rb.clean_columns(_current(headers, fields, joins))
    if not ids or not cols:
        return no_update, dbc.Alert('대상자와 항목이 있는 열을 먼저 정하세요.', color='warning', dismissable=True)
    data = rb.build_workbook(ids, cols, max_items)
    return dcc.send_bytes(data, rb.default_filename(name or '조서')), None


@callback(Output('rb-alert', 'children'), Output('rb-template', 'options'), Output('rb-template', 'value'),
          Input('rb-save', 'n_clicks'), Input('rb-save-as', 'n_clicks'), Input('rb-delete', 'n_clicks'),
          State('rb-template-id', 'data'), State('rb-name', 'value'), State('rb-max', 'value'), State('rb-shared', 'value'),
          State({'type': 'rb-h', 'index': ALL}, 'value'),
          State({'type': 'rb-f', 'index': ALL}, 'value'),
          State({'type': 'rb-j', 'index': ALL}, 'value'),
          prevent_initial_call=True)
def _save_delete(_s, _sa, _d, template_id, name, max_items, shared, headers, fields, joins):
    from services import report_builder as rb
    user_id, is_admin, _perms = _user()
    action = ctx.triggered_id
    try:
        if action == 'rb-delete':
            if not template_id or template_id == rb.DEFAULT_TEMPLATE_ID:
                raise ValueError('기본 양식은 삭제할 수 없습니다.')
            rb.delete_template(template_id, user_id, is_admin)
            return (dbc.Alert('양식을 삭제했습니다.', color='info', dismissable=True, duration=4000),
                    _template_options(user_id), rb.DEFAULT_TEMPLATE_ID)
        overwrite = action == 'rb-save' and template_id and template_id != rb.DEFAULT_TEMPLATE_ID
        t = rb.save_template(user_id, name, _current(headers, fields, joins), max_items, bool(shared), is_admin,
                             template_id if overwrite else None)
        return (dbc.Alert(f"'{t['name']}' 양식을 저장했습니다.", color='success', dismissable=True, duration=4000),
                _template_options(user_id), t['id'])
    except (ValueError, PermissionError) as exc:
        return dbc.Alert(str(exc), color='warning', dismissable=True), no_update, no_update
