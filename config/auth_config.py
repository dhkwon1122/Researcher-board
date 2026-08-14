"""
역할 권한 설정. 환경 변수로 재정의 가능.
"""
import os

DEFAULT_ROLE = 'talent_dev'

SESSION_LIFETIME_HOURS = int(os.getenv('SESSION_LIFETIME_HOURS', '8'))

# 아래 12개 역할 중 상당수는 아직 실사용 여부가 확정되지 않은 초안이다 —
# 라벨/권한 값은 역할명에서 통상적인 의미를 추측해 작성한 것이므로, 실제
# 조직/업무에 맞게 검토 후 조정할 것.
ROLE_LABELS: dict[str, str] = {
    'team_lead':         '팀장',
    'talent_exp':        '인재경험 담당자',
    'talent_mng':        '인재관리 담당자',
    'talent_dev':        '인재개발 담당자',
    'workforce_mng':     '인력운영 담당자',
    'employee_relation': '노사관계 담당자',
    'executive_org':     '임원조직 담당자',
    'workplace_sol':     '근무환경솔루션 담당자',
    'hr_planning':       'HR기획 담당자',
    'hr_policy':         'HR제도 담당자',
    'recruit':           '채용 담당자',
    'org_culture':       '조직문화 담당자',
}

ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    'team_lead': {
        'view_evaluation': True,
        'view_incentive':  False,
        'view_comments':   True,
        'view_grade':      True,
        'manage_users':    False,
    },
    'talent_exp': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
        'manage_users':    False,
    },
    'talent_mng': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   True,
        'view_grade':      True,
        'manage_users':    False,
    },
    'talent_dev': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
        'manage_users':    False,
    },
    'workforce_mng': {
        'view_evaluation': True,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      True,
        'manage_users':    False,
    },
    'employee_relation': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   True,
        'view_grade':      False,
        'manage_users':    False,
    },
    'executive_org': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   True,
        'view_grade':      True,
        'manage_users':    True,   # 사용자 관리 페이지 접근
    },
    'workplace_sol': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
        'manage_users':    False,
    },
    'hr_planning': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   False,
        'view_grade':      True,
        'manage_users':    False,
    },
    'hr_policy': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
        'manage_users':    False,
    },
    'recruit': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
        'manage_users':    False,
    },
    'org_culture': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
        'manage_users':    False,
    },
}
