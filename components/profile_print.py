"""
연구원 개별 프로필 — 선택한 항목만 골라 A4 한 장에 인쇄/PDF로 출력하는
화면 구성.

"무조건 1장 안에 다 들어가야 한다"(사용자 확정)는 요구를 만족시키기 위해
두 가지를 함께 쓴다:
  1) 목록형 항목(양성/시상/인사발령/과제/논문/특허)은 항상 최근 N건만 보여
     주고 나머지는 "외 N건"으로 요약한다(내용 자체를 미리 짧게 만듦).
  2) 각 항목은 services.print_layout이 저장한 그리드 좌표에 맞춰 물리적
     크기가 고정된 칸(overflow: hidden)에 그려진다 — 데이터가 그 칸보다
     많아도 페이지가 늘어나는 대신 칸 안에서 잘린다(assets/custom.css의
     .print-block 규칙). 배치(어디에 놓을지)는 전 사용자 공통 템플릿 하나로
     관리자가 미리 만들어두고, 인쇄할 때는 어떤 항목을 포함할지만 고른다.

화면·엑셀 다운로드에 이미 있는 렌더러를 최대한 재사용하되, 목록형 항목은
그 렌더러들이 전체 이력을 다 보여주는 용도라 개수 제한이 없어서, 이 모듈
에서 별도로 "최근 N건 + 외 N건" 요약 함수를 만들어 쓴다.
"""

from datetime import datetime

import pandas as pd
from dash import html

from components.detail_tabs import llm_summary_block, owned_expertise_block
from components.profile_sections import (
    AWARD_TYPES,
    comments_block,
    education_block,
    evaluation_incentive_block,
    nurturing_block,
    photo_block,
)
from components.timeline_data import dedupe_patents, job_points
from components.timeline_view import filter_hr_rows
from services.evaluations import evaluation_years
from services.print_layout import (  # noqa: F401 (재노출 — pages/researcher_profile.py에서 사용)
    BLOCK_DEFS,
    DEFAULT_EXPERTISE,
    DEFAULT_LAYOUT,
    DEFAULT_PERSONNEL,
    EXPERTISE_FIELDS,
    GRID_COLS,
    GRID_ROWS,
    PERSONNEL_FIELDS,
    read_layout,
    sanitize_layout,
    write_layout,
)

_TOP_N = 4  # 목록형 항목이 칸 안에 보여줄 최대 건수(그 이상은 "외 N건").
_LEADERSHIP_DIMS = ['미래통찰', '성과창출', '몰입촉진', '인재육성', '자기관리', '저해행동']


def _as_list(children) -> list:
    """llm_summary_block()은 데이터가 있으면 list, 없으면 단일 html.Div를
    반환해 반환 타입이 갈린다 — 항상 리스트로 맞춰서 다루기 쉽게 한다."""
    return children if isinstance(children, list) else [children]


def _titled(title: str, body) -> html.Div:
    return html.Div([html.P(title, className='print-block-title'), body], className='print-block-body')


def _lines_block(lines: list) -> html.Div:
    total = len(lines)
    shown = lines[:_TOP_N]
    children = [html.Div(str(line), className='print-line') for line in shown]
    if total > len(shown):
        children.append(html.Div(f'외 {total - len(shown)}건', className='print-line print-more'))
    if not children:
        children = [html.Div('내역 없음', className='print-line print-muted')]
    return html.Div(children)


def _sorted_rows(df: pd.DataFrame, rid: str, sort_col: str, ascending: bool = False) -> pd.DataFrame:
    if df.empty:
        return df
    rows = df[df['researcher_id'] == rid]
    if rows.empty or sort_col not in rows.columns:
        return rows
    return rows.sort_values(sort_col, ascending=ascending)


def _award_lines(awd_df: pd.DataFrame, rid: str) -> list:
    rows = _sorted_rows(awd_df, rid, 'year')
    if not rows.empty and 'award_type' in rows.columns:
        rows = rows[rows['award_type'].isin(AWARD_TYPES)]
    lines = []
    for _, row in rows.iterrows():
        yr = str(row.get('year', '')).strip()
        yr_label = f"'{yr[-2:]}" if len(yr) >= 2 else yr
        lines.append(' '.join(p for p in (yr_label, str(row.get('award_name', '')).strip()) if p))
    return lines


def _hr_lines(hr_df: pd.DataFrame, rid: str) -> list:
    rows = filter_hr_rows(hr_df, rid)
    lines = []
    for _, row in rows.iterrows():
        date = str(row.get('order_date', '')).strip()[:7]
        name = str(row.get('order_name', '')).strip()
        lines.append(' '.join(p for p in (date, name) if p))
    return lines


def _tasks_lines(task_df: pd.DataFrame, rid: str) -> list:
    rows = _sorted_rows(task_df, rid, 'start_date')
    lines = []
    for _, row in rows.iterrows():
        the_name = str(row.get('the_task_name', '') or '').strip()
        name = the_name or str(row.get('task_name', '') or '').strip() or '-'
        start = str(row.get('start_date', ''))[:7]
        lines.append(f'{name} ({start}~)' if start else name)
    return lines


def _job_profile_lines(job_df: pd.DataFrame, rid: str) -> list:
    rows = job_df[job_df['researcher_id'] == rid] if not job_df.empty else job_df
    points = job_points(rows)
    points.sort(key=lambda p: p['start'], reverse=True)
    return [
        f"{p['name']} ({p['start'].strftime('%y')}~{p['end'].strftime('%y') if p['end'] else '현재'})"
        for p in points
    ]


def _publications_lines(pub_df: pd.DataFrame, rid: str) -> list:
    sort_col = 'pub_date' if not pub_df.empty and 'pub_date' in pub_df.columns else 'pub_year'
    rows = _sorted_rows(pub_df, rid, sort_col)
    lines = []
    for _, row in rows.iterrows():
        date = str(row.get('pub_year', '') or row.get('pub_date', ''))[:7]
        title = str(row.get('title', '') or '').strip()
        lines.append(f'{date} {title}' if date else title)
    return lines


def _patents_lines(pat_df: pd.DataFrame, rid: str) -> list:
    pat = pat_df[pat_df['researcher_id'] == rid] if not pat_df.empty else pat_df
    if pat.empty:
        return []
    pat = dedupe_patents(pat)
    sort_col = 'application_date' if 'application_date' in pat.columns else pat.columns[0]
    pat = pat.sort_values(sort_col, ascending=False)
    lines = []
    for _, row in pat.iterrows():
        date = str(row.get('application_date', ''))[:7]
        title = str(row.get('title', '') or row.get('title_ko', '') or '').strip()
        lines.append(f'{date} {title}' if date else title)
    return lines


def _leadership_lines(lea_df: pd.DataFrame, rid: str, year) -> list | None:
    """components.profile_sections.leadership_figure()와 동일한 데이터 선택
    기준(연구원 본인의 '타인평균' 행 vs 전체 '타인평균' 행 평균)을 그대로
    따르되, 레이더 차트 대신 한 줄짜리 텍스트로 만든다 — 인쇄용 그래프는
    렌더링 타이밍(비동기 Plotly 그리기와 인쇄 트리거 경쟁)과 강제 폰트 축소가
    차트 라벨을 깨뜨릴 위험이 있어, 안정적인 텍스트 요약으로 대체했다."""
    if lea_df.empty or not year:
        return None
    selected = lea_df[
        (lea_df['researcher_id'] == rid)
        & (lea_df['year'].astype(str) == str(year))
        & (lea_df['evaluator_group'] == '타인평균')
    ]
    if selected.empty:
        return None
    row = selected.iloc[0]
    all_others = lea_df[lea_df['evaluator_group'] == '타인평균']
    lines = []
    for dim in _LEADERSHIP_DIMS:
        try:
            val = float(row[dim])
        except (KeyError, TypeError, ValueError):
            continue
        avg = all_others[dim].mean() if dim in all_others.columns and not all_others.empty else None
        if avg is not None and pd.notna(avg):
            lines.append(f'{dim} {val:.1f} (평균 {avg:.1f})')
        else:
            lines.append(f'{dim} {val:.1f}')
    return lines


# ── 블록별 렌더러 — 전부 (rid, researcher_row, tables, profile, similar, name_map,
# leadership_year) 시그니처로 통일해 build_print_sheet()에서 하나의 표로 호출한다. ──

def _render_identity(rid, researcher_row, tables, _profile, _similar, _name_map, _leadership_year):
    dept = str(researcher_row.get('department', '') or '').strip()
    org = str(researcher_row.get('org_code', '') or '').strip()
    hire_date = str(researcher_row.get('hire_date', '') or '').strip()[:10]
    org_label = dept + (f' ({org})' if org else '')
    children = photo_block(rid, str(researcher_row.get('name', '')), researcher_row, datetime.now().year) + [
        html.Div(org_label or '-', className='print-line'),
        html.Div(f'입사일 {hire_date}' if hire_date else '', className='print-line print-muted'),
        html.Div(f"출력일 {datetime.now().strftime('%Y-%m-%d')}", className='print-line print-muted'),
    ]
    return html.Div(children, className='print-identity')


def _render_education(rid, _researcher_row, tables, *_rest):
    return _titled('학력', education_block(tables['education'], rid))


def _render_evaluation(rid, _researcher_row, tables, *_rest):
    years = sorted(evaluation_years()[0])
    return _titled('평가 · 인센티브', evaluation_incentive_block(
        tables['evaluations'], tables['incentive_selection'], rid, years))


def _render_nurturing(rid, _researcher_row, tables, *_rest):
    nur = tables['nurturing']
    total = len(nur[nur['researcher_id'] == rid]) if not nur.empty else 0
    children = [nurturing_block(nur, rid, limit=_TOP_N)]
    if total > _TOP_N:
        children.append(html.Div(f'외 {total - _TOP_N}건', className='print-line print-more'))
    return _titled('양성 이력', html.Div(children))


def _render_award(rid, _researcher_row, tables, *_rest):
    return _titled('시상 이력', _lines_block(_award_lines(tables['awards'], rid)))


def _render_hr_orders(rid, _researcher_row, tables, *_rest):
    return _titled('인사발령 이력', _lines_block(_hr_lines(tables['hr_orders'], rid)))


def _render_leadership(rid, _researcher_row, tables, _profile, _similar, _name_map, leadership_year):
    lines = _leadership_lines(tables['leadership'], rid, leadership_year)
    if not lines:
        return _titled('리더십 진단', html.Div('데이터 없음', className='print-line print-muted'))
    return _titled('리더십 진단', html.Div([html.Div(l, className='print-line') for l in lines]))


def _render_comments(rid, _researcher_row, tables, *_rest):
    return _titled('인물 코멘트', comments_block(tables['comments'], rid))


def _render_expertise_summary(_rid, _researcher_row, _tables, profile, similar, name_map, _leadership_year):
    content = _as_list(llm_summary_block(profile, similar, name_map))
    return _titled('전문성 요약', html.Div(content, className='print-expertise-text'))


def _render_owned_expertise(rid, _researcher_row, tables, *_rest):
    core_df = tables['core_technology']
    core_rid = core_df[core_df['researcher_id'] == rid] if not core_df.empty else core_df
    # owned_expertise_block이 내부에서 다시 researcher_id로 필터링하므로, 이미
    # 필터링·상한을 적용한 df를 넘겨도 그대로 유지된다 — 핵심기술 행이 많은
    # 사람도 이 칸 안에서 개수가 무한정 늘어나지 않도록 상한을 건다.
    core_capped = core_rid.head(_TOP_N)
    return _titled('보유 전문성', owned_expertise_block(core_capped, tables['tech_ownership'], rid))


def _render_tasks(rid, _researcher_row, tables, *_rest):
    return _titled('과제 수행 이력', _lines_block(_tasks_lines(tables['tasks'], rid)))


def _render_job_profile(rid, _researcher_row, tables, *_rest):
    return _titled('직무 이력', _lines_block(_job_profile_lines(tables['job_profile'], rid)))


def _render_publications(rid, _researcher_row, tables, *_rest):
    return _titled('논문 요약', _lines_block(_publications_lines(tables['publications'], rid)))


def _render_patents(rid, _researcher_row, tables, *_rest):
    return _titled('특허 요약', _lines_block(_patents_lines(tables['patents'], rid)))


_RENDERERS = {
    'identity': _render_identity,
    'education': _render_education,
    'evaluation': _render_evaluation,
    'nurturing': _render_nurturing,
    'award': _render_award,
    'hr_orders': _render_hr_orders,
    'leadership': _render_leadership,
    'comments': _render_comments,
    'expertise_summary': _render_expertise_summary,
    'owned_expertise': _render_owned_expertise,
    'tasks': _render_tasks,
    'job_profile': _render_job_profile,
    'publications': _render_publications,
    'patents': _render_patents,
}


def render_layout_editor_blocks(layout: dict | None = None) -> list:
    """레이아웃 편집기 캔버스(components/print_layout_editor.js가 드래그/
    리사이즈를 붙이는 대상)에 넣을 블록 목록 — BLOCK_DEFS 전체(14개)를 항상
    다 보여준다(인쇄 시 실제로 포함할지는 이 화면과 무관하게 체크리스트에서
    따로 고름 — 배치는 항목 선택과 별개로 전체를 미리 잡아둔다)."""
    layout = sanitize_layout(layout)
    blocks = []
    for key, label, group, _perm in BLOCK_DEFS:
        pos = layout[key]
        style = {
            'gridColumn': f"{pos['x'] + 1} / span {pos['w']}",
            'gridRow': f"{pos['y'] + 1} / span {pos['h']}",
        }
        blocks.append(html.Div(
            [html.Span(label, className='pl-block-label'), html.Div(className='pl-resize-handle')],
            className=f'pl-block pl-block-{group}', style=style, **{'data-key': key},
        ))
    return blocks


def build_print_sheet(rid: str, researcher_row, tables: dict, profile: dict | None, similar: list,
                       name_map: dict, leadership_year, selected_personnel: list,
                       selected_expertise: list, layout: dict | None = None) -> html.Div:
    """A4 한 장(services.print_layout의 그리드) 위에, 선택된 항목만 저장된
    좌표에 맞춰 배치한다. layout을 안 주면 저장된 공통 템플릿(read_layout())을
    그대로 쓴다 — 레이아웃 편집기 미리보기처럼 아직 저장 전인 배치를 바로
    반영하고 싶을 때만 layout을 직접 넘긴다."""
    layout = sanitize_layout(layout) if layout is not None else read_layout()
    selected = {'identity'} | set(selected_personnel or []) | set(selected_expertise or [])

    blocks = []
    for key in selected:
        render_fn = _RENDERERS.get(key)
        pos = layout.get(key)
        if render_fn is None or pos is None:
            continue
        content = render_fn(rid, researcher_row, tables, profile, similar, name_map, leadership_year)
        style = {
            'gridColumn': f"{pos['x'] + 1} / span {pos['w']}",
            'gridRow': f"{pos['y'] + 1} / span {pos['h']}",
        }
        blocks.append(html.Div(content, className='print-block', style=style))

    return html.Div(html.Div(blocks, className='print-grid'), className='print-sheet')
