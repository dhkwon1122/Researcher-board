import os
import secrets
from html import escape

import dash
import dash_bootstrap_components as dbc
import flask
from dash import Input, Output, callback, dcc, html, no_update

from services.data_store import ASSETS_DIR, PHOTO_DIR, RAW_DIR

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title='연구원 대시보드',
)


def _get_or_create_secret_key() -> str:
    """Flask 세션 서명용 비밀키. FLASK_SECRET_KEY 환경변수가 있으면 그 값을
    쓰고, 없으면 config/.flask_secret_key 에 한 번 생성해 저장한 뒤 재사용한다.

    gunicorn --workers 2 처럼 워커가 여러 개면 각 워커가 이 모듈을 독립적으로
    import 한다 — 매번 secrets.token_hex()로 새 키를 만들면 워커마다 키가
    달라져, 로그인 응답을 처리한 워커가 서명한 세션 쿠키를 다른 워커가 검증하지
    못해(무작위로 요청이 이 워커 저 워커로 분산되므로) 로그인 직후 다시
    로그아웃 상태로 튕기는 것처럼 보인다. 파일에 고정해두면 모든 워커가 같은
    키를 쓴다. 파일 생성은 os.O_EXCL로 원자적으로 시도해, 여러 워커가 거의
    동시에 뜨더라도 하나만 파일을 쓰고 나머지는 그 값을 읽는다."""
    env_key = os.environ.get('FLASK_SECRET_KEY', '').strip()
    if env_key:
        return env_key

    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', '.flask_secret_key')
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


app.server.secret_key = _get_or_create_secret_key()
app.server.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', 'false').lower()
    in ('1', 'true', 'yes', 'on'),
    MAX_CONTENT_LENGTH=int(os.environ.get('MAX_CONTENT_LENGTH', str(10 * 1024 * 1024))),
)

# pages/*.py 콜백은 use_pages=True 스캔 과정에서 자동 등록되지만, 이 모듈은
# 페이지가 아니라 전 탭 공용 컴포넌트라 Dash 인스턴스 생성 이후 직접
# import해서 module-level @callback들을 등록해야 한다(생성 전에 import하면
# 아직 앱이 없어 콜백이 등록되지 않는다).
from components import feedback_modal  # noqa: E402

app.index_string = '''<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>'''

_IMG_EXTS = ('png', 'jpg', 'jpeg')


# ── 사진 서빙 ────────────────────────────────────────────────────────────────
@app.server.route('/photo/<rid>')
def serve_photo(rid):
    rid8 = rid.zfill(8) if rid.isdigit() else None
    if rid8 is None:
        flask.abort(404)
    rid_plain = str(int(rid8))
    candidates = {rid8.lower(), rid_plain.lower()}
    # 파일명·확장자 대소문자 무관하게 찾는다(예: 00000001.JPG) — 대소문자를
    # 구분하는 리눅스 파일시스템에서 os.path.isfile('...jpg')로 직접 조회하면
    # 실제 확장자가 대문자(.JPG)인 파일은 못 찾으므로, 디렉토리 목록을 읽어
    # 소문자로 비교한다.
    for base_dir in (PHOTO_DIR, os.path.join(ASSETS_DIR, 'photos'), RAW_DIR):
        if not os.path.isdir(base_dir):
            continue
        for fname in os.listdir(base_dir):
            stem, dot, fext = fname.rpartition('.')
            if dot and stem.lower() in candidates and fext.lower() in _IMG_EXTS:
                return flask.send_file(os.path.join(base_dir, fname))
    flask.abort(404)


_RAW_IMAGE_ALLOWLIST = {'등급 개요.png', 'lv 개요.png'}


@app.server.route('/raw-image/<path:filename>')
def serve_raw_image(filename):
    """data/raw/ 아래 안내용 이미지(등급/Lv 개요 등)를 서빙. 허용 목록에 있는
    파일명만 응답해 임의 경로 접근을 막는다."""
    if filename not in _RAW_IMAGE_ALLOWLIST:
        flask.abort(404)
    path = os.path.join(RAW_DIR, filename)
    if not os.path.isfile(path):
        flask.abort(404)
    return flask.send_file(path)


def _safe_next_url(raw: str) -> str:
    """로그인 후 이동할 경로를 검증한다. '/'로 시작하되 '//'나 '/\\'로 시작하면
    브라우저가 스킴 상대(protocol-relative) URL로 해석해 외부 사이트로 열린
    리다이렉트(open redirect)가 될 수 있어 함께 거른다."""
    raw = (raw or '').strip()
    if raw.startswith('/') and not raw.startswith(('//', '/\\')):
        return raw
    return '/'


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
    next_url = _safe_next_url(flask.request.args.get('next', '/'))
    setup_ok = flask.request.args.get('setup', '')

    alert = ''
    if error == 'invalid':
        alert = '<div class="alert alert-danger py-2 small mb-3">아이디 또는 비밀번호가 올바르지 않습니다.</div>'
    elif setup_ok:
        alert = '<div class="alert alert-success py-2 small mb-3">계정이 생성되었습니다. 로그인하세요.</div>'

    body = f"""{alert}
    <form method="POST" action="/auth/login">
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
    return _html_page('로그인', body)


@app.server.route('/auth/login', methods=['POST'])
def auth_login():
    from urllib.parse import quote

    from services.auth import authenticate, set_session
    username = flask.request.form.get('username', '').strip()
    password = flask.request.form.get('password', '')
    next_url = _safe_next_url(flask.request.form.get('next', '/'))
    user = authenticate(username, password)
    if not user:
        return flask.redirect(f'/login?error=invalid&next={quote(next_url)}')
    set_session(user)
    return flask.redirect(next_url)


# ── 초기 설정 (첫 관리자 계정 생성) ──────────────────────────────────────────
@app.server.route('/setup', methods=['GET', 'POST'])
def setup_page():
    from services.auth import create_user, has_any_user
    # PostgreSQL을 사용하는 운영 배포에서는 DB 장애/초기화 직후 외부 사용자가
    # 첫 관리자 계정을 선점하지 못하도록 웹 초기 설정을 기본 차단한다. 최초
    # 계정은 scripts/bulk_create_users.py로 만들고, 정말 필요한 경우에만
    # ENABLE_WEB_SETUP=true를 일시적으로 사용한다.
    if os.environ.get('DATABASE_URL', '').strip() and os.environ.get(
            'ENABLE_WEB_SETUP', 'false').lower() not in ('1', 'true', 'yes', 'on'):
        flask.abort(403)
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
                # manage_users는 역할이 아니라 계정별 is_admin으로만 부여되므로
                # (services/auth.py, config/auth_config.py 참고) 첫 계정에는
                # 여기서 명시적으로 관리자 권한을 줘야 한다 — 안 그러면 아무도
                # /admin에 접근하지 못해 이후 관리자를 지정할 방법이 없어진다.
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


# ── 비밀번호 변경 (일괄 계정 생성으로 만든 임시 비밀번호 강제 교체) ───────────
# scripts/bulk_create_users.py 로 만든 계정은 must_change_password=True 상태로
# 시작한다 — 로그인은 되지만 아래 require_login 미들웨어가 이 화면 외의 다른
# 페이지로 못 가게 막는다. 여기서 새 비밀번호를 설정하면 그 상태가 풀린다.
@app.server.route('/change-password', methods=['GET', 'POST'])
def change_password_page():
    from services.auth import authenticate, change_password, get_current_user

    user = get_current_user()
    if user is None:
        return flask.redirect('/login')

    error = ''
    if flask.request.method == 'POST':
        current_pw = flask.request.form.get('current_password', '')
        pw = flask.request.form.get('password', '')
        pw2 = flask.request.form.get('password_confirm', '')
        if not authenticate(user['user_id'], current_pw):
            error = '현재 비밀번호(임시 비밀번호)가 올바르지 않습니다.'
        elif not pw:
            error = '새 비밀번호를 입력하세요.'
        elif pw != pw2:
            error = '새 비밀번호가 일치하지 않습니다.'
        elif len(pw) < 8:
            error = '비밀번호는 8자 이상이어야 합니다.'
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
    alert = f'<div class="alert alert-danger py-2 small mb-3">{error}</div>' if error else notice
    body = f"""{alert}
    <form method="POST" action="/change-password">
      <div class="mb-2">
        <label class="form-label small fw-semibold">현재 비밀번호(임시 비밀번호)</label>
        <input type="password" class="form-control form-control-sm" name="current_password"
               autocomplete="current-password" required autofocus>
      </div>
      <div class="mb-2">
        <label class="form-label small fw-semibold">새 비밀번호 (8자 이상)</label>
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
    return _html_page('비밀번호 변경', body)


# ── 인증 미들웨어 ─────────────────────────────────────────────────────────────
_AUTH_EXEMPT_PREFIXES = ('/assets/',)
_AUTH_EXEMPT_PATHS = {'/login', '/auth/login', '/logout', '/setup'}
_PASSWORD_CHANGE_PATH = '/change-password'


@app.server.before_request
def require_login():
    path = flask.request.path
    if path in _AUTH_EXEMPT_PATHS:
        return None
    if any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES):
        return None
    # Dash 레이아웃/의존성/콜백 엔드포인트도 반드시 세션 인증을 통과해야 한다.
    # 로그인 페이지는 순수 Flask HTML이므로 비로그인 상태에서 /_dash를 열어둘
    # 이유가 없다. API 요청에는 redirect HTML 대신 명시적인 401/403을 반환한다.
    is_json = path.startswith('/_dash') or (
        flask.request.content_type and 'application/json' in flask.request.content_type
    )
    if not flask.session.get('user_id'):
        if is_json:
            return flask.jsonify({'error': 'unauthorized'}), 401
        return flask.redirect(f'/login?next={path}')
    if flask.session.get('must_change_password') and path != _PASSWORD_CHANGE_PATH:
        if is_json:
            return flask.jsonify({'error': 'password_change_required'}), 403
        return flask.redirect(_PASSWORD_CHANGE_PATH)
    return None


# ── 네비게이션 바 ─────────────────────────────────────────────────────────────
navbar = dbc.Navbar(
    dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.I(className='bi bi-bar-chart-fill me-2',
                               style={'fontSize': '1.4rem', 'color': '#0071e3'}),
                        width='auto',
                    ),
                    dbc.Col(
                        dbc.NavbarBrand('연구원 대시보드', className='fw-bold fs-5 mb-0'),
                        width='auto',
                    ),
                    dbc.Col(feedback_modal.render(), width='auto'),
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
                        [html.I(className='bi bi-share-fill me-1'), '보유 전문성'],
                        href='/researcher-similarity-map', active='exact', className='text-white',
                    )),
                    dbc.NavItem(dbc.NavLink(
                        [html.I(className='bi bi-table me-1'), '연구원 명단'],
                        href='/researcher-list', active='exact', className='text-white',
                    )),
                    dbc.NavItem(dbc.NavLink(
                        [html.I(className='bi bi-signpost-split me-1'), 'JOB Market'],
                        href='/job-market', active='exact', className='text-white',
                    )),
                    # '조직별 비교'/'과제 직무/대상자 검증' NavLink는 각각
                    # pages/org_comparison.py, pages/jd_reconciliation.py의
                    # _FEATURE_HIDDEN(기능 준비 중) 동안 제거됨(data/processed/
                    # CLAUDE.md에 재오픈 방법 기록).
                    # 관리자 메뉴 + 사용자 정보 (콜백으로 갱신)
                    html.Div(id='_navbar-user', className='d-flex align-items-center ms-3'),
                    # '로그아웃'은 /logout이 Dash 페이지가 아니라 순수 Flask
                    # 라우트라, 일반 <a href> 클릭을 Dash 페이지 라우터가 가로채면
                    # (page_registry에 없는 경로라) 404로 렌더링돼버린다. 대신
                    # 버튼 클릭 → 이 Location의 href를 콜백으로 채워
                    # refresh=True로 진짜 브라우저 이동을 강제한다(연구원 명단/
                    # 프로필 화면 이동과 동일한 패턴).
                    dcc.Location(id='logout-redirect', refresh=True),
                ],
                navbar=True,
                className='ms-auto align-items-center',
            ),
        ],
        fluid=True,
    ),
    color='#1d1d1f',
    dark=True,
    sticky='top',
    className='app-navbar',
)

app.layout = html.Div(
    [
        navbar,
        dbc.Container(
            [
                dash.page_container,
            ],
            fluid=True,
            className='px-4 py-3',
        ),
    ],
    style={'minHeight': '100vh', 'backgroundColor': '#f5f5f7'},
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
            id='navbar-logout-link',
            href='#', n_clicks=0, className='text-white small px-0',
            style={'cursor': 'pointer'},
        ),
    ]
    return items


@callback(
    Output('logout-redirect', 'href'),
    Input('navbar-logout-link', 'n_clicks'),
    prevent_initial_call=True,
)
def do_logout(n_clicks):
    if not n_clicks:
        return no_update
    return '/logout'


# WSGI 진입점 (gunicorn app:server 로 구동).
server = app.server

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8501'))
    # threaded=True: 기본 Werkzeug 개발 서버는 싱글 스레드라 요청 하나(UMAP 계산,
    # LLM 호출 등 오래 걸리는 작업)가 서버 전체를 붙잡아 다른 사용자의 요청이
    # 밀리거나 타임아웃으로 "연결 끊김"처럼 보이는 문제가 있었다 — 개인 데스크탑에서
    # 소수 인원 베타테스트하는 용도로는 이 정도로 충분(별도 의존성/OS 제약 없음).
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
