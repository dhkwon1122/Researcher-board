"""
자체 아이디/비밀번호 인증 및 Flask 세션 관리.

사용자 정보는 DATABASE_URL이 설정돼 있으면 PostgreSQL(services/user_store,
app_users 테이블 — dhkwon1122/ai-friendly-doc의 users 테이블과 동일한 SQLAlchemy
Core 방식)에 저장하고, 없거나 DB 접근이 실패하면 config/users.json으로
폴백한다(나머지 데이터가 DB/CSV를 오가는 것과 동일한 패턴). 비밀번호는 두
백엔드 모두 werkzeug PBKDF2로 해싱한다.
"""
from __future__ import annotations

import json
import os

import flask
from werkzeug.security import check_password_hash, generate_password_hash

from services import user_store

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


# ── 사용자 파일 I/O (JSON 폴백) ────────────────────────────────────────────────

def _load_users_json() -> dict:
    if not os.path.exists(_USERS_FILE):
        return {}
    with open(_USERS_FILE, encoding='utf-8') as f:
        return json.load(f)


def _save_users_json(users: dict) -> None:
    os.makedirs(os.path.dirname(_USERS_FILE), exist_ok=True)
    with open(_USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# ── 인증 ─────────────────────────────────────────────────────────────────────
# 모든 함수는 DB(user_store, DATABASE_URL 설정 시 PostgreSQL)를 먼저 시도하고,
# DB가 없거나 실패하면 config/users.json으로 폴백한다.

def authenticate(username: str, password: str) -> dict | None:
    """아이디/비밀번호 검증. 성공 시 사용자 dict, 실패 시 None."""
    if not username or not password:
        return None

    if user_store.available():
        data = user_store.get_user(username)
        if data is not None:
            if not check_password_hash(data['password_hash'], password):
                return None
            return {
                'user_id': username,
                'display_name': data.get('display_name', username),
                'email': data.get('email', ''),
                'role': data.get('role', DEFAULT_ROLE),
                'must_change_password': bool(data.get('must_change_password')),
            }

    data = _load_users_json().get(username)
    if not data:
        return None
    if not check_password_hash(data['password_hash'], password):
        return None
    return {
        'user_id': username,
        'display_name': data.get('display_name', username),
        'email': data.get('email', ''),
        'role': data.get('role', DEFAULT_ROLE),
        'must_change_password': bool(data.get('must_change_password')),
    }


def has_any_user() -> bool:
    if user_store.available():
        return user_store.has_any()
    return bool(_load_users_json())


# ── 사용자 CRUD ───────────────────────────────────────────────────────────────

def list_users() -> list[dict]:
    if user_store.available():
        return [
            {
                'user_id': d['user_id'],
                'display_name': d.get('display_name', ''),
                'email': d.get('email', ''),
                'role': d.get('role', DEFAULT_ROLE),
                'must_change_password': bool(d.get('must_change_password')),
            }
            for d in user_store.list_all()
        ]
    return [
        {
            'user_id': uid,
            'display_name': d.get('display_name', ''),
            'email': d.get('email', ''),
            'role': d.get('role', DEFAULT_ROLE),
            'must_change_password': bool(d.get('must_change_password')),
        }
        for uid, d in _load_users_json().items()
    ]


def create_user(user_id: str, password: str, display_name: str,
                role: str, email: str = '', must_change_password: bool = False) -> None:
    """계정을 만든다. must_change_password=True로 만들면(예: 일괄 계정 생성)
    본인이 비밀번호를 바꾸기 전까지 로그인 직후 강제로 비밀번호 변경 화면만
    보게 된다(app.py의 require_login 참고)."""
    if user_store.available():
        if user_store.get_user(user_id) is not None:
            raise ValueError(f'이미 존재하는 계정입니다: {user_id}')
        if user_store.create(user_id, generate_password_hash(password), display_name, role, email,
                              must_change_password=must_change_password):
            return
        # DB insert 실패 시에도 계정 생성 자체는 막지 않고 JSON으로 폴백한다.

    users = _load_users_json()
    if user_id in users:
        raise ValueError(f'이미 존재하는 계정입니다: {user_id}')
    users[user_id] = {
        'password_hash': generate_password_hash(password),
        'display_name': display_name,
        'role': role,
        'email': email,
        'must_change_password': must_change_password,
    }
    _save_users_json(users)


def update_user(user_id: str, display_name: str | None = None,
                role: str | None = None, email: str | None = None) -> bool:
    if user_store.available():
        if user_store.get_user(user_id) is not None:
            return user_store.update_fields(user_id, display_name, role, email)

    users = _load_users_json()
    if user_id not in users:
        return False
    if display_name is not None:
        users[user_id]['display_name'] = display_name
    if role is not None:
        users[user_id]['role'] = role
    if email is not None:
        users[user_id]['email'] = email
    _save_users_json(users)
    return True


def change_password(user_id: str, new_password: str) -> bool:
    """비밀번호를 바꾼다. 임시 비밀번호로 만들어진 계정(must_change_password=True)
    이었다면 이 호출로 그 상태가 해제된다."""
    if user_store.available():
        if user_store.get_user(user_id) is not None:
            return user_store.set_password_hash(user_id, generate_password_hash(new_password))

    users = _load_users_json()
    if user_id not in users:
        return False
    users[user_id]['password_hash'] = generate_password_hash(new_password)
    users[user_id]['must_change_password'] = False
    _save_users_json(users)
    return True


def delete_user(user_id: str) -> bool:
    if user_store.available():
        if user_store.get_user(user_id) is not None:
            return user_store.delete_user(user_id)

    users = _load_users_json()
    if user_id not in users:
        return False
    del users[user_id]
    _save_users_json(users)
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
        'must_change_password': bool(flask.session.get('must_change_password')),
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
    flask.session['must_change_password'] = bool(user.get('must_change_password'))
    flask.current_app.permanent_session_lifetime = timedelta(hours=SESSION_LIFETIME_HOURS)


def clear_session() -> None:
    flask.session.clear()


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)
