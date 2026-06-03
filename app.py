import dash
import dash_bootstrap_components as dbc
from dash import html, dcc

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title='연구원 대시보드',
)

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
