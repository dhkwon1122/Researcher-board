"""
화면 1: 조직별 우수 연구원 비교 — 전체 조직 조직장 석세션 후보 카드
"""

import base64
import mimetypes
import os
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import html

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

GRADE_BADGE_COLOR = {
    '가': 'warning', '나': 'success', '다': 'primary',
    '라': 'secondary', '마': 'danger', '-': 'light',
}


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


# ─── 후보 카드 빌더 ─────────────────────────────────────────────────────────────

def _candidate_card(r_info, rank_type, rank_order, eva, edu, inc, nur):
    rid    = str(r_info['researcher_id'])
    name   = str(r_info.get('name', '-'))
    dept   = str(r_info.get('department', '-'))
    pos    = str(r_info.get('position', '-'))
    gender = str(r_info.get('gender', '-'))
    try:
        age_str = f'{CURRENT_YEAR - int(r_info["birth_year"])}세'
    except (TypeError, ValueError, KeyError):
        age_str = '-'

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
    r_inc = inc[inc['researcher_id'] == rid] if not inc.empty else pd.DataFrame()
    if not r_inc.empty:
        sel_mask = r_inc['selected'].astype(str).isin(['True', 'Y', '1', 'true', 'y'])
        r_inc = r_inc[sel_mask].sort_values('year', ascending=False).head(3)
    award_items = [
        html.Li(
            f"{aw['year']}년{(' — ' + str(aw.get('category', ''))) if aw.get('category') else ''}",
            className='small',
        )
        for _, aw in r_inc.iterrows()
    ]
    award_section = _section('주요 시상이력', html.Ul(
        award_items or [html.Li('해당 없음', className='small text-muted')],
        className='ps-3 mb-0 small',
    ))

    # 기본인적사항 / 평가
    r_eva = eva[eva['researcher_id'] == rid] if not eva.empty else pd.DataFrame()
    grade_chips = []
    for yr in ['2024', '2025', '2026']:
        row = r_eva[r_eva['year'] == yr]
        grade = row.iloc[0]['grade'] if not row.empty else '-'
        grade_chips.append(html.Span([
            html.Small(f"'{yr[-2:]}", className='text-muted'),
            dbc.Badge(grade, color=GRADE_BADGE_COLOR.get(grade, 'light'), className='ms-1 me-2'),
        ]))
    basic_section = _section('기본인적사항 / 평가', html.Div([
        html.P([html.B(name), f'  {gender} / {age_str}'], className='small mb-1'),
        html.P(f'{dept}  |  {pos}', className='small text-muted mb-2'),
        html.Div(grade_chips, className='d-flex flex-wrap align-items-center'),
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


# ─── 조직 섹션 빌더 ─────────────────────────────────────────────────────────────

def _org_section(dept_name, org_code, suc, res, eva, edu, inc, nur):
    suc_org = suc[suc['org_code'] == org_code].copy()
    if suc_org.empty:
        return None

    suc_org['_s'] = suc_org['rank_type'].map({'Ready Now': 0, 'Ready Later': 1}).fillna(2)
    suc_org['rank_order'] = pd.to_numeric(suc_org['rank_order'], errors='coerce').fillna(99).astype(int)
    suc_org = suc_org.sort_values(['_s', 'rank_order']).reset_index(drop=True)

    cards = []
    for _, srow in suc_org.iterrows():
        rid = str(srow['researcher_id'])
        r_rows = res[res['researcher_id'] == rid]
        if r_rows.empty:
            continue
        card = _candidate_card(
            r_rows.iloc[0],
            str(srow['rank_type']),
            int(srow['rank_order']),
            eva, edu, inc, nur,
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
    ], className='mb-4')


# ─── 레이아웃 ────────────────────────────────────────────────────────────────────

def layout():
    try:
        res = _r('researchers')
        eva = _r('evaluations')
        edu = _r('education')
        inc = _r('incentive_selection')
        nur = _r('nurturing')
        suc = _r('succession')
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
    for df in (eva, inc, nur):
        if not df.empty and 'year' in df.columns:
            df['year'] = df['year'].astype(str)

    # 조직 목록 (succession에 등록된 org_code 기준, 이름은 researchers에서)
    org_order = suc['org_code'].unique()
    dept_map = {}
    if not res.empty:
        dept_map = res[['org_code', 'department']].drop_duplicates().set_index('org_code')['department'].to_dict()

    sections = []
    for org_code in sorted(org_order):
        dept_name = dept_map.get(org_code, org_code)
        sec = _org_section(dept_name, org_code, suc, res, eva, edu, inc, nur)
        if sec:
            sections.append(sec)

    return html.Div([
        html.H5(
            [html.I(className='bi bi-people-fill me-2 text-primary'),
             '조직별 우수 연구원 비교 (조직장 석세션)'],
            className='fw-bold mb-4 mt-1',
        ),
        *sections,
    ])
