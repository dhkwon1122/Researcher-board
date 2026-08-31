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
    TABLE_PERMISSIONS: dict[str, str | None] = {}

_USERS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'users.json',
)

# 2026-08-31 사용자 확정 — 기존 "12자 이상 + 4종류 중 3종류"에서 "8~12자
# (상한 포함) + 영문자/숫자/특수문자 3종류 모두 필수"로 변경. 대소문자는
# 더 이상 별도 종류로 세지 않는다(영문자는 대/소문자 구분 없이 하나로 취급).
# 최대 길이 상한은 이례적이지만(길수록 보통 더 안전) 사용자가 명시적으로
# 그대로 유지하기로 확정한 값이다.
MIN_PASSWORD_LENGTH = int(os.environ.get('MIN_PASSWORD_LENGTH', '8'))
MAX_PASSWORD_LENGTH = int(os.environ.get('MAX_PASSWORD_LENGTH', '12'))


def password_validation_error(password: str) -> str | None:
    """조직 계정에 적용할 비밀번호 정책. 오류가 없으면 None."""
    password = password or ''
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        return f'비밀번호는 {MIN_PASSWORD_LENGTH}~{MAX_PASSWORD_LENGTH}자여야 합니다.'
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    if not (has_letter and has_digit and has_special):
        return '비밀번호는 영문자, 숫자, 특수문자를 모두 포함해야 합니다.'
    return None


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

def _normalize_permissions(data: dict) -> dict:
    """DB(user_store._row_to_dict)와 JSON 저장 형식 양쪽 모두에서 4개 권한
    재정의 값을 동일한 모양(dict[str, bool|None])으로 뽑아낸다. None은
    "역할 기본값 사용"을 뜻한다(services/user_store.py PERMISSION_COLUMNS
    설명 참고)."""
    perms = data.get('permissions') or {}
    return {col: perms.get(col) for col in user_store.PERMISSION_COLUMNS}


def _normalize_excluded_dep_ids(data: dict) -> list[str]:
    return [str(d) for d in (data.get('eval_excluded_dep_ids') or []) if str(d).strip()]


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
            'permissions': _normalize_permissions(data),
            'eval_excluded_dep_ids': _normalize_excluded_dep_ids(data),
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
        'permissions': _normalize_permissions(data),
        'eval_excluded_dep_ids': _normalize_excluded_dep_ids(data),
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
                'permissions': _normalize_permissions(d),
                'eval_excluded_dep_ids': _normalize_excluded_dep_ids(d),
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
            'permissions': _normalize_permissions(d),
            'eval_excluded_dep_ids': _normalize_excluded_dep_ids(d),
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
        # 신규 계정은 전부 None(=역할 기본값 사용)으로 시작 — "사용자/권한
        # 관리" 탭에서 한 번이라도 저장해야 명시적 재정의가 생긴다.
        'permissions': {col: None for col in user_store.PERMISSION_COLUMNS},
        'eval_excluded_dep_ids': [],
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


def update_permissions(user_id: str, permissions: dict, eval_excluded_dep_ids: list) -> bool:
    """"사용자/권한 관리" 탭의 저장 버튼 — 4개 권한(view_evaluation 등)을
    이 계정 전용 값으로 명시적으로 고정하고, 평가 열람 예외 부서 목록도
    함께 저장한다. permissions는 user_store.PERMISSION_COLUMNS 4개 키를
    모두 bool로 채워서 넘겨야 한다(부분 업데이트 아님 — 화면이 4개
    체크박스를 항상 전부 함께 저장)."""
    if _database_configured():
        if not user_store.available():
            return False
        return user_store.update_permissions(user_id, permissions, eval_excluded_dep_ids)

    users = _load_users_json()
    if user_id not in users:
        return False
    users[user_id]['permissions'] = {col: bool(permissions.get(col)) for col in user_store.PERMISSION_COLUMNS}
    users[user_id]['eval_excluded_dep_ids'] = [str(d) for d in (eval_excluded_dep_ids or [])]
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
        'permissions': flask.session.get('permissions') or {},
        'eval_excluded_dep_ids': flask.session.get('eval_excluded_dep_ids') or [],
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
    (config/auth_config.py 참고). view_evaluation/view_incentive/
    view_comments/view_grade 4개는 계정별 재정의(permissions, 2026-08-31
    추가)가 있으면 그 값을 먼저 쓰고, 없으면(None) 기존처럼 역할 기본값
    (ROLE_PERMISSIONS)을 쓴다 — "사용자/권한 관리" 탭에서 한 번도 손대지
    않은 계정은 계속 역할을 그대로 따라간다."""
    user = get_current_user()
    if user is None:
        return False
    if permission == 'manage_users':
        return user.get('is_admin', False)
    override = user.get('permissions', {}).get(permission)
    if override is not None:
        return bool(override)
    role = user.get('role', DEFAULT_ROLE)
    return ROLE_PERMISSIONS.get(role, {}).get(permission, False)


def eval_excluded_dep_ids() -> set[str]:
    """현재 로그인 사용자가 평가등급을 볼 수 없는 부서(dep_id) 집합 —
    view_evaluation 자체는 있어도 이 부서 소속 연구원만은 예외로 가린다
    (사용자 확정 2026-08-31, "People팀 평가는 예외"류 세부 권한).
    view_evaluation 권한이 아예 없으면 이 목록 자체가 무의미하므로 빈
    집합을 돌려준다(호출부가 can('view_evaluation')과 별도로 이 함수만
    보고 판단하는 실수를 막기 위함 — can_view_evaluation()을 쓰면 이 걱정
    없이 한 번에 처리된다)."""
    if not can('view_evaluation'):
        return set()
    user = get_current_user()
    if user is None:
        return set()
    return {str(d) for d in user.get('eval_excluded_dep_ids', [])}


def can_view_evaluation(org_code: str, org_code_dep_id_map: dict | None = None) -> bool:
    """특정 연구원(org_code로 식별)의 평가등급을 지금 로그인한 사용자가 볼 수
    있는지 — view_evaluation 권한 + 부서 단위 예외(eval_excluded_dep_ids)를
    한 번에 판정한다. org_code_dep_id_map은 services.similarity_map.
    org_code_dep_id_map()의 결과를 그대로 넘긴다(auth.py는 team_refer 등
    데이터 계층을 직접 import하지 않기 위해 호출부가 매핑을 만들어 전달하는
    구조 — 명단처럼 여러 명을 한꺼번에 판정할 때도 매핑을 한 번만 만들어
    재사용할 수 있다). org_code_dep_id_map을 생략하면 부서 예외 판정 없이
    view_evaluation만 확인한다(매핑을 못 구하는 예외적 호출부용 폴백)."""
    if not can('view_evaluation'):
        return False
    excluded = eval_excluded_dep_ids()
    if not excluded:
        return True
    if org_code_dep_id_map is None:
        return True
    dep_id = org_code_dep_id_map.get(org_code, '')
    return dep_id not in excluded


def can_table(table_name: str) -> bool:
    """자연어 검색 테이블 권한을 기본 거부 방식으로 확인한다.

    evaluations/evaluations_history는 부서 단위 예외(eval_excluded_dep_ids)가
    있으면 통째로 차단한다 — AI 검색 결과는 행 단위로 부서를 걸러내는 기능이
    아직 없어서, 어중간하게 열어두면 화면·엑셀에서는 못 보게 막은 특정 부서
    평가를 AI 검색으로는 그대로 볼 수 있는 우회 경로가 생긴다(사용자 확정
    2026-08-31 — "화면·엑셀만 우선 적용, AI 검색은 안전하게 전체 차단")."""
    if get_current_user() is None or table_name not in TABLE_PERMISSIONS:
        return False
    permission = TABLE_PERMISSIONS.get(table_name)
    if not (True if permission is None else can(permission)):
        return False
    if table_name in ('evaluations', 'evaluations_history') and eval_excluded_dep_ids():
        return False
    return True


def filter_permitted_tables(tables: dict) -> dict:
    """{테이블명: ...} 딕셔너리에서 명시적으로 허용된 테이블만 반환한다.
    TABLE_PERMISSIONS에 없는 테이블은 민감도 분류 누락으로 보고 제외한다.
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
    flask.session['permissions'] = user.get('permissions') or {}
    flask.session['eval_excluded_dep_ids'] = user.get('eval_excluded_dep_ids') or []
    flask.current_app.permanent_session_lifetime = timedelta(hours=SESSION_LIFETIME_HOURS)


def clear_session() -> None:
    flask.session.clear()


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)
