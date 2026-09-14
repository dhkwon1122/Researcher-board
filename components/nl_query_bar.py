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

Dash 콜백 설계 메모(재발 방지 — docs/CLAUDE.md에도 기록):
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
from services import nl_query_feedback
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
                 html.Small(' 자연어 질문 시 결과가 아래에 명단으로 생성', className='text-muted fw-normal')],
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
        # 피드백 바 — 매 렌더링마다 새로 만드는 대신 처음부터 고정 배치해 두고
        # 표시 여부/내용만 콜백으로 갱신한다(이 모듈 docstring의 "동적 컴포넌트
        # 팬텀 트리거" 재발 방지 규약과 동일한 이유). 좋아요/나빠요는 클릭
        # 즉시 제출(코멘트 없이)되고, 서술형 의견은 별도 텍스트영역+제출
        # 버튼으로 독립적으로 제출된다 — 사용자가 이 둘을 반드시 함께 낼
        # 필요는 없다고 판단해 단순하게 분리했다.
        html.Div(
            [
                html.Span('이 결과가 도움이 되었나요?', className='small text-muted me-2'),
                dbc.Button(html.I(className='bi bi-hand-thumbs-up'), id='nl-query-feedback-up',
                           size='sm', outline=True, color='success', n_clicks=0, className='me-1'),
                dbc.Button(html.I(className='bi bi-hand-thumbs-down'), id='nl-query-feedback-down',
                           size='sm', outline=True, color='danger', n_clicks=0, className='me-2'),
                dbc.Button(
                    [html.I(className='bi bi-chat-left-text me-1'), '개선 의견 남기기'],
                    id='nl-query-feedback-comment-toggle', size='sm', color='link',
                    className='text-decoration-none p-0', n_clicks=0,
                ),
            ],
            id='nl-query-feedback-bar', style={'display': 'none'}, className='d-flex align-items-center mt-2',
        ),
        dbc.Collapse(
            html.Div([
                dcc.Textarea(
                    id='nl-query-feedback-comment', value='',
                    placeholder='이 질문/결과에 대해 다음부터 이렇게 답해줬으면 하는 개선 방향을 '
                                '자유롭게 적어주세요. 비슷한 질문을 다시 물으면 참고합니다.',
                    style={'width': '100%', 'height': '70px'}, className='mb-2',
                ),
                dbc.Button('제출', id='nl-query-feedback-submit', size='sm', color='primary', n_clicks=0),
                html.Span(id='nl-query-feedback-msg', className='ms-2'),
            ], className='mt-1'),
            id='nl-query-feedback-collapse', is_open=False,
        ),
        dcc.Store(id='nl-query-full-result'),
    ], className='mb-3')


def answer_block(answer: str):
    """AI가 만든 답변(개조식 — 줄마다 "- "로 시작하는 짧은 문구, 왜 이런
    결과가 나왔는지 설명)을 보여주는 알림 박스. "- " 접두사가 붙은 줄이
    하나라도 있으면 실제 불릿 목록(html.Ul)으로 렌더링하고, 프롬프트
    지시를 안 따른 경우(접두사 없음)는 줄바꿈만 보존해 그대로 보여준다
    (LLM 출력 형식이 어긋나도 화면이 깨지지 않도록 하는 안전한 폴백).
    researcher_list.py도 재사용하지 않는다 — 답변 렌더링은 이 모듈의
    _render_nl_query_note 콜백이 전담하고, 명단 쪽은 표 데이터만 가져간다."""
    lines = [ln.strip() for ln in answer.split('\n') if ln.strip()]
    bullet_lines = [ln[1:].strip() for ln in lines if ln.startswith('-')]
    if bullet_lines and len(bullet_lines) == len(lines):
        body = html.Ul([html.Li(ln) for ln in bullet_lines], className='small mb-0 ps-3')
    else:
        body = html.Div(answer, className='small', style={'whiteSpace': 'pre-wrap'})
    return dbc.Alert([
        html.Div([html.I(className='bi bi-robot me-2'), html.Span('AI 답변', className='fw-semibold')],
                 className='mb-1'),
        body,
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

    result = nl_query.answer_question(question, current_only=current_only, period=period)
    # 원본 질문 텍스트를 결과와 함께 담아 둔다 — 피드백 제출 콜백이 "이 결과가
    # 어떤 질문에 대한 것이었는지"를 검색창의 현재 값(그 사이 사용자가 다른
    # 질문으로 바꿔 타이핑했을 수 있음)이 아니라 항상 정확히 참조하기 위함.
    result['_question'] = question
    return result


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


@callback(
    Output('nl-query-feedback-bar', 'style'),
    Output('nl-query-feedback-collapse', 'is_open', allow_duplicate=True),
    Output('nl-query-feedback-comment', 'value', allow_duplicate=True),
    Output('nl-query-feedback-msg', 'children', allow_duplicate=True),
    Input('nl-query-full-result', 'data'),
    prevent_initial_call=True,
)
def _sync_feedback_ui(full_result):
    """새 질문에 대한 결과가 나오거나(full_result 갱신) 초기화(None)될 때마다
    피드백 바를 그 결과에 맞춰 다시 세팅한다 — 이전 질문에 대해 열어 뒀던
    의견 입력창/메시지가 새 결과에도 그대로 남아 헷갈리지 않도록 매번
    리셋한다."""
    if not full_result:
        return {'display': 'none'}, False, '', ''
    return {'display': 'flex'}, False, '', ''


@callback(
    Output('nl-query-feedback-collapse', 'is_open'),
    Output('nl-query-feedback-comment', 'value'),
    Output('nl-query-feedback-msg', 'children'),
    Input('nl-query-feedback-comment-toggle', 'n_clicks'),
    Input('nl-query-feedback-up', 'n_clicks'),
    Input('nl-query-feedback-down', 'n_clicks'),
    Input('nl-query-feedback-submit', 'n_clicks'),
    State('nl-query-feedback-collapse', 'is_open'),
    State('nl-query-feedback-comment', 'value'),
    State('nl-query-full-result', 'data'),
    prevent_initial_call=True,
)
def _handle_feedback(_toggle, _up, _down, _submit, is_open, comment, full_result):
    """좋아요/나빠요는 클릭 즉시(코멘트 없이) 제출하고, 서술형 의견은 별도
    텍스트영역 + 제출 버튼으로 독립적으로 제출한다(components/feedback_modal.py
    와 동일하게 여러 버튼을 한 콜백에서 dash.ctx.triggered_id로 분기)."""
    triggered_id = dash.ctx.triggered_id
    question = (full_result or {}).get('_question', '')

    if triggered_id == 'nl-query-feedback-comment-toggle':
        return not is_open, dash.no_update, dash.no_update

    if triggered_id in ('nl-query-feedback-up', 'nl-query-feedback-down'):
        if not question:
            return dash.no_update, dash.no_update, dash.no_update
        rating = '좋아요' if triggered_id == 'nl-query-feedback-up' else '나빠요'
        nl_query_feedback.submit_feedback(question, full_result or {}, rating=rating)
        msg = dbc.Alert('피드백 감사합니다!', color='success', className='mb-0 py-1 px-2 d-inline-block')
        # 나빠요를 누르면 구체적인 개선 방향을 받을 기회를 놓치지 않도록 의견
        # 입력창을 바로 열어준다(좋아요는 굳이 열 필요 없음).
        open_collapse = True if triggered_id == 'nl-query-feedback-down' else dash.no_update
        return open_collapse, dash.no_update, msg

    if triggered_id == 'nl-query-feedback-submit':
        text = (comment or '').strip()
        if not text:
            return (dash.no_update, dash.no_update,
                    dbc.Alert('의견 내용을 입력해주세요.', color='warning', className='mb-0 py-1 px-2 d-inline-block'))
        if not question:
            return dash.no_update, dash.no_update, dash.no_update
        nl_query_feedback.submit_feedback(question, full_result or {}, comment=text)
        return (False, '',
                dbc.Alert('제출되었습니다. 다음에 비슷한 질문을 물으면 참고합니다!', color='success',
                          className='mb-0 py-1 px-2 d-inline-block'))

    return dash.no_update, dash.no_update, dash.no_update
