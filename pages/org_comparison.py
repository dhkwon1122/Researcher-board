"""
화면 1: 조직별 우수 연구원 비교 — 전체 조직 조직장 석세션 후보 카드
"""

import base64
import math
import mimetypes
import os
from datetime import date, datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import ClientsideFunction, Input, Output, clientside_callback, dcc, html

dash.register_page(__name__, path='/', name='조직별 비교', title='조직별 우수 연구원 비교')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')
RAW_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')

CURRENT_YEAR = datetime.now().year

RANK_META = {
    ('Ready Now',   1): ('Ready Now 1순위',   'danger'),
    ('Ready Now',   2): ('Ready Now 2순위',   'warning'),
    ('Ready Later', 1): ('Ready Later 1순위', 'info'),
    ('Ready Later', 2): ('Ready Later 2순위', 'secondary'),
}

AWARD_TYPES = {'그룹표창', '대표이사표창', '대표이사표창(시상금미포함)', '부문표창'}


# ─── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _r(name):
    path = os.path.join(DATA_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, encoding='utf-8-sig', dtype=str)


def _load_photo_src(rid_str):
    for ext in ('png', 'jpg', 'jpeg'):
        f = os.path.join(RAW_DIR, f'{rid_str}.{ext}')
        if os.path.exists(f):
            mime = mimetypes.guess_type(f)[0] or f'image/{ext}'
            with open(f, 'rb') as fp:
                enc = base64.b64encode(fp.read()).decode('utf-8')
            return f'data:{mime};base64,{enc}'
    return None


def _avatar(name, size=64):
    colors = ['#4a90e2', '#e25757', '#52c41a', '#f5a623', '#9b59b6', '#1abc9c']
    color = colors[hash(name) % len(colors)]
    return html.Div(
        name[:2] if name else '?',
        style={
            'width': f'{size}px', 'height': f'{size}px', 'borderRadius': '50%',
            'background': color, 'color': '#fff', 'display': 'flex',
            'alignItems': 'center', 'justifyContent': 'center',
            'fontWeight': 'bold', 'fontSize': f'{size // 3}px', 'margin': '0 auto',
        },
    )


def _section(title, body):
    return html.Div([
        html.P(title, className='fw-bold small text-primary mb-1'),
        body,
    ], className='bg-light rounded p-2')


def _parse_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ('', 'nan', 'None', 'NaT'):
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _info_lines(r_info):
    """연구원 프로필 화면과 동일한 2줄 표기 생성.
    1줄: 성명(성별/나이)   2줄: 직급-직급연차(근속)
    """
    name = str(r_info.get('name', '-'))
    gender = str(r_info.get('gender', '')).strip()
    try:
        age_str = f'{CURRENT_YEAR - int(float(r_info["birth_year"]))}세'
    except (TypeError, ValueError, KeyError):
        age_str = '-'
    position = str(r_info.get('position', '')).strip()

    hire_dt = _parse_date(r_info.get('hire_date'))
    tenure = round((date.today() - hire_dt).days / 365, 1) if hire_dt else None

    promo_dt = _parse_date(r_info.get('promotion_date'))
    position_year = math.ceil((date(2027, 3, 1) - promo_dt).days / 365) if promo_dt else None

    line1 = f'{name}({gender}/{age_str})' if gender else f'{name}({age_str})'
    if position:
        if position_year is not None and tenure is not None:
            line2 = f'{position}-{position_year}({tenure:.1f}년)'
        elif tenure is not None:
            line2 = f'{position}({tenure:.1f}년)'
        else:
            line2 = position
    else:
        line2 = f'{tenure:.1f}년 근속' if tenure is not None else ''
    return line1, line2


def _eval_string(r_eva):
    """최근 3년 평가 등급을 '가나다' 형태로 연결. 없으면 'O'."""
    chars = []
    for yr in ['2024', '2025', '2026']:
        row = r_eva[r_eva['year'].astype(str) == yr] if not r_eva.empty else pd.DataFrame()
        g = str(row.iloc[0]['grade']).strip() if not row.empty else ''
        chars.append(g if g and g not in ('nan', '-', '') else 'O')
    return ''.join(chars)


def _incentive_string(r_inc):
    """최근 3년 인센티브 등급(S/A/B/C)을 한 글자씩 연결. 없으면 '-'."""
    def _char(row):
        cat = str(row.get('category', '')).strip().upper()
        if cat in ('S', 'A', 'B', 'C'):
            return cat
        return '-'

    chars = []
    for yr in ['2024', '2025', '2026']:
        row = r_inc[r_inc['year'].astype(str) == yr] if not r_inc.empty else pd.DataFrame()
        chars.append(_char(row.iloc[0]) if not row.empty else '-')
    return ''.join(chars)


# ─── 후보 카드 빌더 ─────────────────────────────────────────────────────────────

def _candidate_card(r_info, rank_type, rank_order, eva, edu, awd, nur, inc):
    rid    = str(r_info['researcher_id'])
    name   = str(r_info.get('name', '-'))

    label, badge_color = RANK_META.get(
        (rank_type, rank_order),
        (f'{rank_type} {rank_order}순위', 'secondary'),
    )

    # 사진
    src = _load_photo_src(rid)
    photo_el = (
        html.Img(src=src,
                 style={'width': '100%', 'maxHeight': '130px',
                        'objectFit': 'contain', 'borderRadius': '6px'})
        if src else _avatar(name, 70)
    )

    # 학력
    r_edu = edu[edu['researcher_id'] == rid] if not edu.empty else pd.DataFrame()
    edu_items = []
    for deg in ['박사', '석사', '학사', '전문대', '고교']:
        row = r_edu[r_edu['degree'] == deg]
        if not row.empty:
            r0 = row.iloc[0]
            edu_items.append(html.Li(
                f"{deg} | {r0.get('major', '-')} | {r0.get('school', '-')} ({r0.get('graduation_year', '-')})",
                className='small',
            ))
    edu_section = _section('학력', html.Ul(
        edu_items or [html.Li('데이터 없음', className='small text-muted')],
        className='ps-3 mb-0 small',
    ))

    # 주요 시상이력
    r_awd = awd[awd['researcher_id'] == rid].copy() if not awd.empty else pd.DataFrame()
    if not r_awd.empty:
        r_awd = r_awd[r_awd['award_type'].astype(str).str.strip().isin(AWARD_TYPES)]
        r_awd = r_awd.sort_values('award_date', ascending=False).head(3)
    award_items = []
    for _, aw in r_awd.iterrows():
        yr    = str(aw.get('year', str(aw.get('award_date', ''))[:4])).strip()
        aname = str(aw.get('award_name', '')).strip()
        desc  = str(aw.get('description', '')).strip()
        yr_label = f"'{yr[-2:]}" if len(yr) >= 2 else yr
        parts = [p for p in [yr_label, aname, desc] if p and p not in ('nan',)]
        award_items.append(html.Li(
            ' / '.join(parts) if parts else '-',
            className='small',
        ))
    award_section = _section('주요 시상이력', html.Ul(
        award_items or [html.Li('해당 없음', className='small text-muted')],
        className='ps-3 mb-0 small',
    ))

    # 기본인적사항 / 평가
    line1, line2 = _info_lines(r_info)
    r_eva = eva[eva['researcher_id'] == rid] if not eva.empty else pd.DataFrame()
    r_inc = inc[inc['researcher_id'] == rid] if not inc.empty else pd.DataFrame()
    eval_str = _eval_string(r_eva)
    inc_str  = _incentive_string(r_inc)
    basic_section = _section('기본인적사항 / 평가', html.Div([
        html.P(line1, className='small fw-bold mb-0'),
        html.P(line2, className='small text-muted mb-2'),
        html.Div([
            html.Span('평가 ', className='text-muted small'),
            html.Span(eval_str, className='small fw-bold me-3',
                      style={'letterSpacing': '0.15em'}),
            html.Span('인센티브 ', className='text-muted small'),
            html.Span(inc_str, className='small fw-bold',
                      style={'letterSpacing': '0.15em'}),
        ], className='d-flex flex-wrap align-items-center'),
    ]))

    # 주요 양성이력
    r_nur = nur[nur['researcher_id'] == rid] if not nur.empty else pd.DataFrame()
    if not r_nur.empty:
        sort_col = 'start_date' if 'start_date' in r_nur.columns else (
                   'year' if 'year' in r_nur.columns else r_nur.columns[0])
        r_nur = r_nur.sort_values(sort_col, ascending=False).head(3)
    nur_items = []
    for _, nr in r_nur.iterrows():
        start = str(nr.get('start_date', '')).strip()
        end   = str(nr.get('end_date', '')).strip()
        sy    = start[:4] if len(start) >= 4 else ''
        ey    = end[:4]   if len(end)   >= 4 else ''
        if sy:
            yr_label = f"'{sy[-2:]}"
            if ey and ey > sy:
                yr_label += f"~'{ey[-2:]}"
        else:
            yr_label = ''
        sub     = str(nr.get('subcategory', '')).strip()
        country = str(nr.get('country', '')).strip()
        inst    = str(nr.get('institution', '')).strip()
        loc_parts = [p for p in [country, inst] if p and p not in ('nan',)]
        loc = ' '.join(loc_parts) if loc_parts else ''
        parts = [p for p in [yr_label, sub, loc] if p and p not in ('nan',)]
        nur_items.append(html.Li(
            ' / '.join(parts) if parts else '-',
            className='small',
        ))
    nur_section = _section('주요 양성이력', html.Ul(
        nur_items or [html.Li('해당 없음', className='small text-muted')],
        className='ps-3 mb-0 small',
    ))

    return dbc.Card([
        dbc.CardHeader(
            dbc.Badge(label, color=badge_color, className='fs-6 px-3 py-2'),
            className='text-center bg-white border-bottom-0 pb-1',
        ),
        dbc.CardBody([
            dbc.Row([
                dbc.Col(photo_el, width=4,
                        className='d-flex align-items-center justify-content-center'),
                dbc.Col([edu_section, html.Div(className='mb-2'), award_section], width=8),
            ], className='g-2 mb-2'),
            dbc.Row([
                dbc.Col(basic_section, width=4),
                dbc.Col(nur_section, width=8),
            ], className='g-2'),
        ], className='p-2'),
    ], className='shadow-sm h-100')


# ─── 부서 섹션 빌더 ─────────────────────────────────────────────────────────────

def _dept_section(dept_name, suc_dept, res, eva, edu, awd, nur, inc):
    """동일 현소속부서명 소속 우수 연구원을 한 행(섹션)으로 표시."""
    s = suc_dept.copy()
    if s.empty:
        return None

    s['_s'] = s['rank_type'].map({'Ready Now': 0, 'Ready Later': 1}).fillna(2)
    s['rank_order'] = pd.to_numeric(s['rank_order'], errors='coerce').fillna(99).astype(int)
    s = s.sort_values(['_s', 'rank_order']).reset_index(drop=True)

    cards = []
    for _, srow in s.iterrows():
        rid = str(srow['researcher_id'])
        r_rows = res[res['researcher_id'] == rid]
        if r_rows.empty:
            continue
        card = _candidate_card(
            r_rows.iloc[0],
            str(srow['rank_type']),
            int(srow['rank_order']),
            eva, edu, awd, nur, inc,
        )
        cards.append(dbc.Col(card, lg=3, md=6, className='mb-2'))

    if not cards:
        return None

    return html.Div([
        html.Div([
            html.I(className='bi bi-building me-2 text-primary'),
            html.Span(dept_name, className='fw-bold fs-6'),
        ], className='mb-2 pb-1 border-bottom border-primary border-2'),
        dbc.Row(cards, className='g-3'),
    ], className='mb-4 org-section')


# ─── 레이아웃 ────────────────────────────────────────────────────────────────────

def layout():
    try:
        res = _r('researchers')
        eva = _r('evaluations')
        edu = _r('education')
        awd = _r('awards')
        nur = _r('nurturing')
        suc = _r('succession')
        inc = _r('incentive_selection')
    except Exception as e:
        return html.P(f'데이터 로드 실패: {e}', className='text-danger p-3')

    if suc.empty:
        return html.Div([
            html.H5([html.I(className='bi bi-people-fill me-2 text-primary'),
                     '조직별 우수 연구원 비교 (조직장 석세션)'],
                    className='fw-bold mb-3 mt-1'),
            dbc.Alert(
                'succession 데이터가 없습니다. '
                'python pipeline/generate_sample_data.py 로 샘플 데이터를 생성하세요.',
                color='warning',
            ),
        ])

    # year 컬럼 문자열 통일
    for df in (eva, nur):
        if not df.empty and 'year' in df.columns:
            df['year'] = df['year'].astype(str)

    # 현소속부서명(researchers.department) 기준으로 그룹화
    if not res.empty and 'department' in res.columns:
        dept_map = (res[['researcher_id', 'department']]
                    .drop_duplicates('researcher_id')
                    .set_index('researcher_id')['department'].to_dict())
    else:
        dept_map = {}
    suc = suc.copy()
    suc['department'] = suc['researcher_id'].astype(str).map(dept_map).fillna('(소속부서 미상)')

    sections = []
    for dept_name in sorted(suc['department'].unique()):
        suc_dept = suc[suc['department'] == dept_name]
        sec = _dept_section(dept_name, suc_dept, res, eva, edu, awd, nur, inc)
        if sec:
            sections.append(sec)

    return html.Div([
        dbc.Row([
            dbc.Col(
                html.H5(
                    [html.I(className='bi bi-people-fill me-2 text-primary'),
                     '조직별 우수 연구원 비교 (조직장 석세션)'],
                    className='fw-bold mb-0 mt-1',
                ),
            ),
            dbc.Col(
                html.Button(
                    [html.I(className='bi bi-printer me-1'), 'A3 인쇄'],
                    id='print-btn',
                    n_clicks=0,
                    className='btn btn-outline-secondary btn-sm no-print',
                ),
                width='auto',
                className='d-flex align-items-center',
            ),
        ], justify='between', align='center', className='mb-4'),
        html.Div(id='_print-dummy', style={'display': 'none'}),
        *sections,
    ])


clientside_callback(
    "function(n) { if (n > 0) { window.print(); } return ''; }",
    Output('_print-dummy', 'children'),
    Input('print-btn', 'n_clicks'),
    prevent_initial_call=True,
)
