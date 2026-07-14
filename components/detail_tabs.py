from datetime import datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

# ── 세로(수직) 타임라인 ──────────────────────────────────────────────────────
# 스파인(독립 축)을 차트 왼쪽 끝에 붙이고, 과제 레인은 스파인에서 뻗어나와
# 오른쪽으로 순차 배치한다(겹치는 기간의 과제만 레인 분리). 논문·특허·인사발령은
# 과제 레인과 무관하게 항상 메인 스파인의 발생 시점에서 점선 화살표로 출발해,
# 모든 이벤트가 공유하는 하나의 라벨 열(label_col_x)까지 이동해 아이콘+텍스트로
# 표시된다. 라벨의 세로 위치(slot_y)는 카테고리 구분 없이 전체 이벤트를 시간순
# 으로 훑으며 최소 픽셀 간격을 강제해 절대 겹치지 않도록 배정하고, 실제 발생일과
# slot_y가 다르면 화살표가 여러 번 꺾여 이동한다.
# y축(날짜)은 기본 방향을 그대로 사용 — 값이 클수록(최신일수록) 위에 그려진다.
SPINE_X = 0.0
SPINE_LEFT_MARGIN = 0.35   # 스파인과 차트 왼쪽 끝 사이 여백(축 눈금 라벨 공간)
TASK_LANE_UNIT = 0.17      # 과제 레인 간 x 간격(스파인 기준 오른쪽으로만 순차 배치, 짧게 축소)
BRANCH_ELBOW = 0.28        # 과제/스파인 → 첫 번째로 꺾이는 지점까지의 가로 길이
BRANCH_BASE = 0.55         # 공유 라벨 열까지의 최소 여유 거리(과제 레인 오른쪽 끝 기준)
Y_STEP_FACTOR = 1.1        # 픽셀 기준 최소 라벨 간격에 곱하는 여유 배수
_ROW_PX_GAP = 20           # 라벨 행 사이에 확보할 최소 픽셀 간격(전체 이벤트 공통)
_HOVER_SPAN_PER_CHAR = 0.052  # 라벨 글자 수 → 호버 히트 영역 가로 폭 근사 환산
_HOVER_SPAN_MIN = 0.5
_HOVER_SPAN_MAX = 2.6
_HOVER_DISTANCE_PX = 5       # 전역 hoverdistance(모든 이벤트 공통, Plotly 레이아웃 단위라 개별 조정 불가)
_HOVER_MIN_OFFSET_PX = 8     # 호버 히트 지점을 텍스트보다 위로 띄우는 최소 오프셋(공간이 좁을 때)
_HOVER_MAX_OFFSET_PX = 32    # 2줄로 꺾인 호버창이 자기 행을 완전히 벗어나기에 충분한 목표 오프셋
                              # (공간이 있을 때만 적용 — 좁으면 _HOVER_MIN_OFFSET_PX 근처로 축소)
_HOVER_MIN_MARKER_SIZE = 6   # 호버 히트 마커 최소 크기(지름, px)
_TASK_LABEL_GAP_PX = 26     # 과제명 라벨이 위치하는 구간에서 선을 끊어 비워둘 픽셀 높이
_ELBOW_STEP = 0.06          # 같은 종류 이벤트끼리 꺾임 지점(elbow) x를 조금씩 어긋나게 해 세로 구간이 겹치지 않게 함
_ELBOW_CYCLE = 3            # 위 어긋남을 순환시키는 주기(라벨이 많아도 폭이 무한정 커지지 않도록)

# 애플 스타일: 절제된 무채색 베이스 위에 채도를 낮춘 데이터 색상만 포인트로 사용.
TIMELINE_COLORS = {
    '인사발령': '#0071e3',
    '논문':     '#c98a2e',
    '특허':     '#3f8f57',
}
# 과제는 항목마다 다른 색을 쓰되, 위 3개 카테고리 색은 피한다. 모두 채도를 낮춘 톤.
TASK_COLOR_PALETTE = ['#4a7fc1', '#7b6fb0', '#c46b6b', '#c07d97', '#c08a52']
_SPINE_COLOR = '#c7c7cc'
_LEGEND_NEUTRAL = '#6e6e73'

_GRIDLINE = '#e8e8ed'
_CHART_FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Display','Noto Sans KR',sans-serif"
_TOOLTIP_BG = '#1d1d1f'
_TOOLTIP_FG = '#f5f5f7'
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

    # 과제 레인 배정 — 실제로 기간이 겹치는 과제만 스파인 오른쪽으로 순차 분리 배치.
    task_items = sorted(task_points, key=lambda t: t['start'])
    lane_items = [{'start': t['start'], 'end': t['end']} for t in task_items]
    levels = _assign_levels(lane_items)
    for t, lvl in zip(task_items, levels):
        t['x'] = SPINE_X + TASK_LANE_UNIT * (lvl + 1)

    task_colors = _task_colors(task_points)

    # 논문/특허/인사발령 모두 항상 메인 스파인에서 출발한다(과제 레인에 배정하지 않음).
    events = []
    for p in pub_points:
        events.append({
            'date': p['date'], 'kind': '논문', 'label': _pub_label(p),
            'hover': f"<b>{_wrap_title(p['title'])}</b>",
        })
    for p in pat_points:
        events.append({
            'date': p['date'], 'kind': '특허', 'label': _patent_label(p),
            'hover': f"<b>{_wrap_title(p['title'])}</b>",
        })
    for p in hr_points:
        events.append({
            'date': p['date'], 'kind': '인사발령', 'label': _hr_label(p), 'hover': None,
        })

    # 논문·특허·인사발령은 모두 하나의 공유 라벨 열(label_col_x)에 아이콘+텍스트로
    # 표시한다. 실제 발생 시점(과제 레인 또는 스파인)에서 뻗어나가는 지점은 그대로
    # 두되, 라벨이 배치되는 세로 위치(slot_y)는 전체 이벤트를 시간순으로 훑으며
    # 최소 간격(row_gap)을 강제해 카테고리·과제 구분 없이 절대 겹치지 않게 한다.
    # 실제 발생일과 slot_y가 다르면 화살표가 여러 번 꺾여 이동한다.
    plot_px = max(_chart_height(y_range) - 50, 100)
    px_per_day = plot_px / total_days
    row_gap = pd.Timedelta(days=(_ROW_PX_GAP / px_per_day) * Y_STEP_FACTOR)

    prev_slot = None
    for e in sorted(events, key=lambda e: e['date'], reverse=True):
        slot = e['date']
        if prev_slot is not None and slot > prev_slot - row_gap:
            slot = prev_slot - row_gap
        e['slot_y'] = slot
        prev_slot = slot

    max_lane = max((t['x'] for t in task_items), default=0.0)
    label_col_x = max_lane + BRANCH_BASE

    fig = go.Figure()
    _add_spine(fig, y_range)
    _add_task_lanes(fig, task_items, task_colors, px_per_day)
    _add_event_traces(fig, events, label_col_x, row_gap, y_range)

    max_label_span = max((_hover_span(e['label']) for e in events), default=0.0)
    max_x = label_col_x + max_label_span + 0.4
    x_range = [SPINE_X - SPINE_LEFT_MARGIN, max_x]

    fig.update_layout(
        font=dict(family=_CHART_FONT, size=12, color='#52525b'),
        xaxis=dict(range=x_range, visible=False, fixedrange=True),
        yaxis=dict(range=y_range, type='date', gridcolor=_GRIDLINE, showline=False,
                   tickfont=dict(size=11, color='#a1a1aa'), automargin=True),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0,
                    groupclick='togglegroup', font=dict(size=11.5),
                    itemsizing='constant'),
        hoverlabel=dict(namelength=-1),
        hovermode='closest',
        hoverdistance=_HOVER_DISTANCE_PX,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=_chart_height(y_range),
    )

    graph = dcc.Graph(figure=fig, config={'displayModeBar': False})
    summary = _summary_cards(len(task_points), pub, pat_dedup)
    scroll_wrap = html.Div(graph, style={'maxHeight': '520px', 'overflowY': 'auto', 'overflowX': 'hidden'})
    return html.Div([summary, scroll_wrap]) if summary is not None else html.Div([scroll_wrap])


def _chart_height(y_range):
    """세로 타임라인 실제 픽셀 높이 — 기간이 길수록 커지고, 카드는 고정 높이로 스크롤."""
    years = max((y_range[1] - y_range[0]).days / 365, 1)
    return int(min(2200, max(460, 165 * years)))


def publications_tab(pub_df, rid):
    """연구원의 논문 실적 목록 (data/processed/publications.csv)."""
    if pub_df.empty:
        return html.Div('논문 데이터 없음', className='text-muted p-3')

    sort_col = 'pub_date' if 'pub_date' in pub_df.columns else 'pub_year'
    pub = pub_df[pub_df['researcher_id'] == rid].copy()
    if pub.empty:
        return html.Div('논문 실적 없음', className='text-muted p-3')
    pub = pub.sort_values(sort_col, ascending=False)

    total = len(pub)
    corr_mask = pub['is_corresponding'].astype(str).str.lower().isin(['true', '1', 'y', 'yes'])
    corr = int(corr_mask.sum())

    summary = dbc.Row([
        dbc.Col(_single_card(total, '총 논문 수', 'text-primary'), md=2),
        dbc.Col(_single_card(corr, '교신저자', 'text-warning'), md=2),
    ], className='mb-3 g-2')

    rows = []
    for _, row in pub.iterrows():
        is_corr = str(row.get('is_corresponding', '')).lower() in ('true', '1', 'y', 'yes')
        contrib = str(row.get('contribution', '')).strip()
        rank_total = ''
        r = str(row.get('author_rank', '')).strip()
        t = str(row.get('total_authors', '')).strip()
        if r and t and r not in ('nan', '') and t not in ('nan', ''):
            rank_total = f'{r}/{t}'

        badges = []
        pub_type = str(row.get('pub_type', '')).strip()
        if pub_type and pub_type not in ('nan', ''):
            badges.append(dbc.Badge(pub_type, color='info', className='me-1'))
        author_type = str(row.get('author_type', '')).strip()
        if author_type and author_type not in ('nan', ''):
            badges.append(dbc.Badge(author_type, color='secondary', className='me-1'))
        if is_corr:
            badges.append(dbc.Badge('교신', color='warning', text_color='dark'))

        rows.append(html.Tr([
            html.Td(str(row.get('pub_year', '') or row.get('pub_date', ''))[:7],
                    className='small text-muted', style={'wordBreak': 'break-word'}),
            html.Td(row.get('title', ''),
                    style={'wordBreak': 'break-word', 'fontSize': '0.82rem'}),
            html.Td(row.get('journal', ''), className='small text-muted',
                    style={'wordBreak': 'break-word'}),
            html.Td(rank_total, className='small text-center', style={'wordBreak': 'break-word'}),
            html.Td(f'{contrib}%' if contrib and contrib not in ('nan', '') else '',
                    className='small text-center'),
            html.Td(html.Div(badges) if badges else '', style={'wordBreak': 'break-word'}),
        ]))

    return html.Div([summary, dbc.Table([
        html.Thead(html.Tr([
            html.Th('발표일', style={'width': '9%'}),
            html.Th('제목', style={'width': '31%'}),
            html.Th('게재처', style={'width': '20%'}),
            html.Th('순위/총수', className='text-center', style={'width': '10%'}),
            html.Th('기여도', className='text-center', style={'width': '10%'}),
            html.Th('구분', style={'width': '20%'}),
        ]), className='table-light'),
        html.Tbody(rows),
    ], bordered=False, hover=True, size='sm',
       style={'tableLayout': 'fixed', 'width': '100%'})])


def patents_tab(pat_df, rid):
    """연구원의 특허 실적 목록 (data/processed/patents.csv)."""
    if pat_df.empty:
        return html.Div('특허 데이터 없음', className='text-muted p-3')
    pat = pat_df[pat_df['researcher_id'] == rid].copy()
    if pat.empty:
        return html.Div('특허 실적 없음', className='text-muted p-3')

    pat_dedup = _dedupe_patents(pat)
    total_cnt = len(pat_dedup)
    reg_cnt = int(pat_dedup['status'].apply(_is_registered).sum()) if 'status' in pat_dedup.columns else 0
    lead_cnt = _count_true(pat_dedup, 'is_lead_inventor')
    strat_cnt = int((pat_dedup.get('patent_grade_a_sub', pd.Series(dtype=str)).astype(str).str.strip() == '전략출원').sum())
    us_reg_cnt = _count_us_registered(pat_dedup)
    share_sum = _share_sum(pat_dedup)

    summary = dbc.Row([
        dbc.Col(_dual_card(total_cnt, '전체 발명', 'text-dark',
                           lead_cnt, '대표 발명', 'text-secondary'), md=3),
        dbc.Col(_dual_card(total_cnt, '출원', 'text-primary',
                           reg_cnt, '등록', 'text-success'), md=3),
        dbc.Col(_single_card(strat_cnt, '전략 출원', 'text-warning'), md=2),
        dbc.Col(_single_card(us_reg_cnt, '미국 등록', 'text-info'), md=2),
        dbc.Col(_single_card(share_sum, '지분율 합계', 'text-danger'), md=2),
    ], className='mb-3 g-2')

    sort_col = 'application_date' if 'application_date' in pat_dedup.columns else pat_dedup.columns[0]
    rows = []
    for _, row in pat_dedup.sort_values(sort_col, ascending=False).iterrows():
        status_val = str(row.get('status', ''))
        lead = str(row.get('is_lead_inventor', ''))
        grade = str(row.get('patent_grade', ''))
        grade_a = str(row.get('patent_grade_a_sub', ''))
        grade_str = grade + (f'({grade_a})' if grade_a and grade_a not in ('', 'nan') else '')
        share_val = row.get('share_ratio', '')
        share_str = f'{share_val}%' if str(share_val).replace('.', '').isdigit() else '-'
        rows.append(html.Tr([
            html.Td(_cell(row, 'application_date')[:7], style={'wordBreak': 'break-word'}),
            html.Td(_cell(row, 'title', 'title_ko'), style={'wordBreak': 'break-word'}),
            html.Td(dbc.Badge('등록', color='success') if _is_registered(status_val)
                    else dbc.Badge(status_val or '출원', color='primary')),
            html.Td(_cell(row, 'application_id', 'application_no'), style={'wordBreak': 'break-word'}),
            html.Td(dbc.Badge('대표', color='warning', text_color='dark')
                    if lead in ('Y', 'y', '1', 'True', 'true') else ''),
            html.Td(share_str),
            html.Td(grade_str or '-', style={'wordBreak': 'break-word'}),
            html.Td(_cell(row, 'country'), style={'wordBreak': 'break-word'}),
        ]))

    return html.Div([summary, dbc.Table([
        html.Thead(html.Tr([
            html.Th('출원일', style={'width': '9%'}),
            html.Th('발명 명칭', style={'width': '24%'}),
            html.Th('상태', style={'width': '9%'}),
            html.Th('접수ID/출원번호', style={'width': '14%'}),
            html.Th('대표발명자', style={'width': '9%'}),
            html.Th('지분율', style={'width': '8%'}),
            html.Th('등급', style={'width': '12%'}),
            html.Th('출원 국가', style={'width': '15%'}),
        ])),
        html.Tbody(rows),
    ], bordered=False, hover=True, size='sm',
       style={'tableLayout': 'fixed', 'width': '100%'})])


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


def _summary_cards(task_count, pub_df, pat_dedup_df):
    cards = []
    if task_count:
        cards.append(dbc.Col(_single_card(task_count, '과제 수', 'text-danger'), md=2))
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


def _wrap_title(text, max_chars=42):
    """호버에 전체 제목을 다 보여주되, 너무 길면 차트 폭을 벗어나지 않도록
    중간 지점에서 가장 가까운 공백을 찾아 <br>로 꺾어 최대 2줄로 표시한다."""
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    mid = len(text) // 2
    left = text.rfind(' ', 0, mid)
    right = text.find(' ', mid)
    if left == -1 and right == -1:
        split_at = mid
    elif left == -1:
        split_at = right
    elif right == -1:
        split_at = left
    else:
        split_at = left if (mid - left) <= (right - mid) else right
    return text[:split_at].rstrip() + '<br>' + text[split_at:].lstrip()


def _hoverlabel(color):
    """카테고리 색은 테두리로만 표시하는 다크 카드형 툴팁 (모던 대시보드 스타일)."""
    return dict(
        bgcolor=_TOOLTIP_BG,
        bordercolor=color,
        font=dict(color=_TOOLTIP_FG, size=12, family=_CHART_FONT),
        align='left',
    )


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


def _add_spine(fig, y_range):
    fig.add_trace(go.Scatter(
        x=[SPINE_X, SPINE_X], y=[y_range[0], y_range[1]], mode='lines',
        line=dict(color=_SPINE_COLOR, width=2, dash='dot'),
        hoverinfo='skip', showlegend=False,
    ))


def _add_task_lanes(fig, task_items, task_colors, px_per_day):
    if not task_items:
        return

    # 범례는 과제별 색과 무관하게 중립색 하나로 대표 표시 (실제 색 구분은 차트에서 호버로 확인)
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode='markers', name='과제', legendgroup='과제',
        marker=dict(symbol='circle', size=9, color=_LEGEND_NEUTRAL,
                    line=dict(color=_MARKER_RING, width=1.5)),
        showlegend=True, hoverinfo='skip',
    ))

    half_gap = pd.Timedelta(days=(_TASK_LABEL_GAP_PX / px_per_day) / 2)
    mids = [t['start'] + (t['end'] - t['start']) / 2 for t in task_items]

    # 과제 기간이 겹치면(=스파인에 더 가까운 레인의 과제가 이 과제의 시작일에 이미
    # 진행 중이었으면) 메인 스파인이 아니라 그 먼저 시작된 과제의 선에서 갈라져
    # 나오도록 연결한다. 겹치는 과제가 없으면 기존처럼 메인 스파인에서 시작.
    origins = {}
    for t in task_items:
        parent = None
        for other in task_items:
            if other is t or other['x'] >= t['x']:
                continue
            if other['start'] < t['start'] <= other['end']:
                if parent is None or other['start'] > parent['start']:
                    parent = other
        origins[id(t)] = parent['x'] if parent else SPINE_X

    for t in task_items:
        color = task_colors[t['task_name']]
        x = t['x']
        origin_x = origins[id(t)]
        hover = f"<b>{_truncate(t['task_name'])}</b><br>{t['start_label']} → {t['end_label']}"
        mid_y = t['start'] + (t['end'] - t['start']) / 2

        # 스파인(또는 겹치는 과제의 선)→레인 연결선과 과제 자체 선을 하나의
        # 연속된 선(점 없이)으로 잇는다: (기점, 시작일) → (레인, 시작일) →
        # (레인, 종료일). 레인 간격이 좁아 옆 레인 과제의 라벨이 이 선 위를
        # 지나갈 수도 있으므로, 자기 자신뿐 아니라 "이 선의 날짜 범위 안에
        # 들어오는 모든 과제"의 라벨 위치에서 선을 끊는다.
        gaps = []
        for m in mids:
            if t['start'] <= m <= t['end']:
                gaps.append((max(t['start'], m - half_gap), min(t['end'], m + half_gap)))
        gaps.sort()

        line_x, line_y = [], []
        cursor = t['start']
        for gs, ge in gaps:
            if gs > cursor:
                line_x += [x, x, None]
                line_y += [cursor, gs, None]
            cursor = max(cursor, ge)
        if cursor < t['end']:
            line_x += [x, x]
            line_y += [cursor, t['end']]
        elif line_x and line_x[-1] is None:
            line_x, line_y = line_x[:-1], line_y[:-1]

        fig.add_trace(go.Scatter(
            x=[origin_x, x, None] + line_x, y=[t['start'], t['start'], None] + line_y,
            mode='lines',
            line=dict(color=color, width=3, shape='linear'),
            name='과제', legendgroup='과제', showlegend=False, hoverinfo='skip',
        ))

        # 레인 전체(스파인 연결 구간 포함)에서 어디를 호버해도 과제 정보가 뜨도록
        # 촘촘한 보조 포인트 배치
        dense_y = _densify_dates(t['start'], t['end'], _DENSIFY_N)
        fig.add_trace(go.Scatter(
            x=[x] * len(dense_y), y=dense_y,
            mode='markers', name='과제', legendgroup='과제', showlegend=False,
            marker=dict(size=6, opacity=0),
            text=[hover] * len(dense_y), hovertemplate='%{text}<extra></extra>',
            hoverlabel=_hoverlabel(color),
        ))

        # 과제명 라벨 — 과제 기간의 세로 중앙에 동일 색 테두리 프레임(칩)으로 표시.
        # 위에서 그 구간의 선을 끊어뒀기 때문에 배경색과 무관하게 겹칠 선이 없다.
        # xanchor='left'로 고정해 라벨 박스가 항상 레인 x 위치 오른쪽으로만
        # 확장되도록 해, 레인 간격이 좁아도 박스 왼쪽 끝이 메인 스파인보다
        # 왼쪽으로 튀어나오지 않게 한다.
        fig.add_annotation(
            x=x, y=mid_y, xref='x', yref='y', xanchor='left',
            text=_truncate(t['task_name'], 16),
            showarrow=False,
            font=dict(size=10.5, color=color, family=_CHART_FONT),
            bgcolor='#ffffff',
            bordercolor=color, borderwidth=1.3, borderpad=3,
        )


def _hover_span(label):
    """라벨 글자 수로 호버 히트 영역의 대략적인 가로 폭을 추정(데이터 좌표 단위)."""
    return max(_HOVER_SPAN_MIN, min(_HOVER_SPAN_MAX, len(label) * _HOVER_SPAN_PER_CHAR))


def _add_event_traces(fig, events, label_col_x, row_gap, y_range):
    if not events:
        return

    # 호버 히트 지점은 라벨 텍스트보다 살짝 위에 두되(텍스트 위에 마우스를 올려도
    # 히트 반경 안에 들어오게), 실제 뜨는 호버창은 그 텍스트 행과 겹치지 않게
    # 한다(위/아래 다른 행과는 겹쳐도 무방). 다만 바로 위 행까지의 실제 여유
    # 공간을 넘어서 오프셋을 주면 엉뚱한 위쪽 이벤트의 호버가 대신 뜨는 오작동이
    # 생기므로, 이벤트마다 "바로 위 행까지 남는 여유"를 계산해 그 안에서만
    # (여유가 넉넉하면 완전히 벗어날 만큼, 좁으면 트리거만 되는 최소한만) 띄운다.
    # Plotly의 hoverdistance는 전역 설정이라 이벤트마다 다르게 줄 수 없으므로,
    # 대신 히트 마커의 크기(반지름)를 이벤트마다 오프셋에 맞춰 늘려 "히트 반경 +
    # 전역 hoverdistance"가 항상 그 이벤트의 오프셋 이상이 되도록 맞춘다. 그러면
    # 오프셋이 아무리 커도(여유 공간이 넉넉해도) 텍스트 위에서 항상 트리거된다.
    day_per_px = row_gap / (_ROW_PX_GAP * Y_STEP_FACTOR)
    by_slot = sorted(events, key=lambda e: e['slot_y'])
    hover_offsets = {}
    hover_marker_px = {}
    for i, e in enumerate(by_slot):
        if i + 1 < len(by_slot):
            room_px = (by_slot[i + 1]['slot_y'] - e['slot_y']) / day_per_px
        else:
            room_px = (y_range[1] - e['slot_y']) / day_per_px
        offset_px = max(_HOVER_MIN_OFFSET_PX, min(_HOVER_MAX_OFFSET_PX, room_px / 2 - 6))
        radius_px = max(_HOVER_MIN_MARKER_SIZE / 2, offset_px - _HOVER_DISTANCE_PX + 2)
        hover_offsets[id(e)] = day_per_px * offset_px
        hover_marker_px[id(e)] = radius_px * 2

    hover_y_max = y_range[1] - pd.Timedelta(days=2)

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
        tip_x, tip_y = [], []
        text_x, text_y, text_str = [], [], []
        hover_x, hover_y, hover_txt, hover_size = [], [], [], []

        for idx, e in enumerate(items):
            origin_x = SPINE_X
            # 같은 종류의 이벤트가 시기적으로 가까우면 꺾임 지점(elbow)의 세로
            # 구간이 서로 같은 x에 겹쳐 보일 수 있어, 항목마다 조금씩 어긋나게 한다.
            elbow_x = origin_x + BRANCH_ELBOW + (idx % _ELBOW_CYCLE) * _ELBOW_STEP
            slot_y = e['slot_y']

            # 실제 발생일(origin) → 꺾이는 지점까지는 실제 날짜 그대로, 이후
            # slot_y(전체 이벤트 기준으로 겹치지 않게 배정된 위치)로 꺾어 올라가거나
            # 내려간 뒤, 공유 라벨 열(label_col_x)까지 수평으로 한 번 더 꺾여 도달한다.
            shaft_x += [origin_x, elbow_x, elbow_x, label_col_x, None]
            shaft_y += [e['date'], e['date'], slot_y, slot_y, None]

            tip_x.append(label_col_x)
            tip_y.append(slot_y)
            text_x.append(label_col_x)
            text_y.append(slot_y)
            text_str.append(f'{icon}  {e["label"]}')
            if e['hover']:
                span = _hover_span(e['label'])
                # 라벨 텍스트 어디에 마우스를 올려도 빈틈없이 호버가 트리거되도록,
                # 히트 포인트를 라벨 길이에 비례해 촘촘히(간격 ≈ 0.05 데이터 단위) 배치.
                n_hit = max(6, int(span / 0.03) + 1)
                hx = _densify_dates(label_col_x, label_col_x + span, n_hit)
                hover_y_pos = min(slot_y + hover_offsets[id(e)], hover_y_max)
                hover_x.extend(hx)
                hover_y.extend([hover_y_pos] * len(hx))
                hover_txt.extend([e['hover']] * len(hx))
                hover_size.extend([hover_marker_px[id(e)]] * len(hx))

        # 논문/특허/인사발령 모두 메인 스파인에서 출발함을 시각적으로 드러내도록
        # 화살표 끝까지 전체를 점선으로 표시한다.
        fig.add_trace(go.Scatter(
            x=shaft_x, y=shaft_y, mode='lines',
            line=dict(color=color, width=1.5, shape='linear', dash='dot'),
            name=kind, legendgroup=kind, showlegend=False, hoverinfo='skip',
        ))
        fig.add_trace(go.Scatter(
            x=tip_x, y=tip_y, mode='markers',
            marker=dict(symbol='triangle-right', size=9, color=color,
                        line=dict(color=_MARKER_RING, width=1.2)),
            name=kind, legendgroup=kind, showlegend=False, hoverinfo='skip',
        ))
        fig.add_trace(go.Scatter(
            x=text_x, y=text_y, mode='text', text=text_str, textposition='middle right',
            textfont=dict(size=11.5, color=color),
            name=kind, legendgroup=kind, showlegend=False, hoverinfo='skip',
            cliponaxis=False,
        ))
        if hover_x:
            # 화살표 끝뿐 아니라 라벨 텍스트 영역 전체에서 호버가 되도록 촘촘히 배치.
            # hovertemplate 끝에 <extra></extra>를 붙여 Plotly가 자동으로 옆에
            # 추가하는 트레이스 이름(예: '특허') 박스가 나오지 않도록 한다.
            fig.add_trace(go.Scatter(
                x=hover_x, y=hover_y, mode='markers',
                marker=dict(size=hover_size, opacity=0),
                text=hover_txt, hovertemplate='%{text}<extra></extra>',
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


def _has_input_rate(val) -> bool:
    """투입률이 0이거나 비어있으면 False (해당 과제는 타임라인에서 제외)."""
    s = str(val).strip() if val is not None else ''
    if not s or s.lower() in ('nan', 'none', 'nat'):
        return False
    try:
        return float(s) > 0
    except (ValueError, TypeError):
        return False


def _task_points(task_df):
    if task_df.empty:
        return []
    today = pd.Timestamp(datetime.now().date())
    points = []
    for _, row in task_df.iterrows():
        if not _has_input_rate(row.get('input_rate')):
            continue
        start = _parse_ts(row.get('start_date'))
        if start is None:
            continue
        end_raw = row.get('end_date')
        end = _parse_ts(end_raw)
        end_label = end.strftime('%Y-%m-%d') if end is not None else '진행중'
        if end is None or end < start:
            end = today
        if (end - start).days <= 30:
            continue
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


def _count_true(df, col):
    if col not in df.columns:
        return 0
    return int(df[col].astype(str).isin(['Y', 'y', '1', 'True', 'true']).sum())


def _count_us_registered(df):
    if 'country' not in df.columns or 'status' not in df.columns:
        return 0
    us_mask = df['country'].astype(str).str.contains('미국|USA|US', case=False, na=False)
    return int((us_mask & df['status'].apply(_is_registered)).sum())


def _share_sum(df):
    if 'share_ratio' not in df.columns:
        return '-'
    shares = pd.to_numeric(df['share_ratio'], errors='coerce').dropna()
    return f'{round(shares.sum(), 1)}%' if not shares.empty else '-'


def _stat(value, label, color):
    return html.Div([
        html.H5(str(value), className=f'fw-bold stat-value {color} mb-0'),
        html.Small(label, className='text-muted'),
    ], className='text-center px-2')


def _dual_card(left_value, left_label, left_color, right_value, right_label, right_color):
    return dbc.Card(dbc.CardBody(
        dbc.Row([
            dbc.Col(_stat(left_value, left_label, left_color), width=6, className='border-end'),
            dbc.Col(_stat(right_value, right_label, right_color), width=6),
        ], className='g-0 align-items-center'),
        className='p-2',
    ), className='profile-card h-100', style={'backgroundColor': '#fafafa'})


def _single_card(value, label, color):
    return dbc.Card(dbc.CardBody(_stat(value, label, color), className='p-2'),
                    className='profile-card h-100', style={'backgroundColor': '#fafafa'})
