"""
역할 권한 설정. 환경 변수로 재정의 가능.
"""
import os

DEFAULT_ROLE = 'talent_dev'

SESSION_LIFETIME_HOURS = int(os.getenv('SESSION_LIFETIME_HOURS', '8'))

# 아래 12개 역할 중 일부는 아직 실사용 여부가 확정되지 않은 초안이다 — 실제
# 조직/업무에 맞게 검토 후 조정할 것.
#
# manage_users(사용자 관리 페이지 접근)는 역할로 부여하지 않는다 — 어떤 역할의
# ROLE_PERMISSIONS에도 manage_users: True를 두지 않고, 대신 계정별
# is_admin 플래그(services/user_store.py, app_users.is_admin)로 개인에게
# 개별 부여한다(services.auth.can() 참고). 이렇게 해야 "이 역할이면 전원
# 자동 관리자"가 되는 걸 피하고, 같은 역할이라도 필요한 사람에게만 관리자
# 권한을 줄 수 있다.
ROLE_LABELS: dict[str, str] = {
    'team_lead':         'People팀장',
    'talent_exp':        'Talent Experience 그룹장',
    'talent_mng':        'Talent Management 그룹장',
    'talent_dev':        '인재개발 담당자',
    'workforce_mng':     '인력운영 담당자',
    'employee_relation': '노사관계 담당자',
    'executive_org':     '임원조직 담당자',
    'workplace_sol':     '총무 담당자',
    'hr_planning':       'HR기획 담당자',
    'hr_policy':         'HR제도 담당자',
    'recruit':           '채용 담당자',
    'org_culture':       '조직문화 담당자',
}

ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    'team_lead': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   True,
        'view_grade':      True,
    },
    'talent_exp': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
    },
    'talent_mng': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   True,
        'view_grade':      True,
    },
    'talent_dev': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
    },
    'workforce_mng': {
        'view_evaluation': True,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      True,
    },
    'employee_relation': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   True,
        'view_grade':      False,
    },
    'executive_org': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   True,
        'view_grade':      True,
    },
    'workplace_sol': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
    },
    'hr_planning': {
        'view_evaluation': False,
        'view_incentive':  True,
        'view_comments':   False,
        'view_grade':      True,
    },
    'hr_policy': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   True,
        'view_grade':      True,
    },
    'recruit': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
    },
    'org_culture': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
    },
}

# services/open_data_query.py(개방형 자연어 질의)와
# services/nl_query.py(find_researchers_by_criteria의 평가등급 조건)가 공유하는
# "테이블(원천 CSV/DB 테이블명) → 필요 권한" 매핑. 화면 UI(pages/*.py)는 이미
# ROLE_PERMISSIONS로 평가등급/인센티브/코멘트/리더십·승계 데이터를 역할별로
# 가려서 보여주는데, AI 자연어 검색은 그 데이터가 담긴 원천 테이블을 그대로
# SQL/필터로 조회할 수 있어 같은 제약이 없으면 권한 우회 통로가 된다 — 여기
# 매핑에 있는 테이블은 해당 권한이 없는 사용자에게는 아예 조회 대상에서
# 제외한다(services.auth.filter_permitted_tables 참고).
# view_grade는 화면 UI 어디에서도 아직 실사용되지 않는 미확정 권한이라(위 주석
# 참고), 여기서는 조직 내부에서 평가등급과 비슷하게 민감한 인사 판단 정보로
# 취급되는 리더십 진단/승계 후보 데이터에 잠정 매핑해 둔다 — 실제 운영 기준과
# 다르면 조정할 것.
# 자연어 검색에서 조회할 수 있는 테이블의 명시적 화이트리스트다. 값이 None이면
# 로그인한 모든 사용자에게 허용하고, 권한 문자열이면 해당 권한이 필요하다.
# 여기에 없는 새 CSV/DB 테이블은 자동 발견되더라도 기본 거부된다.
TABLE_PERMISSIONS: dict[str, str | None] = {
    'researchers':           None,
    'education':             None,
    'transfers':             None,
    'tasks':                 None,
    'tasks_information':     None,
    'nurturing':             None,
    'awards':                None,
    'publications':          None,
    'patents':               None,
    'technology_transfer':   None,
    'hr_orders':             None,
    'core_technology':       None,
    'tech_ownership':        None,
    'job_profile':           None,
    'team_refer':            None,
    'project_confl_address': None,
    'expertise_profiles':    None,
    'researcher_similarity': None,
    'evaluations':         'view_evaluation',
    'incentive_selection': 'view_incentive',
    'comments':            'view_comments',
    'leadership':          'view_grade',
    'succession':          'view_grade',
}
