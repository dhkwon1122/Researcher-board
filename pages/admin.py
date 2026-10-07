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
from dash import html

from components.admin_ai_search_lab_tab import _ai_search_lab_tab
from components.admin_ai_search_log_tab import _ai_search_log_tab
from components.admin_data_update_tab import _data_update_tab
from components.admin_dev_updates_tab import _dev_updates_tab
from components.admin_exception_job_function_tab import _exception_job_function_tab
from components.admin_team_refer_tab import _team_refer_tab
from components.admin_users_tab import _user_management_tab

dash.register_page(__name__, path='/admin', name='관리자', title='사용자/권한 관리')


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

    return dbc.Container([
        dbc.Tabs([
            dbc.Tab(_user_management_tab(), label='사용자/권한 관리',
                    tab_id='tab-users', label_style={'fontWeight': '600'}),
            dbc.Tab(_team_refer_tab(), label='팀/리더 참조',
                    tab_id='tab-team-refer', label_style={'fontWeight': '600'}),
            dbc.Tab(_exception_job_function_tab(), label='직군 예외자',
                    tab_id='tab-exception-job-function', label_style={'fontWeight': '600'}),
            dbc.Tab(_data_update_tab(), label='데이터 업데이트',
                    tab_id='tab-data-update', label_style={'fontWeight': '600'}),
            dbc.Tab(_ai_search_log_tab(), label='AI 검색 로그',
                    tab_id='tab-ai-search-log', label_style={'fontWeight': '600'}),
            dbc.Tab(_ai_search_lab_tab(), label='AI 검색 테스트',
                    tab_id='tab-ai-search-lab', label_style={'fontWeight': '600'}),
            dbc.Tab(_dev_updates_tab(), label='개발업데이트 이력',
                    tab_id='tab-dev-updates', label_style={'fontWeight': '600'}),
        ], id='admin-tabs', active_tab='tab-users'),
    ], className='py-4')
