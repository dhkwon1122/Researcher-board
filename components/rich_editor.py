"""
메일 본문 서식 편집기(2026-11-20, 인사발령에서 분리 — 업무분장과 공용).

rich_editor(prefix, initial_html) → 도구 모음 + contentEditable 편집기({prefix}-body-editor) + HTML을 담는
dcc.Store({prefix}-body). 실제 서식 적용·Store 반영은 assets/rich_editor.js(document.execCommand). 편집기에 저장된 HTML을
처음 채우는 clientside 콜백은 페이지 모듈에서 register_rich_editor(prefix)로 한 번 등록한다.
발송·저장 전 정리는 services/hr_order_mail.sanitize_html.
"""
import dash
from dash import Input, Output, dcc, html

_FONTS = [('맑은 고딕', "'Malgun Gothic'"), ('굴림', 'Gulim'), ('돋움', 'Dotum'), ('바탕', 'Batang'), ('궁서', 'Gungsuh'),
          ('Arial', 'Arial'), ('Times New Roman', "'Times New Roman'"), ('Courier New', "'Courier New'")]
_SIZES = [('10', '1'), ('13', '2'), ('16', '3'), ('18', '4'), ('24', '5'), ('32', '6')]


def _tb_btn(icon: str, cmd: str, tip: str, val: str | None = None):
    kw = {'data-hro-cmd': cmd}
    if val:
        kw['data-hro-val'] = val
    return html.Button(html.I(className=f'bi bi-{icon}'), type='button', title=tip,
                       className='btn btn-sm btn-light border px-2 py-0', **kw)


def editor_toolbar():
    """본문 서식 도구 모음 — 실제 동작은 assets/rich_editor.js(document.execCommand)."""
    select_cls = 'form-select form-select-sm d-inline-block w-auto py-0'
    return html.Div([
        html.Select([html.Option('글꼴', value='')] + [html.Option(n, value=v) for n, v in _FONTS],
                    className=select_cls, title='글꼴', **{'data-hro-cmd': 'fontName'}),
        html.Select([html.Option('크기', value='')] + [html.Option(f'{n}px', value=v) for n, v in _SIZES],
                    className=select_cls, title='글자 크기', **{'data-hro-cmd': 'fontSize'}),
        html.Span(className='vr mx-1'),
        _tb_btn('type-bold', 'bold', '굵게(Ctrl+B)'),
        _tb_btn('type-italic', 'italic', '기울임(Ctrl+I)'),
        _tb_btn('type-underline', 'underline', '밑줄(Ctrl+U)'),
        _tb_btn('type-strikethrough', 'strikeThrough', '취소선'),
        html.Span(className='vr mx-1'),
        html.Label([html.I(className='bi bi-fonts me-1'), html.Span('글자색', className='small'),
                    html.Div(className='hro-color', **{'data-hro-cmd': 'foreColor', 'data-hro-color': '#d00000'})],
                   className='d-inline-flex align-items-center mb-0 me-1', title='글자색'),
        html.Label([html.I(className='bi bi-paint-bucket me-1'), html.Span('바탕색', className='small'),
                    html.Div(className='hro-color', **{'data-hro-cmd': 'hiliteColor', 'data-hro-color': '#ffff00'})],
                   className='d-inline-flex align-items-center mb-0 me-1', title='바탕색(형광펜)'),
        html.Span(className='vr mx-1'),
        _tb_btn('list-ul', 'insertUnorderedList', '글머리 기호'),
        _tb_btn('list-ol', 'insertOrderedList', '번호 매기기'),
        _tb_btn('text-left', 'justifyLeft', '왼쪽 정렬'),
        _tb_btn('text-center', 'justifyCenter', '가운데 정렬'),
        html.Span(className='vr mx-1'),
        _tb_btn('arrow-counterclockwise', 'undo', '되돌리기(Ctrl+Z)'),
        _tb_btn('eraser', 'removeFormat', '서식 지우기'),
    ], className='d-flex flex-wrap align-items-center gap-1 border border-bottom-0 rounded-top bg-light px-2 py-1')



def rich_editor(prefix: str, initial_html: str, min_height: str = '260px'):
    return html.Div([
        editor_toolbar(),
        html.Div(id=f'{prefix}-body-editor', contentEditable='true', className='form-control rich-editor',
                 **{'data-store': f'{prefix}-body'},
                 style={'minHeight': min_height, 'maxHeight': '480px', 'overflowY': 'auto',
                        'fontFamily': "'Malgun Gothic', sans-serif", 'fontSize': '14px', 'lineHeight': '1.7',
                        'borderTopLeftRadius': 0, 'borderTopRightRadius': 0}),
        dcc.Store(id=f'{prefix}-body', data=initial_html),
        dcc.Store(id=f'{prefix}-editor-init'),
    ], className='rich-wrap')


def register_rich_editor(prefix: str) -> None:
    """저장된 HTML을 편집기에 처음 채움(내용이 같으면 그대로 — 입력 중 커서가 튀지 않게)."""
    dash.clientside_callback(
        """function(data) {
            const ed = document.getElementById('%s-body-editor');
            if (ed && typeof data === 'string' && ed.innerHTML !== data) { ed.innerHTML = data; }
            return window.dash_clientside.no_update;
        }""" % prefix,
        Output(f'{prefix}-editor-init', 'data'), Input(f'{prefix}-body', 'data'))
