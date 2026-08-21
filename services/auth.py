"""
자체 아이디/비밀번호 인증 및 Flask 세션 관리.

DATABASE_URL이 설정돼 있으면 인증은 PostgreSQL 저장소만 사용한다. DB 접근이
실패해도 JSON 계정으로 폴백하지 않는다. DATABASE_URL이 없는 명시적 로컬
개발 환경에서만 config/users.json을 사용한다.
"""
from __future__ import annotations

import json
import os
from datetime import timedelta

import flask
from werkzeug.security import check_password_hash, generate_password_hash

from config.settings import load_settings
from services import user_store
from services.user_repositories import DbUserRepository, JsonUserRepository, USERS_FILE, UserRepository

try:
    from config.auth_config import (
        DEFAULT_ROLE, ROLE_LABELS, ROLE_PERMISSIONS, SESSION_LIFETIME_HOURS, TABLE_PERMISSIONS,
    )
except ImportError:
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
    TABLE_PERMISSIONS: dict[str, str | None] = {}


def _load_users_json() -> dict:
    """Compatibility helper for tests and older admin scripts."""
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, encoding='utf-8') as f:
        return json.load(f)


def _database_configured() -> bool:
    return load_settings().database.configured


def _repository() -> UserRepository:
    return DbUserRepository() if _database_configured() else JsonUserRepository()


def _user_view(data: dict, user_id: str | None = None) -> dict:
    uid = user_id or data.get('user_id', '')
    return {
        'user_id': uid,
        'display_name': data.get('display_name', uid),
        'email': data.get('email', ''),
        'role': data.get('role', DEFAULT_ROLE),
        'must_change_password': bool(data.get('must_change_password')),
        'is_admin': bool(data.get('is_admin')),
    }


def password_validation_error(password: str) -> str | None:
    password = password or ''
    min_length = load_settings().security.min_password_length
    if len(password) < min_length:
        return f'비밀번호는 {min_length}자 이상이어야 합니다.'
    classes = sum((
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ))
    if classes < 3:
        return '비밀번호는 영문 대문자·소문자·숫자·특수문자 중 3종류 이상을 포함해야 합니다.'
    return None


def authenticate(username: str, password: str) -> dict | None:
    if not username or not password:
        return None

    repo = _repository()
    if not repo.available():
        return None
    data = repo.get_user(username)
    if data is None or not check_password_hash(data['password_hash'], password):
        return None
    return _user_view(data, username)


def has_any_user() -> bool:
    repo = _repository()
    return repo.has_any() if repo.available() else False


def list_users() -> list[dict]:
    repo = _repository()
    if not repo.available():
        return []
    return [_user_view(data) for data in repo.list_users()]


def create_user(user_id: str, password: str, display_name: str,
                role: str, email: str = '', must_change_password: bool = False,
                is_admin: bool = False) -> None:
    repo = _repository()
    if not repo.available():
        raise RuntimeError('사용자 DB에 연결할 수 없습니다.' if _database_configured() else '사용자 저장소를 사용할 수 없습니다.')
    if repo.get_user(user_id) is not None:
        raise ValueError(f'이미 존재하는 계정입니다: {user_id}')
    ok = repo.create(
        user_id,
        generate_password_hash(password),
        display_name,
        role,
        email,
        must_change_password=must_change_password,
        is_admin=is_admin,
    )
    if not ok:
        raise RuntimeError('사용자 저장소에 계정을 저장하지 못했습니다.')


def update_user(user_id: str, display_name: str | None = None,
                role: str | None = None, email: str | None = None,
                is_admin: bool | None = None) -> bool:
    repo = _repository()
    if not repo.available():
        return False
    return repo.update_fields(user_id, display_name, role, email, is_admin)


def change_password(user_id: str, new_password: str) -> bool:
    repo = _repository()
    if not repo.available():
        return False
    return repo.set_password_hash(user_id, generate_password_hash(new_password))


def delete_user(user_id: str) -> bool:
    repo = _repository()
    if not repo.available():
        return False
    return repo.delete_user(user_id)


def get_current_user() -> dict | None:
    if 'user_id' not in flask.session:
        return None
    return {
        'user_id': flask.session['user_id'],
        'display_name': flask.session.get('display_name', ''),
        'role': flask.session.get('role', DEFAULT_ROLE),
        'email': flask.session.get('email', ''),
        'must_change_password': bool(flask.session.get('must_change_password')),
        'is_admin': bool(flask.session.get('is_admin')),
    }


def current_user_mail_default() -> str:
    user = get_current_user()
    if not user:
        return ''
    return f"{user['user_id']}@samsung.com"


def can(permission: str) -> bool:
    user = get_current_user()
    if user is None:
        return False
    if permission == 'manage_users':
        return user.get('is_admin', False)
    role = user.get('role', DEFAULT_ROLE)
    return ROLE_PERMISSIONS.get(role, {}).get(permission, False)


def can_table(table_name: str) -> bool:
    if get_current_user() is None or table_name not in TABLE_PERMISSIONS:
        return False
    permission = TABLE_PERMISSIONS.get(table_name)
    return True if permission is None else can(permission)


def filter_permitted_tables(tables: dict) -> dict:
    return {name: df for name, df in tables.items() if can_table(name)}


def set_session(user: dict) -> None:
    flask.session.clear()
    flask.session.permanent = True
    flask.session['user_id'] = user['user_id']
    flask.session['display_name'] = user['display_name']
    flask.session['role'] = user['role']
    flask.session['email'] = user.get('email', '')
    flask.session['must_change_password'] = bool(user.get('must_change_password'))
    flask.session['is_admin'] = bool(user.get('is_admin'))
    flask.current_app.permanent_session_lifetime = timedelta(hours=SESSION_LIFETIME_HOURS)


def clear_session() -> None:
    flask.session.clear()


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)
