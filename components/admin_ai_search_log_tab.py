"""
관리자 페이지 "AI 검색 로그" 탭 — pages/admin.py 분할 리팩터링(2026-09-28)
으로 신설. 읽기 전용(콜백 없음) — services/nl_query_log.py, services/
nl_query_feedback.py 기록을 최근 200건까지 보여준다.
"""
import dash_bootstrap_components as dbc
from dash import html

_AI_SEARCH_LOG_COLUMNS = [
    ('시각', '시각'), ('사용자', '사용자'), ('질문', '질문'), ('intent', 'intent'),
    ('성공여부', '성공여부'), ('건수', '건수'), ('검색기준', '검색기준'), ('기간', '기간'), ('비고', '비고'),
]

_AI_SEARCH_LOG_BADGE_COLOR = {'성공': 'success', '결과없음': 'secondary', '실패': 'danger'}


def _ai_search_log_row(row: dict) -> html.Tr:
    status = row.get('성공여부', '')
    return html.Tr([
        html.Td(row.get('시각', ''), style={'whiteSpace': 'nowrap'}),
        html.Td(row.get('사용자', '') or '-'),
        html.Td(row.get('질문', '')),
        html.Td(row.get('intent', '')),
        html.Td(dbc.Badge(status, color=_AI_SEARCH_LOG_BADGE_COLOR.get(status, 'light'),
                           className='text-uppercase')),
        html.Td(row.get('건수', ''), className='text-center'),
        html.Td(row.get('검색기준', '')),
        html.Td(row.get('기간', '') or '-'),
        html.Td(row.get('비고', '') or '-', style={'maxWidth': '320px', 'whiteSpace': 'normal'}),
    ])


_AI_SEARCH_FEEDBACK_COLUMNS = ['시각', '사용자', '질문', 'intent', 'rating', '의견']
_AI_SEARCH_FEEDBACK_BADGE_COLOR = {'좋아요': 'success', '나빠요': 'danger'}


def _ai_search_feedback_row(row: dict) -> html.Tr:
    rating = row.get('rating', '')
    rating_cell = (
        dbc.Badge(rating, color=_AI_SEARCH_FEEDBACK_BADGE_COLOR.get(rating, 'light'))
        if rating else '-'
    )
    return html.Tr([
        html.Td(row.get('시각', ''), style={'whiteSpace': 'nowrap'}),
        html.Td(row.get('사용자', '') or '-'),
        html.Td(row.get('질문', '')),
        html.Td(row.get('intent', '')),
        html.Td(rating_cell),
        html.Td(row.get('의견', '') or '-', style={'maxWidth': '360px', 'whiteSpace': 'normal'}),
    ])


def _ai_search_feedback_section() -> html.Div:
    """연구원 명단 화면의 AI 검색 결과에 남긴 좋아요/나빠요·서술형 의견
    (services/nl_query_feedback.py)을 최근 200건까지 보여준다. 의견이 있는
    피드백은 다음부터 비슷한 질문의 프롬프트에 자동으로 힌트로 들어가므로
    (services.nl_query_feedback.feedback_hint_for), 이 표가 곧 "지금 AI
    검색에 실제로 영향을 주고 있는 피드백 목록"이기도 하다."""
    from services import nl_query_feedback
    rows = nl_query_feedback.read_recent(200)
    if not rows:
        return dbc.Alert('아직 남겨진 피드백이 없습니다.', color='light', className='small border')
    return dbc.Table(
        [
            html.Thead(html.Tr([html.Th(c) for c in _AI_SEARCH_FEEDBACK_COLUMNS])),
            html.Tbody([_ai_search_feedback_row(r) for r in rows]),
        ],
        bordered=True, hover=True, responsive=True, size='sm', className='mb-0 admin-table',
    )


def _ai_search_log_tab() -> html.Div:
    """"연구원 명단(AI검색)" 탭의 자연어 질문마다 services/nl_query_log.py가
    남긴 기록(질문/intent/성공여부/건수)과, 그 결과에 사용자가 남긴 좋아요/
    나빠요·서술형 의견(services/nl_query_feedback.py)을 각각 최근 200건까지
    최신순으로 보여준다. 쿼리 로그가 어떤 질문이 실패/빈 결과로 끝나는지,
    피드백이 어떤 개선 방향을 남겼는지 드러내야 프롬프트·데이터 커버리지를
    실제로 개선할 근거가 생긴다(AI 검색 강화 검토에서 지적된 공백). 웹
    CRUD가 아니라 읽기 전용 — 로그/피드백 자체는 화면에서 지우거나 고칠
    필요가 없어 다른 관리 탭과 달리 저장/삭제 콜백이 없다."""
    from services import nl_query_log
    rows = nl_query_log.read_recent(200)
    if not rows:
        log_body = dbc.Alert('아직 기록된 AI 검색 질문이 없습니다.', color='light', className='small border')
    else:
        log_body = dbc.Table(
            [
                html.Thead(html.Tr([html.Th(label) for _key, label in _AI_SEARCH_LOG_COLUMNS])),
                html.Tbody([_ai_search_log_row(r) for r in rows]),
            ],
            bordered=True, hover=True, responsive=True, size='sm', className='mb-0 admin-table',
        )
    return html.Div([
        dbc.Alert(
            [html.I(className='bi bi-info-circle me-2'),
             f'최근 {len(rows)}건(최대 200건)을 최신순으로 보여줍니다. 질문 원문과 intent/성공여부/'
             '건수만 기록하고 검색 결과 자체(연구원 이름 등)는 저장하지 않습니다.'],
            color='light', className='small border mb-3',
        ),
        log_body,
        html.H6('사용자 피드백', className='fw-bold mt-4 mb-2'),
        dbc.Alert(
            [html.I(className='bi bi-info-circle me-2'),
             '의견(서술형)이 있는 피드백은 다음부터 비슷한 질문에 자동으로 참고됩니다. '
             '좋아요/나빠요만 남긴 피드백은 통계용으로만 쓰입니다.'],
            color='light', className='small border mb-3',
        ),
        _ai_search_feedback_section(),
    ], className='pt-3')
