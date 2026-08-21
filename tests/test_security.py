import os
import re
from unittest.mock import patch

import pytest
from flask import Flask, session

from pipeline.confluence_client import ConfluenceError, _base_url
from services import auth, login_throttle
from services.text2sql import Text2SQLError, sanitize_sql


def _flask_app():
    app = Flask(__name__)
    app.secret_key = 'test-only-secret'
    return app


def test_unknown_ai_table_is_denied_by_default():
    app = _flask_app()
    with app.test_request_context('/'):
        session.update(user_id='tester', role='talent_dev', is_admin=False)
        assert auth.can_table('researchers') is True
        assert auth.can_table('new_sensitive_export') is False
        assert auth.can_table('evaluations') is False


def test_ai_tables_require_authentication():
    app = _flask_app()
    with app.test_request_context('/'):
        assert auth.can_table('researchers') is False


def test_database_auth_never_falls_back_to_json():
    fake_json_user = {'tester': {'password_hash': 'stale'}}
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://db/researcher'}, clear=False), \
         patch.object(auth.user_store, 'available', return_value=False), \
         patch.object(auth, '_load_users_json', return_value=fake_json_user):
        assert auth.authenticate('tester', 'old-password') is None


@pytest.mark.parametrize('password', ['short', 'alllowercasebutlong', '1234567890123456'])
def test_password_policy_rejects_weak_passwords(password):
    assert auth.password_validation_error(password)


def test_password_policy_accepts_mixed_password():
    assert auth.password_validation_error('Correct-Horse-42') is None


def test_confluence_host_allowlist_and_https(monkeypatch):
    monkeypatch.setenv('CONFLUENCE_ALLOWED_HOSTS', 'internal.example.com')
    assert _base_url('https://wiki.internal.example.com/pages/123') == 'https://wiki.internal.example.com'
    with pytest.raises(ConfluenceError):
        _base_url('https://attacker.example/pages/123')
    with pytest.raises(ConfluenceError):
        _base_url('http://wiki.internal.example.com/pages/123')


def test_text2sql_allows_single_select_and_rejects_writes():
    assert sanitize_sql('SELECT * FROM researchers').endswith('LIMIT 200')
    with pytest.raises(Text2SQLError):
        sanitize_sql('DELETE FROM researchers')
    with pytest.raises(Text2SQLError):
        sanitize_sql('SELECT 1; SELECT 2')


def test_dash_and_photos_are_not_auth_exempt():
    from app import app as dash_app

    client = dash_app.server.test_client()
    assert client.get('/_dash-layout').status_code == 401
    assert client.get('/photo/00000001').status_code == 302
    response = client.get('/login')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'


# ── 로그인 rate limiting (services/login_throttle.py) ─────────────────────────

def test_login_throttle_memory_counts_and_clears(monkeypatch):
    """DB(DATABASE_URL)가 없는 로컬/테스트 환경에서는 메모리 카운터로 폴백한다."""
    monkeypatch.setattr(login_throttle, 'get_engine', lambda: None)
    key = 'test:memory-counter'
    login_throttle.clear_failures(key)
    assert login_throttle.count_recent_failures(key, 60) == 0
    login_throttle.record_failure(key, 60)
    login_throttle.record_failure(key, 60)
    assert login_throttle.count_recent_failures(key, 60) == 2
    login_throttle.clear_failures(key)
    assert login_throttle.count_recent_failures(key, 60) == 0


def test_login_throttle_memory_expires_outside_window(monkeypatch):
    monkeypatch.setattr(login_throttle, 'get_engine', lambda: None)
    key = 'test:memory-expiry'
    login_throttle.clear_failures(key)
    login_throttle.record_failure(key, 60)
    assert login_throttle.count_recent_failures(key, 60) == 1
    # window=0 → 방금 기록한 실패도 이미 창을 벗어난 것으로 취급되어야 한다.
    assert login_throttle.count_recent_failures(key, 0) == 0
    login_throttle.clear_failures(key)


def _login_attempt(client, username, password, remote_addr):
    """GET /login에서 CSRF 토큰을 읽어 그대로 POST /auth/login에 실어 보낸다."""
    overrides = {'REMOTE_ADDR': remote_addr}
    page = client.get('/login', environ_overrides=overrides)
    token = re.search(r'name="_csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    return client.post('/auth/login', environ_overrides=overrides, data={
        'username': username, 'password': password, 'next': '/', '_csrf_token': token,
    })


def test_login_lockout_applies_per_account_across_source_addresses(monkeypatch):
    """계정별 카운터가 있어, IP를 바꿔가며 같은 계정을 노리는 분산 시도도 막는다."""
    from app import _LOGIN_MAX_FAILURES
    from app import app as dash_app

    monkeypatch.setattr(login_throttle, 'get_engine', lambda: None)
    monkeypatch.setattr(auth, 'has_any_user', lambda: True)
    username = 'lockout-target-user'
    login_throttle.clear_failures(f'user:{username}')
    try:
        for i in range(_LOGIN_MAX_FAILURES):
            client = dash_app.server.test_client()
            resp = _login_attempt(client, username, 'wrong-password', f'203.0.113.{i}')
            assert resp.status_code == 302

        client = dash_app.server.test_client()
        resp = _login_attempt(client, username, 'wrong-password', '203.0.113.99')
        assert resp.status_code == 429
    finally:
        login_throttle.clear_failures(f'user:{username}')


def test_login_lockout_applies_per_ip_across_accounts(monkeypatch):
    """IP별 카운터가 있어, 계정을 바꿔가며(계정 스프레이) 시도해도 막는다."""
    from app import _LOGIN_MAX_FAILURES
    from app import app as dash_app

    monkeypatch.setattr(login_throttle, 'get_engine', lambda: None)
    monkeypatch.setattr(auth, 'has_any_user', lambda: True)
    ip = '198.51.100.42'
    login_throttle.clear_failures(f'ip:{ip}')
    client = dash_app.server.test_client()
    try:
        for i in range(_LOGIN_MAX_FAILURES):
            resp = _login_attempt(client, f'spray-user-{i}', 'wrong-password', ip)
            assert resp.status_code == 302
        resp = _login_attempt(client, 'spray-user-final', 'wrong-password', ip)
        assert resp.status_code == 429
    finally:
        login_throttle.clear_failures(f'ip:{ip}')
        for i in range(_LOGIN_MAX_FAILURES):
            login_throttle.clear_failures(f'user:spray-user-{i}')
        login_throttle.clear_failures('user:spray-user-final')
