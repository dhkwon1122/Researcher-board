import math
import os
import sys
from datetime import date, datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import html

from components.detail_tabs import plain_indent_list
from services.data_store import ASSETS_DIR, PHOTO_DIR, RAW_DIR
from services.evaluations import (
    competency_column, first_half_column, format_evaluation_cell, salary_grade_column, second_half_column,
)
from services.language_qualification import format_block as language_block_text
from services.task_history import merge_task_rows
from services.task_history import sort_key as _task_sort_key
from services.work_experience import format_line as _work_exp_format_line

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


def load_photo_src(rid: str) -> str | None:
    """사진 URL 반환. 없으면 None.
    파일이 존재하면 Flask 라우트 URL(/photo/<rid8>) 반환 — base64 인코딩 없이 HTTP 서빙.
    탐색 순서: data/photo/(원본 사진 전용 폴더) → assets/photos/ → data/raw/
    (파일명·확장자 대소문자 무관).
    """
    rid8 = str(rid).zfill(8)
    rid_plain = str(int(rid8)) if rid8.isdigit() else rid8
    candidates = {rid8.lower(), rid_plain.lower()}
    _EXTS = {'png', 'jpg', 'jpeg'}

    for base_dir in (PHOTO_DIR, os.path.join(ASSETS_DIR, 'photos'), RAW_DIR):
        if not os.path.isdir(base_dir):
            print(f'[photo] 디렉토리 없음: {base_dir}', file=sys.stderr)
            continue
        try:
            files = os.listdir(base_dir)
        except OSError as exc:
            print(f'[photo] listdir 오류 {base_dir}: {exc}', file=sys.stderr)
            continue
        print(f'[photo] {base_dir} 파일수={len(files)}, 후보={candidates}', file=sys.stderr)
        for fname in files:
            stem, dot, fext = fname.rpartition('.')
            if dot and stem.lower() in candidates and fext.lower() in _EXTS:
                print(f'[photo] 발견: {fname} → /photo/{rid8}', file=sys.stderr)
                return f'/photo/{rid8}'
    print(f'[photo] 없음: rid={rid!r}', file=sys.stderr)
    return None


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


def photo_block(rid: str, name: str, row=None, current_year: int = 2026, *,
                 hide_normal_employment_status: bool = False, img_max_height: int = 200):
    """hide_normal_employment_status=True면 재직상태가 "재직"(정상 재직 중,
    별도로 알릴 필요 없는 기본값)일 때는 "재직상태 : 재직" 줄 자체를 생략한다
    (휴직/퇴직 등 그 외 값은 그대로 표시) — A4 인쇄본처럼 지면이 좁을 때
    사용(기본값 False는 화면과 동일하게 항상 표시). img_max_height는 사진의
    최대 높이(px) — 기본 200은 화면과 동일, 인쇄본은 사진을 더 크게(사용자
    요청) 보여주려는 호출부가 더 큰 값을 넘긴다. 실제 렌더 크기는 이 값과
    부모 컨테이너 폭(maxWidth:100%) 중 더 작은 쪽으로 정해진다(objectFit:
    contain, 원본 비율 유지) — 사진이 정사각형에 가깝고 컨테이너 폭이
    좁아지면 높이를 키워도 폭에 먼저 걸릴 수 있다."""
    photo_el = None
    IMG_STYLE = {'width': 'auto', 'maxWidth': '100%', 'height': 'auto', 'maxHeight': f'{img_max_height}px',
                 'objectFit': 'contain', 'borderRadius': '8px', 'display': 'block'}

    src = load_photo_src(rid)
    if src:
        photo_el = html.Img(src=src, style=IMG_STYLE)

    sub_lines = []
    if row is not None:
        def _int(v, default):
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        def _parse_date(v):
            if v is None:
                return None
            if isinstance(v, (date, datetime)):
                return v.date() if isinstance(v, datetime) else v
            s = str(v).strip()
            if s in ('', 'nan', 'None', 'NaT'):
                return None
            for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
                try:
                    return datetime.strptime(s[:10], fmt).date()
                except ValueError:
                    continue
            return None

        birth_year = _int(row.get('birth_year'), current_year - 30)
        age        = current_year - birth_year
        gender     = str(row.get('gender', '')).strip()
        position   = str(row.get('position', '')).strip()

        # 근속: hire_date 있으면 정밀 계산, 없으면 hire_year 폴백
        hire_dt = _parse_date(row.get('hire_date'))
        if hire_dt:
            tenure = round((date.today() - hire_dt).days / 365, 1)
        else:
            hire_year = _int(row.get('hire_year'), current_year)
            tenure = float(current_year - hire_year)

        # 직급연차: 2027-03-01 기준으로 올림
        promo_dt = _parse_date(row.get('promotion_date'))
        if promo_dt:
            ref = date(2027, 3, 1)
            position_year = math.ceil((ref - promo_dt).days / 365)
        else:
            position_year = int(tenure)

        line1 = f'{name}({gender}/{age}세)' if gender else f'{name}({age}세)'
        line2 = f'{position}-{position_year}({tenure:.1f}년)' if position else f'{tenure:.1f}년 근속'

        sub_lines = [
            html.P(line1, className='fw-bold mt-2 mb-0 text-center small'),
            html.P(line2, className='text-muted text-center mb-0',
                   style={'fontSize': '0.78rem'}),
        ]

        employment_status = str(row.get('employment_status', '') or '').strip()
        if employment_status and not (hide_normal_employment_status and employment_status == '재직'):
            sub_lines.append(html.P(
                f'재직상태 : {employment_status}', className='text-muted text-center mb-0',
                style={'fontSize': '0.78rem'},
            ))

        # 어학 — 재직상태 줄 바로 아래. 여러 언어를 보유하면 줄바꿈으로
        # 나열한다(사용자 확정 — 콤마 아님). 데이터가 전혀 없으면 줄 자체를
        # 생략(재직상태와 동일한 관례). 화면·A4 인쇄 카드가 이 함수를
        # 공유하므로 둘 다에 함께 반영된다(사용자 확정 — 인쇄 카드에도 포함).
        language_text = language_block_text(rid)
        if language_text:
            sub_lines.append(html.P(
                language_text, className='text-muted text-center mb-0',
                style={'fontSize': '0.78rem', 'whiteSpace': 'pre-line'},
            ))
    else:
        sub_lines = [html.P(name, className='fw-bold mt-2 mb-0 text-center small')]

    return [avatar(name, size=90) if photo_el is None else photo_el] + sub_lines


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


def education_block(edu_df: pd.DataFrame, rid: str, *, plain_degree: bool = False):
    """plain_degree=True면 학위(박사/석사/학사 등)를 필(pill) 형태의 dbc.Badge
    대신 일반 굵은 글자로 표시한다 — 인쇄본에서는 색이 있는 뱃지가 아이콘처럼
    보인다는 피드백에 따른 옵션(화면 기본값은 기존 뱃지 유지)."""
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
        if plain_degree:
            # 외부 CDN(부트스트랩) 유틸리티 클래스(me-1/d-flex 등)가 늦게 로드되면
            # 뱃지 대신 쓰는 이 일반 텍스트가 간격 없이 붙어 보일 수 있어(뱃지는
            # assets/custom.css 자체 padding으로 CDN과 무관하게 간격이 생김),
            # 인라인 style로 직접 여백/가로배치를 준다.
            degree_el = html.Span(degree, style={'fontWeight': 700, 'marginRight': '6px',
                                                  'flexShrink': '0'})
            row_style = {'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px'}
        else:
            degree_el = dbc.Badge(degree, color=color_map.get(degree, 'light'),
                                   text_color=text_map.get(degree, 'dark'),
                                   className='me-1 flex-shrink-0')
            row_style = None
        items.append(html.Div([
            degree_el,
            html.Span(f"{edu.get('school', '')}  {edu.get('major', '')} ({grad_year})",
                      className='small'),
        ], className=None if plain_degree else 'd-flex align-items-center mb-1', style=row_style))
    return html.Div(items) if items else html.Div('학력 정보 없음', className='text-muted small')


def _clean_str(val) -> str:
    s = str(val).strip() if val is not None else ''
    return '' if s.lower() in ('', 'nan', 'none', 'nat') else s


def _inc_label(inc: pd.DataFrame, year) -> str:
    """한 해의 인센티브 선정 구분 문자열('-'면 미선정). evaluation_incentive_block()
    (표 형식)과 evaluation_incentive_summary_text()(글자 형식)가 공유한다."""
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


def _eval_cell(eva, year) -> tuple[str, str]:
    """(색상 기준 연봉등급, 화면 표시 문자열 예: "다(EM/EM)") 튜플. eva가 없으면
    둘 다 '-'. evaluation_incentive_block()/evaluation_incentive_summary_text()
    가 공유한다."""
    if eva is None:
        return '-', '-'
    salary = _clean_str(eva.get(salary_grade_column(year)))
    first_half = _clean_str(eva.get(first_half_column(year - 1)))
    second_half = _clean_str(eva.get(second_half_column(year - 1)))
    competency = _clean_str(eva.get(competency_column(year - 1)))
    display = format_evaluation_cell(salary, first_half, second_half, competency)
    return salary, display


def _eval_incentive_rows(eva_df, inc_df, rid: str):
    """evaluation_incentive_block()/evaluation_incentive_summary_text() 공용
    준비 단계 — 해당 연구원의 인센티브 행과 평가 행(evaluations.csv는
    researcher_id당 1행뿐이라 eva는 있으면 1행)을 걸러 반환한다."""
    inc = inc_df[inc_df['researcher_id'] == rid] if not inc_df.empty else pd.DataFrame()
    eva_rows = eva_df[eva_df['researcher_id'] == rid] if not eva_df.empty else pd.DataFrame()
    eva = eva_rows.iloc[0] if not eva_rows.empty else None
    return inc, eva


def evaluation_incentive_block(eva_df, inc_df, rid: str, years: list[int]):
    """years: 연봉등급 연도 리스트(오름차순, 예: [2024,2025,2026]) — 각 연도
    열은 그 해 연봉등급과, 대응하는 전년도(연도-1) 역량/하반기업적(연봉등급이
    없으면 상/하반기업적)을 합쳐 services.evaluations.format_evaluation_cell()로
    한 셀에 표시한다(예:
    "다(EM/EM)")."""
    inc, eva = _eval_incentive_rows(eva_df, inc_df, rid)

    def _grade_td(salary_grade, display):
        color = GRADE_COLOR.get(salary_grade, '#aaa')
        return html.Td(
            html.Span(display, style={'color': color, 'fontWeight': '700', 'fontSize': '0.8rem'}),
            className='text-center', style={'verticalAlign': 'middle'},
        )

    return dbc.Table([
        html.Thead(
            html.Tr(
                [html.Th('구분', className='text-center',
                         style={'fontSize': '0.72rem', 'width': '55px', 'verticalAlign': 'middle'})] +
                [html.Th(f"'{str(year)[-2:]}", className='text-center',
                         style={'fontSize': '0.72rem', 'verticalAlign': 'middle'})
                 for year in years]
            ),
            className='table-light',
        ),
        html.Tbody([
            html.Tr(
                [html.Td('인센티브', className='small text-muted text-center',
                         style={'whiteSpace': 'nowrap', 'fontSize': '0.75rem', 'verticalAlign': 'middle'})] +
                [html.Td(_inc_label(inc, year), className='text-center small',
                         style={'verticalAlign': 'middle'}) for year in years]
            ),
            html.Tr(
                [html.Td('평가등급', className='small text-muted text-center',
                         style={'whiteSpace': 'nowrap', 'fontSize': '0.75rem', 'verticalAlign': 'middle'})] +
                [_grade_td(*_eval_cell(eva, year)) for year in years]
            ),
        ]),
    ], bordered=True, size='sm', className='mb-0 eval-incentive-table', style={'fontSize': '0.8rem'})


def evaluation_incentive_summary_text(eva_df, inc_df, rid: str, years: list[int]):
    """평가/인센티브 이력을 표 대신 글자 두 줄로 — A4 인쇄처럼 지면이 좁아 표
    형식이 부담스러운 곳에서 쓴다(연도·값 계산은 evaluation_incentive_block()과
    동일 로직 공유, 표시 형식만 다름). 제목("평가 · 인센티브 이력")과
    "평가"/"인센티브" 구분자 없이 값만 가운데 정렬로 두 줄 보여준다(사용자
    확정 — 어느 자리에 나오는 값인지는 문맥으로 알 수 있다는 전제). 평가
    줄이 인센티브 줄보다 먼저 온다. 예:
      나(ES)/가(EM)/다(MT)
      -/우수/최우수"""
    inc, eva = _eval_incentive_rows(eva_df, inc_df, rid)
    inc_line = '/'.join(_inc_label(inc, y) for y in years)
    eval_line = '/'.join(_eval_cell(eva, y)[1] for y in years)

    return html.Div([
        html.Div(eval_line, className='small'),
        html.Div(inc_line, className='small'),
    ], className='text-center', style={'textAlign': 'center'})


def nurturing_block(nur_df, rid: str, *, limit: int | None = None, show_empty_message: bool = True,
                     plain_style: bool = False):
    """plain_style=True면 기본 <ul> disc 마커 대신 마커 없이 살짝 들여쓰기만
    된 형태(components/detail_tabs.py의 plain_indent_list()와 같은 모양)로
    보여준다(A4 인쇄본 전용 — 사용자 요청: "논문 실적, 특허 실정, 양성이력,
    시상 이력의 내용도 [전문지식 및 역량과] 동일하게 들여쓰기 해주면
    돼"). 화면(라이브) 탭 호출부는 이 인자를 넘기지 않아 기존 <ul> 그대로."""
    rows = nur_df[nur_df['researcher_id'] == rid].copy() if not nur_df.empty else pd.DataFrame()
    if not rows.empty:
        sort_col = 'start_date' if 'start_date' in rows.columns else (
            'year' if 'year' in rows.columns else rows.columns[0])
        rows = rows.sort_values(sort_col, ascending=False)
        if limit:
            rows = rows.head(limit)

    texts = []
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
        texts.append(' / '.join(parts) if parts else '-')
    if texts:
        if plain_style:
            return plain_indent_list(texts)
        return html.Ul([html.Li(t, className='small') for t in texts], className='ps-3 mb-0 small')
    return html.Div('양성 이력 없음', className='text-muted small') if show_empty_message else None


AWARD_TYPES = {'그룹표창', '대표이사표창', '대표이사표창(시상금미포함)', '부문표창'}


def award_block(awd_df, rid: str, *, limit: int | None = None, single_line: bool = False,
                 show_empty_message: bool = True, plain_style: bool = False):
    """limit이 주어지면 최신순 상위 limit건만 보여준다(A4 인쇄처럼 지면이 좁을
    때). single_line=True면 각 항목을 한 줄로 강제하고 넘치는 글자는 '...'로
    잘라 보여준다(CSS text-overflow: ellipsis — 실제 폭에 맞춰 잘리므로 글자수를
    직접 셀 필요가 없다). show_empty_message=False면 이력이 없을 때 "시상 이력
    없음" 문구 대신 빈 칸으로 둔다(A4 인쇄용). plain_style=True면 기본 <ul>
    disc 마커 대신 마커 없이 살짝 들여쓰기만 된 형태(nurturing_block()의
    plain_style과 동일 — 사용자 요청: "논문 실적, 특허 실정, 양성이력, 시상
    이력의 내용도 동일하게 들여쓰기 해주면 돼")로 보여준다. 나머지 기본값은
    화면과 동일한 기존 동작(전체/여러 줄, 문구 표시)."""
    if awd_df.empty:
        return html.Div('시상 이력 없음', className='text-muted small') if show_empty_message else None
    rows = awd_df[awd_df['researcher_id'] == rid].copy()
    rows = rows[rows['award_type'].isin(AWARD_TYPES)] if 'award_type' in rows.columns else rows
    if rows.empty:
        return html.Div('시상 이력 없음', className='text-muted small') if show_empty_message else None

    sort_col = 'year' if 'year' in rows.columns else ('award_date' if 'award_date' in rows.columns else rows.columns[0])
    rows = rows.sort_values(sort_col, ascending=False)
    if limit:
        rows = rows.head(limit)

    item_style = {'whiteSpace': 'nowrap', 'overflow': 'hidden', 'textOverflow': 'ellipsis'} if single_line else {}
    texts = []
    for _, row in rows.iterrows():
        yr = str(row.get('year', str(row.get('award_date', ''))[:4])).strip()
        yr_label = f"'{yr[-2:]}" if len(yr) >= 2 else yr
        aname = str(row.get('award_name', '')).strip()
        desc  = str(row.get('description', '')).strip()
        parts = [p for p in [yr_label, aname, desc] if p and p not in ('nan',)]
        texts.append(' / '.join(parts) if parts else '-')
    if plain_style:
        return html.Div([
            html.Div(t, className='small', style={**item_style, 'marginLeft': '10px', 'marginBottom': '3px',
                                                    'wordBreak': 'break-word'})
            for t in texts
        ])
    return html.Ul([html.Li(t, className='small', style=item_style) for t in texts], className='ps-3 mb-0 small')


def work_experience_block(we_df, rid: str, *, limit: int | None = None, single_line: bool = False,
                           show_empty_message: bool = True, plain_style: bool = False):
    """근무 경력 표시 — award_block()과 동일한 형태/인자(limit/single_line/
    show_empty_message/plain_style)를 공유한다(사용자 요청: "시상 이력과
    동일한 형태로"). 표시 문구 자체("회사명(시작'YY.MM ~ 종료'YY.MM,
    직무명)")는 services.work_experience.format_line()이 만든다 — 프로필
    화면·인쇄 카드가 같은 표기 규칙을 공유하도록. limit이 주어지면 최신
    시작일순 상위 limit건만(인쇄 카드는 최근 1건만, 사용자 확정
    2026-08-29)."""
    if we_df.empty:
        return html.Div('근무 경력 없음', className='text-muted small') if show_empty_message else None
    rows = we_df[we_df['researcher_id'] == rid].copy()
    if rows.empty:
        return html.Div('근무 경력 없음', className='text-muted small') if show_empty_message else None
    if 'work_start_date' in rows.columns:
        rows = rows.sort_values('work_start_date', ascending=False)
    if limit:
        rows = rows.head(limit)

    item_style = {'whiteSpace': 'nowrap', 'overflow': 'hidden', 'textOverflow': 'ellipsis'} if single_line else {}
    texts = [line for line in (_work_exp_format_line(row.to_dict()) for _, row in rows.iterrows()) if line]
    if not texts:
        return html.Div('근무 경력 없음', className='text-muted small') if show_empty_message else None
    if plain_style:
        return html.Div([
            html.Div(t, className='small', style={**item_style, 'marginLeft': '10px', 'marginBottom': '3px',
                                                    'wordBreak': 'break-word'})
            for t in texts
        ])
    return html.Ul([html.Li(t, className='small', style=item_style) for t in texts], className='ps-3 mb-0 small')


_TASK_EMPTY = {'', 'nan', 'none', 'nat', 'NaN', 'None', 'NaT'}


def _fmt_rate(val) -> str:
    """투입률 표시: 정수% 또는 '-'."""
    if val is None:
        return '-'
    try:
        if pd.isna(val):
            return '-'
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if s.lower() in _TASK_EMPTY:
        return '-'
    try:
        v = float(s)
        if 0.0 < v <= 1.0:
            v *= 100
        return f'{int(round(v))}%'
    except (ValueError, TypeError):
        return '-'


def _has_min_duration(start_raw, end_raw, min_days: int = 30) -> bool:
    """과제 참여기간(종료일-시작일)이 min_days 이하이면 False (해당 과제는 제외).
    종료일이 비어있으면(진행중) 오늘 날짜를 종료일로 간주해 계산한다.
    start_date/end_date가 YYYYMMDD 정수로 들어올 수 있어, pandas가 나노초로
    오인하지 않도록 반드시 문자열로 변환한 뒤 파싱한다."""
    start = pd.to_datetime(str(start_raw).strip(), errors='coerce') if start_raw is not None else pd.NaT
    if pd.isna(start):
        return False
    end_s = str(end_raw).strip() if end_raw is not None else ''
    is_empty_end = end_s == '' or end_s.lower() in _TASK_EMPTY
    end = pd.Timestamp(datetime.now().date()) if is_empty_end else pd.to_datetime(end_s, errors='coerce')
    if pd.isna(end):
        end = pd.Timestamp(datetime.now().date())
    return (end - start).days > min_days


def _fmt_period(start_raw, end_raw) -> str:
    """기간 표시: 'YYYY-MM ~ YYYY-MM' 또는 'YYYY-MM ~ 현재'."""
    start = str(start_raw).strip()[:7] if start_raw is not None else ''
    if start.lower() in _TASK_EMPTY:
        start = ''

    end_s = str(end_raw).strip() if end_raw is not None else ''
    try:
        is_empty_end = pd.isna(end_raw) or end_s.lower() in _TASK_EMPTY
    except (TypeError, ValueError):
        is_empty_end = end_s.lower() in _TASK_EMPTY
    end = '' if is_empty_end else end_s[:7]

    if start and end:
        return f'{start} ~ {end}'
    if start:
        return f'{start} ~ 현재'
    return '-'


def tasks_block(task_df, rid: str, *, limit: int | None = None):
    """과제 수행 이력 테이블 (tasks.csv 기반). 투입률 0도 포함하고, 참여기간
    (종료일-시작일)이 30일 이하인 과제만 제외한다(타임라인 스파인과 동일 기준).
    같은 과제명으로 여러 줄 참여 이력이 있으면 services.task_history.
    merge_task_rows()로 하나로 합친다(엑셀 다운로드 _col_tasks()와 동일한
    병합 규칙 공유 — 사용자 요청 2026-08-31 "화면에도 동일하게 반영").
    진행중('현재')인 과제가 맨 위에 오도록 정렬한다. 병합된 구간의 투입률은
    구간마다 다를 수 있어 "가장 최근 구간"(진행중이면 그 진행중 구간,
    아니면 가장 최근에 끝난 구간) 값만 보여준다(사용자 확정 2026-08-31).
    limit이 주어지면(예: A4 인쇄 요약) 최신순 상위 limit건만 표에 담고, 잘린
    나머지 건수를 표 아래 한 줄로 안내한다 — 기본값 None은 화면 그대로 전체 표시."""
    rows = task_df[task_df['researcher_id'] == rid] if not task_df.empty else pd.DataFrame()
    if not rows.empty:
        rows = rows[rows.apply(lambda r: _has_min_duration(r.get('start_date'), r.get('end_date')), axis=1)]
    if rows.empty:
        return html.Div('과제 수행 이력 없음', className='text-muted small')

    merged = merge_task_rows(rows.to_dict('records'))
    merged.sort(key=_task_sort_key)

    total = len(merged)
    if limit:
        merged = merged[:limit]

    table_rows = []
    for m in merged:
        period = _fmt_period(m['start_row'].get('start_date'),
                              None if m['current'] else m['end_row'].get('end_date'))
        rate_row = m['current_row'] if m['current'] else m['end_row']
        rate = _fmt_rate(rate_row.get('input_rate'))
        table_rows.append(html.Tr([
            html.Td(m['name'], className='small', style={'wordBreak': 'break-word'}),
            html.Td(period, className='small text-muted', style={'wordBreak': 'break-word'}),
            html.Td(rate, className='small text-center', style={'wordBreak': 'break-word'}),
        ]))

    table = dbc.Table([
        html.Thead(html.Tr([
            html.Th('과제명',  style={'fontSize': '0.72rem', 'width': '50%'}),
            html.Th('기간',    style={'fontSize': '0.72rem', 'width': '35%'}),
            html.Th('투입률',  style={'fontSize': '0.72rem', 'width': '15%'}),
        ]), className='table-light'),
        html.Tbody(table_rows),
    ], bordered=False, hover=True, size='sm', className='mb-0',
       style={'tableLayout': 'fixed', 'width': '100%'})

    if limit and total > limit:
        return html.Div([table, html.Div(f'외 {total - limit}건 더', className='text-muted small mt-1')])
    return table


def transfer_block(tra_df, rid: str):
    rows = tra_df[tra_df['researcher_id'] == rid].sort_values('date', ascending=False) if not tra_df.empty else pd.DataFrame()
    if rows.empty:
        return html.Div('발령 / 프로젝트 이력 없음', className='text-muted small')
    table_rows = [
        html.Tr([
            html.Td(str(row.get('date', ''))[:7], className='small text-muted',
                    style={'wordBreak': 'break-word'}),
            html.Td(dbc.Badge(str(row.get('type', '')),
                              color=TRANSFER_BADGE.get(str(row.get('type', '')), 'light'),
                              className='small')),
            html.Td(str(row.get('description', '')), className='small', style={'wordBreak': 'break-word'}),
        ])
        for _, row in rows.iterrows()
    ]
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('시기', style={'fontSize': '0.72rem', 'width': '15%'}),
            html.Th('유형', style={'fontSize': '0.72rem', 'width': '20%'}),
            html.Th('내용', style={'fontSize': '0.72rem', 'width': '65%'}),
        ]), className='table-light'),
        html.Tbody(table_rows),
    ], bordered=False, hover=True, size='sm', className='mb-0',
       style={'tableLayout': 'fixed', 'width': '100%'})


def comments_block(cmt_df, rid: str):
    if cmt_df.empty:
        return html.Div('코멘트 없음', className='text-muted small')
    rows = cmt_df[cmt_df['researcher_id'] == rid]
    if rows.empty:
        return html.Div('코멘트 없음', className='text-muted small')

    cards = []

    # ── 종합요약 (LLM 생성) ─────────────────────────────────────────────────
    summary_rows = rows[rows['commenter_type'] == '종합요약']
    if not summary_rows.empty:
        sr = summary_rows.iloc[0]
        summary_text  = str(sr.get('comment_summary', '')).strip()
        strengths_text = str(sr.get('strengths', '')).strip()
        improve_text   = str(sr.get('improvements', '')).strip()
        body = []
        if summary_text and summary_text not in ('', 'nan'):
            body.append(html.P(summary_text, className='small mb-2',
                               style={'lineHeight': '1.6'}))
        if strengths_text and strengths_text not in ('', 'nan'):
            body.append(html.Div([
                html.Span('강점  ', className='fw-semibold text-success',
                          style={'fontSize': '0.78rem'}),
                html.Span(strengths_text, className='small text-muted'),
            ], className='mb-1'))
        if improve_text and improve_text not in ('', 'nan'):
            body.append(html.Div([
                html.Span('개선  ', className='fw-semibold text-warning',
                          style={'fontSize': '0.78rem'}),
                html.Span(improve_text, className='small text-muted'),
            ], className='mb-0'))
        if body:
            cards.append(dbc.Card(
                dbc.CardBody([
                    html.Div([
                        dbc.Badge('AI 종합요약', color='dark', className='me-2 small'),
                        html.Span('전체 코멘트 기반', className='text-muted',
                                  style={'fontSize': '0.72rem'}),
                    ], className='mb-2'),
                    *body,
                ], className='py-2 px-3'),
                className='mb-3 border-0 shadow-sm',
                style={'backgroundColor': '#f8f9fa'},
            ))

    # ── 개별 코멘트 ──────────────────────────────────────────────────────────
    BADGE = {
        '부서장': ('danger', '부서장'),
        '리더십_본인': ('secondary', '본인'),
        '리더십_동료': ('info', '동료'),
        '리더십_상사': ('primary', '상사'),
        '리더십_부서원': ('success', '부서원'),
    }
    detail = rows[rows['commenter_type'] != '종합요약']
    sort_cols = ['year', 'commenter_type'] if 'commenter_type' in detail.columns else ['year']
    detail = detail.sort_values(sort_cols, ascending=False)

    for _, row in detail.iterrows():
        c_type = str(row.get('commenter_type', '부서장'))
        color, label = BADGE.get(c_type, ('secondary', c_type))
        try:
            year_label = f'{int(row["year"])}년'
        except (TypeError, ValueError):
            year_label = str(row.get('year', ''))

        body = []
        raw = str(row.get('comment_raw', '')).strip()
        summary = str(row.get('comment_summary', '')).strip()
        strengths = str(row.get('strengths', '')).strip()
        improvements = str(row.get('improvements', '')).strip()

        if summary and summary not in ('nan', 'None'):
            body.append(html.P(summary, className='small mb-1', style={'lineHeight': '1.5'}))
        elif raw and raw not in ('nan', 'None'):
            body.append(html.P(raw[:200] + ('...' if len(raw) > 200 else ''),
                               className='small mb-1', style={'lineHeight': '1.5'}))
        if strengths and strengths not in ('nan', 'None'):
            body.append(html.Small(['강점: ', html.Span(strengths, className='text-muted')],
                                   className='d-block'))
        if improvements and improvements not in ('nan', 'None'):
            body.append(html.Small(['개선: ', html.Span(improvements, className='text-muted')],
                                   className='d-block'))

        if not body:
            continue

        cards.append(dbc.Card(
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Span(year_label, className='fw-bold small'), width='auto'),
                    dbc.Col(dbc.Badge(label, color=color, className='small'), width='auto'),
                ], className='mb-1 g-1'),
                *body,
            ], className='py-2 px-3'),
            className='mb-2 border',
        ))

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
