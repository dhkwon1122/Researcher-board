"""플랫폼/과제별 자산화 현황(논문·특허) — 보유 전문성 > 조직(플랫폼/과제) > "논문,특허(플랫폼/과제)" 탭.

2026-10-14 최초(논문 등급만) → 2026-10-15 특허 등급 추가·제외 조직 반영:
  - 대상: 현재 재직 연구원, Staff 조직(하위 포함)·1단계 SAIT/Ideation Factory T/F(SAIT) 제외(services/org_units)
  - 기간: 최근 5년(논문 실적일·특허 출원일 기준)
  - 논문 등급: 최우수 > 우수 > 일반 > 외부(등급구분). 같은 단위 공저는 제목 기준 1건.
  - 특허 등급: 전략("현재등급 - A급구분"이 전략출원) > A1 > A2 > 기타(그 외·빈 값, 현재등급 기준).
    같은 특허(여러 나라 출원 포함)는 출원ID 기준 1건, 같은 단위 공동발명도 1건.
  - (2026-10-15) 과제 기준은 구성원 1명 과제 제외(협업 탭과 같은 기준), 조직코드 순 정렬(그래프·표 공통),
    플랫폼(1단계부서명) 필터, 부서별 색(이름표·표 마커, 과제 기준은 같은 부서 과제끼리 묶고 부서색 배경 띠).
    서로 다른 단위의 공저/공동발명은 각 단위에 1건씩(단위 합계는 전사 건수보다 클 수 있음, 사용자 확정 유지).
"""
import re
from datetime import date

import pandas as pd

from services.data_store import read_processed

RECENT_YEARS = 5
PAPER_GRADES = ['최우수', '우수', '일반', '외부']
PATENT_GRADES = ['전략', 'A1', 'A2', '기타']
# 파스텔 톤(2026-10-15) — 높은 등급일수록 진하게
PAPER_COLORS = {'최우수': '#F4A7A7', '우수': '#F9CFA0', '일반': '#BCD6EE', '외부': '#DADDE6'}
PATENT_COLORS = {'전략': '#C8B1EA', 'A1': '#A9DCCB', 'A2': '#D3EBB4', '기타': '#E4E4E4'}


def _year(*vals):
    for v in vals:
        m = re.match(r'(\d{4})', str(v or ''))
        if m:
            return int(m.group(1))
    return None


def patent_grade(row) -> str:
    if str(row.get('patent_grade_a_sub') or '').strip() == '전략출원':
        return '전략'
    g = str(row.get('patent_grade') or '').strip().upper()
    return g if g in ('A1', 'A2') else '기타'


def dept_order() -> list:
    """플랫폼(1단계부서명) 목록 — 조직코드 순, 제외 조직(SAIT 등) 제외."""
    from services import similarity_map as sm
    from services.collab_graph import is_excluded_level1
    return [o['value'] for o in sm.level_filter_options(1) if not is_excluded_level1(o['value'])]


def dept_color_map() -> dict:
    """부서 → 색(협업 그래프와 같은 팔레트). 전체 부서 목록 기준이라 필터와 무관하게 같은 부서는 같은 색."""
    from services.collab_graph import dept_colors
    return dept_colors(dept_order())


def asset_counts(level: str = 'level1', years: int = RECENT_YEARS, platforms: list | None = None) -> pd.DataFrame:
    """단위별 건수표. 열: unit, 논문_최우수 … 논문_계, 특허_전략 … 특허_계, dept(소속 1단계부서명).
    행 순서 = 조직코드 순(과제 기준은 부서 조직코드 순으로 묶은 뒤 그 안에서 과제 조직코드 순).
    과제 기준은 구성원 1명인 과제 제외. platforms(1단계부서명 목록)를 주면 그 부서(과제는 소속 부서)만."""
    from collections import Counter
    from services import similarity_map as sm
    from services.org_units import unit_members
    unit_by_rid = unit_members(level)
    cols = ['unit'] + [f'논문_{g}' for g in PAPER_GRADES] + ['논문_계'] + [f'특허_{g}' for g in PATENT_GRADES] + ['특허_계']
    if level == 'level3':
        size = Counter(unit_by_rid.values())
        unit_by_rid = {r: u for r, u in unit_by_rid.items() if size[u] > 1}
    dept_of = sm.level1_of_level3() if level == 'level3' else {}
    if platforms:
        allowed = set(platforms)
        unit_by_rid = {r: u for r, u in unit_by_rid.items() if (dept_of.get(u, '') if level == 'level3' else u) in allowed}
    if not unit_by_rid:
        return pd.DataFrame(columns=cols + ['dept'])
    since = date.today().year - years + 1
    counts: dict = {}

    def _bump(unit, key):
        counts.setdefault(unit, dict.fromkeys(cols[1:], 0))[key] += 1

    pubs = read_processed('publications')
    if not pubs.empty and 'grade_publication' in pubs.columns:
        seen = set()
        for r in pubs.fillna('').to_dict('records'):
            unit = unit_by_rid.get(r.get('researcher_id'))
            grade = str(r.get('grade_publication') or '').strip()
            y = _year(r.get('pub_year'), r.get('pub_date'))
            if not unit or grade not in PAPER_GRADES or y is None or y < since:
                continue
            key = (unit, str(r.get('title') or '').strip().lower())
            if key not in seen:
                seen.add(key)
                _bump(unit, f'논문_{grade}')
    pats = read_processed('patents')
    if not pats.empty and 'application_id' in pats.columns:
        seen = set()
        for r in pats.fillna('').to_dict('records'):
            unit = unit_by_rid.get(r.get('researcher_id'))
            app = str(r.get('application_id') or '').strip()
            y = _year(r.get('application_date'))
            if not unit or not app or y is None or y < since:
                continue
            if (unit, app) not in seen:
                seen.add((unit, app))
                _bump(unit, f'특허_{patent_grade(r)}')
    if not counts:
        return pd.DataFrame(columns=cols + ['dept'])
    for c in counts.values():
        c['논문_계'] = sum(c[f'논문_{g}'] for g in PAPER_GRADES)
        c['특허_계'] = sum(c[f'특허_{g}'] for g in PATENT_GRADES)
    unit_pos = {n: i for i, n in enumerate(o['value'] for o in sm.level_filter_options(1 if level == 'level1' else 3))}
    dept_pos = {n: i for i, n in enumerate(dept_order())}

    def _key(u):
        d = dept_of.get(u, '') if level == 'level3' else u
        return (dept_pos.get(d, len(dept_pos)), unit_pos.get(u, len(unit_pos)), u)
    rows = [{'unit': u, **counts[u], 'dept': (dept_of.get(u, '') if level == 'level3' else u)}
            for u in sorted(counts, key=_key)]
    return pd.DataFrame(rows, columns=cols + ['dept'])


def asset_figure(df: pd.DataFrame):
    """논문·특허 등급별 누적 가로 막대 2개(같은 단위 순서 = 조직코드 순, 위에서 아래로).
    막대 색 = 등급, 이름표 색 = 부서색. 과제 기준(dept 열이 단위와 다름)이면 같은 부서 과제 묶음마다 연한 부서색
    배경 띠 + 오른쪽 부서명. 범례는 위쪽 가운데. 비어 있으면 None."""
    import plotly.graph_objects as go  # noqa: F401
    from plotly.subplots import make_subplots
    from services.collab_graph import _shade
    if df is None or df.empty:
        return None
    units = list(df['unit'])
    depts = list(df['dept']) if 'dept' in df.columns else units
    by_project = any(d != u for d, u in zip(depts, units))
    colors = dept_color_map()
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.04,
                        subplot_titles=('논문 (최근 5년)', '특허 (최근 5년, 출원 기준)'))
    for g in PAPER_GRADES:
        fig.add_bar(y=units, x=df[f'논문_{g}'], name=f'논문 {g}', orientation='h', row=1, col=1,
                    marker=dict(color=PAPER_COLORS[g], line=dict(color='#FFFFFF', width=1)),
                    hovertemplate='%{y}<br>논문 ' + g + ' %{x}건<extra></extra>')
    for g in PATENT_GRADES:
        fig.add_bar(y=units, x=df[f'특허_{g}'], name=f'특허 {g}', orientation='h', row=1, col=2,
                    marker=dict(color=PATENT_COLORS[g], line=dict(color='#FFFFFF', width=1)),
                    hovertemplate='%{y}<br>특허 ' + g + ' %{x}건<extra></extra>')
    ticktext = [f'<span style="color:{colors.get(d, "#3B4458")}"><b>{u}</b></span>' for u, d in zip(units, depts)]
    fig.update_yaxes(categoryorder='array', categoryarray=units, autorange='reversed',
                     tickvals=units, ticktext=ticktext, automargin=True)
    if by_project:   # 같은 부서 과제 묶음: 배경 띠 + 오른쪽 부서명
        start = 0
        for i in range(1, len(units) + 1):
            if i == len(units) or depts[i] != depts[start]:
                col = colors.get(depts[start], '#999999')
                fig.add_shape(type='rect', xref='paper', yref='y', x0=0, x1=1, y0=start - 0.5, y1=i - 0.5,
                              fillcolor=_shade(col, 0.88), line=dict(width=0), layer='below')
                fig.add_annotation(xref='paper', yref='y', x=1.0, xanchor='left', y=(start + i - 1) / 2,
                                   text=f'<b>{depts[start] or "(미분류)"}</b>', showarrow=False,
                                   font=dict(size=11, color=col))
                start = i
    fig.update_layout(barmode='stack', height=max(320, 28 * len(units) + 150), plot_bgcolor='rgba(0,0,0,0)',
                      margin=dict(l=10, r=150 if by_project else 10, t=110, b=30),
                      legend=dict(orientation='h', x=0.5, xanchor='center', y=1.13, yanchor='bottom',
                                  font=dict(size=11), traceorder='normal'),
                      font=dict(color='#3B4458'))
    # 서브플롯 제목을 범례 아래로 내려 겹치지 않게(범례는 플롯 위 가운데)
    for a in fig.layout.annotations:
        if a.text in ('논문 (최근 5년)', '특허 (최근 5년, 출원 기준)'):
            a.update(y=1.0, yanchor='bottom', yshift=4, font=dict(size=12, color='#14213D'))
    fig.update_xaxes(gridcolor='#EEF0F4', zeroline=False)
    return fig


# 하위 호환(이전 이름)
grade_counts = asset_counts
grade_figure = asset_figure
