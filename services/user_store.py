"""
사용자 계정을 PostgreSQL(DATABASE_URL 설정 시)에 저장하는 저장소.

services/db.py 의 엔진을 그대로 재사용한다(dhkwon1122/ai-friendly-doc의
web/db.py와 동일한 SQLAlchemy Core 테이블 정의 방식을 따름). DB 연결이
없거나(DATABASE_URL 미설정) 실패하면 모든 함수가 예외를 삼키고 실패를
나타내는 값(None/False/빈 리스트)을 반환한다 — 호출부(services/auth.py)가
그 경우 config/users.json으로 폴백한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, delete, select, text, update

from services.db import get_engine

metadata = MetaData()

# 계정별 권한 재정의(2026-08-31) — NULL이면 "역할 기본값을 따른다"는 뜻이고,
# True/False가 명시적으로 저장돼 있으면 역할이 바뀌어도 그 값을 그대로
# 유지한다(사용자 확정 — 관리자가 개별 조정해 둔 값은 역할 변경과 무관하게
# 유지). pages/admin.py의 "사용자/권한 관리" 탭이 저장할 때는 4개 모두 항상
# 명시적 값을 쓴다(그 화면에서 한 번이라도 저장하면 그 뒤로는 역할 기본값을
# 자동으로 따라가지 않는다는 뜻) — 한 번도 손대지 않은 계정만 NULL로 남아
# 역할 기본값을 계속 따른다.
PERMISSION_COLUMNS = ('view_evaluation', 'view_incentive', 'view_comments', 'view_grade')

# 다른 데이터 테이블(researchers 등)과 이름이 겹치지 않도록 app_users로 둔다.
users = Table(
    'app_users',
    metadata,
    Column('user_id', String, primary_key=True),
    Column('password_hash', String, nullable=False),
    Column('display_name', String, nullable=False),
    Column('role', String, nullable=False),
    Column('email', String),
    # 일괄 계정 생성(scripts/bulk_create_users.py)으로 만든 계정이 임시
    # 비밀번호로 로그인하면 True — app.py가 이 값을 보고 비밀번호를 바꾸기
    # 전까지 다른 화면 접근을 막는다. 비밀번호를 바꾸면(set_password_hash)
    # 항상 False로 되돌아간다.
    Column('must_change_password', Boolean, nullable=False, server_default='false'),
    # manage_users(사용자 관리 페이지) 권한은 역할이 아니라 이 플래그로만
    # 부여한다(config/auth_config.py 상단 설명 참고) — 같은 역할이라도
    # 필요한 사람에게만 개별적으로 관리자 권한을 줄 수 있게 하기 위함이다.
    Column('is_admin', Boolean, nullable=False, server_default='false'),
    # 역할 기본 권한(config/auth_config.py의 ROLE_PERMISSIONS)을 계정 단위로
    # 재정의한 값 — NULL은 "역할 기본값 사용"을 뜻한다(위 PERMISSION_COLUMNS
    # 설명 참고).
    Column('perm_view_evaluation', Boolean),
    Column('perm_view_incentive', Boolean),
    Column('perm_view_comments', Boolean),
    Column('perm_view_grade', Boolean),
    # view_evaluation이 있어도 특정 부서(team_refer의 dep_id) 소속 연구원의
    # 평가만은 못 보게 하는 예외 목록 — JSON 배열 문자열(예: '["D-003"]').
    # dep_name(표시 라벨)이 아니라 dep_id를 쓰는 이유는 services/similarity_map.py
    # org_code_dep_id_map() 참고(부서명이 나중에 바뀌어도 예외가 계속 유효해야 함).
    Column('eval_excluded_dep_ids', String),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

_table_ready = False


def _ensure_column(engine, column_name: str, ddl: str, *, backfill_sql: str | None = None) -> None:
    """column_name 컬럼이 없으면 추가한다(ALTER TABLE ... ADD COLUMN이 아니라
    먼저 information_schema로 존재 여부를 확인하는 이유: 방금 이 실행에서
    컬럼을 새로 추가했을 때만 backfill_sql을 실행하기 위해서다 — 매번
    실행하면, 나중에 관리자가 값을 일부러 바꿔둔 걸 재기동 때마다 덮어써버릴
    수 있다(예: is_admin 백필). 이미 컬럼이 있으면 아무 것도 하지 않는다."""
    with engine.begin() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'app_users' AND column_name = :col"
        ), {'col': column_name}).first()
        if exists:
            return
        conn.execute(text(f'ALTER TABLE app_users ADD COLUMN IF NOT EXISTS {ddl}'))
        if backfill_sql:
            conn.execute(text(backfill_sql))


def available() -> bool:
    """DB 엔진이 있고 app_users 테이블이 준비돼 있으면 True."""
    global _table_ready
    engine = get_engine()
    if engine is None:
        return False
    if not _table_ready:
        try:
            metadata.create_all(engine, tables=[users])
            _ensure_column(engine, 'must_change_password',
                            'must_change_password BOOLEAN NOT NULL DEFAULT FALSE')
            # is_admin이 이번에 처음 추가되는 경우, 이전까지는 role='executive_org'면
            # 역할만으로 자동 관리자였다 — 그 계정들이 마이그레이션 직후 관리자
            # 페이지에서 잠기지 않도록 한 번만 개인별 관리자 권한을 이어서 준다.
            # (컬럼이 이미 있으면 이 UPDATE는 실행되지 않으므로, 이후 누군가 역할을
            # executive_org로 바꾼다고 자동으로 관리자가 되지는 않는다.)
            _ensure_column(engine, 'is_admin',
                            "is_admin BOOLEAN NOT NULL DEFAULT FALSE",
                            backfill_sql="UPDATE app_users SET is_admin = TRUE "
                                         "WHERE role = 'executive_org'")
            # 계정별 권한 재정의 컬럼(2026-08-31) — 전부 NULL 허용(기본값 없음)이라
            # 기존 계정은 컬럼이 새로 생겨도 전부 NULL로 시작해 그대로 역할 기본값을
            # 따른다(백필 불필요).
            for col in PERMISSION_COLUMNS:
                _ensure_column(engine, f'perm_{col}', f'perm_{col} BOOLEAN')
            _ensure_column(engine, 'eval_excluded_dep_ids', 'eval_excluded_dep_ids TEXT')
            _table_ready = True
        except Exception as exc:
            print(f'[user_store] app_users 테이블 준비 실패, JSON으로 폴백: {exc}')
            return False
    return True


def _row_to_dict(row) -> dict:
    try:
        excluded = json.loads(row.get('eval_excluded_dep_ids') or '[]')
        if not isinstance(excluded, list):
            excluded = []
    except (TypeError, ValueError):
        excluded = []
    return {
        'user_id': row['user_id'],
        'password_hash': row['password_hash'],
        'display_name': row['display_name'],
        'role': row['role'],
        'email': row.get('email') or '',
        'must_change_password': bool(row.get('must_change_password')),
        'is_admin': bool(row.get('is_admin')),
        # None이면 "역할 기본값 사용" — services/auth.py의 can()이 판정.
        'permissions': {col: row.get(f'perm_{col}') for col in PERMISSION_COLUMNS},
        'eval_excluded_dep_ids': [str(d) for d in excluded if str(d).strip()],
    }


def get_user(user_id: str) -> dict | None:
    if not available():
        return None
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                select(users).where(users.c.user_id == user_id)
            ).mappings().first()
            return _row_to_dict(row) if row else None
    except Exception as exc:
        print(f'[user_store] get_user 실패: {exc}')
        return None


def list_all() -> list[dict]:
    if not available():
        return []
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(select(users)).mappings().all()
            return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f'[user_store] list_all 실패: {exc}')
        return []


def has_any() -> bool:
    return bool(list_all()) if available() else False


def create(user_id: str, password_hash: str, display_name: str,
           role: str, email: str = '', must_change_password: bool = False,
           is_admin: bool = False) -> bool:
    if not available():
        return False
    try:
        with get_engine().begin() as conn:
            conn.execute(users.insert().values(
                user_id=user_id,
                password_hash=password_hash,
                display_name=display_name,
                role=role,
                email=email or None,
                must_change_password=must_change_password,
                is_admin=is_admin,
                created_at=datetime.now(timezone.utc),
            ))
        return True
    except Exception as exc:
        print(f'[user_store] create 실패: {exc}')
        return False


def update_fields(user_id: str, display_name: str | None = None,
                   role: str | None = None, email: str | None = None,
                   is_admin: bool | None = None) -> bool:
    if not available():
        return False
    values = {}
    if display_name is not None:
        values['display_name'] = display_name
    if role is not None:
        values['role'] = role
    if email is not None:
        values['email'] = email
    if is_admin is not None:
        values['is_admin'] = is_admin
    if not values:
        return True
    try:
        with get_engine().begin() as conn:
            result = conn.execute(
                update(users).where(users.c.user_id == user_id).values(**values)
            )
            return result.rowcount > 0
    except Exception as exc:
        print(f'[user_store] update_fields 실패: {exc}')
        return False


def update_permissions(user_id: str, permissions: dict, eval_excluded_dep_ids: list) -> bool:
    """"사용자/권한 관리" 탭이 저장 버튼을 누를 때 쓴다 — permissions의 4개
    키(PERMISSION_COLUMNS)를 전부 명시적 True/False로 저장한다(이 함수를
    한 번이라도 거치면 그 계정은 이후 역할이 바뀌어도 이 값을 그대로 유지
    — 사용자 확정). eval_excluded_dep_ids는 view_evaluation이 True일 때만
    의미가 있지만, False로 저장하는 경우에도 목록 자체는 그대로 보존한다
    (나중에 다시 True로 바꿀 때 이전에 골라둔 부서 목록이 남아있도록)."""
    if not available():
        return False
    values = {f'perm_{col}': permissions.get(col) for col in PERMISSION_COLUMNS}
    values['eval_excluded_dep_ids'] = json.dumps(list(eval_excluded_dep_ids or []), ensure_ascii=False)
    try:
        with get_engine().begin() as conn:
            result = conn.execute(
                update(users).where(users.c.user_id == user_id).values(**values)
            )
            return result.rowcount > 0
    except Exception as exc:
        print(f'[user_store] update_permissions 실패: {exc}')
        return False


def set_password_hash(user_id: str, password_hash: str) -> bool:
    """비밀번호를 바꾼다 — 임시 비밀번호로 로그인했던 계정이라도 이 시점부터
    must_change_password를 False로 되돌려 강제 변경 화면에서 풀어준다."""
    if not available():
        return False
    try:
        with get_engine().begin() as conn:
            result = conn.execute(
                update(users).where(users.c.user_id == user_id)
                .values(password_hash=password_hash, must_change_password=False)
            )
            return result.rowcount > 0
    except Exception as exc:
        print(f'[user_store] set_password_hash 실패: {exc}')
        return False


def delete_user(user_id: str) -> bool:
    if not available():
        return False
    try:
        with get_engine().begin() as conn:
            result = conn.execute(delete(users).where(users.c.user_id == user_id))
            return result.rowcount > 0
    except Exception as exc:
        print(f'[user_store] delete_user 실패: {exc}')
        return False
