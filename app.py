import dash
import dash_bootstrap_components as dbc

from config.settings import load_settings
from web.assets_routes import register_asset_routes
from web.auth_routes import register_auth_routes
from web.layout import build_layout, register_layout_callbacks
from web.security import configure_security


settings = load_settings()
app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title='연구원 대시보드',
)

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

login_limiter = configure_security(app.server, settings.security)
register_asset_routes(app.server)
register_auth_routes(app.server, login_limiter, settings)
register_layout_callbacks()

app.layout = build_layout()

# WSGI 진입점 (gunicorn app:server 로 구동).
server = app.server

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=settings.app.port, debug=False, threaded=True)
