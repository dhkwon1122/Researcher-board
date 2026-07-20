"""
역할 권한 설정. 환경 변수로 재정의 가능.
"""
import os

DEFAULT_ROLE = 'talent_dev'

SESSION_LIFETIME_HOURS = int(os.getenv('SESSION_LIFETIME_HOURS', '8'))

ROLE_LABELS: dict[str, str] = {
    'executive_org': '임원조직 담당자',
    'talent_dev':    '인재개발 담당자',
}

ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    'executive_org': {
        'view_evaluation': True,
        'view_incentive':  True,
        'view_comments':   True,
        'view_grade':      True,
        'manage_users':    True,   # 사용자 관리 페이지 접근
    },
    'talent_dev': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
        'manage_users':    False,
    },
}
