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

_LEGEND_NEUTRAL = '#8c8c8c'


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


_PANEL_TITLE_STYLE = {'fontSize': '0.85rem', 'fontWeight': 600, 'color': '#1f1f1f'}
_GRADE_PILL_COLOR = '#3f8f57'
_E_SUPPORT_COLOR = '#1677ff'

_PRINT_SUB_HEADING_STYLE = {
    'display': 'inline-block',
    'backgroundColor': '#eef0f3',
    'border': '1px solid #d5d8dc',
    'borderRadius': '4px',
    'padding': '1px 8px',
    'fontSize': '0.78rem',
    'fontWeight': 700,
    'color': '#1f1f1f',
}


def print_sub_heading(text):
    """A4 인쇄본 박스 안의 하위 항목(핵심기술/보유기술/논문 실적/특허 실적/
    양성 이력/시상 이력/전문성 요약(LLM)/과제 수행·인사 발령 이력)을 네모
    박스로 감싸 "중제목"처럼 강조한다(사용자 요청 — "이 키워드들이 네모
    박스 같은 정도로 감싸져서 중제목 정도의 느낌으로 보여지면 좋겠어").
    화면(라이브) 탭에는 쓰지 않는다 — 인쇄본 전용."""
    return html.Div(text, style=_PRINT_SUB_HEADING_STYLE)


_LIST_MARKER_COLOR = '#8e8e93'


def bullet_list(items, *, class_name: str = 'small'):
    """기본 <ul>의 disc 마커 대신 작은 사각 마커 + hanging indent(줄바꿈된
    다음 줄도 마커가 아니라 텍스트 시작 위치에 맞춰 들여써짐)로 목록을
    보여준다(사용자 요청 — "disc 형태로 list가 만들어지는 건 너무 밋밋해").
    _core_technology_table()의 compact 모드(등급 아이콘 + flex 행)와 같은
    구조를 재사용한다."""
    return html.Div([
        html.Div([
            html.Span(style={
                'display': 'inline-block', 'flex': '0 0 5px', 'width': '5px', 'height': '5px',
                'borderRadius': '1px', 'backgroundColor': _LIST_MARKER_COLOR, 'marginTop': '6px',
                'marginRight': '6px',
            }),
            html.Span(item, className=class_name, style={'wordBreak': 'break-word'}),
        ], style={'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '3px'})
        for item in items
    ])


def plain_indent_list(items, *, class_name: str = 'small'):
    """마커(아이콘) 없이 살짝 들여쓰기만 된 상태로 항목을 한 줄씩 나열한다
    (사용자 요청 — "목록 아이콘 없이 약간 들여쓰기만 된 상태로 나열되게
    해줘"). bullet_list()와 달리 마커용 <span>이 없다."""
    return html.Div([
        html.Div(item, className=class_name, style={'marginLeft': '10px', 'marginBottom': '3px',
                                                      'wordBreak': 'break-word'})
        for item in items
    ])


_AI_TAG_STYLE = {
    'display': 'inline-flex', 'alignItems': 'center', 'gap': '3px', 'flex': '0 0 auto',
    'backgroundColor': '#eef1fb', 'border': '1px solid #dde2f5', 'borderRadius': '9px',
    'padding': '1px 7px', 'fontSize': '0.64rem', 'fontWeight': 600, 'color': '#5b6b8c',
}


def _ai_tag():
    """"by AI" 표기를 괄호로 감싼 텍스트가 아니라 아이콘 느낌의 작은 알약
    (pill) 배지로 보여준다(사용자 요청 — "by AI라는 글씨는 괄호에 넣지 않고
    아이콘 느낌으로 표현해줘. AI느낌이 나는 작은 픽토그램을 같이 넣어도
    좋아") — bootstrap-icons의 bi-stars(반짝임) 아이콘 + "by AI" 텍스트를
    옅은 남색 계열 배지에 담는다."""
    return html.Span([
        html.I(className='bi bi-stars', style={'fontSize': '0.68rem'}),
        html.Span('by AI'),
    ], style=_AI_TAG_STYLE)


def llm_summary_block(profile: dict | None, similar: list | None = None, name_map: dict | None = None,
                       *, include_responsibilities: bool = True, deemphasize_strength: bool = False):
    """전문성 요약(LLM) — 연구원 보유 전문성 분석.json의 핵심 분야(strength_fields)/
    키워드(strength_keywords)를 배지로, 주요 역할·책임(key_responsibilities)은
    불릿 목록(bullet_list(), disc 마커 대신 사각 마커 — 사용자 요청)으로,
    전문지식 및 역량(domain_knowledge_skill)은 마커 없이 들여쓰기만 된 목록
    (plain_indent_list() — 사용자 요청: "목록 아이콘 없이 약간 들여쓰기만
    된 상태로 나열되게 해줘")으로 보여준다.
    similar(researcher_similarity.json의 해당 연구원 항목 중 'similar' 리스트,
    시니어 우선으로 이미 정렬돼 있음)가 주어지면 시니어 3명·주니어 3명을 유사
    연구원 배지로 덧붙인다(생략하면 유사 연구원 섹션 자체를 건너뜀 — A4 인쇄
    요약처럼 지면이 좁을 때 사용). include_responsibilities=False면 주요 역할·
    책임 목록을 뺀다(같은 이유). 해당 연구원이 분석 대상이 아니거나 아직
    파이프라인을 실행하지 않아 데이터가 없으면 안내 문구만 표시한다.
    deemphasize_strength=True(A4 인쇄본 전용)면 Strength Field/Strength
    Keywords/전문지식 및 역량 라벨을 모두 print_sub_heading()의 네모 박스
    소제목으로 통일하고(사용자 요청 — "소제목 형태로 통일감 있게 표현해줘"),
    Strength Field/Keywords의 내용은 색깔 배지 대신 옅은 회색 콤마 나열
    텍스트로, marginLeft:10px로 들여써서(사용자 요청 — 전문지식 및 역량과
    동일하게) 보여준다(이전 요청 — "너무 강조되어 보인다... 힘을 빼줘"와
    절충 — 라벨은 다른 소제목들과 통일된 박스로 존재감을 주되, 내용 자체는
    화려한 배지 대신 차분한 텍스트로 유지). Strength Field 줄 오른쪽 끝에는
    _ai_tag()(아이콘 + "by AI" 알약 배지, 괄호 텍스트가 아님 — 사용자 요청)를
    붙인다(인쇄본에서 "전문성 요약(LLM)" 박스 제목을 없앤 대신, 이 블록이
    AI 생성 결과임을 표시할 자리가 필요해짐). 화면(라이브) 탭 호출부는 이
    인자를 넘기지 않아 기존
    배지+회색 텍스트 라벨 그대로다(제목 제거·(by AI) 표기 모두 인쇄본
    전용)."""
    if not profile:
        return html.Div('분석 데이터 없음', className='text-muted small p-1')

    fields = profile.get('strength_fields') or []
    keywords = profile.get('strength_keywords') or []
    responsibilities = profile.get('key_responsibilities') or []
    domain_skill = profile.get('domain_knowledge_skill') or []

    children = []
    if fields:
        if deemphasize_strength:
            children.append(html.Div([
                print_sub_heading('Strength Field'),
                _ai_tag(),
            ], className='d-flex justify-content-between align-items-center mb-1'))
            children.append(html.Div(', '.join(fields), className='small text-muted',
                                      style={'marginBottom': '6px', 'marginLeft': '10px'}))
        else:
            children.append(html.Div('Strength Field', className='small text-muted fw-semibold mb-1'))
            children.append(html.Div(
                [dbc.Badge(f, color='dark', className='me-1 mb-1') for f in fields],
            ))
    if keywords:
        if deemphasize_strength:
            children.append(html.Div(print_sub_heading('Strength Keywords'), className='mb-1'))
            children.append(html.Div(', '.join(keywords), className='small text-muted',
                                      style={'marginBottom': '6px', 'marginLeft': '10px'}))
        else:
            children.append(html.Div('Strength Keywords', className='small text-muted fw-semibold mt-2 mb-1'))
            children.append(html.Div(
                [dbc.Badge(k, color='secondary', className='me-1 mb-1') for k in keywords],
            ))
    if responsibilities and include_responsibilities:
        children.append(html.Div('주요 역할·책임', className='small text-muted fw-semibold mt-2 mb-1'))
        children.append(bullet_list(responsibilities))
    if domain_skill:
        if deemphasize_strength:
            children.append(html.Div(print_sub_heading('전문지식 및 역량'), className='mb-1'))
        else:
            children.append(html.Div('전문지식 및 역량', className='small text-muted fw-semibold mt-2 mb-1'))
        children.append(plain_indent_list(domain_skill))

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


def _grade_circle(grade: str, *, size: int = 18):
    """핵심기술 등급을 색깔 있는 동그라미 + 하얀 글씨 아이콘 형태로 강조한다
    (사용자 요청 — "기존처럼 강조될 수 있게 ... 아이콘 같은 형태로"). 기존
    `_pill()`(둥근 사각형, "B급"처럼 여러 글자)과 달리 정사각형 박스에
    `borderRadius: 50%`로 진짜 원을 만들고, 글자도 "급" 없이 등급 한 글자만
    담아 작은 아이콘 크기(기본 18px)에 맞춘다."""
    return html.Span(grade, style={
        'display': 'inline-flex', 'alignItems': 'center', 'justifyContent': 'center',
        'flex': f'0 0 {size}px', 'width': f'{size}px', 'height': f'{size}px',
        'borderRadius': '50%', 'backgroundColor': _GRADE_PILL_COLOR, 'color': '#ffffff',
        'fontSize': '0.68rem', 'fontWeight': 700, 'lineHeight': '1',
    })


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
    """compact=True면 표(기술분야/핵심기술 2열 + 헤더) 대신 "분야 > 기술명" 한
    줄짜리 텍스트를 항목마다 나열한다(사용자 요청, A4 인쇄본 전용 — 화면
    기본값 False는 기존 표 그대로). 등급은 텍스트 접두사가 아니라
    `_grade_circle()`(색깔 있는 동그라미 + 하얀 글씨 아이콘)로 강조해
    보여준다(사용자 요청 — "핵심기술 등급은 기존처럼 강조될 수 있게 ...
    아이콘 같은 형태로")."""
    if core_df.empty:
        return html.Div('핵심기술 데이터 없음', className='text-muted small')

    if compact:
        lines = []
        for _, row in core_df.iterrows():
            field = str(row.get('tech_field', '')).strip()
            name = str(row.get('tech_name', '')).strip()
            grade = _clean_num_str(row.get('tech_grade', '')) or '-'
            lines.append(html.Div([
                _grade_circle(grade),
                html.Span(f'{field} > {name}', className='small', style={'marginLeft': '5px'}),
            ], style={'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '3px',
                       'wordBreak': 'break-word'}))
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
    no_header=True면 표 헤더 행(구분/전문분야/Lv/보유율)을 빼고 데이터 행만
    바로 보여준다(사용자 요청, A4 인쇄본 전용). 헤더가 없으면 숫자만 보고는
    Lv인지 알 수 없어 값 자체에 "Lv" 접두사를 붙이고(예: "Lv1", 사용자
    요청 — "Lv0, 100% 정도의 글자만 들어갈 수 있으면 되니"), Lv·보유율 열
    폭을 그 글자 수에 맞춰 최소화해 남는 폭을 보유기술명 열에 몰아준다.
    표 헤더가 없으면 <Th> width로 열 폭을 정할 수 없어 <colgroup>을 대신
    쓴다. 원본 tech_ownership.csv의 레벨(N) 값 자체가 이미 "Lv3"처럼 접두사를
    포함해서 들어오는 경우가 있어(원천 엑셀 셀 표기가 그대로 문자열로
    보존됨), 값이 이미 "Lv"로 시작하면 접두사를 또 붙이지 않는다("LvLv3"
    방지, 사용자 버그 리포트)."""
    if tech_row is None:
        return html.Div('보유기술 데이터 없음', className='text-muted small')

    rows = []
    for i in range(1, 6):
        name = str(tech_row.get(f'tech_{i}', '')).strip()
        if not name or name in ('nan', 'None'):
            continue
        lv = _clean_num_str(tech_row.get(f'lv_{i}', ''))
        portion = _clean_num_str(tech_row.get(f'portion_{i}', ''))
        if lv:
            if no_header:
                lv_disp = lv if lv.upper().startswith('LV') else f'Lv{lv}'
            else:
                lv_disp = lv
        else:
            lv_disp = '-'
        cells = [html.Td(str(i), className='small text-center')] if show_index else []
        cells += [
            html.Td(name, className='small', style={'wordBreak': 'break-word'}),
            html.Td(lv_disp, className='small text-center', style={'textAlign': 'center'}),
            html.Td(f'{portion}%' if portion else '-', className='small text-center', style={'textAlign': 'center'}),
        ]
        rows.append(html.Tr(cells))

    if not rows:
        return html.Div('보유기술 데이터 없음', className='text-muted small')

    table_children = []
    if no_header:
        cols = [html.Col(style={'width': '20px'})] if show_index else []
        cols += [
            html.Col(),  # 전문분야(보유기술명) — Lv·보유율이 안 쓰는 나머지 폭을 그대로 가져간다
            html.Col(style={'width': '28px'}),
            html.Col(style={'width': '36px'}),
        ]
        table_children.append(html.Colgroup(cols))
    else:
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
    행만 바로 보여준다. "핵심기술"/"보유기술" 섹션 제목도 compact일 때는
    `print_sub_heading()`(네모 박스로 감싼 중제목)으로 바뀐다(사용자 요청)."""
    core = core_df[core_df['researcher_id'] == rid] if not core_df.empty else pd.DataFrame()
    tech = tech_df[tech_df['researcher_id'] == rid] if not tech_df.empty else pd.DataFrame()
    tech_row = tech.iloc[0] if not tech.empty else None
    e_support = tech_row.get('E_support') if tech_row is not None else None

    left_title = html.Div(print_sub_heading('핵심기술'), className='mb-2') if compact \
        else html.P('핵심기술', style=_PANEL_TITLE_STYLE, className='mb-2')
    left_children = [
        left_title,
        _core_technology_table(core, compact=compact),
    ]
    if show_info_hover:
        left_children.append(_info_hover('grade-info-icon', '등급 개요', '등급 개요.png'))
    left = html.Div(left_children)

    right_title_main = print_sub_heading('보유기술') if compact else html.Span('보유기술', style=_PANEL_TITLE_STYLE)
    right_title_children = [
        right_title_main,
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
