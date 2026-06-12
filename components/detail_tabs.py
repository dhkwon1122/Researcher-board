import dash_bootstrap_components as dbc
import pandas as pd
from dash import html


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
