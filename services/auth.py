"""
SAML 기반 사용자 인증 및 Flask 세션 관리.
python3-saml 라이브러리를 사용하며, 실제 SAML 처리는 app.py의 ACS 라우트에서 수행.
이 모듈은 SAML assertion 속성 → 앱 역할 매핑과 세션 CRUD를 담당.
"""
from __future__ import annotations

import flask

try:
    from config.auth_config import (
        DEFAULT_ROLE, ROLE_ATTRIBUTES, ROLE_LABELS,
        ROLE_PERMISSIONS, SAML_DISPLAY_NAME_ATTR,
        SAML_EMAIL_ATTR, SAML_ROLE_ATTRIBUTE,
        SESSION_LIFETIME_HOURS,
    )
except ImportError:
    DEFAULT_ROLE = 'talent_dev'
    ROLE_ATTRIBUTES: dict[str, str] = {}
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
    SAML_DISPLAY_NAME_ATTR = ''
    SAML_EMAIL_ATTR = ''
    SAML_ROLE_ATTRIBUTE = ''
    SESSION_LIFETIME_HOURS = 8


def build_user_from_saml(attributes: dict, name_id: str) -> dict:
    """SAML assertion 속성에서 앱 사용자 정보와 역할을 결정.

    Args:
        attributes: auth.get_attributes() 반환값 (키→값 리스트 dict)
        name_id: auth.get_nameid() 반환값 (로그인 식별자)
    """
    def _first(attr_name: str) -> str:
        vals = attributes.get(attr_name, [])
        return vals[0] if vals else ''

    display_name = _first(SAML_DISPLAY_NAME_ATTR) or name_id
    email = _first(SAML_EMAIL_ATTR)

    # 그룹 claim으로 역할 결정
    user_groups: list[str] = attributes.get(SAML_ROLE_ATTRIBUTE, [])
    role = DEFAULT_ROLE
    for app_role, group_value in ROLE_ATTRIBUTES.items():
        if group_value in user_groups:
            role = app_role
            break

    return {
        'user_id': name_id,
        'display_name': display_name,
        'email': email,
        'role': role,
    }


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
