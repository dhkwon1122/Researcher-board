"""
화면 1: 조직별 우수 연구원 비교
"""

import os

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dash_table, html, dcc

dash.register_page(__name__, path='/', name='조직별 비교', title='조직별 우수 연구원 비교')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

METRIC_LABELS = {
    'score': '평가점수',
    'pub_count': '논문 수',
    'patent_count': '특허(등록) 수',
    'leadership_score': '리더십 점수',
}

GRADE_COLOR = {
    '가': '#f5a623',  # 금색 — 최우수
    '나': '#52c41a',  # 초록
    '다': '#1890ff',  # 파랑
    '라': '#8c8c8c',  # 회색
    '마': '#ff4d4f',  # 빨강 — 최하
    '-': '#d9d9d9',
}

RADAR_COLORS = [
    'rgba(74,144,226,0.85)', 'rgba(245,166,35,0.85)', 'rgba(82,196,26,0.85)',
    'rgba(235,87,87,0.85)', 'rgba(155,89,182,0.85)',
]


# ─── 데이터 로드 ────────────────────────────────────────────────────────────

def _load():
    def _r(name):
        return pd.read_csv(os.path.join(DATA_DIR, f'{name}.csv'), encoding='utf-8-sig')

    res = _r('researchers')
    eva = _r('evaluations')
    pub = _r('publications')
    pat = _r('patents')
    lea = _r('leadership')
    return res, eva, pub, pat, lea


def _build_metrics(year: int, org_code: str | None) -> pd.DataFrame:
    res, eva, pub, pat, lea = _load()

    if org_code and org_code != 'ALL':
        res = res[res['org_code'] == org_code].copy()

    # 평가점수
    ev = eva[eva['year'] == year][['researcher_id', 'score', 'grade']]

    # 논문 수 (해당 연도)
    pc = pub[pub['pub_year'] == year].groupby('researcher_id').size().reset_index(name='pub_count')

    # 등록 특허 수 (해당 연도까지 누적)
    pat_reg = pat[(pat['status'] == '등록') & (pat['registration_date'].astype(str).str[:4] <= str(year))]
    ptc = pat_reg.groupby('researcher_id').size().reset_index(name='patent_count')

    # 리더십 점수 (해당 연도, 없으면 직전 년도)
    lea_y = lea[lea['year'] <= year].sort_values('year', ascending=False)
    lea_y = lea_y.drop_duplicates('researcher_id')[['researcher_id', 'overall_score']]
    lea_y = lea_y.rename(columns={'overall_score': 'leadership_score'})

    df = res[['researcher_id', 'name', 'department', 'org_code', 'position']].copy()
    df = df.merge(ev, on='researcher_id', how='left')
    df = df.merge(pc, on='researcher_id', how='left')
    df = df.merge(ptc, on='researcher_id', how='left')
    df = df.merge(lea_y, on='researcher_id', how='left')

    df['pub_count'] = df['pub_count'].fillna(0).astype(int)
    df['patent_count'] = df['patent_count'].fillna(0).astype(int)
    df['score'] = df['score'].fillna(0).round(1)
    df['grade'] = df['grade'].fillna('-')
    df['leadership_score'] = df['leadership_score'].fillna(0).round(1)

    return df


def _normalize_col(series: pd.Series) -> pd.Series:
    mx = series.max()
    if mx == 0:
        return series * 0
    return (series / mx * 100).round(1)


# ─── 레이아웃 ────────────────────────────────────────────────────────────────

def _filter_bar(org_options, year_options):
    return dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label('조직', className='fw-semibold small text-muted mb-1'),
                            dcc.Dropdown(
                                id='org-filter',
                                options=org_options,
                                value='ALL',
                                clearable=False,
                                className='dash-dropdown',
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            dbc.Label('기준 연도', className='fw-semibold small text-muted mb-1'),
                            dcc.Dropdown(
                                id='year-filter',
                                options=year_options,
                                value=year_options[-1]['value'],
                                clearable=False,
                            ),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Label('정렬 기준 지표', className='fw-semibold small text-muted mb-1'),
                            dcc.Dropdown(
                                id='metric-filter',
                                options=[{'label': v, 'value': k} for k, v in METRIC_LABELS.items()],
                                value='score',
                                clearable=False,
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            dbc.Label('상위 N명 (레이더)', className='fw-semibold small text-muted mb-1'),
                            dcc.Dropdown(
                                id='topn-filter',
                                options=[{'label': f'Top {n}', 'value': n} for n in [3, 5, 10]],
                                value=5,
                                clearable=False,
                            ),
                        ],
                        md=2,
                    ),
                ],
                className='g-2',
            )
        ),
        className='mb-3 shadow-sm',
    )


def _kpi_card(icon, label, value_id, color):
    return dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            html.I(className=f'bi {icon}',
                                   style={'fontSize': '2rem', 'color': color}),
                            className='d-flex align-items-center justify-content-center',
                            style={'height': '60px'},
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        [
                            html.P(label, className='text-muted small mb-0'),
                            html.H4(id=value_id, className='fw-bold mb-0', style={'color': color}),
                        ],
                        width=9,
                        className='d-flex flex-column justify-content-center',
                    ),
                ],
                className='g-0',
            )
        ),
        className='shadow-sm h-100',
    )


def layout():
    try:
        res, eva, *_ = _load()
        orgs = [{'label': '전체 조직', 'value': 'ALL'}] + [
            {'label': row['department'], 'value': row['org_code']}
            for _, row in res[['department', 'org_code']].drop_duplicates().sort_values('org_code').iterrows()
        ]
        years = [{'label': str(y), 'value': y} for y in sorted(eva['year'].unique())]
    except Exception:
        orgs = [{'label': '전체 조직', 'value': 'ALL'}]
        years = [{'label': str(y), 'value': y} for y in range(2020, 2025)]

    return html.Div(
        [
            html.H5(
                [html.I(className='bi bi-people-fill me-2 text-primary'), '조직별 우수 연구원 비교'],
                className='fw-bold mb-3 mt-1',
            ),
            _filter_bar(orgs, years),

            # KPI 카드
            dbc.Row(
                [
                    dbc.Col(_kpi_card('bi-star-fill', '평균 평가점수', 'kpi-eval', '#f5a623'), md=3),
                    dbc.Col(_kpi_card('bi-journal-text', '총 논문 수 (해당연도)', 'kpi-pub', '#1890ff'), md=3),
                    dbc.Col(_kpi_card('bi-award-fill', '총 등록 특허 수', 'kpi-patent', '#52c41a'), md=3),
                    dbc.Col(_kpi_card('bi-graph-up-arrow', '평균 리더십 점수', 'kpi-leadership', '#9b59b6'), md=3),
                ],
                className='g-3 mb-3',
            ),

            # 레이더 + 순위 테이블
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.P('상위 연구원 다차원 비교 (레이더)',
                                           className='fw-semibold text-muted small mb-2'),
                                    dcc.Graph(id='radar-chart', style={'height': '420px'},
                                              config={'displayModeBar': False}),
                                ]
                            ),
                            className='shadow-sm h-100',
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.P('연구원 순위 테이블',
                                           className='fw-semibold text-muted small mb-2'),
                                    html.Div(id='ranking-table'),
                                ]
                            ),
                            className='shadow-sm h-100',
                        ),
                        md=6,
                    ),
                ],
                className='g-3 mb-3',
            ),

            # 조직별 비교 바 차트
            dbc.Card(
                dbc.CardBody(
                    [
                        html.P('조직별 지표 비교',
                               className='fw-semibold text-muted small mb-2'),
                        dcc.Graph(id='org-bar-chart', style={'height': '340px'},
                                  config={'displayModeBar': False}),
                    ]
                ),
                className='shadow-sm',
            ),
        ]
    )


# ─── 콜백 ────────────────────────────────────────────────────────────────────

@callback(
    Output('kpi-eval', 'children'),
    Output('kpi-pub', 'children'),
    Output('kpi-patent', 'children'),
    Output('kpi-leadership', 'children'),
    Output('radar-chart', 'figure'),
    Output('ranking-table', 'children'),
    Output('org-bar-chart', 'figure'),
    Input('org-filter', 'value'),
    Input('year-filter', 'value'),
    Input('metric-filter', 'value'),
    Input('topn-filter', 'value'),
)
def update_all(org, year, metric, top_n):
    try:
        df = _build_metrics(year, org)
    except Exception as e:
        empty = go.Figure()
        empty.update_layout(
            annotations=[{'text': f'데이터 로드 실패: {e}', 'showarrow': False,
                           'xref': 'paper', 'yref': 'paper', 'x': 0.5, 'y': 0.5}],
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        )
        return '-', '-', '-', '-', empty, html.Div('데이터를 불러올 수 없습니다.'), empty

    # ── KPI ──
    kpi_eval = f'{df["score"].mean():.1f}점' if not df.empty else '-'
    kpi_pub = f'{int(df["pub_count"].sum())}편'
    kpi_patent = f'{int(df["patent_count"].sum())}건'
    kpi_lead = f'{df["leadership_score"].mean():.1f}점' if not df.empty else '-'

    # ── 순위 정렬 ──
    df_sorted = df.sort_values(metric, ascending=False).reset_index(drop=True)
    df_top = df_sorted.head(top_n)

    # ── 레이더 차트 ──
    radar_dims = ['score', 'pub_count', 'patent_count', 'leadership_score']
    radar_labels = ['평가점수', '논문 수', '특허(등록) 수', '리더십 점수']

    norm_df = df_sorted.copy()
    for col in ['pub_count', 'patent_count']:
        norm_df[col] = _normalize_col(df_sorted[col])

    radar_fig = go.Figure()
    for idx, (_, row) in enumerate(df_top.iterrows()):
        vals = [row[c] for c in radar_dims]
        vals_closed = vals + [vals[0]]
        labels_closed = radar_labels + [radar_labels[0]]
        color = RADAR_COLORS[idx % len(RADAR_COLORS)]
        radar_fig.add_trace(go.Scatterpolar(
            r=vals_closed,
            theta=labels_closed,
            fill='toself',
            fillcolor=color.replace('0.85', '0.15'),
            line=dict(color=color, width=2),
            name=row['name'],
            hovertemplate=(
                f"<b>{row['name']}</b><br>"
                '%{theta}: %{r:.1f}<extra></extra>'
            ),
        ))
    radar_fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=9)),
            angularaxis=dict(tickfont=dict(size=11, color='#444')),
        ),
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=-0.25, xanchor='center', x=0.5),
        margin=dict(l=40, r=40, t=20, b=60),
        paper_bgcolor='rgba(0,0,0,0)',
    )

    # ── 순위 테이블 ──
    grade_badges = {
        '가': dbc.Badge('가', color='warning', className='ms-1'),
        '나': dbc.Badge('나', color='success', className='ms-1'),
        '다': dbc.Badge('다', color='primary', className='ms-1'),
        '라': dbc.Badge('라', color='secondary', className='ms-1'),
        '마': dbc.Badge('마', color='danger', className='ms-1'),
    }
    table_rows = []
    for rank, (_, row) in enumerate(df_sorted.iterrows(), 1):
        table_rows.append(
            html.Tr([
                html.Td(rank, className='text-center fw-bold text-muted'),
                html.Td(row['name'], className='fw-semibold'),
                html.Td(row['position'], className='text-muted small'),
                html.Td([f"{row['score']:.0f}", grade_badges.get(row['grade'], '')]),
                html.Td(str(int(row['pub_count'])), className='text-center'),
                html.Td(str(int(row['patent_count'])), className='text-center'),
                html.Td(f"{row['leadership_score']:.0f}", className='text-center'),
            ])
        )
    ranking_table = dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th('#', className='text-center', style={'width': '40px'}),
                html.Th('이름'),
                html.Th('직급'),
                html.Th('평가점수'),
                html.Th('논문', className='text-center'),
                html.Th('특허', className='text-center'),
                html.Th('리더십', className='text-center'),
            ]), className='table-primary'),
            html.Tbody(table_rows),
        ],
        bordered=False,
        hover=True,
        responsive=True,
        size='sm',
        className='mb-0',
        style={'maxHeight': '380px', 'overflowY': 'auto', 'display': 'block'},
    )

    # ── 조직별 비교 바 차트 ──
    try:
        res_df, eva_df, pub_df, pat_df, lea_df = _load()
        orgs_all = res_df['org_code'].unique()
        bar_data = []
        for oc in sorted(orgs_all):
            df_oc = _build_metrics(year, oc)
            dept_name = res_df[res_df['org_code'] == oc]['department'].iloc[0]
            bar_data.append({
                'department': dept_name,
                'score': df_oc['score'].mean(),
                'pub_count': df_oc['pub_count'].sum(),
                'patent_count': df_oc['patent_count'].sum(),
                'leadership_score': df_oc['leadership_score'].mean(),
            })
        bar_df = pd.DataFrame(bar_data)

        bar_fig = go.Figure()
        colors_map = {
            'score': '#f5a623', 'pub_count': '#1890ff',
            'patent_count': '#52c41a', 'leadership_score': '#9b59b6',
        }
        bar_fig.add_trace(go.Bar(
            x=bar_df['department'],
            y=bar_df[metric],
            marker_color=colors_map.get(metric, '#1890ff'),
            text=bar_df[metric].round(1),
            textposition='outside',
            hovertemplate='%{x}<br>' + METRIC_LABELS[metric] + ': %{y:.1f}<extra></extra>',
        ))
        bar_fig.update_layout(
            xaxis_title=None,
            yaxis_title=METRIC_LABELS[metric],
            yaxis=dict(gridcolor='#eeeeee'),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=40, r=20, t=20, b=60),
            bargap=0.35,
        )
    except Exception:
        bar_fig = go.Figure()

    return kpi_eval, kpi_pub, kpi_patent, kpi_lead, radar_fig, ranking_table, bar_fig
