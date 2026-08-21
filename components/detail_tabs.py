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

def llm_summary_block(profile: dict | None, similar: list | None = None, name_map: dict | None = None,
                       *, include_responsibilities: bool = True):
    """전문성 요약(LLM) — 연구원 보유 전문성 분석.json의 핵심 분야(strength_fields)/
    키워드(strength_keywords)를 배지로, 주요 역할·책임(key_responsibilities)/
    전문지식 및 역량(domain_knowledge_skill)을 불릿 목록으로 보여준다.
    similar(researcher_similarity.json의 해당 연구원 항목 중 'similar' 리스트,
    시니어 우선으로 이미 정렬돼 있음)가 주어지면 시니어 3명·주니어 3명을 유사
    연구원 배지로 덧붙인다(생략하면 유사 연구원 섹션 자체를 건너뜀 — A4 인쇄
    요약처럼 지면이 좁을 때 사용). include_responsibilities=False면 주요 역할·
    책임 목록을 뺀다(같은 이유). 해당 연구원이 분석 대상이 아니거나 아직
    파이프라인을 실행하지 않아 데이터가 없으면 안내 문구만 표시한다."""
    if not profile:
        return html.Div('분석 데이터 없음', className='text-muted small p-1')

    fields = profile.get('strength_fields') or []
    keywords = profile.get('strength_keywords') or []
    responsibilities = profile.get('key_responsibilities') or []
    domain_skill = profile.get('domain_knowledge_skill') or []

    children = []
    if fields:
        children.append(html.Div('Strength Field', className='small text-muted fw-semibold mb-1'))
        children.append(html.Div(
            [dbc.Badge(f, color='dark', className='me-1 mb-1') for f in fields],
        ))
    if keywords:
        children.append(html.Div('Strength Keywords', className='small text-muted fw-semibold mt-2 mb-1'))
        children.append(html.Div(
            [dbc.Badge(k, color='secondary', className='me-1 mb-1') for k in keywords],
        ))
    if responsibilities and include_responsibilities:
        children.append(html.Div('주요 역할·책임', className='small text-muted fw-semibold mt-2 mb-1'))
        children.append(html.Ul([html.Li(r, className='small') for r in responsibilities], className='mb-0 ps-3'))
    if domain_skill:
        children.append(html.Div('전문지식 및 역량', className='small text-muted fw-semibold mt-2 mb-1'))
        children.append(html.Ul([html.Li(d, className='small') for d in domain_skill], className='mb-0 ps-3'))

    name_map = name_map or {}
    senior = [s for s in (similar or []) if s.get('tenure_level') == 'Senior'][:3]
    junior = [s for s in (similar or []) if s.get('tenure_level') == 'Junior'][:3]
    if senior or junior:
        def _badge(s, color):
            rid = s.get('researcher_id', '')
            return dbc.Badge(name_map.get(rid, rid), color=color, className='me-1 mb-1')

        children.append(html.Div([
            html.Div('유사 연구원', className='small text-muted fw-semibold mt-2 mb-1'),
            html.Div([_badge(s, 'primary') for s in senior] + [_badge(s, 'info') for s in junior]),
        ]))

    if not children:
        return html.Div('분석 데이터 없음', className='text-muted small p-1')
    return children


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
            target=icon_id, placement='top', className='info-hover-tooltip',
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


def _core_technology_table(core_df, *, compact: bool = False):
    """compact=True면 표(기술분야/핵심기술 2열 + 헤더) 대신 "(등급)분야 > 기술명"
    한 줄짜리 텍스트를 항목마다 나열한다(사용자 요청, A4 인쇄본 전용 —
    화면 기본값 False는 기존 표 그대로)."""
    if core_df.empty:
        return html.Div('핵심기술 데이터 없음', className='text-muted small')

    if compact:
        lines = []
        for _, row in core_df.iterrows():
            field = str(row.get('tech_field', '')).strip()
            name = str(row.get('tech_name', '')).strip()
            grade = _clean_num_str(row.get('tech_grade', '')) or '-'
            grade_disp = f'{grade}급' if grade != '-' else '-'
            lines.append(html.Div(f'({grade_disp}){field} > {name}', className='small',
                                   style={'wordBreak': 'break-word', 'marginBottom': '2px'}))
        return html.Div(lines)

    rows = []
    for _, row in core_df.iterrows():
        field = str(row.get('tech_field', '')).strip()
        name = str(row.get('tech_name', '')).strip()
        grade = _clean_num_str(row.get('tech_grade', '')) or '-'
        grade_disp = f'{grade}급' if grade != '-' else '-'
        # 등급 배지(B급/A급 등) + 기술명을 display:table-cell 두 칸으로 배치한다
        # — 기술명이 길어 줄바꿈되면, 이어지는 줄이 배지 자리(B급 등)까지 다시
        # 밀고 올라오지 않고 기술명 시작 위치에 맞춰 들여써진다(사용자 요청:
        # 줄바꿈된 다음 줄은 배지 아래를 비워 보여달라는 것). 이전에 CSS
        # text-indent 음수값으로 구현했었는데, 첫 줄 맨 앞이 배지(inline-block)일
        # 때 브라우저가 배지 자체의 렌더링 폭까지 잘라내 버려("B급" 글자가
        # 하얗게 사라지고 초록 원만 조그맣게 남는") 버그가 있었다 —
        # table-cell은 각 칸(배지/텍스트)이 서로 별개 박스라 이 문제가 없다.
        rows.append(html.Tr([
            html.Td(field, className='small', style={'wordBreak': 'break-word'}),
            html.Td(html.Div([
                html.Div(_pill(grade_disp, _GRADE_PILL_COLOR),
                          style={'display': 'table-cell', 'verticalAlign': 'top',
                                 'whiteSpace': 'nowrap', 'paddingRight': '6px'}),
                html.Div(html.Span(name, className='small'),
                          style={'display': 'table-cell', 'verticalAlign': 'top', 'width': '100%'}),
            ], style={'display': 'table', 'width': '100%'}),
                style={'wordBreak': 'break-word'}),
        ]))

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('기술분야', style={'fontSize': '0.72rem', 'width': '35%'}),
            html.Th('핵심기술', style={'fontSize': '0.72rem', 'width': '65%'}),
        ]), className='table-light'),
        html.Tbody(rows),
    ], bordered=False, hover=True, size='sm', className='mb-0',
       style={'tableLayout': 'fixed', 'width': '100%'})


# '등록' 을 포함하지만 실제로는 등록이 아닌 상태(등록 전/무산). 필요시 추가.
_NOT_REGISTERED_KEYWORDS = ('등록전', '등록 전', '등록료불납', '등록료 불납')


def _is_registered(value):
    """진행상태 문자열이 '등록(완료)'을 의미하면 True. '등록전 종료' 등은 False."""
    s = str(value)
    if '등록' not in s:
        return False
    return not any(neg in s for neg in _NOT_REGISTERED_KEYWORDS)


def _tech_ownership_table(tech_row, *, show_index: bool = True, no_header: bool = False):
    """show_index=False면 맨 앞 "구분"(1~5 순번) 열을 뺀다 — A4 인쇄처럼 지면이
    좁아 순번 자체가 별 정보가 안 될 때 사용(화면은 기본값 True로 그대로).
    no_header=True면 표 헤더 행(구분/전문분야/Lv/보유율)을 빼고 데이터
    행만 바로 보여준다(사용자 요청, A4 인쇄본 전용)."""
    if tech_row is None:
        return html.Div('보유기술 데이터 없음', className='text-muted small')

    rows = []
    for i in range(1, 6):
        name = str(tech_row.get(f'tech_{i}', '')).strip()
        if not name or name in ('nan', 'None'):
            continue
        lv = _clean_num_str(tech_row.get(f'lv_{i}', ''))
        portion = _clean_num_str(tech_row.get(f'portion_{i}', ''))
        cells = [html.Td(str(i), className='small text-center')] if show_index else []
        cells += [
            html.Td(name, className='small', style={'wordBreak': 'break-word'}),
            html.Td(lv or '-', className='small text-center', style={'textAlign': 'center'}),
            html.Td(f'{portion}%' if portion else '-', className='small text-center', style={'textAlign': 'center'}),
        ]
        rows.append(html.Tr(cells))

    if not rows:
        return html.Div('보유기술 데이터 없음', className='text-muted small')

    table_children = []
    if not no_header:
        headers = [html.Th('구분', className='text-center', style={'fontSize': '0.72rem', 'width': '15%'})] \
            if show_index else []
        headers += [
            html.Th('전문분야', style={'fontSize': '0.72rem', 'width': '45%' if show_index else '55%'}),
            html.Th('Lv', className='text-center', style={'fontSize': '0.72rem', 'width': '15%', 'textAlign': 'center'}),
            html.Th('보유율', className='text-center', style={'fontSize': '0.72rem', 'width': '25%', 'textAlign': 'center'}),
        ]
        table_children.append(html.Thead(html.Tr(headers), className='table-light'))
    table_children.append(html.Tbody(rows))

    return dbc.Table(table_children, bordered=False, hover=True, size='sm', className='mb-0',
       style={'tableLayout': 'fixed', 'width': '100%'})


def owned_expertise_block(core_df, tech_df, rid, *, stacked: bool = False, show_tech_index: bool = True,
                           show_info_hover: bool = True, compact: bool = False):
    """보유 전문성 — 핵심기술(core_technology.csv) / 보유기술(tech_ownership.csv)을
    기본은 좌우로 나눠 표시(좌: 기술분야·핵심기술(등급 배지), 우: 전문분야별
    Lv·보유율, 상단에 E/R 직군 배지). stacked=True면 좌우 대신 핵심기술 아래에
    보유기술을 세로로 쌓는다(A4 인쇄처럼 가로 폭이 좁아 2단이 부담스러울 때).
    show_tech_index=False면 보유기술 표의 "구분"(1~5 순번) 열을 뺀다.
    show_info_hover=False면 "등급 개요"/"Lv 개요" 마우스 오버 안내(_info_hover())를
    아예 뺀다 — 종이 인쇄본에는 호버가 없어 의미가 없고, 이 함수가 화면·인쇄본
    양쪽에서 호출되면 같은 id를 가진 요소가 DOM에 중복되는 문제도 같이 없앤다.
    compact=True면 표 헤더를 없앤다(사용자 요청, A4 인쇄본 전용) — 핵심기술은
    표 대신 "(등급)분야 > 기술명" 텍스트 나열로, 보유기술은 헤더 없이 데이터
    행만 바로 보여준다. "핵심기술"/"보유기술" 섹션 제목 자체는 그대로 유지."""
    core = core_df[core_df['researcher_id'] == rid] if not core_df.empty else pd.DataFrame()
    tech = tech_df[tech_df['researcher_id'] == rid] if not tech_df.empty else pd.DataFrame()
    tech_row = tech.iloc[0] if not tech.empty else None
    e_support = tech_row.get('E_support') if tech_row is not None else None

    left_children = [
        html.P('핵심기술', style=_PANEL_TITLE_STYLE, className='mb-2'),
        _core_technology_table(core, compact=compact),
    ]
    if show_info_hover:
        left_children.append(_info_hover('grade-info-icon', '등급 개요', '등급 개요.png'))
    left = html.Div(left_children)

    right_title_children = [
        html.Span('보유기술', style=_PANEL_TITLE_STYLE),
        html.Span("('25년기준)", style={'fontSize': '0.68rem', 'color': _LEGEND_NEUTRAL, 'marginLeft': '3px'}),
    ]
    if e_support is not None:
        right_title_children.append(html.Div(_e_support_pill(e_support), className='ms-auto'))

    right_children = [
        html.Div(right_title_children, className='d-flex align-items-center mb-2'),
        _tech_ownership_table(tech_row, show_index=show_tech_index, no_header=compact),
    ]
    if show_info_hover:
        right_children.append(_info_hover('lv-info-icon', 'Lv 개요', 'lv 개요.png'))
    right = html.Div(right_children)

    if stacked:
        # 핵심기술/보유기술 사이 구분선을 뺀다(사용자 요청, A4 인쇄본
        # stacked=True 전용 — 화면(stacked=False) 좌우 배치는 border-start로
        # 계속 구분하므로 영향 없음). 구분선이 있을 때 그 위 여백용이던
        # pt-3도 함께 빼고 mt-3만 남긴다.
        return html.Div([left, html.Div(right, className='mt-3')])

    return dbc.Row([
        dbc.Col(left, md=6, className='pe-3'),
        dbc.Col(right, md=6, className='ps-3 border-start'),
    ], className='g-0')


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
