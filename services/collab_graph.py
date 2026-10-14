"""
부서/과제간 협업 시각화용 집계 + plotly Figure 생성(2026-10-09).

입력은 pipeline/process_expertise_metrics.py가 만든 collaboration_edges.csv(연구원 쌍 단위)로,
recent_count(최근 5년 공동 논문+특허 건수)와 현재 1단계/3단계 부서명(level1_*/level3_*)을 쓴다.
level='level1'이면 부서(1단계부서명) 간, 'level3'이면 과제(3단계부서명) 간 협업이며
같은 단위 안의 협업과 단계를 알 수 없는(빈 값) 쪽은 제외한다. 가중치는 연구원 쌍 단위
공동 건수의 합이다.
"""
from __future__ import annotations

import math
import re

import pandas as pd


# 협업 분석에서 제외할 1단계 부서명(2026-10-14, 사용자 확정 — Staff 조직과 함께 제외, 하위 조직은 1단계 이름이
# 같으므로 자동 포함). 비교는 대소문자·공백 무시.
EXCLUDED_LEVEL1 = {'SAIT', 'Ideation Factory T/F(SAIT)'}


def _norm_l1(name) -> str:
    return re.sub(r'\s+', '', str(name or '')).upper()


_EXCLUDED_NORM = {_norm_l1(n) for n in EXCLUDED_LEVEL1}


def is_excluded_level1(name) -> bool:
    return _norm_l1(name) in _EXCLUDED_NORM


def aggregate(edges: pd.DataFrame, level: str) -> dict[tuple[str, str], int]:
    """{(단위A, 단위B)(사전순): 최근 5년 협업량}. 필요한 열이 없으면 {}.
    한쪽이라도 1단계 부서명이 EXCLUDED_LEVEL1(SAIT)인 쌍은 제외 — 분석 재실행 전 산출물에도 바로 적용되도록 화면에서도 거른다."""
    a_col, b_col = f'{level}_a', f'{level}_b'
    if edges is None or edges.empty or not {a_col, b_col, 'recent_count'} <= set(edges.columns):
        return {}
    if {'level1_a', 'level1_b'} <= set(edges.columns):
        drop = edges['level1_a'].map(is_excluded_level1) | edges['level1_b'].map(is_excluded_level1)
        edges = edges[~drop]
    df = edges[[a_col, b_col, 'recent_count']].fillna('')
    out: dict = {}
    for a, b, n in zip(df[a_col].astype(str), df[b_col].astype(str), df['recent_count']):
        a, b = a.strip(), b.strip()
        try:
            n = int(float(n or 0))
        except ValueError:
            n = 0
        if not a or not b or a == b or n <= 0:
            continue
        key = (a, b) if a <= b else (b, a)
        out[key] = out.get(key, 0) + n
    return out


def _ordered(nodes: list[str], order: list | None) -> list[str]:
    """order(팀/리더 참조 조직코드 순 이름 목록)가 있으면 그 순서로, 목록에 없는 이름은 뒤에(이름순)."""
    if not order:
        return nodes
    pos = {n: i for i, n in enumerate(order)}
    return sorted(nodes, key=lambda n: (pos.get(n, len(pos)), n))


# 부서(1단계부서명)별 색(2026-10-14) — 서로 잘 구분되는 12색, 부서가 더 많으면 반복.
DEPT_PALETTE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b',
                '#e377c2', '#17becf', '#bcbd22', '#7f7f7f', '#3b4cc0', '#b8860b']


def dept_colors(depts: list) -> dict:
    """부서 목록(표시 순서) → 색. 같은 목록이면 늘 같은 색."""
    return {d: DEPT_PALETTE[i % len(DEPT_PALETTE)] for i, d in enumerate(dict.fromkeys(depts))}


def _shade(hex_color: str, t: float) -> str:
    """hex 색을 흰색 쪽으로 t(0~1)만큼 섞은 색 — 같은 부서 과제들을 같은 계열의 서로 다른 밝기로."""
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(c + (255 - c) * t) for c in (r, g, b))
    return f'#{r:02x}{g:02x}{b:02x}'


def node_colors(nodes: list, group_of: dict | None) -> tuple[dict, dict]:
    """(노드→색, 부서→색). group_of가 없으면(부서 기준 그래프) 노드 자체가 부서.
    과제 기준이면 같은 부서 과제들은 부서 색 계열에서 밝기만 다르게(0~55% 흰색 혼합)."""
    groups = [(group_of or {}).get(n, n) if group_of is not None else n for n in nodes]
    dcol = dept_colors(groups)
    if group_of is None:
        return {n: dcol[n] for n in nodes}, dcol
    members: dict = {}
    for n, g in zip(nodes, groups):
        members.setdefault(g, []).append(n)
    out = {}
    for g, ns in members.items():
        for i, n in enumerate(ns):
            out[n] = _shade(dcol[g], 0.55 * i / max(len(ns) - 1, 1) if len(ns) > 1 else 0.0)
    return out, dcol


def _partners(pairs: dict) -> dict:
    """단위 -> [(상대, 건수), ...] 건수 내림차순."""
    out: dict = {}
    for (a, b), n in pairs.items():
        out.setdefault(a, []).append((b, n))
        out.setdefault(b, []).append((a, n))
    for k in out:
        out[k].sort(key=lambda x: (-x[1], x[0]))
    return out


def top_nodes(pairs: dict, top_n: int) -> list[str]:
    """협업량 합이 큰 순으로 상위 top_n 단위."""
    total: dict = {}
    for (a, b), n in pairs.items():
        total[a] = total.get(a, 0) + n
        total[b] = total.get(b, 0) + n
    return [k for k, _ in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]]


def network_figure(pairs: dict, top_n: int = 20, min_weight: int = 1, order: list | None = None,
                   group_of: dict | None = None):
    """원형 배치 순서는 order(조직코드 순)를 따른다. 노드 마우스 오버: 타 단위 협업 합계 + 상위 5개 상대별 건수.
    2026-10-14: 노드 색 = 부서별 색(과제 기준이면 소속 부서 색 계열). group_of(과제→1단계부서명)가 있으면
    같은 부서 과제끼리 붙여 배치하고, 원 바깥쪽에 부서별 색 띠 + 부서명을 둘러 "이 과제들은 이 부서" 를 보여준다."""
    import plotly.graph_objects as go

    nodes = _ordered(top_nodes(pairs, top_n), order)
    links = [(a, b, n) for (a, b), n in pairs.items() if a in nodes and b in nodes and n >= min_weight]
    if not nodes or not links:
        return None
    nodes = [n for n in nodes if any(n in (a, b) for a, b, _ in links)]
    if group_of is not None:   # 같은 부서끼리 연속 배치(부서 순서 = 처음 나온 순서 = 조직코드 순)
        first = {}
        for i, n in enumerate(nodes):
            first.setdefault(group_of.get(n, n), i)
        nodes = sorted(nodes, key=lambda n: (first[group_of.get(n, n)], nodes.index(n)))
    colors, dcol = node_colors(nodes, group_of)
    total = {n: 0 for n in nodes}
    for a, b, w in links:
        total[a] += w
        total[b] += w
    k = len(nodes)
    ang = {n: 2 * math.pi * i / k for i, n in enumerate(nodes)}
    pos = {n: (math.cos(ang[n]), math.sin(ang[n])) for n in nodes}
    wmax = max(w for _, _, w in links)
    fig = go.Figure()
    for a, b, w in sorted(links, key=lambda x: x[2]):
        fig.add_trace(go.Scatter(
            x=[pos[a][0], pos[b][0]], y=[pos[a][1], pos[b][1]], mode='lines',
            line=dict(width=1 + 7 * w / wmax, color=f'rgba(90,90,90,{0.15 + 0.5 * w / wmax:.2f})'),
            hovertemplate=f'{a} ↔ {b}<br>최근 5년 협업 {w}건<extra></extra>', showlegend=False))

    # 바깥 레이어: 부서별 호(arc) + 부서명(과제 기준일 때만)
    if group_of is not None:
        runs = []
        for i, n in enumerate(nodes):
            g = group_of.get(n, n)
            if runs and runs[-1][0] == g:
                runs[-1][2] = i
            else:
                runs.append([g, i, i])
        half = math.pi / k
        for g, i0, i1 in runs:
            a0, a1 = 2 * math.pi * i0 / k - half * 0.85, 2 * math.pi * i1 / k + half * 0.85
            ts = [a0 + (a1 - a0) * j / 30 for j in range(31)]
            fig.add_trace(go.Scatter(x=[1.32 * math.cos(t) for t in ts], y=[1.32 * math.sin(t) for t in ts],
                                     mode='lines', line=dict(width=9, color=dcol[g]), hoverinfo='text',
                                     hovertext=g, showlegend=False))
            mid = (a0 + a1) / 2
            fig.add_annotation(x=1.5 * math.cos(mid), y=1.5 * math.sin(mid), text=f'<b>{g}</b>', showarrow=False,
                               font=dict(size=11, color=dcol[g]),
                               xanchor='left' if math.cos(mid) > 0.2 else 'right' if math.cos(mid) < -0.2 else 'center')

    tmax = max(total.values())
    partners = _partners(pairs)
    all_total = {n: sum(c for _, c in partners.get(n, [])) for n in nodes}

    def _top5(n):
        return '<br>'.join(f'· {p}: {c}건' for p, c in partners.get(n, [])[:5])

    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode='markers+text',
        text=[n if len(n) <= 14 else n[:13] + '…' for n in nodes], textposition='top center',
        customdata=[[n, all_total[n], _top5(n), (group_of or {}).get(n, n)] for n in nodes],
        marker=dict(size=[10 + 22 * total[n] / tmax for n in nodes], color=[colors[n] for n in nodes],
                    line=dict(width=1, color='#444')),
        hovertemplate=('<b>%{customdata[0]}</b>' + ('<br>부서: %{customdata[3]}' if group_of is not None else '')
                       + '<br>타 단위 협업 합계 %{customdata[1]}건<br>'
                       '<span style="font-size:11px">상위 협업 상대</span><br>%{customdata[2]}<extra></extra>'),
        hoverlabel=dict(align='left'), showlegend=False))
    lim = 1.95 if group_of is not None else 1.3
    fig.update_layout(xaxis=dict(visible=False, range=[-lim, lim]), yaxis=dict(visible=False, scaleanchor='x', range=[-lim, lim]),
                      margin=dict(l=10, r=10, t=10, b=10), height=560, plot_bgcolor='white')
    return fig


def heatmap_figure(pairs: dict, top_n: int = 20, order: list | None = None, group_of: dict | None = None):
    """협업량 상위 top_n 단위를 고른 뒤, X·Y축 모두 order(팀/리더 참조 조직코드 순)로 나열.
    2026-10-14: 축 이름을 부서 색으로 칠하고, 과제 기준(group_of)이면 같은 부서끼리 붙여 위쪽에 부서 색 띠 + 부서명,
    부서 경계에 구분선을 넣는다."""
    import plotly.graph_objects as go

    nodes = _ordered(top_nodes(pairs, top_n), order)
    if not nodes:
        return None
    if group_of is not None:
        first = {}
        for i, n in enumerate(nodes):
            first.setdefault(group_of.get(n, n), i)
        nodes = sorted(nodes, key=lambda n: (first[group_of.get(n, n)], nodes.index(n)))
    colors, dcol = node_colors(nodes, group_of)
    z = [[0] * len(nodes) for _ in nodes]
    idx = {n: i for i, n in enumerate(nodes)}
    for (a, b), w in pairs.items():
        if a in idx and b in idx:
            z[idx[a]][idx[b]] = w
            z[idx[b]][idx[a]] = w
    for i in range(len(nodes)):
        z[i][i] = None   # 같은 단위는 비움
    tick_col = {n: dcol[(group_of or {}).get(n, n)] if group_of is not None else colors[n] for n in nodes}
    ticktext = [f'<span style="color:{tick_col[n]}"><b>{n}</b></span>' for n in nodes]
    fig = go.Figure(go.Heatmap(
        z=z, x=list(range(len(nodes))), y=list(range(len(nodes))), colorscale='Blues', hoverongaps=False,
        customdata=[[[nodes[r], nodes[c]] for c in range(len(nodes))] for r in range(len(nodes))],
        hovertemplate='%{customdata[0]} ↔ %{customdata[1]}<br>최근 5년 협업 %{z}건<extra></extra>',
        colorbar=dict(title='건')))
    axis = dict(tickmode='array', tickvals=list(range(len(nodes))), ticktext=ticktext, automargin=True)
    top = 40
    if group_of is not None:
        runs = []
        for i, n in enumerate(nodes):
            g = group_of.get(n, n)
            if runs and runs[-1][0] == g:
                runs[-1][2] = i
            else:
                runs.append([g, i, i])
        for g, i0, i1 in runs:
            fig.add_shape(type='rect', xref='x', yref='paper', x0=i0 - 0.5, x1=i1 + 0.5, y0=1.005, y1=1.035,
                          fillcolor=dcol[g], line=dict(width=0))
            fig.add_annotation(x=(i0 + i1) / 2, y=1.04, xref='x', yref='paper', text=f'<b>{g}</b>', showarrow=False,
                               yanchor='bottom', font=dict(size=10, color=dcol[g]))
            if i0 > 0:   # 부서 경계선
                for kw in (dict(x0=i0 - 0.5, x1=i0 - 0.5, y0=-0.5, y1=len(nodes) - 0.5),
                           dict(y0=i0 - 0.5, y1=i0 - 0.5, x0=-0.5, x1=len(nodes) - 0.5)):
                    fig.add_shape(type='line', xref='x', yref='y', line=dict(color='#333', width=1), **kw)
        top = 70
    fig.update_layout(margin=dict(l=10, r=10, t=top, b=10), height=max(440, 22 * len(nodes) + 200),
                      xaxis=dict(tickangle=-45, **axis), yaxis=dict(autorange='reversed', **axis))
    return fig
