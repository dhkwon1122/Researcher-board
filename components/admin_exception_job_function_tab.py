"""
관리자 페이지 "직군 예외자" 탭 — pages/admin.py 분할 리팩터링(2026-09-28)
으로 신설. 예외자 명단 그리드 CRUD와 엑셀 업로드 실행을 담당한다.
"""
import uuid
from datetime import date

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, no_update

from components.admin_shared import _alert, _ensure_rid, _renumbered, _run_status_view, _upload_box
from services import exception_job_function_store as ejf_store
from services import web_pipeline_runner as wpr


def _exception_job_function_tab() -> html.Div:
    """"직군 예외자" 관리 웹 CRUD 탭(2026-09-09) — mapping_job_function.csv
    기반 매칭 결과와 무관하게 특정 연구원의 SAIT 직군 표시를 강제로
    덮어쓰는 예외자 명단. 컬럼은 원본 헤더명 그대로(pipeline.
    process_exception_job_function._COL_MAP 재사용,
    services.exception_job_function_store 참고). 팀/리더 참조 탭과
    UX(그리드 CRUD + 엑셀 업로드)는 동일하지만, 시점(연/월) 이력이 없는
    "현재값만" 테이블이라 입력 날짜 선택기/대량 백필/부서ID 중복 모달 같은
    시점 관련 장치는 없다(사용자 확정 — 구조를 단순하게 유지).

    2026-09-17: 팀/리더 참조와 동일한 이유로 `dash_table.DataTable`에서
    AG Grid(dash-ag-grid)로 전환 — 자세한 배경/검증은 docs/CLAUDE.md의
    2026-09-17 "팀/리더 참조 그리드 — dash_table → dash-ag-grid" 항목
    참고. 이 탭은 하위 조직 계층이 없는 단순 평면 목록이라 `_row_path`/
    `_subtree_range`(cascade 삭제)는 애초에 필요 없다 — 삭제는 체크박스
    선택 + "선택 삭제" 버튼으로 통일했다(예전엔 `row_deletable`의 행별
    × 버튼이었는데, AG Grid Community엔 그 기본 UI가 없어 team_refer와
    같은 방식으로 교체)."""
    rows = _renumbered(_ensure_rid(ejf_store.list_editable_rows()))

    column_defs = [
        {
            'headerName': 'No.', 'field': '_no', 'editable': False,
            'sortable': False, 'filter': False, 'width': 70, 'pinned': 'left',
        },
    ] + [
        {'headerName': col, 'field': col, 'editable': True, 'tooltipField': col}
        for col in ejf_store.KOREAN_COLUMNS
    ]

    return html.Div([
        dbc.Row([
            dbc.Col([
                dbc.Label(' ', className='small d-block mb-1'),
                dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-plus-lg me-1'), '행 추가'],
                               id='exception-job-function-add-row-btn', color='secondary',
                               outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-trash me-1'), '선택 삭제'],
                               id='exception-job-function-bulk-delete-btn', color='danger',
                               outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-save me-1'), '저장'],
                               id='exception-job-function-save-btn', color='primary', size='sm'),
                    dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '엑셀 다운로드'],
                               id='exception-job-function-download-btn', color='success',
                               outline=True, size='sm'),
                ]),
            ], md='auto'),
        ], className='mb-2 align-items-end'),
        dcc.Download(id='exception-job-function-download'),
        html.Div(id='exception-job-function-bulk-msg'),

        dag.AgGrid(
            id='exception-job-function-table',
            className='gs-ag-grid',
            columnDefs=column_defs,
            rowData=rows,
            getRowId='params.data._rid',
            selectedRows=[],
            defaultColDef={
                'resizable': True, 'sortable': True, 'filter': False,
                'minWidth': 55, 'wrapHeaderText': True, 'autoHeaderHeight': True,
                'cellStyle': {'textAlign': 'center'},  # 헤더 가운데 정렬은 .gs-ag-grid(custom.css)가 처리
            },
            dashGridOptions={
                'rowSelection': {'mode': 'multiRow', 'checkboxes': True, 'headerCheckbox': True},
                'domLayout': 'autoHeight',
                'stopEditingWhenCellsLoseFocus': True,
                'tooltipShowDelay': 0,
            },
            style={'width': '100%'},
        ),

        html.Div(id='exception-job-function-save-msg', className='mt-2'),

        _exception_job_function_upload_section(),
    ], className='pt-3')


def _exception_job_function_upload_section():
    """"직군 예외자" 탭 안의 엑셀 업로드 UI(2026-09-09) — "팀/리더 참조" 탭의
    _team_refer_upload_section()과 동일한 패턴. 백엔드는 services/
    web_pipeline_runner.py의 'exception_job_function' 항목
    (hidden_from_table=True)을 그대로 재사용 — 업로드 저장/실행 로그가
    "데이터 업데이트" 탭의 다른 항목과 동일한 경로를 탄다. needs_valid_date가
    없어(시점 이력 없는 "현재값만" 테이블) 팀/리더 참조와 달리 "누적
    시점(연/월)" 입력도, 대량 백필 업로드도 없다."""
    row = next((r for r in wpr.snapshot() if r['key'] == 'exception_job_function'), None)
    if row is None:
        return None
    filenames = row['uploaded_filenames']
    filenames_view = (
        html.Div([html.Div(f, className='small') for f in filenames], className='mt-1')
        if filenames else html.Div('업로드된 파일 없음', className='small text-muted mt-1')
    )

    return dbc.Card(dbc.CardBody([
        html.Div([
            html.I(className='bi bi-file-earmark-excel me-2 text-success'),
            html.Span('엑셀 파일로 한 번에 반영', className='fw-semibold small'),
        ], className='mb-2'),
        dbc.Row([
            dbc.Col([
                html.Div('업로드(직무_직군_맵핑_예외자.xlsx)', className='small text-muted mb-1'),
                _upload_box('exception_job_function', 'single'),
                filenames_view,
            ], md=7),
            dbc.Col([
                html.Div(' ', className='small mb-1'),
                dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-play-fill me-1'), '실행'],
                               id='exception-job-function-run-upload-btn', color='primary', size='sm'),
                    dbc.Button(html.I(className='bi bi-download'),
                               id={'type': 'du-download', 'key': 'exception_job_function'},
                               color='link', size='sm', disabled=not row['has_upload'],
                               title='업로드한 원본 파일 다운로드'),
                ]),
            ], md=2),
            dbc.Col([
                html.Div('최종실행이력', className='small text-muted mb-1'),
                html.Div(id='exception-job-function-upload-status',
                         children=_run_status_view(row)),
            ], md=3),
        ], className='g-2 align-items-start'),
    ]), className='shadow-sm mb-3')


# ── 콜백: 직군 예외자 — 행 추가(2026-09-17: 항상 맨 뒤에 추가로 단순화 —
# team_refer_add_row와 같은 이유, AG Grid의 selectedRows는 클릭 위치가
# 아니라 체크된 행 전체를 담는 값이라 "클릭해둔 셀 다음" 방식을 그대로
# 재현하기 어렵다) ────────────────────────────────────────────────────────────
@callback(
    Output('exception-job-function-table', 'rowData', allow_duplicate=True),
    Output('exception-job-function-table', 'selectedRows', allow_duplicate=True),
    Input('exception-job-function-add-row-btn', 'n_clicks'),
    State('exception-job-function-table', 'rowData'),
    prevent_initial_call=True,
)
def exception_job_function_add_row(n_clicks, rows):
    if not n_clicks:
        return no_update, no_update
    rows = list(rows or [])
    new_row = {col: '' for col in ejf_store.KOREAN_COLUMNS}
    new_row['_rid'] = uuid.uuid4().hex[:12]
    rows.append(new_row)
    return _renumbered(rows), []


# ── 콜백: 직군 예외자 — 체크박스 선택 삭제(2026-09-17, AG Grid 전환과 함께
# row_deletable의 행별 × 버튼을 대체) ─────────────────────────────────────────
# 이 탭은 하위 조직 계층이 없는 평면 목록이라 team_refer_bulk_delete와 달리
# cascade 판정(_subtree_range) 없이 체크한 행만 그대로 지운다.
@callback(
    Output('exception-job-function-table', 'rowData', allow_duplicate=True),
    Output('exception-job-function-table', 'selectedRows', allow_duplicate=True),
    Output('exception-job-function-bulk-msg', 'children', allow_duplicate=True),
    Input('exception-job-function-bulk-delete-btn', 'n_clicks'),
    State('exception-job-function-table', 'rowData'),
    State('exception-job-function-table', 'selectedRows'),
    prevent_initial_call=True,
)
def exception_job_function_bulk_delete(n_clicks, rows, selected_rows):
    if not n_clicks:
        return no_update, no_update, no_update
    rows = list(rows or [])
    selected_rids = {r['_rid'] for r in (selected_rows or []) if r.get('_rid')}
    if not selected_rids:
        return no_update, no_update, _alert('삭제할 행을 먼저 체크해주세요.', 'warning')

    new_rows = [r for r in rows if r.get('_rid') not in selected_rids]
    new_rows = _renumbered(new_rows)
    msg = _alert(f'{len(rows) - len(new_rows)}개 행을 삭제했습니다. "저장"을 눌러야 실제로 반영됩니다.',
                 'success')
    return new_rows, [], msg


# ── 콜백: 직군 예외자 — 저장 ───────────────────────────────────────────────────
# 시점(연/월) 이력이 없는 "현재값만" 테이블이라 team_refer_save()와 달리
# valid_date/삭제 톰스톤 처리가 없다 — 그리드의 현재 내용 전체가 곧 저장될
# 값이다(services.exception_job_function_store.save_snapshot() 참고).
@callback(
    Output('exception-job-function-save-msg', 'children'),
    Input('exception-job-function-save-btn', 'n_clicks'),
    State('exception-job-function-table', 'rowData'),
    prevent_initial_call=True,
)
def exception_job_function_save(n_clicks, rows):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 저장할 수 있습니다.', 'danger')
    if not n_clicks:
        return no_update

    rows = rows or []
    valid_rows = [r for r in rows if str(r.get('사원번호') or '').strip()]
    skipped = len(rows) - len(valid_rows)

    result = ejf_store.save_snapshot(valid_rows)

    parts = [
        f"저장 완료 — {result['saved_rows']}건 반영"
        + ('' if result['db_ok'] else ' (DB 미반영, CSV에는 반영됨)') + '.',
    ]
    if skipped:
        parts.append(f'사원번호가 비어 있어 {skipped}행은 저장에서 제외됐습니다.')

    dupes = result.get('duplicate_researcher_ids') or []
    if dupes:
        ids = ', '.join(g['researcher_id'] for g in dupes[:5])
        more = f' 외 {len(dupes) - 5}건' if len(dupes) > 5 else ''
        parts.append(f'사원번호가 중복된 항목은 첫 번째 행만 반영됐습니다: {ids}{more}')

    alert_color = 'warning' if dupes else 'success'
    return dbc.Alert([html.Div(p) for p in parts], color=alert_color, dismissable=True,
                      className='py-2 small mb-0')


# ── 콜백: 직군 예외자 — 현재 기준 엑셀 다운로드 ────────────────────────────────
@callback(
    Output('exception-job-function-download', 'data'),
    Input('exception-job-function-download-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def exception_job_function_download(n_clicks):
    from services.auth import can
    if not n_clicks or not can('manage_users'):
        return no_update
    data = ejf_store.current_snapshot_workbook_bytes()
    fname = f"직군_예외자_{date.today().strftime('%Y%m%d')}.xlsx"
    return dcc.send_bytes(data, fname)


# ── 콜백: 직군 예외자 — 엑셀 업로드 실행 ───────────────────────────────────────
# hidden_from_table 항목이라 "데이터 업데이트" 탭의 전체/선택 실행 버튼과
# 무관한 이 탭 전용 실행 트리거가 필요하다(team_refer_run_upload()와 동일한
# 이유). needs_valid_date가 없어 연/월 State가 필요 없다.
@callback(
    Output('exception-job-function-upload-status', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input('exception-job-function-run-upload-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def exception_job_function_run_upload(n_clicks):
    from services.auth import can
    if not n_clicks:
        return no_update, no_update
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True
    if not wpr.has_upload('exception_job_function'):
        return _alert('업로드된 파일이 없습니다.', 'warning'), True

    if not wpr.start_run(['exception_job_function']):
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False
    return (_alert('실행을 시작했습니다. 브라우저를 닫아도 서버에서 계속 진행되며, '
                    '화면은 자동으로 갱신됩니다.', 'info'), False)
