"""
관리자 페이지: 사용자 계정 관리 (추가 / 수정 / 삭제)
manage_users 권한이 있는 계정만 접근 가능.

2026-09-28: 6개 탭(사용자/권한 관리, 팀/리더 참조, 직군 예외자, 데이터
업데이트, AI 검색 로그, 개발업데이트 이력)의 구현을 components/admin_*_tab.py
로 분리하고, 이 파일은 각 탭을 조합하는 얇은 오케스트레이터로 남겼다(순수
분할 리팩터링 — 기능 변경 없음).

이 파일 자체를 여기서 top-level import하는 것이 안전한 이유: pages/admin.py는
Dash가 dash.Dash(use_pages=True) 생성자 안에서 pages/ 폴더를 훑으며(파일
내용에 "register_page" 문자열이 있는지만 검사) 그 시점에 한 번 import한다 —
app.py가 components/feedback_modal.py 등을 app = dash.Dash(...) 실행 "이후"에
따로 import하는 것과 달리(그때는 아직 앱이 없어 @callback이 등록되지 않으므로),
pages/admin.py의 이 import들은 이미 dash.Dash(...) 생성자 호출 "안에서" 실행되는
것이 보장되므로 @callback/clientside_callback 등록에 문제가 없다. 각 탭
서브모듈은 pages/가 아니라 components/에 둔다 — pages/ 밑에 두면 Dash
페이지워커가 그 파일도 독립된 페이지로 다시 import하려 시도한다(파일명이
"_"로 시작하지 않는 한).
"""
import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, html, no_update

from components.admin_ai_search_log_tab import _ai_search_log_tab
from components.admin_data_update_tab import _data_update_tab
from components.admin_dev_updates_tab import _dev_updates_tab
from components.admin_exception_job_function_tab import _exception_job_function_tab
from components.admin_team_refer_tab import _team_refer_tab
from components.admin_users_tab import _user_management_tab

dash.register_page(__name__, path='/admin', name='관리자', title='사용자/권한 관리')

# (tab_id, 라벨, 콘텐츠를 담을 placeholder div id, 콘텐츠 빌더) — layout()과
# 아래 지연 렌더링 콜백이 함께 쓴다.
_TABS = [
    ('tab-users', '사용자/권한 관리', 'admin-tab-content-users', _user_management_tab),
    ('tab-team-refer', '팀/리더 참조', 'admin-tab-content-team-refer', _team_refer_tab),
    ('tab-exception-job-function', '직군 예외자',
     'admin-tab-content-exception-job-function', _exception_job_function_tab),
    ('tab-data-update', '데이터 업데이트', 'admin-tab-content-data-update', _data_update_tab),
    ('tab-ai-search-log', 'AI 검색 로그', 'admin-tab-content-ai-search-log', _ai_search_log_tab),
    ('tab-dev-updates', '개발업데이트 이력', 'admin-tab-content-dev-updates', _dev_updates_tab),
]


def _access_denied():
    return dbc.Container(
        dbc.Alert(
            [html.I(className='bi bi-shield-lock me-2'), '접근 권한이 없습니다.'],
            color='danger', className='mt-4',
        ),
        className='py-4',
    )


def layout():
    from services.auth import can
    if not can('manage_users'):
        return _access_denied()

    # 2026-10-10 수정: 예전엔 6개 탭의 콘텐츠를 여기서 전부 즉시 계산해(탭
    # 전환은 dbc.Tabs가 클라이언트에서 보이기/숨기기만 할 뿐, 콘텐츠 자체는
    # 이미 서버에서 다 만들어져 있었음) 실제로 보려는 탭이 하나뿐이어도
    # 나머지 5개 탭까지 매번 렌더링하는 비용을 치렀다 — "사용자/권한 관리"
    # 탭은 다른 시스템과 공유하는 DB 테이블(app_users)을 읽으므로, 그쪽이
    # 느려지면(다른 시스템의 트랜잭션과 겹치는 등) admin 페이지 전체가
    # 덩달아 느려지는 문제가 있었다(사용자 보고). 각 탭을 빈 placeholder로만
    # 먼저 그리고, 실제 콘텐츠는 아래 _render_active_admin_tab() 콜백이
    # "그 탭이 처음 열릴 때"만 채운다.
    return dbc.Container([
        dbc.Tabs([
            dbc.Tab(html.Div(id=div_id), label=label, tab_id=tab_id,
                    label_style={'fontWeight': '600'})
            for tab_id, label, div_id, _builder in _TABS
        ], id='admin-tabs', active_tab='tab-users'),
    ], className='py-4')


@callback(
    [Output(div_id, 'children') for _, _, div_id, _ in _TABS],
    Input('admin-tabs', 'active_tab'),
    [State(div_id, 'children') for _, _, div_id, _ in _TABS],
)
def _render_active_admin_tab(active_tab, *current_children):
    """탭을 처음 열 때만 그 탭의 콘텐츠를 계산해 채운다 — 이미 채워진 탭은
    (State로 확인) 다시 계산하지 않으므로, 탭을 왔다갔다 해도 그 안의
    미저장 편집 내용(예: 팀/리더 참조 그리드)이 사라지지 않는다. 초기
    로드 시에도 한 번 실행되어(기본 prevent_initial_call=False) 처음
    활성 탭('tab-users')이 자동으로 채워진다."""
    outputs = []
    for i, (tab_id, _label, _div_id, builder) in enumerate(_TABS):
        if tab_id == active_tab and not current_children[i]:
            outputs.append(builder())
        else:
            outputs.append(no_update)
    return outputs
