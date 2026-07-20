"""
자체 아이디/비밀번호 인증 및 Flask 세션 관리.
사용자 정보는 config/users.json 에 저장되며 비밀번호는 werkzeug PBKDF2로 해싱.
"""
from __future__ import annotations

import json
import os

import flask
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from config.auth_config import (
        DEFAULT_ROLE, ROLE_LABELS, ROLE_PERMISSIONS, SESSION_LIFETIME_HOURS,
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
            'view_comments': True, 'view_grade': True, 'manage_users': True,
        },
        'talent_dev': {
            'view_evaluation': False, 'view_incentive': False,
            'view_comments': False, 'view_grade': False, 'manage_users': False,
        },
    }
    SESSION_LIFETIME_HOURS = 8

_USERS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'users.json',
)


# ── 사용자 파일 I/O ───────────────────────────────────────────────────────────

def _load_users() -> dict:
    if not os.path.exists(_USERS_FILE):
        return {}
    with open(_USERS_FILE, encoding='utf-8') as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    os.makedirs(os.path.dirname(_USERS_FILE), exist_ok=True)
    with open(_USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# ── 인증 ─────────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> dict | None:
    """아이디/비밀번호 검증. 성공 시 사용자 dict, 실패 시 None."""
    if not username or not password:
        return None
    users = _load_users()
    data = users.get(username)
    if not data:
        return None
    if not check_password_hash(data['password_hash'], password):
        return None
    return {
        'user_id': username,
        'display_name': data.get('display_name', username),
        'email': data.get('email', ''),
        'role': data.get('role', DEFAULT_ROLE),
    }


def has_any_user() -> bool:
    return bool(_load_users())


# ── 사용자 CRUD ───────────────────────────────────────────────────────────────

def list_users() -> list[dict]:
    return [
        {
            'user_id': uid,
            'display_name': d.get('display_name', ''),
            'email': d.get('email', ''),
            'role': d.get('role', DEFAULT_ROLE),
        }
        for uid, d in _load_users().items()
    ]


def create_user(user_id: str, password: str, display_name: str,
                role: str, email: str = '') -> None:
    users = _load_users()
    if user_id in users:
        raise ValueError(f'이미 존재하는 계정입니다: {user_id}')
    users[user_id] = {
        'password_hash': generate_password_hash(password),
        'display_name': display_name,
        'role': role,
        'email': email,
    }
    _save_users(users)


def update_user(user_id: str, display_name: str | None = None,
                role: str | None = None, email: str | None = None) -> bool:
    users = _load_users()
    if user_id not in users:
        return False
    if display_name is not None:
        users[user_id]['display_name'] = display_name
    if role is not None:
        users[user_id]['role'] = role
    if email is not None:
        users[user_id]['email'] = email
    _save_users(users)
    return True


def change_password(user_id: str, new_password: str) -> bool:
    users = _load_users()
    if user_id not in users:
        return False
    users[user_id]['password_hash'] = generate_password_hash(new_password)
    _save_users(users)
    return True


def delete_user(user_id: str) -> bool:
    users = _load_users()
    if user_id not in users:
        return False
    del users[user_id]
    _save_users(users)
    return True


# ── Flask 세션 ────────────────────────────────────────────────────────────────

def get_current_user() -> dict | None:
    if 'user_id' not in flask.session:
        return None
    return {
        'user_id': flask.session['user_id'],
        'display_name': flask.session.get('display_name', ''),
        'role': flask.session.get('role', DEFAULT_ROLE),
        'email': flask.session.get('email', ''),
    }


def can(permission: str) -> bool:
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
