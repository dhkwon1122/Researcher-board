"""
자체 아이디/비밀번호 인증 및 Flask 세션 관리.

사용자 정보는 DATABASE_URL이 설정돼 있으면 PostgreSQL만 사용한다. DB 접근이
실패하거나 계정이 없을 때 JSON 계정으로 폴백하지 않는다. 인증 저장소의 자동
폴백은 삭제·비활성화된 계정이 과거 JSON 자격증명으로 다시 로그인하는 fail-open
상태를 만들 수 있기 때문이다. DATABASE_URL이 없는 명시적 로컬 개발 환경에서만
config/users.json을 사용한다. 비밀번호는 두 백엔드 모두 Werkzeug 해시를 쓴다.
"""
from __future__ import annotations

import json
import os

import flask
from werkzeug.security import check_password_hash, generate_password_hash

from services import user_store

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
    TABLE_PERMISSIONS: dict[str, str] = {}

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
    fd = os.open(_USERS_FILE, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _database_configured() -> bool:
    """DATABASE_URL이 있으면 인증은 PostgreSQL에서만 수행한다."""
    return bool(os.environ.get('DATABASE_URL', '').strip())


# ── 인증 ─────────────────────────────────────────────────────────────────────
# DATABASE_URL이 있으면 DB-only, 없으면 개발용 JSON-only로 동작한다.

def authenticate(username: str, password: str) -> dict | None:
    """아이디/비밀번호 검증. 성공 시 사용자 dict, 실패 시 None."""
    if not username or not password:
        return None

    if _database_configured():
        if not user_store.available():
            return None
        data = user_store.get_user(username)
        if data is None or not check_password_hash(data['password_hash'], password):
            return None
        return {
            'user_id': username,
            'display_name': data.get('display_name', username),
            'email': data.get('email', ''),
            'role': data.get('role', DEFAULT_ROLE),
            'must_change_password': bool(data.get('must_change_password')),
            'is_admin': bool(data.get('is_admin')),
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
        'is_admin': bool(data.get('is_admin')),
    }


def has_any_user() -> bool:
    if _database_configured():
        return user_store.has_any() if user_store.available() else False
    return bool(_load_users_json())


# ── 사용자 CRUD ───────────────────────────────────────────────────────────────

def list_users() -> list[dict]:
    if _database_configured():
        if not user_store.available():
            return []
        return [
            {
                'user_id': d['user_id'],
                'display_name': d.get('display_name', ''),
                'email': d.get('email', ''),
                'role': d.get('role', DEFAULT_ROLE),
                'must_change_password': bool(d.get('must_change_password')),
                'is_admin': bool(d.get('is_admin')),
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
            'is_admin': bool(d.get('is_admin')),
        }
        for uid, d in _load_users_json().items()
    ]


def create_user(user_id: str, password: str, display_name: str,
                role: str, email: str = '', must_change_password: bool = False,
                is_admin: bool = False) -> None:
    """계정을 만든다. must_change_password=True로 만들면(예: 일괄 계정 생성)
    본인이 비밀번호를 바꾸기 전까지 로그인 직후 강제로 비밀번호 변경 화면만
    보게 된다(app.py의 require_login 참고). is_admin=True면 역할과 무관하게
    사용자 관리 페이지(manage_users)에 접근할 수 있다 — 역할별 권한이 아니라
    계정별로만 부여되는 값이다(config/auth_config.py 참고)."""
    if _database_configured():
        if not user_store.available():
            raise RuntimeError('사용자 DB에 연결할 수 없습니다.')
        if user_store.get_user(user_id) is not None:
            raise ValueError(f'이미 존재하는 계정입니다: {user_id}')
        if user_store.create(user_id, generate_password_hash(password), display_name, role, email,
                              must_change_password=must_change_password, is_admin=is_admin):
            return
        raise RuntimeError('사용자 DB에 계정을 저장하지 못했습니다.')

    users = _load_users_json()
    if user_id in users:
        raise ValueError(f'이미 존재하는 계정입니다: {user_id}')
    users[user_id] = {
        'password_hash': generate_password_hash(password),
        'display_name': display_name,
        'role': role,
        'email': email,
        'must_change_password': must_change_password,
        'is_admin': is_admin,
    }
    _save_users_json(users)


def update_user(user_id: str, display_name: str | None = None,
                role: str | None = None, email: str | None = None,
                is_admin: bool | None = None) -> bool:
    if _database_configured():
        if not user_store.available():
            return False
        return user_store.update_fields(user_id, display_name, role, email, is_admin)

    users = _load_users_json()
    if user_id not in users:
        return False
    if display_name is not None:
        users[user_id]['display_name'] = display_name
    if role is not None:
        users[user_id]['role'] = role
    if email is not None:
        users[user_id]['email'] = email
    if is_admin is not None:
        users[user_id]['is_admin'] = is_admin
    _save_users_json(users)
    return True


def change_password(user_id: str, new_password: str) -> bool:
    """비밀번호를 바꾼다. 임시 비밀번호로 만들어진 계정(must_change_password=True)
    이었다면 이 호출로 그 상태가 해제된다."""
    if _database_configured():
        if not user_store.available():
            return False
        return user_store.set_password_hash(user_id, generate_password_hash(new_password))

    users = _load_users_json()
    if user_id not in users:
        return False
    users[user_id]['password_hash'] = generate_password_hash(new_password)
    users[user_id]['must_change_password'] = False
    _save_users_json(users)
    return True


def delete_user(user_id: str) -> bool:
    if _database_configured():
        if not user_store.available():
            return False
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
        'is_admin': bool(flask.session.get('is_admin')),
    }


def current_user_mail_default() -> str:
    """현재 로그인 계정의 사내 메일 주소 추정값(로그인 ID@samsung.com).
    메일 발송 화면(pages/admin.py, pages/researcher_similarity_map.py)에서
    수신자를 비워두면 본인에게 보내는 기본값으로 쓴다. 로그인 세션이 없으면
    빈 문자열."""
    user = get_current_user()
    if not user:
        return ''
    return f"{user['user_id']}@samsung.com"


def can(permission: str) -> bool:
    """권한 확인. manage_users(사용자 관리 페이지)는 역할이 아니라 계정별
    is_admin 플래그로만 판단한다 — ROLE_PERMISSIONS에는 이 키를 두지 않는다
    (config/auth_config.py 참고). 나머지 권한은 역할 기준 그대로."""
    user = get_current_user()
    if user is None:
        return False
    if permission == 'manage_users':
        return user.get('is_admin', False)
    role = user.get('role', DEFAULT_ROLE)
    return ROLE_PERMISSIONS.get(role, {}).get(permission, False)


def can_table(table_name: str) -> bool:
    """table_name이 TABLE_PERMISSIONS에 등록돼 있으면 그 권한을, 없으면(민감정보로
    분류되지 않은 테이블) 항상 True를 반환한다. TABLE_PERMISSIONS 쪽만 보고
    판단하므로, 어떤 테이블이 어떤 권한에 걸리는지는 이 함수를 호출하는 쪽이
    권한 이름을 직접 하드코딩하지 않아도 된다(config/auth_config.py의
    TABLE_PERMISSIONS만 고치면 모든 호출부에 자동 반영)."""
    permission = TABLE_PERMISSIONS.get(table_name)
    return permission is None or can(permission)


def filter_permitted_tables(tables: dict) -> dict:
    """{테이블명: ...} 딕셔너리에서 TABLE_PERMISSIONS에 등록된 테이블 중
    현재 로그인 사용자에게 필요 권한이 없는 것을 제외하고 반환한다.
    TABLE_PERMISSIONS에 없는 테이블(민감정보로 분류되지 않은 것)은 그대로 둔다.
    AI 자연어 검색(services/nl_query.py, services/open_data_query.py)이 화면
    UI(pages/*.py)와 같은 권한 기준으로 평가등급/인센티브/코멘트/리더십·승계
    데이터를 가리는 데 쓴다 — 화면에서 못 보게 막아둔 데이터를 자연어 질문으로
    우회 조회하지 못하게 하는 것이 목적."""
    return {name: df for name, df in tables.items() if can_table(name)}


def set_session(user: dict) -> None:
    from datetime import timedelta
    # 기존 익명/로그인 세션 값을 모두 버린 뒤 새 인증 정보를 기록한다.
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
