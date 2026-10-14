"""
관리자 페이지 "AI 검색 로그" 탭 — pages/admin.py 분할 리팩터링(2026-09-28)
으로 신설. 읽기 전용(콜백 없음) — services/nl_query_log.py 기록을 최근 200건까지
보여준다(사용자 피드백 표는 2026-10-14 피드백 기능 삭제로 제거).
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


def _ai_search_log_tab() -> html.Div:
    """"연구원 명단(AI검색)" 탭의 자연어 질문마다 services/nl_query_log.py가
    남긴 기록(질문/intent/성공여부/건수)을 최근 200건까지 최신순으로 보여준다.
    어떤 질문이 실패/빈 결과로 끝나는지 드러내야 프롬프트·데이터 커버리지를
    개선할 근거가 생긴다. 읽기 전용 — 저장/삭제 콜백이 없다."""
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
    ], className='pt-3')
