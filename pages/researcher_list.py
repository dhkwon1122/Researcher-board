"""
화면 3: 연구원 명단 (정량 지표 테이블)
"""

import re
from datetime import date, datetime
from urllib.parse import parse_qs

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, dash_table, dcc, html, no_update

from components import nl_query_bar
from components.timeline_data import dedupe_patents
from services import researcher_profile_export, similarity_map
from services.data_store import filter_current, read_processed
from services.evaluations import evaluation_years, salary_grade_column
from services.period_snapshot import resolve_period_snapshot as _resolve_period_snapshot

dash.register_page(
    __name__,
    path='/researcher-list',
    name='연구원 명단',
    title='연구원 명단',
)

_CURRENT_YEAR = datetime.now().year

# 평가등급 컬럼("'24평가" 등)의 연도 — evaluations.csv와 동일한 회계연도
# 기준(매년 3월 시작, services.evaluations)으로 오름차순(과거→최신) 계산.
_EVAL_SALARY_YEARS = sorted(evaluation_years()[0])
_EVAL_GRADE_COLUMNS = [f"'{str(y)[-2:]}평가" for y in _EVAL_SALARY_YEARS]
_INCENTIVE_COL = '인센티브'

# 평가등급 컬럼 판별용 정규식 — 기간 지정(period) 조회 시에는 _EVAL_GRADE_COLUMNS
# (오늘 기준 3개년)와 다른 연도의 컬럼("'23평가" 등)이 만들어질 수 있어(2026-08-28),
# 권한 필터/조건부 색상 스타일 둘 다 이 패턴으로 "실제 df에 있는" 평가등급
# 컬럼을 동적으로 찾아야 한다 — 고정 목록만 보면 기간 조회 시 권한 필터가
# 그 컬럼을 못 찾아 평가등급이 권한 없이도 그대로 노출되는 문제가 생긴다.
_EVAL_GRADE_PATTERN = re.compile(r"^'\d{2}평가$")

# ── 학위 우선순위 ─────────────────────────────────────────────────────────────
_DEGREE_RANK = {'박사': 5, '석사': 4, '학사': 3, '전문대': 2, '고교': 1}


def _active_period(mode: str, period_start: str | None, period_end: str | None) -> tuple[date, date] | None:
    """검색 기준 모드 + 기간 두 날짜 문자열로부터 실제 적용할 기간을
    계산한다 — 누적기준(mode == 'all')이고 두 날짜가 다 지정됐을 때만
    기간이 있는 것으로 본다. toggle_org_filters/update_project_options/
    update_table 콜백이 전부 같은 판정을 공유한다(2026-08-29 추가 —
    이전엔 update_table 안에 이 판정이 중복돼 있었다)."""
    if mode == 'all' and period_start and period_end:
        return date.fromisoformat(period_start), date.fromisoformat(period_end)
    return None


def _build_summary_df(current_only: bool = True, period: tuple[date, date] | None = None) -> pd.DataFrame:
    """CSV들을 집계하여 연구원 1인 1행의 요약 DataFrame 반환.
    current_only=False(누적기준)면 전배·퇴사 등으로 최신 인력현황에 없는
    사람도 포함하고, 그 경우에만 '현재소속' 열을 추가로 붙인다(최신기준에서는
    전원이 '현재'라 의미가 없어 열 자체를 안 만든다).
    period=(시작일, 종료일)이 함께 주어지면(누적기준에서만 의미가 있음)
    "한 번이라도 있었던 전체 인원"이 아니라 "그 기간 동안 소속돼 있던
    사람"만, researchers_history.csv 기준 그 기간의 마지막 상태로 보여준다
    — 이때는 '현재소속' 대신 '조회기간 기준' 열에 그 사람 스냅샷의
    연/월을 보여준다."""
    try:
        res  = _resolve_period_snapshot(period) if period else read_processed('researchers')
        # 평가등급도 기간이 주어지면 evaluations_history.csv에서 그 기간의
        # 마지막 스냅샷을 쓴다(2026-08-28) — evaluations.csv/_history.csv는
        # 회계연도(매년 3월 시작) 이름의 동적 컬럼이라({연도}_salary_grade),
        # "그 시점 기준 최근 3개년"이 실제 오늘 기준과 다르면 컬럼명 자체가
        # 달라진다. period[1](조회 기간의 끝)을 기준 시점으로 삼아 그 3개년
        # 컬럼을 다시 계산한다 — process_tp_evaluation.py의 evaluation_years
        # (valid_date=...) 수정과 동일한 원리.
        if period:
            eva = _resolve_period_snapshot(period, table='evaluations_history')
            eval_salary_years = sorted(evaluation_years(today=period[1])[0])
            eval_grade_columns = [f"'{str(y)[-2:]}평가" for y in eval_salary_years]
        else:
            eva = read_processed('evaluations')
            eval_salary_years, eval_grade_columns = _EVAL_SALARY_YEARS, _EVAL_GRADE_COLUMNS
        pub  = read_processed('publications')
        pat  = read_processed('patents')
        awd  = read_processed('awards')
        edu  = read_processed('education')
        inc  = read_processed('incentive_selection')
    except Exception:
        return pd.DataFrame()

    if not period:
        res = filter_current(res, current_only)

    # 직책 = team_refer의 assignment_name(researcher_id 기준, 조직장급만
    # 등록돼 있어 나머지는 매핑이 없음 — 그 경우 "-"). 부서/과제(파트)
    # 표시값 = researchers.csv의 org_code를 team_refer의 dep_name/
    # pjt_part_name으로 매핑(검색 기준의 부서/과제 필터와 동일한 기준으로
    # 통일 — 사용자 확정). team_refer에 매핑이 없는 org_code는 원본
    # department/org_code 값을 그대로 보여준다(빈 칸으로 두면 데이터
    # 누락처럼 보이므로 — 사용자 확정).
    #
    # period가 주어지면(누적기준 + 기간 지정) 셋 다 "오늘 기준"이 아니라
    # 그 기간 기준(그 기간 안 dep_id별 최신 스냅샷) team_refer로 매핑한다
    # (2026-08-29 추가 — 이전엔 team_refer 관련 매핑 전부가 항상 오늘
    # 기준이라, 예를 들어 2023년 조직 개편 이전 시점을 조회해도 오늘
    # 기준 조직명이 표시됐다).
    title_by_id = similarity_map.title_by_researcher_id(period=period)
    dep_label_map, pjt_label_map = similarity_map.org_code_label_maps(period=period)

    # 숫자 변환
    for col in ['pub_year', 'impact_factor', 'citation_count', 'contribution']:
        if col in pub.columns:
            pub[col] = pd.to_numeric(pub[col], errors='coerce')
    # pub_year가 없으면 pub_date 앞 4자리에서 파생
    if 'pub_year' not in pub.columns and 'pub_date' in pub.columns:
        pub['pub_year'] = pd.to_numeric(pub['pub_date'].str[:4], errors='coerce')
    if 'year' in inc.columns:
        inc['year'] = pd.to_numeric(inc['year'], errors='coerce')

    rows = []
    for _, r in res.iterrows():
        rid = r['researcher_id']

        # ── 평가 등급(연봉등급만 — 상/하반기업적은 이 표에 넣지 않음) ────────
        ev_rows = eva[eva['researcher_id'] == rid]
        ev = ev_rows.iloc[0] if not ev_rows.empty else None
        def _grade(yr):
            if ev is None:
                return '-'
            val = str(ev.get(salary_grade_column(yr), '') or '').strip()
            return val if val and val.lower() != 'nan' else '-'
        grades = {col: _grade(yr) for col, yr in zip(eval_grade_columns, eval_salary_years)}

        # ── 인센티브 ───────────────────────────────────────────────────────
        sel = inc[inc['researcher_id'] == rid]
        # selected 열이 문자열일 수 있으므로 유연하게 처리
        if not sel.empty and 'selected' in sel.columns:
            sel_true = sel[sel['selected'].astype(str).str.lower().isin(['true', '1', 'yes'])]
        else:
            sel_true = pd.DataFrame()
        if not sel_true.empty:
            latest_inc = sel_true.sort_values('year').iloc[-1]
            inc_cat = str(latest_inc.get('category', '')).strip() or '-'
        else:
            inc_cat = '-'

        # ── 논문 ───────────────────────────────────────────────────────────
        pubs = pub[pub['researcher_id'] == rid]
        pub_total  = len(pubs)
        pub_3yr    = int((pubs['pub_year'] >= _CURRENT_YEAR - 2).sum()) if not pubs.empty and 'pub_year' in pubs.columns else 0
        avg_if     = round(pubs['impact_factor'].mean(), 2) if not pubs.empty and 'impact_factor' in pubs.columns and pubs['impact_factor'].notna().any() else '-'

        # ── 특허 ───────────────────────────────────────────────────────────
        # 타임라인과 동일하게 application_id 기준으로 중복(공동발명자 등) 제거 후 집계
        pats = pat[pat['researcher_id'] == rid]
        pats_dedup = dedupe_patents(pats) if not pats.empty else pats
        pat_app = int((pats_dedup['status'] == '출원').sum()) if not pats_dedup.empty else 0
        pat_reg = int((pats_dedup['status'] == '등록').sum()) if not pats_dedup.empty else 0

        # ── 수상 ───────────────────────────────────────────────────────────
        awd_cnt = len(awd[awd['researcher_id'] == rid])

        # ── 학력/전공 ───────────────────────────────────────────────────
        edu_r = edu[edu['researcher_id'] == rid]
        if not edu_r.empty and 'degree' in edu_r.columns:
            top_edu = edu_r.assign(_rank=edu_r['degree'].map(_DEGREE_RANK).fillna(0)) \
                           .sort_values('_rank').iloc[-1]
            highest = top_edu['degree']
            major = str(top_edu.get('major', '') or '').strip() or '-'
        else:
            highest = '-'
            major = '-'

        org_code = str(r.get('org_code', ''))
        row = {
            'researcher_id': rid,
            '_org_code':      org_code,  # 화면에는 안 보임 — 부서/과제 필터가 org_code로 매칭할 때만 씀
            '이름':           str(r.get('name', '')),
            '부서':           dep_label_map.get(org_code) or str(r.get('department', '')),
            '과제':           pjt_label_map.get(org_code) or org_code,
            '직급':           str(r.get('position', '')),
            '직책':           str(title_by_id.get(rid, '') or '').strip() or '-',
            '성별':           str(r.get('gender', '')),
            '재직상태':       str(r.get('employment_status', '') or '').strip() or '-',
            'Knox ID':        str(r.get('knox_id', '') or '').strip() or '-',
            '학력':           highest,
            '전공':           major,
            **grades,
            _INCENTIVE_COL:   inc_cat,
            '논문(전체)':     pub_total,
            '논문(3년)':      pub_3yr,
            '평균IF':         avg_if,
            '특허(출원)':     pat_app,
            '특허(등록)':     pat_reg,
            '수상':           awd_cnt,
        }
        if period:
            y, m = str(r.get('valid_year', '')).strip(), str(r.get('valid_month', '')).strip()
            row['조회기간 기준'] = f'{y}-{m}' if y and m else '-'
        elif not current_only:
            row['현재소속'] = '미소속' if str(r.get('is_current', 'Y')) == 'N' else '현재'
        rows.append(row)

    return pd.DataFrame(rows)


def _apply_permission_filter(df: pd.DataFrame, show_eval: bool, show_incentive: bool,
                              excluded_dep_ids: set | None = None,
                              org_code_dep_id_map: dict | None = None) -> pd.DataFrame:
    """평가/인센티브 열람 권한이 없으면 해당 컬럼을 통째로 제거한다.
    평가등급 컬럼은 df에 실제로 있는 컬럼 중 _EVAL_GRADE_PATTERN에 맞는
    것을 전부 찾아 지운다(고정 _EVAL_GRADE_COLUMNS만 보면, 기간 지정 조회로
    다른 연도의 컬럼이 만들어졌을 때 권한 필터가 그 컬럼을 놓친다).

    show_eval이 True라도 excluded_dep_ids(부서 단위 평가 제외 목록, 2026-08-31)가
    있으면 컬럼 자체는 남기되, 그 부서(org_code → dep_id로 판정) 소속 연구원
    행만 평가등급 값을 비운다 — 같은 명단 화면 안에 "볼 수 있는 사람"과
    "볼 수 없는 사람"이 섞여야 해서(컬럼 전체 삭제로는 표현할 수 없음)."""
    df = df.copy()
    drop = []
    if not show_eval:
        drop.extend(c for c in df.columns if _EVAL_GRADE_PATTERN.match(str(c)))
    elif excluded_dep_ids and org_code_dep_id_map and '_org_code' in df.columns:
        grade_cols = [c for c in df.columns if _EVAL_GRADE_PATTERN.match(str(c))]
        if grade_cols:
            masked = df['_org_code'].map(
                lambda oc: org_code_dep_id_map.get(str(oc), '') in excluded_dep_ids
            )
            df.loc[masked, grade_cols] = ''
    if not show_incentive:
        drop.append(_INCENTIVE_COL)
    if not drop:
        return df
    return df.drop(columns=[c for c in drop if c in df.columns])


def _filter_options(df: pd.DataFrame, col: str) -> list:
    if df.empty or col not in df.columns:
        return []
    vals = sorted(df[col].dropna().unique())
    return [{'label': v, 'value': v} for v in vals if str(v).strip()]




# ── 조건부 스타일 (평가등급 색상) ─────────────────────────────────────────────
_GRADE_COLOR = {
    '가': ('#d4edda', '#155724'),
    '나': ('#d1ecf1', '#0c5460'),
    '다': ('#fff3cd', '#856404'),
    '라': ('#fde8d8', '#7d3c00'),
    '마': ('#f8d7da', '#721c24'),
}
def _grade_styles_for(columns) -> list:
    """주어진 컬럼id 목록 중 평가등급 컬럼(_EVAL_GRADE_PATTERN에 맞는 것)에
    대해서만 조건부 색상 스타일을 만든다. 고정 _EVAL_GRADE_COLUMNS(오늘 기준
    3개년) 대신 실제 표시되는 컬럼 기준으로 매번 계산해야, 기간 지정 조회로
    다른 연도의 평가등급 컬럼("'23평가" 등)이 나와도 색상이 정상 적용된다
    (2026-08-28 — 고정 목록만 쓰면 기간 조회 시 색상이 하나도 안 붙었다)."""
    grade_cols = [c for c in columns if _EVAL_GRADE_PATTERN.match(str(c))]
    return [
        {'if': {'filter_query': f'{{{col}}} = {grade}', 'column_id': col},
         'backgroundColor': bg, 'color': fg}
        for col in grade_cols
        for grade, (bg, fg) in _GRADE_COLOR.items()
    ]


_GRADE_STYLES = _grade_styles_for(_EVAL_GRADE_COLUMNS)

# 순서 중요: style_data_conditional은 뒤에 오는 규칙이 같은 셀의 같은 속성을
# 덮어쓴다(나중에 매치되는 규칙이 우선) — 홀수행 줄무늬(row_index: 'odd')가
# 열 지정 없이 모든 셀에 적용되므로, 평가등급 색상(특정 열만 대상)보다
# 먼저 와야 홀수행에서도 등급 색이 줄무늬 배경에 덮이지 않고 살아남는다.
_BASE_STYLE_DATA_CONDITIONAL = [
    {'if': {'row_index': 'odd'}, 'backgroundColor': '#f9fbfd'},
    {'if': {'state': 'active'}, 'backgroundColor': '#dbeafe',
     'border': '1px solid #3b82f6'},
]


def _style_data_conditional_for(columns: list, show_eval: bool) -> list:
    """`columns`(_build_columns()가 만든 dict 목록)에 실제로 포함된 평가등급
    컬럼 기준으로 조건부 색상 스타일을 계산한다."""
    if not show_eval:
        return _BASE_STYLE_DATA_CONDITIONAL
    col_ids = [c['id'] for c in columns]
    return _BASE_STYLE_DATA_CONDITIONAL + _grade_styles_for(col_ids)


# ── 필수 컬럼(사용자 확정) — AI 검색 없이도 항상 노출된다. 사번(researcher_id)은
# 라벨만 "사번"으로 보여주고 내부 데이터 키는 그대로 둔다 — 행 클릭 프로필
# 이동/엑셀 다운로드/일괄 인쇄가 전부 이 키로 연구원을 식별하기 때문.
# 나머지(평가등급/인센티브/논문/특허/수상/성별/학력/전공)는 기본적으로
# 숨기고, 상세 필터로 값을 고르거나 AI 검색 결과에 나올 때만 컬럼을
# 노출한다(사용자 요청: "AI검색과 아래 명단이 겹쳐 보인다 — 필수 컬럼을
# 줄이고 AI검색 결과에 따라 동적으로 추가 컬럼이 구성되게").
_ESSENTIAL_COLUMNS = [
    ('researcher_id', '사번'),
    ('이름', '이름'),
    ('부서', '부서'),
    ('과제', '과제/파트'),
    ('직급', '직급'),
    ('직책', '직책'),
    ('재직상태', '재직상태'),
    ('Knox ID', 'Knox ID'),
    ('조회기간 기준', '조회기간 기준'),
]
_ESSENTIAL_IDS = {col_id for col_id, _ in _ESSENTIAL_COLUMNS}

# 상세 필터 모달에서 값을 고르면(=그 기준으로 비교하고 싶다는 뜻으로 보고)
# 그 컬럼도 함께 보여준다. 직급/직책/재직상태는 이미 필수 컬럼이라 제외.
_OPTIONAL_FILTER_COLUMNS = ['성별', '학력', '전공']

_NUMERIC_COLUMNS = {'논문(전체)', '논문(3년)', '특허(출원)', '특허(등록)', '수상'}


def _build_columns(df: pd.DataFrame, optional_ids: list | None = None,
                    extra_ids: list | None = None, extra_labels: list | None = None) -> list:
    """필수 컬럼 → (상세 필터로 선택돼 함께 보여줄) 선택 컬럼 → AI 검색이
    돌려준 추가 컬럼 순서로 구성한다. df에 실제로 존재하는 컬럼만 포함한다
    (권한 필터로 평가/인센티브가 빠졌을 수 있어서)."""
    cols = [
        {'name': label, 'id': col_id, 'type': 'text'}
        for col_id, label in _ESSENTIAL_COLUMNS if col_id in df.columns
    ]
    seen = set(_ESSENTIAL_IDS)
    for col_id in (optional_ids or []):
        if col_id in df.columns and col_id not in seen:
            seen.add(col_id)
            cols.append({'name': col_id, 'id': col_id, 'type': 'text'})
    extra_ids = extra_ids or []
    extra_labels = extra_labels or extra_ids
    for col_id, label in zip(extra_ids, extra_labels):
        if col_id in seen:
            continue
        seen.add(col_id)
        cols.append({'name': label, 'id': col_id,
                     'type': 'numeric' if col_id in _NUMERIC_COLUMNS else 'text'})
    return cols
    # 평균IF는 혼합값(숫자/'-')이 있어 numeric으로 분류하지 않고 text로 유지


def _build_tooltip_data(records: list) -> list:
    """각 셀에 그 값 전체를 툴팁으로 붙인다 — 컬럼 너비가 좁아 말줄임(...)
    처리된 값도 마우스를 올리면 전체를 볼 수 있게(사용자 확정: 전체 컬럼
    대상). `_org_code`처럼 화면에 없는 내부 컬럼이 섞여 있어도 dash_table이
    실제 렌더링 중인 컬럼id만 골라 쓰므로 문제없다."""
    return [{k: str(v) if v is not None else '' for k, v in row.items()} for row in records]


# AI 검색 결과 중 명단에 다시 노출하지 않을 컬럼 — 이름/부서는 필수 컬럼과
# 100% 같은 값이라 중복이지만, 그 밖의 open_data_query 결과 컬럼(예:
# org_code/degree_major/age)은 그 질문에 대한 근거로 AI가 일부러 보여주는
# 값일 수 있어 그대로 둔다.
_AI_SKIP_COLUMNS = {'researcher_id', 'name', 'department'}


def _merge_ai_result(base_df: pd.DataFrame, ai_result: dict):
    """AI 검색 결과(columns/labels/rows, researcher_id 포함)를 명단 기본
    정보(base_df — 필수 컬럼 값의 출처)와 합친다. 반환: (merged_df,
    extra_col_ids, extra_col_labels). researcher_id가 없는 결과(합계/통계성
    답변 등이라 표로 보여줄 사람이 없는 경우)면 빈 DataFrame을 반환한다 —
    이 경우 명단은 비우고 nl_query_bar의 AI 답변 문장만으로 안내한다."""
    columns = ai_result.get('columns') or []
    if 'researcher_id' not in columns or base_df.empty:
        return base_df.iloc[0:0], [], []

    labels = ai_result.get('labels') or columns
    rows = ai_result.get('rows') or []
    rid_idx = columns.index('researcher_id')
    extra_pairs = [(c, lbl) for c, lbl in zip(columns, labels) if c not in _AI_SKIP_COLUMNS]

    # 같은 연구원이 여러 행(과제/논문별 등)으로 나올 수 있어 처음 나온 값만 쓴다.
    by_rid, order = {}, []
    for row in rows:
        if rid_idx >= len(row):
            continue
        rid = str(row[rid_idx] or '').strip().zfill(8)
        if not rid or rid in by_rid:
            continue
        by_rid[rid] = row
        order.append(rid)

    base_indexed = base_df.set_index('researcher_id')
    merged_rows = []
    for rid in order:
        if rid not in base_indexed.index:
            continue  # 권한 필터/현재 소속 기준 등으로 기본 명단에 없는 사람은 제외
        record = base_indexed.loc[rid].to_dict()
        record['researcher_id'] = rid
        ai_row = by_rid[rid]
        for col, _label in extra_pairs:
            idx = columns.index(col)
            record[col] = ai_row[idx] if idx < len(ai_row) else ''
        merged_rows.append(record)

    merged_df = pd.DataFrame(merged_rows) if merged_rows else base_df.iloc[0:0]
    return merged_df, [c for c, _ in extra_pairs], [lbl for _, lbl in extra_pairs]


def layout():
    from services.auth import can, eval_excluded_dep_ids
    show_eval = can('view_evaluation')
    show_incentive = can('view_incentive')
    excluded_dep_ids = eval_excluded_dep_ids()

    df = _build_summary_df(current_only=True)
    display_df = _apply_permission_filter(
        df, show_eval, show_incentive,
        excluded_dep_ids, similarity_map.org_code_dep_id_map(),
    )

    dept_opts     = similarity_map.department_filter_options()
    project_opts  = similarity_map.pjt_part_filter_options()
    pos_opts      = _filter_options(df, '직급')
    title_opts    = _filter_options(df, '직책')
    gender_opts   = _filter_options(df, '성별')
    degree_opts   = _filter_options(df, '학력')
    major_opts    = _filter_options(df, '전공')
    employ_opts   = _filter_options(df, '재직상태')

    columns = _build_columns(display_df)
    style_data_conditional = _style_data_conditional_for(columns, show_eval)

    return html.Div([
        dcc.Location(id='list-url', refresh=True),
        dcc.Download(id='researcher-list-excel-download'),

        dbc.Row([
            dbc.Col(
                html.H5([html.I(className='bi bi-table me-2 text-primary'), '연구원 명단'],
                        className='fw-bold mb-0 mt-1'),
                className='d-flex align-items-center',
            ),
            dbc.Col(
                dbc.Button('필터 초기화', id='clear-filters-btn', color='secondary',
                           size='sm', outline=True, className='float-end'),
                className='d-flex align-items-center justify-content-end',
            ),
        ], className='mb-3'),

        # ── AI 검색 — 질문하면 아래 명단 자체가 그 결과로 바뀐다(사용자 요청:
        # 별도 결과창이 명단과 겹쳐 헷갈리던 것을 하나로 통합). ───────────────
        nl_query_bar.render(),

        # ── 상단 드롭다운 필터 ─────────────────────────────────────────────
        # 드롭다운 선택 자체는 바로 반영되지 않고, 검색 아이콘(또는 상세 필터
        # 모달의 '적용')을 눌러야 테이블에 적용된다(사용자 확정) — 드롭다운은
        # filter-*, 검색/엑셀 버튼은 아래 콜백에서 각각 Input/State로 분리해서
        # 처리한다. 자주 쓰는 부서/과제만 메인 화면에 남기고, 직급/직책/성별/
        # 학력/전공/재직상태는 화면이 복잡해지지 않도록 '필터' 모달로 옮겼다
        # (사용자 요청).
        dbc.Card(
            dbc.CardBody(
                dbc.Row([
                    dbc.Col([
                        dbc.Label('검색 기준', className='small fw-semibold text-muted mb-1'),
                        dbc.RadioItems(
                            id='list-search-mode',
                            options=[
                                {'label': '최신기준', 'value': 'current'},
                                {'label': '누적기준', 'value': 'all'},
                            ],
                            value='current',
                            inline=True,
                            className='small',
                        ),
                        html.Div(
                            '누적기준: 이름/사번 검색 중심 (부서·과제·직급·직책 필터 비활성화)',
                            className='text-muted', style={'fontSize': '0.72rem'},
                        ),
                        # 누적기준에서 기간(시작~종료)을 지정하면, 그 기간 동안
                        # 소속돼 있던 사람만(researchers_history.csv 기준, 그
                        # 기간 내 가장 최근 스냅샷 값으로) 조회한다 — 이때는
                        # 부서/과제/직급/직책도 그 시점 값이라 필터를 다시
                        # 켠다(toggle_org_filters 콜백 참고). 기간을 비워두면
                        # 기존과 동일하게 "한 번이라도 있었던 전체 인원"만 보임.
                        dcc.DatePickerRange(
                            id='list-period-range',
                            start_date_placeholder_text='시작일',
                            end_date_placeholder_text='종료일',
                            display_format='YYYY-MM-DD',
                            disabled=True,
                            className='mt-1',
                            style={'fontSize': '0.72rem'},
                        ),
                        html.Div(
                            '기간 지정 시 그 기간 내 마지막 상태 기준으로 조회(부서·과제·직급·직책 필터 다시 사용 가능)',
                            id='list-period-hint',
                            className='text-muted', style={'fontSize': '0.68rem', 'display': 'none'},
                        ),
                    ], md=3),
                    dbc.Col([
                        dbc.Label('부서', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-dept', options=dept_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=3),
                    dbc.Col([
                        dbc.Label('과제/파트', className='small fw-semibold text-muted mb-1'),
                        dcc.Dropdown(id='filter-project', options=project_opts, multi=True,
                                     placeholder='전체', clearable=True),
                    ], md=3),
                    dbc.Col([
                        dbc.Label(' ', className='small d-block mb-1'),  # 라벨 줄 높이 맞춤
                        dbc.ButtonGroup([
                            dbc.Button([html.I(className='bi bi-funnel me-1'), '필터'],
                                       id='open-filter-btn', color='secondary', outline=True,
                                       title='상세 필터(직급/직책/성별/학력/전공/재직상태)'),
                            dbc.Button(html.I(className='bi bi-search'), id='list-search-btn',
                                       color='primary', title='검색(필터 적용)'),
                            dbc.Button(html.I(className='bi bi-file-earmark-excel'), id='list-excel-btn',
                                       color='success', title='엑셀 다운로드(현재 화면에 보이는 대상)'),
                            dbc.Button(html.I(className='bi bi-sliders'), id='list-excel-options-btn',
                                       color='secondary', outline=True,
                                       title='추가 항목 선택(보유 전문성, 직무, 재직상태 등)'),
                            dbc.Button(html.I(className='bi bi-printer'), id='list-bulk-print-btn',
                                       color='info',
                                       title='프로필 일괄 인쇄(체크한 사람, 없으면 현재 화면에 보이는 전체)'),
                        ], className='w-100'),
                        # 엑셀 다운로드에 포함할 추가 항목 — 항상 노출하지 않고
                        # 위 아이콘(list-excel-options-btn) 클릭 시 뜨는 가벼운
                        # 팝오버로 옮겼다(사용자 요청). trigger='click'이라 별도
                        # 열기/닫기 콜백 없이 dbc가 알아서 토글한다.
                        dbc.Popover(
                            dbc.Checklist(
                                id='list-excel-options-check',
                                options=[
                                    {'label': '보유 전문성 포함', 'value': 'expertise'},
                                    {'label': '특허 포함', 'value': 'patents'},
                                    {'label': '논문 포함', 'value': 'publications'},
                                    {'label': '직무 포함', 'value': 'job_function'},
                                    {'label': '직무이력 포함', 'value': 'job_profile'},
                                    {'label': '재직상태 포함', 'value': 'employment_status'},
                                    {'label': '어학 포함', 'value': 'language'},
                                    {'label': '근무 경력 포함', 'value': 'work_experience'},
                                ],
                                value=[], switch=True,
                                className='small',
                            ),
                            target='list-excel-options-btn', trigger='click',
                            placement='bottom', body=True,
                        ),
                        html.Div(
                            '프로필 인쇄: 표에서 원하는 행을 체크하면 그 인원만, '
                            '체크가 없으면 현재 필터·검색 결과 전체를 인쇄합니다(과제/부서로 '
                            '필터해두면 그 풀 전체를 한 번에 인쇄할 수 있습니다).',
                            className='text-muted mt-1', style={'fontSize': '0.72rem'},
                        ),
                    ], md=3),
                ], className='g-3'),
            ),
            className='mb-3 shadow-sm',
        ),

        # ── 상세 필터 모달 ────────────────────────────────────────────────
        # 메인 화면에서 뺀 직급/직책/성별/학력/전공/재직상태를 별도 창(모달)
        # 으로 열어 선택한다(사용자 요청). '과제'는 메인 화면에 이미 있어
        # 중복 배치하지 않았다.
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle('상세 필터')),
                dbc.ModalBody(
                    dbc.Row([
                        dbc.Col([
                            dbc.Label('직급', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-pos', options=pos_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('직책', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-title', options=title_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('성별', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-gender', options=gender_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('학력', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-degree', options=degree_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('전공', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-major', options=major_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                        dbc.Col([
                            dbc.Label('재직상태', className='small fw-semibold text-muted mb-1'),
                            dcc.Dropdown(id='filter-employment', options=employ_opts, multi=True,
                                         placeholder='전체', clearable=True),
                        ], md=6, className='mb-3'),
                    ], className='g-2'),
                ),
                dbc.ModalFooter([
                    dbc.Button('초기화', id='filter-modal-clear-btn', color='secondary', outline=True, size='sm'),
                    dbc.Button('적용', id='filter-modal-apply-btn', color='primary', size='sm'),
                ]),
            ],
            id='filter-modal', is_open=False,
        ),

        # ── DataTable ─────────────────────────────────────────────────────
        dbc.Card(
            dbc.CardBody(
                dash_table.DataTable(
                    id='researcher-table',
                    columns=columns,
                    data=display_df.to_dict('records') if not display_df.empty else [],
                    # 필터 / 정렬
                    filter_action='native',
                    sort_action='native',
                    sort_mode='multi',
                    # 행 체크박스(프로필 일괄 인쇄용 — 없으면 화면에 보이는 전체를 인쇄)
                    row_selectable='multi',
                    selected_rows=[],
                    # 페이지
                    page_action='native',
                    page_size=30,
                    # 스타일
                    style_as_list_view=True,
                    style_table={'overflowX': 'auto'},
                    style_header={
                        'backgroundColor': '#1e3a5f',
                        'color': 'white',
                        'fontWeight': '600',
                        'fontSize': '0.8rem',
                        'textAlign': 'center',
                        'whiteSpace': 'normal',
                    },
                    # 검색(필터) 행이라는 게 눈에 띄도록 배경/테두리를 뚜렷하게
                    # 준다(사용자 확정 — "검색 가능한 행이라는 걸 보여주면 좋겠다").
                    style_filter={
                        'backgroundColor': '#eaf2fb',
                        'fontSize': '0.75rem',
                        'borderTop': '2px solid #1e3a5f',
                        'borderBottom': '2px solid #cfe0f3',
                    },
                    style_cell={
                        'fontSize': '0.82rem',
                        'padding': '5px 10px',
                        'textAlign': 'center',
                        'minWidth': '55px',
                        'maxWidth': '160px',
                        'overflow': 'hidden',
                        'textOverflow': 'ellipsis',
                    },
                    style_cell_conditional=[
                        {'if': {'column_id': '이름'}, 'textAlign': 'left', 'minWidth': '80px',
                         'fontWeight': '600', 'cursor': 'pointer', 'color': '#1e3a5f'},
                        {'if': {'column_id': '부서'}, 'textAlign': 'left', 'minWidth': '100px'},
                        {'if': {'column_id': '과제'}, 'textAlign': 'left', 'minWidth': '100px'},
                    ],
                    style_data_conditional=style_data_conditional,
                    tooltip_header={col['id']: col['id'] for col in columns},
                    tooltip_data=_build_tooltip_data(display_df.to_dict('records') if not display_df.empty else []),
                    tooltip_delay=0,
                    tooltip_duration=None,
                    # 대소문자 구분 없이 항상 필터(사용자 확정) + 필터 행 자체에
                    # 브라우저 네이티브 CSS resize로 컬럼 너비 드래그 조절(admin.py
                    # team-refer-table과 동일한 트릭).
                    filter_options={'case': 'insensitive', 'placeholder_text': '🔍 검색...'},
                    css=[
                        {
                            'selector': '.column-header-name',
                            'rule': ('display: inline-block; resize: horizontal; overflow: auto; '
                                     'min-width: 40px; max-width: 600px; vertical-align: bottom;'),
                        },
                        # 대소문자 토글 아이콘(Aa) 숨김 — filter_options.case로 이미
                        # 항상 대소문자 무시로 고정했으니 토글 자체가 필요 없다.
                        {'selector': '.dash-filter--case', 'rule': 'display: none;'},
                    ],
                ),
                className='p-0',
            ),
            className='shadow-sm',
        ),

        html.P(
            '행을 클릭하면 해당 연구원의 개별 프로필 화면으로 이동합니다.',
            className='text-muted small mt-2 mb-0',
        ),
    ])


# ── 콜백 1: 부서 선택(+ 검색 기준/기간) → 과제/파트 드롭다운 옵션 캐스케이딩 ────
# 기간을 지정한 상태(누적기준 + 기간)면 그 기간 기준 team_refer로 옵션을
# 만든다(2026-08-29 추가) — 부서를 먼저 바꾸든 기간을 먼저 바꾸든 둘 다
# 이 콜백을 다시 트리거해 최종적으로는 항상 "선택된 부서 + 현재 기간"
# 기준으로 수렴한다.
@callback(
    Output('filter-project', 'options'),
    Input('filter-dept', 'value'),
    Input('list-search-mode', 'value'),
    Input('list-period-range', 'start_date'),
    Input('list-period-range', 'end_date'),
)
def update_project_options(dept, mode, period_start, period_end):
    period = _active_period(mode, period_start, period_end)
    return similarity_map.pjt_part_filter_options(dept, period=period)


# ── 콜백 1-1: 검색 기준(현재/누적) → 부서·과제·직급·직책 필터 비활성화 + 부서
# 옵션 갱신 ────────────────────────────────────────────────────────────────
# 누적기준에서는 조직 배치(부서/과제/직급/직책)가 최신 시점 기준이 아닐 수 있어
# 혼란을 줄 수 있으므로 비활성화하고 값도 비운다 — 이름/사번(테이블 자체
# 필터 행)으로만 찾도록 유도한다. 성별/학력/전공/재직상태는 시점에 덜
# 민감해 그대로 둔다. 다만 누적기준에서 기간(시작~종료)까지 지정하면
# researchers_history.csv에서 그 기간의 마지막 스냅샷을 쓰므로(사용자 요청,
# data/processed/CLAUDE.md 2026-08-28 참고) 부서/과제/직급/직책도 그 시점
# 기준으로 다시 의미가 있어져 필터를 도로 켠다.
#
# '부서' 드롭다운 옵션 자체도 이 콜백에서 기간 기준으로 다시 계산한다
# (2026-08-29 추가 — 이전엔 layout() 최초 렌더링 시 오늘 기준으로 한 번만
# 만들고 끝이었다). 기간이 바뀌면(옵션 자체가 그 시점 기준으로 달라질 수
# 있으므로) 부서/과제 선택값을 초기화한다 — 이전 기간에 고른 값이 새
# 기간엔 없는 옵션일 수 있어서. 직급/직책 옵션은 team_refer가 아니라
# researchers.csv 기준이라 이 갱신과 무관해 값을 그대로 둔다.
@callback(
    Output('filter-dept', 'disabled'),
    Output('filter-project', 'disabled'),
    Output('filter-pos', 'disabled'),
    Output('filter-title', 'disabled'),
    Output('filter-dept', 'options'),
    Output('filter-dept', 'value', allow_duplicate=True),
    Output('filter-project', 'value', allow_duplicate=True),
    Output('filter-pos', 'value', allow_duplicate=True),
    Output('filter-title', 'value', allow_duplicate=True),
    Output('list-period-range', 'disabled'),
    Output('list-period-hint', 'style'),
    Input('list-search-mode', 'value'),
    Input('list-period-range', 'start_date'),
    Input('list-period-range', 'end_date'),
    prevent_initial_call=True,
)
def toggle_org_filters(mode, period_start, period_end):
    period = _active_period(mode, period_start, period_end)
    is_cumulative = (mode == 'all')
    has_period = period is not None
    hint_style = {'fontSize': '0.68rem', 'display': 'block' if has_period else 'none'}
    dept_options = similarity_map.department_filter_options(period=period)

    if has_period:
        return (False, False, False, False, dept_options, None, None, no_update, no_update,
                False, hint_style)
    if is_cumulative:
        return True, True, True, True, dept_options, None, None, None, None, False, hint_style
    return (False, False, False, False, dept_options, no_update, no_update, no_update, no_update,
            True, hint_style)


# ── 콜백 2: 검색 버튼(필터 적용) / 필터 초기화 버튼 → 테이블 데이터 갱신 ──────
# 드롭다운 값은 State로만 읽는다 — 선택하는 즉시가 아니라 검색 아이콘을 눌러야
# 테이블에 반영된다(사용자 확정). 필터 초기화 버튼은 이 콜백에도 함께 연결해,
# 눌렀을 때 드롭다운 값과 무관하게 항상 전체 목록으로 되돌아가게 한다.
@callback(
    Output('researcher-table', 'data'),
    Output('researcher-table', 'columns'),
    Output('researcher-table', 'tooltip_header'),
    Output('researcher-table', 'tooltip_data'),
    Output('researcher-table', 'selected_rows'),
    Output('researcher-table', 'style_data_conditional'),
    Input('list-search-btn',   'n_clicks'),
    Input('filter-modal-apply-btn', 'n_clicks'),
    Input('clear-filters-btn', 'n_clicks'),
    Input('list-search-mode',  'value'),
    Input('nl-query-full-result', 'data'),
    State('filter-dept',       'value'),
    State('filter-project',    'value'),
    State('filter-pos',        'value'),
    State('filter-title',      'value'),
    State('filter-gender',     'value'),
    State('filter-degree',     'value'),
    State('filter-major',      'value'),
    State('filter-employment', 'value'),
    State('list-period-range', 'start_date'),
    State('list-period-range', 'end_date'),
    prevent_initial_call=True,
)
def update_table(_search_clicks, _apply_clicks, _clear_clicks, mode, ai_result, dept, project, pos, title,
                  gender, degree, major, employment, period_start, period_end):
    from services.auth import can, eval_excluded_dep_ids
    show_eval = can('view_evaluation')
    show_incentive = can('view_incentive')
    excluded_dep_ids = eval_excluded_dep_ids()

    current_only = (mode != 'all')
    period = _active_period(mode, period_start, period_end)
    df = _build_summary_df(current_only=current_only, period=period)
    display_df = _apply_permission_filter(
        df, show_eval, show_incentive,
        excluded_dep_ids, similarity_map.org_code_dep_id_map(),
    )
    # 기간을 지정했을 땐 그 시점 기준 값이 있어 부서/과제/직급/직책 필터도
    # 다시 쓸 수 있다(toggle_org_filters 콜백과 동일한 조건).
    filters_active = current_only or bool(period)

    triggered = dash.ctx.triggered_id

    # AI 검색 결과가 있으면 명단 자체를 그 결과로 바꾼다(사용자 요청: 완전
    # 통합) — 기존 부서/과제/직급/직책/성별/학력/전공/재직상태 필터는 이때
    # 적용하지 않는다(AI 검색 질문 자체가 이미 그 필터 역할을 한다).
    if triggered == 'nl-query-full-result':
        if not ai_result or not ai_result.get('rows'):
            # 질문 없음/초기화/결과 없음 → 필수 컬럼만으로 전체 목록 복귀
            columns = _build_columns(display_df)
            tooltip_header = {c['id']: c['id'] for c in columns}
            records = display_df.to_dict('records')
            return (records, columns, tooltip_header, _build_tooltip_data(records), [],
                    _style_data_conditional_for(columns, show_eval))
        merged_df, extra_ids, extra_labels = _merge_ai_result(display_df, ai_result)
        columns = _build_columns(merged_df, extra_ids=extra_ids, extra_labels=extra_labels)
        tooltip_header = {c['id']: c['id'] for c in columns}
        records = merged_df.to_dict('records')
        return (records, columns, tooltip_header, _build_tooltip_data(records), [],
                _style_data_conditional_for(columns, show_eval))

    # 상세 필터(성별/학력/전공)로 값을 고르면 그 컬럼도 함께 보여준다.
    optional_values = dict(zip(_OPTIONAL_FILTER_COLUMNS, (gender, degree, major)))
    optional_ids = [col for col in _OPTIONAL_FILTER_COLUMNS if optional_values[col]]
    columns = _build_columns(display_df, optional_ids=optional_ids)
    tooltip_header = {c['id']: c['id'] for c in columns}
    style_data_conditional = _style_data_conditional_for(columns, show_eval)
    if display_df.empty:
        return [], columns, tooltip_header, [], [], style_data_conditional

    # 모드 전환 자체가 트리거면(부서/과제/직급/직책 필터가 비활성화·초기화되는
    # 시점과 겹칠 수 있어) 조직 필터는 적용하지 않고 전체(해당 모드) 목록을 보여준다.
    if triggered in ('clear-filters-btn', 'list-search-mode'):
        records = display_df.to_dict('records')
        return records, columns, tooltip_header, _build_tooltip_data(records), [], style_data_conditional

    # 부서/과제·파트 필터는 team_refer의 dep_name/pjt_part_name을 라벨로 쓰지만,
    # 실제 매칭은 항상 org_name_wd(=researchers.csv의 org_code, 화면에는 안
    # 보이는 내부 컬럼 '_org_code')로 한다 — 라벨 문자열이 researchers.csv
    # 표기와 다를 수 있어 라벨로 직접 비교하지 않는다(services.similarity_map
    # 참고). '과제' 컬럼 자체는 이제 표시용 pjt_part_name 라벨이라 이 매칭에
    # 쓸 수 없다(사용자 확정 — 명단 '과제/파트' 열을 team_refer 라벨로 표시).
    # period가 주어지면(누적기준 + 기간 지정) 그 기간 기준 team_refer로
    # 매칭한다(2026-08-29 추가) — 선택한 부서/과제 이름이 그 시점에 실제로
    # 그 org_code를 가리켰는지 오늘 기준이 아니라 그 시점 기준으로 판단한다.
    if dept and filters_active:
        org_codes = similarity_map.org_codes_for_dep_names(dept, period=period)
        display_df = display_df[display_df['_org_code'].isin(org_codes)]
    if project and filters_active:
        org_codes = similarity_map.org_codes_for_pjt_part_names(project, period=period)
        display_df = display_df[display_df['_org_code'].isin(org_codes)]
    if pos and filters_active:
        display_df = display_df[display_df['직급'].isin(pos)]
    if title and filters_active:
        display_df = display_df[display_df['직책'].isin(title)]
    if gender:
        display_df = display_df[display_df['성별'].isin(gender)]
    if degree:
        display_df = display_df[display_df['학력'].isin(degree)]
    if major:
        display_df = display_df[display_df['전공'].isin(major)]
    if employment:
        display_df = display_df[display_df['재직상태'].isin(employment)]
    records = display_df.to_dict('records')
    return records, columns, tooltip_header, _build_tooltip_data(records), [], style_data_conditional


# ── 콜백 3: 필터 초기화 버튼 → 드롭다운 값 비우기(메인 화면 + 필터 모달) ─────
@callback(
    Output('filter-dept',       'value'),
    Output('filter-project',    'value'),
    Output('filter-pos',        'value'),
    Output('filter-title',      'value'),
    Output('filter-gender',     'value'),
    Output('filter-degree',     'value'),
    Output('filter-major',      'value'),
    Output('filter-employment', 'value'),
    Input('clear-filters-btn', 'n_clicks'),
    Input('filter-modal-clear-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def clear_filters(_clear_clicks, _modal_clear_clicks):
    return None, None, None, None, None, None, None, None


# ── 콜백 3-1: '필터' 버튼 → 상세 필터 모달 열기/닫기 ──────────────────────────
# 열기는 '필터' 버튼만, 닫기는 모달의 '적용'/'닫기'(X) 버튼 모두에 반응한다.
@callback(
    Output('filter-modal', 'is_open'),
    Input('open-filter-btn', 'n_clicks'),
    Input('filter-modal-apply-btn', 'n_clicks'),
    prevent_initial_call=True,
)
def toggle_filter_modal(_open_clicks, _apply_clicks):
    return dash.ctx.triggered_id == 'open-filter-btn'


# ── 콜백 4: 엑셀 다운로드 — 지금 화면에 실제로 보이는(검색 필터 + 표 자체
# 열별 필터/정렬까지 반영된) 대상자들의 프로필을 다운로드 ───────────────────
@callback(
    Output('researcher-list-excel-download', 'data'),
    Input('list-excel-btn', 'n_clicks'),
    State('researcher-table', 'derived_virtual_data'),
    State('list-excel-options-check', 'value'),
    prevent_initial_call=True,
)
def download_excel(n_clicks, virtual_data, excel_options):
    if not n_clicks or not virtual_data:
        return no_update
    researcher_ids = [row['researcher_id'] for row in virtual_data if row.get('researcher_id')]
    if not researcher_ids:
        return no_update
    excel_options = excel_options or []
    data = researcher_profile_export.build_profile_workbook(
        researcher_ids,
        include_expertise='expertise' in excel_options,
        include_patents='patents' in excel_options,
        include_publications='publications' in excel_options,
        include_job_function='job_function' in excel_options,
        include_job_profile='job_profile' in excel_options,
        include_employment_status='employment_status' in excel_options,
        include_language='language' in excel_options,
        include_work_experience='work_experience' in excel_options,
    )
    return dcc.send_bytes(data, researcher_profile_export.default_filename())


# ── 콜백 5: 행 클릭 → 프로필 화면 이동 ──────────────────────────────────────
@callback(
    Output('list-url', 'href'),
    Input('researcher-table', 'active_cell'),
    State('researcher-table', 'derived_virtual_data'),
    prevent_initial_call=True,
)
def navigate_to_profile(active_cell, virtual_data):
    if not active_cell or not virtual_data:
        return no_update
    row_idx = active_cell.get('row')
    if row_idx is None or row_idx >= len(virtual_data):
        return no_update
    rid = virtual_data[row_idx].get('researcher_id')
    if not rid:
        return no_update
    return f'/?id={rid}'


# ── 콜백 6: 프로필 일괄 인쇄 버튼 → 여러 명 인쇄 화면으로 이동 ────────────────
# 체크한 행이 있으면 그 사람들만, 없으면 지금 화면에 보이는(검색 필터 +
# 표 자체 열별 필터/정렬까지 반영된, 엑셀 다운로드와 동일한 기준) 전체를
# 대상으로 삼는다 — 과제/부서로 필터해두고 그냥 누르면 그 풀 전체가,
# 체크박스로 일부만 고르면 그 인원만 인쇄 화면(/?ids=...)으로 넘어간다.
@callback(
    Output('list-url', 'href', allow_duplicate=True),
    Input('list-bulk-print-btn', 'n_clicks'),
    State('researcher-table', 'derived_virtual_data'),
    State('researcher-table', 'selected_rows'),
    prevent_initial_call=True,
)
def bulk_print_navigate(n_clicks, virtual_data, selected_rows):
    if not n_clicks or not virtual_data:
        return no_update
    if selected_rows:
        rows = [virtual_data[i] for i in selected_rows if i < len(virtual_data)]
    else:
        rows = virtual_data
    researcher_ids = [row['researcher_id'] for row in rows if row.get('researcher_id')]
    if not researcher_ids:
        return no_update
    return '/?ids=' + ','.join(researcher_ids)
