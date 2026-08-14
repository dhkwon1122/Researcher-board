"""
사용자 계정을 PostgreSQL(DATABASE_URL 설정 시)에 저장하는 저장소.

services/db.py 의 엔진을 그대로 재사용한다(dhkwon1122/ai-friendly-doc의
web/db.py와 동일한 SQLAlchemy Core 테이블 정의 방식을 따름). DB 연결이
없거나(DATABASE_URL 미설정) 실패하면 모든 함수가 예외를 삼키고 실패를
나타내는 값(None/False/빈 리스트)을 반환한다 — 호출부(services/auth.py)가
그 경우 config/users.json으로 폴백한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, delete, select, text, update

from services.db import get_engine

metadata = MetaData()

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
            _table_ready = True
        except Exception as exc:
            print(f'[user_store] app_users 테이블 준비 실패, JSON으로 폴백: {exc}')
            return False
    return True


def _row_to_dict(row) -> dict:
    return {
        'user_id': row['user_id'],
        'password_hash': row['password_hash'],
        'display_name': row['display_name'],
        'role': row['role'],
        'email': row.get('email') or '',
        'must_change_password': bool(row.get('must_change_password')),
        'is_admin': bool(row.get('is_admin')),
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
