"""
자연어 질문 바 — "특정 전문성 보유자 찾기"/"연구원과 유사한 연구원 찾기"
(구조화 조회) + 그 밖의 원천 데이터 개방형 질문(services.open_data_query,
SQL 생성)을 4개 intent 모두 같은 표 형태(columns/labels/rows)로 받는다.
자세한 아키텍처는 services/nl_query.py, services/open_data_query.py 모듈
docstring 참고.

연구원 명단 화면(pages/researcher_list.py) 전용 컴포넌트다 — 검색 결과의
표 렌더링은 이 모듈이 직접 하지 않고, researcher_list.py의
연구원명단 테이블(researcher-table)이 nl-query-full-result Store를 읽어
그 열/행으로 바꿔치기한다("AI 검색과 아래 명단이 별 창처럼 헷갈린다"는
사용자 피드백에 따라 명단 자체가 검색 결과가 되도록 통합 — data/processed/
CLAUDE.md 참고). 이 모듈은 질문 입력창과, 검색 결과에 대한 AI 답변 문장/
안내 메시지만 렌더링한다.

Dash 콜백 설계 메모(재발 방지 — data/processed/CLAUDE.md에도 기록):
매 렌더링마다 새로 나타나는 컴포넌트에 건 콜백은, Dash가 "새로 나타난
컴포넌트"를 클릭 없이 한 번 더 실행시키는 현상(팬텀 트리거)이 있다. 이
모듈은 더 이상 그런 동적 컴포넌트(정렬/필터 드롭다운, 행 체크박스 등)를
만들지 않으므로(명단 테이블 쪽 책임) 이 문제와 무관해졌다.
"""

from datetime import date

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from services import nl_query
from services import query_settings


def render() -> html.Div:
    """연구원 명단 화면(researcher_list.py)에 삽입하는 자연어 질문 바.
    검색 기준(최신/누적)은 이 컴포넌트가 따로 갖지 않고, 같은 화면의
    'list-search-mode' 라디오를 State로 공유한다(명단 필터와 검색 기준이
    화면에 두 벌 있으면 헷갈린다는 사용자 피드백에 따라 하나로 통일)."""
    return html.Div([
        html.Div([
            html.H5(
                [html.I(className='bi bi-robot me-2 text-primary'), 'AI 검색',
                 html.Small(' 자연어로 물어보면 아래 명단이 그 결과로 바뀝니다', className='text-muted fw-normal')],
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
                placeholder='예: "로봇 제어 전문가 찾아줘", "물리학 전공한 사람 찾아줘", '
                            '"특허 3건 이상인 연구원"',
            ),
            dbc.Button([html.I(className='bi bi-search me-1'), '질문하기'],
                       id='nl-query-submit', color='primary', n_clicks=0),
            dbc.Button([html.I(className='bi bi-x-circle me-1'), '초기화'],
                       id='nl-query-reset-btn', color='secondary', outline=True, n_clicks=0),
        ], className='mb-2'),
        # target_components: 실제 느린 작업(LLM 호출 + SQL 실행)은 _run_nl_query
        # 콜백이 하고 그 결과를 화면에 안 보이는 nl-query-full-result Store에
        # 담는다 — 이 Store가 Loading의 자식이 아니라서(안 보이는 컴포넌트라
        # 안에 둘 수 없음) 그냥 두면 스피너가 실제 대기 시간 동안 뜨지 않는다.
        # target_components로 "이 컴포넌트의 이 prop이 갱신되는 동안 로딩
        # 표시"를 명시적으로 지정해 해결한다.
        dcc.Loading(
            html.Div(id='nl-query-note'),
            target_components={'nl-query-full-result': 'data'},
        ),
        dcc.Store(id='nl-query-full-result'),
    ], className='mb-3')


def answer_block(answer: str):
    """AI가 만든 자연어 답변 문장(예: "로봇 제어 전문가는 총 3명입니다")을
    보여주는 알림 박스. researcher_list.py도 재사용하지 않는다 — 답변
    렌더링은 이 모듈의 _render_nl_query_note 콜백이 전담하고, 명단 쪽은
    표 데이터만 가져간다."""
    return dbc.Alert([
        html.Div([html.I(className='bi bi-robot me-2'), html.Span('AI 답변', className='fw-semibold')],
                 className='mb-1'),
        html.Div(answer, className='small', style={'whiteSpace': 'pre-wrap'}),
    ], color='primary', className='mb-0')


@callback(
    Output('nl-query-full-result', 'data'),
    Input('nl-query-submit', 'n_clicks'),
    Input('nl-query-input', 'n_submit'),
    State('nl-query-input', 'value'),
    State('list-search-mode', 'value'),
    State('list-period-range', 'start_date'),
    State('list-period-range', 'end_date'),
    prevent_initial_call=True,
)
def _run_nl_query(_n_clicks, _n_submit, question, search_mode, period_start, period_end):
    """실제 LLM 호출/SQL 실행을 여기서 한 번만 하고 dcc.Store에 담아 둔다 —
    researcher_list.py의 update_table 콜백이 이 Store를 Input으로 받아
    명단 테이블의 데이터/컬럼을 그 결과로 바꾼다.

    누적기준에서 명단과 동일하게 기간(list-period-range)을 지정할 수 있다
    (2026-08-28) — 지정하면 그 기간의 마지막 스냅샷 기준으로 조회한다(연/월
    단위만 의미가 있어 날짜에서 일자는 버리고 nl_query.answer_question()에
    "YYYY-MM" 튜플로 넘긴다)."""
    from dash.exceptions import PreventUpdate
    from services.auth import get_current_user
    if get_current_user() is None:
        raise PreventUpdate
    empty = {'intent': 'unsupported', 'columns': [], 'labels': [], 'rows': [], 'total_rows': 0, 'note': ''}
    if not question or not question.strip():
        return {**empty, 'note': '질문을 입력해주세요.'}

    current_only = (search_mode != 'all')
    period = None
    if search_mode == 'all' and period_start and period_end:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
        period = (f'{start.year:04d}-{start.month:02d}', f'{end.year:04d}-{end.month:02d}')

    return nl_query.answer_question(question, current_only=current_only, period=period)


@callback(
    Output('nl-query-rules-collapse', 'is_open'),
    Output('nl-query-rules-textarea', 'value'),
    Input('nl-query-rules-toggle-btn', 'n_clicks'),
    State('nl-query-rules-collapse', 'is_open'),
    prevent_initial_call=True,
)
def _toggle_rules_panel(n_clicks, is_open):
    """열 때마다 디스크에서 최신 규칙을 다시 읽는다 — render()가 페이지
    진입 시점에 한 번만 호출되므로(다른 세션이 그 사이 저장한 내용을 못
    보는 문제 방지), 텍스트를 layout에 미리 심어 두지 않고 여기서 매번 갱신."""
    from services.auth import can
    if not n_clicks:
        return dash.no_update, dash.no_update
    if not can('manage_users'):
        return False, ''
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
    from services.auth import can
    if not n_clicks:
        return dash.no_update
    if not can('manage_users'):
        return html.Span('관리자만 AI 검색 규칙을 변경할 수 있습니다.', className='text-danger small')
    query_settings.write_rules(text or '')
    return html.Span([html.I(className='bi bi-check-circle-fill me-1'), '저장되었습니다.'],
                      className='text-success small')


@callback(
    Output('nl-query-note', 'children'),
    Input('nl-query-full-result', 'data'),
    prevent_initial_call=True,
)
def _render_nl_query_note(full_result):
    """검색 결과의 표는 명단 테이블이 그리므로, 여기서는 AI 답변 문장/안내
    메시지만 보여준다. full_result가 None(초기화 버튼으로 비워짐)이면
    아무것도 보여주지 않는다."""
    if not full_result:
        return None
    intent = full_result.get('intent')
    note = full_result.get('note', '')
    answer = full_result.get('answer')
    if intent in ('error', 'unsupported'):
        return dbc.Alert(note, color='warning', className='mb-0')
    children = []
    if answer:
        children.append(answer_block(answer))
    elif note:
        children.append(html.Div(note, className='small text-muted'))
    if not full_result.get('rows'):
        children.append(dbc.Alert(note or '검색 결과가 없습니다.', color='light', className='mb-0 border mt-2'))
    return html.Div(children) if children else None


@callback(
    Output('nl-query-input', 'value'),
    Output('nl-query-full-result', 'data', allow_duplicate=True),
    Input('nl-query-reset-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def _reset_query(n_clicks):
    """검색창/답변/명단을 전부 초기 상태로 되돌린다(사용자 확정: 검색어
    텍스트까지 포함해 완전 초기화). full_result를 None으로 비우면
    researcher_list.py의 update_table 콜백이 명단을 필터 기준 전체
    목록으로 되돌린다."""
    if not n_clicks:
        return dash.no_update, dash.no_update
    return '', None
