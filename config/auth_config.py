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
