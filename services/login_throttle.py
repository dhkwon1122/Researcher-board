"""
로그인 실패 횟수를 세어 무차별 대입(brute-force) 시도를 완화한다.

DATABASE_URL이 설정돼 있으면 PostgreSQL(login_failures 테이블)에 기록한다 —
운영 배포는 gunicorn 다중 워커(app.py의 _get_or_create_secret_key 설명 참고)
또는 다중 컨테이너로 뜨는데, 카운터를 프로세스 메모리에만 두면 워커/컨테이너
수만큼 실제 허용 시도 횟수가 늘어나 rate limit이 사실상 무력화된다. DB가
없으면(로컬 단일 프로세스 개발 환경) 프로세스 메모리로 폴백한다.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Index, Integer, MetaData, String, Table, delete, func, select

from services.db import get_engine

metadata = MetaData()

login_failures = Table(
    'login_failures',
    metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('key', String, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Index('ix_login_failures_key_created_at', 'key', 'created_at'),
)

_table_ready = False


def _ensure_table(engine) -> bool:
    global _table_ready
    if _table_ready:
        return True
    try:
        metadata.create_all(engine, tables=[login_failures])
        _table_ready = True
    except Exception as exc:
        print(f'[login_throttle] login_failures 테이블 준비 실패, 메모리로 폴백: {exc}')
        return False
    return True


# ── 메모리 폴백 (DATABASE_URL 미설정 시 — 단일 프로세스 전제) ─────────────────
_mem_failures: dict[str, deque] = defaultdict(deque)
_mem_lock = threading.Lock()


def _mem_count(key: str, window_seconds: int) -> int:
    cutoff = time.monotonic() - window_seconds
    with _mem_lock:
        failures = _mem_failures[key]
        while failures and failures[0] < cutoff:
            failures.popleft()
        return len(failures)


def _mem_record(key: str) -> None:
    with _mem_lock:
        _mem_failures[key].append(time.monotonic())


def _mem_clear(key: str) -> None:
    with _mem_lock:
        _mem_failures.pop(key, None)


# ── 공개 API ─────────────────────────────────────────────────────────────────

def count_recent_failures(key: str, window_seconds: int) -> int:
    engine = get_engine()
    if engine is not None and _ensure_table(engine):
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        try:
            with engine.connect() as conn:
                return conn.execute(
                    select(func.count()).select_from(login_failures)
                    .where(login_failures.c.key == key, login_failures.c.created_at >= cutoff)
                ).scalar_one()
        except Exception as exc:
            print(f'[login_throttle] count 조회 실패, 메모리로 폴백: {exc}')
    return _mem_count(key, window_seconds)


def record_failure(key: str, window_seconds: int) -> None:
    engine = get_engine()
    if engine is not None and _ensure_table(engine):
        try:
            with engine.begin() as conn:
                conn.execute(login_failures.insert().values(
                    key=key, created_at=datetime.now(timezone.utc),
                ))
                # 창(window)을 벗어난 기록은 그때그때 지워 테이블이 무한히
                # 커지지 않게 한다.
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
                conn.execute(delete(login_failures).where(login_failures.c.created_at < cutoff))
            return
        except Exception as exc:
            print(f'[login_throttle] record 실패, 메모리로 폴백: {exc}')
    _mem_record(key)


def clear_failures(key: str) -> None:
    engine = get_engine()
    if engine is not None and _ensure_table(engine):
        try:
            with engine.begin() as conn:
                conn.execute(delete(login_failures).where(login_failures.c.key == key))
            return
        except Exception as exc:
            print(f'[login_throttle] clear 실패, 메모리로 폴백: {exc}')
    _mem_clear(key)
