"""
관리자 페이지(pages/admin.py) 여러 탭이 함께 쓰는 순수 헬퍼/상수 모음 —
콜백은 없다(2026-09-28, pages/admin.py 분할 리팩터링으로 신설). 이 모듈
자체는 어떤 탭에도 속하지 않으므로 components/admin_*_tab.py들이 필요한
것만 가져다 쓴다.
"""
import uuid

import dash_bootstrap_components as dbc
from dash import dcc, html

_STATUS_COLORS = {'성공': 'success', '실패': 'danger', '실행중': 'info'}


def _alert(msg: str, color: str):
    return dbc.Alert(msg, color=color, dismissable=True, className='py-2 small mb-0')


def _upload_box(key: str, slot: str, small_label: str = '', multiple: bool = False) -> html.Div:
    """단일 업로드 드롭존. slot: 'single'(대부분) | 'legacy'/'new'(직무이력 전용).
    multiple=True(대량 백필 대상 항목만, needs_valid_date 참고)면 파일을
    여러 개 한 번에 선택할 수 있다 — 파일명이 "_YYYYMM"으로 끝나는 것만
    백필로 인식되고(pipeline/backfill_utils.py), 그 외는 무시된다."""
    return dcc.Upload(
        id={'type': 'du-upload', 'key': key, 'slot': slot},
        children=html.Div([
            html.I(className='bi bi-cloud-arrow-up me-1'),
            small_label or '클릭 또는 드래그해 업로드',
        ], className='small text-muted'),
        style={
            'padding': '4px 8px', 'border': '1px dashed #adb5bd', 'borderRadius': '4px',
            'textAlign': 'center', 'cursor': 'pointer',
        },
        multiple=multiple,
    )


# ── 팀/리더 참조 그리드 — 체크박스 이동/삭제(2026-09-15, 2026-09-16 단순화) ────
# 체크박스로 고른 행 + 그 하위 조직 전체를 하나의 구간으로 묶어 삭제
# 버튼용으로 쓴다(로직은 assets/team_refer_grid.js가 2026-09-17에 제거된
# 행 드래그 재정렬 기능에서 쓰던 것과 같은 발상 — 부모 행과 그 하위
# 자손 행은 항상 화면에 연속으로 붙어 나온다는 성질을 이용). 2026-09-16:
# "구조" 열(부모-자식 아이콘 표시)을 없애면서, 이동은 "체크한 행 하나만
# 개별로, 상위부서 경계와 무관하게 자유롭게" 이동하는 방식으로 단순화
# (사용자 확정) — 하위 조직을 함께 묶어 이동시키던 로직(_preceding_
# sibling_range 등)은 제거. 삭제만 기존처럼 하위 조직 전체를 함께
# 지운다(사용자 확정 — 하위 조직이 남아있으면 그 소속 정보 때문에 상위
# 조직이 자동으로 다시 생성돼 사실상 삭제되지 않는 문제가 있어, 삭제는
# 계속 하위 조직 포함이 맞음).
#
# 아래 _renumbered/_ensure_rid는 team_refer 탭뿐 아니라 직군 예외자 탭도
# 함께 쓰는 공용 함수라 여기(admin_shared)에 둔다.


def _renumbered(rows: list) -> list:
    """현재 순서(정렬/추가/삭제/이동 반영 후) 그대로 1부터 'No.'를 다시
    매긴다 — 화면 표시 전용이라 저장 대상 데이터에는 포함되지 않는다.
    (2026-09-16: 계층 구조 표시('_tree') 관련 로직은 "구조" 열 제거와
    함께 삭제 — team_refer 탭뿐 아니라 직군 예외자 탭도 함께 쓰는 공용
    함수라 그 탭 행에는 애초에 의미 없는 필드였다.) 조직코드(dep_code)
    재배당은 이 함수의 책임이 아니다(_renumber_dep_codes() 참고 —
    이동/삭제/행추가 콜백이 필요할 때만 명시적으로 호출). 팀/리더 참조
    탭은 2026-09-17 AG Grid 전환 이후에도 이 함수를 그대로 쓴다 —
    valueGetter로 rowIndex에서 매번 계산하는 방식을 시도했으나, getRowId를
    쓰는 AG Grid는 행 순서만 바뀌었을 때(삭제/이동) 그 값을 다시 그리지
    않는 문제를 직접 확인해(_no 필드 자체가 실제로 안 바뀌면 셀이
    갱신되지 않음) 되돌렸다."""
    for i, r in enumerate(rows, start=1):
        r['_no'] = i
    return rows


def _ensure_rid(rows: list) -> list:
    """AG Grid(dash-ag-grid)는 안정적인 행 식별자(getRowId)가 필요하다 —
    이름처럼 편집 가능한 필드를 키로 쓰면 값이 바뀌거나 겹칠 때 선택/이동
    상태가 엉킬 수 있어, 로드/생성 시점에 한 번만 부여하는 합성 필드를
    쓴다. team_refer_store.KOREAN_COLUMNS에 없으므로 save_snapshot()이
    그대로 무시한다(2026-09-17, AG Grid 전환)."""
    for r in rows:
        r.setdefault('_rid', uuid.uuid4().hex[:12])
    return rows


def _mark_stale_rows(rows: list, highlight_date: str | None) -> list:
    """엑셀 일괄 업로드 직후에만, 이번 업로드 날짜(highlight_date,
    'YYYY-MM-DD')와 그 행의 마지막 저장일(team_refer_store.list_editable_
    rows()가 채워주는 `_valid_date`)이 다른 행에 `_stale=True`를 표시한다
    (2026-09-16, 사용자 요청). intake 원본의 1~3단계부서명(경로 텍스트)이
    조금만 바뀌어도 dep_id가 새로 계산돼, 비공식소속부서명은 같은데 예전
    dep_id로 저장된 "과거 데이터"가 새 항목과 나란히 남는 경우가 있다 —
    이걸 색으로 표시해 관리자가 눈으로 찾아 수동으로 정리("선택 삭제")할
    수 있게 하는 용도다. getRowStyle의 styleConditions가 이 값을 읽어
    배경색을 강조한다.

    highlight_date가 없으면(업로드 직후가 아니라 평소 화면 로드/조회 시)
    아무 것도 표시하지 않는다 — 조직마다 마지막 저장일이 원래 제각각인
    게 정상이라(날짜 기반 누적 테이블), 업로드와 무관하게 상시로 켜두면
    맞지 않는 조직마다 항상 색이 칠해져 오히려 혼란을 준다(사용자 확정
    — "엑셀 업로드 직후에만 특별히 보여주는 형태")."""
    if not highlight_date:
        for r in rows:
            r.pop('_stale', None)
        return rows
    for r in rows:
        r['_stale'] = bool(r.get('_valid_date')) and r['_valid_date'] != highlight_date
    return rows


def _split_hidden_rows(rows: list) -> tuple[list, list]:
    """비공식소속부서명이 빈 행(리프에 실제 배정이 없는 조직 — 조직도
    트리를 이루기 위한 상위 노드로만 쓰이는 행, 2026-09-15 요청)을
    가독성을 위해 그리드 화면에서 숨긴다. dep_id/upper_dep_id/team_layer
    (부모-자식 관계에 필수)는 이 그리드의 편집 컬럼이 아니라 1/2/3단계
    부서명 "전체 경로"에서 매번 자동 계산되므로(pipeline/team_hierarchy.py),
    이 행들을 화면에서만 안 보이게 해도 그 계산에 필요한 정보(1/2/3단계
    부서명)는 여전히 온전히 보존된다 — 실제로 삭제하지 않고
    team-refer-hidden-rows Store에 그대로 담아 두었다가, 저장(team_refer_save)
    시 화면에 보이는(편집된) 행과 합쳐서 반영한다(안 그러면 tombstone_
    missing_dep_ids()가 "이번 저장에 없다"고 판단해 실수로 삭제될 것).
    반환값은 (화면에 보일 행, 숨길 행) 순서."""
    visible, hidden = [], []
    for r in rows:
        (hidden if not str(r.get('비공식소속부서명') or '').strip() else visible).append(r)
    return visible, hidden


def _run_status_view(row: dict):
    """엑셀 업로드 섹션의 "최종실행이력/실행결과" 미니 표시 — 팀/리더 참조·
    직군 예외자 탭의 초기 렌더와 데이터 업데이트 탭의 폴링 갱신
    (data_update_poll)이 모두 공유한다(원래 이름 _team_refer_run_status_view
    — 이름과 달리 처음부터 범용이었다, 2026-09-28 분할 리팩터링에서
    admin_shared로 옮기며 이름도 실제 쓰임에 맞게 변경)."""
    status = row['status']
    status_badge = (
        dbc.Badge([html.I(className='bi bi-arrow-repeat me-1'), '실행중'], color='info')
        if status == '실행중'
        else dbc.Badge(status or '-', color=_STATUS_COLORS.get(status, 'secondary'))
    )
    source = row.get('source', '')
    source_badge = (
        dbc.Badge(source, color='info' if source == 'API' else 'secondary',
                  className='ms-1', style={'fontSize': '0.62rem'})
        if source else None
    )
    return html.Div([
        html.Div([html.Span(row['last_run_at'] or '-', className='small'), source_badge]),
        html.Div([status_badge, html.Span(row['message'], className='small text-muted ms-2',
                                           title=row['message'])], className='mt-1'),
    ])
