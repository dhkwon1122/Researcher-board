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

import pandas as pd


# 협업 분석에서 제외할 1단계 부서명(2026-10-14, 사용자 확정 — Staff 조직과 함께 제외). 대소문자 무시.
EXCLUDED_LEVEL1 = {'SAIT'}


def is_excluded_level1(name) -> bool:
    return str(name or '').strip().upper() in EXCLUDED_LEVEL1


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


def network_figure(pairs: dict, top_n: int = 20, min_weight: int = 1, order: list | None = None):
    """원형 배치 순서는 order(조직코드 순)를 따른다. 노드 마우스 오버: 타 단위 협업 합계 + 상위 5개 상대별 건수."""
    import plotly.graph_objects as go

    nodes = _ordered(top_nodes(pairs, top_n), order)
    links = [(a, b, n) for (a, b), n in pairs.items() if a in nodes and b in nodes and n >= min_weight]
    if not nodes or not links:
        return None
    nodes = [n for n in nodes if any(n in (a, b) for a, b, _ in links)]
    total = {n: 0 for n in nodes}
    for a, b, w in links:
        total[a] += w
        total[b] += w
    pos = {n: (math.cos(2 * math.pi * i / len(nodes)), math.sin(2 * math.pi * i / len(nodes)))
           for i, n in enumerate(nodes)}
    wmax = max(w for _, _, w in links)
    fig = go.Figure()
    for a, b, w in sorted(links, key=lambda x: x[2]):
        fig.add_trace(go.Scatter(
            x=[pos[a][0], pos[b][0]], y=[pos[a][1], pos[b][1]], mode='lines',
            line=dict(width=1 + 7 * w / wmax, color=f'rgba(22,119,255,{0.2 + 0.6 * w / wmax:.2f})'),
            hovertemplate=f'{a} ↔ {b}<br>최근 5년 협업 {w}건<extra></extra>', showlegend=False))
    tmax = max(total.values())
    partners = _partners(pairs)
    all_total = {n: sum(c for _, c in partners.get(n, [])) for n in nodes}

    def _top5(n):
        return '<br>'.join(f'· {p}: {c}건' for p, c in partners.get(n, [])[:5])

    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode='markers+text',
        text=[n if len(n) <= 14 else n[:13] + '…' for n in nodes], textposition='top center',
        customdata=[[n, all_total[n], _top5(n)] for n in nodes],
        marker=dict(size=[10 + 22 * total[n] / tmax for n in nodes], color='#1677ff',
                    line=dict(width=1, color='white')),
        hovertemplate='<b>%{customdata[0]}</b><br>타 단위 협업 합계 %{customdata[1]}건<br>'
                      '<span style="font-size:11px">상위 협업 상대</span><br>%{customdata[2]}<extra></extra>',
        hoverlabel=dict(align='left'), showlegend=False))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor='x'),
                      margin=dict(l=10, r=10, t=10, b=10), height=520, plot_bgcolor='white')
    return fig


def heatmap_figure(pairs: dict, top_n: int = 20, order: list | None = None):
    """협업량 상위 top_n 단위를 고른 뒤, X·Y축 모두 order(팀/리더 참조 조직코드 순)로 나열."""
    import plotly.graph_objects as go

    nodes = _ordered(top_nodes(pairs, top_n), order)
    if not nodes:
        return None
    z = [[0] * len(nodes) for _ in nodes]
    idx = {n: i for i, n in enumerate(nodes)}
    for (a, b), w in pairs.items():
        if a in idx and b in idx:
            z[idx[a]][idx[b]] = w
            z[idx[b]][idx[a]] = w
    for i in range(len(nodes)):
        z[i][i] = None   # 같은 단위는 비움
    fig = go.Figure(go.Heatmap(
        z=z, x=nodes, y=nodes, colorscale='Blues', hoverongaps=False,
        hovertemplate='%{y} ↔ %{x}<br>최근 5년 협업 %{z}건<extra></extra>', colorbar=dict(title='건')))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=max(420, 22 * len(nodes) + 160),
                      xaxis=dict(tickangle=-45, automargin=True), yaxis=dict(autorange='reversed', automargin=True))
    return fig
