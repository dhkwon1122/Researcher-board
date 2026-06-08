import base64
import mimetypes
import os

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import html

from services.data_store import RAW_DIR

DEGREE_ORDER = ['박사', '석사', '학사', '전문대', '고교']
GRADE_COLOR = {
    '가': '#f5a623',
    '나': '#52c41a',
    '다': '#1890ff',
    '라': '#8c8c8c',
    '마': '#ff4d4f',
    '-': '#aaa',
}
TRANSFER_BADGE = {
    '부서발령': 'primary',
    '프로젝트파견': 'success',
    '해외파견': 'info',
    '공동연구': 'secondary',
}
LEADERSHIP_DIMS = ['미래통찰', '성과창출', '몰입촉진', '인재육성', '자기관리', '저해행동']


def avatar(name: str, size: int = 88):
    initial = name[0] if name else '?'
    return html.Div(
        initial,
        style={
            'width': f'{size}px', 'height': f'{size}px', 'borderRadius': '50%',
            'backgroundColor': '#1e3a5f', 'color': 'white',
            'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center',
            'fontSize': f'{int(size * 0.45)}px', 'fontWeight': 'bold',
        },
    )


def photo_block(rid: str, name: str, row=None, current_year: int = 2026):
    photo_el = None
    for ext in ('png', 'jpg', 'jpeg'):
        photo_file = os.path.join(RAW_DIR, f'{rid}.{ext}')
        if os.path.exists(photo_file):
            mime = mimetypes.guess_type(photo_file)[0] or f'image/{ext}'
            with open(photo_file, 'rb') as file:
                encoded = base64.b64encode(file.read()).decode('utf-8')
            photo_el = html.Img(
                src=f'data:{mime};base64,{encoded}',
                style={'width': '100%', 'maxHeight': '200px',
                       'objectFit': 'contain', 'borderRadius': '8px',
                       'display': 'block'},
            )
            break

    sub_lines = []
    if row is not None:
        def _int(v, default):
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        birth_year = _int(row.get('birth_year'), current_year - 30)
        hire_year  = _int(row.get('hire_year'),  current_year)
        age        = current_year - birth_year
        tenure     = current_year - hire_year
        gender     = str(row.get('gender', '')).strip()
        position   = str(row.get('position', '')).strip()

        line1 = f'{name}({gender}/{age}세)' if gender else f'{name}({age}세)'
        line2 = f'{position}-{tenure}({tenure:.1f}년)' if position else f'{tenure:.1f}년 근속'

        sub_lines = [
            html.P(line1, className='fw-bold mt-2 mb-0 text-center small'),
            html.P(line2, className='text-muted text-center mb-0',
                   style={'fontSize': '0.78rem'}),
        ]
    else:
        sub_lines = [html.P(name, className='fw-bold mt-2 mb-0 text-center small')]

    return [photo_el or avatar(name, size=90)] + sub_lines


def basic_info_block(row, current_year: int):
    def _int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    birth_year = _int(row.get('birth_year'), current_year - 30)
    hire_year = _int(row.get('hire_year'), current_year)
    age = current_year - birth_year
    tenure = current_year - hire_year

    return html.Table(
        html.Tbody([
            html.Tr([
                html.Td(label, className='text-muted pe-2',
                        style={'fontSize': '0.78rem', 'fontWeight': '600',
                               'whiteSpace': 'nowrap', 'verticalAlign': 'top'}),
                html.Td(value, style={'fontSize': '0.8rem'}),
            ])
            for label, value in [
                ('성별', str(row.get('gender', ''))),
                ('나이', f'{age}세'),
                ('직급', str(row.get('position', ''))),
                ('직급연차', f'{tenure}년차'),
                ('근속', f'{tenure}년'),
            ]
        ]),
        className='w-100 mb-0',
    )


def education_block(edu_df: pd.DataFrame, rid: str):
    edu_rows = edu_df[edu_df['researcher_id'] == rid] if not edu_df.empty else pd.DataFrame()
    color_map = {'박사': 'primary', '석사': 'secondary', '학사': 'light',
                 '전문대': 'light', '고교': 'light'}
    text_map = {'박사': 'white', '석사': 'white', '학사': 'dark',
                '전문대': 'dark', '고교': 'dark'}
    items = []
    for degree in DEGREE_ORDER:
        rows = edu_rows[edu_rows['degree'] == degree]
        if rows.empty:
            continue
        edu = rows.iloc[0]
        try:
            grad_year = int(edu['graduation_year'])
        except (TypeError, ValueError):
            grad_year = edu.get('graduation_year', '-')
        items.append(html.Div([
            dbc.Badge(degree, color=color_map.get(degree, 'light'),
                      text_color=text_map.get(degree, 'dark'),
                      className='me-1 flex-shrink-0'),
            html.Span(f"{edu.get('school', '')}  {edu.get('major', '')} ({grad_year})",
                      className='small'),
        ], className='d-flex align-items-center mb-1'))
    return html.Div(items) if items else html.Div('학력 정보 없음', className='text-muted small')


def evaluation_incentive_block(eva_df, inc_df, rid: str, years: list[int]):
    inc = inc_df[inc_df['researcher_id'] == rid] if not inc_df.empty else pd.DataFrame()
    eva = eva_df[eva_df['researcher_id'] == rid] if not eva_df.empty else pd.DataFrame()

    def _inc_label(year):
        if inc.empty:
            return '-'
        row = inc[inc['year'].astype(str) == str(year)]
        if row.empty:
            return '-'
        selected = str(row.iloc[0].get('selected', '')).lower()
        if selected in ('true', '1', 'yes'):
            category = str(row.iloc[0].get('category', '선정'))
            return '최우수' if '최우수' in category else ('우수' if '우수' in category else category[:4])
        return '-'

    def _grade(year):
        if eva.empty:
            return '-'
        row = eva[eva['year'].astype(str) == str(year)]
        return str(row.iloc[0].get('grade', '-')) if not row.empty else '-'

    def _grade_td(grade):
        color = GRADE_COLOR.get(grade, '#aaa')
        return html.Td(
            html.Span(grade, style={'color': color, 'fontWeight': '700', 'fontSize': '0.9rem'}),
            className='text-center',
        )

    return dbc.Table([
        html.Thead(
            html.Tr(
                [html.Th('구분', style={'fontSize': '0.72rem', 'width': '55px'})] +
                [html.Th(f"'{str(year)[-2:]}", className='text-center',
                         style={'fontSize': '0.72rem'})
                 for year in years]
            ),
            className='table-light',
        ),
        html.Tbody([
            html.Tr(
                [html.Td('인센티브', className='small text-muted',
                         style={'whiteSpace': 'nowrap', 'fontSize': '0.75rem'})] +
                [html.Td(_inc_label(year), className='text-center small') for year in years]
            ),
            html.Tr(
                [html.Td('평가등급', className='small text-muted',
                         style={'whiteSpace': 'nowrap', 'fontSize': '0.75rem'})] +
                [_grade_td(_grade(year)) for year in years]
            ),
        ]),
    ], bordered=True, size='sm', className='mb-0', style={'fontSize': '0.8rem'})


def nurturing_block(nur_df, rid: str, *, limit: int | None = None):
    rows = nur_df[nur_df['researcher_id'] == rid].copy() if not nur_df.empty else pd.DataFrame()
    if not rows.empty:
        sort_col = 'start_date' if 'start_date' in rows.columns else (
            'year' if 'year' in rows.columns else rows.columns[0])
        rows = rows.sort_values(sort_col, ascending=False)
        if limit:
            rows = rows.head(limit)

    items = []
    for _, row in rows.iterrows():
        start = str(row.get('start_date', '')).strip()
        end = str(row.get('end_date', '')).strip()
        sy = start[:4] if len(start) >= 4 else ''
        ey = end[:4] if len(end) >= 4 else ''
        year_label = f"'{sy[-2:]}" if sy else ''
        if sy and ey and ey > sy:
            year_label += f"~'{ey[-2:]}"
        loc = ' '.join(p for p in [
            str(row.get('country', '')).strip(),
            str(row.get('institution', '')).strip(),
        ] if p and p not in ('nan',))
        parts = [p for p in [year_label, str(row.get('subcategory', '')).strip(), loc]
                 if p and p not in ('nan',)]
        items.append(html.Li(' / '.join(parts) if parts else '-', className='small'))
    return html.Ul(items, className='ps-3 mb-0 small') if items else html.Div('양성 이력 없음', className='text-muted small')


AWARD_TYPES = {'그룹표창', '대표이사표창', '대표이사표창(시상금미포함)', '부문표창'}


def award_block(awd_df, rid: str):
    if awd_df.empty:
        return html.Div('시상 이력 없음', className='text-muted small')
    rows = awd_df[awd_df['researcher_id'] == rid].copy()
    rows = rows[rows['award_type'].isin(AWARD_TYPES)] if 'award_type' in rows.columns else rows
    if rows.empty:
        return html.Div('시상 이력 없음', className='text-muted small')

    sort_col = 'year' if 'year' in rows.columns else ('award_date' if 'award_date' in rows.columns else rows.columns[0])
    rows = rows.sort_values(sort_col, ascending=False)

    items = []
    for _, row in rows.iterrows():
        yr = str(row.get('year', str(row.get('award_date', ''))[:4])).strip()
        yr_label = f"'{yr[-2:]}" if len(yr) >= 2 else yr
        aname = str(row.get('award_name', '')).strip()
        desc  = str(row.get('description', '')).strip()
        parts = [p for p in [yr_label, aname, desc] if p and p not in ('nan',)]
        items.append(html.Li(' / '.join(parts) if parts else '-', className='small'))
    return html.Ul(items, className='ps-3 mb-0 small')


def transfer_block(tra_df, rid: str):
    rows = tra_df[tra_df['researcher_id'] == rid].sort_values('date', ascending=False) if not tra_df.empty else pd.DataFrame()
    if rows.empty:
        return html.Div('발령 / 프로젝트 이력 없음', className='text-muted small')
    table_rows = [
        html.Tr([
            html.Td(str(row.get('date', ''))[:7], className='small text-muted',
                    style={'whiteSpace': 'nowrap'}),
            html.Td(dbc.Badge(str(row.get('type', '')),
                              color=TRANSFER_BADGE.get(str(row.get('type', '')), 'light'),
                              className='small')),
            html.Td(str(row.get('description', '')), className='small'),
        ])
        for _, row in rows.iterrows()
    ]
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('시기', style={'fontSize': '0.72rem'}),
            html.Th('유형', style={'fontSize': '0.72rem'}),
            html.Th('내용', style={'fontSize': '0.72rem'}),
        ]), className='table-light'),
        html.Tbody(table_rows),
    ], bordered=False, hover=True, responsive=True, size='sm',
       className='mb-0', style={'maxHeight': '130px', 'overflowY': 'auto', 'display': 'block'})


def comments_block(cmt_df, rid: str):
    if cmt_df.empty:
        return html.Div('코멘트 없음', className='text-muted small')
    rows = cmt_df[cmt_df['researcher_id'] == rid]
    sort_cols = ['year', 'commenter_type'] if 'commenter_type' in cmt_df.columns else ['year']
    rows = rows.sort_values(sort_cols, ascending=False)
    cards = []
    for _, row in rows.iterrows():
        c_type = str(row.get('commenter_type', '부서장'))
        badge_color = 'danger' if c_type == '부서장' else 'info'
        try:
            year_label = f'{int(row["year"])}년'
        except (TypeError, ValueError):
            year_label = f'{row.get("year", "")}년'
        cards.append(
            dbc.Card(
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col(html.Span(year_label, className='fw-bold small'), width='auto'),
                        dbc.Col(dbc.Badge(c_type, color=badge_color, className='small'), width='auto'),
                    ], className='mb-1 g-1'),
                    html.P(str(row.get('comment_summary', '')),
                           className='small mb-1', style={'lineHeight': '1.5'}),
                    html.Small(['강점: ', html.Span(str(row.get('strengths', '')),
                                                   className='text-muted')],
                               className='d-block') if row.get('strengths') else None,
                ], className='py-2 px-3'),
                className='mb-2 border',
            )
        )
    return html.Div(cards) if cards else html.Div('코멘트 없음', className='text-muted small')


def leadership_year_options(lea_df, rid: str):
    if lea_df.empty:
        return [], None
    years = sorted(lea_df[lea_df['researcher_id'] == rid]['year'].unique(), reverse=True)
    return [{'label': str(year), 'value': year} for year in years], years[0] if years else None


def leadership_figure(lea_df, rid: str, year):
    fig = go.Figure()
    if not rid or not year or lea_df.empty:
        return fig
    dims = LEADERSHIP_DIMS
    labels = dims + [dims[0]]

    def _vals(row):
        return [float(row[d]) if d in row and pd.notna(row[d]) else 0 for d in dims]

    all_others = lea_df[lea_df['evaluator_group'] == '타인평균']
    if not all_others.empty:
        grand_vals = [all_others[d].mean() if d in all_others.columns else 0 for d in dims]
        fig.add_trace(go.Scatterpolar(
            r=grand_vals + [grand_vals[0]],
            theta=labels,
            fill='toself',
            fillcolor='rgba(180,180,180,0.15)',
            line=dict(color='rgba(150,150,150,0.5)', width=1.5, dash='dot'),
            name='전체 평균',
            hovertemplate='%{theta}: %{r:.2f}<extra>전체 평균</extra>',
        ))

    selected = lea_df[
        (lea_df['researcher_id'] == rid) &
        (lea_df['year'].astype(str) == str(year)) &
        (lea_df['evaluator_group'] == '타인평균')
    ]
    if selected.empty:
        return fig

    my_vals = _vals(selected.iloc[0])
    fig.add_trace(go.Scatterpolar(
        r=my_vals + [my_vals[0]],
        theta=labels,
        fill='toself',
        fillcolor='rgba(30,58,95,0.18)',
        line=dict(color='#1e3a5f', width=2.5),
        name='타인평균',
        hovertemplate='%{theta}: %{r:.2f}<extra>타인평균</extra>',
    ))

    all_vals = my_vals + ([all_others[d].mean() for d in dims if d in all_others.columns]
                          if not all_others.empty else [])
    r_max = max((value for value in all_vals if value), default=5) * 1.1
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, r_max], tickfont=dict(size=8)),
            angularaxis=dict(tickfont=dict(size=10, color='#333')),
        ),
        showlegend=True,
        legend=dict(orientation='h', y=-0.12, font=dict(size=11)),
        margin=dict(l=50, r=50, t=15, b=35),
        paper_bgcolor='rgba(0,0,0,0)',
    )
    return fig
