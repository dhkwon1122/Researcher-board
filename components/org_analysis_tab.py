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

def _section(title: str, hint: str, body) -> html.Div:
    return html.Div([
        html.Div(title, className='fw-semibold mb-1'),
        html.Div(hint, className='text-muted mb-2', style={'fontSize': '0.75rem'}),
        body,
    ], className='mb-4')


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
    title = '부서/과제간 협업 (최근 5년 논문 공저·특허 공동발명)'
    hint = ('같은 논문 공저자 또는 같은 특허 공동발명자인 현재 재직 연구원 쌍을 협업 1건으로 보고, 현재 소속 기준으로 '
            '부서(1단계부서명) 간 / 과제(3단계부서명) 간으로 합산합니다. 최근 5년(올해 포함) 건만, 같은 단위 안의 협업과 '
            '팀/리더 참조 구분이 "Staff"인 조직(하위 조직 포함)과 1단계 부서명이 "SAIT"인 조직은 제외. 순서는 조직코드 순, 노드에 마우스를 올리면 협업 건수. '
            '네트워크 그래프는 선이 굵을수록 협업이 많고, 히트맵은 진할수록 많습니다(마우스 오버로 건수 확인).')
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
    unit = '부서' if level != 'level3' else '과제'
    from services import similarity_map as sm
    # 네트워크 원형 배치·히트맵 X/Y축 순서 = 팀/리더 참조 조직코드(dep_code) 순(드롭다운과 같은 기준)
    order = [o['value'] for o in sm.level_filter_options(3 if level == 'level3' else 1)]
    net = cg.network_figure(pairs, int(top_n or 20), order=order)
    heat = cg.heatmap_figure(pairs, int(top_n or 20), order=order)
    if net is None or heat is None:
        return _empty(f'표시할 {unit} 간 협업이 없습니다(최근 5년, 현재 소속 기준).')
    return dbc.Row([
        dbc.Col([html.Div(f'{unit} 간 협업 네트워크', className='small text-muted mb-1'),
                 dcc.Graph(figure=net, config={'displaylogo': False})], lg=6),
        dbc.Col([html.Div(f'{unit} 간 협업 히트맵', className='small text-muted mb-1'),
                 dcc.Graph(figure=heat, config={'displaylogo': False})], lg=6),
    ], className='g-3')


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


@callback(Output('org-gap-detail', 'children'), Input('org-gap-project', 'value'))
def _gap_detail(project):
    if not project:
        return _empty('위에서 플랫폼 → 그룹 → 과제를 선택하면 그 과제의 필요 역량별 인력 현황이 표시됩니다.')
    item = next((i for i in _gap_items() if i.get('project_name') == project), None)
    if not item:
        return _empty('선택한 과제의 분석 결과가 없습니다.')
    comps = item.get('competencies') or []
    summary = html.Div([
        dbc.Badge(f"필요 역량 {len(comps)}개", color='primary', className='me-1'),
        dbc.Badge(f"과제원 {item.get('member_count', 0)}명(분석 {item.get('analyzed_member_count', 0)}명)",
                  color='secondary', className='me-1'),
        html.Span(item.get('project_name', ''), className='small text-muted ms-1'),
    ], className='mb-2')
    if not comps:
        return html.Div([summary, _empty('이 과제의 필요 역량이 없습니다.')])
    return html.Div([summary, _competency_table(item)])


def competency_gap_section() -> html.Div:
    title = '과제별 필요 역량'
    hint = ('과제 문서에서 LLM이 뽑은 필요 역량과 쉬운 설명, 소속 과제원의 임베딩 유사도, 소속은 아니지만 해당 역량을 가진 '
            '임직원 상위 10명을 보여줍니다. 배지 숫자는 유사도(0~1), 마우스를 올리면 LLM 근거(비과제원은 1·3단계 부서명 포함).')
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
    title = '부서/과제별 논문 등급 (최근 5년)'
    hint = ('현재 재직 연구원의 최근 5년 논문을 등급구분(최우수 > 우수 > 일반 > 외부)별로 세어 부서(1단계부서명) 또는 '
            '과제(3단계부서명) 단위로 비교합니다. 같은 단위의 공저자가 같은 논문을 각자 올린 경우는 1건으로 셉니다. '
            '최우수·우수가 많은 순으로 정렬되며, 표에는 전체 단위가 조직코드 순으로 나옵니다.')
    controls = dbc.Row([
        dbc.Col([dbc.Label('기준', className='small fw-semibold text-muted mb-1'),
                 dbc.RadioItems(id='org-pubgrade-level', value='level1', inline=True,
                                options=[{'label': '부서(1단계부서명)', 'value': 'level1'},
                                         {'label': '과제(3단계부서명)', 'value': 'level3'}])], md=6),
    ], className='g-2 mb-3')
    return _section(title, hint, html.Div([controls, html.Div(id='org-pubgrade-body')]))


@callback(Output('org-pubgrade-body', 'children'), Input('org-pubgrade-level', 'value'))
def _pubgrade_body(level):
    from services import publication_quality as pq
    df = pq.grade_counts(level or 'level1')
    fig = pq.grade_figure(df)
    if fig is None:
        return _empty('표시할 논문 등급 데이터가 없습니다(논문 원천에 "등급구분" 열 반영 후 데이터 업데이트 필요).')
    th = {'textAlign': 'center', 'verticalAlign': 'middle', 'fontWeight': 700, 'color': '#000'}
    table = dbc.Table([
        html.Thead(html.Tr([html.Th(c if c != 'unit' else ('부서' if level != 'level3' else '과제'), style=th)
                            for c in df.columns])),
        html.Tbody([html.Tr([html.Td(v, style={'textAlign': 'left' if i == 0 else 'center'})
                             for i, v in enumerate(r)]) for r in df.itertuples(index=False)]),
    ], bordered=True, size='sm', className='mb-0', style={'fontSize': '0.78rem'})
    return dbc.Row([
        dbc.Col(dcc.Graph(figure=fig, config={'displaylogo': False}), lg=7),
        dbc.Col(html.Div(table, style={'maxHeight': '520px', 'overflowY': 'auto'}), lg=5),
    ], className='g-3')


def org_analysis_content() -> html.Div:
    tabs = [dbc.Tab(competency_gap_section(), label='과제별 필요 역량', tab_id='org-sub-gap'),
            dbc.Tab(collaboration_section(), label='부서/과제간 협업', tab_id='org-sub-collab'),
            dbc.Tab(publication_grade_section(), label='부서별 논문 등급', tab_id='org-sub-pubgrade')]
    return dbc.Tabs(tabs, id='org-sub-tabs', active_tab='org-sub-gap', className='mt-2')
