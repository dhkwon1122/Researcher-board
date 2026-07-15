from urllib.parse import quote

import dash_bootstrap_components as dbc
import pandas as pd
from dash import html

from components.timeline_data import (
    cell,
    count_true,
    count_us_registered,
    dedupe_patents,
    is_registered,
    share_sum,
)

_LEGEND_NEUTRAL = '#6e6e73'


def publications_tab(pub_df, rid):
    """연구원의 논문 실적 목록 (data/processed/publications.csv)."""
    if pub_df.empty:
        return html.Div('논문 데이터 없음', className='text-muted p-3')

    sort_col = 'pub_date' if 'pub_date' in pub_df.columns else 'pub_year'
    pub = pub_df[pub_df['researcher_id'] == rid].copy()
    if pub.empty:
        return html.Div('논문 실적 없음', className='text-muted p-3')
    pub = pub.sort_values(sort_col, ascending=False)

    total = len(pub)
    corr_mask = pub['is_corresponding'].astype(str).str.lower().isin(['true', '1', 'y', 'yes'])
    corr = int(corr_mask.sum())

    summary = dbc.Row([
        dbc.Col(_single_card(total, '총 논문 수', 'text-primary'), md=2),
        dbc.Col(_single_card(corr, '교신저자', 'text-warning'), md=2),
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
                    className='small text-muted', style={'wordBreak': 'break-word'}),
            html.Td(row.get('title', ''),
                    style={'wordBreak': 'break-word', 'fontSize': '0.82rem'}),
            html.Td(row.get('journal', ''), className='small text-muted',
                    style={'wordBreak': 'break-word'}),
            html.Td(rank_total, className='small text-center', style={'wordBreak': 'break-word'}),
            html.Td(f'{contrib}%' if contrib and contrib not in ('nan', '') else '',
                    className='small text-center'),
            html.Td(html.Div(badges) if badges else '', style={'wordBreak': 'break-word'}),
        ]))

    return html.Div([summary, dbc.Table([
        html.Thead(html.Tr([
            html.Th('발표일', style={'width': '9%'}),
            html.Th('제목', style={'width': '31%'}),
            html.Th('게재처', style={'width': '20%'}),
            html.Th('순위/총수', className='text-center', style={'width': '10%'}),
            html.Th('기여도', className='text-center', style={'width': '10%'}),
            html.Th('구분', style={'width': '20%'}),
        ]), className='table-light'),
        html.Tbody(rows),
    ], bordered=False, hover=True, size='sm',
       style={'tableLayout': 'fixed', 'width': '100%'})])


def patents_tab(pat_df, rid):
    """연구원의 특허 실적 목록 (data/processed/patents.csv)."""
    if pat_df.empty:
        return html.Div('특허 데이터 없음', className='text-muted p-3')
    pat = pat_df[pat_df['researcher_id'] == rid].copy()
    if pat.empty:
        return html.Div('특허 실적 없음', className='text-muted p-3')

    pat_dedup = dedupe_patents(pat)
    total_cnt = len(pat_dedup)
    reg_cnt = int(pat_dedup['status'].apply(is_registered).sum()) if 'status' in pat_dedup.columns else 0
    lead_cnt = count_true(pat_dedup, 'is_lead_inventor')
    strat_cnt = int((pat_dedup.get('patent_grade_a_sub', pd.Series(dtype=str)).astype(str).str.strip() == '전략출원').sum())
    us_reg_cnt = count_us_registered(pat_dedup)
    share_sum_val = share_sum(pat_dedup)

    summary = dbc.Row([
        dbc.Col(_dual_card(total_cnt, '전체 발명', 'text-dark',
                           lead_cnt, '대표 발명', 'text-secondary'), md=3),
        dbc.Col(_dual_card(total_cnt, '출원', 'text-primary',
                           reg_cnt, '등록', 'text-success'), md=3),
        dbc.Col(_single_card(strat_cnt, '전략 출원', 'text-warning'), md=2),
        dbc.Col(_single_card(us_reg_cnt, '미국 등록', 'text-info'), md=2),
        dbc.Col(_single_card(share_sum_val, '지분율 합계', 'text-danger'), md=2),
    ], className='mb-3 g-2')

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
            html.Td(cell(row, 'application_date')[:7], style={'wordBreak': 'break-word'}),
            html.Td(cell(row, 'title', 'title_ko'), style={'wordBreak': 'break-word'}),
            html.Td(dbc.Badge('등록', color='success') if is_registered(status_val)
                    else dbc.Badge(status_val or '출원', color='primary')),
            html.Td(cell(row, 'application_id', 'application_no'), style={'wordBreak': 'break-word'}),
            html.Td(dbc.Badge('대표', color='warning', text_color='dark')
                    if lead in ('Y', 'y', '1', 'True', 'true') else ''),
            html.Td(share_str),
            html.Td(grade_str or '-', style={'wordBreak': 'break-word'}),
            html.Td(cell(row, 'country'), style={'wordBreak': 'break-word'}),
        ]))

    return html.Div([summary, dbc.Table([
        html.Thead(html.Tr([
            html.Th('출원일', style={'width': '9%'}),
            html.Th('발명 명칭', style={'width': '24%'}),
            html.Th('상태', style={'width': '9%'}),
            html.Th('접수ID/출원번호', style={'width': '14%'}),
            html.Th('대표발명자', style={'width': '9%'}),
            html.Th('지분율', style={'width': '8%'}),
            html.Th('등급', style={'width': '12%'}),
            html.Th('출원 국가', style={'width': '15%'}),
        ])),
        html.Tbody(rows),
    ], bordered=False, hover=True, size='sm',
       style={'tableLayout': 'fixed', 'width': '100%'})])


_PANEL_TITLE_STYLE = {'fontSize': '0.85rem', 'fontWeight': 600, 'color': '#1d1d1f'}
_GRADE_PILL_COLOR = '#3f8f57'
_E_SUPPORT_COLOR = '#0071e3'


def _pill(text, bg, fg='#ffffff'):
    return html.Span(text, style={
        'display': 'inline-block',
        'backgroundColor': bg,
        'color': fg,
        'borderRadius': '999px',
        'padding': '2px 10px',
        'fontSize': '0.7rem',
        'fontWeight': 600,
        'lineHeight': '1.5',
        'whiteSpace': 'nowrap',
    })


def _e_support_pill(value):
    v = str(value).strip().upper()
    return _pill('E직군', _LEGEND_NEUTRAL) if v == 'E' else _pill('R직군', _E_SUPPORT_COLOR)


def _info_hover(icon_id, label, image_filename):
    return html.Div([
        html.I(className='bi bi-info-circle', id=icon_id,
               style={'fontSize': '0.85rem', 'color': _LEGEND_NEUTRAL, 'cursor': 'help'}),
        html.Span(f' {label}', className='small text-muted ms-1'),
        dbc.Tooltip(
            html.Img(src=f'/raw-image/{quote(image_filename)}',
                     style={'maxWidth': '360px', 'maxHeight': '360px', 'display': 'block'}),
            target=icon_id, placement='top',
        ),
    ], className='d-flex align-items-center mt-2')


def _clean_num_str(val) -> str:
    """CSV 왕복 과정에서 컬럼에 빈 값이 섞이면 pandas가 float로 승격시켜
    '3.0'처럼 불필요한 소수점이 붙는 경우가 있어, 표시 직전에 한 번 더 정리한다."""
    s = str(val).strip()
    if s in ('', 'nan', 'None', 'NaT'):
        return ''
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else s
    except (ValueError, OverflowError):
        return s


def _core_technology_table(core_df):
    if core_df.empty:
        return html.Div('핵심기술 데이터 없음', className='text-muted small')

    rows = []
    for _, row in core_df.iterrows():
        field = str(row.get('tech_field', '')).strip()
        name = str(row.get('tech_name', '')).strip()
        grade = _clean_num_str(row.get('tech_grade', '')) or '-'
        grade_disp = f'{grade}급' if grade != '-' else '-'
        rows.append(html.Tr([
            html.Td(field, className='small', style={'wordBreak': 'break-word'}),
            html.Td(html.Div([
                _pill(grade_disp, _GRADE_PILL_COLOR),
                html.Span(name, className='small ms-2'),
            ], className='d-flex align-items-center'), style={'wordBreak': 'break-word'}),
        ]))

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('기술분야', style={'fontSize': '0.72rem', 'width': '35%'}),
            html.Th('핵심기술', style={'fontSize': '0.72rem', 'width': '65%'}),
        ]), className='table-light'),
        html.Tbody(rows),
    ], bordered=False, hover=True, size='sm', className='mb-0',
       style={'tableLayout': 'fixed', 'width': '100%'})


def _tech_ownership_table(tech_row):
    if tech_row is None:
        return html.Div('보유기술 데이터 없음', className='text-muted small')

    rows = []
    for i in range(1, 6):
        name = str(tech_row.get(f'tech_{i}', '')).strip()
        if not name or name in ('nan', 'None'):
            continue
        lv = _clean_num_str(tech_row.get(f'lv_{i}', ''))
        portion = _clean_num_str(tech_row.get(f'portion_{i}', ''))
        rows.append(html.Tr([
            html.Td(str(i), className='small text-center'),
            html.Td(name, className='small', style={'wordBreak': 'break-word'}),
            html.Td(lv or '-', className='small text-center'),
            html.Td(f'{portion}%' if portion else '-', className='small text-center'),
        ]))

    if not rows:
        return html.Div('보유기술 데이터 없음', className='text-muted small')

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('구분', className='text-center', style={'fontSize': '0.72rem', 'width': '15%'}),
            html.Th('전문분야', style={'fontSize': '0.72rem', 'width': '45%'}),
            html.Th('Lv', className='text-center', style={'fontSize': '0.72rem', 'width': '15%'}),
            html.Th('보유율', className='text-center', style={'fontSize': '0.72rem', 'width': '25%'}),
        ]), className='table-light'),
        html.Tbody(rows),
    ], bordered=False, hover=True, size='sm', className='mb-0',
       style={'tableLayout': 'fixed', 'width': '100%'})


def owned_expertise_block(core_df, tech_df, rid):
    """보유 전문성 — 핵심기술(core_technology.csv) / 보유기술(tech_ownership.csv)을
    좌우로 나눠 표시. 좌: 기술분야·핵심기술(등급 배지). 우: 전문분야별 Lv·보유율,
    상단에 E/R 직군 배지."""
    core = core_df[core_df['researcher_id'] == rid] if not core_df.empty else pd.DataFrame()
    tech = tech_df[tech_df['researcher_id'] == rid] if not tech_df.empty else pd.DataFrame()
    tech_row = tech.iloc[0] if not tech.empty else None
    e_support = tech_row.get('E_support') if tech_row is not None else None

    left = html.Div([
        html.P('핵심기술', style=_PANEL_TITLE_STYLE, className='mb-2'),
        _core_technology_table(core),
        _info_hover('grade-info-icon', '등급 개요', '등급 개요.png'),
    ])

    right_title_children = [
        html.Span('보유기술', style=_PANEL_TITLE_STYLE),
        html.Span("('25년기준)", style={'fontSize': '0.68rem', 'color': _LEGEND_NEUTRAL, 'marginLeft': '3px'}),
    ]
    if e_support is not None:
        right_title_children.append(html.Div(_e_support_pill(e_support), className='ms-auto'))

    right = html.Div([
        html.Div(right_title_children, className='d-flex align-items-center mb-2'),
        _tech_ownership_table(tech_row),
        _info_hover('lv-info-icon', 'Lv 개요', 'lv 개요.png'),
    ])

    return dbc.Row([
        dbc.Col(left, md=6, className='pe-3'),
        dbc.Col(right, md=6, className='ps-3 border-start'),
    ], className='g-0')


def expertise_tab(expertise_df, rid):
    """과제 이력 기반 전문성 분류 결과 표시 (data/processed/researcher_expertise.csv).
    CLOSE 3: 참여 과제 전체를 종합했을 때 가장 가까운 기술분류 3개.
    FAR 3: 과제별로는 후보에 올랐지만 최종 전문성과 가장 거리가 먼 기술분류 3개.
    """
    if expertise_df.empty:
        return html.Div('전문성 분석 데이터 없음', className='text-muted p-3')
    rows = expertise_df[expertise_df['researcher_id'] == rid]
    if rows.empty:
        return html.Div('전문성 분석 데이터 없음', className='text-muted p-3')

    close = rows[rows['kind'] == 'CLOSE'].sort_values('rank')
    far = rows[rows['kind'] == 'FAR'].sort_values('rank')

    def _item(row):
        category = f"{row.get('category_top', '')} > {row.get('category_mid', '')} > {row.get('category_name', '')}"
        similarity = row.get('similarity', '')
        reason = str(row.get('reason', '')).strip()
        children = [
            html.Span(category, className='fw-semibold me-2'),
            html.Span(f'(유사도 {similarity})', className='text-muted small'),
        ]
        if reason and reason not in ('nan', 'None'):
            children.append(html.Div(reason, className='small text-muted mt-1'))
        return html.Li(children, className='mb-3')

    blocks = [
        html.P('전문성 CLOSE 3', className='section-label mb-2'),
        html.Ul([_item(r) for _, r in close.iterrows()], className='ps-3 mb-0')
        if not close.empty else html.Div('데이터 없음', className='text-muted small mb-3'),
    ]

    if not far.empty:
        blocks += [
            html.P('전문성 FAR 3', className='section-label mb-2 mt-3', style={'color': '#c98a1c'}),
            html.Ul([_item(r) for _, r in far.iterrows()], className='ps-3 mb-0'),
        ]

    return html.Div(blocks)


def _stat(value, label, color):
    return html.Div([
        html.H5(str(value), className=f'fw-bold stat-value {color} mb-0'),
        html.Small(label, className='text-muted'),
    ], className='text-center px-2')


def _dual_card(left_value, left_label, left_color, right_value, right_label, right_color):
    return dbc.Card(dbc.CardBody(
        dbc.Row([
            dbc.Col(_stat(left_value, left_label, left_color), width=6, className='border-end'),
            dbc.Col(_stat(right_value, right_label, right_color), width=6),
        ], className='g-0 align-items-center'),
        className='p-2',
    ), className='profile-card h-100', style={'backgroundColor': '#fafafa'})


def _single_card(value, label, color):
    return dbc.Card(dbc.CardBody(_stat(value, label, color), className='p-2'),
                    className='profile-card h-100', style={'backgroundColor': '#fafafa'})
