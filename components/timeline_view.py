"""
연구원 프로필 — 타임라인 (HTML/CSS 카드 오버레이).

기존에는 Plotly 차트 하나로 전체(스파인·과제 레인·이벤트 라벨·호버)를 그렸으나,
과제 카드를 "쌓아서 클릭하면 맨 위로" 오는 인터랙션을 자연스럽게 구현하기 위해
날짜→픽셀 매핑만 Python에서 계산하고, 실제 스파인·카드·필은 모두 일반 Dash HTML
컴포넌트로 절대 위치시킨다(Plotly 미사용). 클릭 시 순서 변경은 클라이언트사이드
콜백(서버 왕복 없음)으로 처리한다.

구조:
  ┌ 헤더 필(과제/논문/특허/인사발령 + 개수) ─────────────────────┐
  ├ Main spine(과제)              │ Support spine(논문·특허·인사발령) ┤
  │  점선 스파인 + 연도 라벨      │  점선 스파인                      │
  │  과제 박스 카드                │  타원(pill) 카드                  │
  │  (겹치는 기간의 과제는 쌓임,   │  (호버 시 논문/특허 title 표시)   │
  │   클릭하면 맨 위로)            │                                    │
  └────────────────────────────────┴────────────────────────────────┘
"""

from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import ALL, MATCH, Input, Output, State, dcc, html

from components.timeline_data import (
    dedupe_patents,
    hr_points,
    pat_points,
    pub_points,
    task_points,
    truncate,
    yymm,
)

# ── 레이아웃 상수(px) ─────────────────────────────────────────────────────
_TOP_PAD = 24
_SPINE_X = 34            # 스파인이 컬럼 왼쪽 끝에서 떨어진 거리(연도 라벨 공간)
_TASK_CARD_X = _SPINE_X + 26
_EVENT_PILL_X = _SPINE_X + 26
_STACK_OFFSET_PX = 16    # 겹치는 과제 카드가 쌓일 때 한 겹당 우측으로 밀리는 거리
_TASK_ROW_GAP_PX = 40    # 과제 카드 사이 최소 세로 간격
_EVENT_ROW_GAP_PX = 30   # 이벤트 필 사이 최소 세로 간격
_TASK_CARD_WIDTH = 168

# ── 색상 ──────────────────────────────────────────────────────────────────
TASK_COLOR_PALETTE = ['#4a7fc1', '#7b6fb0', '#c46b6b', '#c07d97', '#c08a52']
EVENT_COLORS = {'논문': '#c98a2e', '특허': '#3f8f57', '인사발령': '#0071e3'}
_SPINE_COLOR = '#c7c7cc'
_GRIDLINE = '#e8e8ed'
_LEGEND_NEUTRAL = '#6e6e73'
_ICONS = {'논문': '📄', '특허': '💡', '인사발령': '🧭'}


def timeline_view(task_df, hr_df, pub_df, pat_df, rid):
    task = task_df[task_df['researcher_id'] == rid].copy() if not task_df.empty else pd.DataFrame()
    hr = hr_df[hr_df['researcher_id'] == rid].copy() if not hr_df.empty else pd.DataFrame()
    pub = pub_df[pub_df['researcher_id'] == rid].copy() if not pub_df.empty else pd.DataFrame()
    pat = pat_df[pat_df['researcher_id'] == rid].copy() if not pat_df.empty else pd.DataFrame()
    pat_dedup = dedupe_patents(pat) if not pat.empty else pat

    if task.empty and hr.empty and pub.empty and pat.empty:
        return html.Div('타임라인 데이터 없음', className='text-muted p-3')

    tasks = task_points(task)
    hrs = hr_points(hr)
    pubs = pub_points(pub)
    pats = pat_points(pat_dedup)

    if not tasks and not hrs and not pubs and not pats:
        return html.Div('타임라인 데이터 없음', className='text-muted p-3')

    today = pd.Timestamp(datetime.now().date())
    all_dates = (
        [d for t in tasks for d in (t['start'], t['end'])]
        + [p['date'] for p in hrs] + [p['date'] for p in pubs] + [p['date'] for p in pats]
    )
    min_date = min(all_dates) if all_dates else today
    max_date = max(all_dates + [today])
    pad = max(pd.Timedelta(days=20), (max_date - min_date) * 0.04)
    y_range = [min_date - pad, max_date + pad]
    total_height = _chart_height(y_range)

    header = _header_pills(len(tasks), len(pubs), len(pats))
    main_col, stores = _build_main_spine(tasks, rid, y_range, total_height)
    support_col = _build_support_spine(pubs, pats, hrs, y_range, total_height)

    body = dbc.Row([
        dbc.Col(main_col, md=7),
        dbc.Col(support_col, md=5),
    ], className='g-2')

    scroll_wrap = html.Div(body, style={'maxHeight': '520px', 'overflowY': 'auto', 'overflowX': 'hidden'})
    return html.Div([header, scroll_wrap, *stores])


def _chart_height(y_range):
    """세로 타임라인 실제 픽셀 높이 — 기간이 길수록 커지고, 카드는 고정 높이로 스크롤."""
    years = max((y_range[1] - y_range[0]).days / 365, 1)
    return int(min(2200, max(460, 165 * years)))


def _date_to_y(d, y_range, total_height):
    total_days = max((y_range[1] - y_range[0]).days, 1)
    usable = max(total_height - _TOP_PAD * 2, 10)
    px_per_day = usable / total_days
    return _TOP_PAD + (y_range[1] - d).days * px_per_day


def _assign_slots(dates, y_range, total_height, min_gap_px):
    """최신 날짜부터 훑으며 최소 픽셀 간격을 강제한 y(px) 목록을 입력 순서 그대로 반환."""
    order = sorted(range(len(dates)), key=lambda i: dates[i], reverse=True)
    y_px = [0.0] * len(dates)
    prev_y = None
    for i in order:
        y = _date_to_y(dates[i], y_range, total_height)
        if prev_y is not None and y < prev_y + min_gap_px:
            y = prev_y + min_gap_px
        y_px[i] = y
        prev_y = y
    return y_px


def _group_overlapping_tasks(tasks):
    """기간이 겹치는(직접·전이적으로) 과제끼리 하나의 그룹으로 묶는다.
    반환값은 그룹 목록, 각 그룹은 tasks 리스트에 대한 인덱스 목록."""
    order = sorted(range(len(tasks)), key=lambda i: tasks[i]['start'])
    groups = []
    current, current_end = [], None
    for i in order:
        t = tasks[i]
        if current and t['start'] <= current_end:
            current.append(i)
            current_end = max(current_end, t['end'])
        else:
            if current:
                groups.append(current)
            current, current_end = [i], t['end']
    if current:
        groups.append(current)
    return groups


def _assign_task_colors(tasks):
    names = list(dict.fromkeys(t['task_name'] for t in tasks))
    return {name: TASK_COLOR_PALETTE[i % len(TASK_COLOR_PALETTE)] for i, name in enumerate(names)}


def _header_pills(task_count, pub_count, pat_count):
    task_box = html.Div(f'과제 ({task_count})', style={
        'border': '1.5px solid #1d1d1f', 'borderRadius': '8px',
        'padding': '4px 12px', 'fontSize': '0.78rem', 'fontWeight': 600, 'color': '#1d1d1f',
    })

    def _oval(text, color):
        return html.Div(text, style={
            'border': f'1.5px solid {color}', 'borderRadius': '999px',
            'padding': '4px 14px', 'fontSize': '0.78rem', 'fontWeight': 600, 'color': color,
        })

    return html.Div([
        task_box,
        _oval(f'논문 ({pub_count})', EVENT_COLORS['논문']),
        _oval(f'특허 ({pat_count})', EVENT_COLORS['특허']),
        _oval('인사발령', EVENT_COLORS['인사발령']),
    ], className='d-flex gap-2 mb-3 flex-wrap')


def _year_gridlines(y_range, total_height):
    children = []
    for yr in range(y_range[0].year, y_range[1].year + 1):
        d = pd.Timestamp(year=yr, month=1, day=1)
        if d < y_range[0] or d > y_range[1]:
            continue
        y_px = _date_to_y(d, y_range, total_height)
        children.append(html.Div(str(yr), style={
            'position': 'absolute', 'top': f'{y_px - 7}px', 'left': '0px',
            'width': f'{_SPINE_X - 8}px', 'textAlign': 'right',
            'fontSize': '0.66rem', 'color': _LEGEND_NEUTRAL,
        }))
        children.append(html.Div(style={
            'position': 'absolute', 'top': f'{y_px}px', 'left': f'{_SPINE_X}px', 'right': '0',
            'borderTop': f'1px solid {_GRIDLINE}',
        }))
    return children


def _build_main_spine(tasks, rid, y_range, total_height):
    task_y = _assign_slots([t['start'] for t in tasks], y_range, total_height, _TASK_ROW_GAP_PX)
    groups = _group_overlapping_tasks(tasks)
    task_colors = _assign_task_colors(tasks)

    stack_meta = {}
    for gi, group in enumerate(groups):
        ordered = sorted(group, key=lambda i: tasks[i]['start'], reverse=True)
        gkey = f'{rid}-g{gi}'
        for rank, idx in enumerate(ordered):
            stack_meta[idx] = (gkey, rank)

    children = [
        html.Div(style={
            'position': 'absolute', 'top': '0', 'bottom': '0', 'left': f'{_SPINE_X}px',
            'borderLeft': f'2px dashed {_SPINE_COLOR}',
        }),
        *_year_gridlines(y_range, total_height),
    ]
    stores = []
    seen_groups = set()
    for idx, t in enumerate(tasks):
        gkey, rank = stack_meta[idx]
        if gkey not in seen_groups:
            seen_groups.add(gkey)
            group_size = sum(1 for v in stack_meta.values() if v[0] == gkey)
            stores.append(dcc.Store(id={'type': 'task-stack-order', 'gkey': gkey},
                                     data=list(range(group_size))))

        x_px = _TASK_CARD_X + rank * _STACK_OFFSET_PX
        z_index = 100 - rank
        color = task_colors[t['task_name']]
        children.append(_task_connector(task_y[idx], x_px, color))
        children.append(_task_card(t, gkey, rank, task_y[idx], x_px, z_index, color))

    main_col = html.Div(children, style={'position': 'relative', 'height': f'{total_height}px',
                                          'paddingBottom': '20px'})
    return main_col, stores


def _task_connector(y_px, x_px, color):
    return html.Div(style={
        'position': 'absolute', 'top': f'{y_px + 13}px', 'left': f'{_SPINE_X}px',
        'width': f'{max(x_px - _SPINE_X, 0)}px', 'height': '2px',
        'backgroundColor': color, 'opacity': 0.55, 'zIndex': 1,
    })


def _task_card(t, gkey, rank, y_px, x_px, z_index, color):
    start_disp = t['start'].strftime('%y.%m')
    end_disp = '진행중' if t['end_label'] == '진행중' else t['end'].strftime('%y.%m')
    name_disp = truncate(t['task_name'], 20)
    tooltip_id = f'task-tt-{gkey}-{rank}'

    return html.Div([
        html.Div(name_disp, id=tooltip_id, className='fw-semibold',
                 style={'fontSize': '0.76rem', 'color': color, 'whiteSpace': 'nowrap',
                        'overflow': 'hidden', 'textOverflow': 'ellipsis'}),
        html.Div(f'{start_disp} ~ {end_disp}', style={
            'fontSize': '0.66rem', 'color': _LEGEND_NEUTRAL, 'marginTop': '1px',
        }),
        dbc.Tooltip(t['task_name'], target=tooltip_id, placement='top'),
    ], id={'type': 'task-card', 'gkey': gkey, 'idx': rank}, n_clicks=0, style={
        'position': 'absolute', 'top': f'{y_px}px', 'left': f'{x_px}px',
        'zIndex': z_index, 'width': f'{_TASK_CARD_WIDTH}px',
        'backgroundColor': '#ffffff', 'border': f'1.3px solid {color}',
        'borderRadius': '10px', 'padding': '5px 10px', 'cursor': 'pointer',
        'boxShadow': '0 1px 4px rgba(0,0,0,0.10)',
    })


def _patent_pill_text(p):
    date_str = yymm(p['date'])
    grade, grade_a = p['grade'], p['grade_a']
    grade_str = f'{grade}({grade_a})' if grade and grade_a else grade
    parts = [date_str, grade_str]
    if p['share']:
        parts.append(f"{p['share']}%")
    if p['is_lead'] == 'Y':
        parts.append('대표자')
    return ' · '.join(x for x in parts if x)


def _pub_pill_text(p):
    date_str = yymm(p['date'])
    parts = [date_str, p['journal'], p['author_type']]
    return ' · '.join(x for x in parts if x and x not in ('nan', 'None'))


def _hr_pill_text(p):
    date_str = yymm(p['date'])
    dep = f"{p['order_name']}({p['order_dep']})" if p['order_dep'] else p['order_name']
    cl = f"{p['order_cl']}({p['order_assignment']})" if p['order_assignment'] else p['order_cl']
    return '  '.join(x for x in (date_str, dep, cl) if x)


def _build_support_spine(pubs, pats, hrs, y_range, total_height):
    events = []
    for p in pubs:
        events.append({'date': p['date'], 'kind': '논문', 'text': _pub_pill_text(p), 'title': p['title']})
    for p in pats:
        events.append({'date': p['date'], 'kind': '특허', 'text': _patent_pill_text(p), 'title': p['title']})
    for p in hrs:
        events.append({'date': p['date'], 'kind': '인사발령', 'text': _hr_pill_text(p), 'title': None})

    if not events:
        return html.Div(style={'position': 'relative', 'height': f'{total_height}px'})

    event_y = _assign_slots([e['date'] for e in events], y_range, total_height, _EVENT_ROW_GAP_PX)

    children = [html.Div(style={
        'position': 'absolute', 'top': '0', 'bottom': '0', 'left': f'{_SPINE_X}px',
        'borderLeft': f'2px dashed {_SPINE_COLOR}',
    })]
    for i, e in enumerate(events):
        color = EVENT_COLORS[e['kind']]
        children.append(_event_connector(event_y[i], color))
        children.append(_event_pill(e, i, event_y[i], color))

    return html.Div(children, style={'position': 'relative', 'height': f'{total_height}px',
                                      'paddingBottom': '20px'})


def _event_connector(y_px, color):
    return html.Div(style={
        'position': 'absolute', 'top': f'{y_px + 11}px', 'left': f'{_SPINE_X}px',
        'width': f'{_EVENT_PILL_X - _SPINE_X}px', 'height': '2px',
        'backgroundColor': color, 'opacity': 0.55, 'zIndex': 1,
    })


def _event_pill(e, i, y_px, color):
    pill_id = f'event-pill-{i}'
    pill = html.Div(f"{_ICONS[e['kind']]} {e['text']}", id=pill_id, style={
        'display': 'inline-block', 'position': 'absolute', 'top': f'{y_px}px',
        'left': f'{_EVENT_PILL_X}px', 'backgroundColor': color, 'color': '#ffffff',
        'borderRadius': '999px', 'padding': '4px 14px', 'fontSize': '0.72rem',
        'fontWeight': 500, 'whiteSpace': 'nowrap', 'boxShadow': '0 1px 3px rgba(0,0,0,0.10)',
        'zIndex': 5,
    })
    if not e['title']:
        return pill
    # 특허/논문은 호버 시 전체 title 표시. placement='top'이면 pill 위쪽에 여백을 두고
    # 뜨므로 pill 자체는 가리지 않는다.
    return html.Div([pill, dbc.Tooltip(e['title'], target=pill_id, placement='top')])


# ── 클릭한 과제 카드를 스택 맨 위로 올리는 클라이언트사이드 콜백 ───────────
# idx는 렌더링 시점의 stack_rank(=초기 left 오프셋 배수)와 같으므로, 현재 스타일의
# left 값에서 idx*OFFSET을 역산해 그룹의 기준 left를 복원한 뒤 새 순서로 재배치한다.
dash.clientside_callback(
    """
    function(n_clicks_list, current_styles, current_order) {
        const ctx = dash_clientside.callback_context;
        if (!ctx.triggered || !ctx.triggered.length) {
            return [dash_clientside.no_update, dash_clientside.no_update];
        }
        const propId = ctx.triggered[0].prop_id;
        if (!propId.endsWith('.n_clicks')) {
            return [dash_clientside.no_update, dash_clientside.no_update];
        }
        let triggeredId;
        try {
            triggeredId = JSON.parse(propId.substring(0, propId.lastIndexOf('.')));
        } catch (e) {
            return [dash_clientside.no_update, dash_clientside.no_update];
        }
        const clickedIdx = triggeredId.idx;
        const OFFSET = """ + str(_STACK_OFFSET_PX) + """;

        const outIds = ctx.outputs_list[0].map(o => o.id.idx);
        let order = (current_order && current_order.length ? current_order : outIds.slice()).slice();
        if (order.indexOf(clickedIdx) === -1) { order = outIds.slice(); }
        order = order.filter(i => i !== clickedIdx);
        order.unshift(clickedIdx);

        const newStyles = outIds.map((idx, i) => {
            const pos = order.indexOf(idx);
            const style = Object.assign({}, current_styles[i]);
            const curLeft = parseFloat(style.left);
            const baseLeft = curLeft - idx * OFFSET;
            style.left = (baseLeft + pos * OFFSET) + 'px';
            style.zIndex = 100 - pos;
            return style;
        });

        return [newStyles, order];
    }
    """,
    Output({'type': 'task-card', 'gkey': MATCH, 'idx': ALL}, 'style'),
    Output({'type': 'task-stack-order', 'gkey': MATCH}, 'data'),
    Input({'type': 'task-card', 'gkey': MATCH, 'idx': ALL}, 'n_clicks'),
    State({'type': 'task-card', 'gkey': MATCH, 'idx': ALL}, 'style'),
    State({'type': 'task-stack-order', 'gkey': MATCH}, 'data'),
)
