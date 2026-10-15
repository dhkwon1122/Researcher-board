"""플랫폼/과제별 자산화 현황(논문·특허) — 보유 전문성 > 조직(플랫폼/과제) > "논문,특허(플랫폼/과제)" 탭.

2026-10-14 최초(논문 등급만) → 2026-10-15 특허 등급 추가·제외 조직 반영:
  - 대상: 현재 재직 연구원, Staff 조직(하위 포함)·1단계 SAIT/Ideation Factory T/F(SAIT) 제외(services/org_units)
  - 기간: 최근 5년(논문 실적일·특허 출원일 기준)
  - 논문 등급: 최우수 > 우수 > 일반 > 외부(등급구분). 같은 단위 공저는 제목 기준 1건.
  - 특허 등급: 전략("현재등급 - A급구분"이 전략출원) > A1 > A2 > 기타(그 외·빈 값, 현재등급 기준).
    같은 특허(여러 나라 출원 포함)는 출원ID 기준 1건, 같은 단위 공동발명도 1건.
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


def asset_counts(level: str = 'level1', years: int = RECENT_YEARS) -> pd.DataFrame:
    """단위별 건수표. 열: unit, 논문_최우수 … 논문_계, 특허_전략 … 특허_계. 행 순서 = 조직코드 순."""
    from services import similarity_map as sm
    from services.org_units import unit_members
    unit_by_rid = unit_members(level)
    cols = ['unit'] + [f'논문_{g}' for g in PAPER_GRADES] + ['논문_계'] + [f'특허_{g}' for g in PATENT_GRADES] + ['특허_계']
    if not unit_by_rid:
        return pd.DataFrame(columns=cols)
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
        return pd.DataFrame(columns=cols)
    for c in counts.values():
        c['논문_계'] = sum(c[f'논문_{g}'] for g in PAPER_GRADES)
        c['특허_계'] = sum(c[f'특허_{g}'] for g in PATENT_GRADES)
    order = [o['value'] for o in sm.level_filter_options(1 if level == 'level1' else 3)]
    pos = {n: i for i, n in enumerate(order)}
    rows = [{'unit': u, **c} for u, c in sorted(counts.items(), key=lambda kv: (pos.get(kv[0], len(pos)), kv[0]))]
    return pd.DataFrame(rows, columns=cols)


def asset_figure(df: pd.DataFrame, top_n: int = 30):
    """논문·특허 등급별 누적 가로 막대 2개(같은 단위 순서). 범례는 위쪽 가운데, 막대와 겹치지 않게. 비어 있으면 None."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    if df is None or df.empty:
        return None
    key = df['논문_최우수'] * 1000 + df['논문_우수'] * 100 + df['특허_전략'] * 10 + df['특허_A1']
    df = df.assign(_k=key, _t=df['논문_계'] + df['특허_계']).sort_values(['_k', '_t'], ascending=False).head(top_n)
    df = df.iloc[::-1]   # 가로 막대는 아래부터 그려지므로 1위가 맨 위
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.04,
                        subplot_titles=('논문 (최근 5년)', '특허 (최근 5년, 출원 기준)'))
    for g in PAPER_GRADES:
        fig.add_bar(y=df['unit'], x=df[f'논문_{g}'], name=f'논문 {g}', orientation='h', row=1, col=1,
                    marker=dict(color=PAPER_COLORS[g], line=dict(color='#FFFFFF', width=1)),
                    hovertemplate='%{y}<br>논문 ' + g + ' %{x}건<extra></extra>')
    for g in PATENT_GRADES:
        fig.add_bar(y=df['unit'], x=df[f'특허_{g}'], name=f'특허 {g}', orientation='h', row=1, col=2,
                    marker=dict(color=PATENT_COLORS[g], line=dict(color='#FFFFFF', width=1)),
                    hovertemplate='%{y}<br>특허 ' + g + ' %{x}건<extra></extra>')
    fig.update_layout(barmode='stack', height=max(320, 28 * len(df) + 150), plot_bgcolor='#FFFFFF',
                      margin=dict(l=10, r=10, t=110, b=30),
                      legend=dict(orientation='h', x=0.5, xanchor='center', y=1.0, yanchor='bottom',
                                  font=dict(size=11), traceorder='normal'),
                      font=dict(color='#3B4458'))
    # 서브플롯 제목을 범례 아래로 내려 겹치지 않게(범례는 플롯 위 가운데)
    for a in fig.layout.annotations:
        a.update(y=1.0, yanchor='bottom', yshift=4, font=dict(size=12, color='#14213D'))
    fig.update_layout(legend=dict(y=1.13))
    fig.update_xaxes(gridcolor='#EEF0F4', zeroline=False)
    fig.update_yaxes(automargin=True)
    return fig


# 하위 호환(이전 이름)
grade_counts = asset_counts
grade_figure = asset_figure
