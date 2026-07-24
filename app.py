import os
import secrets

import dash
import dash_bootstrap_components as dbc
import flask
from dash import Input, Output, callback, dcc, html

from services.data_store import ASSETS_DIR, RAW_DIR

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title='연구원 대시보드',
)

app.server.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

_IMG_EXTS = ('png', 'jpg', 'jpeg')


# ── 사진 서빙 ────────────────────────────────────────────────────────────────
@app.server.route('/photo/<rid>')
def serve_photo(rid):
    rid8 = rid.zfill(8) if rid.isdigit() else None
    if rid8 is None:
        flask.abort(404)
    rid_plain = str(int(rid8))
    candidates = {rid8.lower(), rid_plain.lower()}
    for r in (rid8, rid_plain):
        for ext in _IMG_EXTS:
            path = os.path.join(ASSETS_DIR, 'photos', f'{r}.{ext}')
            if os.path.isfile(path):
                return flask.send_file(path)
    if os.path.isdir(RAW_DIR):
        for fname in os.listdir(RAW_DIR):
            stem, dot, fext = fname.rpartition('.')
            if dot and stem.lower() in candidates and fext.lower() in _IMG_EXTS:
                return flask.send_file(os.path.join(RAW_DIR, fname))
    flask.abort(404)


# ── HTML 템플릿 (로그인 / 초기 설정 공통 골격) ─────────────────────────────
def _html_page(title: str, body: str) -> str:
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


# ── 로그인 ───────────────────────────────────────────────────────────────────
@app.server.route('/login')
def login_page():
    from services.auth import get_current_user, has_any_user
    if get_current_user():
        return flask.redirect('/')
    if not has_any_user():
        return flask.redirect('/setup')

    error = flask.request.args.get('error', '')
    next_url = flask.request.args.get('next', '/')
    setup_ok = flask.request.args.get('setup', '')

    alert = ''
    if error == 'invalid':
        alert = '<div class="alert alert-danger py-2 small mb-3">아이디 또는 비밀번호가 올바르지 않습니다.</div>'
    elif setup_ok:
        alert = '<div class="alert alert-success py-2 small mb-3">계정이 생성되었습니다. 로그인하세요.</div>'

    body = f"""{alert}
    <form method="POST" action="/auth/login">
      <input type="hidden" name="next" value="{next_url}">
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
    return _html_page('로그인', body)


@app.server.route('/auth/login', methods=['POST'])
def auth_login():
    from services.auth import authenticate, set_session
    username = flask.request.form.get('username', '').strip()
    password = flask.request.form.get('password', '')
    next_url = flask.request.form.get('next', '/')
    user = authenticate(username, password)
    if not user:
        return flask.redirect(f'/login?error=invalid&next={next_url}')
    set_session(user)
    return flask.redirect(next_url if next_url.startswith('/') else '/')


# ── 초기 설정 (첫 관리자 계정 생성) ──────────────────────────────────────────
@app.server.route('/setup', methods=['GET', 'POST'])
def setup_page():
    from services.auth import create_user, has_any_user
    if has_any_user():
        return flask.redirect('/login')

    error = ''
    if flask.request.method == 'POST':
        uid = flask.request.form.get('username', '').strip()
        name = flask.request.form.get('display_name', '').strip()
        pw = flask.request.form.get('password', '')
        pw2 = flask.request.form.get('password_confirm', '')
        if not uid or not name or not pw:
            error = '모든 항목을 입력하세요.'
        elif pw != pw2:
            error = '비밀번호가 일치하지 않습니다.'
        elif len(pw) < 8:
            error = '비밀번호는 8자 이상이어야 합니다.'
        else:
            try:
                create_user(uid, pw, name, 'executive_org')
                return flask.redirect('/login?setup=1')
            except Exception as exc:
                error = str(exc)

    alert = f'<div class="alert alert-danger py-2 small mb-3">{error}</div>' if error else ''
    body = f"""<p class="text-center text-muted small mb-3">
        첫 실행입니다. 관리자 계정을 만드세요.
      </p>
      {alert}
      <form method="POST" action="/setup">
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
          <label class="form-label small fw-semibold">비밀번호 (8자 이상)</label>
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
    return _html_page('초기 설정', body)


# ── 로그아웃 ─────────────────────────────────────────────────────────────────
@app.server.route('/logout')
def logout():
    from services.auth import clear_session
    clear_session()
    return flask.redirect('/login')


# ── 인증 미들웨어 ─────────────────────────────────────────────────────────────
_AUTH_EXEMPT_PREFIXES = ('/assets/', '/photo/', '/_dash', '/_reload')
_AUTH_EXEMPT_PATHS = {'/login', '/auth/login', '/logout', '/setup'}


@app.server.before_request
def require_login():
    path = flask.request.path
    if path in _AUTH_EXEMPT_PATHS:
        return None
    if any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES):
        return None
    if not flask.session.get('user_id'):
        if flask.request.content_type and 'application/json' in flask.request.content_type:
            return flask.jsonify({'error': 'unauthorized'}), 401
        return flask.redirect(f'/login?next={path}')
    return None


# ── 네비게이션 바 ─────────────────────────────────────────────────────────────
navbar = dbc.Navbar(
    dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.I(className='bi bi-bar-chart-fill me-2',
                               style={'fontSize': '1.4rem', 'color': '#7eb8f7'}),
                        width='auto',
                    ),
                    dbc.Col(
                        dbc.NavbarBrand('연구원 대시보드', className='fw-bold fs-5 mb-0'),
                        width='auto',
                    ),
                ],
                align='center',
                className='g-0',
            ),
            dbc.Nav(
                [
                    dbc.NavItem(dbc.NavLink(
                        [html.I(className='bi bi-person-badge-fill me-1'), '연구원 프로필'],
                        href='/', active='exact', className='text-white',
                    )),
                    dbc.NavItem(dbc.NavLink(
                        [html.I(className='bi bi-people-fill me-1'), '조직별 비교'],
                        href='/org-comparison', active='exact', className='text-white',
                    )),
                    dbc.NavItem(dbc.NavLink(
                        [html.I(className='bi bi-table me-1'), '연구원 목록'],
                        href='/researcher-list', active='exact', className='text-white',
                    )),
                    # 관리자 메뉴 + 사용자 정보 (콜백으로 갱신)
                    html.Div(id='_navbar-user', className='d-flex align-items-center ms-3'),
                ],
                navbar=True,
                className='ms-auto align-items-center',
            ),
        ],
        fluid=True,
    ),
    color='#1e3a5f',
    dark=True,
    sticky='top',
    className='shadow-sm',
)

app.layout = html.Div(
    [
        navbar,
        dbc.Container(dash.page_container, fluid=True, className='px-4 py-3'),
    ],
    style={'minHeight': '100vh', 'backgroundColor': '#f0f2f5'},
)


@callback(
    Output('_navbar-user', 'children'),
    Input('_pages_location', 'pathname'),
)
def refresh_navbar_user(_):
    from services.auth import can, get_current_user, role_label
    user = get_current_user()
    if not user:
        return []
    items = []
    if can('manage_users'):
        items.append(dbc.NavItem(dbc.NavLink(
            [html.I(className='bi bi-gear me-1'), '관리자'],
            href='/admin', className='text-white small',
        )))
    items += [
        html.Span(
            f"{user['display_name']}  ({role_label(user['role'])})",
            className='text-white-50 small me-2 ms-2',
        ),
        dbc.NavLink(
            [html.I(className='bi bi-box-arrow-right me-1'), '로그아웃'],
            href='/logout', className='text-white small px-0',
            external_link=True,
        ),
    ]
    return items

# WSGI 진입점 (gunicorn app:server 로 구동).
server = app.server

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8501'))
    app.run(host='0.0.0.0', port=port, debug=False)
