"""부서/과제별 논문 등급 비교(2026-10-14) — 보유 전문성 > 조직 분석 > "부서별 논문 등급" 하위 탭.

현재 재직 연구원의 최근 N년 논문을 등급구분(최우수/우수/일반/외부)별로 세어 1단계부서명(부서) 또는
3단계부서명(과제) 단위로 합산한다. 같은 단위의 공저자가 같은 논문을 각자 올린 경우는 제목 기준 1건으로 센다.
등급구분 열이 없거나(원천 미반영) 해당 기간 논문이 없으면 빈 결과.
"""
import re
from datetime import date

import pandas as pd
import plotly.graph_objects as go

from components.timeline_data import PUBLICATION_GRADE_COLORS, PUBLICATION_GRADE_ORDER
from services.data_store import filter_current, read_processed

RECENT_YEARS = 5


def _year(row) -> int | None:
    for v in (row.get('pub_year'), row.get('pub_date')):
        m = re.match(r'(\d{4})', str(v or ''))
        if m:
            return int(m.group(1))
    return None


def grade_counts(level: str = 'level1', years: int = RECENT_YEARS) -> pd.DataFrame:
    """단위별 등급 건수 표: 열 = unit, 최우수, 우수, 일반, 외부, 합계. 행 순서 = 조직코드 순."""
    from services import similarity_map as sm
    pubs = read_processed('publications')
    cols = ['unit', *PUBLICATION_GRADE_ORDER, '합계']
    if pubs.empty or 'grade_publication' not in pubs.columns:
        return pd.DataFrame(columns=cols)
    res = filter_current(read_processed('researchers'))
    if res.empty or 'org_code' not in res.columns:
        return pd.DataFrame(columns=cols)
    idx = 0 if level == 'level1' else 2
    cache: dict = {}
    unit_by_rid = {}
    for rid, org in zip(res['researcher_id'], res['org_code'].astype(str).str.strip()):
        if org not in cache:
            cache[org] = sm.org_code_level_names(org)[idx]
        if cache[org]:
            unit_by_rid[rid] = cache[org]
    since = date.today().year - years + 1
    seen, counts = set(), {}
    for r in pubs.fillna('').to_dict('records'):
        unit = unit_by_rid.get(r.get('researcher_id'))
        grade = str(r.get('grade_publication') or '').strip()
        y = _year(r)
        if not unit or grade not in PUBLICATION_GRADE_ORDER or y is None or y < since:
            continue
        key = (unit, str(r.get('title') or '').strip().lower())
        if key in seen:
            continue
        seen.add(key)
        counts.setdefault(unit, dict.fromkeys(PUBLICATION_GRADE_ORDER, 0))[grade] += 1
    if not counts:
        return pd.DataFrame(columns=cols)
    order = [o['value'] for o in sm.level_filter_options(1 if level == 'level1' else 3)]
    pos = {n: i for i, n in enumerate(order)}
    rows = [{'unit': u, **c, '합계': sum(c.values())}
            for u, c in sorted(counts.items(), key=lambda kv: (pos.get(kv[0], len(pos)), kv[0]))]
    return pd.DataFrame(rows, columns=cols)


def grade_figure(df: pd.DataFrame, top_n: int = 30):
    """최우수·우수 많은 순 상위 top_n 단위의 등급별 누적 가로 막대. 비어 있으면 None."""
    if df is None or df.empty:
        return None
    df = df.assign(_top=df['최우수'] * 1000 + df['우수']).sort_values(['_top', '합계'], ascending=False).head(top_n)
    df = df.iloc[::-1]   # 가로 막대는 아래부터 그려지므로 뒤집어 1위가 맨 위
    fig = go.Figure()
    for g in PUBLICATION_GRADE_ORDER:
        fig.add_bar(y=df['unit'], x=df[g], name=g, orientation='h', marker_color=PUBLICATION_GRADE_COLORS[g],
                    hovertemplate='%{y}<br>' + g + ' %{x}건<extra></extra>')
    fig.update_layout(barmode='stack', height=max(260, 26 * len(df) + 80), margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation='h', y=1.02, x=0), plot_bgcolor='#fff',
                      xaxis=dict(title='논문 수(최근 5년, 제목 기준 중복 제외)', gridcolor='#eee'),
                      yaxis=dict(automargin=True))
    return fig
