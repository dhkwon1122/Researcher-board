"""
메일 받는 사람 UI(2026-11-20, 인사발령에서 분리 — 인사발령·업무분장이 각자 명단으로 같은 화면을 쓴다).

- contacts_card(p, store): 부서별 담당자(수신 TO) 표 — 인력현황 검색 + 담당 부서(겸직이면 여러 개)로 추가, 직접 입력(부서·이름·
  이메일 — 비실명·팀 계정 등 검색되지 않는 주소), 빈 행·삭제·엑셀 불러오기·저장.
- cc_block(p, store): 참조(CC)·비밀참조(BCC) — 인력현황 검색 + 직접 입력 주소(값 'mail:주소'), 발송 방식, 저장.
- register(p, store, ...): 위 두 블록의 콜백을 접두어 p로 등록(인사발령 'hro', 업무분장 'wa').
  받는 사람 체크 목록 id는 f'{p}-recipients', 빈 명단 안내는 f'{p}-recipients-hint'(각 페이지가 배치).

store는 load_contacts/save_contacts/recipient_settings/save_recipient_settings를 가진 객체(RecipientStore).
"""
import base64
import io
import re
from dataclasses import dataclass
from typing import Callable

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from services import hr_order_mail as hom

CONTACT_COLUMNS = [
    {'field': 'dept', 'headerName': '부서', 'editable': True, 'checkboxSelection': True, 'headerCheckboxSelection': True,
     'flex': 1},
    {'field': 'name', 'headerName': '담당자', 'editable': True, 'flex': 1},
    {'field': 'email', 'headerName': '이메일', 'editable': True, 'flex': 2},
]


@dataclass
class RecipientStore:
    load_contacts: Callable
    save_contacts: Callable
    recipient_settings: Callable
    save_recipient_settings: Callable


def contact_option(c: dict) -> dict:
    """c는 group_contacts의 묶음(겸직이면 dept = 'A · B') 또는 담당자 행."""
    who = f" · {c['name']}" if c.get('name') else ''
    return {'label': f"{c['dept']}{who} <{c['email']}>", 'value': c['email']}


def recipient_options(contacts: list) -> list:
    """받는 사람 체크 목록 — 겸직 담당자는 한 줄(부서를 · 로 이어서), 값은 이메일."""
    return [contact_option(g) for g in hom.group_contacts(contacts)]


def _mail_option(value: str) -> dict:
    return {'label': f"{value[len(hom.MAIL_PREFIX):]} (직접 입력)", 'value': value}


def cc_options(saved: list) -> list:
    """참조 선택 옵션 — 저장된 직접 입력 주소·인력현황에서 빠진 사람 + 현재 인력현황."""
    opts = hom.person_options()
    have = {o['value'] for o in opts}
    extra = []
    for p in saved:
        rid = p.get('rid')
        if not rid or rid in have:
            continue
        extra.append(_mail_option(rid) if str(rid).startswith(hom.MAIL_PREFIX)
                     else {'label': f"{p.get('name', '')} [{p.get('dept', '')}] ({rid})", 'value': rid})
    return extra + opts


def cc_people(store: RecipientStore, cc, bcc) -> tuple[list, list]:
    """화면의 참조 선택값 → (참조, 비밀참조) 사람 목록(CC와 겹치는 BCC는 뺌)."""
    saved = store.recipient_settings()
    pool = saved['cc'] + saved['bcc']
    cc_p = hom.people_for(cc or [], pool)
    cc_e = {p['email'].lower() for p in cc_p}
    bcc_p = [p for p in hom.people_for(bcc or [], pool) if p['email'].lower() not in cc_e]
    return cc_p, bcc_p


def _split_emails(text: str) -> list:
    return [a for a in re.split(r'[\s,;]+', text or '') if a]


def dept_options(store: RecipientStore) -> list:
    """담당 부서 선택지 — 팀/리더 참조의 1단계 부서명(= 업무분장 플랫폼)과 이미 등록된 부서명."""
    try:
        from services.similarity_map import level_filter_options
        names = [o['value'] for o in level_filter_options(1)]
    except Exception:  # noqa: BLE001 — 조직도가 없어도 화면은 뜨게
        names = []
    for c in store.load_contacts():
        if c.get('dept') and c['dept'] not in names:
            names.append(c['dept'])
    return [{'label': n, 'value': n} for n in names]


# ── 화면 블록 ───────────────────────────────────────────────────────────────

def cc_block(p: str, store: RecipientStore):
    rcp = store.recipient_settings()
    opts = cc_options(rcp['cc'] + rcp['bcc'])
    return html.Div([
        dbc.Row([
            dbc.Col([dbc.Label('참조(CC) — 우리 부서 동료 등', className='small mb-1'),
                     dcc.Dropdown(id=f'{p}-cc', options=opts, value=[x['rid'] for x in rcp['cc'] if x.get('rid')],
                                  multi=True, placeholder='인력현황에서 이름/사번 검색')], md=6),
            dbc.Col([dbc.Label('비밀참조(BCC)', className='small mb-1'),
                     dcc.Dropdown(id=f'{p}-bcc', options=opts, value=[x['rid'] for x in rcp['bcc'] if x.get('rid')],
                                  multi=True, placeholder='필요할 때만')], md=6),
        ], className='g-2 mb-1'),
        html.Div([
            dbc.Input(id=f'{p}-cc-manual', placeholder='검색되지 않는 주소 직접 입력(팀 계정 등, 쉼표로 여러 개)', size='sm',
                      style={'maxWidth': '420px'}, className='me-1'),
            dbc.Button('참조에 추가', id=f'{p}-cc-manual-add', color='secondary', outline=True, size='sm',
                       className='py-0 me-1'),
            dbc.Button('비밀참조에 추가', id=f'{p}-bcc-manual-add', color='secondary', outline=True, size='sm',
                       className='py-0'),
            html.Span(id=f'{p}-cc-manual-msg', className='small ms-2'),
        ], className='d-flex align-items-center flex-wrap mb-2'),
        dbc.Label('발송 방식', className='small mb-0'),
        dbc.RadioItems(id=f'{p}-mode', value=rcp['mode'], className='small', options=[
            {'label': '담당자별 따로 — 부서끼리 주소가 안 보임, 참조인은 담당자 수만큼 받음', 'value': 'each'},
            {'label': '한 통으로 — 담당자 전원을 수신(TO)에 넣어 한 번, 참조인도 한 통만 받음', 'value': 'single'},
        ]),
        html.Div([dbc.Button([html.I(className='bi bi-save me-1'), '참조·발송 방식 저장'], id=f'{p}-rcp-save',
                             color='secondary', outline=True, size='sm', className='py-0'),
                  html.Span('저장하면 다음에도, 자동 발송에도 이 참조인·방식을 씁니다.', className='small text-muted ms-2'),
                  html.Span(id=f'{p}-rcp-msg', className='small ms-2')], className='d-flex align-items-center mt-1'),
    ], className='border rounded p-2 mb-3')


def contacts_card(p: str, store: RecipientStore, title: str = '부서별 담당자', note: str = ''):
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-people me-1'), title], className='fw-semibold')),
        dbc.CardBody([
            html.Div(note, className='small text-muted mb-2') if note else None,
            dbc.Row([
                dbc.Col(dcc.Dropdown(id=f'{p}-person', options=hom.person_options(),
                                     placeholder='인력현황에서 이름·사번 검색(이메일 = Knox ID@samsung.com)'), md=5),
                dbc.Col(dcc.Dropdown(id=f'{p}-person-dept', options=dept_options(store), multi=True,
                                     placeholder='담당 부서(비우면 본인 소속) — 겸직이면 여러 개'), md=5),
                dbc.Col(dbc.Button([html.I(className='bi bi-person-plus me-1'), '담당자로 추가'], id=f'{p}-person-add',
                                   color='primary', outline=True, size='sm'), md=2),
            ], className='g-2 align-items-center mb-1'),
            dbc.Row([
                dbc.Col(dbc.Input(id=f'{p}-manual-dept', placeholder='부서(직접 입력)', size='sm'), md=3),
                dbc.Col(dbc.Input(id=f'{p}-manual-name', placeholder='이름·계정 설명(예: 인사팀 공용)', size='sm'), md=3),
                dbc.Col(dbc.Input(id=f'{p}-manual-email', placeholder='이메일(검색 안 되는 팀 계정 등)', size='sm'), md=4),
                dbc.Col(dbc.Button([html.I(className='bi bi-pencil-square me-1'), '직접 추가'], id=f'{p}-manual-add',
                                   color='primary', outline=True, size='sm'), md=2),
            ], className='g-2 align-items-center mb-1'),
            html.Div('겸직 담당자: 담당 부서를 여러 개 고르거나, 같은 사람을 부서를 바꿔 다시 추가하세요. 같은 이메일은 받는 사람 목록에서 '
                     '한 줄로 합쳐지고 메일도 한 통만 갑니다. 비실명·팀 계정처럼 검색되지 않는 주소는 위 둘째 줄(부서·이름·이메일)에 직접 입력해 추가하세요.',
                     className='small text-muted mb-2'),
            html.Div([
                dbc.Button([html.I(className='bi bi-plus me-1'), '빈 행 추가'], id=f'{p}-row-add', color='secondary',
                           outline=True, size='sm', className='me-1'),
                dbc.Button([html.I(className='bi bi-trash me-1'), '선택 삭제'], id=f'{p}-row-del', color='danger',
                           outline=True, size='sm', className='me-1'),
                dbc.Button([html.I(className='bi bi-save me-1'), '저장'], id=f'{p}-row-save', color='primary', size='sm',
                           className='me-2'),
                dcc.Upload(id=f'{p}-contacts-upload', children=dbc.Button(
                    [html.I(className='bi bi-file-earmark-excel me-1'), '엑셀로 불러오기'], color='success', outline=True,
                    size='sm'), accept='.xlsx,.xls,.csv'),
                html.Span('추가·수정 뒤 저장을 눌러야 반영됩니다(엑셀 열: 부서 · 담당자 · 이메일)', className='small text-muted ms-2'),
            ], className='d-flex align-items-center flex-wrap mb-2'),
            dag.AgGrid(id=f'{p}-contacts', columnDefs=CONTACT_COLUMNS, rowData=store.load_contacts(),
                       dashGridOptions={'rowSelection': 'multiple', 'singleClickEdit': True,
                                        'stopEditingWhenCellsLoseFocus': True},
                       style={'height': '320px'}, className='ag-theme-alpine'),
            html.Div(id=f'{p}-contacts-msg', className='small mt-2'),
        ]),
    ], className='shadow-sm mb-4')


# ── 콜백 ────────────────────────────────────────────────────────────────────

def register(p: str, store: RecipientStore, status_id: str | None = None, status_fn: Callable | None = None,
             empty_hint: str = '아래 "부서별 담당자"에 먼저 등록하세요.') -> None:
    """p 접두어 블록의 콜백 등록. status_id/status_fn을 주면 참조 저장 뒤 그 영역(자동 발송 상태 등)도 다시 그림."""

    rcp_outputs = [Output(f'{p}-rcp-msg', 'children')]
    if status_id:
        rcp_outputs.append(Output(status_id, 'children', allow_duplicate=True))

    @callback(*rcp_outputs, Input(f'{p}-rcp-save', 'n_clicks'), State(f'{p}-cc', 'value'), State(f'{p}-bcc', 'value'),
              State(f'{p}-mode', 'value'), prevent_initial_call=True)
    def _save_rcp(n, cc, bcc, mode):
        extra = [no_update] if status_id else []
        if not n:
            return [no_update] + extra
        try:
            rcp = store.save_recipient_settings(cc or [], bcc or [], mode or 'each')
        except (PermissionError, ValueError) as exc:
            return [html.Span(str(exc), className='text-danger')] + extra
        msg = html.Span(f"저장했습니다(참조 {len(rcp['cc'])}명, 비밀참조 {len(rcp['bcc'])}명).", className='text-success')
        return [msg] + ([status_fn()] if status_id else [])

    @callback(Output(f'{p}-cc', 'options'), Output(f'{p}-cc', 'value'), Output(f'{p}-bcc', 'options'),
              Output(f'{p}-bcc', 'value'), Output(f'{p}-cc-manual', 'value'), Output(f'{p}-cc-manual-msg', 'children'),
              Input(f'{p}-cc-manual-add', 'n_clicks'), Input(f'{p}-bcc-manual-add', 'n_clicks'),
              State(f'{p}-cc-manual', 'value'), State(f'{p}-cc', 'options'), State(f'{p}-cc', 'value'),
              State(f'{p}-bcc', 'value'), prevent_initial_call=True)
    def _add_manual_cc(_c, _b, text, options, cc, bcc):
        addrs = _split_emails(text)
        bad = [a for a in addrs if not hom.is_email(a)]
        if not addrs or bad:
            return (no_update,) * 5 + (html.Span(f"이메일 형식이 아닙니다: {', '.join(bad)}" if bad else
                                                 '추가할 주소를 입력하세요.', className='text-danger'),)
        options = list(options or [])
        have = {o['value'] for o in options}
        values = [hom.MAIL_PREFIX + a for a in addrs]
        options = [_mail_option(v) for v in values if v not in have] + options
        to_cc = ctx.triggered_id == f'{p}-cc-manual-add'
        cc, bcc = list(cc or []), list(bcc or [])
        target = cc if to_cc else bcc
        target += [v for v in values if v not in target]
        return (options, cc, options, bcc, '',
                html.Span(f"{'참조' if to_cc else '비밀참조'}에 {len(values)}개 넣었습니다 — 계속 쓰려면 저장하세요.",
                          className='text-muted'))

    @callback(Output(f'{p}-contacts', 'rowData'), Output(f'{p}-contacts-msg', 'children'),
              Output(f'{p}-manual-email', 'value'),
              Input(f'{p}-row-add', 'n_clicks'), Input(f'{p}-row-del', 'n_clicks'),
              Input(f'{p}-contacts-upload', 'contents'), Input(f'{p}-person-add', 'n_clicks'),
              Input(f'{p}-manual-add', 'n_clicks'),
              State(f'{p}-contacts-upload', 'filename'), State(f'{p}-contacts', 'rowData'),
              State(f'{p}-contacts', 'selectedRows'), State(f'{p}-person', 'value'), State(f'{p}-person-dept', 'value'),
              State(f'{p}-manual-dept', 'value'), State(f'{p}-manual-name', 'value'), State(f'{p}-manual-email', 'value'),
              prevent_initial_call=True)
    def _edit_contacts(_add, _del, content, _padd, _madd, filename, rows, selected, person, person_depts,
                       m_dept, m_name, m_email):
        rows = list(rows or [])
        trig = ctx.triggered_id
        have = {(str(r.get('dept', '')), str(r.get('email', '')).lower()) for r in rows}
        if trig == f'{p}-manual-add':
            dept, name, email = (m_dept or '').strip(), (m_name or '').strip(), (m_email or '').strip()
            if not dept or not hom.is_email(email):
                return no_update, html.Span('부서와 올바른 이메일을 입력하세요.', className='text-warning'), no_update
            if (dept, email.lower()) in have:
                return no_update, html.Span('이미 그 부서에 같은 이메일이 있습니다.', className='text-warning'), no_update
            return (rows + [{'dept': dept, 'name': name, 'email': email}],
                    html.Span(f'{dept} · {email}을 추가했습니다 — 저장을 눌러야 반영됩니다.', className='text-muted'), '')
        if trig == f'{p}-person-add':
            if not person:
                return no_update, html.Span('추가할 사람을 먼저 검색해 고르세요.', className='text-warning'), no_update
            try:
                c = hom.contact_for_person(person)
            except ValueError as exc:
                return no_update, html.Span(str(exc), className='text-danger'), no_update
            depts = [d for d in (person_depts or []) if d] or [c['dept']]       # 겸직: 고른 부서마다 한 행
            new = [{**c, 'dept': d} for d in depts if not (c['email'] and (d, c['email'].lower()) in have)]
            if not new:
                return no_update, html.Span(f"{c['name']}님은 이미 그 부서 담당자로 있습니다.", className='text-warning'), \
                    no_update
            note = '' if c['email'] else ' — Knox ID가 없어 이메일을 직접 입력해야 합니다.'
            return rows + new, html.Span(f"{c['name']}({', '.join(n['dept'] for n in new)})을 추가했습니다{note} — "
                                         f"저장을 눌러야 반영됩니다.", className='text-warning' if note else 'text-muted'), \
                no_update
        if trig == f'{p}-row-add':
            return rows + [{'dept': '', 'name': '', 'email': ''}], '', no_update
        if trig == f'{p}-row-del':
            if not selected:
                return no_update, html.Span('삭제할 행을 체크하세요.', className='text-warning'), no_update
            return ([r for r in rows if r not in selected],
                    html.Span('삭제했습니다 — 저장을 눌러야 반영됩니다.', className='text-muted'), no_update)
        if content:
            try:
                raw = base64.b64decode(content.split(',', 1)[1])
                df = (pd.read_csv(io.BytesIO(raw)) if (filename or '').lower().endswith('.csv')
                      else pd.read_excel(io.BytesIO(raw)))
                new = hom.contacts_from_table(df)
            except Exception as exc:  # noqa: BLE001
                return no_update, html.Span(f'불러오지 못했습니다: {exc}', className='text-danger'), no_update
            return new, html.Span(f'{len(new)}행을 불러왔습니다 — 확인 후 저장을 누르세요.', className='text-muted'), no_update
        return no_update, no_update, no_update

    @callback(Output(f'{p}-contacts-msg', 'children', allow_duplicate=True), Output(f'{p}-recipients', 'options'),
              Output(f'{p}-recipients-hint', 'children'),
              Input(f'{p}-row-save', 'n_clicks'), State(f'{p}-contacts', 'rowData'), prevent_initial_call=True)
    def _save_contacts(n, rows):
        if not n:
            return no_update, no_update, no_update
        try:
            saved, errors = store.save_contacts(rows)
        except PermissionError as exc:
            return html.Span(str(exc), className='text-danger'), no_update, no_update
        if errors:
            return html.Div([html.Div(e, className='text-danger') for e in errors]), no_update, no_update
        return (html.Span(f'{len(saved)}명 저장했습니다.', className='text-success'),
                recipient_options(saved), '' if saved else empty_hint)
