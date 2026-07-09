from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

TIMELINE_COLORS = {
    '과제':     '#2a78d6',
    '인사발령': '#1baf7a',
    '논문':     '#eda100',
    '특허':     '#008300',
}
_MUTED_INK = '#898781'
_GRIDLINE = '#e1e0d9'


def publications_tab(pub_df, rid):
    if pub_df.empty:
        return html.Div('논문 데이터 없음', className='text-muted p-3')

    # pub_date 기준 정렬 (없으면 pub_year)
    sort_col = 'pub_date' if 'pub_date' in pub_df.columns else 'pub_year'
    pub = pub_df[pub_df['researcher_id'] == rid].copy()
    if pub.empty:
        return html.Div('논문 실적 없음', className='text-muted p-3')
    pub = pub.sort_values(sort_col, ascending=False)

    total = len(pub)
    corr_mask = pub['is_corresponding'].astype(str).str.lower().isin(['true', '1', 'y', 'yes'])
    corr = int(corr_mask.sum())

    summary = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(str(total), className='fw-bold text-primary mb-0'),
            html.Small('총 논문 수', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=2),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(str(corr), className='fw-bold text-warning mb-0'),
            html.Small('교신저자', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=2),
    ], className='mb-3 g-2')

    rows = []
    for _, row in pub.iterrows():
        is_corr = str(row.get('is_corresponding', '')).lower() in ('true', '1', 'y', 'yes')
        contrib = str(row.get('contribution', '')).strip()
        rank_total = ''
        r = str(row.get('author_rank', '')).strip()
        t = str(row.get('total_authors', '')).strip()
        if r and t and r not in ('nan', '') and t not in ('nan', ''):
            rank_total = f'{r}/{t}'

        badges = []
        pub_type = str(row.get('pub_type', '')).strip()
        if pub_type and pub_type not in ('nan', ''):
            badges.append(dbc.Badge(pub_type, color='info', className='me-1'))
        author_type = str(row.get('author_type', '')).strip()
        if author_type and author_type not in ('nan', ''):
            badges.append(dbc.Badge(author_type, color='secondary', className='me-1'))
        if is_corr:
            badges.append(dbc.Badge('교신', color='warning', text_color='dark'))

        rows.append(html.Tr([
            html.Td(str(row.get('pub_year', '') or row.get('pub_date', ''))[:7],
                    className='small text-muted', style={'whiteSpace': 'nowrap'}),
            html.Td(row.get('title', ''),
                    style={'maxWidth': '320px', 'wordBreak': 'break-word', 'fontSize': '0.82rem'}),
            html.Td(row.get('journal', ''), className='small text-muted',
                    style={'maxWidth': '160px', 'wordBreak': 'break-word'}),
            html.Td(rank_total, className='small text-center', style={'whiteSpace': 'nowrap'}),
            html.Td(f'{contrib}%' if contrib and contrib not in ('nan', '') else '',
                    className='small text-center'),
            html.Td(html.Div(badges) if badges else ''),
        ]))

    return html.Div([summary, dbc.Table([
        html.Thead(html.Tr([
            html.Th('발표일', style={'width': '70px'}),
            html.Th('제목'),
            html.Th('게재처'),
            html.Th('순위/총수', className='text-center', style={'width': '70px'}),
            html.Th('기여도', className='text-center', style={'width': '55px'}),
            html.Th('구분'),
        ]), className='table-light'),
        html.Tbody(rows),
    ], bordered=False, hover=True, responsive=True, size='sm',
       style={'maxHeight': '340px', 'overflowY': 'auto', 'display': 'block'})])


def patents_tab(pat_df, rid):
    if pat_df.empty:
        return html.Div('특허 데이터 없음', className='text-muted p-3')
    pat = pat_df[pat_df['researcher_id'] == rid].copy()
    if pat.empty:
        return html.Div('특허 실적 없음', className='text-muted p-3')

    pat_dedup = _dedupe_patents(pat)
    total_cnt = len(pat_dedup)
    reg_cnt = int(pat_dedup['status'].apply(_is_registered).sum()) if 'status' in pat_dedup.columns else 0
    lead_cnt = _count_true(pat_dedup, 'is_lead_inventor')
    strat_cnt = int((pat_dedup.get('patent_grade_a_sub', pd.Series(dtype=str)).astype(str).str.strip() == '전략출원').sum())
    us_reg_cnt = _count_us_registered(pat_dedup)
    share_sum = _share_sum(pat_dedup)

    summary = dbc.Row([
        dbc.Col(_dual_card(total_cnt, '전체 발명', 'text-dark',
                           lead_cnt, '대표 발명', 'text-secondary'), md=3),
        dbc.Col(_dual_card(total_cnt, '출원', 'text-primary',
                           reg_cnt, '등록', 'text-success'), md=3),
        dbc.Col(_single_card(strat_cnt, '전략 출원', 'text-warning'), md=2),
        dbc.Col(_single_card(us_reg_cnt, '미국 등록', 'text-info'), md=2),
        dbc.Col(_single_card(share_sum, '지분율 합계', 'text-danger'), md=2),
    ], className='mb-3')

    sort_col = 'application_date' if 'application_date' in pat_dedup.columns else pat_dedup.columns[0]
    rows = []
    for _, row in pat_dedup.sort_values(sort_col, ascending=False).iterrows():
        status_val = str(row.get('status', ''))
        lead = str(row.get('is_lead_inventor', ''))
        grade = str(row.get('patent_grade', ''))
        grade_a = str(row.get('patent_grade_a_sub', ''))
        grade_str = grade + (f'({grade_a})' if grade_a and grade_a not in ('', 'nan') else '')
        share_val = row.get('share_ratio', '')
        share_str = f'{share_val}%' if str(share_val).replace('.', '').isdigit() else '-'
        rows.append(html.Tr([
            html.Td(_cell(row, 'application_date')[:7]),
            html.Td(_cell(row, 'title', 'title_ko'), style={'maxWidth': '280px', 'wordBreak': 'break-word'}),
            html.Td(dbc.Badge('등록', color='success') if _is_registered(status_val)
                    else dbc.Badge(status_val or '출원', color='primary')),
            html.Td(_cell(row, 'application_id', 'application_no')),
            html.Td(dbc.Badge('대표', color='warning', text_color='dark')
                    if lead in ('Y', 'y', '1', 'True', 'true') else ''),
            html.Td(share_str),
            html.Td(grade_str or '-'),
            html.Td(_cell(row, 'country')),
        ]))

    return html.Div([summary, dbc.Table([
        html.Thead(html.Tr([
            html.Th('출원일'), html.Th('발명 명칭'), html.Th('상태'),
            html.Th('접수ID/출원번호'), html.Th('대표발명자'), html.Th('지분율'),
            html.Th('등급'), html.Th('출원 국가'),
        ])),
        html.Tbody(rows),
    ], bordered=False, hover=True, responsive=True, size='sm')])


def technology_transfer_tab(tt_df, rid):
    if tt_df.empty:
        return html.Div('기술 이전 데이터 없음', className='text-muted p-3')
    tt = tt_df[tt_df['researcher_id'] == rid].sort_values('transfer_date', ascending=False)
    if tt.empty:
        return html.Div('기술 이전 실적 없음', className='text-muted p-3')
    amount = pd.to_numeric(tt['amount'], errors='coerce').fillna(0).sum()
    summary = dbc.Row([
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(str(len(tt)), className='fw-bold text-primary mb-0'),
            html.Small('총 건수', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=2),
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H4(f'{int(amount):,}만원', className='fw-bold text-success mb-0'),
            html.Small('누적 금액', className='text-muted'),
        ]), className='text-center border-0 bg-light'), md=3),
    ], className='mb-3')
    rows = [html.Tr([
        html.Td(str(row.get('transfer_date', ''))[:10]),
        html.Td(row.get('tech_name', '')),
        html.Td(row.get('recipient', '')),
        html.Td(row.get('transfer_type', '')),
        html.Td(_money(row.get('amount')), className='text-end'),
    ]) for _, row in tt.iterrows()]
    return html.Div([summary, dbc.Table([
        html.Thead(html.Tr([html.Th('이전일'), html.Th('기술명'), html.Th('거래처'),
                            html.Th('유형'), html.Th('금액', className='text-end')])),
        html.Tbody(rows),
    ], bordered=False, hover=True, responsive=True, size='sm')])


def timeline_tab(task_df, hr_df, pub_df, pat_df, rid):
    task = task_df[task_df['researcher_id'] == rid].copy() if not task_df.empty else pd.DataFrame()
    hr = hr_df[hr_df['researcher_id'] == rid].copy() if not hr_df.empty else pd.DataFrame()
    pub = pub_df[pub_df['researcher_id'] == rid].copy() if not pub_df.empty else pd.DataFrame()
    pat = pat_df[pat_df['researcher_id'] == rid].copy() if not pat_df.empty else pd.DataFrame()
    if not pat.empty:
        pat = _dedupe_patents(pat)

    if task.empty and hr.empty and pub.empty and pat.empty:
        return html.Div('타임라인 데이터 없음', className='text-muted p-3')

    task_points = _task_points(task)
    hr_points = _hr_points(hr)
    pub_points = _pub_points(pub)
    pat_points = _pat_points(pat)

    lane_labels = _assign_task_lanes(task_points)
    task_lanes = list(dict.fromkeys(lane_labels)) if lane_labels else ['과제']

    today = pd.Timestamp(datetime.now().date())
    all_dates = (
        [d for seg in task_points for d in (seg['start'], seg['end'])]
        + [p['date'] for p in hr_points]
        + [p['date'] for p in pub_points]
        + [p['date'] for p in pat_points]
    )
    min_date = min(all_dates) if all_dates else today
    pad = max(pd.Timedelta(days=15), (today - min_date) * 0.03)
    x_range = [min_date - pad, today + pd.Timedelta(days=15)]
    x_mid = x_range[0] + (x_range[1] - x_range[0]) / 2

    y_order = task_lanes + ['인사발령', '논문', '특허']

    fig = go.Figure()

    if task_points:
        xs, ys, texts = [], [], []
        for seg, lane in zip(task_points, lane_labels):
            hover = f"{seg['task_name']} | {seg['start_label']} ~ {seg['end_label']}"
            xs += [seg['start'], seg['end'], None]
            ys += [lane, lane, None]
            texts += [hover, hover, None]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode='lines+markers', name='과제',
            marker=dict(symbol='circle', size=9, color=TIMELINE_COLORS['과제']),
            line=dict(color=TIMELINE_COLORS['과제'], width=2),
            text=texts, hovertemplate='%{text}',
        ))
    else:
        fig.add_annotation(x=x_mid, y='과제', text='과제 데이터 없음',
                            showarrow=False, font=dict(color=_MUTED_INK, size=12))

    if hr_points:
        fig.add_trace(go.Scatter(
            x=[p['date'] for p in hr_points], y=['인사발령'] * len(hr_points),
            mode='markers', name='인사발령',
            marker=dict(symbol='star', size=12, color=TIMELINE_COLORS['인사발령']),
            text=[p['hover'] for p in hr_points], hovertemplate='%{text}',
        ))
    else:
        fig.add_annotation(x=x_mid, y='인사발령', text='인사발령 데이터 없음',
                            showarrow=False, font=dict(color=_MUTED_INK, size=12))

    if pub_points:
        fig.add_trace(go.Scatter(
            x=[p['date'] for p in pub_points], y=['논문'] * len(pub_points),
            mode='markers', name='논문',
            marker=dict(symbol='square', size=9, color=TIMELINE_COLORS['논문']),
            text=[p['hover'] for p in pub_points], hovertemplate='%{text}',
        ))
    else:
        fig.add_annotation(x=x_mid, y='논문', text='논문 데이터 없음',
                            showarrow=False, font=dict(color=_MUTED_INK, size=12))

    if pat_points:
        fig.add_trace(go.Scatter(
            x=[p['date'] for p in pat_points], y=['특허'] * len(pat_points),
            mode='markers', name='특허',
            marker=dict(symbol='triangle-up', size=10, color=TIMELINE_COLORS['특허']),
            text=[p['hover'] for p in pat_points], hovertemplate='%{text}',
        ))
    else:
        fig.add_annotation(x=x_mid, y='특허', text='특허 데이터 없음',
                            showarrow=False, font=dict(color=_MUTED_INK, size=12))

    fig.update_layout(
        xaxis=dict(range=x_range, type='date', gridcolor=_GRIDLINE),
        yaxis=dict(type='category', categoryorder='array', categoryarray=y_order,
                   gridcolor=_GRIDLINE),
        legend=dict(orientation='v', yanchor='top', y=1, xanchor='right', x=1),
        hoverlabel=dict(namelength=-1),
        margin=dict(l=10, r=10, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=420,
    )

    return dcc.Graph(figure=fig, config={'displayModeBar': False})


def _parse_ts(val):
    s = str(val).strip() if val is not None else ''
    if not s or s in ('nan', 'None', 'NaT'):
        return None
    try:
        return pd.Timestamp(s)
    except (ValueError, TypeError):
        return None


def _task_points(task_df):
    if task_df.empty:
        return []
    today = pd.Timestamp(datetime.now().date())
    points = []
    for _, row in task_df.iterrows():
        start = _parse_ts(row.get('start_date'))
        if start is None:
            continue
        end_raw = row.get('end_date')
        end = _parse_ts(end_raw)
        end_label = end.strftime('%Y-%m-%d') if end is not None else '진행중'
        if end is None or end < start:
            end = today
        points.append({
            'task_name': str(row.get('task_name', '')).strip(),
            'start': start,
            'end': end,
            'start_label': start.strftime('%Y-%m-%d'),
            'end_label': end_label,
        })
    points.sort(key=lambda p: p['start'])
    return points


def _assign_task_lanes(points):
    if not points:
        return []
    lane_ends = []
    lane_idx = [0] * len(points)
    for i, p in enumerate(points):
        placed = False
        for lane, lane_end in enumerate(lane_ends):
            if p['start'] >= lane_end:
                lane_ends[lane] = p['end']
                lane_idx[i] = lane
                placed = True
                break
        if not placed:
            lane_ends.append(p['end'])
            lane_idx[i] = len(lane_ends) - 1
    if len(lane_ends) <= 1:
        return ['과제'] * len(points)
    return [f'과제 {idx + 1}' for idx in lane_idx]


def _hr_points(hr_df):
    if hr_df.empty:
        return []
    points = []
    for _, row in hr_df.iterrows():
        date = _parse_ts(row.get('order_date'))
        if date is None:
            continue
        hover = (f"{str(row.get('order_date', '')).strip()} | "
                 f"{str(row.get('order_name', '')).strip()} | "
                 f"{str(row.get('order_dep', '')).strip()} | "
                 f"{str(row.get('order_cl', '')).strip()}")
        points.append({'date': date, 'hover': hover})
    points.sort(key=lambda p: p['date'])
    return points


def _pub_points(pub_df):
    if pub_df.empty:
        return []
    points = []
    for _, row in pub_df.iterrows():
        pub_date = str(row.get('pub_date', '')).strip()
        if not pub_date or pub_date in ('nan', 'None'):
            pub_year = str(row.get('pub_year', '')).strip()
            pub_date = f'{pub_year}-01-01' if pub_year and pub_year not in ('nan', 'None') else ''
        date = _parse_ts(pub_date)
        if date is None:
            continue
        hover = (f"{str(row.get('title', '')).strip()} | "
                 f"{str(row.get('journal', '')).strip()} | "
                 f"{str(row.get('author_type', '')).strip()}")
        points.append({'date': date, 'hover': hover})
    points.sort(key=lambda p: p['date'])
    return points


def _pat_points(pat_df):
    if pat_df.empty:
        return []
    points = []
    for _, row in pat_df.iterrows():
        reg = str(row.get('registration_date', '')).strip()
        app = str(row.get('application_date', '')).strip()
        date_raw = reg if reg and reg not in ('nan', 'None') else app
        date = _parse_ts(date_raw)
        if date is None:
            continue
        title = _cell(row, 'title', 'title_ko')
        grade = str(row.get('patent_grade', '')).strip()
        grade_a = str(row.get('patent_grade_a_sub', '')).strip()
        grade_str = grade + (' (전략출원)' if grade_a == '전략출원' else '')
        share = str(row.get('share_ratio', '')).strip()
        lead = str(row.get('is_lead_inventor', '')).strip()
        hover = f'{title} | {grade_str} | 지분율 {share}% | 대표발명자 {lead}'
        points.append({'date': date, 'hover': hover})
    points.sort(key=lambda p: p['date'])
    return points


def _number(value, fmt):
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return '-'


def _money(value):
    number = pd.to_numeric(value, errors='coerce')
    if pd.isna(number):
        number = 0
    return f'{int(number):,}만원'


def _is_registered(value):
    return '등록' in str(value)


def _cell(row, *keys, default='-'):
    for key in keys:
        value = str(row.get(key, ''))
        if value and value not in ('', 'nan', 'None'):
            return value
    return default


def _dedupe_patents(pat):
    id_col = 'application_id' if 'application_id' in pat.columns else None
    if not id_col:
        return pat.copy()

    def _merge_countries(series):
        seen = {}
        for value in series:
            text = str(value).strip()
            if text in ('', 'nan', 'None', '-'):
                continue
            for part in text.split(','):
                part = part.strip()
                if part:
                    seen[part] = None
        return ', '.join(seen.keys()) if seen else '-'

    def _agg_status(series):
        values = series.astype(str).tolist()
        for value in values:
            if _is_registered(value):
                return value
        return values[0] if values else ''

    agg_dict = {col: 'first' for col in pat.columns if col not in (id_col, 'researcher_id', 'country', 'status')}
    if 'status' in pat.columns:
        agg_dict['status'] = _agg_status
    if 'country' in pat.columns:
        agg_dict['country'] = _merge_countries
    return pat.groupby(id_col, sort=False).agg(agg_dict).reset_index()


def _count_true(df, col):
    if col not in df.columns:
        return 0
    return int(df[col].astype(str).isin(['Y', 'y', '1', 'True', 'true']).sum())


def _count_us_registered(df):
    if 'country' not in df.columns or 'status' not in df.columns:
        return 0
    us_mask = df['country'].astype(str).str.contains('미국|USA|US', case=False, na=False)
    return int((us_mask & df['status'].apply(_is_registered)).sum())


def _share_sum(df):
    if 'share_ratio' not in df.columns:
        return '-'
    shares = pd.to_numeric(df['share_ratio'], errors='coerce').dropna()
    return f'{round(shares.sum(), 1)}%' if not shares.empty else '-'


def _stat(value, label, color):
    return html.Div([
        html.H5(str(value), className=f'fw-bold {color} mb-0'),
        html.Small(label, className='text-muted'),
    ], className='text-center px-2')


def _dual_card(left_value, left_label, left_color, right_value, right_label, right_color):
    return dbc.Card(dbc.CardBody(
        dbc.Row([
            dbc.Col(_stat(left_value, left_label, left_color), width=6, className='border-end'),
            dbc.Col(_stat(right_value, right_label, right_color), width=6),
        ], className='g-0 align-items-center'),
        className='p-2',
    ), className='border-0 bg-light h-100')


def _single_card(value, label, color):
    return dbc.Card(dbc.CardBody(_stat(value, label, color), className='p-2'),
                    className='border-0 bg-light h-100')
