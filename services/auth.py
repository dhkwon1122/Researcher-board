"""
AD LDAP 인증 및 Flask 세션 기반 권한 관리.
"""
from __future__ import annotations

import flask

try:
    import ldap3
    import ldap3.utils.conv as _ldap_conv
    _LDAP_AVAILABLE = True
except ImportError:
    _LDAP_AVAILABLE = False

try:
    from config.auth_config import (
        AD_BASE_DN, AD_DOMAIN, AD_PORT, AD_SERVER, AD_USE_SSL,
        DEFAULT_ROLE, ROLE_GROUP_MAPPING, ROLE_LABELS,
        ROLE_PERMISSIONS, SESSION_LIFETIME_HOURS,
    )
except ImportError:
    AD_SERVER = 'ldap://localhost'
    AD_PORT = 389
    AD_USE_SSL = False
    AD_BASE_DN = 'DC=company,DC=com'
    AD_DOMAIN = 'COMPANY'
    ROLE_GROUP_MAPPING: dict[str, str] = {}
    DEFAULT_ROLE = 'talent_dev'
    ROLE_LABELS: dict[str, str] = {
        'executive_org': '임원조직 담당자',
        'talent_dev': '인재개발 담당자',
    }
    ROLE_PERMISSIONS: dict[str, dict[str, bool]] = {
        'executive_org': {
            'view_evaluation': True, 'view_incentive': True,
            'view_comments': True, 'view_grade': True,
        },
        'talent_dev': {
            'view_evaluation': False, 'view_incentive': False,
            'view_comments': False, 'view_grade': False,
        },
    }
    SESSION_LIFETIME_HOURS = 8


def authenticate(username: str, password: str) -> dict | None:
    """AD LDAP 인증. 성공 시 사용자 dict 반환, 실패 시 None."""
    if not username or not password:
        return None

    if not _LDAP_AVAILABLE:
        return None

    try:
        server = ldap3.Server(
            AD_SERVER,
            port=AD_PORT,
            use_ssl=AD_USE_SSL,
            connect_timeout=5,
        )
        conn = ldap3.Connection(
            server,
            user=f'{AD_DOMAIN}\\{username}',
            password=password,
            authentication=ldap3.NTLM,
            auto_bind=False,
        )
        if not conn.bind():
            return None

        safe_username = _ldap_conv.escape_filter_chars(username)
        conn.search(
            search_base=AD_BASE_DN,
            search_filter=f'(sAMAccountName={safe_username})',
            attributes=['displayName', 'memberOf', 'mail'],
        )

        if not conn.entries:
            conn.unbind()
            return None

        entry = conn.entries[0]
        display_name = (
            str(entry.displayName)
            if hasattr(entry, 'displayName') and entry.displayName
            else username
        )
        email = (
            str(entry.mail)
            if hasattr(entry, 'mail') and entry.mail
            else ''
        )
        member_of = list(entry.memberOf) if hasattr(entry, 'memberOf') else []
        conn.unbind()

        return {
            'user_id': username,
            'display_name': display_name,
            'email': email,
            'role': _resolve_role(member_of),
        }
    except Exception:
        return None


def _resolve_role(member_of: list[str]) -> str:
    lower = [dn.lower() for dn in member_of]
    for role, group_dn in ROLE_GROUP_MAPPING.items():
        if group_dn.lower() in lower:
            return role
    return DEFAULT_ROLE


def get_current_user() -> dict | None:
    """Flask 세션에서 현재 사용자 정보를 반환. 비로그인 시 None."""
    if 'user_id' not in flask.session:
        return None
    return {
        'user_id': flask.session['user_id'],
        'display_name': flask.session.get('display_name', ''),
        'role': flask.session.get('role', DEFAULT_ROLE),
        'email': flask.session.get('email', ''),
    }


def can(permission: str) -> bool:
    """현재 사용자가 해당 권한을 가지는지 확인."""
    user = get_current_user()
    if user is None:
        return False
    role = user.get('role', DEFAULT_ROLE)
    return ROLE_PERMISSIONS.get(role, {}).get(permission, False)


def set_session(user: dict) -> None:
    from datetime import timedelta
    flask.session.permanent = True
    flask.session['user_id'] = user['user_id']
    flask.session['display_name'] = user['display_name']
    flask.session['role'] = user['role']
    flask.session['email'] = user.get('email', '')
    flask.current_app.permanent_session_lifetime = timedelta(hours=SESSION_LIFETIME_HOURS)


def clear_session() -> None:
    flask.session.clear()


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)
