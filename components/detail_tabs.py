from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

# 인사발령·과제이력 레인은 y=1, 논문·특허 레인은 y=0 을 중심선으로 사용한다.
LANE_TOP = 1.0
LANE_BOTTOM = 0.0

TIMELINE_COLORS = {
    '인사발령': '#1baf7a',
    '논문':     '#eda100',
    '특허':     '#008300',
}
# 과제는 항목마다 다른 색을 쓰되, 위 3개 카테고리 색(aqua/yellow/green)은 피한다.
TASK_COLOR_PALETTE = ['#2a78d6', '#4a3aa7', '#e34948', '#e87ba4', '#eb6834']
_LEGEND_NEUTRAL = '#52514e'

_MUTED_INK = '#898781'
_GRIDLINE = '#e1e0d9'

# 레인 중심선 기준 위/아래 오프셋 간격
_OFFSET_UNIT_TASK = 0.14
_OFFSET_UNIT_POINT = 0.10
# 호버 텍스트박스를 레인 중심에서 얼마나 멀리(위/아래) 띄울지 — 레인을 공유하는
# 두 카테고리가 서로 다른 밴드에 뜨도록 카테고리별로 다른 값을 준다.
_ANCHOR_SHIFT = {'과제': 0.22, '인사발령': 0.38, '논문': 0.22, '특허': 0.38}
_DENSIFY_N = 12


def timeline_tab(task_df, hr_df, pub_df, pat_df, rid):
    task = task_df[task_df['researcher_id'] == rid].copy() if not task_df.empty else pd.DataFrame()
    hr = hr_df[hr_df['researcher_id'] == rid].copy() if not hr_df.empty else pd.DataFrame()
    pub = pub_df[pub_df['researcher_id'] == rid].copy() if not pub_df.empty else pd.DataFrame()
    pat = pat_df[pat_df['researcher_id'] == rid].copy() if not pat_df.empty else pd.DataFrame()
    pat_dedup = _dedupe_patents(pat) if not pat.empty else pat

    if task.empty and hr.empty and pub.empty and pat.empty:
        return html.Div('타임라인 데이터 없음', className='text-muted p-3')

    task_points = _task_points(task)
    hr_points = _hr_points(hr)
    pub_points = _pub_points(pub)
    pat_points = _pat_points(pat_dedup)

    today = pd.Timestamp(datetime.now().date())
    all_dates = (
        [d for seg in task_points for d in (seg['start'], seg['end'])]
        + [p['date'] for p in hr_points]
        + [p['date'] for p in pub_points]
        + [p['date'] for p in pat_points]
    )
    min_date = min(all_dates) if all_dates else today
    pad = max(pd.Timedelta(days=15), (today - min_date) * 0.03)
    x_range = [min_date - pad, today + pd.Timedelta(days=15)]

    total_days = max((x_range[1] - x_range[0]).days, 1)
    min_gap_days = max(10, total_days * 0.015)

    task_levels = _assign_task_levels(task_points)
    task_colors = _task_colors(task_points)
    hr_levels = _declutter_levels(hr_points, min_gap_days)
    pub_levels = _declutter_levels(pub_points, min_gap_days)
    pat_levels = _declutter_levels(pat_points, min_gap_days)

    fig = go.Figure()
    _add_task_category(fig, task_points, task_levels, task_colors, x_range)
    _add_point_category(fig, '인사발령', hr_points, hr_levels, LANE_TOP,
                         symbol='star', size=12, x_range=x_range)
    _add_point_category(fig, '논문', pub_points, pub_levels, LANE_BOTTOM,
                         symbol='square', size=9, x_range=x_range)
    _add_point_category(fig, '특허', pat_points, pat_levels, LANE_BOTTOM,
                         symbol='triangle-up', size=10, x_range=x_range)

    y_top_max = LANE_TOP + _ANCHOR_SHIFT['인사발령'] + _OFFSET_UNIT_POINT + 0.15
    y_bottom_min = LANE_BOTTOM - _ANCHOR_SHIFT['특허'] - _OFFSET_UNIT_POINT - 0.15

    fig.update_layout(
        xaxis=dict(range=x_range, type='date', gridcolor=_GRIDLINE),
        yaxis=dict(range=[y_bottom_min, y_top_max], tickmode='array',
                   tickvals=[LANE_BOTTOM, LANE_TOP],
                   ticktext=['논문 · 특허', '인사발령 · 과제이력'],
                   gridcolor=_GRIDLINE, zeroline=False),
        legend=dict(orientation='v', yanchor='top', y=1, xanchor='right', x=1,
                    groupclick='togglegroup'),
        hoverlabel=dict(namelength=-1),
        hovermode='closest',
        hoverdistance=60,
        margin=dict(l=10, r=10, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=460,
    )

    graph = dcc.Graph(figure=fig, config={'displayModeBar': False})
    summary = _summary_cards(task, pub, pat_dedup)
    return html.Div([summary, graph]) if summary is not None else html.Div([graph])


def _summary_cards(task_df, pub_df, pat_dedup_df):
    cards = []
    if not task_df.empty:
        cards.append(dbc.Col(_single_card(len(task_df), '과제 수', 'text-primary'), md=2))
    if not pub_df.empty:
        cards.append(dbc.Col(_single_card(len(pub_df), '논문 수', 'text-warning'), md=2))
    if not pat_dedup_df.empty:
        cards.append(dbc.Col(_single_card(len(pat_dedup_df), '특허 수', 'text-success'), md=2))
    if not cards:
        return None
    return dbc.Row(cards, className='mb-3 g-2')


def _mid(x_range):
    return x_range[0] + (x_range[1] - x_range[0]) / 2


def _level_to_offset(level, unit):
    """0 -> 중앙, 1 -> +unit, 2 -> -unit, 3 -> +2*unit, 4 -> -2*unit, ... (중앙선 기준 위/아래 교대 배치)"""
    if level == 0:
        return 0.0
    n = (level + 1) // 2
    sign = 1 if level % 2 == 1 else -1
    return sign * n * unit


def _add_task_category(fig, task_points, task_levels, task_colors, x_range):
    if not task_points:
        fig.add_annotation(x=_mid(x_range), y=LANE_TOP, text='과제 데이터 없음',
                            showarrow=False, font=dict(color=_MUTED_INK, size=12))
        return

    # 범례는 과제별 색과 무관하게 중립색 하나로 대표 표시 (실제 색 구분은 차트에서 호버로 확인)
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode='markers', name='과제', legendgroup='과제',
        marker=dict(symbol='circle', size=9, color=_LEGEND_NEUTRAL),
        showlegend=True, hoverinfo='skip',
    ))

    for seg, level in zip(task_points, task_levels):
        y = LANE_TOP + _level_to_offset(level, _OFFSET_UNIT_TASK)
        color = task_colors[seg['task_name']]
        hover = f"{seg['task_name']} | {seg['start_label']} ~ {seg['end_label']}"

        fig.add_trace(go.Scatter(
            x=[seg['start'], seg['end']], y=[y, y],
            mode='lines+markers', name='과제', legendgroup='과제', showlegend=False,
            marker=dict(symbol='circle', size=9, color=color),
            line=dict(color=color, width=2.5),
            hoverinfo='skip',
        ))

        # 선분 전체에서 호버가 동작하도록 촘촘한 보조 포인트를 깔고,
        # 호버 텍스트박스가 레인 중심에서 위로 떨어져 표시되도록 y를 offset한다.
        dense_x = _densify_dates(seg['start'], seg['end'], _DENSIFY_N)
        anchor_y = y + _ANCHOR_SHIFT['과제']
        fig.add_trace(go.Scatter(
            x=dense_x, y=[anchor_y] * len(dense_x),
            mode='markers', name='과제', legendgroup='과제', showlegend=False,
            marker=dict(size=16, opacity=0),
            text=[hover] * len(dense_x), hovertemplate='%{text}',
        ))


def _add_point_category(fig, label, points, levels, lane_base, *, symbol, size, x_range):
    if not points:
        fig.add_annotation(x=_mid(x_range), y=lane_base, text=f'{label} 데이터 없음',
                            showarrow=False, font=dict(color=_MUTED_INK, size=12))
        return

    color = TIMELINE_COLORS[label]
    xs = [p['date'] for p in points]
    ys = [lane_base + _level_to_offset(lvl, _OFFSET_UNIT_POINT) for lvl in levels]
    texts = [p['hover'] for p in points]

    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode='markers', name=label, legendgroup=label,
        marker=dict(symbol=symbol, size=size, color=color),
        hoverinfo='skip',
    ))

    # 호버 텍스트박스를 레인 중심에서 위/아래로 떨어뜨려 표시 (마커를 가리지 않도록)
    sign = 1 if lane_base >= LANE_TOP else -1
    anchor_ys = [y + sign * _ANCHOR_SHIFT[label] for y in ys]
    fig.add_trace(go.Scatter(
        x=xs, y=anchor_ys, mode='markers', name=label, legendgroup=label, showlegend=False,
        marker=dict(size=16, opacity=0),
        text=texts, hovertemplate='%{text}',
    ))


def _densify_dates(start, end, n=12):
    if n <= 1 or start == end:
        return [start]
    span = end - start
    return [start + span * (i / (n - 1)) for i in range(n)]


def _declutter_levels(points, min_gap_days):
    """서로 min_gap_days 이내로 가까운 점들을 다른 레벨로 분리 (0, +1, -1, +2, -2 ...)."""
    if not points:
        return []
    order = sorted(range(len(points)), key=lambda i: points[i]['date'])
    slot_last = []
    levels = [0] * len(points)
    for i in order:
        d = points[i]['date']
        placed = False
        for slot_idx, last_date in enumerate(slot_last):
            if (d - last_date).days >= min_gap_days:
                slot_last[slot_idx] = d
                levels[i] = slot_idx
                placed = True
                break
        if not placed:
            slot_last.append(d)
            levels[i] = len(slot_last) - 1
    return levels


def _assign_task_levels(points):
    """과제 기간이 실제로 겹치는 경우에만 레벨을 분리 (points는 start 오름차순 정렬 상태)."""
    if not points:
        return []
    lane_ends = []
    levels = [0] * len(points)
    for i, p in enumerate(points):
        placed = False
        for lvl, lane_end in enumerate(lane_ends):
            if p['start'] >= lane_end:
                lane_ends[lvl] = p['end']
                levels[i] = lvl
                placed = True
                break
        if not placed:
            lane_ends.append(p['end'])
            levels[i] = len(lane_ends) - 1
    return levels


def _task_colors(points):
    names = list(dict.fromkeys(p['task_name'] for p in points))
    return {name: TASK_COLOR_PALETTE[i % len(TASK_COLOR_PALETTE)] for i, name in enumerate(names)}


def _parse_ts(val):
    s = str(val).strip() if val is not None else ''
    if not s or s in ('nan', 'None', 'NaT'):
        return None
    try:
        return pd.Timestamp(s)
    except (ValueError, TypeError):
        return None


def _task_points(task_df):
    if task_df.empty:
        return []
    today = pd.Timestamp(datetime.now().date())
    points = []
    for _, row in task_df.iterrows():
        start = _parse_ts(row.get('start_date'))
        if start is None:
            continue
        end_raw = row.get('end_date')
        end = _parse_ts(end_raw)
        end_label = end.strftime('%Y-%m-%d') if end is not None else '진행중'
        if end is None or end < start:
            end = today
        points.append({
            'task_name': str(row.get('task_name', '')).strip(),
            'start': start,
            'end': end,
            'start_label': start.strftime('%Y-%m-%d'),
            'end_label': end_label,
        })
    points.sort(key=lambda p: p['start'])
    return points


def _hr_points(hr_df):
    if hr_df.empty:
        return []
    points = []
    for _, row in hr_df.iterrows():
        date = _parse_ts(row.get('order_date'))
        if date is None:
            continue
        hover = (f"{str(row.get('order_date', '')).strip()} | "
                 f"{str(row.get('order_name', '')).strip()} | "
                 f"{str(row.get('order_dep', '')).strip()} | "
                 f"{str(row.get('order_cl', '')).strip()}")
        points.append({'date': date, 'hover': hover})
    points.sort(key=lambda p: p['date'])
    return points


def _pub_points(pub_df):
    if pub_df.empty:
        return []
    points = []
    for _, row in pub_df.iterrows():
        pub_date = str(row.get('pub_date', '')).strip()
        if not pub_date or pub_date in ('nan', 'None'):
            pub_year = str(row.get('pub_year', '')).strip()
            pub_date = f'{pub_year}-01-01' if pub_year and pub_year not in ('nan', 'None') else ''
        date = _parse_ts(pub_date)
        if date is None:
            continue
        title = str(row.get('title', '')).strip()
        journal = str(row.get('journal', '')).strip()
        author_type = str(row.get('author_type', '')).strip()
        hover = f'{pub_date} | {title} | {journal} | {author_type}'
        points.append({'date': date, 'hover': hover})
    points.sort(key=lambda p: p['date'])
    return points


def _pat_points(pat_df):
    if pat_df.empty:
        return []
    points = []
    for _, row in pat_df.iterrows():
        app_date = str(row.get('application_date', '')).strip()
        date = _parse_ts(app_date)
        if date is None:
            continue
        title = _cell(row, 'title', 'title_ko')
        grade = str(row.get('patent_grade', '')).strip()
        grade_a = str(row.get('patent_grade_a_sub', '')).strip()
        grade_str = grade + (' (전략출원)' if grade_a == '전략출원' else '')
        share = str(row.get('share_ratio', '')).strip()
        lead = str(row.get('is_lead_inventor', '')).strip()
        hover = f'{app_date} | {title} | {grade_str} | 지분율 {share}% | 대표발명자 {lead}'
        points.append({'date': date, 'hover': hover})
    points.sort(key=lambda p: p['date'])
    return points


def _is_registered(value):
    return '등록' in str(value)


def _cell(row, *keys, default='-'):
    for key in keys:
        value = str(row.get(key, ''))
        if value and value not in ('', 'nan', 'None'):
            return value
    return default


def _dedupe_patents(pat):
    id_col = 'application_id' if 'application_id' in pat.columns else None
    if not id_col:
        return pat.copy()

    def _merge_countries(series):
        seen = {}
        for value in series:
            text = str(value).strip()
            if text in ('', 'nan', 'None', '-'):
                continue
            for part in text.split(','):
                part = part.strip()
                if part:
                    seen[part] = None
        return ', '.join(seen.keys()) if seen else '-'

    def _agg_status(series):
        values = series.astype(str).tolist()
        for value in values:
            if _is_registered(value):
                return value
        return values[0] if values else ''

    agg_dict = {col: 'first' for col in pat.columns if col not in (id_col, 'researcher_id', 'country', 'status')}
    if 'status' in pat.columns:
        agg_dict['status'] = _agg_status
    if 'country' in pat.columns:
        agg_dict['country'] = _merge_countries
    return pat.groupby(id_col, sort=False).agg(agg_dict).reset_index()


def _stat(value, label, color):
    return html.Div([
        html.H5(str(value), className=f'fw-bold {color} mb-0'),
        html.Small(label, className='text-muted'),
    ], className='text-center px-2')


def _single_card(value, label, color):
    return dbc.Card(dbc.CardBody(_stat(value, label, color), className='p-2'),
                    className='border-0 bg-light h-100')
