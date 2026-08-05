import os

import dash
import dash_bootstrap_components as dbc
import flask
from dash import dcc, html

from services.data_store import ASSETS_DIR, RAW_DIR

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title='연구원 대시보드',
)

# pages/*.py 콜백은 use_pages=True 스캔 과정에서 자동 등록되지만, 이 모듈은
# 페이지가 아니라 전 탭 공용 컴포넌트라 Dash 인스턴스 생성 이후 직접
# import해서 module-level @callback들을 등록해야 한다(생성 전에 import하면
# 아직 앱이 없어 콜백이 등록되지 않는다).
from components import nl_query_bar  # noqa: E402

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


@app.server.route('/photo/<rid>')
def serve_photo(rid):
    """assets/photos/ 또는 data/raw/ 의 사진을 브라우저에 직접 서빙.
    파일명 대소문자 무관, 8자리 패딩 + 원본 사번 모두 시도.
    """
    rid8 = rid.zfill(8) if rid.isdigit() else None
    if rid8 is None:
        flask.abort(404)
    rid_plain = str(int(rid8))
    candidates = {rid8.lower(), rid_plain.lower()}

    # assets/photos/ 우선 — 정확한 경로 시도
    for r in (rid8, rid_plain):
        for ext in _IMG_EXTS:
            path = os.path.join(ASSETS_DIR, 'photos', f'{r}.{ext}')
            if os.path.isfile(path):
                return flask.send_file(path)

    # data/raw/ — 디렉토리 스캔 (대소문자 무관)
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
                ],
                align='center',
                className='g-0',
            ),
            dbc.Nav(
                [
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
                            [html.I(className='bi bi-share-fill me-1'), '보유 전문성'],
                            href='/researcher-similarity-map',
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
                            [html.I(className='bi bi-file-earmark-check me-1'), '과제 직무/대상자 검증'],
                            href='/jd-reconciliation',
                            active='exact',
                            className='text-white',
                        )
                    ),
                    dbc.NavItem(
                        dbc.NavLink(
                            [html.I(className='bi bi-signpost-split me-1'), 'JOB Market'],
                            href='/job-market',
                            active='exact',
                            className='text-white',
                        )
                    ),
                ],
                navbar=True,
                className='ms-auto',
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
                # 전 탭 공용 자연어 질문 바 — 어느 탭에 있든 항상 보이도록
                # 네비게이션 바로 아래, 페이지 콘텐츠 위에 고정 배치한다
                # (구 "연구원 목록" 탭 전용 AI 검색을 대체).
                nl_query_bar.render(),
                html.Hr(className='mt-1 mb-3'),
                dash.page_container,
            ],
            fluid=True,
            className='px-4 py-3',
        ),
    ],
    style={'minHeight': '100vh', 'backgroundColor': '#f5f5f7'},
)

# WSGI 진입점 (gunicorn app:server 로 구동). Dash 의 내부 Flask 서버.
server = app.server

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8501'))
    app.run(host='0.0.0.0', port=port, debug=False)
