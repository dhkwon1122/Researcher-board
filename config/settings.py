from __future__ import annotations

import os
from dataclasses import dataclass


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class AppSettings:
    port: int = 8501


@dataclass(frozen=True)
class SecuritySettings:
    flask_secret_key: str = ''
    session_cookie_secure: bool = False
    max_content_length: int = 10 * 1024 * 1024
    login_window_seconds: int = 900
    login_max_failures: int = 5
    min_password_length: int = 12
    enable_web_setup: bool = False


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: str = ''

    @property
    def configured(self) -> bool:
        return bool(self.database_url.strip())


@dataclass(frozen=True)
class QueryRuntimeSettings:
    duckdb_memory_limit_mb: int = 512
    duckdb_threads: int = 2


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    security: SecuritySettings
    database: DatabaseSettings
    query_runtime: QueryRuntimeSettings


def load_settings() -> Settings:
    return Settings(
        app=AppSettings(
            port=int(os.environ.get('PORT', '8501')),
        ),
        security=SecuritySettings(
            flask_secret_key=os.environ.get('FLASK_SECRET_KEY', '').strip(),
            session_cookie_secure=env_bool('SESSION_COOKIE_SECURE', False),
            max_content_length=int(os.environ.get('MAX_CONTENT_LENGTH', str(10 * 1024 * 1024))),
            login_window_seconds=int(os.environ.get('LOGIN_WINDOW_SECONDS', '900')),
            login_max_failures=int(os.environ.get('LOGIN_MAX_FAILURES', '5')),
            min_password_length=int(os.environ.get('MIN_PASSWORD_LENGTH', '12')),
            enable_web_setup=env_bool('ENABLE_WEB_SETUP', False),
        ),
        database=DatabaseSettings(
            database_url=os.environ.get('DATABASE_URL', '').strip(),
        ),
        query_runtime=QueryRuntimeSettings(
            duckdb_memory_limit_mb=int(os.environ.get('DUCKDB_MEMORY_LIMIT_MB', '512')),
            duckdb_threads=int(os.environ.get('DUCKDB_THREADS', '2')),
        ),
    )
