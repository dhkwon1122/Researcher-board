"""
업무 시나리오 > 업무분장(2026-11-20) — 매월 업무분장표 작성 양식을 부서별 담당자에게 메일로 보내고(수동·자동),
회신받은 업무분장표를 올려 부서별 제출 현황과 통합표로 관리한다. 받는 사람·참조인·발송 방식은 업무분장 전용(2026-11-20 인사발령과 분리).
흐름·저장·일정 계산은 services/work_assign.py 참고.
"""
import base64
from datetime import date, datetime, timedelta

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from components.rich_editor import register_rich_editor, rich_editor
from components import mail_recipients as mr
from pages.hr_order import _file_list, _md, _rcp_summary, _upload_box
from services import hr_order_mail as hom
from services import work_assign as wa
from services import work_assign_form as waf

dash.register_page(__name__, path='/work-assign', name='업무분장', title='업무분장')

# 받는 사람·참조는 업무분장 전용 명단(2026-11-20 인사발령과 분리 — 처음엔 인사발령 값으로 시작)
WA_STORE = mr.RecipientStore(wa.load_contacts, wa.save_contacts, wa.recipient_settings, wa.save_recipient_settings)


def _target_options() -> list:
    out = []
    for t in wa.target_options():
        out.append({'label': f"{wa.target_label(t)}분 (자동 발송 예정 {_md(wa.send_date(t))})", 'value': t})
    return out


def _sub_target_options() -> list:
    today = date.today()
    return [{'label': f'{wa.target_label(t)}분', 'value': t} for t in (wa.target_of(today, k) for k in range(2, -7, -1))]


def _body_frame(body: str, target: str, reply: date, height: str = '300px'):
    doc = ('<html><head><meta charset="utf-8"></head><body style="margin:8px">'
           + hom.body_html(wa.render(body or '', target, reply)) + '</body></html>')
    return html.Iframe(srcDoc=doc, sandbox='', style={'width': '100%', 'height': height, 'border': '0', 'background': '#fff'})


# ── 카드: 양식 메일 ─────────────────────────────────────────────────────────

def _compose_card():
    contacts = wa.load_contacts()
    subject_t, body_t = wa.template()
    opts = _target_options()
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-envelope-paper me-1'), '업무분장 작성 요청 메일'],
                                 className='fw-semibold')),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([dbc.Label('발신 계정', className='small mb-1'),
                         dcc.Dropdown(id='wa-sender', options=hom.sender_options(), clearable=False)], md=6),
                dbc.Col([dbc.Label('대상월', className='small mb-1'),
                         dcc.Dropdown(id='wa-target', options=opts, value=opts[1]['value'], clearable=False)], md=6),
            ], className='g-2 mb-3'),
            dbc.Label('받을 부서 담당자(수신 TO)', className='small mb-1'),
            html.Div([
                dbc.Button('전체 선택', id='wa-all', color='link', size='sm', className='p-0 me-3'),
                dbc.Button('선택 해제', id='wa-none', color='link', size='sm', className='p-0 me-3'),
                dbc.Button('미제출 부서만', id='wa-unsub', color='link', size='sm', className='p-0'),
            ], className='mb-1'),
            dbc.Checklist(id='wa-recipients', options=mr.recipient_options(contacts), value=[],
                          className='small mb-1', style={'columns': '2'}),
            html.Div('아래 "부서별 담당자(업무분장)"에 먼저 등록하세요.' if not contacts else '', id='wa-recipients-hint',
                     className='small text-muted mb-2'),
            mr.cc_block('wa', WA_STORE),
            dbc.Row([
                dbc.Col([
                    html.Div([dbc.Label('제목·본문 템플릿', className='small mb-0 me-2'),
                              dbc.Button([html.I(className='bi bi-save me-1'), '템플릿 저장'], id='wa-tpl-save',
                                         color='secondary', outline=True, size='sm', className='py-0'),
                              html.Span(id='wa-tpl-msg', className='small ms-2')],
                             className='d-flex align-items-center mb-1'),
                    html.Div(['평소 쓰시는 문구를 붙여 넣고(서식 유지), ', html.Code('{대상월}'), ' ', html.Code('{대상월_숫자}'),
                              ' ', html.Code('{회신일}'), ' ', html.Code('{회신일_월일}'), ' ', html.Code('{메일 발송일}'), ' ',
                              html.Code('{메일 발송일_월일}'),
                              '을 넣으면 대상월·회신 기한·메일 보내는 날(수동은 오늘, 자동은 자동 발송일)에 맞춰 바뀝니다'
                              '(예: 2026년 12월 / 2026.12 / 12월 1일(화) / 2026.11.25). '
                              '회신 기한은 대상월의 아래 "자동 발송"에서 정한 날(기본 1일, 휴일이면 다음 워킹데이)입니다.'],
                             className='small text-muted mb-2'),
                    dbc.Input(id='wa-subject', value=subject_t, size='sm', className='mb-2'),
                    rich_editor('wa', body_t),
                ], md=6),
                dbc.Col([
                    dbc.Label('미리보기(지금 보낼 때)', className='small mb-1'),
                    html.Div(id='wa-preview', className='border rounded p-2 small bg-light', style={'minHeight': '260px'}),
                ], md=6),
            ], className='g-3 mb-3'),
            _form_box(),
            dbc.Label('공통 첨부파일(플랫폼별 양식을 쓰면 선택 — 함께 보냄)', className='small mb-1'),
            _upload_box('wa-upload', '클릭 또는 끌어다 놓아 첨부(여러 개 가능, 합계 20MB까지)'),
            html.Div(id='wa-files', className='small mb-3'),
            dbc.Button([html.I(className='bi bi-send me-1'), '메일 보내기'], id='wa-send', color='primary'),
            html.Div(id='wa-result', className='mt-3'),
            dcc.Store(id='wa-files-store', data=[]),
            dbc.Modal([
                dbc.ModalHeader(dbc.ModalTitle('보낼 내용을 확인하세요')),
                dbc.ModalBody(id='wa-confirm-body'),
                dbc.ModalFooter([html.Span('받는 사람별 첨부 파일을 내려받아 확인한 뒤 보내세요.', className='small text-muted me-auto'),
                                 dbc.Button('취소', id='wa-confirm-cancel', color='secondary', size='sm'),
                                 dbc.Button([html.I(className='bi bi-send me-1'), '확인했습니다 — 보내기'], id='wa-confirm-ok',
                                            color='primary', size='sm')]),
            ], id='wa-confirm', is_open=False, size='xl', scrollable=True),
        ]),
    ], className='shadow-sm mb-4')


def _form_status():
    st = waf.settings()
    src = (f"올린 양식 원본: {st['template_name']}" if st['template_name']
           else '기본 양식(구글 시트 "업무분장 양식"과 같은 구조) 사용 중 — 서식을 바꾸려면 엑셀 원본을 올리세요')
    return html.Span(src, className='text-muted')


def _form_box():
    st = waf.settings()
    return html.Div([
        html.Div([html.I(className='bi bi-magic me-1'), html.B('플랫폼별 양식 자동 생성')], className='small mb-1'),
        html.Div(['켜면 최신 인력현황의 대상자(직급 ', ', '.join(waf.TARGET_POSITIONS), ')로 Knox ID·재직현황·플랫폼·그룹·'
                  '과제/파트명·성명을 채운 양식을 플랫폼별 파일(업무분장_26년12월_플랫폼.xlsx)로 나눠, 담당자 부서가 그 플랫폼인 '
                  '담당자에게만 보냅니다(항상 담당자별 따로). "참고 : 지난달" 칸은 아래에 올린 참고 엑셀(지난달 업무분장)에서 '
                  'Knox ID로 찾아 채우고, 1행 날짜는 대상월에 맞춰 바뀝니다.'], className='small text-muted mb-2'),
        dbc.Switch(id='wa-gen', value=st['enabled'], label='플랫폼별 양식 자동 생성해 첨부(수동·자동 발송)', className='small'),
        html.Div([html.Span('참고(지난달) 엑셀 — 위에서 고른 대상월용: ', className='small fw-semibold me-1'),
                  html.Span(id='wa-ref-src', className='small me-2'),
                  dcc.Upload(id='wa-ref-upload', children=dbc.Button([html.I(className='bi bi-upload me-1'), '참고 엑셀 올리기'],
                                                                    color='secondary', outline=True, size='sm',
                                                                    className='py-0'), className='d-inline-block me-2'),
                  dbc.Button('삭제', id='wa-ref-del', color='link', size='sm', className='py-0 text-danger')],
                 className='d-flex flex-wrap align-items-center gap-1 mt-1'),
        html.Div([html.Span(id='wa-form-src', children=_form_status(), className='small me-2'),
                  dcc.Upload(id='wa-form-upload', children=dbc.Button([html.I(className='bi bi-upload me-1'), '양식 원본 올리기'],
                                                                     color='secondary', outline=True, size='sm',
                                                                     className='py-0'), className='d-inline-block me-2'),
                  dbc.Button('기본 양식으로', id='wa-form-reset', color='link', size='sm', className='py-0 me-2'),
                  dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '전체 명단 받기(한 파일)'], id='wa-form-full',
                             color='success', outline=True, size='sm', className='py-0'),
                  dbc.Button([html.I(className='bi bi-file-earmark-zip me-1'), '플랫폼별 파일 모두(zip)'], id='wa-form-zip',
                             color='success', outline=True, size='sm', className='py-0')],
                 className='d-flex flex-wrap align-items-center gap-1 mt-1'),
        html.Div(id='wa-form-msg', className='small mt-1'),
        html.Div(id='wa-plan', className='small mt-2'),
        dcc.Store(id='wa-ref-ver', data=0),
    ], className='border rounded p-2 mb-3')


def _ref_src(target: str):
    info = waf.ref_info(target) if target else {}
    if info:
        return html.Span(f"{info['name']} ({info['rows']}행, {info['at'].replace('T', ' ')[:16]})", className='text-success')
    src = waf._ref_table(target)[1] if target else ''
    return html.Span(f'없음 — {src}로 대신 채움' if src else '없음 — 참고 칸을 비워 둠', className='text-muted')


def _dl_link(kind: str, platform: str, name: str):
    return html.Span([html.I(className='bi bi-download me-1'), name], id={'type': kind, 'p': platform}, n_clicks=0,
                     className='text-primary', style={'cursor': 'pointer'}, title='내려받아 확인')


def _plan_view(target: str):
    pl = waf.plan(target)
    if not pl['platforms']:
        return html.Div('대상자가 없습니다(최신 인력현황·직급 확인).', className='text-warning')
    total = sum(p['count'] for p in pl['platforms'])
    multi = {}
    for p in pl['platforms']:
        for c in p['contacts']:
            multi[c['email'].lower()] = multi.get(c['email'].lower(), 0) + 1
    rows = [html.Tr([html.Td(p['platform']), html.Td(f"{p['count']}명"),
                     html.Td(_dl_link('wa-form-dl', p['platform'], waf.file_name(target, p['platform']))),
                     html.Td(', '.join(f"{c.get('name') or ''} <{c['email']}>" + (' (겸직 — 한 통으로)' if multi[c['email'].lower()] > 1 else '')
                                       for c in p['contacts'])
                             if p['contacts'] else html.Span('담당자 없음 — 보내지 않음', className='text-danger'))])
            for p in pl['platforms']]
    rows.append(html.Tr([html.Td(html.B('전체')), html.Td(html.B(f'{total}명')),
                         html.Td(_dl_link('wa-form-dl', '__all__', waf.file_name(target, None))),
                         html.Td('확인용(보내지 않음)', className='text-muted')]))
    extra = []
    if pl['unmatched_contacts']:
        extra.append(html.Div(['플랫폼과 부서명이 맞지 않아 양식을 받지 못하는 담당자: ',
                               ', '.join(f"{c['dept']} · {c.get('name') or c['email']}" for c in pl['unmatched_contacts']),
                               ' — 아래 부서별 담당자(업무분장)의 부서명을 플랫폼 이름과 같게 고치세요.'], className='text-danger mt-1'))
    return html.Div([html.Div(f"플랫폼별 대상 인원·생성 파일·받는 담당자 — 참고 칸 출처: {pl['ref'] or '없음'}",
                              className='fw-semibold mb-1'),
                     dbc.Table([html.Thead(html.Tr([html.Th('플랫폼'), html.Th('대상'), html.Th('파일(눌러서 받기)'),
                                                    html.Th('받는 담당자')])),
                                html.Tbody(rows)], size='sm', bordered=True, className='small mb-0'), *extra])


# ── 카드: 회신 관리 ─────────────────────────────────────────────────────────

def _submit_card():
    opts = _sub_target_options()
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-inboxes me-1'), '회신 업무분장표 — 부서별 제출 현황·통합표'],
                                 className='fw-semibold')),
        dbc.CardBody([
            html.Div('메일로 회신받은 업무분장표(엑셀·CSV)를 올리면 부서별 제출 현황에 표시되고, 아래 통합표에 양식의 열 그대로 '
                     '"부서" 열을 붙여 합쳐집니다(양식 오른쪽 "참고 : 이전 달" 열은 기본으로 빼고, 체크하면 "참고_" 열로 함께 표시). '
                     '파일 이름에 부서명이 들어 있으면 여러 개를 한 번에 올려도 부서가 자동으로 '
                     '연결되고, 아니면 부서를 고른 뒤 한 개씩 올리세요. 같은 부서에 다시 올리면 새 파일로 바뀝니다.',
                     className='small text-muted mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('대상월', className='small mb-1'),
                         dcc.Dropdown(id='wa-sub-target', options=opts, value=opts[1]['value'], clearable=False)], md=3),
                dbc.Col([dbc.Label('부서(파일 1개 올릴 때 선택)', className='small mb-1'),
                         dcc.Dropdown(id='wa-sub-dept', options=wa.departments(), placeholder='파일 이름으로 자동 연결')],
                        md=3),
                dbc.Col(dcc.Upload(id='wa-sub-upload', multiple=True,
                                   children=html.Div([html.I(className='bi bi-upload me-1'), '회신 파일 올리기(여러 개 가능)']),
                                   className='border border-2 rounded text-center text-muted small py-2',
                                   style={'borderStyle': 'dashed', 'cursor': 'pointer'}), md=6),
            ], className='g-2 align-items-end mb-2'),
            html.Div(id='wa-sub-msg', className='small mb-2'),
            html.Div(id='wa-sub-status', className='mb-3'),
            html.Div([html.Span('통합표', className='fw-semibold small me-2'),
                      dbc.Button([html.I(className='bi bi-file-earmark-excel me-1'), '다운로드 (엑셀)'], id='wa-merged-dl',
                                 color='success', outline=True, size='sm', className='py-0 me-3'),
                      dbc.Checkbox(id='wa-merged-ref', value=False, label='참고(이전 달) 열 포함',
                                   className='small mb-0')],
                     className='d-flex align-items-center mb-1'),
            dag.AgGrid(id='wa-merged', rowData=[], columnDefs=[], className='ag-theme-alpine',
                       defaultColDef={'resizable': True, 'sortable': True, 'filter': True, 'minWidth': 90},
                       dashGridOptions={'enableCellTextSelection': True}, style={'height': '420px'}),
            dcc.Store(id='wa-sub-ver', data=0),
            dcc.Download(id='wa-download'),
        ]),
    ], className='shadow-sm mb-4')


def _status_table(target: str):
    rows = wa.status(target)
    if not rows:
        return html.Div(['부서별 담당자가 없습니다 — 위 "부서별 담당자(업무분장)"에 먼저 등록하세요.'],
                        className='small text-muted')
    done = sum(1 for r in rows if r['submitted'])
    body = []
    for r in rows:
        body.append(html.Tr([
            html.Td(r['dept']), html.Td(r['contact']),
            html.Td(dbc.Badge('제출', color='success') if r['submitted'] else dbc.Badge('미제출', color='secondary')),
            html.Td(r['name']), html.Td(r['rows']), html.Td(r['at'].replace('T', ' ')[:16]), html.Td(r['by_name']),
            html.Td([
                html.Span(html.I(className='bi bi-download'), id={'type': 'wa-sub-dl', 'dept': r['dept']}, n_clicks=0,
                          className='text-primary me-3', style={'cursor': 'pointer'}, title='원본 파일 받기'),
                html.Span(html.I(className='bi bi-trash'), id={'type': 'wa-sub-del', 'dept': r['dept']}, n_clicks=0,
                          className='text-danger', style={'cursor': 'pointer'}, title='제출 취소(파일 삭제)'),
            ] if r['submitted'] else ''),
        ]))
    return html.Div([
        html.Div(f'{wa.target_label(target)}분 제출 {done}/{len(rows)}개 부서', className='small fw-semibold mb-1'),
        dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('부서', '담당자', '상태', '파일', '행 수', '올린 시각', '올린 사람', '')])),
                   html.Tbody(body)], size='sm', bordered=True, hover=True, className='small mb-0'),
    ])


# ── 카드: 자동 발송 ─────────────────────────────────────────────────────────

def _auto_status():
    cfg = wa.auto_settings()
    if not cfg['enabled']:
        return html.Span('자동 발송이 꺼져 있습니다.', className='text-muted')
    nxt = wa.next_auto_send()
    who = (cfg['sender'] or {}).get('label', '')
    lines = [html.Div([html.I(className='bi bi-check-circle text-success me-1'),
                       f'켜짐 — 매월 마지막 워킹데이 {wa.send_workdays()}일 전 발송·회신 기한 대상월 {wa.reply_day()}일, '
                       f'발신 {who}, 담당자 {len(wa.load_contacts())}명 전체, 공통 첨부 {len(cfg["files"])}개'
                       + (', 플랫폼별 양식 자동 생성(담당자별 따로)' if waf.settings()['enabled'] else '')
                       + _rcp_summary(wa.recipient_settings())])]
    if nxt:
        t, when = nxt
        lines.append(html.Div(f'다음 발송: {_md(when.date())} {when:%H:%M} — {wa.target_label(t)}분'
                              f'(회신 {_md(wa.reply_due(t))})', className='fw-semibold'))
    return html.Div(lines)


def _days_preview(send, reply):
    if send is None or not reply:
        return []
    lines = []
    for k in (1, 2, 3):                                  # 다음 3개월 — 휴일로 밀리는 경우를 미리 보이게
        t = wa.target_of(date.today(), k)
        base = wa.base_date(t)
        sd = hom.workdays_before(base, int(send))
        y, m = wa._month(t)
        first = date(y, m, int(reply))
        rd, skipped = first, []
        while not hom.is_workday(rd):
            skipped.append(f'{rd.month}.{rd.day} {hom.day_off_reason(rd)}')
            rd += timedelta(days=1)
        why = f" ({', '.join(skipped)} → 다음 워킹데이)" if skipped else ''
        lines.append(html.Div(f'{wa.target_label(t)}분: 발송 {_md(sd)}, 회신 기한 {_md(rd)}{why}'))
    if not hom.holidays_available():
        lines.append(html.Div('공휴일 계산 패키지(holidays)가 없어 지금은 주말·회사 휴무일만 뺍니다 — 서버 재빌드 필요.',
                              className='text-danger'))
    return lines


def _auto_card():
    cfg = wa.auto_settings()
    files = [{'name': n, 'size': len(b)} for n, b in wa.auto_files()]
    sender_value = hom.SHARED_SENDER if cfg['sender'] and not cfg['sender'].get('user_id') else None
    return dbc.Card([
        dbc.CardHeader(html.Span([html.I(className='bi bi-alarm me-1'), '자동 발송'], className='fw-semibold')),
        dbc.CardBody([
            html.Div('켜 두면 매월 마지막 워킹데이의 아래 일수 전, 지정한 시각에 부서별 담당자 전체에게 저장된 템플릿·참조인·'
                     '발송 방식과 아래 첨부로 다음 달 업무분장을 요청합니다(대상월당 한 번). 워킹데이는 토·일, 공휴일, 인사발령 '
                     '화면의 회사 휴무일을 뺀 날입니다.', className='small text-muted mb-2'),
            dbc.Row([
                dbc.Col(dbc.Switch(id='wa-auto-on', label='자동 발송 사용', value=cfg['enabled']), md=3),
                dbc.Col([dbc.Label('발송 시각', className='small mb-1'),
                         dcc.Dropdown(id='wa-auto-hour', options=[{'label': f'{h:02d}:00', 'value': h} for h in range(7, 20)],
                                      value=cfg['hour'], clearable=False)], md=3),
                dbc.Col([dbc.Label('발신 계정', className='small mb-1'),
                         dcc.Dropdown(id='wa-auto-sender', options=hom.sender_options(), value=sender_value,
                                      clearable=False)], md=6),
            ], className='g-2 align-items-end mb-2'),
            dbc.Row([
                dbc.Col([dbc.Label('발송일 — 매월 마지막 워킹데이 며칠 전', className='small mb-1'),
                         dcc.Dropdown(id='wa-send-days', value=wa.send_workdays(), clearable=False,
                                      options=[{'label': '당일(마지막 워킹데이)' if n == 0 else f'{n}일 전', 'value': n}
                                               for n in range(0, wa.MAX_DAYS + 1)])], md=3),
                dbc.Col([dbc.Label('회신 기한 — 대상월 며칠(수동·자동 공통)', className='small mb-1'),
                         dcc.Dropdown(id='wa-reply-days', value=wa.reply_day(), clearable=False,
                                      options=[{'label': '1일(당일)' if n == 1 else f'{n}일', 'value': n}
                                               for n in range(1, wa.MAX_REPLY_DAY + 1)])], md=3),
                dbc.Col(html.Div(id='wa-days-preview', className='small text-muted'), md=6),
            ], className='g-2 align-items-end mb-2'),
            dbc.Label('자동 발송용 첨부(서버에 보관)', className='small mb-1'),
            _upload_box('wa-auto-upload', '클릭 또는 끌어다 놓아 첨부(여러 개 가능, 계속 추가됨 — 같은 이름이면 새 파일로 바뀜)'),
            html.Div(_file_list(files, 'wa-auto-file-del'), id='wa-auto-files', className='small mb-2'),
            dbc.Button([html.I(className='bi bi-save me-1'), '자동 발송 설정 저장'], id='wa-auto-save', color='primary',
                       size='sm', className='mt-1'),
            html.Div(id='wa-auto-msg', className='small mt-2'),
            html.Div(_auto_status(), id='wa-auto-status', className='small mt-2'),
        ]),
    ], className='shadow-sm mb-4')


# ── 카드: 발송 이력 ─────────────────────────────────────────────────────────

def _log_table():
    from pages.hr_order import _log_cc
    rows = wa.read_log()
    if not rows:
        return html.Div('아직 보낸 메일이 없습니다.', className='small text-muted')
    body = []
    for e in rows:
        ok = [r for r in e.get('results', []) if r.get('ok')]
        fail = [r for r in e.get('results', []) if not r.get('ok')]
        target = e.get('target', '')
        body.append(html.Tr([
            html.Td(e.get('at', '').replace('T', ' ')[:16], className='text-nowrap'),
            html.Td('자동' if e.get('kind') == 'auto' else '수동'),
            html.Td(wa.target_label(target) if target else ''),
            html.Td(e.get('by_name') or e.get('by')), html.Td(e.get('sender', '')), html.Td(e.get('subject', '')),
            html.Td(_log_cc(e)), html.Td(', '.join(f['name'] for f in e.get('files', []))),
            html.Td([html.Span(f'성공 {len(ok)}', className='text-success me-2'),
                     html.Span(f'실패 {len(fail)}', className='text-danger') if fail else None],
                    title='\n'.join(f"{r['dept']} {r['email']}: {r['error']}" for r in fail) or None),
        ]))
    return dbc.Table([html.Thead(html.Tr([html.Th(h) for h in ('시각', '구분', '대상월', '보낸 사람', '발신 계정', '제목',
                                                               '참조', '첨부', '결과')])),
                      html.Tbody(body)], size='sm', bordered=True, className='small mb-0')


def layout():
    if not wa.can_use():
        return dbc.Alert('업무분장 메뉴를 쓸 권한이 없습니다. 관리자에게 요청하세요.', color='warning', className='mt-3')
    return dbc.Container([
        html.H4([html.I(className='bi bi-list-task me-2 text-primary'), '업무분장'], className='fw-bold mt-2'),
        html.P('매월 업무분장표 작성 양식을 부서별 담당자에게 메일로 보내고, 회신받은 업무분장표를 올려 제출 현황과 통합표로 '
               '관리합니다. 받는 사람·참조인·발송 방식은 업무분장 전용이고(인사발령과 따로), 사용 권한·회사 휴무일은 인사발령 설정을 '
               '함께 씁니다.',
               className='text-muted small'),
        _compose_card(),
        mr.contacts_card('wa', WA_STORE, title='부서별 담당자(업무분장)',
                         note='업무분장 전용 명단입니다(인사발령 명단과 따로 — 처음엔 인사발령 명단을 복사해 시작). 업무분장 '
                              '플랫폼별 양식은 부서명이 플랫폼 이름과 같은 담당자에게만 갑니다.'),
        _submit_card(),
        _auto_card(),
        dbc.Card([dbc.CardHeader(html.Span([html.I(className='bi bi-clock-history me-1'), '발송 이력(최근 50건)'],
                                           className='fw-semibold')),
                  dbc.CardBody(html.Div(_log_table(), id='wa-log'))], className='shadow-sm mb-4'),
    ], fluid=True, className='py-3')


# ── 콜백: 작성 요청 메일 ─────────────────────────────────────────────────────

register_rich_editor('wa')


@callback(Output('wa-sender', 'value'), Input('wa-sender', 'options'))
def _default_sender(options):
    return options[0]['value'] if options else None


@callback(Output('wa-preview', 'children'), Input('wa-target', 'value'), Input('wa-subject', 'value'),
          Input('wa-body', 'data'))
def _preview(target, subject, body):
    if not target:
        return ''
    reply = wa.reply_due(target)
    return html.Div([html.Div([html.B('제목: '), wa.render(subject, target, reply)], className='mb-2'),
                     _body_frame(body, target, reply)])


@callback(Output('wa-tpl-msg', 'children'), Input('wa-tpl-save', 'n_clicks'), State('wa-subject', 'value'),
          State('wa-body', 'data'), prevent_initial_call=True)
def _save_template(n, subject, body):
    if not n:
        return no_update
    try:
        wa.save_template(subject, body)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger')
    return html.Span('저장했습니다.', className='text-success')


@callback(Output('wa-recipients', 'value'), Input('wa-all', 'n_clicks'), Input('wa-none', 'n_clicks'),
          Input('wa-unsub', 'n_clicks'), State('wa-recipients', 'options'), State('wa-target', 'value'),
          prevent_initial_call=True)
def _select(_a, _n, _u, options, target):
    if ctx.triggered_id == 'wa-none':
        return []
    if ctx.triggered_id == 'wa-unsub':
        submitted = set(wa.submissions(target or ''))     # 겸직이면 맡은 부서 중 하나라도 미제출이면 선택
        return [g['email'] for g in hom.group_contacts(wa.load_contacts())
                if any(d not in submitted for d in g['depts'])]
    return [o['value'] for o in options or []]


@callback(Output('wa-files-store', 'data'), Output('wa-upload', 'contents'),
          Input('wa-upload', 'contents'), Input({'type': 'wa-file-del', 'i': ALL}, 'n_clicks'),
          State('wa-upload', 'filename'), State('wa-files-store', 'data'), prevent_initial_call=True)
def _files(contents, dels, filenames, files):
    files = list(files or [])
    if isinstance(ctx.triggered_id, dict):
        if not any(dels or []):
            return no_update, no_update
        files.pop(ctx.triggered_id['i'])
        return files, no_update
    for content, name in zip(contents or [], filenames or []):
        b64 = content.split(',', 1)[1]
        files.append({'name': name, 'b64': b64, 'size': len(base64.b64decode(b64))})
    return files, None


@callback(Output('wa-files', 'children'), Input('wa-files-store', 'data'))
def _files_view(files):
    return _file_list(files, 'wa-file-del')


@callback(Output('wa-confirm', 'is_open'), Output('wa-confirm-body', 'children'), Output('wa-result', 'children'),
          Input('wa-send', 'n_clicks'), Input('wa-confirm-cancel', 'n_clicks'),
          State('wa-recipients', 'value'), State('wa-recipients', 'options'), State('wa-subject', 'value'),
          State('wa-body', 'data'), State('wa-target', 'value'), State('wa-files-store', 'data'),
          State('wa-sender', 'value'), State('wa-sender', 'options'), State('wa-gen', 'value'),
          State('wa-cc', 'value'), State('wa-bcc', 'value'), State('wa-mode', 'value'), prevent_initial_call=True)
def _confirm(_send, _cancel, emails, options, subject, body, target, files, sender, sender_opts, gen, cc, bcc, mode):
    if ctx.triggered_id == 'wa-confirm-cancel':
        return False, no_update, no_update
    problems = [m for ok, m in ((emails, '받을 담당자를 고르세요.'), ((subject or '').strip(), '제목을 입력하세요.'),
                                (files or gen, '첨부파일을 올리거나 플랫폼별 양식 자동 생성을 켜세요.'), (sender, '발신 계정을 고르세요.'), (target, '대상월을 고르세요.'))
                if not ok]
    if problems:
        return False, no_update, dbc.Alert(' '.join(problems), color='warning', className='small py-2')
    try:
        cc_p, bcc_p = mr.cc_people(WA_STORE, cc, bcc)
    except ValueError as exc:
        return False, no_update, dbc.Alert(str(exc), color='warning', className='small py-2')
    reply = wa.reply_due(target)
    sender_label = next((o['label'] for o in sender_opts or [] if o['value'] == sender), sender)
    single = mode == 'single' and not gen
    chosen = hom.group_contacts(wa.contacts_for_emails(emails))     # 겸직 담당자는 한 줄·한 통
    plats = set(waf.platforms()) if gen else set()
    common = [f['name'] for f in files or []]
    common_view = [html.Div([html.I(className='bi bi-paperclip me-1'), n]) for n in common]
    rows, n_send = [], 0
    for c in chosen:
        mine = [d for d in c['depts'] if d in plats]
        has_form = bool(mine)
        skip = gen and not has_form
        n_send += 0 if skip else 1
        file_cell = common_view + ([html.Div(_dl_link('wa-form-dl2', d, waf.file_name(target, d))) for d in mine]
                                   if gen else [])
        if gen and has_form and len(mine) < len(c['depts']):
            file_cell.append(html.Div(f"양식 없음: {', '.join(d for d in c['depts'] if d not in plats)}",
                                      className='text-warning'))
        rows.append(html.Tr([
            html.Td(f"{c.get('name') or ''} <{c['email']}>"), html.Td(c['dept']),
            html.Td(file_cell or '-'),
            html.Td(html.Span(f"'{c['dept']}' 플랫폼 대상자 없음 — 보내지 않음", className='text-danger') if skip
                    else html.Span('보냄', className='text-success')),
        ], className='table-danger' if skip else None))
    cc_text = ', '.join(f"{p['name']} <{p['email']}>" for p in cc_p) or '없음'
    bcc_text = ', '.join(f"{p['name']} <{p['email']}>" for p in bcc_p)
    how = '담당자별 따로(플랫폼별 양식)' if gen else ('한 통으로(담당자 전원 TO)' if single else '담당자별 따로')
    return True, html.Div([
        html.Div([html.B('발신: '), sender_label], className='small mb-1'),
        html.Div([html.B('제목: '), wa.render(subject, target, reply)], className='small mb-1'),
        html.Div([html.B('발송 방식: '), how, ' · ', html.B('참조(CC): '), cc_text,
                  (html.Span([' · ', html.B('비밀참조: '), bcc_text]) if bcc_text else '')], className='small mb-2'),
        html.Div(html.B(f'받는 사람과 첨부 파일 — 보냄 {n_send}명' + (f' / 보내지 않음 {len(chosen) - n_send}명'
                                                                if n_send < len(chosen) else '')), className='small mb-1'),
        dbc.Table([html.Thead(html.Tr([html.Th('받는 사람(TO)'), html.Th('부서'), html.Th('첨부 파일'), html.Th('상태')])),
                   html.Tbody(rows)], size='sm', bordered=True, className='small mb-2'),
        html.Details([html.Summary('본문 미리보기', className='small'),
                      html.Div(_body_frame(body, target, reply, '240px'), className='border rounded mt-1')], open=False),
    ]), no_update


@callback(Output('wa-result', 'children', allow_duplicate=True), Output('wa-confirm', 'is_open', allow_duplicate=True),
          Output('wa-log', 'children'),
          Input('wa-confirm-ok', 'n_clicks'),
          State('wa-recipients', 'value'), State('wa-subject', 'value'), State('wa-body', 'data'),
          State('wa-target', 'value'), State('wa-files-store', 'data'), State('wa-sender', 'value'),
          State('wa-gen', 'value'), State('wa-cc', 'value'), State('wa-bcc', 'value'), State('wa-mode', 'value'),
          prevent_initial_call=True)
def _send(n, emails, subject, body, target, files, sender, gen, cc, bcc, mode):
    if not n:
        return no_update, no_update, no_update
    reply = wa.reply_due(target)
    contacts = wa.contacts_for_emails(emails)             # 겸직이면 여러 행 — 발송 때 한 통으로 묶임
    attachments = [(f['name'], base64.b64decode(f['b64'])) for f in files or []]
    try:
        cc_p, bcc_p = mr.cc_people(WA_STORE, cc, bcc)
        results = wa.send(contacts, wa.render(subject, target, reply), wa.render(body, target, reply), attachments, sender,
                          target, cc=cc_p, bcc=bcc_p, mode=mode or 'each', gen_forms=bool(gen))
    except (PermissionError, ValueError) as exc:
        return dbc.Alert(str(exc), color='danger', className='small py-2'), False, no_update
    ok = [r for r in results if r['ok']]
    fail = [r for r in results if not r['ok']]
    items = [html.Div([html.I(className='bi bi-check-circle text-success me-1'), f'{len(ok)}명에게 보냈습니다.'])] if ok else []
    items += [html.Div([html.I(className='bi bi-x-circle text-danger me-1'), f"{r['dept']} {r['email']}: {r['error']}"])
              for r in fail]
    return dbc.Alert(items, color='success' if not fail else 'warning', className='small py-2'), False, _log_table()


# ── 콜백: 플랫폼별 양식 ──────────────────────────────────────────────────────

@callback(Output('wa-form-msg', 'children'), Output('wa-auto-status', 'children', allow_duplicate=True),
          Input('wa-gen', 'value'), prevent_initial_call=True)
def _form_settings(gen):
    try:
        waf.save_settings(bool(gen))
    except PermissionError as exc:
        return html.Span(str(exc), className='text-danger'), no_update
    return html.Span('저장했습니다.', className='text-success'), _auto_status()


@callback(Output('wa-form-msg', 'children', allow_duplicate=True), Output('wa-ref-ver', 'data'),
          Output('wa-ref-upload', 'contents'),
          Input('wa-ref-upload', 'contents'), Input('wa-ref-del', 'n_clicks'), State('wa-ref-upload', 'filename'),
          State('wa-target', 'value'), State('wa-ref-ver', 'data'), prevent_initial_call=True)
def _ref_upload(content, _del, filename, target, ver):
    try:
        if ctx.triggered_id == 'wa-ref-del':
            waf.delete_ref(target)
            return html.Span('참고 엑셀을 지웠습니다.', className='text-muted'), (ver or 0) + 1, no_update
        if not content:
            return no_update, no_update, no_update
        info = waf.save_ref(target, filename, base64.b64decode(content.split(',', 1)[1]))
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), no_update, None
    return (html.Span(f"{wa.target_label(target)}분 참고 엑셀을 저장했습니다({info['rows']}행).", className='text-success'),
            (ver or 0) + 1, None)


@callback(Output('wa-ref-src', 'children'), Output('wa-plan', 'children'),
          Input('wa-target', 'value'), Input('wa-ref-ver', 'data'), Input('wa-gen', 'value'))
def _ref_and_plan(target, _ver, gen):
    if not target:
        return '', ''
    return _ref_src(target), _plan_view(target)


@callback(Output('wa-form-src', 'children'), Output('wa-form-msg', 'children', allow_duplicate=True),
          Output('wa-form-upload', 'contents'),
          Input('wa-form-upload', 'contents'), Input('wa-form-reset', 'n_clicks'), State('wa-form-upload', 'filename'),
          prevent_initial_call=True)
def _form_template(content, _reset, filename):
    try:
        if ctx.triggered_id == 'wa-form-reset':
            waf.delete_template()
            return _form_status(), html.Span('기본 양식으로 돌렸습니다.', className='text-muted'), no_update
        if not content:
            return no_update, no_update, no_update
        waf.save_template(filename, base64.b64decode(content.split(',', 1)[1]))
    except (PermissionError, ValueError) as exc:
        return no_update, html.Span(str(exc), className='text-danger'), None
    return _form_status(), html.Span('양식 원본을 저장했습니다.', className='text-success'), None


def _clicks_of(trig: dict) -> int:
    """패턴 매칭 입력 중 trig에 해당하는 n_clicks — ctx.triggered의 value가 None으로 오는 경우가 있어 inputs_list에서 찾는다."""
    for group in ctx.inputs_list:
        for item in group if isinstance(group, list) else [group]:
            if item.get('id') == trig:
                return item.get('value') or 0
    return 0


@callback(Output('wa-download', 'data', allow_duplicate=True), Output('wa-form-msg', 'children', allow_duplicate=True),
          Input('wa-form-full', 'n_clicks'), Input({'type': 'wa-form-dl', 'p': ALL}, 'n_clicks'),
          Input({'type': 'wa-form-dl2', 'p': ALL}, 'n_clicks'), State('wa-target', 'value'), prevent_initial_call=True)
def _form_file(_full, dl, dl2, target):
    """생성 양식 확인용 다운로드 — 전체 명단 한 파일 또는 플랫폼 하나(계획 표·확인창)."""
    trig = ctx.triggered_id
    if not wa.can_use() or not target:
        return no_update, no_update
    if isinstance(trig, dict) and not _clicks_of(trig):   # 표·확인창이 다시 그려질 때(클릭 아님)는 무시
        return no_update, no_update
    platform = None if trig == 'wa-form-full' or (isinstance(trig, dict) and trig['p'] == '__all__') else trig['p']
    try:
        name, content = waf.build_form(target, platform)
    except ValueError as exc:
        return no_update, html.Span(str(exc), className='text-danger')
    return dcc.send_bytes(content, name), no_update


@callback(Output('wa-download', 'data', allow_duplicate=True), Output('wa-form-msg', 'children', allow_duplicate=True),
          Input('wa-form-zip', 'n_clicks'), State('wa-target', 'value'), prevent_initial_call=True)
def _form_zip(n, target):
    if not n or not wa.can_use() or not target:
        return no_update, no_update
    try:
        data = waf.build_all_zip(target)
    except ValueError as exc:
        return no_update, html.Span(str(exc), className='text-danger')
    return dcc.send_bytes(data, f'업무분장_플랫폼별양식_{target}.zip'), no_update


# ── 콜백: 회신 관리 ─────────────────────────────────────────────────────────

@callback(Output('wa-sub-msg', 'children'), Output('wa-sub-ver', 'data'), Output('wa-sub-upload', 'contents'),
          Input('wa-sub-upload', 'contents'), Input({'type': 'wa-sub-del', 'dept': ALL}, 'n_clicks'),
          State('wa-sub-upload', 'filename'), State('wa-sub-target', 'value'), State('wa-sub-dept', 'value'),
          State('wa-sub-ver', 'data'), prevent_initial_call=True)
def _submit(contents, dels, filenames, target, dept, ver):
    try:
        if isinstance(ctx.triggered_id, dict):
            if not any(dels or []):
                return no_update, no_update, no_update
            d = ctx.triggered_id['dept']
            wa.delete_submission(target, d)
            return html.Span(f'{d} 제출을 취소했습니다.', className='text-muted'), (ver or 0) + 1, no_update
        files = [(n, base64.b64decode(c.split(',', 1)[1])) for c, n in zip(contents or [], filenames or [])]
        if not files:
            return no_update, no_update, None
        done, errors = wa.save_uploads(target, files, dept)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), no_update, None
    items = [html.Div([html.I(className='bi bi-check-circle text-success me-1'),
                       f'{len(done)}개 저장: ' + ', '.join(f'{d}({n})' for d, n in done)])] if done else []
    items += [html.Div([html.I(className='bi bi-exclamation-triangle text-warning me-1'), e]) for e in errors]
    return html.Div(items), (ver or 0) + 1, None


@callback(Output('wa-sub-status', 'children'), Output('wa-merged', 'rowData'), Output('wa-merged', 'columnDefs'),
          Input('wa-sub-target', 'value'), Input('wa-sub-ver', 'data'), Input('wa-merged-ref', 'value'))
def _status(target, _ver, include_ref):
    if not target:
        return '', [], []
    df = wa.merged(target, bool(include_ref))
    cols = [{'field': c, 'headerName': c, 'pinned': 'left' if i == 0 else None} for i, c in enumerate(df.columns)]
    return _status_table(target), df.to_dict('records'), cols


@callback(Output('wa-download', 'data'), Input('wa-merged-dl', 'n_clicks'),
          Input({'type': 'wa-sub-dl', 'dept': ALL}, 'n_clicks'), State('wa-sub-target', 'value'),
          State('wa-merged-ref', 'value'), prevent_initial_call=True)
def _download(_m, dls, target, include_ref):
    if not wa.can_use() or not target:
        return no_update
    if isinstance(ctx.triggered_id, dict):
        if not any(dls or []):
            return no_update
        f = wa.submission_file(target, ctx.triggered_id['dept'])
        return dcc.send_bytes(f[1], f[0]) if f else no_update
    if wa.merged(target, bool(include_ref)).empty:
        return no_update
    return dcc.send_bytes(wa.merged_excel(target, bool(include_ref)), f'업무분장_통합_{target}.xlsx')


# ── 콜백: 자동 발송 ─────────────────────────────────────────────────────────

@callback(Output('wa-days-preview', 'children'), Input('wa-send-days', 'value'), Input('wa-reply-days', 'value'))
def _days(send, reply):
    return _days_preview(send, reply)


@callback(Output('wa-auto-sender', 'value'), Input('wa-auto-sender', 'options'), State('wa-auto-sender', 'value'))
def _default_auto_sender(options, value):
    return value or (options[0]['value'] if options else None)


@callback(Output('wa-auto-files', 'children'), Output('wa-auto-upload', 'contents'), Output('wa-auto-msg', 'children'),
          Input('wa-auto-upload', 'contents'), Input({'type': 'wa-auto-file-del', 'i': ALL}, 'n_clicks'),
          State('wa-auto-upload', 'filename'), prevent_initial_call=True)
def _auto_files(contents, dels, filenames):
    current = wa.auto_files()
    try:
        if isinstance(ctx.triggered_id, dict):
            if not any(dels or []):
                return no_update, no_update, no_update
            i = ctx.triggered_id['i']
            if i < len(current):
                wa.remove_auto_file(current[i][0])
        else:
            new = [(n, base64.b64decode(c.split(',', 1)[1])) for c, n in zip(contents or [], filenames or [])]
            wa.add_auto_files(new)
    except (PermissionError, ValueError) as exc:
        return no_update, None, html.Span(str(exc), className='text-danger')
    files = [{'name': n, 'size': len(b)} for n, b in wa.auto_files()]
    return _file_list(files, 'wa-auto-file-del'), None, html.Span('자동 발송용 첨부를 저장했습니다.', className='text-success')


@callback(Output('wa-auto-msg', 'children', allow_duplicate=True), Output('wa-auto-status', 'children'),
          Output('wa-target', 'options'),
          Input('wa-auto-save', 'n_clicks'),
          State('wa-auto-on', 'value'), State('wa-auto-hour', 'value'), State('wa-auto-sender', 'value'),
          State('wa-send-days', 'value'), State('wa-reply-days', 'value'), prevent_initial_call=True)
def _save_auto(n, enabled, hour, sender, send_days, reply_days):
    if not n:
        return no_update, no_update, no_update
    try:
        wa.set_workdays(send_days, reply_days)
        wa.save_auto(bool(enabled), hour, sender)
    except (PermissionError, ValueError) as exc:
        return html.Span(str(exc), className='text-danger'), _auto_status(), no_update
    return (html.Span(f'저장했습니다({datetime.now():%H:%M}).', className='text-success'), _auto_status(),
            _target_options())


mr.register('wa', WA_STORE, 'wa-auto-status', lambda: _auto_status(), empty_hint='아래 "부서별 담당자(업무분장)"에 먼저 등록하세요.')
