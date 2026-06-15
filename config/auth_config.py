"""
AD 인증 및 역할 권한 설정.
환경 변수로 재정의 가능 (AD_SERVER, AD_PORT, AD_BASE_DN, AD_DOMAIN, 등).
"""
import os

# ── AD LDAP 서버 ───────────────────────────────────────────────────────────────
AD_SERVER = os.getenv('AD_SERVER', 'ldap://your-ad-server.company.com')
AD_PORT = int(os.getenv('AD_PORT', '389'))
AD_USE_SSL = os.getenv('AD_USE_SSL', 'false').lower() == 'true'
AD_BASE_DN = os.getenv('AD_BASE_DN', 'DC=company,DC=com')
AD_DOMAIN = os.getenv('AD_DOMAIN', 'COMPANY')  # NTLM 도메인명

# 세션 유지 시간 (시간 단위)
SESSION_LIFETIME_HOURS = int(os.getenv('SESSION_LIFETIME_HOURS', '8'))

# ── AD 그룹 → 앱 역할 매핑 ────────────────────────────────────────────────────
# 실제 AD 그룹 DN 으로 변경해야 함
ROLE_GROUP_MAPPING = {
    'executive_org': os.getenv(
        'AD_GROUP_EXECUTIVE_ORG',
        'CN=임원조직담당자,OU=Groups,DC=company,DC=com',
    ),
    'talent_dev': os.getenv(
        'AD_GROUP_TALENT_DEV',
        'CN=인재개발담당자,OU=Groups,DC=company,DC=com',
    ),
}

# 어떤 그룹에도 속하지 않은 경우 기본 역할 (가장 제한적)
DEFAULT_ROLE = 'talent_dev'

# 역할 표시명
ROLE_LABELS = {
    'executive_org': '임원조직 담당자',
    'talent_dev': '인재개발 담당자',
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
