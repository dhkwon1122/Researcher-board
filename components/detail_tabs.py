from collections import defaultdict
from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

# ── 세로(수직) 타임라인 ──────────────────────────────────────────────────────
# 중앙에 독립 스파인(x=0)을 두고, 과제는 겹치는 기간에만 좌우로 레인을 나눠
# 세로 막대로 표시한다. 과제 진행 기간 중 발생한 논문·특허·인사발령은 그 과제
# 레인에서 화살표(선+화살촉)로 가지처럼 뻗어나가 아이콘+텍스트로 표시되고,
# 과제가 없던 공백 기간에 발생한 항목은 중앙 스파인에서 바로 뻗어나간다.
# y축(날짜)은 기본 방향을 그대로 사용 — 값이 클수록(최신일수록) 위에 그려진다.
SPINE_X = 0.0
TASK_LANE_UNIT = 1.05      # 과제 레인 간 x 간격(스파인 기준 좌우 교대 배치)
BRANCH_BASE = 0.55         # 과제 레인 → 이벤트 아이콘까지 기본 가지 길이
BRANCH_STEP = 0.42         # 같은 레인에서 시점이 가까운 이벤트를 추가로 밀어내는 간격
ORPHAN_BRANCH = 0.55       # 공백기간(스파인 직결) 이벤트의 기본 가지 길이

TIMELINE_COLORS = {
    '인사발령': '#1baf7a',
    '논문':     '#eda100',
    '특허':     '#008300',
}
# 과제는 항목마다 다른 색을 쓰되, 위 3개 카테고리 색은 피한다.
TASK_COLOR_PALETTE = ['#2a78d6', '#4a3aa7', '#e34948', '#e87ba4', '#eb6834']
_SPINE_COLOR = '#c4c8cf'
_LEGEND_NEUTRAL = '#52514e'

_GRIDLINE = '#eef0f2'
_CHART_FONT = "'Inter','Noto Sans KR',sans-serif"
_TOOLTIP_BG = '#18181b'
_TOOLTIP_FG = '#f4f4f5'
_MARKER_RING = '#ffffff'

_ICONS = {'논문': '📄', '특허': '💡', '인사발령': '🧭'}

_DENSIFY_N = 10            # 과제 레인 위에서 어디를 호버해도 되도록 배치할 보조 포인트 수
_TRUNCATE_LEN = 30         # 호버/라벨 텍스트 기본 최대 길이(단어 경계에서 자르고 ... 표시)


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

    if not task_points and not hr_points and not pub_points and not pat_points:
        return html.Div('타임라인 데이터 없음', className='text-muted p-3')

    today = pd.Timestamp(datetime.now().date())
    all_dates = (
        [d for seg in task_points for d in (seg['start'], seg['end'])]
        + [p['date'] for p in hr_points]
        + [p['date'] for p in pub_points]
        + [p['date'] for p in pat_points]
    )
    min_date = min(all_dates) if all_dates else today
    max_date = max(all_dates + [today])
    pad = max(pd.Timedelta(days=20), (max_date - min_date) * 0.04)
    y_range = [min_date - pad, max_date + pad]

    total_days = max((y_range[1] - y_range[0]).days, 1)
    min_gap_days = max(12, total_days * 0.02)

    # 과제 레인 배정 — 실제로 기간이 겹치는 과제만 좌우로 분리 배치.
    task_items = sorted(task_points, key=lambda t: t['start'])
    lane_items = [{'start': t['start'], 'end': t['end']} for t in task_items]
    levels = _assign_levels(lane_items)
    for t, lvl in zip(task_items, levels):
        t['x'] = _level_to_offset(lvl + 1, TASK_LANE_UNIT)

    task_colors = _task_colors(task_points)

    # 논문/특허/인사발령 → 발생 시점에 진행 중이던 과제에 배정(겹치면 가장 나중에
    # 시작된 과제 하나만). 진행 중인 과제가 없으면 스파인에 직접 배정(독립 표시).
    events = []
    for p in pub_points:
        events.append({
            'date': p['date'], 'kind': '논문', 'label': _pub_label(p),
            'hover': f"<b>{_truncate(p['title'])}</b>",
        })
    for p in pat_points:
        events.append({
            'date': p['date'], 'kind': '특허', 'label': _patent_label(p),
            'hover': f"<b>{_truncate(p['title'])}</b>",
        })
    for p in hr_points:
        events.append({
            'date': p['date'], 'kind': '인사발령', 'label': _hr_label(p), 'hover': None,
        })

    for e in events:
        e['host'] = _host_task(e['date'], task_items)

    # 같은 레인(과제 또는 스파인)에서 시점이 가까운 이벤트는 겹치지 않도록
    # 가지 길이를 단계적으로 늘린다.
    groups = defaultdict(list)
    for e in events:
        groups[id(e['host']) if e['host'] is not None else 'orphan'].append(e)
    for grp in groups.values():
        grp.sort(key=lambda e: e['date'])
        half = pd.Timedelta(days=min_gap_days / 2)
        stagger_items = [{'start': e['date'] - half, 'end': e['date'] + half} for e in grp]
        for e, lvl in zip(grp, _assign_levels(stagger_items)):
            e['stagger'] = lvl

    fig = go.Figure()
    _add_spine(fig, y_range)
    _add_task_lanes(fig, task_items, task_colors)
    _add_event_traces(fig, events)

    max_lane = max((abs(t['x']) for t in task_items), default=0.0)
    max_stagger = max((e['stagger'] for e in events), default=0)
    max_x = max_lane + TASK_LANE_UNIT + BRANCH_BASE + max_stagger * BRANCH_STEP + 2.8
    x_range = [-max_x, max_x]

    fig.update_layout(
        font=dict(family=_CHART_FONT, size=12, color='#52525b'),
        xaxis=dict(range=x_range, visible=False, fixedrange=True),
        yaxis=dict(range=y_range, type='date', gridcolor=_GRIDLINE, showline=False,
                   tickfont=dict(size=11, color='#a1a1aa')),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0,
                    groupclick='togglegroup', font=dict(size=11.5),
                    itemsizing='constant'),
        hoverlabel=dict(namelength=-1),
        hovermode='closest',
        hoverdistance=15,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=_chart_height(y_range),
    )

    graph = dcc.Graph(figure=fig, config={'displayModeBar': False})
    summary = _summary_cards(task, pub, pat_dedup)
    scroll_wrap = html.Div(graph, style={'maxHeight': '620px', 'overflowY': 'auto', 'overflowX': 'hidden'})
    return html.Div([summary, scroll_wrap]) if summary is not None else html.Div([scroll_wrap])


def _chart_height(y_range):
    """세로 타임라인 실제 픽셀 높이 — 기간이 길수록 커지고, 카드는 고정 높이로 스크롤."""
    years = max((y_range[1] - y_range[0]).days / 365, 1)
    return int(min(2200, max(460, 165 * years)))


def expertise_tab(expertise_df, rid):
    """과제 이력 기반 전문성 분류 결과 표시 (data/processed/researcher_expertise.csv).
    CLOSE 3: 참여 과제 전체를 종합했을 때 가장 가까운 기술분류 3개.
    FAR 3: 과제별로는 후보에 올랐지만 최종 전문성과 가장 거리가 먼 기술분류 3개.
    """
    if expertise_df.empty:
        return html.Div('전문성 분석 데이터 없음', className='text-muted p-3')
    rows = expertise_df[expertise_df['researcher_id'] == rid]
    if rows.empty:
        return html.Div('전문성 분석 데이터 없음', className='text-muted p-3')

    close = rows[rows['kind'] == 'CLOSE'].sort_values('rank')
    far = rows[rows['kind'] == 'FAR'].sort_values('rank')

    def _item(row):
        category = f"{row.get('category_top', '')} > {row.get('category_mid', '')} > {row.get('category_name', '')}"
        similarity = row.get('similarity', '')
        reason = str(row.get('reason', '')).strip()
        children = [
            html.Span(category, className='fw-semibold me-2'),
            html.Span(f'(유사도 {similarity})', className='text-muted small'),
        ]
        if reason and reason not in ('nan', 'None'):
            children.append(html.Div(reason, className='small text-muted mt-1'))
        return html.Li(children, className='mb-3')

    blocks = [
        html.P('전문성 CLOSE 3', className='section-label mb-2'),
        html.Ul([_item(r) for _, r in close.iterrows()], className='ps-3 mb-0')
        if not close.empty else html.Div('데이터 없음', className='text-muted small mb-3'),
    ]

    if not far.empty:
        blocks += [
            html.P('전문성 FAR 3', className='section-label mb-2 mt-3', style={'color': '#c98a1c'}),
            html.Ul([_item(r) for _, r in far.iterrows()], className='ps-3 mb-0'),
        ]

    return html.Div(blocks)


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


def _truncate(text, maxlen=_TRUNCATE_LEN):
    """maxlen을 넘으면 단어 중간을 자르지 않고 단어 경계에서 잘라 '...'을 붙인다."""
    text = str(text).strip()
    if len(text) <= maxlen:
        return text
    cut = text[:maxlen]
    if ' ' in cut:
        cut = cut.rsplit(' ', 1)[0]
    return cut.rstrip() + '...'


def _hoverlabel(color):
    """카테고리 색은 테두리로만 표시하는 다크 카드형 툴팁 (모던 대시보드 스타일)."""
    return dict(
        bgcolor=_TOOLTIP_BG,
        bordercolor=color,
        font=dict(color=_TOOLTIP_FG, size=12, family=_CHART_FONT),
        align='left',
    )


def _level_to_offset(level, unit):
    """0 -> 중앙, 1 -> +unit, 2 -> -unit, 3 -> +2*unit, 4 -> -2*unit, ... (중앙선 기준 위/아래 교대 배치)"""
    if level == 0:
        return 0.0
    n = (level + 1) // 2
    sign = 1 if level % 2 == 1 else -1
    return sign * n * unit


def _assign_levels(items):
    """구간이 실제로 겹치는 경우에만 레벨을 분리 (items는 start 오름차순 정렬 상태)."""
    if not items:
        return []
    lane_ends = []
    levels = [0] * len(items)
    for i, it in enumerate(items):
        placed = False
        for lvl, lane_end in enumerate(lane_ends):
            if it['start'] >= lane_end:
                lane_ends[lvl] = it['end']
                levels[i] = lvl
                placed = True
                break
        if not placed:
            lane_ends.append(it['end'])
            levels[i] = len(lane_ends) - 1
    return levels


def _host_task(date, task_items):
    """date 시점에 진행 중이던 과제를 찾는다. 여러 개면 가장 나중에 시작된 과제
    (동률이면 더 일찍 끝나는, 즉 더 짧고 구체적인 과제) 하나만 반환. 없으면 None."""
    candidates = [t for t in task_items if t['start'] <= date <= t['end']]
    if not candidates:
        return None
    candidates.sort(key=lambda t: t['start'])
    latest_start = candidates[-1]['start']
    tied = [t for t in candidates if t['start'] == latest_start]
    return tied[0] if len(tied) == 1 else min(tied, key=lambda t: t['end'])


def _add_spine(fig, y_range):
    fig.add_trace(go.Scatter(
        x=[SPINE_X, SPINE_X], y=[y_range[0], y_range[1]], mode='lines',
        line=dict(color=_SPINE_COLOR, width=2, dash='dot'),
        hoverinfo='skip', showlegend=False,
    ))


def _add_task_lanes(fig, task_items, task_colors):
    if not task_items:
        return

    # 범례는 과제별 색과 무관하게 중립색 하나로 대표 표시 (실제 색 구분은 차트에서 호버로 확인)
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode='markers', name='과제', legendgroup='과제',
        marker=dict(symbol='circle', size=9, color=_LEGEND_NEUTRAL,
                    line=dict(color=_MARKER_RING, width=1.5)),
        showlegend=True, hoverinfo='skip',
    ))

    for t in task_items:
        color = task_colors[t['task_name']]
        x = t['x']
        hover = f"<b>{_truncate(t['task_name'])}</b><br>{t['start_label']} → {t['end_label']}"

        fig.add_trace(go.Scatter(
            x=[x, x], y=[t['start'], t['end']],
            mode='lines+markers', name='과제', legendgroup='과제', showlegend=False,
            marker=dict(symbol='circle', size=8, color=color,
                        line=dict(color=_MARKER_RING, width=1.5)),
            line=dict(color=color, width=3),
            hoverinfo='skip',
        ))

        # 레인 전체에서 어디를 호버해도 과제 정보가 뜨도록 촘촘한 보조 포인트 배치
        dense_y = _densify_dates(t['start'], t['end'], _DENSIFY_N)
        fig.add_trace(go.Scatter(
            x=[x] * len(dense_y), y=dense_y,
            mode='markers', name='과제', legendgroup='과제', showlegend=False,
            marker=dict(size=6, opacity=0),
            text=[hover] * len(dense_y), hovertemplate='%{text}',
            hoverlabel=_hoverlabel(color),
        ))

        # 과제명 라벨 (레인 끝에 상시 표시)
        fig.add_trace(go.Scatter(
            x=[x], y=[t['end']], mode='text', text=[_truncate(t['task_name'], 16)],
            textposition='top center', textfont=dict(size=10.5, color=color),
            name='과제', legendgroup='과제', showlegend=False, hoverinfo='skip',
            cliponaxis=False,
        ))


def _add_event_traces(fig, events):
    if not events:
        return

    by_kind = {'논문': [], '특허': [], '인사발령': []}
    for e in events:
        by_kind[e['kind']].append(e)

    for kind, items in by_kind.items():
        if not items:
            continue
        color = TIMELINE_COLORS[kind]
        icon = _ICONS[kind]

        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode='markers', name=kind, legendgroup=kind,
            marker=dict(symbol='circle', size=9, color=color,
                        line=dict(color=_MARKER_RING, width=1.5)),
            showlegend=True, hoverinfo='skip',
        ))

        shaft_x, shaft_y = [], []
        tip_x, tip_y, tip_symbol = [], [], []
        text_x, text_y, text_str, text_pos = [], [], [], []
        hover_x, hover_y, hover_txt = [], [], []

        for e in items:
            origin_x = e['host']['x'] if e['host'] is not None else SPINE_X
            direction = 1 if origin_x >= 0 else -1
            branch_base = BRANCH_BASE if e['host'] is not None else ORPHAN_BRANCH
            tip = origin_x + direction * (branch_base + e['stagger'] * BRANCH_STEP)

            shaft_x += [origin_x, tip, None]
            shaft_y += [e['date'], e['date'], None]
            tip_x.append(tip)
            tip_y.append(e['date'])
            tip_symbol.append('triangle-right' if direction > 0 else 'triangle-left')
            text_x.append(tip)
            text_y.append(e['date'])
            text_str.append(f'{icon}  {e["label"]}')
            text_pos.append('middle right' if direction > 0 else 'middle left')
            if e['hover']:
                hover_x.append(tip)
                hover_y.append(e['date'])
                hover_txt.append(e['hover'])

        fig.add_trace(go.Scatter(
            x=shaft_x, y=shaft_y, mode='lines',
            line=dict(color=color, width=1.5),
            name=kind, legendgroup=kind, showlegend=False, hoverinfo='skip',
        ))
        fig.add_trace(go.Scatter(
            x=tip_x, y=tip_y, mode='markers',
            marker=dict(symbol=tip_symbol, size=9, color=color,
                        line=dict(color=_MARKER_RING, width=1.2)),
            name=kind, legendgroup=kind, showlegend=False, hoverinfo='skip',
        ))
        fig.add_trace(go.Scatter(
            x=text_x, y=text_y, mode='text', text=text_str, textposition=text_pos,
            textfont=dict(size=11.5, color=color),
            name=kind, legendgroup=kind, showlegend=False, hoverinfo='skip',
            cliponaxis=False,
        ))
        if hover_x:
            fig.add_trace(go.Scatter(
                x=hover_x, y=hover_y, mode='markers',
                marker=dict(size=18, opacity=0),
                text=hover_txt, hovertemplate='%{text}',
                name=kind, legendgroup=kind, showlegend=False,
                hoverlabel=_hoverlabel(color),
            ))


def _yymm(ts):
    return ts.strftime('%y.%m') if isinstance(ts, pd.Timestamp) else ''


def _patent_label(p):
    date_str = _yymm(p['date'])
    grade, grade_a = p['grade'], p['grade_a']
    grade_str = f'{grade}({grade_a})' if grade and grade_a else grade
    parts = ['특허', date_str, grade_str]
    if p['share']:
        parts.append(f"{p['share']}%")
    if p['is_lead'] == 'Y':
        parts.append('대표자')
    return ' · '.join(x for x in parts if x)


def _pub_label(p):
    date_str = _yymm(p['date'])
    parts = ['논문', date_str, _truncate(p['journal'], 16), p['author_type'], p['contribution']]
    return ' · '.join(x for x in parts if x and x not in ('nan', 'None'))


def _hr_label(p):
    date_str = _yymm(p['date'])
    dep = f"{_truncate(p['order_name'], 14)}({_truncate(p['order_dep'], 10)})" if p['order_dep'] else _truncate(p['order_name'], 14)
    cl = f"{p['order_cl']}({p['order_assignment']})" if p['order_assignment'] else p['order_cl']
    parts = ['인사발령', date_str, dep, cl]
    return ' · '.join(x for x in parts if x)


def _densify_dates(start, end, n=12):
    if n <= 1 or start == end:
        return [start]
    span = end - start
    return [start + span * (i / (n - 1)) for i in range(n)]


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
        points.append({
            'date': date,
            'order_date': str(row.get('order_date', '')).strip(),
            'order_name': str(row.get('order_name', '')).strip(),
            'order_dep': str(row.get('order_dep', '')).strip(),
            'order_cl': str(row.get('order_cl', '')).strip(),
            'order_assignment': _clean(row.get('order_assignment', '')),
        })
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
        points.append({
            'date': date,
            'title': str(row.get('title', '')).strip(),
            'journal': _clean(row.get('journal', '')),
            'author_type': _clean(row.get('author_type', '')),
            'contribution': _clean(row.get('contribution', '')),
        })
    points.sort(key=lambda p: p['date'])
    return points


def _clean(value):
    s = str(value).strip()
    return '' if s in ('nan', 'None', 'NaT') else s


def _pat_points(pat_df):
    if pat_df.empty:
        return []
    points = []
    for _, row in pat_df.iterrows():
        app_date = _clean(row.get('application_date', ''))
        reg_date = _clean(row.get('registration_date', ''))
        date = _parse_ts(reg_date if reg_date else app_date)
        if date is None:
            continue
        title = _cell(row, 'title', 'title_ko')
        grade = _clean(row.get('patent_grade', ''))
        grade_a = _clean(row.get('patent_grade_a_sub', ''))
        grade_a = '' if grade_a == '없음' else grade_a
        share = _clean(row.get('share_ratio', ''))
        is_lead = _clean(row.get('is_lead_inventor', ''))
        points.append({
            'date': date,
            'title': title,
            'grade': grade,
            'grade_a': grade_a,
            'share': share,
            'is_lead': is_lead,
        })
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
        html.H5(str(value), className=f'fw-bold stat-value {color} mb-0'),
        html.Small(label, className='text-muted'),
    ], className='text-center px-2')


def _single_card(value, label, color):
    return dbc.Card(dbc.CardBody(_stat(value, label, color), className='p-2'),
                    className='profile-card h-100', style={'backgroundColor': '#fafafa'})
