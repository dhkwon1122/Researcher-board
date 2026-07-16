"""
SAML 인증 속성 매핑 및 역할 권한 설정.
환경 변수로 재정의 가능.
"""
import os

# ── SAML Claim URI 매핑 (AD FS 기본값) ───────────────────────────────────────
# AD FS에서 전송하는 각 속성의 Claim URI 또는 짧은 속성명
SAML_DISPLAY_NAME_ATTR = os.getenv(
    'SAML_DISPLAY_NAME_ATTR',
    'http://schemas.microsoft.com/ws/2008/06/identity/claims/displayname',
)
SAML_EMAIL_ATTR = os.getenv(
    'SAML_EMAIL_ATTR',
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',
)
# 그룹 멤버십이 담긴 속성 (AD FS에서 Group Claim으로 구성)
SAML_ROLE_ATTRIBUTE = os.getenv(
    'SAML_ROLE_ATTRIBUTE',
    'http://schemas.xmlsoap.org/claims/Group',
)

# ── 앱 역할 → IdP 그룹명 매핑 ─────────────────────────────────────────────────
# AD FS에서 보내는 그룹 claim 값과 일치해야 함
ROLE_ATTRIBUTES: dict[str, str] = {
    'executive_org': os.getenv('SAML_GROUP_EXECUTIVE_ORG', '임원조직담당자'),
    'talent_dev':    os.getenv('SAML_GROUP_TALENT_DEV',    '인재개발담당자'),
}

# 어떤 그룹에도 속하지 않는 경우의 기본 역할 (가장 제한적)
DEFAULT_ROLE = 'talent_dev'

# 세션 유지 시간 (시간 단위)
SESSION_LIFETIME_HOURS = int(os.getenv('SESSION_LIFETIME_HOURS', '8'))

# 역할 표시명
ROLE_LABELS: dict[str, str] = {
    'executive_org': '임원조직 담당자',
    'talent_dev':    '인재개발 담당자',
}

# ── 역할별 권한 매트릭스 ──────────────────────────────────────────────────────
ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
    'executive_org': {
        'view_evaluation': True,   # 평가 등급 열람
        'view_incentive':  True,   # 인센티브 이력 열람
        'view_comments':   True,   # 인물 코멘트 열람 및 작성
        'view_grade':      True,   # 연구원 목록 평가 컬럼 노출
    },
    'talent_dev': {
        'view_evaluation': False,
        'view_incentive':  False,
        'view_comments':   False,
        'view_grade':      False,
    },
}
