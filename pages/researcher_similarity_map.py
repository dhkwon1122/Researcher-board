"""화면: 연구원 전문성 유사도 지도 (BGE-M3 임베딩 UMAP 2D 시각화)"""

import dash
import dash_bootstrap_components as dbc
import plotly.express as px
from dash import Input, Output, callback, dcc, html

from services.similarity_map import load_similarity_map

dash.register_page(__name__, path='/researcher-similarity-map', name='유사도 지도',
                    title='연구원 전문성 유사도 지도')


def _missing_data_alert() -> dbc.Alert:
    return dbc.Alert(
        [
            '유사도 지도를 표시할 데이터가 없습니다. 아래 순서로 먼저 실행하세요.',
            html.Ul([
                html.Li('python pipeline/process_researcher_expertise.py'),
                html.Li('python pipeline/process_researcher_similarity.py '
                        '(또는 process_project_researcher_fit.py — 둘 다 임베딩 캐시를 채웁니다)'),
            ], className='mb-0 mt-2'),
        ],
        color='warning', className='mt-3',
    )


def layout(**_kwargs):
    df, missing = load_similarity_map()
    if df.empty or 'x' not in df.columns:
        return _missing_data_alert()

    df = df.copy()
    df['strength_fields_str'] = df['strength_fields'].apply(lambda v: ', '.join(v) if v else '-')
    df['strength_keywords_str'] = df['strength_keywords'].apply(lambda v: ', '.join(v) if v else '-')
    df['label'] = df['researcher_id'] + ' ' + df['name']

    fig = px.scatter(
        df, x='x', y='y', color='department',
        hover_name='label',
        hover_data={
            'org_code': True, 'strength_fields_str': True, 'strength_keywords_str': True,
            'x': False, 'y': False, 'department': False,
        },
        custom_data=['researcher_id'],
        labels={
            'org_code': '과제/파트', 'strength_fields_str': '강점 분야', 'strength_keywords_str': '강점 키워드',
            'department': '플랫폼/팀',
        },
    )
    fig.update_traces(marker=dict(size=11, opacity=0.85, line=dict(width=1, color='white')))
    fig.update_layout(
        height=680,
        legend_title_text='플랫폼/팀',
        xaxis_title=None, yaxis_title=None,
        xaxis=dict(showticklabels=False, zeroline=False, showgrid=False),
        yaxis=dict(showticklabels=False, zeroline=False, showgrid=False),
        margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor='white',
    )

    missing_note = (
        dbc.Alert(
            f'임베딩 캐시가 없어 지도에서 제외된 연구원 {missing}명 — '
            'process_researcher_similarity.py를 실행하면 함께 표시됩니다.',
            color='secondary', className='mb-3',
        )
        if missing else None
    )

    return html.Div([
        html.H4('연구원 전문성 유사도 지도', className='mb-1'),
        html.P(
            'BGE-M3 임베딩(1024차원)을 UMAP으로 2D에 투영한 지도입니다 — 가까이 모인 점일수록 '
            '실제 보유 전문성이 유사합니다(과제명과 무관). 점을 클릭하면 해당 연구원 프로필로 이동합니다.',
            className='text-muted small mb-3',
        ),
        missing_note,
        dbc.Card(
            dbc.CardBody(
                dcc.Graph(id='similarity-map-graph', figure=fig, config={'displayModeBar': False}),
            ),
        ),
        dcc.Location(id='similarity-map-url', refresh=True),
    ])


@callback(
    Output('similarity-map-url', 'href'),
    Input('similarity-map-graph', 'clickData'),
    prevent_initial_call=True,
)
def _go_to_profile(click_data):
    if not click_data:
        return dash.no_update
    rid = click_data['points'][0]['customdata'][0]
    return f'/researcher-profile?id={rid}'
