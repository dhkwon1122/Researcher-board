"""
연구원 개별 프로필 — 선택한 항목만 골라 인쇄/PDF로 출력하는 화면 구성.

레이아웃(사용자 확정, "요약 1페이지"형 A안):
  상단 — 인사정보 밴드(사진 + 선택한 인사정보 항목들을 2열로 배치)
  하단 — 전문성 요약 직사각형(좌: 전문성 요약(LLM)+유사 연구원 텍스트,
         우: 보유 전문성 표) 하나가 좌우 전체 폭을 쓰고, 그 아래 과제/논문/
         특허를 3장의 카드로 나란히 배치(사용자 확정: 전문성 요약은 정사각형
         카드가 아니라 전체 폭 직사각형으로).

화면·엑셀 다운로드에 이미 있는 렌더러(components.profile_sections/detail_tabs/
timeline_view)를 그대로 재사용해, 같은 데이터가 화면마다 다르게 계산되는 걸
막는다 — 이 모듈은 그 결과물을 인쇄용 틀(상단 밴드/전체폭 직사각형/카드 3열)
에 배치하는 역할만 한다.
"""

from datetime import datetime

from dash import dcc, html

from components.detail_tabs import llm_summary_block, owned_expertise_block, patents_tab, publications_tab
from components.profile_sections import (
    award_block,
    comments_block,
    education_block,
    evaluation_incentive_block,
    leadership_figure,
    nurturing_block,
    photo_block,
    tasks_block,
)
from components.timeline_data import job_points
from components.timeline_view import _hr_table, filter_hr_rows
from services.evaluations import evaluation_years

# (key, 체크리스트 라벨, 필요 권한 — None이면 항상 노출)
PERSONNEL_FIELDS = [
    ('education', '학력', None),
    ('evaluation', '평가 · 인센티브 이력', 'view_evaluation'),
    ('nurturing', '양성 이력', None),
    ('award', '시상 이력', None),
    ('hr_orders', '인사발령 이력', None),
    ('leadership', '리더십 진단', None),
    ('comments', '인물 코멘트', 'view_comments'),
]

# 유사 연구원은 llm_summary_block이 전문성 요약과 한 덩어리로 이미 보여주는
# 항목이라(화면의 "전문성 요약(LLM)" 패널과 동일 구성) 별도 체크박스로 안 쪼갠다.
EXPERTISE_FIELDS = [
    ('expertise_summary', '전문성 요약 (LLM) · 유사 연구원', None),
    ('owned_expertise', '보유 전문성 표', None),
    ('tasks', '과제 수행 이력', None),
    ('job_profile', '직무 이력', None),
    ('publications', '논문 요약', None),
    ('patents', '특허 요약', None),
]

# 인물 코멘트는 민감정보라 기본 미포함(사용자 요청 반영).
DEFAULT_PERSONNEL = ['education', 'evaluation', 'nurturing', 'award', 'hr_orders', 'leadership']
DEFAULT_EXPERTISE = [key for key, _label, _perm in EXPERTISE_FIELDS]


def _as_list(children) -> list:
    """llm_summary_block()은 데이터가 있으면 list, 없으면 단일 html.Div를
    반환해 반환 타입이 갈린다 — 항상 리스트로 맞춰서 다루기 쉽게 한다."""
    return children if isinstance(children, list) else [children]


def _field(label: str, content) -> html.Div:
    return html.Div([
        html.P(label, className='print-field-label'),
        content,
    ], className='print-field')


def _personnel_band(rid: str, researcher_row, tables: dict, selected: list, leadership_year) -> html.Div:
    photo_col = html.Div(
        photo_block(rid, str(researcher_row.get('name', '')), researcher_row, datetime.now().year),
        className='print-photo-col',
    )

    dept = str(researcher_row.get('department', '') or '').strip()
    org = str(researcher_row.get('org_code', '') or '').strip()
    hire_date = str(researcher_row.get('hire_date', '') or '').strip()[:10]
    org_label = dept + (f' ({org})' if org else '')
    header_line = html.Div([
        html.Span(org_label or '-'),
        html.Span(f'입사일 {hire_date}' if hire_date else ''),
    ], className='print-header-line')

    fields = [header_line]
    if 'education' in selected:
        fields.append(_field('학력', education_block(tables['education'], rid)))
    if 'evaluation' in selected:
        years = sorted(evaluation_years()[0])
        fields.append(_field(
            '평가 · 인센티브',
            evaluation_incentive_block(tables['evaluations'], tables['incentive_selection'], rid, years),
        ))
    if 'nurturing' in selected:
        fields.append(_field('양성 이력', nurturing_block(tables['nurturing'], rid, limit=5)))
    if 'award' in selected:
        fields.append(_field('시상 이력', award_block(tables['awards'], rid)))
    if 'hr_orders' in selected:
        hr_rows = filter_hr_rows(tables['hr_orders'], rid).head(6)
        fields.append(_field('인사발령 이력', _hr_table(hr_rows)))
    if 'leadership' in selected and leadership_year:
        fig = leadership_figure(tables['leadership'], rid, leadership_year)
        fields.append(_field('리더십 진단', dcc.Graph(
            figure=fig, config={'staticPlot': True, 'displayModeBar': False},
            style={'height': '190px'},
        )))
    if 'comments' in selected:
        fields.append(_field('인물 코멘트', comments_block(tables['comments'], rid)))

    return html.Div([photo_col, html.Div(fields, className='print-info-grid')], className='print-band')


def _expertise_rect(rid: str, tables: dict, profile: dict | None, similar: list, name_map: dict,
                     selected: list) -> html.Div | None:
    left = None
    if 'expertise_summary' in selected:
        left = html.Div(_as_list(llm_summary_block(profile, similar, name_map)), className='print-expertise-text')

    right = None
    if 'owned_expertise' in selected:
        right = html.Div(
            owned_expertise_block(tables['core_technology'], tables['tech_ownership'], rid),
            className='print-expertise-table',
        )

    cols = [c for c in (left, right) if c is not None]
    if not cols:
        return None
    return html.Div([
        html.P('전문성 요약', className='print-rect-title'),
        html.Div(cols, className='print-rect-cols'),
    ], className='print-rect')


def _job_profile_lines(job_df, rid: str):
    rows = job_df[job_df['researcher_id'] == rid] if not job_df.empty else job_df
    points = job_points(rows)
    if not points:
        return None
    items = [
        html.Li(
            f"{p['name']} ({p['start'].strftime('%y')}~{p['end'].strftime('%y') if p['end'] else '현재'})",
            className='small',
        )
        for p in points
    ]
    return html.Div([
        html.P('직무 이력', className='print-subtitle'),
        html.Ul(items, className='ps-3 mb-0 small'),
    ])


def _cards_row(rid: str, tables: dict, selected: list) -> html.Div | None:
    cards = []
    if 'tasks' in selected or 'job_profile' in selected:
        body = [tasks_block(tables['tasks'], rid)] if 'tasks' in selected else []
        if 'job_profile' in selected:
            extra = _job_profile_lines(tables['job_profile'], rid)
            if extra is not None:
                body.append(extra)
        if body:
            cards.append(html.Div([
                html.P('과제 수행 이력', className='print-card-title'),
                html.Div(body, className='print-card-body'),
            ], className='print-card'))
    if 'publications' in selected:
        cards.append(html.Div([
            html.P('논문 요약', className='print-card-title'),
            html.Div(publications_tab(tables['publications'], rid), className='print-card-body'),
        ], className='print-card'))
    if 'patents' in selected:
        cards.append(html.Div([
            html.P('특허 요약', className='print-card-title'),
            html.Div(patents_tab(tables['patents'], rid), className='print-card-body'),
        ], className='print-card'))
    return html.Div(cards, className='print-cards-row') if cards else None


def build_print_sheet(rid: str, researcher_row, tables: dict, profile: dict | None, similar: list,
                       name_map: dict, leadership_year, selected_personnel: list,
                       selected_expertise: list) -> html.Div:
    band = _personnel_band(rid, researcher_row, tables, selected_personnel, leadership_year)
    rect = _expertise_rect(rid, tables, profile, similar, name_map, selected_expertise)
    cards = _cards_row(rid, tables, selected_expertise)

    body = [band] + [part for part in (rect, cards) if part is not None]

    header = html.Div([
        html.Span(f"{researcher_row.get('name', '')} 프로필", className='print-doc-title'),
        html.Span(f"출력일 {datetime.now().strftime('%Y-%m-%d')}", className='print-doc-date'),
    ], className='print-doc-header')

    return html.Div([header] + body, className='print-sheet')
