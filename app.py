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

# pages/*.py 콜백은 use_pages=True 스캔 과정에서 자동 등록되지만, 이 모듈들은
# 페이지가 아니라 전 탭 공용 컴포넌트라 Dash 인스턴스 생성 이후 직접
# import해서 module-level @callback들을 등록해야 한다(생성 전에 import하면
# 아직 앱이 없어 콜백이 등록되지 않는다).
from components import feedback_modal, nl_query_bar  # noqa: E402

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
                        [html.I(className='bi bi-people-fill me-1'), '조직별 비교'],
                        href='/org-comparison', active='exact', className='text-white',
                    )),
                    dbc.NavItem(dbc.NavLink(
                        [html.I(className='bi bi-signpost-split me-1'), 'JOB Market'],
                        href='/job-market', active='exact', className='text-white',
                    )),
                    # '과제 직무/대상자 검증' NavLink는 pages/jd_reconciliation.py의
                    # _FEATURE_HIDDEN(기능 준비 중) 동안 제거됨(data/processed/
                    # CLAUDE.md에 재오픈 방법 기록).
                    # 관리자 메뉴 + 사용자 정보 (콜백으로 갱신)
                    html.Div(id='_navbar-user', className='d-flex align-items-center ms-3'),
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
                # AI 검색(자연어 질문 바) — 레이아웃은 네비게이션 바로 아래에
                # 한 번만 두되(모든 탭에서 같은 컴포넌트/콜백 상태 유지),
                # "연구원 명단" 탭(/researcher-list)에서만 보이도록 아래
                # _toggle_nl_query_bar 콜백이 pathname에 따라 숨긴다
                # (사용자 요청 — 다른 탭에서는 노출 안 함).
                html.Div(nl_query_bar.render(), id='_nl-query-bar-wrap'),
                html.Hr(className='mt-1 mb-3'),
                dash.page_container,
            ],
            fluid=True,
            className='px-4 py-3',
        ),
    ],
    style={'minHeight': '100vh', 'backgroundColor': '#f5f5f7'},
)


@callback(
    Output('_nl-query-bar-wrap', 'style'),
    Input('_pages_location', 'pathname'),
)
def _toggle_nl_query_bar(pathname):
    return {} if pathname == '/researcher-list' else {'display': 'none'}


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
        ),
    ]
    return items

# WSGI 진입점 (gunicorn app:server 로 구동).
server = app.server

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8501'))
    # threaded=True: 기본 Werkzeug 개발 서버는 싱글 스레드라 요청 하나(UMAP 계산,
    # LLM 호출 등 오래 걸리는 작업)가 서버 전체를 붙잡아 다른 사용자의 요청이
    # 밀리거나 타임아웃으로 "연결 끊김"처럼 보이는 문제가 있었다 — 개인 데스크탑에서
    # 소수 인원 베타테스트하는 용도로는 이 정도로 충분(별도 의존성/OS 제약 없음).
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
