"""
관리자 페이지 "AI 검색 테스트" 탭(2026-10, 사용자 요청) — 백엔드는 services/ai_search_lab.py.

흐름: ① 질문 만들기(LLM 생성 + 정답 대조 질문) → ② 질문 목록 편집/세트 저장 → ③ 일괄 실행(서버
백그라운드, 화면을 닫아도 계속) → ④ 결과 확인(상태/정답 대조 F1/LLM 심사/SQL) · 이전 실행과 비교 ·
엑셀 · 개선 제안. 컴포넌트 id는 모두 'lab-' 접두사.
"""
import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, no_update

from components.admin_shared import _alert
from services import ai_search_lab as lab
from services import nl_query_curation as cur

try:  # 개선 반영 기능 제거(2026-10-09) — 이미 반영돼 있던 규칙/예시를 1회 전부 끈다(표식 파일로 중복 방지)
    cur.disable_all_once()
except Exception as _exc:  # 데이터 폴더 접근 불가 등 — 화면 로딩을 막지 않는다
    print(f'[ai_search_lab] 반영 규칙/예시 비활성화 실패: {_exc}')

_STATUS_COLOR = {'양호': 'success', '주의': 'warning', '실패': 'danger'}
_STATUS_STYLE = {
    'styleConditions': [
        {'condition': "params.value === '실패'", 'style': {'color': '#cf1322', 'fontWeight': 600}},
        {'condition': "params.value === '주의'", 'style': {'color': '#d46b08', 'fontWeight': 600}},
        {'condition': "params.value === '양호'", 'style': {'color': '#389e0d'}},
    ],
    'defaultStyle': {'textAlign': 'center'},
}
_GRID_DEFAULT = {'resizable': True, 'sortable': True, 'wrapHeaderText': True, 'autoHeaderHeight': True,
                 'cellStyle': {'textAlign': 'center'}}


def _question_rows(items: list[dict]) -> list[dict]:
    return [{'id': it.get('id', ''), 'category': it.get('category', ''), 'question': it.get('question', ''),
             'expected_desc': (it.get('expected') or {}).get('desc', ''), '_expected': it.get('expected')}
            for it in items]


def _items_from_rows(rows) -> list[dict]:
    return [{'id': r.get('id', ''), 'category': r.get('category', ''), 'question': r.get('question', ''),
             'expected': r.get('_expected')} for r in (rows or [])]


def _job_view():
    st = lab.job_state()
    kinds = {'generate': '질문 생성', 'run': '일괄 실행', 'suggest': '개선 제안'}
    kind = kinds.get(st['kind'], '')
    if st['status'] == 'running':
        progress = f"{st['done']}/{st['total']} · " if st['total'] > 1 else ''
        return html.Div([html.Span(className='spinner-border spinner-border-sm me-2'),
                         f"{kind} 중(서버에서 계속 실행 — 다른 화면으로 이동해도 됩니다) · {progress}경과 {st['elapsed']}초 · {st['message']}"],
                        className='small text-primary fw-semibold')
    if st['status'] == 'done':
        return html.Div([html.I(className='bi bi-check-circle-fill text-success me-1'), f'{kind} 완료 — {st["message"]}'],
                        className='small')
    if st['status'] == 'stopped':
        return html.Div([html.I(className='bi bi-stop-circle-fill text-warning me-1'),
                         f'{kind} 중지됨 — 지금까지 {st["done"]}건 결과가 저장돼 있습니다'], className='small')
    if st['status'] == 'error':
        return html.Div([html.I(className='bi bi-exclamation-triangle-fill text-danger me-1'),
                         f'{kind} 실패 — {st["message"]}'], className='small text-danger')
    return html.Div('질문을 만들거나 불러온 뒤 실행하세요.', className='small text-muted')


def _run_options():
    opts = []
    for r in lab.list_runs():
        s = r['summary']
        opts.append({'label': f"{r['label']} ({r['started'][5:16]}, {s['n']}건 · 양호 {s['양호']}/주의 {s['주의']}/실패 {s['실패']})",
                     'value': r['run_id']})
    return opts


def _question_grid():
    return dag.AgGrid(
        id='lab-question-grid', className='gs-ag-grid',
        columnDefs=[
            {'headerName': '카테고리', 'field': 'category', 'width': 170, 'editable': True,
             'cellEditor': 'agSelectCellEditor',
             'cellEditorParams': {'values': list(lab.CATEGORIES) + [lab.GOLDEN_CATEGORY, '기타']}},
            {'headerName': '질문 (더블클릭으로 수정)', 'field': 'question', 'editable': True, 'flex': 1, 'minWidth': 320,
             'cellStyle': {'textAlign': 'left'}, 'tooltipField': 'question'},
            {'headerName': '정답 대조 기준', 'field': 'expected_desc', 'width': 260, 'cellStyle': {'textAlign': 'left'},
             'tooltipField': 'expected_desc'},
        ],
        rowData=_question_rows(lab.load_draft()), defaultColDef=_GRID_DEFAULT,
        dashGridOptions={'rowSelection': {'mode': 'multiRow', 'checkboxes': True, 'headerCheckbox': True},
                         'domLayout': 'normal', 'tooltipShowDelay': 0,
                         'pagination': True, 'paginationPageSize': 25},
        style={'height': '420px'},
    )


def _result_grid():
    num = {'filter': 'agNumberColumnFilter', 'floatingFilter': True, 'width': 90}
    txt = {'filter': 'agTextColumnFilter', 'floatingFilter': True}
    return dag.AgGrid(
        id='lab-result-grid', className='gs-ag-grid',
        columnDefs=[
            {'headerName': '상태', 'field': 'status', 'width': 90, 'cellStyle': _STATUS_STYLE, **txt},
            {'headerName': '카테고리', 'field': 'category', 'width': 150, **txt},
            {'headerName': '질문', 'field': 'question', 'flex': 1, 'minWidth': 260, 'cellStyle': {'textAlign': 'left'},
             'tooltipField': 'question', **txt},
            {'headerName': '유형', 'field': 'intent', 'width': 150, **txt},
            {'headerName': '건수', 'field': 'row_count', **num},
            {'headerName': '시간(초)', 'field': 'seconds', **num},
            {'headerName': '정답 F1', 'field': 'f1', **num},
            {'headerName': '심사', 'field': 'score', **num},
            {'headerName': '문제 유형', 'field': 'issue', 'width': 140, **txt},
            {'headerName': '플래그', 'field': 'flags', 'width': 150, **txt},
            {'headerName': '이전 상태', 'field': 'prev_status', 'width': 90, 'hide': True},
            {'headerName': '이전 심사', 'field': 'prev_score', 'width': 90, 'hide': True},
            {'headerName': '심사 변화', 'field': 'delta_score', 'width': 90, 'hide': True},
        ],
        rowData=[], defaultColDef=_GRID_DEFAULT, columnSize=None,
        dashGridOptions={'rowSelection': {'mode': 'singleRow', 'checkboxes': False}, 'tooltipShowDelay': 0,
                         'pagination': True, 'paginationPageSize': 20},
        style={'height': '460px'},
    )


def _ai_search_lab_tab() -> html.Div:
    return html.Div([
        dcc.Interval(id='lab-interval', interval=2500, disabled=not lab.is_busy()),
        dcc.Store(id='lab-tick', data=None),
        dcc.Download(id='lab-download'),

        dbc.Alert([html.I(className='bi bi-info-circle me-2'),
                   '내부 LLM으로 사전 질문을 만들어 실제 AI 검색 경로로 일괄 실행하고, 정답 대조·LLM 심사로 품질을 확인합니다. '
                   '실행은 서버에서 계속 돌아 오래 걸려도(수십 분) 화면을 닫아도 됩니다. 일반 AI 검색 로그에는 남지 않고, '
                   '현재 로그인한 관리자 권한으로 조회됩니다.'],
                  color='light', className='small border mb-3'),

        dbc.Card(dbc.CardBody([
            html.Div('① 질문 만들기', className='fw-semibold small mb-2'),
            dbc.Row([
                dbc.Col([
                    html.Div('카테고리(LLM이 생성)', className='small text-muted mb-1'),
                    dbc.Checklist(id='lab-categories', options=[{'label': c, 'value': c} for c in lab.CATEGORIES],
                                  value=list(lab.CATEGORIES), className='small', inline=True),
                ], md=7),
                dbc.Col([
                    html.Div('카테고리당 개수', className='small text-muted mb-1'),
                    dbc.Input(id='lab-per-category', type='number', value=8, min=1, max=30, size='sm'),
                ], md=2),
                dbc.Col([
                    dbc.Checklist(id='lab-gen-options', value=['golden'], className='small', options=[
                        {'label': '정답 대조 질문 포함(데이터로 정답 계산)', 'value': 'golden'},
                        {'label': '기존 목록 교체(끄면 뒤에 추가)', 'value': 'replace'}]),
                    dbc.Button([html.I(className='bi bi-magic me-1'), '질문 생성'], id='lab-generate-btn',
                               color='primary', size='sm', className='mt-2'),
                ], md=3),
            ], className='g-2'),
        ]), className='shadow-sm mb-3'),

        dbc.Card(dbc.CardBody([
            html.Div([html.Span('② 질문 목록', className='fw-semibold small me-3'),
                      html.Span('셀을 더블클릭해 질문/카테고리를 고칠 수 있고, 행을 체크해 "선택 삭제"하거나 선택한 질문만 실행할 수 있습니다.',
                                className='small text-muted')], className='mb-2'),
            _question_grid(),
            dbc.Row([
                dbc.Col(dbc.ButtonGroup([
                    dbc.Button('행 추가', id='lab-add-btn', color='secondary', outline=True, size='sm'),
                    dbc.Button('선택 삭제', id='lab-del-btn', color='danger', outline=True, size='sm'),
                    dbc.Button('작업 목록 저장', id='lab-save-draft-btn', color='secondary', outline=True, size='sm'),
                ]), md='auto'),
                dbc.Col(dbc.InputGroup([
                    dbc.Input(id='lab-set-name', placeholder='세트 이름', size='sm', type='text'),
                    dbc.Button('세트로 저장', id='lab-save-set-btn', color='secondary', outline=True, size='sm'),
                ], size='sm'), md=3),
                dbc.Col(dbc.InputGroup([
                    dcc.Dropdown(id='lab-set-select', options=[{'label': n, 'value': n} for n in lab.list_sets()],
                                 placeholder='저장된 세트', style={'minWidth': '180px'}),
                    dbc.Button('불러오기', id='lab-load-set-btn', color='secondary', outline=True, size='sm'),
                ], size='sm'), md=4),
            ], className='g-2 mt-2 align-items-center'),
            html.Div(id='lab-edit-msg', className='mt-2'),
        ]), className='shadow-sm mb-3'),

        dbc.Card(dbc.CardBody([
            html.Div('③ 일괄 실행', className='fw-semibold small mb-2'),
            dbc.Row([
                dbc.Col([html.Div('실행 이름', className='small text-muted mb-1'),
                         dbc.Input(id='lab-run-label', placeholder='예: 규칙 추가 전', size='sm', type='text')], md=3),
                dbc.Col([html.Div('검색 기준', className='small text-muted mb-1'),
                         dbc.RadioItems(id='lab-current-only', value='current', inline=True, className='small', options=[
                             {'label': '현재', 'value': 'current'}, {'label': '누적', 'value': 'all'}])], md=2),
                dbc.Col([html.Div('대상', className='small text-muted mb-1'),
                         dbc.RadioItems(id='lab-target', value='all', inline=True, className='small', options=[
                             {'label': '전체', 'value': 'all'}, {'label': '선택한 행', 'value': 'selected'}])], md=3),
                dbc.Col([html.Div(' ', className='small mb-1'),
                         dbc.Checklist(id='lab-judge', value=['judge'], className='small',
                                       options=[{'label': 'LLM 심사 사용(느려짐)', 'value': 'judge'}])], md=2),
                dbc.Col(dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-play-fill me-1'), '실행'], id='lab-run-btn', color='primary', size='sm'),
                    dbc.Button([html.I(className='bi bi-stop-fill me-1'), '중지'], id='lab-stop-btn', color='secondary',
                               outline=True, size='sm')]), md=2),
            ], className='g-2 align-items-end'),
            html.Div(_job_view(), id='lab-status', className='mt-2'),
        ]), className='shadow-sm mb-3'),

        dbc.Card(dbc.CardBody([
            html.Div('④ 결과', className='fw-semibold small mb-2'),
            dbc.Row([
                dbc.Col([html.Div('실행 선택', className='small text-muted mb-1'),
                         dcc.Dropdown(id='lab-run-select', options=_run_options(), placeholder='실행 이력', clearable=True)], md=5),
                dbc.Col([html.Div('비교할 이전 실행(선택)', className='small text-muted mb-1'),
                         dcc.Dropdown(id='lab-compare-select', options=_run_options(), placeholder='이전 실행과 비교', clearable=True)], md=4),
                dbc.Col(dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '엑셀'], id='lab-excel-btn',
                               color='success', outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-lightbulb me-1'), '개선 제안'], id='lab-suggest-btn',
                               color='warning', outline=True, size='sm')]), md=3, className='pt-4'),
            ], className='g-2'),
            html.Div(id='lab-summary', className='my-2'),
            _result_grid(),
            html.Div(id='lab-detail', className='mt-3'),
            html.Div(id='lab-suggestion', className='mt-3'),
        ]), className='shadow-sm mb-3'),
    ], className='pt-3')

# ── 콜백: 질문 목록 편집 ──────────────────────────────────────────────────────

@callback(
    Output('lab-question-grid', 'rowData', allow_duplicate=True),
    Output('lab-edit-msg', 'children', allow_duplicate=True),
    Input('lab-add-btn', 'n_clicks'),
    Input('lab-del-btn', 'n_clicks'),
    Input('lab-save-draft-btn', 'n_clicks'),
    Input('lab-save-set-btn', 'n_clicks'),
    Input('lab-load-set-btn', 'n_clicks'),
    State('lab-question-grid', 'virtualRowData'),
    State('lab-question-grid', 'selectedRows'),
    State('lab-set-name', 'value'),
    State('lab-set-select', 'value'),
    prevent_initial_call=True,
)
def lab_edit_questions(_a, _d, _sd, _ss, _l, rows, selected, set_name, set_select):
    from services.auth import can
    if not can('manage_users'):
        return no_update, _alert('관리자만 사용할 수 있습니다.', 'danger')
    trig = dash.ctx.triggered_id
    rows = list(rows or [])
    if trig == 'lab-add-btn':
        rows.append({'id': '', 'category': '기타', 'question': '새 질문', 'expected_desc': '', '_expected': None})
        return rows, no_update
    if trig == 'lab-del-btn':
        drop_q = {(r.get('question'), r.get('category')) for r in (selected or [])}
        if not drop_q:
            return no_update, _alert('삭제할 행을 체크하세요.', 'warning')
        rows = [r for r in rows if (r.get('question'), r.get('category')) not in drop_q]
        lab.save_draft(_items_from_rows(rows))
        return rows, _alert(f'{len(drop_q)}건 삭제했습니다.', 'success')
    if trig == 'lab-save-draft-btn':
        lab.save_draft(_items_from_rows(rows))
        return no_update, _alert(f'작업 목록 {len(rows)}건을 저장했습니다.', 'success')
    if trig == 'lab-save-set-btn':
        if not (set_name or '').strip():
            return no_update, _alert('세트 이름을 입력하세요.', 'warning')
        name = lab.save_set(set_name, _items_from_rows(rows))
        return no_update, _alert(f'세트 "{name}"로 {len(rows)}건을 저장했습니다.', 'success')
    if trig == 'lab-load-set-btn':
        if not set_select:
            return no_update, _alert('불러올 세트를 고르세요.', 'warning')
        items = lab.load_set(set_select)
        lab.save_draft(items)
        return _question_rows(lab.load_draft()), _alert(f'세트 "{set_select}" {len(items)}건을 불러왔습니다.', 'success')
    return no_update, no_update


@callback(
    Output('lab-status', 'children', allow_duplicate=True),
    Output('lab-interval', 'disabled', allow_duplicate=True),
    Input('lab-generate-btn', 'n_clicks'),
    State('lab-categories', 'value'),
    State('lab-per-category', 'value'),
    State('lab-gen-options', 'value'),
    prevent_initial_call=True,
)
def lab_generate(n_clicks, categories, per_category, options):
    from services.auth import can, get_current_user
    if not n_clicks:
        return no_update, no_update
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True
    ok, reason = lab.start_generate(categories or [], int(per_category or 8), 'golden' in (options or []),
                                    'replace' in (options or []), get_current_user())
    if not ok:
        return _alert(reason, 'warning'), not lab.is_busy()
    return _job_view(), False


@callback(
    Output('lab-status', 'children', allow_duplicate=True),
    Output('lab-interval', 'disabled', allow_duplicate=True),
    Input('lab-run-btn', 'n_clicks'),
    State('lab-question-grid', 'virtualRowData'),
    State('lab-question-grid', 'selectedRows'),
    State('lab-target', 'value'),
    State('lab-current-only', 'value'),
    State('lab-judge', 'value'),
    State('lab-run-label', 'value'),
    prevent_initial_call=True,
)
def lab_run(n_clicks, rows, selected, target, current_only, judge, label):
    from services.auth import can, get_current_user
    if not n_clicks:
        return no_update, no_update
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True
    source = selected if (target == 'selected') else rows
    if target == 'selected' and not source:
        return _alert('"선택한 행"을 고르려면 질문 행을 체크하세요.', 'warning'), not lab.is_busy()
    items = _items_from_rows(source)
    lab.save_draft(_items_from_rows(rows))      # 실행 시점의 목록을 작업 목록으로도 남긴다
    ok, reason, _rid = lab.start_run(items, get_current_user(), label=(label or '').strip(),
                                     current_only=(current_only != 'all'), judge='judge' in (judge or []))
    if not ok:
        return _alert(reason, 'warning'), not lab.is_busy()
    return _job_view(), False


@callback(
    Output('lab-status', 'children', allow_duplicate=True),
    Input('lab-stop-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def lab_stop(n_clicks):
    from services.auth import can
    if not n_clicks or not can('manage_users'):
        return no_update
    lab.stop()
    return _alert('중지를 요청했습니다 — 지금 처리 중인 질문까지 마치고 멈춥니다.', 'info')


# ── 콜백: 상태 폴링 → 질문/결과 갱신 ──────────────────────────────────────────

@callback(
    Output('lab-status', 'children', allow_duplicate=True),
    Output('lab-interval', 'disabled', allow_duplicate=True),
    Output('lab-tick', 'data'),
    Input('lab-interval', 'n_intervals'),
    prevent_initial_call=True,
)
def lab_poll(_n):
    st = lab.job_state()
    tick = {'status': st['status'], 'kind': st['kind'], 'run_id': st['run_id'], 'updated_at': st['updated_at'],
            'done': st['done']}
    return _job_view(), st['status'] != 'running', tick


@callback(
    Output('lab-question-grid', 'rowData', allow_duplicate=True),
    Output('lab-set-select', 'options'),
    Output('lab-run-select', 'options'),
    Output('lab-compare-select', 'options'),
    Output('lab-run-select', 'value', allow_duplicate=True),
    Input('lab-tick', 'data'),
    State('lab-run-select', 'value'),
    prevent_initial_call=True,
)
def lab_refresh_after_job(tick, current_run):
    if not tick:
        return no_update, no_update, no_update, no_update, no_update
    set_opts = [{'label': n, 'value': n} for n in lab.list_sets()]
    run_opts = _run_options()
    questions = _question_rows(lab.load_draft()) if (tick['kind'] == 'generate' and tick['status'] == 'done') else no_update
    # 일괄 실행 중/직후에는 그 실행을 자동으로 선택해 진행 중 결과가 계속 갱신되게 한다
    run_value = tick['run_id'] if tick['kind'] in ('run', 'suggest') and tick['run_id'] else no_update
    return questions, set_opts, run_opts, run_opts, run_value


def _result_rows(run: dict, prev: dict | None) -> list[dict]:
    cmp_by_q = {c['question']: c for c in lab.compare_runs(prev, run)} if prev else {}
    rows = []
    for r in run.get('results') or []:
        g, j = r.get('golden') or {}, r.get('judge') or {}
        c = cmp_by_q.get(r['question'], {})
        rows.append({'question': r['question'], 'category': r['category'], 'status': r['status'],
                     'intent': r['intent'], 'row_count': r['row_count'], 'seconds': r['seconds'],
                     'f1': g.get('f1'), 'score': j.get('score'), 'issue': j.get('issue_type', ''),
                     'flags': ', '.join(r['flags']), 'prev_status': c.get('status_before', ''),
                     'prev_score': c.get('score_before'), 'delta_score': c.get('delta_score')})
    return rows


@callback(
    Output('lab-result-grid', 'rowData'),
    Output('lab-result-grid', 'columnDefs'),
    Output('lab-summary', 'children'),
    Output('lab-suggestion', 'children'),
    Input('lab-run-select', 'value'),
    Input('lab-compare-select', 'value'),
    Input('lab-tick', 'data'),
    State('lab-result-grid', 'columnDefs'),
    prevent_initial_call=True,
)
def lab_show_results(run_id, compare_id, _tick, col_defs):
    if not run_id:
        return [], no_update, html.Div('실행을 선택하세요.', className='small text-muted'), ''
    run = lab.load_run(run_id)
    prev = lab.load_run(compare_id) if compare_id and compare_id != run_id else None
    s = lab.summarize(run)
    summary = html.Div([
        dbc.Badge(f"양호 {s['양호']}", color='success', className='me-1'),
        dbc.Badge(f"주의 {s['주의']}", color='warning', text_color='dark', className='me-1'),
        dbc.Badge(f"실패 {s['실패']}", color='danger', className='me-2'),
        html.Span(f"{run.get('label', '')} · {s['n']}건 · 평균 심사 {s['avg_score'] if s['avg_score'] is not None else '-'}"
                  f" · 평균 정답 F1 {s['avg_f1'] if s['avg_f1'] is not None else '-'} · 평균 {s['avg_seconds'] or '-'}초"
                  + (f" · 상태 {run.get('status')}" if run.get('status') != 'done' else ''),
                  className='small'),
    ] + ([html.Span(f" · 이전 실행({prev.get('label', '')}) 대비 변화 컬럼 표시", className='small text-muted')]
         if prev else []))
    defs = []
    for d in col_defs or []:
        d = dict(d)
        if d.get('field') in ('prev_status', 'prev_score', 'delta_score'):
            d['hide'] = prev is None
        defs.append(d)
    suggestion = ''
    if run.get('suggestion'):
        suggestion = dbc.Card(dbc.CardBody([
            html.Div('개선 제안 — 검토 후 "규칙 설정"에 직접 반영하세요(자동 적용 안 됨)', className='fw-semibold small mb-2'),
            html.Pre(run['suggestion'], className='small mb-0', style={'whiteSpace': 'pre-wrap'}),
        ]), className='border-warning')
    return _result_rows(run, prev), defs, summary, suggestion


@callback(
    Output('lab-detail', 'children'),
    Input('lab-result-grid', 'selectedRows'),
    State('lab-run-select', 'value'),
    prevent_initial_call=True,
)
def lab_show_detail(selected, run_id):
    if not selected or not run_id:
        return ''
    question = selected[0].get('question')
    run = lab.load_run(run_id)
    rec = next((r for r in run.get('results') or [] if r['question'] == question), None)
    if not rec:
        return ''
    g, j = rec.get('golden'), rec.get('judge')
    parts = [html.Div([dbc.Badge(rec['status'], color=_STATUS_COLOR.get(rec['status'], 'light'), className='me-2'),
                       html.Span(rec['question'], className='fw-semibold')], className='mb-2'),
             html.Div(f"유형 {rec['intent']} · {rec['row_count']}건(전체 {rec['total_rows']}) · {rec['seconds']}초 · "
                      f"플래그 {', '.join(rec['flags']) or '없음'}", className='small text-muted mb-2')]
    if g:
        parts.append(html.Div(f"정답 대조 — {g.get('desc', '')}: 기대 {g['expected']}명 / 반환 {g['returned']}명, 정밀도 {g['precision']}, "
                              f"재현율 {g['recall']}, F1 {g['f1']}" +
                              (f" · 빠진 사번 예: {', '.join(g['missing_sample'])}" if g['missing_sample'] else '') +
                              (f" · 기대에 없던 사번 예: {', '.join(g['extra_sample'])}" if g['extra_sample'] else ''),
                              className='small mb-2'))
    if j:
        parts.append(html.Div(f"LLM 심사 {j['score']}점 · {j['issue_type']} — {j['reason']}", className='small mb-2'))
    if rec.get('sql'):
        parts += [html.Div('생성된 SQL', className='small text-muted'),
                  html.Pre(rec['sql'], className='small border rounded p-2 bg-light', style={'whiteSpace': 'pre-wrap'})]
    if rec.get('answer') or rec.get('note'):
        parts += [html.Div('시스템 설명/안내', className='small text-muted'),
                  html.Pre(rec.get('answer') or rec.get('note'), className='small border rounded p-2 bg-light',
                           style={'whiteSpace': 'pre-wrap'})]
    if rec.get('sample_rows'):
        head = rec.get('columns') or []
        parts.append(html.Div('결과 일부', className='small text-muted'))
        parts.append(html.Div(dbc.Table([html.Thead(html.Tr([html.Th(c) for c in head])),
                                         html.Tbody([html.Tr([html.Td(v or '') for v in row]) for row in rec['sample_rows']])],
                                        size='sm', bordered=True, className='small'),
                              style={'overflowX': 'auto'}))
    return dbc.Card(dbc.CardBody(parts), className='border')


@callback(
    Output('lab-download', 'data'),
    Input('lab-excel-btn', 'n_clicks'),
    State('lab-run-select', 'value'),
    prevent_initial_call=True,
)
def lab_download(n_clicks, run_id):
    from services.auth import can
    if not n_clicks or not run_id or not can('manage_users'):
        return no_update
    run = lab.load_run(run_id)
    if not run:
        return no_update
    return dcc.send_bytes(lab.build_run_workbook(run), f'AI검색테스트_{run_id}.xlsx')


@callback(
    Output('lab-status', 'children', allow_duplicate=True),
    Output('lab-interval', 'disabled', allow_duplicate=True),
    Input('lab-suggest-btn', 'n_clicks'),
    State('lab-run-select', 'value'),
    prevent_initial_call=True,
)
def lab_suggest(n_clicks, run_id):
    from services.auth import can
    if not n_clicks:
        return no_update, no_update
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True
    if not run_id:
        return _alert('개선 제안을 만들 실행을 먼저 선택하세요.', 'warning'), not lab.is_busy()
    ok, reason = lab.start_suggest(run_id)
    if not ok:
        return _alert(reason, 'warning'), not lab.is_busy()
    return _job_view(), False
