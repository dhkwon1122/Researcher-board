import os
import secrets

import dash
import dash_bootstrap_components as dbc
import flask
from dash import Input, Output, callback, dcc, html

from services.data_store import ASSETS_DIR, RAW_DIR

try:
    from onelogin.saml2.auth import OneLogin_Saml2_Auth
    from onelogin.saml2.utils import OneLogin_Saml2_Utils
    _SAML_AVAILABLE = True
except ImportError:
    _SAML_AVAILABLE = False

# SAML 설정 파일 경로 (saml/settings.json, saml/advanced_settings.json)
SAML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saml')

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


# ── SAML 헬퍼 ────────────────────────────────────────────────────────────────
def _prepare_flask_request(request) -> dict:
    """Flask request 객체를 python3-saml 형식으로 변환.
    리버스 프록시(X-Forwarded-Proto) 환경을 자동으로 감지.
    """
    forwarded_proto = request.headers.get('X-Forwarded-Proto', '')
    is_https = forwarded_proto.lower() == 'https' or request.scheme == 'https'
    return {
        'https': 'on' if is_https else 'off',
        'http_host': request.host,
        'script_name': request.path,
        'get_data': request.args.copy(),
        'post_data': request.form.copy(),
    }


def _init_saml_auth(request) -> 'OneLogin_Saml2_Auth':
    req = _prepare_flask_request(request)
    return OneLogin_Saml2_Auth(req, custom_base_path=SAML_PATH)


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


# ── 로그인 페이지 (SSO 버튼만 표시) ─────────────────────────────────────────
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
                   box-shadow:0 4px 24px rgba(0,0,0,.1); max-width:420px; width:100%; }}
    .btn-sso {{ background-color:#1e3a5f; border-color:#1e3a5f; font-size:1rem; padding:.6rem 1.5rem; }}
    .btn-sso:hover {{ background-color:#163050; border-color:#163050; }}
    .brand-icon {{ font-size:2.4rem; color:#1e3a5f; }}
  </style>
</head>
<body>
  <div class="login-card card p-5 mx-3">
    <div class="text-center mb-4">
      <i class="bi bi-bar-chart-fill brand-icon"></i>
      <h5 class="fw-bold mt-2 mb-1">연구원 대시보드</h5>
      <p class="text-muted small mb-0">피플팀 전용 시스템입니다</p>
    </div>
    {error_block}
    <div class="d-grid mt-2">
      <a href="/saml/sso?next={next_url}" class="btn btn-sso text-white">
        <i class="bi bi-shield-lock-fill me-2"></i>사내 AD SSO 로그인
      </a>
    </div>
    <p class="text-center text-muted small mt-4 mb-0">
      사내 AD 계정으로 자동 인증됩니다.<br>
      접근 권한 문의: IT 보안팀
    </p>
  </div>
</body>
</html>"""

_ERROR_MESSAGES = {
    'saml': ('danger',  'SAML 인증에 실패했습니다. 다시 시도하거나 IT 보안팀에 문의하세요.'),
    'slo':  ('warning', 'SSO 로그아웃 처리 중 오류가 발생했습니다.'),
}


@app.server.route('/login')
def login_page():
    from services.auth import get_current_user
    if get_current_user():
        return flask.redirect('/')
    error = flask.request.args.get('error', '')
    next_url = flask.request.args.get('next', '/')

    if error in _ERROR_MESSAGES:
        color, msg = _ERROR_MESSAGES[error]
        error_block = (
            f'<div class="alert alert-{color} py-2 small">'
            f'<i class="bi bi-exclamation-circle me-1"></i>{msg}'
            f'</div>'
        )
    else:
        error_block = ''

    return _LOGIN_HTML.format(error_block=error_block, next_url=next_url)


# ── SAML SSO 시작 ──────────────────────────────────────────────────────────────
@app.server.route('/saml/sso')
def saml_sso():
    """IdP로 인증 요청 리다이렉트. next 파라미터를 RelayState로 전달."""
    if not _SAML_AVAILABLE:
        return flask.make_response(
            'python3-saml 라이브러리가 설치되지 않았습니다. '
            'pip install python3-saml 을 실행하세요.', 500
        )
    auth = _init_saml_auth(flask.request)
    next_url = flask.request.args.get('next', '/')
    return flask.redirect(auth.login(return_to=next_url))


# ── SAML ACS (Assertion Consumer Service) ────────────────────────────────────
@app.server.route('/saml/acs', methods=['POST'])
def saml_acs():
    """IdP에서 POST로 전달된 SAML Response를 검증하고 세션을 생성."""
    if not _SAML_AVAILABLE:
        return flask.redirect('/login?error=saml')

    auth = _init_saml_auth(flask.request)
    request_id = flask.session.get('AuthNRequestID')
    auth.process_response(request_id=request_id)
    errors = auth.get_errors()

    if errors or not auth.is_authenticated():
        return flask.redirect('/login?error=saml')

    if 'AuthNRequestID' in flask.session:
        del flask.session['AuthNRequestID']

    from services.auth import build_user_from_saml, set_session
    user = build_user_from_saml(auth.get_attributes(), auth.get_nameid())
    set_session(user)

    # SAML 세션 정보 저장 (SLO 에 필요)
    flask.session['samlNameId'] = auth.get_nameid()
    flask.session['samlNameIdFormat'] = auth.get_nameid_format()
    flask.session['samlNameIdNameQualifier'] = auth.get_nameid_nq()
    flask.session['samlNameIdSPNameQualifier'] = auth.get_nameid_spnq()
    flask.session['samlSessionIndex'] = auth.get_session_index()

    # RelayState를 원래 목적지로 사용 (오픈 리다이렉트 방지)
    relay_state = flask.request.form.get('RelayState', '/')
    req_dict = _prepare_flask_request(flask.request)
    self_url = OneLogin_Saml2_Utils.get_self_url(req_dict)
    if relay_state and relay_state != self_url and relay_state.startswith('/'):
        return flask.redirect(relay_state)
    return flask.redirect('/')


# ── SAML SLO 시작 (앱 → IdP) ─────────────────────────────────────────────────
@app.server.route('/saml/slo')
def saml_slo():
    """사용자가 로그아웃 요청 → IdP에 SLO 요청을 전송."""
    if not _SAML_AVAILABLE:
        from services.auth import clear_session
        clear_session()
        return flask.redirect('/login')

    auth = _init_saml_auth(flask.request)
    url = auth.logout(
        name_id=flask.session.get('samlNameId'),
        session_index=flask.session.get('samlSessionIndex'),
        nq=flask.session.get('samlNameIdNameQualifier'),
        name_id_format=flask.session.get('samlNameIdFormat'),
        spnq=flask.session.get('samlNameIdSPNameQualifier'),
    )
    return flask.redirect(url)


# ── SAML SLS (Single Logout Service, IdP → 앱) ───────────────────────────────
@app.server.route('/saml/sls', methods=['GET', 'POST'])
def saml_sls():
    """IdP에서 전달된 로그아웃 응답을 처리하고 세션을 삭제."""
    if not _SAML_AVAILABLE:
        flask.session.clear()
        return flask.redirect('/login')

    auth = _init_saml_auth(flask.request)
    request_id = flask.session.get('LogoutRequestID')

    def _clear():
        flask.session.clear()

    url = auth.process_slo(request_id=request_id, delete_session_cb=_clear)
    errors = auth.get_errors()

    if not errors:
        return flask.redirect(url) if url else flask.redirect('/login')
    return flask.redirect('/login?error=slo')


# ── SP 메타데이터 엔드포인트 ─────────────────────────────────────────────────
@app.server.route('/saml/metadata')
def saml_metadata():
    """SP 메타데이터 XML 반환. IdP(AD FS)에 SP 등록 시 이 URL을 제출."""
    if not _SAML_AVAILABLE:
        return flask.make_response('python3-saml 미설치', 500)

    auth = _init_saml_auth(flask.request)
    settings = auth.get_settings()
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)

    if not errors:
        resp = flask.make_response(metadata, 200)
        resp.headers['Content-Type'] = 'text/xml'
        return resp
    return flask.make_response(', '.join(errors), 500)


# ── 로그아웃 진입점 ──────────────────────────────────────────────────────────
@app.server.route('/logout')
def logout():
    """네비게이션 바의 로그아웃 링크 → SAML SLO 흐름으로 위임."""
    return flask.redirect('/saml/slo')


# ── 인증 미들웨어 ─────────────────────────────────────────────────────────────
# /saml/* 전체를 허용 — SSO, ACS, SLO, SLS, metadata 모두 인증 전에 접근 가능해야 함
_AUTH_EXEMPT_PREFIXES = ('/assets/', '/photo/', '/_dash', '/_reload', '/saml/')
_AUTH_EXEMPT_PATHS = {'/login', '/logout'}


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
