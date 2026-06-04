"""
화면 1: 조직별 우수 연구원 비교 — 조직장 석세션 후보 카드
"""

import base64
import mimetypes
import os
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, callback, html, dcc

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


# ─── 후보 카드 빌더 ─────────────────────────────────────────────────────────────

def _candidate_card(r_info, rank_type, rank_order, eva, edu, inc, nur):
    rid  = str(r_info['researcher_id'])
    name = str(r_info.get('name', '-'))
    dept = str(r_info.get('department', '-'))
    pos  = str(r_info.get('position', '-'))
    gender = str(r_info.get('gender', '-'))
    try:
        age_str = f'{CURRENT_YEAR - int(r_info["birth_year"])}세'
    except (TypeError, ValueError, KeyError):
        age_str = '-'

    label, badge_color = RANK_META.get(
        (rank_type, rank_order),
        (f'{rank_type} {rank_order}순위', 'secondary'),
    )

    # ── 사진 ────────────────────────────────────────────────────────────────────
    src = _load_photo_src(rid)
    photo_el = (
        html.Img(src=src,
                 style={'width': '100%', 'maxHeight': '130px',
                        'objectFit': 'contain', 'borderRadius': '6px'})
        if src else _avatar(name, 70)
    )

    # ── 학력 ────────────────────────────────────────────────────────────────────
    r_edu = edu[edu['researcher_id'] == rid] if not edu.empty else pd.DataFrame()
    edu_items = []
    for deg in ['박사', '석사', '학사']:
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

    # ── 주요 시상이력 ────────────────────────────────────────────────────────────
    r_inc = (inc[inc['researcher_id'] == rid] if not inc.empty else pd.DataFrame())
    if not r_inc.empty:
        sel_mask = r_inc['selected'].astype(str).isin(['True', 'Y', '1', 'true', 'y'])
        r_inc = r_inc[sel_mask].sort_values('year', ascending=False).head(3)
    award_items = []
    for _, aw in r_inc.iterrows():
        cat = str(aw.get('category', ''))
        award_items.append(html.Li(
            f"{aw['year']}년{(' — ' + cat) if cat else ''}",
            className='small',
        ))
    award_section = _section('주요 시상이력', html.Ul(
        award_items or [html.Li('해당 없음', className='small text-muted')],
        className='ps-3 mb-0 small',
    ))

    # ── 기본인적사항 / 평가 ─────────────────────────────────────────────────────
    r_eva = eva[eva['researcher_id'] == rid] if not eva.empty else pd.DataFrame()
    grade_chips = []
    for yr in ['2024', '2025', '2026']:
        row = r_eva[r_eva['year'].astype(str) == yr]
        grade = row.iloc[0]['grade'] if not row.empty else '-'
        grade_chips.append(html.Span([
            html.Small(f"'{yr[-2:]}", className='text-muted'),
            dbc.Badge(grade, color=GRADE_BADGE_COLOR.get(grade, 'light'),
                      className='ms-1 me-2'),
        ]))
    basic_section = _section('기본인적사항 / 평가', html.Div([
        html.P([html.B(name), f'  {gender} / {age_str}'],
               className='small mb-1'),
        html.P(f'{dept}  |  {pos}', className='small text-muted mb-2'),
        html.Div(grade_chips, className='d-flex flex-wrap align-items-center'),
    ]))

    # ── 주요 양성이력 ────────────────────────────────────────────────────────────
    r_nur = nur[nur['researcher_id'] == rid] if not nur.empty else pd.DataFrame()
    if not r_nur.empty:
        r_nur = r_nur.sort_values('year', ascending=False).head(3)
    nur_items = []
    for _, nr in r_nur.iterrows():
        nur_items.append(html.Li(
            f"{nr['year']}년  {nr.get('category', '')} — {nr.get('content', '')}  ({nr.get('result', '')})",
            className='small',
        ))
    nur_section = _section('주요 양성이력', html.Ul(
        nur_items or [html.Li('해당 없음', className='small text-muted')],
        className='ps-3 mb-0 small',
    ))

    # ── 카드 조립 (모형과 동일한 2×2 그리드) ─────────────────────────────────────
    return dbc.Card([
        dbc.CardHeader(
            dbc.Badge(label, color=badge_color, className='fs-6 px-3 py-2'),
            className='text-center bg-white border-bottom-0 pb-1',
        ),
        dbc.CardBody([
            # 윗줄: [사진] [학력 / 주요 시상이력]
            dbc.Row([
                dbc.Col(photo_el, width=4,
                        className='d-flex align-items-center justify-content-center'),
                dbc.Col([edu_section, html.Div(className='mb-2'), award_section], width=8),
            ], className='g-2 mb-2'),
            # 아랫줄: [기본인적사항/평가] [주요 양성이력]
            dbc.Row([
                dbc.Col(basic_section, width=6),
                dbc.Col(nur_section, width=6),
            ], className='g-2'),
        ], className='p-2'),
    ], className='shadow-sm h-100')


def _section(title, body):
    return html.Div([
        html.P(title, className='fw-bold small text-primary mb-1'),
        body,
    ], className='bg-light rounded p-2')


# ─── 레이아웃 ────────────────────────────────────────────────────────────────────

def layout():
    try:
        res = _r('researchers')
        orgs = [
            {'label': row['department'], 'value': row['org_code']}
            for _, row in (
                res[['department', 'org_code']]
                .drop_duplicates()
                .sort_values('org_code')
                .iterrows()
            )
        ]
        default_org = orgs[0]['value'] if orgs else None
    except Exception:
        orgs, default_org = [], None

    return html.Div([
        html.H5(
            [html.I(className='bi bi-people-fill me-2 text-primary'),
             '조직별 우수 연구원 비교 (조직장 석세션)'],
            className='fw-bold mb-3 mt-1',
        ),
        dbc.Card(
            dbc.CardBody(dbc.Row([
                dbc.Col([
                    dbc.Label('조직 선택', className='fw-semibold small text-muted mb-1'),
                    dcc.Dropdown(
                        id='org-filter',
                        options=orgs,
                        value=default_org,
                        clearable=False,
                        className='dash-dropdown',
                    ),
                ], md=4),
            ], className='g-2')),
            className='mb-3 shadow-sm',
        ),
        html.Div(id='succession-cards'),
    ])


# ─── 콜백 ────────────────────────────────────────────────────────────────────────

@callback(
    Output('succession-cards', 'children'),
    Input('org-filter', 'value'),
)
def update_cards(org_code):
    if not org_code:
        return html.P('조직을 선택하세요.', className='text-muted')

    try:
        res = _r('researchers')
        eva = _r('evaluations')
        edu = _r('education')
        inc = _r('incentive_selection')
        nur = _r('nurturing')
        suc = _r('succession')
    except Exception as e:
        return html.P(f'데이터 로드 실패: {e}', className='text-danger')

    if suc.empty:
        return dbc.Alert(
            '석세션 데이터가 없습니다. '
            'succession_raw 파일을 data/raw/ 에 넣거나 '
            'python pipeline/generate_sample_data.py 로 샘플 데이터를 생성하세요.',
            color='warning',
        )

    suc_org = suc[suc['org_code'] == org_code].copy()
    if suc_org.empty:
        return html.P('해당 조직의 석세션 데이터가 없습니다.', className='text-muted')

    # Ready Now → Ready Later, 오름차순 정렬
    suc_org['_s'] = suc_org['rank_type'].map({'Ready Now': 0, 'Ready Later': 1}).fillna(2)
    suc_org['rank_order'] = pd.to_numeric(suc_org['rank_order'], errors='coerce').fillna(99).astype(int)
    suc_org = suc_org.sort_values(['_s', 'rank_order']).reset_index(drop=True)

    # year 컬럼을 문자열로 통일
    for df in (eva, inc, nur):
        if not df.empty and 'year' in df.columns:
            df['year'] = df['year'].astype(str)

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
        cards.append(dbc.Col(card, lg=4, md=6, className='mb-3'))

    if not cards:
        return html.P('표시할 후보가 없습니다.', className='text-muted')

    return dbc.Row(cards, className='g-3')
