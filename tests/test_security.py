import os
from unittest.mock import patch

import pytest
from flask import Flask, session

from pipeline.confluence_client import ConfluenceError, _base_url
from services import auth
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
