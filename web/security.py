from __future__ import annotations

import os
import secrets
import threading
import time
from collections import defaultdict, deque

import flask

from config.settings import SecuritySettings, load_settings


AUTH_EXEMPT_PREFIXES = ('/assets/',)
AUTH_EXEMPT_PATHS = {'/login', '/auth/login', '/logout', '/setup'}
PASSWORD_CHANGE_PATH = '/change-password'


def get_or_create_secret_key() -> str:
    env_key = load_settings().security.flask_secret_key
    if env_key:
        return env_key

    key_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config',
        '.flask_secret_key',
    )
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    try:
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            key = secrets.token_hex(32)
            os.write(fd, key.encode('utf-8'))
        finally:
            os.close(fd)
        return key
    except FileExistsError:
        with open(key_path, encoding='utf-8') as f:
            return f.read().strip()


def csrf_token() -> str:
    token = flask.session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        flask.session['_csrf_token'] = token
    return token


def require_csrf() -> None:
    supplied = flask.request.form.get('_csrf_token', '')
    expected = flask.session.get('_csrf_token', '')
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        flask.abort(400)


class LoginRateLimiter:
    def __init__(self, window_seconds: int, max_failures: int) -> None:
        self.window_seconds = window_seconds
        self.max_failures = max_failures
        self._failures: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> 'LoginRateLimiter':
        settings = load_settings().security
        return cls(
            settings.login_window_seconds,
            settings.login_max_failures,
        )

    def key(self) -> str:
        return flask.request.remote_addr or 'unknown'

    def is_blocked(self, key: str) -> bool:
        cutoff = time.monotonic() - self.window_seconds
        with self._lock:
            failures = self._failures[key]
            while failures and failures[0] < cutoff:
                failures.popleft()
            return len(failures) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'no-referrer')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; "
        "img-src 'self' data:; font-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'",
    )
    if flask.request.is_secure or flask.request.headers.get('X-Forwarded-Proto') == 'https':
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response


def require_login():
    path = flask.request.path
    if path in AUTH_EXEMPT_PATHS:
        return None
    if any(path.startswith(p) for p in AUTH_EXEMPT_PREFIXES):
        return None

    is_json = path.startswith('/_dash') or (
        flask.request.content_type and 'application/json' in flask.request.content_type
    )
    if not flask.session.get('user_id'):
        if is_json:
            return flask.jsonify({'error': 'unauthorized'}), 401
        return flask.redirect(f'/login?next={path}')
    if flask.session.get('must_change_password') and path != PASSWORD_CHANGE_PATH:
        if is_json:
            return flask.jsonify({'error': 'password_change_required'}), 403
        return flask.redirect(PASSWORD_CHANGE_PATH)
    return None


def configure_security(server, settings: SecuritySettings | None = None) -> LoginRateLimiter:
    settings = settings or load_settings().security
    server.secret_key = get_or_create_secret_key()
    server.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
        MAX_CONTENT_LENGTH=settings.max_content_length,
    )
    server.after_request(add_security_headers)
    server.before_request(require_login)
    return LoginRateLimiter(settings.login_window_seconds, settings.login_max_failures)
