"""
관리자 페이지 "데이터 업데이트" 탭 — pages/admin.py 분할 리팩터링
(2026-09-28)으로 신설. 매니페스트 등록 파일 업로드/실행/DB 반영, 과제별컨플
PDF 첨부, 진행 상황 폴링을 담당한다. data_update_poll()은 팀/리더 참조·
직군 예외자 탭의 업로드 상태 자리도 함께 갱신하므로(hidden_from_table 항목),
team_refer_store와 admin_shared의 공용 헬퍼도 함께 가져온다.
"""
import base64
import os
from datetime import date

import dash
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, dcc, html, no_update

from components.admin_shared import (
    _alert, _ensure_rid, _mark_stale_rows, _renumbered, _run_status_view, _split_hidden_rows,
    _STATUS_COLORS, _upload_box,
)
from services import confl_tree, team_refer_store
from services import web_pipeline_runner as wpr


def _valid_period_picker(key: str, year: int, month: int):
    """"누적 시점(연/월)" 입력 — 일(day) 없이 연/월만, 연이 왼쪽/월이 오른쪽,
    월은 숫자(1월~12월) 표기(2026-09-01, 사용자 확정). dcc.DatePickerSingle은
    일 단위 선택만 지원하고 팝업 캘린더 헤더도 영문이라, 연/월 각각 별도
    dcc.Dropdown 두 개로 대체했다."""
    year_options = [{'label': f'{y}년', 'value': y}
                     for y in range(year - _VALID_YEAR_SPAN_BACK, year + _VALID_YEAR_SPAN_FWD + 1)]
    month_options = [{'label': f'{m}월', 'value': m} for m in range(1, 13)]
    return dbc.Row([
        dbc.Col(dcc.Dropdown(
            id={'type': 'du-valid-year', 'key': key}, options=year_options, value=year,
            clearable=False, searchable=False, style={'minWidth': '92px'},
        ), width='auto'),
        dbc.Col(dcc.Dropdown(
            id={'type': 'du-valid-month', 'key': key}, options=month_options, value=month,
            clearable=False, searchable=False, style={'minWidth': '76px'},
        ), width='auto'),
    ], className='g-1 justify-content-center')


# 연도 드롭다운 범위 — 과거 백필(소급 반영)과 근시일 소급 입력을 모두 커버.
_VALID_YEAR_SPAN_BACK = 6
_VALID_YEAR_SPAN_FWD = 1


def _api_button(key: str, has_api: bool):
    return dbc.Button(
        [html.I(className='bi bi-cloud-arrow-down me-1'),
         'API로 가져오기' if has_api else 'API 연동 예정'],
        id={'type': 'du-api', 'key': key},
        color='primary' if has_api else 'secondary',
        outline=True, size='sm', className='py-0 px-1',
        style={'fontSize': '0.68rem'},
    )


def _data_update_row(row: dict) -> html.Tr:
    key = row['key']

    if row['mode'] == 'dual':
        upload_cell = html.Div([
            html.Div("① '18.5월 이전", className='small text-muted mb-1'),
            _upload_box(key, 'legacy', '업로드'),
            html.Div("② '18.5월 이후", className='small text-muted mt-2 mb-1'),
            _upload_box(key, 'new', '업로드'),
        ])
    else:
        upload_cell = _upload_box(key, 'single', multiple=row['needs_valid_date'])

    filenames = row['uploaded_filenames']
    filenames_view = (
        html.Div([html.Div(f, className='small') for f in filenames], className='mt-1')
        if filenames else html.Div('업로드된 파일 없음', className='small text-muted mt-1')
    )

    # 대량 백필 대기 파일(파일명이 "_YYYYMM"으로 끝나는 것들, 2026-08-28) —
    # 실행을 누르면 오래된 시점부터 순서대로 전부 반영된다.
    backfill_view = None
    if row['needs_valid_date'] and row.get('backfill_files'):
        bf = row['backfill_files']
        backfill_view = html.Div([
            html.Div(
                [html.I(className='bi bi-layers me-1'), f'백필 대기 {len(bf)}건 ({bf[0][1]} ~ {bf[-1][1]})'],
                className='small text-info fw-semibold mt-1',
            ),
            html.Div(
                '한 파일에 "_YYYYMM"(예: _202305)을 붙여 여러 개를 한 번에 올리면, '
                '실행 시 오래된 시점부터 순서대로 전부 반영됩니다.',
                className='text-muted', style={'fontSize': '0.68rem'},
            ),
        ])

    status = row['status']
    status_badge = (
        dbc.Badge([html.I(className='bi bi-arrow-repeat me-1'), '실행중'], color='info')
        if status == '실행중'
        else dbc.Badge(status or '-', color=_STATUS_COLORS.get(status, 'secondary'))
    )

    api_btn = _api_button(key, row['has_api'])

    # 업로드 파일 형식 안내는 구분 라벨 옆 호버 아이콘으로만 보여준다(2026-09-01,
    # 사용자 확정) — 표에 항상 보이는 텍스트 줄 대신 필요할 때만 마우스 오버로.
    hint_icon_id = f'du-hint-icon-{key}'
    label_with_hint = html.Div([
        html.Span(row['label'], className='fw-semibold'),
        html.I(className='bi bi-question-circle ms-1', id=hint_icon_id,
               style={'fontSize': '0.75rem', 'color': '#6c757d', 'cursor': 'help'}),
        dbc.Tooltip(row['hint'], target=hint_icon_id, placement='right'),
    ])

    # "누적 시점(연/월)" — "현재상태" 성격 항목(evaluations/core_technology/
    # job_profile/work_objective_*)만 별도 컬럼으로 보여준다(2026-09-01,
    # 사용자 확정 — "구분" 셀에서 분리). 과거 시점으로 잘못 지정하면
    # process_*.py가 기존 최신 값을 보호하려고 그 사람 행을 건너뛴다(정상
    # 동작, 실행결과 메시지로 안내). 기본값은 오늘.
    today = date.today()
    valid_period_cell = (
        _valid_period_picker(key, today.year, today.month)
        if row['needs_valid_date'] else html.Span('-', className='text-muted')
    )

    # 최종실행이력 — 실행 시각 + 이번 실행이 API였는지 업로드였는지(2026-09-01,
    # 사용자 확정). 아직 한 번도 실행한 적 없으면(source 빈 문자열) 배지 자체를
    # 안 보여준다.
    source = row.get('source', '')
    source_badge = (
        dbc.Badge(source, color='info' if source == 'API' else 'secondary',
                  className='mt-1', style={'fontSize': '0.62rem'})
        if source else None
    )

    return html.Tr([
        # dbc.Checkbox는 블록 레벨 .form-check div로 렌더링되어(inline 요소가
        # 아니라서) 부모 Td의 text-center가 먹지 않는다 — flex로 직접
        # 가운데 정렬한다(사용자 확정 2026-09-02).
        html.Td(html.Div(dbc.Checkbox(id={'type': 'du-check', 'key': key}, value=False,
                                       className='du-check-box'),
                          className='d-flex justify-content-center'),
                className='align-middle text-center'),
        html.Td(label_with_hint, className='align-middle text-center'),
        html.Td([upload_cell, filenames_view, backfill_view], className='align-middle', style={'minWidth': '220px'}),
        html.Td(valid_period_cell, className='align-middle text-center'),
        html.Td([
            dbc.Button(html.I(className='bi bi-download'), id={'type': 'du-download', 'key': key},
                       color='link', size='sm', disabled=not row['has_upload'], className='p-0'),
            html.Div(row['uploaded_at'] or '-', className='small text-muted'),
        ], className='align-middle text-center'),
        html.Td(api_btn, className='align-middle text-center'),
        html.Td([row['last_run_at'] or '-', html.Div(source_badge)], className='align-middle small text-center'),
        html.Td([status_badge, html.Div(row['message'], className='small text-muted mt-1',
                                         title=row['message'])],
                className='align-middle', style={'minWidth': '200px'}),
    ])


_DATA_UPDATE_TABLE_COLSPAN = 8

# 표시 순서: 공용(공용파일) → 대시보드용 → LLM분석용(2026-09-01, 사용자 확정
# — 순서 그대로). 각 값은 run_pipeline.py(대시보드)와 run_expertise.py(LLM
# 분석) 두 파이프라인 스크립트가 실제로 그 항목의 process_*.py를 호출하는지
# 코드 호출 그래프를 대조해 web_pipeline_runner.MANIFEST의 pipeline_scope로
# 이미 분류돼 있다(services/web_pipeline_runner.py 참고) — 여기서는 그 값
# 기준으로 그룹만 나눈다.
_DATA_UPDATE_SCOPES = [
    ('common', '공용파일 (대시보드 · LLM분석 공통)'),
    ('dashboard', '대시보드용'),
    ('llm', 'LLM분석용'),
]


def _data_update_section_header(label: str) -> html.Tr:
    return html.Tr(html.Td(label, colSpan=_DATA_UPDATE_TABLE_COLSPAN,
                            className='fw-semibold small text-muted',
                            style={'backgroundColor': 'var(--gs-header-bg)'}))


def _data_update_table() -> dbc.Table:
    # hidden_from_table 항목(팀/리더 참조 — 그 탭 안에 별도 업로드 UI로
    # 이동, 2026-09-01 사용자 확정)은 이 표에서 뺀다.
    rows = [r for r in wpr.snapshot() if not r['hidden_from_table']]
    # 표 자체가 dash_table.DataTable이 아니라 일반 dbc.Table이라 컬럼 너비
    # 드래그 조절 기능이 없다 — 헤더 텍스트를 감싸는 span에 브라우저 네이티브
    # CSS resize를 적용해 우측 하단 모서리를 드래그해 조절할 수 있게 한다
    # (팀/리더 참조 표의 .column-header-name과 같은 방식, assets/custom.css
    # 의 .admin-table .du-th-resize 참고, 사용자 확정 2026-09-02).
    def _th(label: str, style: dict | None = None) -> html.Th:
        return html.Th(html.Span(label, className='du-th-resize'), style=style)

    header = html.Thead(html.Tr([
        _th('체크', style={'width': '48px'}), _th('구분'), _th('업로드'),
        _th('누적 시점(연/월)'), _th('이전 Data'), _th('API 연동'),
        _th('최종실행이력'), _th('실행결과'),
    ]))
    body_rows: list = []
    for scope_key, scope_label in _DATA_UPDATE_SCOPES:
        # 그룹이 비어 있어도(현재 LLM분석용) 헤더는 항상 보여준다
        # (2026-09-01, 사용자 확정 — "그룹 3개 유지, 비어있으면 그대로 비움").
        body_rows.append(_data_update_section_header(scope_label))
        body_rows.extend(_data_update_row(r) for r in rows if r['pipeline_scope'] == scope_key)
    body = html.Tbody(body_rows)
    return dbc.Table([header, body], bordered=True, hover=True, responsive=True, size='sm',
                      className='align-middle mb-0 admin-table')


def _db_status_view() -> html.Span:
    s = wpr.db_load_status()
    if not s.get('last_run_at'):
        return html.Span('DB 반영: 아직 실행한 적 없음', className='text-muted small')
    color = _STATUS_COLORS.get(s['status'], 'secondary')
    return html.Span([
        html.Span('DB 반영 ', className='small text-muted'),
        dbc.Badge(s['status'] or '-', color=color, className='me-2'),
        html.Span(s['last_run_at'], className='text-muted small me-2'),
        html.Span(s.get('message', ''), className='small'),
    ])


def _confl_pdf_upload_section():
    """"과제별컨플"에서 컨플 주소가 없는 과제의 PDF 대체 첨부(2026-09-01,
    사용자 요청) — 지금까지는 서버 파일시스템(data/raw/conflue_MPR/)에
    직접 파일을 갖다 놓아야 했는데, 여기서 웹으로 올릴 수 있게 한다.
    파일명이 project_confl_address.csv의 "과제명"과 정확히 같아야
    pipeline/pdf_reader.py가 찾는다. 실제 소비(텍스트 추출·LLM 요약)는
    과제 전문성 분석 CLI(run_expertise.py)가 나중에 별도로 하므로, 다른
    MANIFEST 항목과 달리 이 섹션에는 "실행" 버튼이 없다 — 파일을 정확한
    이름으로 두기만 하면 된다."""
    pdfs = wpr.list_confl_pdfs()
    missing = wpr.confl_projects_missing_pdf()

    if pdfs:
        rows_view = html.Div([
            html.Div([
                dbc.Checkbox(id={'type': 'confl-pdf-check', 'name': p['filename']}, value=False,
                             className='me-2 mb-0'),
                html.I(className='bi bi-file-earmark-pdf me-1 text-danger'),
                html.Span(p['filename'], className='me-2'),
                html.Span(f"{p['size_kb']}KB · {p['uploaded_at']}",
                          className='text-muted', style={'fontSize': '0.7rem'}),
                dbc.Button(html.I(className='bi bi-x'),
                           id={'type': 'confl-pdf-delete', 'name': p['filename']},
                           color='link', size='sm', className='p-0 ms-2 text-danger',
                           title='삭제'),
            ], className='d-flex align-items-center mb-1')
            for p in pdfs
        ], style={'maxHeight': '260px', 'overflowY': 'auto'})
        # 선택/전체 삭제(2026-10, 사용자 요청) — 파일마다 X를 누르지 않아도 되게 한다.
        # 되돌릴 수 없는 삭제라 확인창(ConfirmDialogProvider)을 거친다.
        toolbar = html.Div([
            dbc.Checkbox(id='confl-pdf-select-all', label=f'전체 선택 ({len(pdfs)}건)', value=False,
                         className='small me-3 mb-0'),
            dcc.ConfirmDialogProvider(
                children=dbc.Button([html.I(className='bi bi-trash me-1'), '선택 삭제'],
                                    color='danger', outline=True, size='sm', className='me-2'),
                id='confl-pdf-del-selected-confirm',
                message='선택한 PDF를 삭제할까요? 되돌릴 수 없습니다.',
            ),
            dcc.ConfirmDialogProvider(
                children=dbc.Button([html.I(className='bi bi-trash3 me-1'), '전체 삭제'],
                                    color='danger', size='sm'),
                id='confl-pdf-del-all-confirm',
                message=f'업로드된 PDF {len(pdfs)}건을 전부 삭제할까요? 되돌릴 수 없습니다.',
            ),
        ], className='d-flex align-items-center mb-2')
        pdf_list_view = html.Div([toolbar, rows_view])
    else:
        pdf_list_view = html.Div('업로드된 PDF 없음', className='small text-muted')

    missing_view = None
    if missing:
        preview = ', '.join(missing[:8]) + (f' 외 {len(missing) - 8}건' if len(missing) > 8 else '')
        missing_view = html.Div(
            [html.I(className='bi bi-exclamation-circle me-1'),
             f'컨플 주소도 PDF도 없는 과제 {len(missing)}건: {preview}'],
            className='small text-warning mt-2',
        )

    return dbc.Card(dbc.CardBody([
        html.Div([
            html.I(className='bi bi-file-earmark-pdf me-2 text-danger'),
            html.Span('과제별컨플 — 컨플 주소 없는 과제 PDF 첨부', className='fw-semibold small'),
            html.I(className='bi bi-question-circle ms-1', id='confl-pdf-hint-icon',
                   style={'fontSize': '0.75rem', 'color': '#6c757d', 'cursor': 'help'}),
            dbc.Tooltip(
                '컨플 주소가 없는 과제는 여기 PDF(Monthly Report 등)를 올려두면 '
                '과제 전문성 분석 때 컨플루언스 대신 이 내용을 씁니다. 파일명이 '
                '과제별컨플의 "과제명"과 정확히 같아야 합니다(예: 지능형 물류 '
                '시스템.pdf).',
                target='confl-pdf-hint-icon', placement='right',
            ),
        ], className='mb-2'),
        dbc.Row([
            dbc.Col(
                dcc.Upload(
                    id='confl-pdf-upload',
                    children=html.Div([
                        html.I(className='bi bi-cloud-arrow-up me-1'),
                        '클릭 또는 드래그해 PDF 업로드(여러 개 가능, 파일명 = 과제명)',
                    ], className='small text-muted'),
                    accept='.pdf', multiple=True,
                    style={'padding': '8px', 'border': '1px dashed #adb5bd', 'borderRadius': '4px',
                           'textAlign': 'center', 'cursor': 'pointer'},
                ),
                md=6,
            ),
            dbc.Col(pdf_list_view, md=6),
        ], className='g-2'),
        missing_view,
    ]), className='shadow-sm mb-3')


def _confl_tree_status_view():
    """하위 페이지 추출 진행/결과 한 줄."""
    st = confl_tree.snapshot()
    if st['status'] == 'running':
        return html.Div([dbc.Spinner(size='sm', className='me-2'),
                         f"추출 중… 경과 {st['elapsed']}초 · {st['count']}개 수집 (마지막: {st['message']})"],
                        className='small text-primary fw-semibold')
    if st['status'] == 'done':
        return html.Div([html.I(className='bi bi-check-circle-fill text-success me-1'),
                         f"완료 — 상위 페이지 {st['root']} 아래 {st['count']}개 페이지 ({st['finished_at']})"],
                        className='small')
    if st['status'] == 'error':
        return html.Div([html.I(className='bi bi-exclamation-triangle-fill text-danger me-1'),
                         f"실패 — {st['message']}"], className='small text-danger')
    return html.Div('상위 페이지를 입력하고 "추출"을 누르세요.', className='small text-muted')


def _confl_tree_section():
    """"컨플 하위 페이지 목록 추출"(2026-10, 사용자 요청) — 상위 페이지 하나의 주소/ID를
    넣으면 그 아래 모든 하위 페이지의 제목·페이지 ID(10자리)를 엑셀로 내려받는다.
    백엔드는 services/confl_tree.py(백그라운드 스레드 + 폴링)."""
    return dbc.Card(dbc.CardBody([
        html.Div([
            html.I(className='bi bi-diagram-3 me-2 text-primary'),
            html.Span('컨플 하위 페이지 목록 추출 — 제목 · 페이지 ID 엑셀', className='fw-semibold small'),
            html.I(className='bi bi-question-circle ms-1', id='confl-tree-hint-icon',
                   style={'fontSize': '0.75rem', 'color': '#6c757d', 'cursor': 'help'}),
            dbc.Tooltip(
                '상위 컨플 페이지의 페이지 ID(숫자) 또는 pageId가 들어간 주소를 넣으면, 그 아래 모든 '
                '하위 페이지(최하위까지)의 제목과 페이지 ID를 엑셀로 뽑습니다. 이 ID를 과제별컨플의 '
                '"컨플 주소"에 그대로 쓸 수 있습니다. 사내 컨플루언스 접속 설정(.env)이 필요합니다.',
                target='confl-tree-hint-icon', placement='right',
            ),
        ], className='mb-2'),
        dbc.Row([
            dbc.Col(dbc.Input(id='confl-tree-root', placeholder='상위 페이지 ID(예: 3862782334) 또는 주소',
                              type='text', size='sm', debounce=False), md=5),
            dbc.Col(dcc.Dropdown(
                id='confl-tree-depth', value='all', clearable=False,
                options=[{'label': '최하위까지 전부', 'value': 'all'},
                         {'label': '1단계 아래까지', 'value': '1'},
                         {'label': '2단계 아래까지', 'value': '2'},
                         {'label': '3단계 아래까지', 'value': '3'}],
            ), md=3),
            dbc.Col(dbc.ButtonGroup([
                dbc.Button([html.I(className='bi bi-search me-1'), '추출'], id='confl-tree-run-btn',
                           color='primary', size='sm'),
                dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '엑셀 다운로드'],
                           id='confl-tree-download-btn', color='success', outline=True, size='sm',
                           disabled=not confl_tree.snapshot()['has_result']),
            ]), md=4),
        ], className='g-2 align-items-center'),
        html.Div(_confl_tree_status_view(), id='confl-tree-status', className='mt-2'),
        dcc.Download(id='confl-tree-download'),
        dcc.Interval(id='confl-tree-interval', interval=2000, disabled=not confl_tree.is_running()),
    ]), className='shadow-sm mb-3')


def _data_update_tab() -> html.Div:
    """매니페스트 등록 파일 중 20개(리더십진단·comments 제외)를 웹에서 직접
    업로드→실행할 수 있는 탭. 실제 실행/락/로그는 services/web_pipeline_runner.py.
    전제: 업로드 전 사용자가 DRM을 해제한 사본을 올린다(사용자 확정)."""
    return html.Div([
        dcc.Download(id='data-update-download'),
        dcc.Interval(id='data-update-interval', interval=3000, disabled=not wpr.any_running()),

        dbc.Alert(
            [
                html.I(className='bi bi-info-circle me-2'),
                '엑셀 업로드 시 복호화(일반문서로 변환) 후 업로드 가능, '
                '전체 업데이트는 파일이 업로드 된 항목만 실행',
            ],
            color='light', className='small border mb-3',
        ),

        dbc.Row([
            dbc.Col(html.Div(id='data-update-status-msg'), md=True),
            dbc.Col(
                dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-database-up me-1'), 'DB 반영'],
                               id='data-update-db-btn', color='secondary', outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-check2-square me-1'), '선택 업데이트'],
                               id='data-update-selected-btn', color='primary', outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-arrow-repeat me-1'), '전체 업데이트'],
                               id='data-update-all-btn', color='primary', size='sm'),
                ]),
                md='auto',
            ),
        ], className='mb-2 align-items-start'),

        html.Div(_db_status_view(), id='data-update-db-status', className='mb-2'),

        html.Div(_data_update_table(), id='data-update-table-container'),

        html.Div(_confl_pdf_upload_section(), id='confl-pdf-section-container'),
        html.Div(id='confl-pdf-status', className='mt-2'),

        html.Div(_confl_tree_section(), id='confl-tree-section-container'),
    ], className='pt-3')


# ── 콜백: 데이터 업데이트 — 파일 업로드 ────────────────────────────────────────
@callback(
    Output('data-update-table-container', 'children', allow_duplicate=True),
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Output('team-refer-upload-status', 'children', allow_duplicate=True),
    Output('exception-job-function-upload-status', 'children', allow_duplicate=True),
    Input({'type': 'du-upload', 'key': ALL, 'slot': ALL}, 'contents'),
    State({'type': 'du-upload', 'key': ALL, 'slot': ALL}, 'filename'),
    State({'type': 'du-upload', 'key': ALL, 'slot': ALL}, 'id'),
    prevent_initial_call=True,
)
def data_update_on_upload(all_contents, all_filenames, all_ids):
    from services.auth import can
    if not can('manage_users'):
        return no_update, _alert('관리자만 업로드할 수 있습니다.', 'danger'), no_update, no_update

    trig = dash.callback_context.triggered_id
    if trig is None:
        return no_update, no_update, no_update, no_update
    idx = next((i for i, cid in enumerate(all_ids) if cid == trig), None)
    if idx is None or not all_contents[idx]:
        return no_update, no_update, no_update, no_update

    # needs_valid_date 항목의 대량 백필 업로드는 dcc.Upload(multiple=True)라
    # contents/filename이 리스트로 온다 — 그 외(기존 단일 업로드)는 문자열
    # 그대로 온다. 둘 다 아래에서 같은 방식으로 처리하도록 리스트로 통일한다.
    raw_contents = all_contents[idx]
    raw_filenames = all_filenames[idx]
    if isinstance(raw_contents, list):
        contents_list, filenames_list = raw_contents, raw_filenames
    else:
        contents_list, filenames_list = [raw_contents], [raw_filenames]

    slot = None if trig['slot'] == 'single' else trig['slot']
    ok_count, errors = 0, []
    for filename, contents in zip(filenames_list, contents_list):
        try:
            _header, b64data = contents.split(',', 1)
            file_bytes = base64.b64decode(b64data, validate=True)
        except (ValueError, TypeError):
            errors.append(f'{filename}: 파일을 읽지 못했습니다.')
            continue
        if len(file_bytes) > wpr.MAX_UPLOAD_BYTES:
            limit_mb = wpr.MAX_UPLOAD_BYTES // (1024 * 1024)
            errors.append(f'{filename}: 파일이 너무 큽니다(최대 {limit_mb}MB).')
            continue
        wpr.save_upload(trig['key'], filename, file_bytes, slot=slot)
        ok_count += 1

    if ok_count and not errors:
        msg, color = f'{ok_count}개 파일 업로드 완료.' if ok_count > 1 else f'{filenames_list[0]} 업로드 완료.', 'success'
    elif ok_count and errors:
        msg, color = f'{ok_count}개 업로드 완료, {len(errors)}개 실패({"; ".join(errors[:3])})', 'warning'
    else:
        msg, color = '; '.join(errors[:3]) or '업로드에 실패했습니다.', 'danger'

    # team_refer/exception_job_function은 "데이터 업데이트" 탭 표에서
    # 숨겨져 있어(hidden_from_table), 그 탭의 상태 메시지 자리
    # (data-update-status-msg)는 다른 탭이라 안 보인다 — 대신 각자의 탭 안
    # 전용 상태 자리로 알림을 보낸다.
    if trig['key'] == 'team_refer':
        return _data_update_table(), no_update, _alert(msg, color), no_update
    if trig['key'] == 'exception_job_function':
        return _data_update_table(), no_update, no_update, _alert(msg, color)
    return _data_update_table(), _alert(msg, color), no_update, no_update


# ── 콜백: 과제별컨플 — 컨플 주소 없는 과제 PDF 업로드/삭제 ──────────────────────
# du-upload 패턴매칭 콜백(data_update_on_upload)과 별개다 — PDF는 MANIFEST의
# save_upload()(data/web_updates/<key>/)가 아니라 data/raw/conflue_MPR/에
# 원본 파일명 그대로 저장해야 하고(services.web_pipeline_runner.save_confl_pdf
# 참고), "실행"할 process_*.py도 없기 때문이다.
@callback(
    Output('confl-pdf-section-container', 'children', allow_duplicate=True),
    Output('confl-pdf-status', 'children', allow_duplicate=True),
    Input('confl-pdf-upload', 'contents'),
    State('confl-pdf-upload', 'filename'),
    prevent_initial_call=True,
)
def confl_pdf_on_upload(all_contents, all_filenames):
    from services.auth import can
    if not can('manage_users'):
        return no_update, _alert('관리자만 업로드할 수 있습니다.', 'danger')
    if not all_contents:
        return no_update, no_update

    ok_count, errors = 0, []
    for filename, contents in zip(all_filenames, all_contents):
        try:
            _header, b64data = contents.split(',', 1)
            file_bytes = base64.b64decode(b64data, validate=True)
        except (ValueError, TypeError):
            errors.append(f'{filename}: 파일을 읽지 못했습니다.')
            continue
        if len(file_bytes) > wpr.MAX_UPLOAD_BYTES:
            limit_mb = wpr.MAX_UPLOAD_BYTES // (1024 * 1024)
            errors.append(f'{filename}: 파일이 너무 큽니다(최대 {limit_mb}MB).')
            continue
        try:
            wpr.save_confl_pdf(filename, file_bytes)
            ok_count += 1
        except ValueError as exc:
            errors.append(f'{filename}: {exc}')

    if ok_count and not errors:
        msg, color = f'{ok_count}개 PDF 업로드 완료.' if ok_count > 1 else f'{all_filenames[0]} 업로드 완료.', 'success'
    elif ok_count and errors:
        msg, color = f'{ok_count}개 업로드 완료, {len(errors)}개 실패({"; ".join(errors[:3])})', 'warning'
    else:
        msg, color = '; '.join(errors[:3]) or '업로드에 실패했습니다.', 'danger'

    return _confl_pdf_upload_section(), _alert(msg, color)


@callback(
    Output('confl-pdf-section-container', 'children', allow_duplicate=True),
    Output('confl-pdf-status', 'children', allow_duplicate=True),
    Input({'type': 'confl-pdf-delete', 'name': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def confl_pdf_on_delete(n_clicks_list):
    from services.auth import can
    trig = dash.callback_context.triggered_id
    if trig is None or not any(n_clicks_list):
        return no_update, no_update
    if not can('manage_users'):
        return no_update, _alert('관리자만 삭제할 수 있습니다.', 'danger')

    ok = wpr.delete_confl_pdf(trig['name'])
    msg, color = (f"{trig['name']} 삭제했습니다.", 'success') if ok else ('파일을 찾지 못했습니다.', 'warning')
    return _confl_pdf_upload_section(), _alert(msg, color)


# ── 콜백: 컨플 PDF — 전체 선택 체크박스 → 각 파일 체크박스 일괄 토글 ───────────
@callback(
    Output({'type': 'confl-pdf-check', 'name': ALL}, 'value'),
    Input('confl-pdf-select-all', 'value'),
    State({'type': 'confl-pdf-check', 'name': ALL}, 'id'),
    prevent_initial_call=True,
)
def confl_pdf_select_all(checked, ids):
    return [bool(checked)] * len(ids)


# ── 콜백: 컨플 PDF — 선택 삭제 ────────────────────────────────────────────────
@callback(
    Output('confl-pdf-section-container', 'children', allow_duplicate=True),
    Output('confl-pdf-status', 'children', allow_duplicate=True),
    Input('confl-pdf-del-selected-confirm', 'submit_n_clicks'),
    State({'type': 'confl-pdf-check', 'name': ALL}, 'value'),
    State({'type': 'confl-pdf-check', 'name': ALL}, 'id'),
    prevent_initial_call=True,
)
def confl_pdf_delete_selected(submit_n_clicks, values, ids):
    from services.auth import can
    if not submit_n_clicks:
        return no_update, no_update
    if not can('manage_users'):
        return no_update, _alert('관리자만 삭제할 수 있습니다.', 'danger')
    names = [i['name'] for i, v in zip(ids or [], values or []) if v]
    if not names:
        return no_update, _alert('선택된 PDF가 없습니다. 삭제할 파일을 체크해주세요.', 'warning')
    done, failed = wpr.delete_confl_pdfs(names)
    msg = f'{done}건 삭제했습니다.' + (f' (찾지 못한 파일 {failed}건)' if failed else '')
    return _confl_pdf_upload_section(), _alert(msg, 'success' if done else 'warning')


# ── 콜백: 컨플 PDF — 전체 삭제 ────────────────────────────────────────────────
@callback(
    Output('confl-pdf-section-container', 'children', allow_duplicate=True),
    Output('confl-pdf-status', 'children', allow_duplicate=True),
    Input('confl-pdf-del-all-confirm', 'submit_n_clicks'),
    prevent_initial_call=True,
)
def confl_pdf_delete_all(submit_n_clicks):
    from services.auth import can
    if not submit_n_clicks:
        return no_update, no_update
    if not can('manage_users'):
        return no_update, _alert('관리자만 삭제할 수 있습니다.', 'danger')
    names = [p['filename'] for p in wpr.list_confl_pdfs()]
    if not names:
        return no_update, _alert('삭제할 PDF가 없습니다.', 'warning')
    done, failed = wpr.delete_confl_pdfs(names)
    msg = f'PDF {done}건을 전부 삭제했습니다.' + (f' (실패 {failed}건)' if failed else '')
    return _confl_pdf_upload_section(), _alert(msg, 'success' if done else 'warning')


# ── 콜백: 컨플 하위 페이지 목록 추출 ─────────────────────────────────────────
@callback(
    Output('confl-tree-status', 'children', allow_duplicate=True),
    Output('confl-tree-interval', 'disabled', allow_duplicate=True),
    Output('confl-tree-download-btn', 'disabled', allow_duplicate=True),
    Input('confl-tree-run-btn', 'n_clicks'),
    State('confl-tree-root', 'value'),
    State('confl-tree-depth', 'value'),
    prevent_initial_call=True,
)
def confl_tree_start(n_clicks, root, depth):
    from services.auth import can
    if not n_clicks:
        return no_update, no_update, no_update
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True, True
    ok, reason = confl_tree.start(root or '', None if depth in (None, 'all') else int(depth))
    if not ok:
        return _alert(reason, 'warning'), not confl_tree.is_running(), True
    return _confl_tree_status_view(), False, True


@callback(
    Output('confl-tree-status', 'children', allow_duplicate=True),
    Output('confl-tree-interval', 'disabled', allow_duplicate=True),
    Output('confl-tree-download-btn', 'disabled', allow_duplicate=True),
    Input('confl-tree-interval', 'n_intervals'),
    prevent_initial_call=True,
)
def confl_tree_poll(_n):
    st = confl_tree.snapshot()
    return _confl_tree_status_view(), st['status'] != 'running', not st['has_result']


@callback(
    Output('confl-tree-download', 'data'),
    Input('confl-tree-download-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def confl_tree_download(n_clicks):
    from services.auth import can
    if not n_clicks or not can('manage_users'):
        return no_update
    result = confl_tree.result_workbook()
    if result is None:
        return no_update
    filename, data = result
    return dcc.send_bytes(data, filename)


# ── 콜백: 데이터 업데이트 — 전체/선택 실행 ─────────────────────────────────────
@callback(
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input('data-update-all-btn', 'n_clicks'),
    Input('data-update-selected-btn', 'n_clicks'),
    State({'type': 'du-check', 'key': ALL}, 'value'),
    State({'type': 'du-check', 'key': ALL}, 'id'),
    State({'type': 'du-valid-year', 'key': ALL}, 'value'),
    State({'type': 'du-valid-year', 'key': ALL}, 'id'),
    State({'type': 'du-valid-month', 'key': ALL}, 'value'),
    prevent_initial_call=True,
)
def data_update_run(_all_clicks, _sel_clicks, check_values, check_ids,
                     valid_years, valid_year_ids, valid_months):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True

    trig = dash.callback_context.triggered_id
    if trig == 'data-update-all-btn':
        keys = wpr.runnable_keys()
        if not keys:
            return _alert('업로드된 파일이 있는 항목이 없습니다.', 'warning'), True
    elif trig == 'data-update-selected-btn':
        keys = [cid['key'] for cid, v in zip(check_ids, check_values) if v]
        if not keys:
            return _alert('선택된 항목이 없습니다.', 'warning'), True
        missing = [k for k in keys if not wpr.has_upload(k)]
        if missing:
            labels = [wpr._BY_KEY[k]['label'] for k in missing]
            return (_alert(f"업로드되지 않은 항목이 선택됐습니다: {', '.join(labels)}"
                            ' — 업로드 후 다시 시도해주세요.', 'warning'), True)
    else:
        return no_update, no_update

    # needs_valid_date 항목(evaluations/core_technology/job_profile/
    # work_objective_*)만 화면에 "누적 시점(연/월)" 드롭다운이 렌더링되므로,
    # id-value를 매칭해 그 항목만 valid_dates 딕셔너리로 모은다. 지정 안 된
    # 항목은 process_*.py 기본값(오늘). 연/월 둘 다 값이 있어야 반영(항상
    # 일=1일로 고정 — 일 단위는 이 화면에서 다루지 않음, 2026-09-01 사용자 확정).
    valid_dates_by_key = {}
    for cid, y, m in zip(valid_year_ids, valid_years, valid_months):
        if y and m:
            valid_dates_by_key[cid['key']] = date(int(y), int(m), 1)

    if not wpr.start_run(keys, valid_dates=valid_dates_by_key):
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False
    return (_alert(f'{len(keys)}개 항목 실행을 시작했습니다. 브라우저를 닫아도 서버에서 계속 '
                    '진행되며, 화면은 자동으로 갱신됩니다.', 'info'), False)


# ── 콜백: 데이터 업데이트 — 항목별 "API로 가져오기" 아이콘 ─────────────────────
# 사내 API 연동은 아직 없다(services/web_pipeline_runner.py의 register_api_fetch()
# 참고) — 지금 눌러도 파일 업로드 실행과 완전히 같은 경로(락/로그/폴링)를 타되,
# 실행결과 칸에 "아직 연동되지 않음"이 그대로 표시된다. 연동을 붙이는 시점에
# register_api_fetch()만 호출하면 이 아이콘이 화면 변경 없이 바로 동작한다.
@callback(
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input({'type': 'du-api', 'key': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def data_update_run_via_api(n_clicks_list):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True

    trig = dash.callback_context.triggered_id
    if not trig or not any(n_clicks_list):
        return no_update, no_update

    key = trig['key']
    if not wpr.start_run_via_api([key]):
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False
    return _alert(f"{wpr._BY_KEY[key]['label']} 항목의 API 연동을 시도합니다.", 'info'), False


# ── 콜백: 데이터 업데이트 — DB 반영 ────────────────────────────────────────────
@callback(
    Output('data-update-status-msg', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Input('data-update-db-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def data_update_db_load(n_clicks):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True
    if not n_clicks:
        return no_update, no_update
    if not wpr.start_db_load():
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False
    return _alert('DB 반영을 시작했습니다. 완료되면 아래 상태가 갱신됩니다.', 'info'), False


# ── 콜백: 데이터 업데이트 — 진행 상황 폴링(브라우저를 새로 열어도 최신 상태) ────
@callback(
    Output('data-update-table-container', 'children', allow_duplicate=True),
    Output('data-update-db-status', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Output('team-refer-upload-status', 'children', allow_duplicate=True),
    Output('exception-job-function-upload-status', 'children', allow_duplicate=True),
    Output('team-refer-table', 'rowData', allow_duplicate=True),
    Output('team-refer-hidden-rows', 'data', allow_duplicate=True),
    Output('team-refer-table', 'selectedRows', allow_duplicate=True),
    Input('data-update-interval', 'n_intervals'),
    State('team-refer-highlight-date', 'data'),
    prevent_initial_call=True,
)
def data_update_poll(_n, highlight_date):
    team_refer_row = next((r for r in wpr.snapshot() if r['key'] == 'team_refer'), None)
    team_refer_status = _run_status_view(team_refer_row) if team_refer_row else no_update
    ejf_row = next((r for r in wpr.snapshot() if r['key'] == 'exception_job_function'), None)
    ejf_status = _run_status_view(ejf_row) if ejf_row else no_update
    # 팀/리더 참조 그리드도 매 폴링마다 최신 저장 상태로 갱신한다(2026-09-14
    # 추가) — intake CSV 업로드→실행이 끝나도 그리드가 페이지 최초 로드 시점
    # 값 그대로 남아 새로고침해야만 반영되던 문제. data-update-interval은
    # 어떤 작업이든 실행 중일 때만 틱하고 끝나면 스스로 꺼지므로(아래
    # not wpr.any_running()), 실질적으로 "실행 완료 직후 한 번" 갱신되는
    # 효과를 낸다 — 단, 이 틱이 도는 사이(다른 항목이 실행 중인 동안 포함)
    # 그리드에서 저장 안 한 수동 편집을 하고 있었다면 그 내용은 이 갱신으로
    # 덮어써질 수 있다(사용자 확정 — 자동 갱신을 우선하기로 함).
    # 비공식소속부서명 빈 행은 여기서도 다시 숨겨(_split_hidden_rows,
    # 2026-09-15 추가) team-refer-hidden-rows Store를 함께 갱신한다.
    visible_rows, hidden_rows = _split_hidden_rows(team_refer_store.list_editable_rows())
    grid_data = _renumbered(_ensure_rid(visible_rows))
    # 엑셀 업로드가 방금 끝난 경우(team-refer-highlight-date가 채워져
    # 있음)에만, 이번 업로드 날짜와 다른 행("과거 데이터")을 색으로
    # 강조한다(_mark_stale_rows() 참고).
    grid_data = _mark_stale_rows(grid_data, highlight_date)
    return (_data_update_table(), _db_status_view(), not wpr.any_running(),
            team_refer_status, ejf_status, grid_data, hidden_rows, [])


# ── 콜백: 데이터 업데이트 — "이전 Data" 다운로드 ───────────────────────────────
@callback(
    Output('data-update-download', 'data'),
    Input({'type': 'du-download', 'key': ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def data_update_download(_n_clicks_list):
    trig = dash.callback_context.triggered_id
    if not trig:
        return no_update
    files = wpr.uploaded_files(trig['key'])
    if not files:
        return no_update
    path = max(files, key=os.path.getmtime)
    return dcc.send_file(path)
