from __future__ import annotations

from html import escape
from urllib.parse import quote

import flask

from config.settings import Settings, load_settings
from web.security import LoginRateLimiter, csrf_token, require_csrf


def safe_next_url(raw: str) -> str:
    raw = (raw or '').strip()
    if raw.startswith('/') and not raw.startswith(('//', '/\\')):
        return raw
    return '/'


def html_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — 연구원 대시보드</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {{ background:#f0f2f5; min-height:100vh;
            display:flex; align-items:center; justify-content:center; }}
    .auth-card {{ border:none; border-radius:12px;
                  box-shadow:0 4px 24px rgba(0,0,0,.1); max-width:420px; width:100%; }}
    .btn-brand {{ background:#1e3a5f; border-color:#1e3a5f; }}
    .btn-brand:hover {{ background:#163050; border-color:#163050; }}
    .brand-icon {{ font-size:2.2rem; color:#1e3a5f; }}
  </style>
</head>
<body>
  <div class="auth-card card p-4 mx-3">
    <div class="text-center mb-4">
      <i class="bi bi-bar-chart-fill brand-icon"></i>
      <h5 class="fw-bold mt-2 mb-1">연구원 대시보드</h5>
      <p class="text-muted small mb-0">피플팀 전용 시스템</p>
    </div>
    {body}
  </div>
</body>
</html>"""


def register_auth_routes(server, limiter: LoginRateLimiter, settings: Settings | None = None) -> None:
    settings = settings or load_settings()

    @server.route('/login')
    def login_page():
        from services.auth import get_current_user, has_any_user
        if get_current_user():
            return flask.redirect('/')
        if not has_any_user():
            return flask.redirect('/setup')

        error = flask.request.args.get('error', '')
        next_url = safe_next_url(flask.request.args.get('next', '/'))
        setup_ok = flask.request.args.get('setup', '')

        alert = ''
        if error == 'invalid':
            alert = '<div class="alert alert-danger py-2 small mb-3">아이디 또는 비밀번호가 올바르지 않습니다.</div>'
        elif setup_ok:
            alert = '<div class="alert alert-success py-2 small mb-3">계정이 생성되었습니다. 로그인하세요.</div>'

        body = f"""{alert}
    <form method="POST" action="/auth/login">
      <input type="hidden" name="_csrf_token" value="{csrf_token()}">
      <input type="hidden" name="next" value="{escape(next_url)}">
      <div class="mb-3">
        <label class="form-label small fw-semibold">아이디</label>
        <div class="input-group">
          <span class="input-group-text"><i class="bi bi-person"></i></span>
          <input type="text" class="form-control" name="username"
                 autocomplete="username" autofocus required>
        </div>
      </div>
      <div class="mb-4">
        <label class="form-label small fw-semibold">비밀번호</label>
        <div class="input-group">
          <span class="input-group-text"><i class="bi bi-lock"></i></span>
          <input type="password" class="form-control" name="password"
                 autocomplete="current-password" required>
        </div>
      </div>
      <button type="submit" class="btn btn-brand text-white w-100">
        <i class="bi bi-box-arrow-in-right me-1"></i> 로그인
      </button>
    </form>"""
        return html_page('로그인', body)

    @server.route('/auth/login', methods=['POST'])
    def auth_login():
        from services.auth import authenticate, set_session
        require_csrf()
        login_key = limiter.key()
        if limiter.is_blocked(login_key):
            return flask.jsonify({'error': 'too_many_login_attempts'}), 429
        username = flask.request.form.get('username', '').strip()
        password = flask.request.form.get('password', '')
        next_url = safe_next_url(flask.request.form.get('next', '/'))
        user = authenticate(username, password)
        if not user:
            limiter.record_failure(login_key)
            return flask.redirect(f'/login?error=invalid&next={quote(next_url)}')
        limiter.clear(login_key)
        set_session(user)
        return flask.redirect(next_url)

    @server.route('/setup', methods=['GET', 'POST'])
    def setup_page():
        from services.auth import create_user, has_any_user, password_validation_error
        if settings.database.configured and not settings.security.enable_web_setup:
            flask.abort(403)
        if has_any_user():
            return flask.redirect('/login')

        error = ''
        if flask.request.method == 'POST':
            require_csrf()
            uid = flask.request.form.get('username', '').strip()
            name = flask.request.form.get('display_name', '').strip()
            pw = flask.request.form.get('password', '')
            pw2 = flask.request.form.get('password_confirm', '')
            if not uid or not name or not pw:
                error = '모든 항목을 입력하세요.'
            elif pw != pw2:
                error = '비밀번호가 일치하지 않습니다.'
            elif password_validation_error(pw):
                error = password_validation_error(pw)
            else:
                try:
                    create_user(uid, pw, name, 'executive_org', is_admin=True)
                    return flask.redirect('/login?setup=1')
                except Exception as exc:
                    error = str(exc)

        alert = f'<div class="alert alert-danger py-2 small mb-3">{escape(error)}</div>' if error else ''
        body = f"""<p class="text-center text-muted small mb-3">
        첫 실행입니다. 관리자 계정을 만드세요.
      </p>
      {alert}
      <form method="POST" action="/setup">
        <input type="hidden" name="_csrf_token" value="{csrf_token()}">
        <div class="mb-2">
          <label class="form-label small fw-semibold">아이디</label>
          <input type="text" class="form-control form-control-sm" name="username"
                 placeholder="예: hong.gildong" required>
        </div>
        <div class="mb-2">
          <label class="form-label small fw-semibold">이름</label>
          <input type="text" class="form-control form-control-sm" name="display_name"
                 placeholder="예: 홍길동" required>
        </div>
        <div class="mb-2">
          <label class="form-label small fw-semibold">비밀번호 (12자 이상, 문자 조합)</label>
          <input type="password" class="form-control form-control-sm" name="password" required>
        </div>
        <div class="mb-4">
          <label class="form-label small fw-semibold">비밀번호 확인</label>
          <input type="password" class="form-control form-control-sm" name="password_confirm" required>
        </div>
        <button type="submit" class="btn btn-brand text-white w-100">
          <i class="bi bi-person-check me-1"></i> 관리자 계정 생성
        </button>
      </form>"""
        return html_page('초기 설정', body)

    @server.route('/logout')
    def logout():
        from services.auth import clear_session
        clear_session()
        return flask.redirect('/login')

    @server.route('/change-password', methods=['GET', 'POST'])
    def change_password_page():
        from services.auth import authenticate, change_password, get_current_user, password_validation_error

        user = get_current_user()
        if user is None:
            return flask.redirect('/login')

        error = ''
        if flask.request.method == 'POST':
            require_csrf()
            current_pw = flask.request.form.get('current_password', '')
            pw = flask.request.form.get('password', '')
            pw2 = flask.request.form.get('password_confirm', '')
            if not authenticate(user['user_id'], current_pw):
                error = '현재 비밀번호(임시 비밀번호)가 올바르지 않습니다.'
            elif not pw:
                error = '새 비밀번호를 입력하세요.'
            elif pw != pw2:
                error = '새 비밀번호가 일치하지 않습니다.'
            elif password_validation_error(pw):
                error = password_validation_error(pw)
            elif pw == current_pw:
                error = '기존 비밀번호와 다른 비밀번호를 입력하세요.'
            else:
                change_password(user['user_id'], pw)
                flask.session['must_change_password'] = False
                return flask.redirect('/')

        notice = (
            ''
            if error
            else '<div class="alert alert-warning py-2 small mb-3">'
                 '임시 비밀번호로 로그인하셨습니다. 계속하려면 비밀번호를 새로 설정하세요.</div>'
        )
        alert = f'<div class="alert alert-danger py-2 small mb-3">{escape(error)}</div>' if error else notice
        body = f"""{alert}
    <form method="POST" action="/change-password">
      <input type="hidden" name="_csrf_token" value="{csrf_token()}">
      <div class="mb-2">
        <label class="form-label small fw-semibold">현재 비밀번호(임시 비밀번호)</label>
        <input type="password" class="form-control form-control-sm" name="current_password"
               autocomplete="current-password" required autofocus>
      </div>
      <div class="mb-2">
        <label class="form-label small fw-semibold">새 비밀번호 (12자 이상, 문자 조합)</label>
        <input type="password" class="form-control form-control-sm" name="password"
               autocomplete="new-password" required>
      </div>
      <div class="mb-4">
        <label class="form-label small fw-semibold">새 비밀번호 확인</label>
        <input type="password" class="form-control form-control-sm" name="password_confirm"
               autocomplete="new-password" required>
      </div>
      <button type="submit" class="btn btn-brand text-white w-100">
        <i class="bi bi-key me-1"></i> 비밀번호 설정
      </button>
    </form>"""
        return html_page('비밀번호 변경', body)
