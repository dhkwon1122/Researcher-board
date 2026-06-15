import os
import secrets

import dash
import dash_bootstrap_components as dbc
import flask
from dash import Input, Output, callback, dcc, html

from services.data_store import ASSETS_DIR, RAW_DIR

# ── Flask/Dash 앱 초기화 ──────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title='연구원 대시보드',
)

# 세션 암호화 키 (운영 시 FLASK_SECRET_KEY 환경변수로 고정값 설정 필수)
app.server.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

_IMG_EXTS = ('png', 'jpg', 'jpeg')

# ── 사진 서빙 라우트 ──────────────────────────────────────────────────────────
@app.server.route('/photo/<rid>')
def serve_photo(rid):
    """assets/photos/ 또는 data/raw/ 의 사진을 브라우저에 직접 서빙."""
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


# ── 로그인 페이지 HTML 템플릿 ─────────────────────────────────────────────────
_LOGIN_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>로그인 — 연구원 대시보드</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
  <style>
    body {{ background:#f0f2f5; min-height:100vh;
            display:flex; align-items:center; justify-content:center; }}
    .login-card {{ border:none; border-radius:12px;
                   box-shadow:0 4px 24px rgba(0,0,0,.1); max-width:400px; width:100%; }}
    .btn-primary {{ background-color:#1e3a5f; border-color:#1e3a5f; }}
    .btn-primary:hover {{ background-color:#163050; border-color:#163050; }}
    .brand-icon {{ font-size:2.4rem; color:#1e3a5f; }}
  </style>
</head>
<body>
  <div class="login-card card p-4 mx-3">
    <div class="text-center mb-4">
      <i class="bi bi-bar-chart-fill brand-icon"></i>
      <h5 class="fw-bold mt-2 mb-0">연구원 대시보드</h5>
      <p class="text-muted small mt-1 mb-0">사내 AD 계정으로 로그인하세요</p>
    </div>
    {error_block}
    <form method="POST" action="/auth/login">
      <input type="hidden" name="next" value="{next_url}">
      <div class="mb-3">
        <label class="form-label small fw-semibold">AD 계정 (사번)</label>
        <div class="input-group">
          <span class="input-group-text"><i class="bi bi-person"></i></span>
          <input type="text" class="form-control" name="username"
                 placeholder="AD 계정명 입력" autocomplete="username" autofocus required>
        </div>
      </div>
      <div class="mb-4">
        <label class="form-label small fw-semibold">비밀번호</label>
        <div class="input-group">
          <span class="input-group-text"><i class="bi bi-lock"></i></span>
          <input type="password" class="form-control" name="password"
                 placeholder="비밀번호 입력" autocomplete="current-password" required>
        </div>
      </div>
      <button type="submit" class="btn btn-primary w-100">
        <i class="bi bi-box-arrow-in-right me-1"></i> 로그인
      </button>
    </form>
  </div>
</body>
</html>"""


@app.server.route('/login')
def login_page():
    from services.auth import get_current_user
    if get_current_user():
        return flask.redirect('/')
    error = flask.request.args.get('error', '')
    next_url = flask.request.args.get('next', '/')
    if error == 'invalid':
        error_block = (
            '<div class="alert alert-danger py-2 small">'
            '<i class="bi bi-exclamation-circle me-1"></i>'
            'AD 계정 또는 비밀번호가 올바르지 않습니다.'
            '</div>'
        )
    elif error == 'server':
        error_block = (
            '<div class="alert alert-warning py-2 small">'
            '<i class="bi bi-exclamation-triangle me-1"></i>'
            'AD 서버에 연결할 수 없습니다. 관리자에게 문의하세요.'
            '</div>'
        )
    else:
        error_block = ''
    return _LOGIN_HTML.format(error_block=error_block, next_url=next_url)


@app.server.route('/auth/login', methods=['POST'])
def auth_login():
    from services.auth import authenticate, set_session
    username = flask.request.form.get('username', '').strip()
    password = flask.request.form.get('password', '')
    next_url = flask.request.form.get('next', '/')

    user = authenticate(username, password)
    if user is None:
        # ldap3 미설치 또는 서버 연결 실패와 단순 인증 실패를 구분하기 어려우므로
        # 현재는 동일한 에러 메시지 표시
        return flask.redirect(
            f'/login?error=invalid&next={flask.request.form.get("next", "/")}'
        )

    set_session(user)
    return flask.redirect(next_url if next_url.startswith('/') else '/')


@app.server.route('/logout')
def logout():
    from services.auth import clear_session
    clear_session()
    return flask.redirect('/login')


# ── 인증 미들웨어 ─────────────────────────────────────────────────────────────
_AUTH_EXEMPT_PREFIXES = ('/assets/', '/photo/', '/_dash', '/_reload')
_AUTH_EXEMPT_PATHS = {'/login', '/auth/login', '/logout'}


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
                    dbc.NavItem(
                        dbc.NavLink(
                            [html.I(className='bi bi-people-fill me-1'), '조직별 비교'],
                            href='/',
                            active='exact',
                            className='text-white',
                        )
                    ),
                    dbc.NavItem(
                        dbc.NavLink(
                            [html.I(className='bi bi-person-badge-fill me-1'), '연구원 프로필'],
                            href='/researcher-profile',
                            active='exact',
                            className='text-white',
                        )
                    ),
                    dbc.NavItem(
                        dbc.NavLink(
                            [html.I(className='bi bi-table me-1'), '연구원 목록'],
                            href='/researcher-list',
                            active='exact',
                            className='text-white',
                        )
                    ),
                    # 사용자 정보 / 로그아웃 (콜백으로 갱신)
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
        dcc.Location(id='_auth-location', refresh=False),
        navbar,
        dbc.Container(
            dash.page_container,
            fluid=True,
            className='px-4 py-3',
        ),
    ],
    style={'minHeight': '100vh', 'backgroundColor': '#f0f2f5'},
)


@callback(
    Output('_navbar-user', 'children'),
    Input('_auth-location', 'pathname'),
)
def refresh_navbar_user(_):
    from services.auth import get_current_user, role_label
    user = get_current_user()
    if not user:
        return []
    label = role_label(user['role'])
    return [
        html.Span(
            f"{user['display_name']}  ({label})",
            className='text-white-50 small me-3',
        ),
        dbc.NavLink(
            [html.I(className='bi bi-box-arrow-right me-1'), '로그아웃'],
            href='/logout',
            className='text-white small px-0',
        ),
    ]

# WSGI 진입점 (gunicorn app:server 로 구동).
server = app.server

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8501'))
    app.run(host='0.0.0.0', port=port, debug=False)
