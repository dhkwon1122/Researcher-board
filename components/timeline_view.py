"""
연구원 프로필 — 타임라인 (HTML/CSS 카드 오버레이).

Main spine 하나로 과제와 인사발령만 표시한다. 논문·특허는 스파인에 별도 항목으로
나타나지 않고, (1) 상단 요약 pill(과제/인사발령/논문/특허)을 클릭하면 그 종류의
전체 표(기존 "과제 수행 이력/논문/특허" 탭 카드에 있던 것과 동일한 컴포넌트,
개수 포함)가 타임라인 카드 전체 폭으로 펼쳐지고(아코디언 — 한 번에 하나만),
(2) 과제 카드를 클릭하면 그 과제에 project_name/project_code로 연결된 논문·특허가
(참여기간과 무관하게) 과제 박스 자체가 확장되며 안에 나열된다. 과제에 전혀
연결되지 않은 논문·특허는 타임라인에는 나타나지 않는다(요약 pill을 눌렀을 때의
전체 표에서만 확인 가능).

구조:
  ┌ 헤더 필(과제/인사발령/논문/특허 + 개수, 클릭 시 전체 폭 표 아코디언) ──┐
  ├ Main spine(과제 + 인사발령만; 과제 클릭 시 박스 안에 연결 논문/특허 나열) ┤
  │  점선 스파인 + 연도 라벨(현재 시점까지만)                              │
  │  (겹치는 기간의 항목은 쌓임, 클릭하면 맨 위로)                         │
  └──────────────────────────────────────────────────────────────────────┘

세로 위치는 달력상 절대 시간이 아니라 "탄력적" 척도를 쓴다(_build_time_axis).
항목 사이 간격은 그 앞 항목의 실제 렌더 높이만큼만 확보해(데이터가 몰린 구간은
그만큼만 촘촘하게 = 팽창), 진짜 날짜 차이는 상한(_GAP_CAP_DAYS)을 둬 압축한다
— 데이터가 없는 구간이 아무리 길어도 고정된 픽셀 이상 차지하지 않는다. 이
방식이 과제 카드(여러 줄)와 인사발령 필(한 줄)의 실제 높이 차이도 반영하므로,
두 종류가 시각적으로 겹치는 문제도 함께 해결한다.

과제/인사발령 모두 "겹칠 때 쌓기 + 클릭 시 맨 위로" 로직을 공유한다
(_group_overlapping, _assign_stack_groups, 클라이언트사이드 콜백).
과제 클릭 시 "박스 안에 연결 논문/특허 펼치기"는 별도의 독립된 클라이언트사이드
콜백(state: tl-expand-store)으로 처리하며, 카드 쌓기 순서 변경과는 무관하다.
"""

import bisect
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import ALL, MATCH, Input, Output, State, dcc, html

from components.detail_tabs import patents_tab, publications_tab
from components.profile_sections import tasks_block
from components.timeline_data import (
    dedupe_patents,
    hr_points,
    job_points,
    linked_task_names,
    pat_points,
    pub_points,
    task_code_map,
    task_points,
    truncate,
    yymm,
)

# ── 레이아웃 상수(px) ─────────────────────────────────────────────────────
_TOP_PAD = 24
_SPINE_X = 34             # 스파인이 컬럼 왼쪽 끝에서 떨어진 거리(연도 라벨 공간)
_STACK_BASE_X = _SPINE_X + 26   # 스택(과제 카드/이벤트 필 공통) 카드의 x 위치(항상 고정)

# 세로 위치는 달력상 절대 시간이 아니라 "탄력적" 척도를 쓴다: 각 항목 사이 간격은
# 그 앞 항목의 실제 렌더 높이만큼만 확보하고(데이터가 몰린 구간은 그만큼만 촘촘하게
# 표시 = 팽창), 달력상 진짜 간격은 _GAP_CAP_DAYS로 상한을 둬 아무리 오래 비어 있는
# 기간이라도 고정된 픽셀 이상은 차지하지 않는다(압축). _build_time_axis() 참고.
_ROW_BUFFER_PX = 6        # 항목 사이 최소 여백(데이터가 아무리 몰려도 이만큼은 띄움)
_GAP_CAP_DAYS = 21        # 이보다 먼 실제 날짜 차이는 전부 동일하게(상한만큼만) 압축
_PX_PER_DAY = 1.0         # 상한 이내 날짜 차이 1일당 추가 픽셀
_HR_ROW_HEIGHT = 32       # 인사발령 필 1건의 대략적 렌더 높이(px)

# ── 색상 ──────────────────────────────────────────────────────────────────
TASK_COLOR_PALETTE = ['#4a7fc1', '#7b6fb0', '#c46b6b', '#c07d97', '#c08a52']
EVENT_COLORS = {'논문': '#c98a2e', '특허': '#3f8f57', '인사발령': '#1677ff'}
_SPINE_COLOR = '#c7c7cc'
_GRIDLINE = '#d9d9d9'
_LEGEND_NEUTRAL = '#8c8c8c'
_ICONS = {'논문': '📄', '특허': '💡', '인사발령': '🧭'}


def timeline_view(task_df, hr_df, pub_df, pat_df, job_df, tasks_info_df, rid):
    task = task_df[task_df['researcher_id'] == rid].copy() if not task_df.empty else pd.DataFrame()
    hr_rows = filter_hr_rows(hr_df, rid)
    pub = pub_df[pub_df['researcher_id'] == rid].copy() if not pub_df.empty else pd.DataFrame()
    pat = pat_df[pat_df['researcher_id'] == rid].copy() if not pat_df.empty else pd.DataFrame()
    job = job_df[job_df['researcher_id'] == rid].copy() if not job_df.empty else pd.DataFrame()
    pat_dedup = dedupe_patents(pat) if not pat.empty else pat

    if task.empty and hr_rows.empty and pub.empty and pat.empty:
        return html.Div('타임라인 데이터 없음', className='text-muted p-3')

    tasks = task_points(task)
    hrs = hr_points(hr_rows)
    pubs = pub_points(pub)
    pats = pat_points(pat_dedup)
    jobs = job_points(job)

    if not tasks and not hrs and not pubs and not pats:
        return html.Div('타임라인 데이터 없음', className='text-muted p-3')

    today = pd.Timestamp(datetime.now().date())
    code_map = task_code_map(tasks_info_df)
    task_names = {t['task_name'] for t in tasks}
    pub_unlinked = sum(1 for p in pubs
                        if not linked_task_names(p['project_name'], p['project_code'], task_names, code_map))
    pat_unlinked = sum(1 for p in pats
                        if not linked_task_names(p['project_name'], p['project_code'], task_names, code_map))
    header = _header_pills(len(tasks), hr_rows, len(pub), len(pat_dedup), pub_unlinked, pat_unlinked,
                            task_df, pub_df, pat_df, rid)
    main_col, main_stores = _build_main_spine(tasks, jobs, hrs, pubs, pats, code_map, today, rid)

    scroll_wrap = html.Div(main_col, style={
        'flex': '1 1 auto', 'minHeight': '0', 'overflowY': 'auto', 'overflowX': 'hidden',
    })
    stores = [dcc.Store(id='tl-expand-store', data=[]), dcc.Store(id='tl-open-panel', data=None)]
    return html.Div([header, scroll_wrap, *stores, *main_stores],
                     style={'height': '100%', 'display': 'flex', 'flexDirection': 'column'})


def _task_row_height(jobs):
    """과제 카드의 대략적 렌더 높이(px) 추정(이름/기간 2줄 + 직무 줄 수 + 여백)."""
    return 48 + len(jobs or []) * 13


def _build_time_axis(anchors):
    """anchors: [{'date': Timestamp, 'height': px}, ...] (최소 1개, 중복 날짜 허용).
    달력상 절대 시간이 아니라 "탄력적" 세로 위치를 만든다: 앞 항목의 실제 렌더
    높이만큼만 간격을 주고(데이터가 몰린 구간은 그만큼만 촘촘 = 팽창), 실제 날짜
    차이는 _GAP_CAP_DAYS로 상한을 둬(빈 기간은 압축) 아무리 오래 비어 있어도
    고정된 픽셀 이상 차지하지 않는다. 최근이 위(작은 y), 과거가 아래(큰 y)다.
    반환: (pos_fn, total_height). pos_fn(date)는 anchors에 없는 임의 날짜(연도
    경계 등)도 인접한 두 anchor 사이 실제 날짜 비율로 보간해 반환한다."""
    height_by_date = {}
    for a in anchors:
        height_by_date[a['date']] = max(height_by_date.get(a['date'], 0), a['height'])
    uniq = sorted(height_by_date)  # 오래된 것[0] → 최근 것[-1]
    n = len(uniq)

    # y[i]는 uniq[i]의 세로 위치. 최근(n-1)이 맨 위(_TOP_PAD)이고, 과거로 갈수록
    # (인덱스가 작아질수록) 그 다음(더 최근) 항목의 실제 높이 + 여백 + 압축된
    # 날짜 차이만큼 아래로 내려간다.
    y = [0.0] * n
    y[n - 1] = float(_TOP_PAD)
    for i in range(n - 2, -1, -1):
        gap_days = (uniq[i + 1] - uniq[i]).days
        step = height_by_date[uniq[i + 1]] + _ROW_BUFFER_PX + _PX_PER_DAY * min(gap_days, _GAP_CAP_DAYS)
        y[i] = y[i + 1] + step
    total_height = y[0] + height_by_date[uniq[0]] + _TOP_PAD

    def pos(d):
        idx = bisect.bisect_left(uniq, d)
        if idx < n and uniq[idx] == d:
            return y[idx]
        if idx == 0:
            # uniq[0](가장 오래된 anchor)보다 더 과거 → 그보다 아래(더 큰 y)
            gap_days = (uniq[0] - d).days
            return y[0] + height_by_date[uniq[0]] + _ROW_BUFFER_PX + _PX_PER_DAY * min(gap_days, _GAP_CAP_DAYS)
        if idx >= n:
            # uniq[-1](가장 최근 anchor)보다 더 미래 → 그보다 위(더 작은 y)
            gap_days = (d - uniq[-1]).days
            return y[-1] - (_ROW_BUFFER_PX + _PX_PER_DAY * min(gap_days, _GAP_CAP_DAYS))
        d0, d1 = uniq[idx - 1], uniq[idx]   # d0: 과거, d1: 최근
        y0, y1 = y[idx - 1], y[idx]         # y0 > y1 (과거일수록 아래)
        span_days = (d1 - d0).days
        if span_days <= 0:
            return y0
        frac = (d - d0).days / span_days
        return y0 + frac * (y1 - y0)

    return pos, total_height


def _group_overlapping(items):
    """items: [{'start','end'}, ...] (Timestamp). 구간이 겹치는(직접·전이적으로)
    항목끼리 하나의 그룹으로 묶는다. 반환값은 그룹 목록(각 그룹은 items에 대한
    인덱스 리스트), items를 start 기준으로 훑는 스윕 방식."""
    order = sorted(range(len(items)), key=lambda i: items[i]['start'])
    groups = []
    current, current_end = [], None
    for i in order:
        it = items[i]
        if current and it['start'] <= current_end:
            current.append(i)
            current_end = max(current_end, it['end'])
        else:
            if current:
                groups.append(current)
            current, current_end = [i], it['end']
    if current:
        groups.append(current)
    return groups


def _assign_stack_groups(groups, dates, prefix):
    """그룹별로 최신 날짜가 앞(rank 0)에 오도록 정렬하고, 카드 스타일/클릭 콜백에
    쓸 (gkey, rank)를 원래 인덱스별로 반환. 그룹마다 현재 순서를 저장할 dcc.Store도
    함께 만든다."""
    stack_meta = {}
    stores = []
    for gi, group in enumerate(groups):
        ordered = sorted(group, key=lambda i: dates[i], reverse=True)
        gkey = f'{prefix}-g{gi}'
        for rank, idx in enumerate(ordered):
            stack_meta[idx] = (gkey, rank)
        stores.append(dcc.Store(id={'type': 'stack-order', 'gkey': gkey}, data=list(range(len(ordered)))))
    return stack_meta, stores


def _assign_task_colors(tasks):
    names = list(dict.fromkeys(t['task_name'] for t in tasks))
    return {name: TASK_COLOR_PALETTE[i % len(TASK_COLOR_PALETTE)] for i, name in enumerate(names)}


def _accordion_pill(kind, count, color, radius='999px', border_width='1.5px', unlinked=None):
    """헤더 요약 pill. 클릭하면 아래에 전체 폭 표가 펼쳐진다(아코디언 — 한 번에 하나만).
    unlinked가 0보다 크면(논문/특허) '(전체) *과제미연결수'를 덧붙인다. 미연결이
    하나도 없으면(0) 굳이 표시하지 않는다."""
    label = f'{kind} ({count})'
    if unlinked:
        label += f' *{unlinked}'
    return html.Div(label, id={'type': 'tl-header-pill', 'kind': kind}, n_clicks=0, style={
        'border': f'{border_width} solid {color}', 'borderRadius': radius,
        'padding': '4px 14px', 'fontSize': '0.78rem', 'fontWeight': 600, 'color': color,
        'cursor': 'pointer', 'userSelect': 'none', 'display': 'inline-block',
    })


def _accordion_panel(kind, body):
    return html.Div(body, id={'type': 'tl-header-panel', 'kind': kind}, style={
        'display': 'none', 'marginTop': '6px', 'padding': '10px 14px',
        'border': f'1px solid {_GRIDLINE}', 'borderRadius': '10px', 'backgroundColor': '#fafafa',
        'maxHeight': '240px', 'overflowY': 'auto',
    })


def _hr_cell(val) -> str:
    s = str(val).strip() if val is not None else ''
    return '-' if s.lower() in ('', 'nan', 'none', 'nat') else s


def filter_hr_rows(hr_df, rid):
    """이 연구원의 인사발령 행 중, order_date가 '→'(연속 표시용 특수값으로 추정)인
    행을 제외하고 최신순 정렬해 반환. 헤더 pill 개수와 표에서 공통으로 쓴다."""
    rows = (hr_df[hr_df['researcher_id'] == rid].sort_values('order_date', ascending=False)
            if not hr_df.empty else pd.DataFrame())
    if rows.empty:
        return rows
    return rows[rows['order_date'].astype(str).str.strip() != '→']


def _hr_table(hr_rows):
    """인사발령 표: 발령일(order_date)/발령명(order_name)/부서(order_dep)/
    직급명(order_cl)/직책명(order_assignment). 값이 없으면 '-'."""
    if hr_rows.empty:
        return html.Div('인사발령 이력 없음', className='text-muted small')

    table_rows = [
        html.Tr([
            html.Td(_hr_cell(row.get('order_date')), className='small text-muted', style={'wordBreak': 'break-word'}),
            html.Td(_hr_cell(row.get('order_name')), className='small', style={'wordBreak': 'break-word'}),
            html.Td(_hr_cell(row.get('order_dep')), className='small text-muted', style={'wordBreak': 'break-word'}),
            html.Td(_hr_cell(row.get('order_cl')), className='small', style={'wordBreak': 'break-word'}),
            html.Td(_hr_cell(row.get('order_assignment')), className='small text-muted',
                    style={'wordBreak': 'break-word'}),
        ])
        for _, row in hr_rows.iterrows()
    ]
    return dbc.Table([
        html.Thead(html.Tr([
            html.Th('발령일', style={'fontSize': '0.72rem', 'width': '16%'}),
            html.Th('발령명', style={'fontSize': '0.72rem', 'width': '26%'}),
            html.Th('부서', style={'fontSize': '0.72rem', 'width': '22%'}),
            html.Th('직급명', style={'fontSize': '0.72rem', 'width': '18%'}),
            html.Th('직책명', style={'fontSize': '0.72rem', 'width': '18%'}),
        ]), className='table-light'),
        html.Tbody(table_rows),
    ], bordered=False, hover=True, size='sm', className='mb-0', style={'tableLayout': 'fixed', 'width': '100%'})


def _header_pills(task_count, hr_rows, pub_count, pat_count, pub_unlinked, pat_unlinked,
                   task_df, pub_df, pat_df, rid):
    kinds = [
        ('과제', task_count, None, '#1f1f1f', '8px', tasks_block(task_df, rid)),
        ('인사발령', len(hr_rows), None, EVENT_COLORS['인사발령'], '999px', _hr_table(hr_rows)),
        ('논문', pub_count, pub_unlinked, EVENT_COLORS['논문'], '999px', publications_tab(pub_df, rid)),
        ('특허', pat_count, pat_unlinked, EVENT_COLORS['특허'], '999px', patents_tab(pat_df, rid)),
    ]
    pills = [_accordion_pill(kind, count, color, radius, unlinked=unlinked)
             for kind, count, unlinked, color, radius, _ in kinds]
    panels = [_accordion_panel(kind, body) for kind, _, _, _, _, body in kinds]
    return html.Div([
        html.Div(pills, className='d-flex gap-2 flex-wrap'),
        html.Div(panels),
    ], className='mb-2', style={'flex': '0 0 auto'})


def _year_gridlines(pos_fn, min_year, max_year):
    children = []
    for yr in range(min_year, max_year + 1):
        d = pd.Timestamp(year=yr, month=1, day=1)
        y_px = pos_fn(d)
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


def _overlapping_jobs(task, jobs, today):
    """과제 기간과 겹치는 직무 구간만 겹치는 부분으로 잘라 반환한다. 종료일이 없는
    (진행중) 직무는 오늘 날짜로 클리핑한다."""
    result = []
    for j in jobs:
        j_end = j['end'] if j['end'] is not None else today
        start = max(task['start'], j['start'])
        end = min(task['end'], j_end)
        if start <= end:
            result.append({'name': j['name'], 'start': start, 'end': end})
    return result


def _resolve_item_task(item, task_names, code_map, tasks):
    """논문/특허 한 건이 이 연구원의 어떤 과제 인스턴스(tasks 리스트의 인덱스)에
    속하는지 반환. project_name/project_code로 연결되면 참여기간과 무관하게
    그 과제에 우선 연결한다(논문은 연구 종료 후 게재되는 경우가 많아, 기간
    내로 제한하면 실제로 연결된 항목 대부분이 걸러지는 문제가 있었다).
    같은 과제명이 여러 시점에 걸쳐 여러 번 수행된 경우(인스턴스 여러 개)에는
    이 항목의 날짜가 속하는 인스턴스를 우선 고르고, 어느 기간에도 속하지
    않으면 날짜가 가장 가까운 인스턴스를 고른다. project_name/code로 아예
    연결되는 과제가 없으면 None(타임라인 요약 카드에서만 노출)."""
    linked = linked_task_names(item['project_name'], item['project_code'], task_names, code_map)
    if not linked:
        return None
    linked_set = set(linked)
    candidates = [i for i, t in enumerate(tasks) if t['task_name'] in linked_set]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    for i in candidates:
        t = tasks[i]
        if t['start'] <= item['date'] <= t['end']:
            return i
    return min(candidates, key=lambda i: min(abs((item['date'] - tasks[i]['start']).days),
                                              abs((item['date'] - tasks[i]['end']).days)))


def _task_expand_body(matched_pubs, matched_pats):
    """과제 박스를 클릭해 펼쳤을 때 안에 나열할 연결 논문/특허 목록(없으면 안내 문구)."""
    if not matched_pubs and not matched_pats:
        return html.P('연결된 논문/특허 없음', className='empty',
                       style={'fontSize': '0.68rem', 'color': _LEGEND_NEUTRAL, 'margin': 0})
    items = [
        html.Div(f"{_ICONS['논문']} {_pub_pill_text(p)} · {p['title']}",
                  style={'fontSize': '0.66rem', 'color': '#333', 'marginTop': '2px',
                         'whiteSpace': 'normal', 'overflowWrap': 'break-word'})
        for p in matched_pubs
    ] + [
        html.Div(f"{_ICONS['특허']} {_patent_pill_text(p)} · {p['title']}",
                  style={'fontSize': '0.66rem', 'color': '#333', 'marginTop': '2px',
                         'whiteSpace': 'normal', 'overflowWrap': 'break-word'})
        for p in matched_pats
    ]
    return html.Div(items)


def _build_main_spine(tasks, jobs, hrs, pubs, pats, code_map, today, rid):
    task_names = {t['task_name'] for t in tasks}
    for p in pubs:
        p['ref'] = _resolve_item_task(p, task_names, code_map, tasks)
    for p in pats:
        p['ref'] = _resolve_item_task(p, task_names, code_map, tasks)

    matched_pubs_by_task = {i: [] for i in range(len(tasks))}
    matched_pats_by_task = {i: [] for i in range(len(tasks))}
    for p in pubs:
        if p['ref'] is not None:
            matched_pubs_by_task[p['ref']].append(p)
    for p in pats:
        if p['ref'] is not None:
            matched_pats_by_task[p['ref']].append(p)

    task_jobs_by_idx = [_overlapping_jobs(t, jobs, today) for t in tasks]

    # 스파인에는 과제(구간)와 인사발령(시점)만 배치한다. 논문/특허는 스파인에
    # 따로 나타나지 않고, 연결된 과제 박스를 펼쳤을 때 그 안에만 나열된다.
    spine_items = (
        [{'kind': 'task', 'anchor': t['start'], 'interval': {'start': t['start'], 'end': t['end']},
          'ref': i, 'payload': t, 'height': _task_row_height(task_jobs_by_idx[i])}
         for i, t in enumerate(tasks)]
        + [{'kind': 'hr', 'anchor': h['date'], 'interval': {'start': h['date'], 'end': h['date']},
            'ref': None, 'payload': h, 'height': _HR_ROW_HEIGHT} for h in hrs]
    )

    dates = [it['anchor'] for it in spine_items]
    intervals = [it['interval'] for it in spine_items]
    groups = _group_overlapping(intervals)
    stack_meta, stores = _assign_stack_groups(groups, dates, f'{rid}-main')

    # 오늘을 높이 0짜리 anchor로 포함시켜, 스파인이 정확히 현재 시점에서 끝나도록
    # 한다(마지막 실제 항목 이후로 미래 방향 여백이 무한정 늘어나지 않게).
    anchors = [{'date': it['anchor'], 'height': it['height']} for it in spine_items] + [{'date': today, 'height': 0}]
    pos_fn, total_height = _build_time_axis(anchors)

    min_year = min([d.year for d in dates] + [today.year])
    max_year = today.year

    task_colors = _assign_task_colors(tasks)
    task_ref_map = {}   # f'{gkey}|{rank}' → 과제의 tasks 리스트 인덱스(클라이언트사이드 콜백이 조회)

    children = [
        html.Div(style={
            'position': 'absolute', 'top': '0', 'bottom': '0', 'left': f'{_SPINE_X}px',
            'borderLeft': f'2px dashed {_SPINE_COLOR}',
        }),
        *_year_gridlines(pos_fn, min_year, max_year),
    ]

    for i, it in enumerate(spine_items):
        gkey, rank = stack_meta[i]
        # 세로 위치가 이미 탄력적 축(_build_time_axis)으로 충분히 벌어져 있어 겹칠
        # 일이 없으므로, 가로 위치는 랭크와 무관하게 항상 맨 왼쪽(_STACK_BASE_X)에
        # 정렬한다. 랭크는 겹침 그룹 내 z-index(맨 앞으로 가져오기)에만 쓰인다.
        x_px = _STACK_BASE_X
        z_index = 100 - rank
        y_px = pos_fn(it['anchor'])

        if it['kind'] == 'task':
            t = it['payload']
            task_idx = it['ref']
            color = task_colors[t['task_name']]
            task_jobs = task_jobs_by_idx[task_idx]
            matched_pubs = matched_pubs_by_task[task_idx]
            matched_pats = matched_pats_by_task[task_idx]
            expand_body = _task_expand_body(matched_pubs, matched_pats)
            children.append(_stack_connector(y_px, x_px, color))
            children.append(_task_card(t, gkey, rank, y_px, x_px, z_index, color, task_jobs,
                                        len(matched_pubs), len(matched_pats)))
            children.append(_task_expand_overlay(expand_body, task_idx, y_px, x_px, it['height'], color))
            task_ref_map[f'{gkey}|{rank}'] = task_idx
            continue

        e = {'date': it['payload']['date'], 'kind': '인사발령', 'text': _hr_pill_text(it['payload']), 'title': None}
        color = EVENT_COLORS['인사발령']
        children.append(_stack_connector(y_px, x_px, color))
        children.append(_event_pill(e, gkey, rank, y_px, x_px, z_index, color))

    main_col = html.Div(children, style={'position': 'relative', 'height': f'{total_height}px',
                                          'paddingBottom': '20px'})
    stores = [*stores, dcc.Store(id='tl-task-ref-map', data=task_ref_map)]
    return main_col, stores


def _stack_connector(y_px, x_px, color):
    return html.Div(style={
        'position': 'absolute', 'top': f'{y_px + 13}px', 'left': f'{_SPINE_X}px',
        'width': f'{max(x_px - _SPINE_X, 0)}px', 'height': '2px',
        'backgroundColor': color, 'opacity': 0.55, 'zIndex': 1,
    })


def _task_counts_badge(pub_count, pat_count):
    """과제명 우측에 붙는 연결 논문/특허 수 배지. 하나도 없으면 아무것도 표시하지 않는다."""
    parts = []
    if pub_count:
        parts.append(f"{_ICONS['논문']}{pub_count}")
    if pat_count:
        parts.append(f"{_ICONS['특허']}{pat_count}")
    if not parts:
        return None
    return html.Span(' '.join(parts), style={
        'fontSize': '0.66rem', 'color': _LEGEND_NEUTRAL, 'fontWeight': 500,
        'whiteSpace': 'nowrap', 'flexShrink': '0', 'marginLeft': '6px',
    })


def _task_card(t, gkey, rank, y_px, x_px, z_index, color, jobs, pub_count, pat_count):
    start_disp = t['start'].strftime('%y.%m')
    end_disp = '진행중' if t['end_label'] == '진행중' else t['end'].strftime('%y.%m')
    name_disp = truncate(t['task_name'], 60)
    tooltip_id = f'task-tt-{gkey}-{rank}'

    job_lines = [
        html.Div(f"{j['name']}({j['start'].strftime('%y.%m')}~{j['end'].strftime('%y.%m')})", style={
            'fontSize': '0.64rem', 'color': _LEGEND_NEUTRAL, 'marginTop': '1px',
        })
        for j in (jobs or [])
    ]

    name_row_children = [
        html.Div(name_disp, id=tooltip_id, className='fw-semibold',
                 style={'fontSize': '0.76rem', 'color': color, 'whiteSpace': 'nowrap',
                        'overflow': 'hidden', 'textOverflow': 'ellipsis', 'minWidth': '0',
                        'flex': '0 1 auto'}),
    ]
    counts_badge = _task_counts_badge(pub_count, pat_count)
    if counts_badge is not None:
        name_row_children.append(counts_badge)

    return html.Div([
        html.Div(name_row_children, style={'display': 'flex', 'alignItems': 'baseline'}),
        html.Div(f'{start_disp} ~ {end_disp}', style={
            'fontSize': '0.66rem', 'color': _LEGEND_NEUTRAL, 'marginTop': '1px',
        }),
        *job_lines,
        dbc.Tooltip(t['task_name'], target=tooltip_id, placement='top'),
    ], id={'type': 'stack-card', 'gkey': gkey, 'idx': rank}, n_clicks=0, style={
        'position': 'absolute', 'top': f'{y_px}px', 'left': f'{x_px}px', 'right': '4px',
        'zIndex': z_index,
        'backgroundColor': '#ffffff', 'border': f'1.3px solid {color}',
        'borderRadius': '10px', 'padding': '5px 10px', 'cursor': 'pointer',
        'boxShadow': '0 1px 4px rgba(0,0,0,0.10)',
    })


# 과제 박스를 펼쳤을 때 나오는 연결 논문/특허 패널. 카드 내부(자식)가 아니라
# main_col의 형제로 별도 배치한다 — 카드 자신이 z-index를 명시해 별도의 스태킹
# 컨텍스트를 만들기 때문에, 카드 안에 넣으면 이 패널의 z-index가 카드 바깥의
# 다른 항목(예: 아래쪽 인사발령 필)에 가려질 수 있다. 형제로 두고 항상 최상위
# 고정 z-index를 줘 어떤 항목도 이 패널을 가리지 못하게 한다.
_TASK_EXPAND_Z = 9999


def _task_expand_overlay(expand_body, task_idx, y_px, x_px, card_height, color):
    return html.Div(expand_body, id={'type': 'task-expand-body', 'ref': task_idx}, style={
        'display': 'none', 'position': 'absolute',
        'top': f'{y_px + card_height + 4}px', 'left': f'{x_px}px', 'right': '4px',
        'zIndex': _TASK_EXPAND_Z,
        'backgroundColor': '#ffffff', 'border': f'1.3px solid {color}',
        'borderRadius': '8px', 'padding': '8px 10px',
        'boxShadow': '0 4px 16px rgba(0,0,0,0.18)',
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


def _event_pill(e, gkey, rank, y_px, x_px, z_index, color):
    tooltip_id = f'event-tt-{gkey}-{rank}'
    # 컬럼 폭이 좁을 때 텍스트가 프레임 밖으로 잘리지 않도록, 고정폭 대신 남은
    # 가로 공간(100% - 스파인 여백)을 넘지 않는 선에서 줄바꿈되게 한다.
    inner = html.Div(f"{_ICONS[e['kind']]} {e['text']}", id=tooltip_id, style={
        'backgroundColor': color, 'color': '#ffffff',
        'borderRadius': '14px', 'padding': '4px 14px', 'fontSize': '0.72rem',
        'fontWeight': 500, 'whiteSpace': 'normal', 'overflowWrap': 'break-word',
        'boxShadow': '0 1px 3px rgba(0,0,0,0.10)',
    })
    wrapper = html.Div(
        inner, id={'type': 'stack-card', 'gkey': gkey, 'idx': rank}, n_clicks=0,
        style={
            'position': 'absolute', 'top': f'{y_px}px', 'left': f'{x_px}px', 'right': '4px',
            'zIndex': z_index, 'cursor': 'pointer',
        },
    )
    if not e['title']:
        return wrapper
    # 특허/논문은 호버 시 전체 title 표시. placement='top'이면 pill 위쪽에 여백을 두고
    # 뜨므로 pill 자체는 가리지 않는다.
    return html.Div([wrapper, dbc.Tooltip(e['title'], target=tooltip_id, placement='top')])


# ── 클릭한 카드(과제/이벤트 공통)를 스택 맨 위로 올리는 클라이언트사이드 콜백 ──
# 세로 위치가 이미 탄력적 축(_build_time_axis)으로 충분히 벌어져 있어 겹칠 일이
# 없으므로, 가로 위치(left)는 항상 _STACK_BASE_X로 고정하고 건드리지 않는다.
# 클릭 시에는 z-index만 맨 앞으로 올린다.
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

        const outIds = ctx.outputs_list[0].map(o => o.id.idx);
        let order = (current_order && current_order.length ? current_order : outIds.slice()).slice();
        if (order.indexOf(clickedIdx) === -1) { order = outIds.slice(); }
        order = order.filter(i => i !== clickedIdx);
        order.unshift(clickedIdx);

        const newStyles = outIds.map((idx, i) => {
            const pos = order.indexOf(idx);
            const style = Object.assign({}, current_styles[i]);
            style.zIndex = 100 - pos;
            return style;
        });

        return [newStyles, order];
    }
    """,
    Output({'type': 'stack-card', 'gkey': MATCH, 'idx': ALL}, 'style'),
    Output({'type': 'stack-order', 'gkey': MATCH}, 'data'),
    Input({'type': 'stack-card', 'gkey': MATCH, 'idx': ALL}, 'n_clicks'),
    State({'type': 'stack-card', 'gkey': MATCH, 'idx': ALL}, 'style'),
    State({'type': 'stack-order', 'gkey': MATCH}, 'data'),
)


# ── 과제 카드 클릭 → 박스 안의 연결 논문/특허(task-expand-body) 펼치기/접기 ──
# (여러 과제 동시 펼침 가능). 카드 쌓기 순서(위 콜백)와는 독립된 상태
# (tl-expand-store, 펼쳐진 과제의 ref 목록)로 관리한다.
# 과제 카드와 인사발령 필이 모두 'stack-card' id를 공유하므로(위 재배치 콜백과
# 정확히 같은 id 모양이어야 매칭됨 — 여기에 kind/ref 등 키를 더 넣으면 그
# 콜백의 매칭이 깨진다), 이 콜백은 모든 stack-card 클릭을 받은 뒤
# tl-task-ref-map(gkey|idx → 과제 인덱스)에서 찾아 과제 카드 클릭만 처리하고,
# 인사발령 필 클릭은 무시한다.
dash.clientside_callback(
    """
    function(n_clicks_list, ref_map, current_set, current_body_styles) {
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

        const lookupKey = triggeredId.gkey + '|' + triggeredId.idx;
        if (!ref_map || !(lookupKey in ref_map)) {
            return [dash_clientside.no_update, dash_clientside.no_update];
        }
        const refIdx = ref_map[lookupKey];

        let expanded = (current_set || []).slice();
        const pos = expanded.indexOf(refIdx);
        if (pos === -1) { expanded.push(refIdx); } else { expanded.splice(pos, 1); }

        const outIds = ctx.outputs_list[1].map(o => o.id.ref);
        const newStyles = outIds.map((ref, i) => {
            const style = Object.assign({}, current_body_styles[i]);
            style.display = expanded.includes(ref) ? 'block' : 'none';
            return style;
        });

        return [expanded, newStyles];
    }
    """,
    Output('tl-expand-store', 'data'),
    Output({'type': 'task-expand-body', 'ref': ALL}, 'style'),
    Input({'type': 'stack-card', 'gkey': ALL, 'idx': ALL}, 'n_clicks'),
    State('tl-task-ref-map', 'data'),
    State('tl-expand-store', 'data'),
    State({'type': 'task-expand-body', 'ref': ALL}, 'style'),
)


# ── 헤더 요약 pill 클릭 → 전체 폭 표 아코디언 펼치기/접기 (한 번에 하나만) ──
dash.clientside_callback(
    """
    function(n_clicks_list, current_open, current_panel_styles) {
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

        const clickedKind = triggeredId.kind;
        const newOpen = (current_open === clickedKind) ? null : clickedKind;

        const outIds = ctx.outputs_list[1].map(o => o.id.kind);
        const newStyles = outIds.map((kind, i) => {
            const style = Object.assign({}, current_panel_styles[i]);
            style.display = (kind === newOpen) ? 'block' : 'none';
            return style;
        });

        return [newOpen, newStyles];
    }
    """,
    Output('tl-open-panel', 'data'),
    Output({'type': 'tl-header-panel', 'kind': ALL}, 'style'),
    Input({'type': 'tl-header-pill', 'kind': ALL}, 'n_clicks'),
    State('tl-open-panel', 'data'),
    State({'type': 'tl-header-panel', 'kind': ALL}, 'style'),
)
