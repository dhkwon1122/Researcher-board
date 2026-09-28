"""
관리자 페이지 "팀/리더 참조" 탭 — pages/admin.py 분할 리팩터링(2026-09-28)
으로 신설. 조직 그리드 CRUD(행 추가/삭제/이동/저장)와 엑셀 일괄 업로드
실행을 담당한다.
"""
import uuid
from datetime import date

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, clientside_callback, ctx, dcc, html, no_update

from components.admin_shared import (
    _alert, _ensure_rid, _renumbered, _run_status_view, _split_hidden_rows, _upload_box,
)
from services import team_refer_store
from services import web_pipeline_runner as wpr

# ── 팀/리더 참조 그리드 — 체크박스 이동/삭제(2026-09-15, 2026-09-16 단순화) ────
# 체크박스로 고른 행 + 그 하위 조직 전체를 하나의 구간으로 묶어 삭제
# 버튼용으로 쓴다(로직은 assets/team_refer_grid.js가 2026-09-17에 제거된
# 행 드래그 재정렬 기능에서 쓰던 것과 같은 발상 — 부모 행과 그 하위
# 자손 행은 항상 화면에 연속으로 붙어 나온다는 성질을 이용). 2026-09-16:
# "구조" 열(부모-자식 아이콘 표시)을 없애면서, 이동은 "체크한 행 하나만
# 개별로, 상위부서 경계와 무관하게 자유롭게" 이동하는 방식으로 단순화
# (사용자 확정) — 하위 조직을 함께 묶어 이동시키던 로직(_preceding_
# sibling_range 등)은 제거. 삭제만 기존처럼 하위 조직 전체를 함께
# 지운다(사용자 확정 — 하위 조직이 남아있으면 그 소속 정보 때문에 상위
# 조직이 자동으로 다시 생성돼 사실상 삭제되지 않는 문제가 있어, 삭제는
# 계속 하위 조직 포함이 맞음).
_LEVEL_COLS = ['1단계부서명', '2단계부서명', '3단계부서명']


def _row_path(row: dict) -> tuple:
    """행의 "자기 경로"(1→2→3단계 순서로 읽다가 처음 빈 값을 만나면 중단)."""
    path = []
    for col in _LEVEL_COLS:
        v = str(row.get(col) or '').strip()
        if not v:
            break
        path.append(v)
    return tuple(path)


def _is_descendant_path(path: tuple, ancestor: tuple) -> bool:
    return len(path) > len(ancestor) and path[:len(ancestor)] == ancestor


def _subtree_range(rows: list, idx: int) -> tuple:
    """rows[idx](및 그 뒤에 연속으로 이어지는 하위 조직 행 전체)를 하나의
    구간 [start, end)로 묶는다 — list_editable_rows()가 깊이 우선(부모→자식)
    순서로 반환하므로 자손 행은 항상 부모 바로 다음부터 연속이다."""
    path = _row_path(rows[idx])
    end = idx + 1
    while end < len(rows) and _is_descendant_path(_row_path(rows[end]), path):
        end += 1
    return idx, end


def _renumber_dep_codes(rows: list) -> None:
    """조직코드(dep_code)를 현재 화면 순서 그대로 1~N으로 다시 매긴다
    (2026-09-16 확정 — "맨 위가 1, 맨 뒤가 N"). 이동/삭제/행 추가 직후
    호출해 그리드에 즉시 반영되는 미리보기 값일 뿐이다 — 실제 저장되는
    최종 조직코드는 services.team_refer_store._assign_depth_first_
    dep_codes()가 저장 시점에 dep_id/upper_dep_id로 구성한 실제 트리를
    순회하며 다시 매긴다(숨김 행까지 포함한 전체 트리 기준이라 이 값과
    똑같지는 않을 수 있지만, 보이는 형제끼리의 상대적 순서는 그대로
    유지된다). 헤더 클릭 정렬은 호출하지 않는다(AG Grid 네이티브
    sortable은 화면 표시 순서만 바꾸고 rowData 배열 자체는 그대로
    유지함을 확인했으므로, 정렬 기준으로 조직코드를 덮어쓸 위험 자체가
    없다). 4자리로 0-패딩하는 이유는 서버 쪽과 동일 — build_org_tree()의
    형제 정렬이 문자열 비교라 패딩 없이는 '10'이 '2'보다 앞서는 문제가
    있다."""
    for i, row in enumerate(rows, start=1):
        row['조직코드'] = f'{i:04d}'


def _team_refer_upload_section():
    """"팀/리더 참조" 탭 안의 엑셀 업로드 UI(2026-09-01, 사용자 확정 — "데이터
    업데이트" 탭에서 이동). 백엔드는 services/web_pipeline_runner.py의
    'team_refer' 항목(hidden_from_table=True)을 그대로 재사용 — 업로드
    저장/백필/실행 로그가 전부 "데이터 업데이트" 탭의 다른 항목과 동일한
    경로를 탄다. 업로드 컴포넌트({'type':'du-upload','key':'team_refer',...})와
    다운로드 버튼({'type':'du-download','key':'team_refer'})은 패턴매칭
    콜백(data_update_on_upload/data_update_download)이 위치와 무관하게
    그대로 처리하므로 이 탭 안에 있어도 새 콜백이 필요 없다 — "실행" 버튼만
    이 탭 전용 콜백(team_refer_run_upload)이 따로 필요하다(이 항목이
    hidden_from_table이라 "데이터 업데이트" 탭의 전체/선택 실행 대상에서
    빠지므로)."""
    row = next((r for r in wpr.snapshot() if r['key'] == 'team_refer'), None)
    if row is None:
        return None
    today = date.today()
    filenames = row['uploaded_filenames']
    filenames_view = (
        html.Div([html.Div(f, className='small') for f in filenames], className='mt-1')
        if filenames else html.Div('업로드된 파일 없음', className='small text-muted mt-1')
    )
    backfill_view = None
    if row.get('backfill_files'):
        bf = row['backfill_files']
        backfill_view = html.Div(
            [html.I(className='bi bi-layers me-1'), f'백필 대기 {len(bf)}건 ({bf[0][1]} ~ {bf[-1][1]})'],
            className='small text-info fw-semibold mt-1',
        )

    return dbc.Card(dbc.CardBody([
        html.Div([
            html.I(className='bi bi-file-earmark-excel me-2 text-success'),
            html.Span('엑셀 파일로 한 번에 반영', className='fw-semibold small'),
        ], className='mb-2'),
        dbc.Row([
            dbc.Col([
                html.Div('업로드(xlsx 또는 csv)', className='small text-muted mb-1'),
                _upload_box('team_refer', 'single', multiple=True),
                filenames_view, backfill_view,
            ], md=5),
            dbc.Col([
                html.Div('누적 시점(연/월/일)', className='small text-muted mb-1'),
                _valid_date_picker('team_refer', today),
            ], md=3),
            dbc.Col([
                html.Div(' ', className='small mb-1'),
                dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-play-fill me-1'), '실행'],
                               id='team-refer-run-upload-btn', color='primary', size='sm'),
                    dbc.Button(html.I(className='bi bi-download'),
                               id={'type': 'du-download', 'key': 'team_refer'},
                               color='link', size='sm', disabled=not row['has_upload'],
                               title='업로드한 원본 파일 다운로드'),
                ]),
            ], md=2),
            dbc.Col([
                html.Div('최종실행이력', className='small text-muted mb-1'),
                html.Div(id='team-refer-upload-status', children=_run_status_view(row)),
            ], md=2),
        ], className='g-2 align-items-start'),
    ]), className='shadow-sm mb-3')


def _valid_date_picker(key: str, valid_date: date):
    """"누적 시점(연/월/일)" 입력 — 일 단위까지 필요한 항목 전용(2026-09-16
    추가, team_refer가 첫 사용처). team_refer는 자연키가 (dep_id,
    valid_year, valid_month, valid_day)라 "가장 최근 날짜"로 현재 상태를
    가리는데, 이 화면(엑셀 일괄 업로드)이 항상 일=1로 고정 저장하면 이미
    그달 중 더 늦은 날짜로 저장된 값(관리자 화면 그리드의
    team-refer-valid-date로 수동 저장한 값 등)에 밀려 "최신 데이터"로
    반영되지 않는 문제가 있었다(사용자 리포트 — 매달 1일 이후에 올린
    엑셀이 실제로는 무시되는 현상). 그리드의 team-refer-valid-date와
    동일하게 dcc.DatePickerSingle을 그대로 쓴다 — _valid_period_picker()가
    이걸 안 쓰고 연/월 드롭다운으로 대체한 이유(영문 캘린더 헤더, 일
    단위가 필요 없음)가 여기서는 해당하지 않는다(일 단위가 반드시
    필요함)."""
    return dcc.DatePickerSingle(
        id={'type': 'du-valid-date', 'key': key}, date=valid_date.isoformat(),
        display_format='YYYY-MM-DD', className='d-block',
    )


# ── 팀/리더 참조 그리드 — AG Grid(dash-ag-grid) 전환(2026-09-17) ─────────────
# 기존 dash_table.DataTable + assets/team_refer_grid.js의 커스텀 JS 패치
# (자동채움 가이드용 <datalist>, 클릭 위치로 커서 이동, F2 편집 진입 등 —
# 전부 dash_table 자체에 없는 기능을 직접 흉내 낸 것들) 대신, 그런 기능을
# 원래 갖추고 있는 오픈소스 그리드 라이브러리 AG Grid(Community 에디션,
# MIT 라이선스 — 사내 상업적 용도 제약 없음)로 교체했다. Dash 공식
# 패키지(dash-ag-grid)가 있어 이 Dash/Python 구조를 그대로 유지하면서
# 그리드 엔진만 바꿀 수 있다. AG Grid가 기본 제공해 더 이상 직접 구현할
# 필요가 없어진 것들: 헤더 전체선택 체크박스, 셀 클릭 위치로 커서 이동,
# 더블클릭/Enter/F2로 편집 진입, 컬럼 리사이즈, 툴팁(tooltipField), 헤더
# 클릭 정렬(클라이언트에서 즉시 처리 — 서버 왕복 불필요, 실제 rowData
# 순서는 안 바뀌고 화면 표시만 바뀜을 확인). 자유 입력 + 값 제안이라는
# 자동채움 가이드(<datalist>) 기능은 AG Grid Community에 직접적인 대응
# 기능이 없어 이번 전환에서는 빠졌다(값 자체를 잘못 적을 위험은 여전히
# 크지 않은 컬럼들이라 — 나중에 정말 필요하면 커스텀 셀 에디터로 추가
# 가능).
_WORK_TYPE_OPTIONS = ['R&D', 'R&D_Support', 'Staff']


def _team_refer_tab() -> html.Div:
    """팀/리더 참조 웹 CRUD 탭. 컬럼은 팀참조시트.xlsx 원본 헤더명을 그대로
    쓴다(pipeline.process_team_refer._COL_MAP 재사용, services.team_refer_store
    참고) — 행 추가/삭제로 조직 단위를 직접 편집하고, 저장하면 지정한 날짜로
    누적된다(같은 날 재저장은 그날 값을 덮어씀).

    3단계 부서 체계(2026-09-11) 도입 이후 부서ID/상위부서ID/조직 레벨은 이
    그리드의 편집 대상이 아니다 — 1단계부서명/2단계부서명/3단계부서명을 각
    행에 "전체 경로"로 채우면(예: 3단계 소속이면 1/2/3단계 이름을 전부 채움)
    저장 시점에 dep_id/upper_dep_id/team_layer가 그 경로에서 자동으로
    계산된다(services.team_refer_store.list_editable_rows()가 저장된
    조직을 불러올 때도 상위 부서명을 전체 경로로 채워 보여준다).

    비공식소속부서명이 빈 행(리프 배정 없이 조직도 트리 구조상으로만
    존재하는 상위 노드)은 가독성을 위해 화면에서 숨기고(_split_hidden_rows),
    team-refer-hidden-rows Store에 그대로 보관해 저장 시 다시 합친다."""
    rows = team_refer_store.list_editable_rows()
    rows, hidden_rows = _split_hidden_rows(rows)
    rows = _renumbered(_ensure_rid(rows))

    # AG Grid columnDefs — 'No.'는 화면 표시 전용(저장 대상 컬럼
    # KOREAN_COLUMNS에는 없음). getRowId를 쓰는 AG Grid는 행 순서가 바뀌어도
    # 그 자체만으로는 valueGetter 기반 컬럼을 다시 그리지 않는다는 걸 직접
    # 확인해(rowIndex가 바뀌어도 화면에 예전 값이 그대로 남음), dash_table
    # 시절처럼 이동/삭제/행추가 콜백이 끝날 때마다 파이썬에서 _renumbered()로
    # 실제 필드 값을 다시 매겨 확실하게 갱신되게 한다.
    # 구분 컬럼만 agSelectCellEditor로 _WORK_TYPE_OPTIONS 3가지 값 중에서만
    # 고를 수 있게 제한한다(2026-09-17 확정, 사용자 요청).
    column_defs = [
        {
            'headerName': 'No.', 'field': '_no', 'editable': False,
            'sortable': False, 'filter': False, 'width': 70, 'pinned': 'left',
        },
    ] + [
        {
            'headerName': col, 'field': col, 'editable': True,
            'tooltipField': col,
            **({'cellEditor': 'agSelectCellEditor',
                'cellEditorParams': {'values': [''] + _WORK_TYPE_OPTIONS}}
               if col == '구분' else {}),
        }
        for col in team_refer_store.KOREAN_COLUMNS
    ]

    return html.Div([
        # 비공식소속부서명이 빈 행(가독성을 위해 화면에서 숨김) — 편집 대상이
        # 아니라 저장 시 화면에 보이는 행과 그대로 합쳐서 반영한다.
        dcc.Store(id='team-refer-hidden-rows', data=hidden_rows),
        # "엑셀 파일로 한번에 반영" 실행 시점에만 이번 업로드 날짜('YYYY-MM-DD')로
        # 채워지는 임시 표시 — _mark_stale_rows()/team_refer_run_upload() 참고.
        # 페이지를 새로고침하거나 다른 화면으로 나갔다 오면(이 컴포넌트가
        # 새로 만들어지며 기본값 None으로 리셋) 강조 표시도 함께 사라진다
        # (사용자 확정 — "엑셀 업로드 직후에만" 보이는 임시 기능).
        dcc.Store(id='team-refer-highlight-date', data=None),
        # clientside_callback 전용 더미 Output(화면에 표시할 내용 없음) —
        # pages/researcher_profile.py의 profile-print-dummy와 동일한 패턴.
        html.Div(id='team-refer-grid-dummy', style={'display': 'none'}),

        dbc.Row([
            dbc.Col([
                dbc.Label('입력 날짜', className='small fw-semibold text-muted mb-1'),
                dcc.DatePickerSingle(
                    id='team-refer-valid-date', date=date.today().isoformat(),
                    display_format='YYYY-MM-DD', className='d-block',
                ),
            ], md='auto'),
            dbc.Col([
                dbc.Label(' ', className='small d-block mb-1'),
                dbc.ButtonGroup([
                    dbc.Button([html.I(className='bi bi-plus-lg me-1'), '행 추가'],
                               id='team-refer-add-row-btn', color='secondary', outline=True, size='sm'),
                    dbc.Button([html.I(className='bi bi-save me-1'), '저장'],
                               id='team-refer-save-btn', color='primary', size='sm'),
                    dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '엑셀 다운로드'],
                               id='team-refer-download-btn', color='success', outline=True, size='sm'),
                    dbc.Button(html.I(className='bi bi-database-up'),
                               id='team-refer-db-load-btn', color='info', outline=True, size='sm',
                               title='team_refer 테이블만 DB에 바로 반영(저장된 최신 값 기준)'),
                ]),
            ], md='auto'),
        ], className='mb-2 align-items-end'),

        # 체크박스 선택/이동/삭제 버튼은 화면(브라우저) 스크롤에 영향받지
        # 않도록 항상 보이는 위치에 고정한다(2026-09-16, 사용자 요청 —
        # 아래쪽 행을 체크하려면 위로 스크롤해 이 버튼을 누른 뒤 결과를
        # 보려고 다시 아래로 스크롤해야 하는 불편함이 있었음). CSS
        # (assets/custom.css의 .team-refer-sticky-toolbar)가
        # position: sticky로 네비게이션 바 바로 아래에 붙인다 — 네비게이션
        # 바 실제 높이는 assets/team_refer_grid.js가 재서 CSS 변수로
        # 넘겨준다(고정 픽셀로 하드코딩하면 화면 폭에 따라 네비게이션
        # 바 줄바꿈이 달라질 때 어긋날 수 있음).
        html.Div([
            dbc.ButtonGroup([
                dbc.Button([html.I(className='bi bi-arrow-bar-up me-1'), '맨 위로'],
                           id='team-refer-move-top-btn', color='secondary', outline=True, size='sm'),
                dbc.Button([html.I(className='bi bi-arrow-up me-1'), '위로'],
                           id='team-refer-move-up-btn', color='secondary', outline=True, size='sm'),
                dbc.Button([html.I(className='bi bi-arrow-down me-1'), '아래로'],
                           id='team-refer-move-down-btn', color='secondary', outline=True, size='sm'),
                dbc.Button([html.I(className='bi bi-arrow-bar-down me-1'), '맨 아래로'],
                           id='team-refer-move-bottom-btn', color='secondary', outline=True, size='sm'),
                dbc.Button([html.I(className='bi bi-trash me-1'), '선택 삭제'],
                           id='team-refer-bulk-delete-btn', color='danger', outline=True, size='sm'),
            ]),
        ], className='team-refer-sticky-toolbar'),

        dcc.Download(id='team-refer-download'),
        html.Div(id='team-refer-db-load-msg'),
        html.Div(id='team-refer-bulk-msg'),

        # id를 가진 고정 래퍼 — assets/team_refer_grid.js가 이 안에서 네비게이션
        # 바 높이를 재 CSS 변수로 넘겨준다(.team-refer-sticky-toolbar가 씀).
        # AG Grid가 내부 DOM을 재렌더링해도 이 래퍼 자체의 id는 계속 유지된다.
        html.Div(
            dag.AgGrid(
                id='team-refer-table',
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
                    # 헤더 전체선택 체크박스 포함 — dash_table에는 없던 기능이라
                    # 예전엔 '전체 선택/해제' 버튼으로 대신했으나 AG Grid는
                    # 기본 제공한다(2026-09-17, AG Grid 전환).
                    'rowSelection': {'mode': 'multiRow', 'checkboxes': True, 'headerCheckbox': True},
                    'domLayout': 'autoHeight',  # 페이지 나누지 않고 전체 행을 한 번에 표시(dash_table의 page_action='none'과 동일)
                    'stopEditingWhenCellsLoseFocus': True,
                    'tooltipShowDelay': 0,
                },
                # 엑셀 업로드 직후에만 _mark_stale_rows()가 채우는 `_stale`을
                # 보고 배경색을 강조한다(2026-09-16, 사용자 요청) — 코드 실행
                # 플래그(dangerously_allow_code) 없이 되는 선언형 방식(dash-ag-grid
                # 전용 styleConditions, pages/researcher_list.py의 홀수행
                # 줄무늬와 동일한 패턴).
                getRowStyle={
                    'styleConditions': [
                        {'condition': 'params.data._stale === true',
                         'style': {'backgroundColor': '#fff3cd'}},
                    ],
                },
                # 헤더 클릭 정렬(sortable=True)은 화면 표시 순서만 바꾸고
                # rowData 자체의 순서는 그대로 유지됨을 확인했다 — 이동/삭제가
                # 배열 순서=계층 구조를 가정하는 로직(_row_path 등)에 영향 없음.
                # 폰트 크기는 style이 아니라 className='gs-ag-grid'(assets/
                # custom.css)의 --ag-font-size로 지정한다 — AG Grid는 내부
                # 셀/헤더 글자 크기를 이 CSS 변수로 그리므로, 여기 style에
                # fontSize를 줘도 반영되지 않는다(격리 테스트로 확인,
                # 2026-09-17).
                style={'width': '100%'},
            ),
            id='team-refer-grid-wrap',
        ),

        html.Div(id='team-refer-save-msg', className='mt-2'),

        # "엑셀 파일로 한번에 반영" 카드는 탭 맨 아래로 이동(사용자 확정
        # 2026-09-02) — 위 표로 직접 편집하는 것이 주 흐름이고, 엑셀 일괄
        # 반영은 보조 수단이라 화면 아래쪽에 두는 것이 자연스럽다.
        _team_refer_upload_section(),

        # 저장한 행들 안에 부서ID(dep_id)가 중복되면(업서트 자연키 충돌로
        # 일부 행이 조용히 사라지는 원인) 별도 창으로 바로 보여준다(사용자
        # 요청) — docs/CLAUDE.md 참고.
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle([
                    html.I(className='bi bi-exclamation-triangle-fill text-warning me-2'),
                    '부서ID(dep_id) 중복 발견',
                ])),
                dbc.ModalBody(id='team-refer-dupe-modal-body'),
                dbc.ModalFooter(dbc.Button('확인', id='team-refer-dupe-modal-close', size='sm')),
            ],
            id='team-refer-dupe-modal', is_open=False, size='lg',
        ),

        # "(SAIT)"/"(기술원)" 표기 제거로 서로 다른 원본이 하나로 합쳐지면
        # 값 손실이 없는지 확인할 수 있도록 별도 창으로 보여준다(2026-09-15
        # 확정 — docs/CLAUDE.md 참고).
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle([
                    html.I(className='bi bi-info-circle-fill text-info me-2'),
                    '조직명 병합 확인 — "(SAIT)"/"(기술원)" 표기 제거',
                ])),
                dbc.ModalBody(id='team-refer-merge-modal-body'),
                dbc.ModalFooter(dbc.Button('확인', id='team-refer-merge-modal-close', size='sm')),
            ],
            id='team-refer-merge-modal', is_open=False, size='lg',
        ),
    ], className='pt-3')


# ── 콜백: 팀/리더 참조 — 행 추가 ─────────────────────────────────────────────
# 항상 맨 뒤에 추가한다(2026-09-17, AG Grid 전환과 함께 단순화 — 예전엔
# 클릭해둔 셀 바로 다음에 끼워 넣었으나, AG Grid의 selectedRows는 클릭
# 위치가 아니라 체크된 행 전체를 담는 값이라 같은 방식으로 재현하려면
# 별도 상태 추적이 필요해 실익 대비 복잡도가 커 뺐다 — 새 행은 맨 뒤에서
# "위로" 버튼으로 옮기면 된다). 3단계 부서 체계 도입 이후 부서ID는 더
# 이상 그리드 컬럼이 아니라(경로에서 자동 계산) "다음 번호 자동 제안"
# 기능도 없다 — 새 행은 빈 칸으로 추가되고, 1/2/3단계부서명을 자기
# 레벨까지 채우면 된다.
@callback(
    Output('team-refer-table', 'rowData', allow_duplicate=True),
    Output('team-refer-table', 'selectedRows', allow_duplicate=True),
    Input('team-refer-add-row-btn', 'n_clicks'),
    State('team-refer-table', 'rowData'),
    prevent_initial_call=True,
)
def team_refer_add_row(n_clicks, rows):
    if not n_clicks:
        return no_update, no_update
    rows = list(rows or [])
    new_row = {col: '' for col in team_refer_store.KOREAN_COLUMNS}
    new_row['_rid'] = uuid.uuid4().hex[:12]
    rows.append(new_row)
    # 새 행이 맨 뒤에 붙으며 총 행 수가 늘므로 No./조직코드를 화면 순서
    # 그대로 다시 매긴다(맨 위 1 ~ 맨 아래 N, 2026-09-16 확정). 'No.'는
    # getRowId를 쓰는 AG Grid에서 rowIndex 파생 값이 행 순서 변경만으로는
    # 자동 갱신되지 않음을 확인해(위 컬럼 정의 주석 참고) 실제 필드 값으로
    # 둔다.
    rows = _renumbered(rows)
    _renumber_dep_codes(rows)
    return rows, []


# ── 콜백: 팀/리더 참조 — 체크박스 선택 삭제(2026-09-15) ───────────────────────
# 체크한 행 + 그 하위 조직 전체(_subtree_range)를 한번에 지운다 — 부모만
# 체크해도 자식이 자동으로 함께 삭제된다(하위 조직을 남겨두면 그 소속 정보
# 때문에 상위 조직이 자동으로 다시 생겨 실제로 삭제되지 않기 때문 —
# 2026-09-16 재확인, "구조" 열 제거와 무관하게 삭제만은 계속 하위 조직
# 포함). 행 1개만 지우고 싶을 때도 그 행 하나만 체크해 이 버튼으로
# 지운다(AG Grid Community에는 dash_table의 행별 × 삭제 버튼 같은 기본
# 제공 UI가 없어 2026-09-17 전환과 함께 정리 — 기능은 이 버튼 하나로
# 통합).
@callback(
    Output('team-refer-table', 'rowData', allow_duplicate=True),
    Output('team-refer-table', 'selectedRows', allow_duplicate=True),
    Output('team-refer-bulk-msg', 'children', allow_duplicate=True),
    Input('team-refer-bulk-delete-btn', 'n_clicks'),
    State('team-refer-table', 'rowData'),
    State('team-refer-table', 'selectedRows'),
    prevent_initial_call=True,
)
def team_refer_bulk_delete(n_clicks, rows, selected_rows):
    if not n_clicks:
        return no_update, no_update, no_update
    rows = list(rows or [])
    selected_rids = {r['_rid'] for r in (selected_rows or []) if r.get('_rid')}
    selected_idx = [i for i, r in enumerate(rows) if r.get('_rid') in selected_rids]
    if not selected_idx:
        return no_update, no_update, _alert('삭제할 행을 먼저 체크해주세요.', 'warning')

    # 하위 조직 판정(_subtree_range)은 계층적(부모→자식) 순서를 전제로
    # 한다 — AG Grid 헤더 클릭 정렬은 화면 표시 순서만 바꾸고 rowData 배열
    # 순서 자체는 그대로 유지됨을 확인했으므로(2026-09-17), 정렬 중에도
    # 이 전제가 깨지지 않아 예전처럼 "정렬 해제" 요청이 필요 없다.
    to_delete: set = set()
    for idx in selected_idx:
        start, end = _subtree_range(rows, idx)
        to_delete.update(range(start, end))

    new_rows = [r for i, r in enumerate(rows) if i not in to_delete]
    new_rows = _renumbered(new_rows)
    _renumber_dep_codes(new_rows)
    msg = _alert(f'{len(to_delete)}개 행을 삭제했습니다(하위 조직 포함). "저장"을 눌러야 실제로 반영됩니다.',
                 'success')
    return new_rows, [], msg


# ── 콜백: 팀/리더 참조 — 체크박스 선택 위/아래 이동(2026-09-16 단순화) ─────────
# 체크한 행 하나하나를 각각 한 칸씩 개별로 위/아래로 옮긴다 — 하위 조직을
# 묶어서 함께 옮기지 않고, 상위부서 경계와도 무관하게 그리드 전체에서
# 자유롭게 이동한다(사용자 확정, "구조" 열 제거와 함께 단순화). 여러 개
# 체크하면 이동 방향에 맞는 순서로 처리해 인접한 선택끼리 자연스럽게 함께
# 밀려 올라가거나/내려간다. 그리드 맨 위(위로 이동 시)/맨 아래(아래로 이동
# 시)에 이미 있는 행은 더 이상 이동할 수 없어 건너뛴다.
def _move_selected(rows: list, selected_rows: list, direction: str):
    rows = list(rows)
    own_paths = []
    seen = set()
    for idx in selected_rows:
        if 0 <= idx < len(rows):
            p = _row_path(rows[idx])
            if p not in seen:
                seen.add(p)
                own_paths.append(p)

    # 경로별 "현재 인덱스"를 매번 rows 전체를 다시 스캔해서 찾지 않고
    # (예전 방식 — 체크한 행마다 O(N) 스캔을 2번씩 해서 사실상 O(N^2),
    # 2026-09-17 확인: 2,000행 전체 선택 후 이동 시 3초 넘게 걸려 화면이
    # 멈춘 것처럼 보이는 원인으로 확인됨) 사전(index_of)에 한 번만 담아두고
    # 스왑이 일어날 때마다 그 두 행의 인덱스만 O(1)로 갱신한다.
    index_of = {_row_path(r): i for i, r in enumerate(rows)}

    ordered = sorted(
        (p for p in own_paths if p in index_of),
        key=lambda p: index_of[p], reverse=(direction == 'down'),
    )

    blocked = 0
    for path in ordered:
        idx = index_of.get(path)
        if idx is None:
            continue
        if direction == 'up':
            if idx == 0:
                blocked += 1
                continue
            other_path = _row_path(rows[idx - 1])
            rows[idx - 1], rows[idx] = rows[idx], rows[idx - 1]
            index_of[path] = idx - 1
            index_of[other_path] = idx
        else:
            if idx >= len(rows) - 1:
                blocked += 1
                continue
            other_path = _row_path(rows[idx + 1])
            rows[idx], rows[idx + 1] = rows[idx + 1], rows[idx]
            index_of[path] = idx + 1
            index_of[other_path] = idx

    new_selected = [i for i, r in enumerate(rows) if _row_path(r) in seen]
    return rows, new_selected, blocked


# ── 팀/리더 참조 그리드 — 체크박스 선택 맨 위/맨 아래로 이동(2026-09-17 추가) ───
# _move_selected()(한 칸씩)와 달리 체크한 행들을 한 번에 그리드 맨 위/맨
# 아래로 보낸다 — 여러 칸 떨어진 곳으로 옮기려고 "위로"/"아래로"를 여러 번
# 누를 필요가 없게. 체크한 행들끼리의 상대 순서, 체크하지 않은 행들끼리의
# 상대 순서는 각각 원래 배열 순서 그대로 유지된다(안정 분할 — stable
# partition). 이동은 여기서도 상위부서 경계와 무관하게 체크한 행만
# 개별적으로 옮긴다(하위 조직을 묶어 옮기지 않음 — 위/아래 한 칸 이동과
# 동일한 방침, 2026-09-16 확정).
def _move_to_edge(rows: list, selected_idx: list, edge: str):
    selected_set = set(selected_idx)
    picked = [r for i, r in enumerate(rows) if i in selected_set]
    rest = [r for i, r in enumerate(rows) if i not in selected_set]
    if edge == 'top':
        new_rows = picked + rest
        new_selected_idx = list(range(len(picked)))
    else:
        new_rows = rest + picked
        new_selected_idx = list(range(len(rest), len(new_rows)))
    return new_rows, new_selected_idx


@callback(
    Output('team-refer-table', 'rowData', allow_duplicate=True),
    Output('team-refer-table', 'selectedRows', allow_duplicate=True),
    Output('team-refer-bulk-msg', 'children', allow_duplicate=True),
    Input('team-refer-move-top-btn', 'n_clicks'),
    Input('team-refer-move-up-btn', 'n_clicks'),
    Input('team-refer-move-down-btn', 'n_clicks'),
    Input('team-refer-move-bottom-btn', 'n_clicks'),
    State('team-refer-table', 'rowData'),
    State('team-refer-table', 'selectedRows'),
    prevent_initial_call=True,
)
def team_refer_move_selected(n_top, n_up, n_down, n_bottom, rows, selected_rows):
    trig = ctx.triggered_id
    n_clicks_by_id = {
        'team-refer-move-top-btn': n_top,
        'team-refer-move-up-btn': n_up,
        'team-refer-move-down-btn': n_down,
        'team-refer-move-bottom-btn': n_bottom,
    }
    if not trig or not n_clicks_by_id.get(trig):
        return no_update, no_update, no_update

    rows = list(rows or [])
    selected_rids = {r['_rid'] for r in (selected_rows or []) if r.get('_rid')}
    selected_idx = [i for i, r in enumerate(rows) if r.get('_rid') in selected_rids]
    if not selected_idx:
        return no_update, no_update, _alert('이동할 행을 먼저 체크해주세요.', 'warning')

    if trig in ('team-refer-move-up-btn', 'team-refer-move-down-btn'):
        direction = 'up' if trig == 'team-refer-move-up-btn' else 'down'
        new_rows, new_selected_idx, blocked = _move_selected(rows, selected_idx, direction)
        msg = (_alert('이미 맨 위/맨 아래에 있어 더 이상 이동할 수 없는 행이 있습니다.', 'info')
               if blocked else no_update)
    else:
        edge = 'top' if trig == 'team-refer-move-top-btn' else 'bottom'
        new_rows, new_selected_idx = _move_to_edge(rows, selected_idx, edge)
        msg = no_update

    new_rows = _renumbered(new_rows)
    _renumber_dep_codes(new_rows)
    new_selected_rows = [new_rows[i] for i in new_selected_idx]
    return new_rows, new_selected_rows, msg


# assets/team_refer_grid.js의 window.__syncTeamReferNavbarHeight()가
# 네비게이션 바 실제 높이를 재 CSS 변수로 넘긴다(.team-refer-sticky-toolbar가
# 그 값을 씀) — AG Grid가 rowData를 그릴 때마다(최초 로드 포함) 네비게이션
# 바가 이미 렌더링되어 있음이 보장되는 시점이라 이 Input에 건다(2026-09-17,
# 예전 자동채움 가이드 갱신 콜백에 얹혀 있던 것을 분리 — 그 콜백 자체는
# AG Grid 전환으로 제거됨).
clientside_callback(
    """
    function(rowData) {
        if (window.__syncTeamReferNavbarHeight) {
            window.__syncTeamReferNavbarHeight();
        }
        return '';
    }
    """,
    Output('team-refer-grid-dummy', 'children'),
    Input('team-refer-table', 'rowData'),
)


# ── 콜백: 팀/리더 참조 — 저장 ─────────────────────────────────────────────────
# 행 삭제는 위 team_refer_bulk_delete가 서버 콜백으로 처리하므로(AG Grid
# Community에는 dash_table의 row_deletable 같은 클라이언트 자동 삭제가
# 없음) 별도 저장 로직은 없다. 3단계 부서 체계 도입 이후 dep_id는 부서명
# 경로에서 매번 새로 계산되는 값이라(사람이 타이핑하는 값이 아님) "그리드에서
# 사라진 부서ID"를 여기서 직접 비교할 방법이 없다 — 대신 team_refer_store.
# save_snapshot()이 process_team_refer.tombstone_missing_dep_ids()로 저장
# 시점마다 자동으로 삭제(톰스톤) 대상을 찾아 처리한다(그리드가 매번 "현재
# 조직 전체"를 불러와 그 전체를 다시 저장하는 구조이므로 가능).
@callback(
    Output('team-refer-save-msg', 'children'),
    Output('team-refer-dupe-modal', 'is_open', allow_duplicate=True),
    Output('team-refer-dupe-modal-body', 'children'),
    Output('team-refer-merge-modal', 'is_open', allow_duplicate=True),
    Output('team-refer-merge-modal-body', 'children'),
    Input('team-refer-save-btn', 'n_clicks'),
    State('team-refer-table', 'rowData'),
    State('team-refer-hidden-rows', 'data'),
    State('team-refer-valid-date', 'date'),
    prevent_initial_call=True,
)
def team_refer_save(n_clicks, rows, hidden_rows, valid_date_str):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 저장할 수 있습니다.', 'danger'), no_update, no_update, no_update, no_update
    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update
    if not valid_date_str:
        return _alert('입력 날짜를 선택해주세요.', 'warning'), no_update, no_update, no_update, no_update

    valid_date = date.fromisoformat(valid_date_str[:10])
    # 화면에 보이는(편집된) 행 + 가독성을 위해 숨겨뒀던 행(비공식소속부서명
    # 공백, _split_hidden_rows 참고)을 합쳐서 저장한다 — 숨긴 행을 빼고
    # 저장하면 tombstone_missing_dep_ids()가 "이번 저장에 없다"고 보고
    # 실수로 삭제 처리할 것이다.
    rows = list(rows or []) + list(hidden_rows or [])

    valid_rows = [r for r in rows if str(r.get('1단계부서명') or '').strip()]
    skipped = len(rows) - len(valid_rows)

    result = team_refer_store.save_snapshot(valid_rows, valid_date)
    team_refer_store.export_snapshot_xlsx(valid_rows, valid_date)

    parts = [
        f"저장 완료 — 이번 저장 {result['saved_rows']}행 반영"
        + ('' if result['db_ok'] else ' (DB 미반영, CSV에는 반영됨)') + '.',
    ]
    if skipped:
        parts.append(f'1단계부서명이 비어 있어 {skipped}행은 저장에서 제외됐습니다.')

    dupes = result.get('duplicate_dep_ids') or []
    if dupes:
        parts.append(f'부서ID가 중복된 항목이 {len(dupes)}건 있어 일부 행이 저장되지 '
                      '않았을 수 있습니다 — 아래 창을 확인해주세요.')

    merges = result.get('tag_merges') or []
    if merges:
        parts.append(f'"(SAIT)"/"(기술원)" 표기 제거로 {len(merges)}건이 하나의 조직으로 '
                      '합쳐졌습니다 — 값이 유실되지 않았는지 아래 창에서 확인해주세요.')

    alert_color = 'warning' if (dupes or merges) else 'success'
    body = [html.Div(p) for p in parts]

    msg = dbc.Alert(body, color=alert_color, dismissable=True, className='py-2 small mb-0')
    return msg, bool(dupes), _dupe_modal_body(dupes), bool(merges), _merge_modal_body(merges)


# ── 콜백: 팀/리더 참조 — 현재 기준 엑셀 다운로드 ──────────────────────────────
# 그리드에 편집 중인(아직 저장 안 한) 내용이 아니라, 저장소에 이미 반영된
# 최신 값(dep_id별 최신·비삭제 행)을 그대로 내려받는다(사용자 확정).
@callback(
    Output('team-refer-download', 'data'),
    Input('team-refer-download-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def team_refer_download(n_clicks):
    from services.auth import can
    if not n_clicks or not can('manage_users'):
        return no_update
    data = team_refer_store.current_snapshot_workbook_bytes()
    fname = f"팀_리더_참조_{date.today().strftime('%Y%m%d')}.xlsx"
    return dcc.send_bytes(data, fname)


# ── 콜백: 팀/리더 참조 — team_refer 테이블만 DB 반영 ──────────────────────────
# "저장" 버튼(그리드 편집분)은 team_refer_store.save_snapshot()이 CSV와 함께
# DB도 이미 반영하지만, "엑셀 파일로 한번에 반영"(대량 업로드,
# pipeline/process_team_refer.py의 process())은 CSV만 쓰고 DB는 건드리지
# 않는다 — 그 경로로 반영한 뒤에는 DB가 CSV보다 뒤처진 채로 남는다. 이
# 버튼으로 저장된 최신 team_refer.csv를 그 자리에서 바로 DB에 반영할 수
# 있다(2026-09-02 추가, 아이콘 버튼).
@callback(
    Output('team-refer-db-load-msg', 'children'),
    Input('team-refer-db-load-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def team_refer_db_load(n_clicks):
    from services.auth import can
    if not can('manage_users'):
        return _alert('관리자만 DB에 반영할 수 있습니다.', 'danger')
    if not n_clicks:
        return no_update
    ok, msg = wpr.run_team_refer_db_load()
    return _alert(f'DB 반영 완료 — {msg}' if ok else f'DB 반영 실패 — {msg}',
                  'success' if ok else 'danger')


def _dupe_modal_body(dupes: list[dict]):
    """부서ID(dep_id) 중복 그룹 리스트를 별도 창(모달)에 보여줄 표로 렌더링.
    dupes: pipeline.process_team_refer.find_duplicate_dep_ids()의 반환값
    (display_cols: dep_id/dep_code/dep_1st_name/dep_2nd_name/dep_3rd_name/
    upper_dep_id/researcher_id/name)."""
    if not dupes:
        return None
    header = html.Thead(html.Tr([
        html.Th('부서ID'), html.Th('조직코드'), html.Th('1단계'), html.Th('2단계'), html.Th('3단계'),
        html.Th('상위부서ID'), html.Th('사번'), html.Th('성명'),
    ]))
    body_rows = []
    for g in dupes:
        for row in g['rows']:
            body_rows.append(html.Tr([
                html.Td(g['dep_id'], className='fw-semibold'),
                html.Td(row['dep_code']), html.Td(row['dep_1st_name']),
                html.Td(row['dep_2nd_name']), html.Td(row['dep_3rd_name']),
                html.Td(row['upper_dep_id']), html.Td(row['researcher_id']), html.Td(row['name']),
            ]))
    return html.Div([
        html.Div(
            f"같은 부서ID를 가진 행이 {len(dupes)}개 부서ID에서 발견됐습니다 — 같은 "
            '부서ID로는 하나만 저장되고 나머지는 사라지니, 부서ID를 다르게 고쳐서 '
            '다시 저장해주세요.',
            className='small text-muted mb-2',
        ),
        dbc.Table([header, html.Tbody(body_rows)], bordered=True, hover=True, size='sm',
                   responsive=True, className='mb-0'),
    ])


@callback(
    Output('team-refer-dupe-modal', 'is_open', allow_duplicate=True),
    Input('team-refer-dupe-modal-close', 'n_clicks'),
    prevent_initial_call=True,
)
def team_refer_close_dupe_modal(n_clicks):
    if not n_clicks:
        return no_update
    return False


def _merge_modal_body(merges: list[dict]):
    """"(SAIT)"/"(기술원)" 태그 제거로 여러 원본 조직이 하나로 합쳐진 경우를
    보여준다. merges: pipeline.process_team_refer.find_tag_merges()의 반환값
    — 각 병합 그룹마다 원래 표기(variants)와 최종 유지된 값(kept)을 대조해서
    값 손실이 없는지 확인할 수 있게 한다. kept은 필드별로 "먼저 나온 값
    우선"이라 variants 중 어느 한 행과 정확히 일치한다는 보장이 없어(예:
    조직코드는 A 행 것, 사번은 B 행 것이 섞여 남을 수 있음), 행 단위로
    "이 값이 유지됐다"고 표시하지 않고 원본들과 최종 값을 나란히 보여주는
    방식으로 구성했다."""
    if not merges:
        return None
    header = html.Thead(html.Tr([
        html.Th('구분'), html.Th('표기'), html.Th('조직코드'),
        html.Th('사번'), html.Th('성명'), html.Th('직책'),
    ]))
    body_rows = []
    for m in merges:
        body_rows.append(html.Tr([
            html.Td(f"■ {m['merged_name']}으로 합쳐짐", colSpan=6, className='fw-semibold bg-light'),
        ]))
        for v in m['variants']:
            body_rows.append(html.Tr([
                html.Td('원본'), html.Td(v['original_name']),
                html.Td(v['dep_code']), html.Td(v['researcher_id']),
                html.Td(v['name']), html.Td(v['assignment_name']),
            ], className='text-muted'))
        k = m['kept']
        body_rows.append(html.Tr([
            html.Td('최종 유지', className='fw-semibold'), html.Td(m['merged_name']),
            html.Td(k['dep_code']), html.Td(k['researcher_id']),
            html.Td(k['name']), html.Td(k['assignment_name']),
        ], className='table-success'))
    return html.Div([
        html.Div(
            f'"(SAIT)"/"(기술원)" 표기가 제거되면서 {len(merges)}건이 같은 이름의 조직으로 '
            '합쳐졌습니다. 필드마다 먼저 값이 채워진 원본이 우선 채택되므로(조직코드는 '
            'A 원본, 사번은 B 원본 것이 섞여 남을 수 있음), 초록색 "최종 유지" 행과 위쪽 '
            '"원본" 행들을 비교해 필요한 값이 빠지지 않았는지 확인해주세요. 빠진 값이 있으면 '
            '"최종 유지" 행에 해당하는 실제 그리드 행에 직접 채워 넣은 뒤 다시 저장하면 됩니다.',
            className='small text-muted mb-2',
        ),
        dbc.Table([header, html.Tbody(body_rows)], bordered=True, hover=True, size='sm',
                   responsive=True, className='mb-0'),
    ])


@callback(
    Output('team-refer-merge-modal', 'is_open', allow_duplicate=True),
    Input('team-refer-merge-modal-close', 'n_clicks'),
    prevent_initial_call=True,
)
def team_refer_close_merge_modal(n_clicks):
    if not n_clicks:
        return no_update
    return False


# ── 콜백: 팀/리더 참조 — 엑셀 업로드 실행 ─────────────────────────────────────
# hidden_from_table 항목이라 "데이터 업데이트" 탭의 전체/선택 실행 버튼과
# 무관한 이 탭 전용 실행 트리거가 필요하다.
@callback(
    Output('team-refer-upload-status', 'children', allow_duplicate=True),
    Output('data-update-interval', 'disabled', allow_duplicate=True),
    Output('team-refer-highlight-date', 'data', allow_duplicate=True),
    Input('team-refer-run-upload-btn', 'n_clicks'),
    State({'type': 'du-valid-date', 'key': 'team_refer'}, 'date'),
    prevent_initial_call=True,
)
def team_refer_run_upload(n_clicks, valid_date_str):
    from services.auth import can
    if not n_clicks:
        return no_update, no_update, no_update
    if not can('manage_users'):
        return _alert('관리자만 실행할 수 있습니다.', 'danger'), True, no_update
    if not wpr.has_upload('team_refer'):
        return _alert('업로드된 파일이 없습니다.', 'warning'), True, no_update

    # 일(day) 단위까지 그대로 반영한다(2026-09-16 수정 — _valid_date_picker
    # 참고: 예전에는 항상 일=1로 고정 저장돼, 이미 그달 중 더 늦은 날짜로
    # 저장된 값에 밀려 새로 올린 엑셀이 "최신"으로 반영되지 않는 문제가 있었음).
    highlight_date = valid_date_str or date.today().isoformat()
    valid_dates = {'team_refer': date.fromisoformat(valid_date_str)} if valid_date_str else {}
    if not wpr.start_run(['team_refer'], valid_dates=valid_dates):
        return _alert('이미 다른 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.', 'warning'), False, no_update
    # team-refer-highlight-date를 이번 업로드 날짜로 채워, 완료 후
    # data_update_poll()이 그리드를 새로고침할 때 이 날짜와 다른(=이번
    # 업로드로 안 갱신된) 행을 색으로 강조하게 한다(_mark_stale_rows() 참고).
    return (_alert('실행을 시작했습니다. 브라우저를 닫아도 서버에서 계속 진행되며, '
                    '화면은 자동으로 갱신됩니다.', 'info'), False, highlight_date)
