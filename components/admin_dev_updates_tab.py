"""
관리자 페이지 "개발업데이트 이력" 탭 — pages/admin.py 분할 리팩터링
(2026-09-28)으로 신설. 읽기 전용(콜백 없음) — services/dev_updates.py의
주 단위 이력을 보여준다.
"""
import dash_bootstrap_components as dbc
from dash import html


def _dev_update_week_card(week: dict) -> dbc.Card:
    body = [html.Div(week['range_label'], className='fw-bold mb-2', style={'fontSize': '0.95rem'})]
    if week.get('major'):
        body.append(html.Div('주요 업데이트', className='text-uppercase text-muted fw-semibold',
                              style={'fontSize': '0.68rem', 'letterSpacing': '0.04em'}))
        body.append(html.Ul([html.Li(m, className='mb-1') for m in week['major']],
                             className='mb-2', style={'fontSize': '0.88rem'}))
    if week.get('detail'):
        body.append(html.Div('세부사항', className='text-uppercase text-muted fw-semibold',
                              style={'fontSize': '0.68rem', 'letterSpacing': '0.04em'}))
        body.append(html.Ul([html.Li(d, className='mb-1') for d in week['detail']],
                             className='mb-0 text-muted', style={'fontSize': '0.82rem'}))
    return dbc.Card(dbc.CardBody(body), className='shadow-sm mb-3')


def _dev_updates_tab() -> html.Div:
    """이 앱 자체의 기능 변경 이력을 주 단위 개조식으로 보여주는 탭 — 콘텐츠는
    services/dev_updates.py에서 관리한다(웹 CRUD 아님, 코드로 유지 — 매주
    금요일 기능 업데이트가 있으면 Claude가 이 파일에 추가할 내용을 제안하도록
    예약돼 있다. 사용자 확정)."""
    from services import dev_updates
    return html.Div([
        dbc.Alert(
            [html.I(className='bi bi-info-circle me-2'),
             '이 화면에 보이는 기능 개발 이력입니다(원천 데이터/DB 갱신은 포함하지 않습니다). '
             '최신 주가 맨 위에 옵니다.'],
            color='light', className='small border mb-3',
        ),
        html.Div([_dev_update_week_card(w) for w in dev_updates.WEEKS]),
    ], className='pt-3')
