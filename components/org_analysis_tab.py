"""
"보유 전문성" 페이지의 "조직 분석" 탭(2026-10, 전문성 심화 지표 ③④⑤).

pipeline/process_expertise_metrics.py 등이 만든 조직 단위 집계 산출물을
보여준다. 산출물이 없으면(파이프라인 미실행) 섹션마다 안내 문구만 표시한다.

  - 부서/과제간 협업(collaboration_edges.csv) — 최근 5년·현재 소속 기준 1단계/3단계부서명 간
    협업을 네트워크 그래프 + 히트맵으로(services/collab_graph.py). 모든 로그인 사용자.
  - 과제별 필요 역량(project_competency_gap.json) — 플랫폼/그룹/과제 캐스케이딩으로 과제를 고르면
    필요 역량별 소속 과제원과 비소속 적합 임직원. 분석 결과가 없는 과제 목록(사유)도 함께. 모든 로그인 사용자.
  - (2026-10-13) "기술별 보유자 수" 하위 탭은 사용자 확정으로 삭제(표기만 다른 같은 기술 통합이
    기대만큼 개선되지 않음). 집계 파일 technology_holder_summary.csv는 계속 생성된다.
"""

import dash_bootstrap_components as dbc
from dash import Input, Output, callback, dcc, html

from services.data_store import read_processed, read_project_competency_gap

def _section(title: str, hint, body) -> html.Div:
    """hint가 리스트면 개조식(글머리 목록)으로 보여준다(2026-10-15, 탭 설명 개조식화).
    hint가 None이면 설명 없이 제목만(2026-10-15 사용자 확정 — 하위 탭 설명 전부 제외)."""
    if not hint:
        return html.Div([html.Div(title, className='fw-semibold mb-2'), body], className='mb-4')
    hint_el = (html.Ul([html.Li(h) for h in hint], className='text-muted mb-2 ps-3', style={'fontSize': '0.75rem'})
               if isinstance(hint, (list, tuple)) else
               html.Div(hint, className='text-muted mb-2', style={'fontSize': '0.75rem'}))
    return html.Div([html.Div(title, className='fw-semibold mb-1'), hint_el, body], className='mb-4')


def _empty(msg: str) -> html.Div:
    return html.Div(msg, className='text-muted small p-2 border rounded bg-light')


def _name_map() -> dict:
    df = read_processed('researchers')
    if df.empty or 'name' not in df.columns:
        return {}
    return dict(zip(df['researcher_id'], df['name'].astype(str)))


def _names(ids: str, name_map: dict) -> str:
    return ', '.join(name_map.get(x.zfill(8), x) for x in str(ids or '').split(';') if x)


def collaboration_section() -> html.Div:
    title = '협업(플랫폼/과제) — 최근 5년 논문 공저·특허 공동발명'
    hint = None   # 하위 탭 설명 제외(2026-10-15 사용자 확정)
    edges = read_processed('collaboration_edges')
    if edges.empty:
        return _section(title, hint, _empty('데이터 없음 — pipeline/run_analysis.py(4/4 전문성 심화 지표) 실행 후 표시됩니다.'))
    if not {'recent_count', 'level1_a', 'level3_a'} <= set(edges.columns):
        return _section(title, hint, _empty('협업 데이터가 구버전입니다 — pipeline/run_analysis.py(4/4 전문성 심화 지표)를 '
                                            '다시 실행한 뒤 DB 반영하면 표시됩니다.'))
    controls = dbc.Row([
        dbc.Col([dbc.Label('기준', className='small fw-semibold text-muted mb-1'),
                 dbc.RadioItems(id='org-collab-level', value='level1', inline=True,
                                options=[{'label': '부서(1단계부서명)', 'value': 'level1'},
                                         {'label': '과제(3단계부서명)', 'value': 'level3'}])], md=6),
        dbc.Col([dbc.Label('표시 단위 수(협업량 상위)', className='small fw-semibold text-muted mb-1'),
                 dcc.Dropdown(id='org-collab-topn', value=20, clearable=False,
                              options=[{'label': f'상위 {n}개', 'value': n} for n in (10, 20, 30, 50)])], md=3),
    ], className='g-2 mb-3')
    return _section(title, hint, html.Div([controls, html.Div(id='org-collab-body')]))


@callback(Output('org-collab-body', 'children'),
          Input('org-collab-level', 'value'), Input('org-collab-topn', 'value'))
def _collab_body(level, top_n):
    from services import collab_graph as cg

    edges = read_processed('collaboration_edges')
    pairs = cg.aggregate(edges, level or 'level1')
    if level == 'level3':   # 구성원 1명인 과제는 제외(2026-10-15 — 조직 특성상 1인 과제가 있음)
        from services.org_units import unit_sizes
        sizes = unit_sizes('level3')
        pairs = {k: v for k, v in pairs.items() if sizes.get(k[0], 0) > 1 and sizes.get(k[1], 0) > 1}
    unit = '부서' if level != 'level3' else '과제'
    from services import similarity_map as sm
    # 네트워크 원형 배치·히트맵 X/Y축 순서 = 팀/리더 참조 조직코드(dep_code) 순(드롭다운과 같은 기준)
    order = [o['value'] for o in sm.level_filter_options(3 if level == 'level3' else 1)]
    # 과제 기준이면 과제→1단계부서명으로 묶어 부서 색 계열 + 바깥 부서 띠(2026-10-14)
    group_of = sm.level1_of_level3() if level == 'level3' else None
    net = cg.network_figure(pairs, int(top_n or 20), order=order, group_of=group_of)
    heat = cg.heatmap_figure(pairs, int(top_n or 20), order=order, group_of=group_of)
    if net is None or heat is None:
        return _empty(f'표시할 {unit} 간 협업이 없습니다(최근 5년, 현재 소속 기준).')
    graphs = dbc.Row([
        dbc.Col([html.Div(f'{unit} 간 협업 네트워크', className='small text-muted mb-1'),
                 dcc.Graph(figure=net, config={'displaylogo': False})], lg=6),
        dbc.Col([html.Div(f'{unit} 간 협업 히트맵', className='small text-muted mb-1'),
                 dcc.Graph(figure=heat, config={'displaylogo': False})], lg=6),
    ], className='g-3')
    return html.Div([graphs, _collab_summary_card(level or 'level1')])


def _pair_line(r: dict, extra: str = '') -> str:
    kinds = ' · '.join(x for x in (f"논문 {r['papers']}" if r.get('papers') else '',
                                   f"특허 {r['patents']}" if r.get('patents') else '') if x)
    return f"{r['a']} ↔ {r['b']} ({kinds or str(r.get('total', 0)) + '건'}{extra})"


def _collab_summary_card(level: str):
    """AI 협업 요약(pipeline/process_collab_summary.py 산출물, 2026-10-14). 없으면 안내만."""
    from services.data_store import read_collab_summary
    s = read_collab_summary().get(level)
    unit = '부서' if level != 'level3' else '과제'
    if not s:
        return html.Div(_empty('AI 협업 요약이 아직 없습니다 — 분석 실행(run_integration) 후 표시됩니다.'), className='mt-3')
    li = lambda items: html.Ul([html.Li(x) for x in items], className='mb-2 ps-3')  # noqa: E731
    top = []
    for r in s.get('top_pairs') or []:
        grade = f", 최우수·우수 {r['top_grade']}" if r.get('top_grade') else ''
        names = '·'.join(r.get('people') or [])
        if r.get('people_more'):
            names += f" 외 {r['people_more']}명"
        top.append(html.Li([
            html.Span(_pair_line(r, grade), className='fw-semibold'),
            html.Span(f" — 주제: {', '.join(r['topics'])}" if r.get('topics') else ''),
            html.Span(f' / 참여: {names}' if names else '', className='text-muted'),
        ]))
    facts = []
    if s.get('hubs'):
        facts.append('허브 ' + unit + ': ' + ', '.join(f"{h['unit']}(상대 {h['partners']}곳·{h['docs']}건)" for h in s['hubs']))
    if s.get('low'):
        facts.append(f'협업이 적은 {unit}: ' + ', '.join(s['low']))
    if s.get('new_pairs'):
        facts.append('최근 2년 새로 생긴 협업: ' + ', '.join(f"{r['a']} ↔ {r['b']}" for r in s['new_pairs']))
    if s.get('rising'):
        facts.append('최근 늘어난 협업: ' + ', '.join(f"{r['a']} ↔ {r['b']}(최근2년 {r['recent']}·이전3년 {r['prior']})"
                                               for r in s['rising']))
    if s.get('falling'):
        facts.append('최근 줄어든 협업: ' + ', '.join(f"{r['a']} ↔ {r['b']}(최근2년 {r['recent']}·이전3년 {r['prior']})"
                                               for r in s['falling']))
    facts.append(f"협업 유형: 논문 {s.get('papers', 0)}건 · 특허 {s.get('patents', 0)}건 "
                 f"({'논문' if s.get('papers', 0) >= s.get('patents', 0) else '특허'} 중심)")
    if s.get('top_grade_pairs'):
        facts.append('최우수·우수 논문 공동 성과: ' + ', '.join(f"{r['a']} ↔ {r['b']}({r['top_grade']}편)"
                                                    for r in s['top_grade_pairs']))
    head = html.Div([
        html.I(className='bi bi-stars me-1 text-primary'),
        html.Span(f'AI 협업 요약 — {unit} 기준', className='fw-semibold'),
        html.Span(f" (최근 5년 {s.get('period', '')}, 생성 {s.get('generated_at', '')}"
                  + ('' if s.get('llm') else ', AI 응답 없어 통계 기반') + ')', className='text-muted small ms-1'),
    ], className='mb-2')
    return dbc.Card(dbc.CardBody([
        head,
        html.Div('총평', className='small fw-semibold text-muted'), li(s.get('overview') or []),
        html.Div(f'협업 상위 {unit} 쌍', className='small fw-semibold text-muted'),
        html.Ul(top, className='mb-2 ps-3') if top else _empty('협업 쌍 없음'),
        html.Div('세부 현황', className='small fw-semibold text-muted'), li(facts),
        html.Div('건수는 서로 다른 논문·특허 수 기준(위 그래프는 연구원 쌍 기준이라 숫자가 다를 수 있음). '
                 'AI에는 이름 없이 부서/과제명·제목·건수만 전달되며, 참여자 이름은 데이터에서 직접 표시합니다.',
                 className='text-muted', style={'fontSize': '0.7rem'}),
    ], style={'fontSize': '0.8rem'}), className='mt-3 shadow-sm')


# ── 과제별 역량(2026-10-08 개편) ────────────────────────────────────────────────
# 플랫폼(1단계부서명) → 그룹(2단계부서명) → 과제(3단계부서명) 캐스케이딩으로 과제를 고르면,
# 그 과제의 필요 역량을 행별로 보여주고 역량마다 (a) 소속 과제원을 임베딩 유사도 구간
# (0~0.25/0.25~0.5/0.5~0.75/0.75~1)별로, (b) 비소속이지만 전문성이 맞는 임직원
# (0.75 이상, 없으면 0.75 미만 대표 최대 5명)을 보여준다. 데이터는
# pipeline/process_project_competency_gap.py 산출물(project_competency_gap.json).

_NO_LEVEL = '(미분류)'


def _lv(it: dict, key: str) -> str:
    return str(it.get(key) or '').strip() or _NO_LEVEL


def _opts(values) -> list:
    return [{'label': v, 'value': v} for v in sorted(set(values))]


def _gap_items() -> list:
    return read_project_competency_gap() or []


def _org_map() -> dict:
    df = read_processed('researchers')
    if df.empty or 'org_code' not in df.columns:
        return {}
    return dict(zip(df['researcher_id'], df['org_code'].astype(str)))


def _evidence_text(x: dict) -> str:
    reason = str(x.get('reason') or '').strip()
    items = '; '.join(f"{t.get('item', '')}({float(t.get('score', 0)):.2f})" for t in x.get('top_items') or []) \
        or str(x.get('item') or '')
    lines = []
    if reason:   # 개조식 항목(줄바꿈 구분, 2026-10-14)
        lines.append('근거:\n' + '\n'.join(f'· {r}' for r in reason.split('\n') if r.strip()))
    lines.append(f'가까운 보유 항목: {items}' if items else '')
    return '\n'.join(l for l in lines if l)


def _person_badge(x: dict, name_map: dict, color: str, org_map: dict | None = None) -> html.Span:
    """배지 = 이름 + 임베딩 유사도. 마우스 오버: (비과제원이면 1단계/3단계 부서명) + LLM 근거 + 가까운 보유 항목."""
    rid = x.get('researcher_id', '')
    tip = _evidence_text(x)
    if org_map is not None:
        from services import similarity_map as sm
        l1, _l2, l3 = sm.org_code_level_names(org_map.get(rid, ''))
        tip = f"1단계부서: {l1 or '-'}\n3단계부서: {l3 or '-'}\n" + tip
    return dbc.Badge(f"{name_map.get(rid, rid)} {float(x.get('score', 0)):.2f}", color=color, className='me-1 mb-1',
                     title=tip, text_color='dark' if color == 'warning' else None, style={'cursor': 'help'})


def _score_color(score: float) -> str:
    return 'success' if score >= 0.75 else 'primary' if score >= 0.5 else 'warning' if score >= 0.25 else 'secondary'


def _bullet_list(text):
    """개조식 설명(줄바꿈 구분)을 글머리 목록으로. 예전 서술형(한 줄)은 그 한 줄을 그대로 한 항목으로."""
    lines = [ln.strip() for ln in str(text or '').split('\n') if ln.strip()]
    if not lines:
        return None
    return html.Ul([html.Li(ln) for ln in lines], className='mb-0 ps-3')


def _competency_table(item: dict) -> html.Div:
    name_map, org_map = _name_map(), _org_map()
    rows = []
    for c in item.get('competencies') or []:
        members = c.get('members')
        if members is None:   # 구버전 산출물(재실행 전) — 충족 인력만 있음
            members = c.get('covered_by') or []
        outsiders = c.get('outsiders')
        if outsiders is None:
            outsiders = c.get('candidates') or []
        mem_cell = html.Td([_person_badge(m, name_map, _score_color(float(m.get('score', 0)))) for m in members]
                           or html.Span('-', className='text-muted'), style={'verticalAlign': 'top'})
        out_cell = html.Td([_person_badge(x, name_map, _score_color(float(x.get('score', 0))), org_map)
                            for x in outsiders] or html.Span('-', className='text-muted'),
                           style={'verticalAlign': 'top'})
        rows.append(html.Tr([
            html.Td(html.Div(c.get('competency', ''), className='fw-semibold'), style={'verticalAlign': 'top'}),
            html.Td(_bullet_list(c.get('description'))
                    or html.Span('(설명 없음 — 분석 재실행 필요)', className='text-muted'),
                    style={'verticalAlign': 'top'}),
            mem_cell, out_cell,
        ]))
    # 헤더: 셀(0.78rem)보다 크게, 검정 볼드, 가로·세로 가운데(2026-10-14)
    th = {'fontSize': '0.86rem', 'fontWeight': 700, 'color': '#000', 'textAlign': 'center',
          'verticalAlign': 'middle'}
    head = html.Thead(html.Tr([
        html.Th('필요 역량', style={**th, 'width': '15%'}),
        html.Th('설명', style={**th, 'width': '25%'}),
        html.Th([html.Div('과제원 맵핑'), html.Div('(이름 + 임베딩 유사도)', style={'fontSize': '0.78rem'})],
                style={**th, 'width': '30%'}),
        html.Th([html.Div('비과제원 맵핑(상위 10명)'), html.Div('(이름 + 임베딩 유사도)', style={'fontSize': '0.78rem'})],
                style={**th, 'width': '30%'}),
    ]))
    return dbc.Table([head, html.Tbody(rows)], bordered=True, size='sm', className='mb-0 align-middle',
                     style={'fontSize': '0.78rem', 'tableLayout': 'fixed'})


def _norm_name(text: str) -> str:
    """과제명/조직명 비교용: 대괄호 꼬리표([연구] 등)·공백 제거, 소문자."""
    import re
    return re.sub(r'\[[^\]]*\]|\s+', '', str(text or '')).lower()


def _project_matches(l1, l2) -> tuple:
    """(선택된 단계의 조직 코드 집합, 비교용 이름 집합) — 선택이 없으면 (None, None).
    이름 집합에는 팀/리더 참조의 비공식소속부서명(org_name_wd)과 3단계부서명을 모두 넣는다
    (2026-10-13: 과제명이 3단계부서명과는 같지만 비공식소속부서명과 표기가 달라 목록에서 빠지던 문제)."""
    from services import similarity_map as sm
    rows = sm.org_rows_for_levels(l1, l2, None)
    if rows is None:
        return None, None
    codes = {(r.get('org_name_wd') or '').strip() for r in rows}
    names = {_norm_name(r.get('org_name_wd')) for r in rows} | {_norm_name(r.get('dep_3rd_name')) for r in rows}
    return codes, names - {''}


def _item_in_levels(item: dict, codes: set, names: set, org_map: dict) -> bool:
    """과제명이 선택 조직의 이름과 같거나, 분석된 과제원 과반이 선택 조직 소속이면 포함."""
    if _norm_name(item.get('project_name')) in names:
        return True
    # 과제별컨플의 비공식소속부서명(있으면 org_code로 저장됨)이 선택 조직이면 포함(2026-10-13)
    if item.get('org_code') and (item['org_code'] in codes or _norm_name(item['org_code']) in names):
        return True
    rids = {m.get('researcher_id') for c in item.get('competencies') or [] for m in c.get('members') or []}
    rids.discard(None)
    if not rids:
        return False
    inside = sum(1 for r in rids if org_map.get(r, '') in codes)
    return inside * 2 >= len(rids)


def _project_options(l1, l2) -> list:
    """플랫폼/그룹 선택에 속하는 과제 옵션(연구원 프로필·명단과 같은 팀/리더 참조 1/2단계 기준).
    아무것도 선택하지 않으면 전체(팀/리더 참조에 없는 과제 포함)."""
    items = _gap_items()
    codes, names = _project_matches(l1, l2)
    if codes is not None:
        org_map = _org_map()
        items = [i for i in items if _item_in_levels(i, codes, names, org_map)]
    return sorted(({'label': i.get('project_name', ''), 'value': i.get('project_name', '')} for i in items),
                  key=lambda o: o['label'])


def _missing_projects(l1, l2) -> list:
    """과제별컨플에 등록됐지만 과제별 필요 역량 결과가 없는 과제 [(과제명, 소속, 사유)].
    플랫폼/그룹을 고르면 이름이 그 조직과 맞는 과제만."""
    from services.data_store import read_project_expertise_analysis
    from pipeline.researcher_fit import current_rows
    confl = current_rows(read_processed('project_confl_address'))
    if confl.empty or 'project_name' not in confl.columns:
        return []
    have = {i.get('project_name', '') for i in _gap_items()}
    analyzed = {i.get('project_name', '') for i in (read_project_expertise_analysis() or [])}
    _codes, names = _project_matches(l1, l2)
    out, seen = [], set()
    for r in confl.fillna('').to_dict('records'):
        name = str(r.get('project_name', '')).strip()
        if not name or name in have or name in seen:
            continue
        if names is not None and _norm_name(name) not in names:
            continue
        seen.add(name)
        reason = ('필요 역량 추출 실패 또는 문서 내용 부족(과제 문서 분석은 됨)' if name in analyzed
                  else '과제 문서 분석 실패(Confluence/PDF 원문 조회 또는 요약 실패)')
        out.append((name, str(r.get('dep_name', '')).strip(), reason))
    return sorted(out)


def _missing_block(l1, l2):
    rows = _missing_projects(l1, l2)
    if not rows:
        return html.Div()
    return html.Details([
        html.Summary(f'분석 결과가 없는 과제 {len(rows)}건', className='small fw-semibold text-muted',
                     style={'cursor': 'pointer'}),
        dbc.Table([html.Thead(html.Tr([html.Th('과제'), html.Th('소속'), html.Th('사유')])),
                   html.Tbody([html.Tr([html.Td(n), html.Td(d), html.Td(why)]) for n, d, why in rows])],
                  bordered=True, size='sm', className='mt-2 mb-0', style={'fontSize': '0.75rem'}),
        html.Div('다음 run_integration.py 실행 때 다시 시도됩니다. 계속 실패하면 실행 로그에서 해당 과제명을 확인하세요.',
                 className='text-muted mt-1', style={'fontSize': '0.7rem'}),
    ], className='mb-3')


@callback(Output('org-gap-l2', 'options'), Output('org-gap-l2', 'value'),
          Input('org-gap-l1', 'value'))
def _gap_l2_options(l1):
    from services import similarity_map as sm
    return sm.level_filter_options(2, {1: l1} if l1 else None), None


@callback(Output('org-gap-project', 'options'), Output('org-gap-project', 'value'),
          Output('org-gap-missing', 'children'),
          Input('org-gap-l1', 'value'), Input('org-gap-l2', 'value'))
def _gap_project_options(l1, l2):
    return _project_options(l1, l2), None, _missing_block(l1, l2)


def _overview_card(item: dict) -> html.Div:
    """과제 개요(2026-10-15): 과제 목표·마일스톤·주요 업무(과제 문서 요약을 LLM으로 개조식 압축) +
    인력현황(researchers.csv 최신 시점, 휴직 제외 — 과제별컨플 담당자는 쓰지 않음)."""
    from services.project_staffing import project_staffing
    ov = item.get('overview') or {}

    def _block(label, lines):
        lines = [str(x).strip() for x in lines or [] if str(x).strip()]
        body = (html.Ul([html.Li(x) for x in lines], className='mb-0 ps-3') if lines
                else html.Div('(문서 근거 없음 — 분석 재실행 시 생성)', className='text-muted'))
        return html.Div([html.Div(label, className='fw-semibold mb-1', style={'color': '#14213D'}), body],
                        className='mb-2')

    st = project_staffing(item.get('project_name', ''))
    if st['total']:
        def _chips(pairs):
            return [dbc.Badge(f'{k} · {v}명', color='light', text_color='dark', className='me-1 mb-1 border')
                    for k, v in pairs]
        staff = html.Ul([
            html.Li([html.B(f"총 {st['total']}명"), html.Span(' (최신 인력현황 기준, 휴직자 제외)', className='text-muted')]),
            html.Li(['CL별 ', *_chips(st['by_cl'])]),
            html.Li(['직무별 ', *_chips(st['by_job'])]),
            html.Li(f"학위: 박사 {st['doctor']}명 · 석사 {st['master']}명"),
        ], className='mb-0 ps-3')
    else:
        staff = html.Div('최신 인력현황(researchers.csv)에서 이 과제 소속 인원을 찾지 못했습니다.', className='text-muted')
    staff_block = html.Div([html.Div('인력현황', className='fw-semibold mb-1', style={'color': '#14213D'}), staff],
                           className='mb-2')
    return html.Div([
        html.Div('과제 개요', className='fw-bold mb-2', style={'fontSize': '0.9rem'}),
        dbc.Row([
            dbc.Col([_block('과제 목표', ov.get('goals')), _block('주요 업무', ov.get('tasks'))], md=6),
            dbc.Col([_block('과제 마일스톤', ov.get('milestones')), staff_block], md=6),
        ]),
    ], className='border rounded p-3 mb-3', style={'fontSize': '0.8rem', 'background': '#F8FAFD'})


@callback(Output('org-gap-detail', 'children'), Input('org-gap-project', 'value'))
def _gap_detail(project):
    if not project:
        return _empty('위에서 플랫폼 → 그룹 → 과제를 선택하면 그 과제의 필요 역량별 인력 현황이 표시됩니다.')
    item = next((i for i in _gap_items() if i.get('project_name') == project), None)
    if not item:
        return _empty('선택한 과제의 분석 결과가 없습니다.')
    comps = item.get('competencies') or []
    overview = _overview_card(item)
    summary = html.Div([
        dbc.Badge(f"필요 역량 {len(comps)}개", color='primary', className='me-1'),
        dbc.Badge(f"과제원 {item.get('member_count', 0)}명(분석 {item.get('analyzed_member_count', 0)}명)",
                  color='secondary', className='me-1'),
        html.Span(item.get('project_name', ''), className='small text-muted ms-1'),
    ], className='mb-2')
    if not comps:
        return html.Div([overview, summary, _empty('이 과제의 필요 역량이 없습니다.')])
    return html.Div([overview, summary, _competency_table(item)])


def competency_gap_section() -> html.Div:
    title = '필요 역량(과제)'
    hint = None   # 하위 탭 설명 제외(2026-10-15 사용자 확정)
    items = _gap_items()
    if not items:
        return _section(title, hint, _empty('데이터 없음 — pipeline/run_analysis.py(5/5 과제별 역량 갭) 실행 후 표시됩니다.'))
    from services import similarity_map as sm
    drop = lambda id_, label, opts: dbc.Col([
        dbc.Label(label, className='small fw-semibold text-muted mb-1'),
        dcc.Dropdown(id=id_, options=opts, placeholder='전체' if id_ != 'org-gap-project' else '과제 선택', clearable=True),
    ], md=4)
    controls = dbc.Row([
        drop('org-gap-l1', '플랫폼', sm.level_filter_options(1)),
        drop('org-gap-l2', '그룹', sm.level_filter_options(2)),
        drop('org-gap-project', '과제', _project_options(None, None)),
    ], className='g-2 mb-3')
    return _section(title, hint, html.Div([controls, html.Div(_missing_block(None, None), id='org-gap-missing'),
                                           html.Div(id='org-gap-detail')]))


# ── 부서별 논문 등급(2026-10-14) ──────────────────────────────────────────────

def publication_grade_section() -> html.Div:
    title = '논문,특허(플랫폼/과제) — 최근 5년 자산화 현황'
    hint = None   # 하위 탭 설명 제외(2026-10-15 사용자 확정)
    from services import publication_quality as pq
    controls = dbc.Row([
        dbc.Col([dbc.Label('기준', className='small fw-semibold text-muted mb-1'),
                 dbc.RadioItems(id='org-pubgrade-level', value='level1', inline=True,
                                options=[{'label': '부서(1단계부서명)', 'value': 'level1'},
                                         {'label': '과제(3단계부서명)', 'value': 'level3'}])], md=5),
        dbc.Col([dbc.Label('플랫폼', className='small fw-semibold text-muted mb-1'),
                 dcc.Dropdown(id='org-pubgrade-l1', multi=True, placeholder='전체',
                              options=[{'label': d, 'value': d} for d in pq.dept_order()])], md=7),
    ], className='g-2 mb-3')
    return _section(title, hint, html.Div([controls, html.Div(id='org-pubgrade-body')]))


@callback(Output('org-pubgrade-body', 'children'),
          Input('org-pubgrade-level', 'value'), Input('org-pubgrade-l1', 'value'))
def _pubgrade_body(level, platforms):
    from services import publication_quality as pq
    level = level or 'level1'
    df = pq.asset_counts(level, platforms=platforms or None)
    fig = pq.asset_figure(df)
    if fig is None:
        return _empty('표시할 논문·특허 데이터가 없습니다(최근 5년, 제외 조직 반영 후).')
    th = {'textAlign': 'center', 'verticalAlign': 'middle', 'fontWeight': 700, 'color': '#000'}
    unit = '부서' if level != 'level3' else '과제'
    cols = [c for c in df.columns if c != 'dept']
    lead = [html.Th('부서', rowSpan=2, style=th)] if level == 'level3' else []
    groups = html.Tr(lead + [html.Th(unit, rowSpan=2, style=th),
                             html.Th('논문', colSpan=len(pq.PAPER_GRADES) + 1, style={**th, 'background': '#FBEDE3'}),
                             html.Th('특허', colSpan=len(pq.PATENT_GRADES) + 1, style={**th, 'background': '#EFE8FA'})])
    sub = html.Tr([html.Th(c.split('_', 1)[1], style=th) for c in cols[1:]])
    colors = pq.dept_color_map()
    rows = []
    for r in df.to_dict('records'):
        dept = r.get('dept') or r['unit']
        dot = html.Span('■ ', style={'color': colors.get(dept, '#999')})
        cells = [html.Td([dot, dept], style={'textAlign': 'left', 'whiteSpace': 'nowrap'})] if level == 'level3' else []
        cells.append(html.Td(([dot] if level != 'level3' else []) + [r['unit']], style={'textAlign': 'left'}))
        cells += [html.Td(r[c], style={'textAlign': 'center', 'fontWeight': 600 if c.endswith('_계') else None})
                  for c in cols[1:]]
        rows.append(html.Tr(cells))
    table = dbc.Table([html.Thead([groups, sub]), html.Tbody(rows)],
                      bordered=True, size='sm', className='mb-0', style={'fontSize': '0.76rem'})
    return html.Div([
        dcc.Graph(figure=fig, config={'displaylogo': False}),
        html.Div(table, style={'maxHeight': '420px', 'overflowY': 'auto'}, className='mt-2'),
    ])


def org_analysis_content() -> html.Div:
    # 탭 이름(2026-10-15 사용자 확정): 필요 역량(과제) / 협업(플랫폼/과제) / 논문,특허(플랫폼/과제)
    tabs = [dbc.Tab(competency_gap_section(), label='필요 역량(과제)', tab_id='org-sub-gap'),
            dbc.Tab(collaboration_section(), label='협업(플랫폼/과제)', tab_id='org-sub-collab'),
            dbc.Tab(publication_grade_section(), label='논문,특허(플랫폼/과제)', tab_id='org-sub-pubgrade')]
    return dbc.Tabs(tabs, id='org-sub-tabs', active_tab='org-sub-gap', className='mt-2')
