import json
from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

# 과제이력·논문·특허는 하나의 통합 레인(y=0 중심)을 공유하고,
# 인사발령은 그 위 별도 영역(텍스트 + 아래를 향한 화살표)에 표시한다.
# (5, 6번 요청: 인사발령 라벨 간 간격은 넉넉히, 대신 메인 레인과의 상하 간격은 좁게)
MAIN_LANE = 0.0
HR_ARROW_TIP_Y = 0.30
HR_TEXT_BASE_Y = 0.48
HR_TEXT_LEVEL_GAP = 0.16
_HR_TEXT_CLEARANCE = 0.05   # 발령명 텍스트 바로 아래까지만 여백을 두고 선을 시작
_HR_ARROW_CLEARANCE = 0.03  # 화살촉 바로 위까지만 여백을 두고 선을 마무리

TIMELINE_COLORS = {
    '인사발령': '#1baf7a',
    '논문':     '#eda100',
    '특허':     '#008300',
}
# 과제는 항목마다 다른 색을 쓰되, 위 3개 카테고리 색(aqua/yellow/green)은 피한다.
TASK_COLOR_PALETTE = ['#2a78d6', '#4a3aa7', '#e34948', '#e87ba4', '#eb6834']
_LEGEND_NEUTRAL = '#52514e'

_GRIDLINE = '#e1e0d9'

_OFFSET_UNIT_MAIN = 0.13   # 통합 레인 중심선 기준 위/아래 오프셋 간격
_DENSIFY_N = 14            # 과제 연결선을 따라 호버가 되도록 촘촘히 배치하는 보조 포인트 수
_NEAR_EXCLUDE_DAYS = 3     # 논문/특허 지점 근처의 과제 보조 포인트를 제외해 점의 호버를 우선시
_TRUNCATE_LEN = 36         # 호버 텍스트 한 줄당 최대 길이(단어 경계에서 자르고 ... 표시)
_HR_GAP_MULTIPLIER = 3     # 인사발령 라벨은 텍스트라 마커보다 더 넓은 간격이 필요해 배수 적용


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

    # 과제·논문·특허를 하나의 레인으로 놓고, 세 카테고리를 통틀어 겹치는 항목만
    # 중앙선 기준 위/아래로 분리한다.
    items = _combined_items(task_points, pub_points, pat_points, min_gap_days)
    levels = _assign_levels(items)
    for item, level in zip(items, levels):
        item['ref']['y'] = MAIN_LANE + _level_to_offset(level, _OFFSET_UNIT_MAIN)

    task_colors = _task_colors(task_points)

    # 인사발령 라벨은 겹치는 시점이 있으면 단계적으로 더 위에 표시.
    # 라벨은 마커보다 폭이 넓은 텍스트라 더 넉넉한 간격 기준을 사용한다.
    hr_min_gap_days = min_gap_days * _HR_GAP_MULTIPLIER
    hr_levels = _declutter_levels(hr_points, hr_min_gap_days)
    for p, level in zip(hr_points, hr_levels):
        p['label_y'] = HR_TEXT_BASE_Y + level * HR_TEXT_LEVEL_GAP

    exclude_dates = [p['date'] for p in pub_points] + [p['date'] for p in pat_points]

    fig = go.Figure()
    _add_task_traces(fig, task_points, task_colors, exclude_dates)
    _add_pub_trace(fig, pub_points)
    _add_pat_trace(fig, pat_points)
    _add_hr_traces(fig, hr_points)

    max_offset = max((abs(_level_to_offset(lvl, _OFFSET_UNIT_MAIN)) for lvl in levels), default=0.0)
    main_top = max_offset + 0.15
    main_bottom = -(max_offset + 0.15)
    hr_top = (max(p['label_y'] for p in hr_points) if hr_points else HR_TEXT_BASE_Y) + 0.25
    y_top = max(main_top, hr_top)

    fig.update_layout(
        xaxis=dict(range=x_range, type='date', gridcolor=_GRIDLINE),
        yaxis=dict(range=[main_bottom, y_top], tickmode='array',
                   tickvals=[MAIN_LANE], ticktext=['과제이력<br>논문<br>특허'],
                   gridcolor=_GRIDLINE, zeroline=False),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0,
                    groupclick='togglegroup'),
        hoverlabel=dict(namelength=-1),
        hovermode='closest',
        hoverdistance=15,
        margin=dict(l=10, r=10, t=40, b=30),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=460,
    )

    graph = dcc.Graph(figure=fig, config={'displayModeBar': False})
    summary = _summary_cards(task, pub, pat_dedup)
    return html.Div([summary, graph]) if summary is not None else html.Div([graph])


def expertise_tab(expertise_df, rid):
    """과제 이력 기반 LLM 전문성 분석 결과 표시 (data/processed/task_expertise.csv)."""
    if expertise_df.empty:
        return html.Div('전문성 분석 데이터 없음', className='text-muted p-3')
    row = expertise_df[expertise_df['researcher_id'] == rid]
    if row.empty:
        return html.Div('전문성 분석 데이터 없음', className='text-muted p-3')
    row = row.iloc[0]

    try:
        parsed = json.loads(row.get('expertise_json', '') or '{}')
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    expertise = parsed.get('expertise') or []
    caution_flags = parsed.get('caution_flags') or []

    matched = row.get('matched_task_count', '')
    total = row.get('total_task_count', '')
    header = html.Small(f'매칭된 과제 {matched}/{total}건 기반 분석', className='text-muted d-block mb-3')

    if not expertise:
        return html.Div([header, html.Div('전문성 분석 데이터 없음', className='text-muted p-3')])

    expertise_items = [
        html.Li([
            html.Span(str(item.get('keyword', '')), className='fw-semibold me-2'),
            html.Span(f"— {item.get('evidence', '')}", className='text-muted small'),
        ], className='mb-2')
        for item in expertise
    ]

    blocks = [
        header,
        html.P('전문성 분석', className='fw-semibold small mb-2'),
        html.Ul(expertise_items, className='ps-3 mb-0'),
    ]

    if caution_flags:
        caution_items = [
            html.Li([
                html.I(className='bi bi-question-circle-fill text-warning me-2'),
                html.Span(f"{flag.get('from_task', '')} → {flag.get('to_task', '')}",
                          className='fw-semibold me-2'),
                html.Span(str(flag.get('reason', '')), className='text-muted small'),
            ], className='mb-2')
            for flag in caution_flags
        ]
        blocks += [
            html.P('확인 필요', className='fw-semibold text-warning small mb-2 mt-3'),
            html.Ul(caution_items, className='ps-3 mb-0'),
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


def _hover_font_color(hex_color):
    """호버박스 배경색(hex_color) 대비 잘 보이는 글자색(흑/백)을 계산."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return '#0b0b0b' if luminance > 0.6 else '#ffffff'


def _hoverlabel(color):
    return dict(bgcolor=color, font=dict(color=_hover_font_color(color)))


def _level_to_offset(level, unit):
    """0 -> 중앙, 1 -> +unit, 2 -> -unit, 3 -> +2*unit, 4 -> -2*unit, ... (중앙선 기준 위/아래 교대 배치)"""
    if level == 0:
        return 0.0
    n = (level + 1) // 2
    sign = 1 if level % 2 == 1 else -1
    return sign * n * unit


def _combined_items(task_points, pub_points, pat_points, min_gap_days):
    """과제(구간)·논문·특허(시점)를 하나의 겹침-회피 계산 대상으로 묶는다.
    점(논문/특허)은 min_gap_days 폭의 짧은 구간으로 취급해 과제와 동일한
    구간-겹침 알고리즘을 그대로 적용할 수 있게 한다."""
    items = []
    for seg in task_points:
        items.append({'start': seg['start'], 'end': seg['end'], 'ref': seg})
    half = pd.Timedelta(days=min_gap_days / 2)
    for p in pub_points:
        items.append({'start': p['date'] - half, 'end': p['date'] + half, 'ref': p})
    for p in pat_points:
        items.append({'start': p['date'] - half, 'end': p['date'] + half, 'ref': p})
    items.sort(key=lambda it: it['start'])
    return items


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


def _add_task_traces(fig, task_points, task_colors, exclude_dates):
    if not task_points:
        return

    # 범례는 과제별 색과 무관하게 중립색 하나로 대표 표시 (실제 색 구분은 차트에서 호버로 확인)
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode='markers', name='과제', legendgroup='과제',
        marker=dict(symbol='circle', size=9, color=_LEGEND_NEUTRAL),
        showlegend=True, hoverinfo='skip',
    ))

    for seg in task_points:
        y = seg['y']
        color = task_colors[seg['task_name']]
        hover = (f"{_truncate(seg['task_name'])}<br>"
                 f"시작일: {seg['start_label']}<br>종료일: {seg['end_label']}")

        fig.add_trace(go.Scatter(
            x=[seg['start'], seg['end']], y=[y, y],
            mode='lines+markers', name='과제', legendgroup='과제', showlegend=False,
            marker=dict(symbol='circle', size=9, color=color),
            line=dict(color=color, width=2.5),
            hoverinfo='skip',
        ))

        # 선분 전체에서 호버가 동작하도록 촘촘한 보조 포인트를 실제 위치(y)에 깔되,
        # 논문/특허 지점과 가까운 x는 제외해 점의 호버가 항상 우선되도록 한다.
        dense_x = _densify_dates(seg['start'], seg['end'], _DENSIFY_N)
        dense_x = _filter_near(dense_x, exclude_dates)
        fig.add_trace(go.Scatter(
            x=dense_x, y=[y] * len(dense_x),
            mode='markers', name='과제', legendgroup='과제', showlegend=False,
            marker=dict(size=6, opacity=0),
            text=[hover] * len(dense_x), hovertemplate='%{text}',
            hoverlabel=_hoverlabel(color),
        ))


def _add_pub_trace(fig, pub_points):
    if not pub_points:
        return

    color = TIMELINE_COLORS['논문']
    texts = [
        f"{p['pub_date']}<br>{_truncate(p['title'])}<br>{_truncate(p['journal'])}<br>{p['author_type']}"
        for p in pub_points
    ]
    fig.add_trace(go.Scatter(
        x=[p['date'] for p in pub_points], y=[p['y'] for p in pub_points],
        mode='markers', name='논문', legendgroup='논문',
        marker=dict(symbol='square', size=9, color=color),
        text=texts, hovertemplate='%{text}',
        hoverlabel=_hoverlabel(color),
    ))


def _add_pat_trace(fig, pat_points):
    if not pat_points:
        return

    color = TIMELINE_COLORS['특허']
    texts = [
        f"{_truncate(p['title'])}<br>{p['status']}<br>"
        f"지분율 {p['share']}%<br>{p['grade_str']}"
        for p in pat_points
    ]
    fig.add_trace(go.Scatter(
        x=[p['date'] for p in pat_points], y=[p['y'] for p in pat_points],
        mode='markers', name='특허', legendgroup='특허',
        marker=dict(symbol='triangle-up', size=10, color=color),
        text=texts, hovertemplate='%{text}',
        hoverlabel=_hoverlabel(color),
    ))


def _hr_hover_text(p):
    cl = p['order_cl']
    assignment = p.get('order_assignment', '')
    cl_str = f'{cl}({assignment})' if assignment else cl
    return f"{p['order_date']}<br>{_truncate(p['order_dep'])}<br>{cl_str}"


def _add_hr_traces(fig, hr_points):
    if not hr_points:
        return

    color = TIMELINE_COLORS['인사발령']
    hover_texts = [_hr_hover_text(p) for p in hr_points]

    # 발령명 텍스트 라벨 (상단) — 화면 표시는 order_name, 호버는 다른 항목들과 동일하게
    fig.add_trace(go.Scatter(
        x=[p['date'] for p in hr_points], y=[p['label_y'] for p in hr_points],
        mode='text', text=[_truncate(p['order_name']) for p in hr_points],
        textposition='middle center', textfont=dict(color=color, size=11),
        name='인사발령', legendgroup='인사발령', showlegend=False,
        customdata=hover_texts, hovertemplate='%{customdata}',
        hoverlabel=_hoverlabel(color),
    ))

    # 텍스트에서 타임라인으로 내려오는 화살표 축 — 텍스트 바로 아래 ~ 화살촉 바로 위까지
    # 최대한 길게 이어서 어떤 발령명과 어떤 지점이 연결되는지 직관적으로 보이게 한다.
    # 선 위 어디를 호버해도 동작하도록 텍스트도 각 점 쌍에 맞춰 반복한다.
    shaft_x, shaft_y, shaft_text = [], [], []
    for p, hover in zip(hr_points, hover_texts):
        shaft_x += [p['date'], p['date'], None]
        shaft_y += [p['label_y'] - _HR_TEXT_CLEARANCE, HR_ARROW_TIP_Y + _HR_ARROW_CLEARANCE, None]
        shaft_text += [hover, hover, None]
    fig.add_trace(go.Scatter(
        x=shaft_x, y=shaft_y, mode='lines',
        line=dict(color=color, width=1.5),
        name='인사발령', legendgroup='인사발령', showlegend=False,
        text=shaft_text, hovertemplate='%{text}',
        hoverlabel=_hoverlabel(color),
    ))

    # 화살촉 (타임라인 날짜 위치, 정밀한 히트 영역)
    fig.add_trace(go.Scatter(
        x=[p['date'] for p in hr_points], y=[HR_ARROW_TIP_Y] * len(hr_points),
        mode='markers', marker=dict(symbol='triangle-down', size=9, color=color),
        name='인사발령', legendgroup='인사발령', showlegend=True,
        text=hover_texts, hovertemplate='%{text}',
        hoverlabel=_hoverlabel(color),
    ))


def _densify_dates(start, end, n=12):
    if n <= 1 or start == end:
        return [start]
    span = end - start
    return [start + span * (i / (n - 1)) for i in range(n)]


def _filter_near(dense_dates, exclude_dates, epsilon_days=_NEAR_EXCLUDE_DAYS):
    """exclude_dates(논문/특허 지점) 근처의 보조 포인트를 제외해, 점과 선이 겹칠 때
    선이 아닌 점의 호버가 우선되도록 한다. 전부 제외되면 최소 1개는 남긴다."""
    if not exclude_dates:
        return dense_dates
    eps_sec = epsilon_days * 86400
    kept = [d for d in dense_dates
            if all(abs((d - e).total_seconds()) > eps_sec for e in exclude_dates)]
    return kept if kept else dense_dates[:1]


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
            'pub_date': pub_date,
            'title': str(row.get('title', '')).strip(),
            'journal': str(row.get('journal', '')).strip(),
            'author_type': str(row.get('author_type', '')).strip(),
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
        app_date = str(row.get('application_date', '')).strip()
        date = _parse_ts(app_date)
        if date is None:
            continue
        title = _cell(row, 'title', 'title_ko')
        status = _clean(row.get('status', ''))
        reg_date = _clean(row.get('registration_date', ''))
        if status == '등록' and reg_date:
            status_str = f'{status}({reg_date})'
        elif status == '출원' and app_date:
            status_str = f'{status}({app_date})'
        else:
            status_str = status
        grade = _clean(row.get('patent_grade', ''))
        grade_a = _clean(row.get('patent_grade_a_sub', ''))
        grade_a = '' if grade_a == '없음' else grade_a
        grade_str = f'{grade}({grade_a})' if grade_a else grade
        share = str(row.get('share_ratio', '')).strip()
        points.append({
            'date': date,
            'title': title,
            'status': status_str,
            'grade_str': grade_str,
            'share': share,
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
        html.H5(str(value), className=f'fw-bold {color} mb-0'),
        html.Small(label, className='text-muted'),
    ], className='text-center px-2')


def _single_card(value, label, color):
    return dbc.Card(dbc.CardBody(_stat(value, label, color), className='p-2'),
                    className='border-0 bg-light h-100')
