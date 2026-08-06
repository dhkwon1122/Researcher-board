"""
좌측 상단 "기능 관련 수정/추가/보완/기타 의견 제출하기" 버튼 + 제출 모달.

app.py가 dash.Dash 인스턴스 생성 이후 명시적으로 import해야 이 모듈의
module-level @callback이 등록된다(components/nl_query_bar.py와 동일한 이유
— 생성 전에 import하면 아직 앱이 없어 콜백이 등록되지 않는다).
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, html

from services import feedback

_CATEGORY_OPTIONS = [{'label': c, 'value': c} for c in feedback.CATEGORIES]


def render() -> html.Div:
    return html.Div([
        # 기본 color='primary'는 assets/custom.css의 .btn-primary { ... !important }
        # 때문에 인라인 style로 배경색을 덮어써도 반영되지 않는다 — 그 규칙이 없는
        # 'warning'(밝은 노랑/주황 계열, Bootstrap 기본 배지 색)을 대신 사용해
        # !important와 부딪히지 않으면서도 눈에 잘 띄게 한다.
        dbc.Button(
            '기능 관련 수정/추가/보완/기타 의견 제출하기',
            id='feedback-open-btn', n_clicks=0, size='sm', className='ms-3',
            color='warning',
            style={'color': '#1d1d1f', 'fontWeight': 600},
        ),
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle('기능 관련 의견 제출하기')),
            dbc.ModalBody([
                dbc.Label('구분', className='fw-semibold small'),
                dbc.RadioItems(
                    id='feedback-category', options=_CATEGORY_OPTIONS,
                    value='기타', inline=True, className='mb-3',
                ),
                dbc.Label('내용', className='fw-semibold small'),
                dbc.Textarea(
                    id='feedback-message', rows=5,
                    placeholder='수정/추가/보완이 필요한 부분이나 그 밖의 의견을 자유롭게 작성해주세요.',
                    className='mb-3',
                ),
                dbc.Label('작성자 (선택)', className='fw-semibold small'),
                dbc.Input(id='feedback-author', placeholder='이름을 남기고 싶으면 입력하세요.'),
                html.Div(id='feedback-status', className='mt-2'),
            ]),
            dbc.ModalFooter([
                dbc.Button('취소', id='feedback-cancel-btn', color='secondary', outline=True, n_clicks=0),
                dbc.Button('제출', id='feedback-submit-btn', color='primary', n_clicks=0),
            ]),
        ], id='feedback-modal', is_open=False),
    ], style={'display': 'inline-block'})


@callback(
    Output('feedback-modal', 'is_open'),
    Output('feedback-category', 'value'),
    Output('feedback-message', 'value'),
    Output('feedback-author', 'value'),
    Output('feedback-status', 'children'),
    Input('feedback-open-btn', 'n_clicks'),
    Input('feedback-cancel-btn', 'n_clicks'),
    Input('feedback-submit-btn', 'n_clicks'),
    State('feedback-category', 'value'),
    State('feedback-message', 'value'),
    State('feedback-author', 'value'),
    prevent_initial_call=True,
)
def _handle_feedback_modal(_open_clicks, _cancel_clicks, _submit_clicks, category, message, author):
    triggered_id = dash.ctx.triggered_id

    if triggered_id == 'feedback-open-btn':
        return True, '기타', '', '', ''

    if triggered_id == 'feedback-cancel-btn':
        return False, dash.no_update, dash.no_update, dash.no_update, ''

    if triggered_id == 'feedback-submit-btn':
        if not (message or '').strip():
            return (True, dash.no_update, dash.no_update, dash.no_update,
                    dbc.Alert('내용을 입력해주세요.', color='warning', className='mb-0 py-1 px-2'))
        try:
            feedback.submit_feedback(category, message, author)
        except Exception as exc:  # noqa: BLE001 — 파일 쓰기 실패 등 예상 못한 오류도 화면에 안내
            return (True, dash.no_update, dash.no_update, dash.no_update,
                    dbc.Alert(f'제출 중 오류가 발생했습니다: {exc}', color='danger', className='mb-0 py-1 px-2'))
        return (True, '기타', '', '',
                dbc.Alert('제출되었습니다. 소중한 의견 감사합니다!', color='success', className='mb-0 py-1 px-2'))

    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
