from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html, no_update

from components import feedback_modal


def build_layout():
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
                        html.Div(id='_navbar-user', className='d-flex align-items-center ms-3'),
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

    return html.Div(
        [
            navbar,
            dbc.Container(
                [dash.page_container],
                fluid=True,
                className='px-4 py-3',
            ),
        ],
        style={'minHeight': '100vh', 'backgroundColor': '#f5f5f7'},
    )


def register_layout_callbacks() -> None:
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
