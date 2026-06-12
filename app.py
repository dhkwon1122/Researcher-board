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

_IMG_EXTS = ('png', 'jpg', 'jpeg')


@app.server.route('/photo/<rid>')
def serve_photo(rid):
    """data/raw/ 또는 assets/photos/ 의 사진을 브라우저에 직접 서빙."""
    if not rid.replace('_', '').isdigit():
        flask.abort(404)
    rid8 = rid.zfill(8)

    # assets/photos/ 우선
    for ext in _IMG_EXTS:
        path = os.path.join(ASSETS_DIR, 'photos', f'{rid8}.{ext}')
        if os.path.isfile(path):
            return flask.send_file(path)

    # data/raw/ — 파일명 대소문자 무관 스캔
    if os.path.isdir(RAW_DIR):
        for fname in os.listdir(RAW_DIR):
            stem, _, fext = fname.rpartition('.')
            if stem == rid8 and fext.lower() in _IMG_EXTS:
                return flask.send_file(os.path.join(RAW_DIR, fname))

    flask.abort(404)

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
                ],
                navbar=True,
                className='ms-auto',
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
        dbc.Container(
            dash.page_container,
            fluid=True,
            className='px-4 py-3',
        ),
    ],
    style={'minHeight': '100vh', 'backgroundColor': '#f0f2f5'},
)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8050, debug=False)
