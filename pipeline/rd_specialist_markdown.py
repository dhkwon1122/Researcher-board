"""
"콘솔"형 정적 HTML 리포트 공용 인프라(CONSOLE_STYLE/console_page/stat_row_html/
group_ordered/build_org_tree/strength_section_html/map_link_html 등)와, 과제
카드 렌더링(project_card_html, process_project_expertise.py 전용)을 모아 둔
모듈. 세 개 리포트(연구원 유사도/과제 전문성/연구원 전문성)가 모두 이 공용
인프라 위에서 렌더링되므로, 색상 토큰이나 사이드바·카드 스타일을 바꾸려면
이 파일만 고치면 된다.

(예전에는 "R&D Project Specialist Agent" 페르소나 프롬프트와 그 마크다운
출력을 파싱하는 헬퍼들도 이 모듈에 있었지만, 과제↔연구원 매칭 기능 자체가
제거되면서 함께 삭제됐다 — data/processed/CLAUDE.md 참고.)
"""

import html
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import call_llm


def group_ordered(items: list, key_fn) -> list:
    """items를 key_fn(item) 그룹 키 기준으로 묶어 [(key, [item, ...]), ...]로 반환.
    HTML 리포트를 부서/조직 등 기준으로 시각적으로 묶어 보여줄 때 사용
    (process_researcher_expertise.py, process_project_expertise.py 등). 그룹은
    키 문자열 기준 정렬하되, 빈 키('미분류')는 항상 맨 뒤로 보낸다."""
    groups: dict = {}
    for item in items:
        key = key_fn(item) or '미분류'
        groups.setdefault(key, []).append(item)
    keys = sorted(groups.keys(), key=lambda k: (k == '미분류', k))
    return [(k, groups[k]) for k in keys]


# ── 조직도(팀참조시트/team_refer.csv 기반) ──────────────────────────────────
# "보유 전문성" 콘솔의 연구원/연구원↔연구원/연구원↔과제 3개 리포트가 좌측
# 사이드바에 공통으로 쓰는 확장/축소 가능한 조직도 트리 인프라.


def read_team_refer(out_dir: str) -> list:
    """team_refer.csv(또는 DB 테이블 team_refer)를 dict 리스트로 반환한다
    (build_org_tree()가 dep_id/upper_dep_id로 부모-자식 관계를 판단하므로
    행 순서는 무관). DB(DATABASE_URL)가 설정돼 있으면 services.data_store.
    read_processed()로 DB를 우선 읽고, 없으면 out_dir/team_refer.csv를 직접
    읽는다 — 이 함수는 파이프라인 CLI(데이터 파일에 직접 접근 가능한 환경)
    뿐 아니라 실행 중인 앱 프로세스에서도 호출된다(pages/researcher_similarity_map.py가
    "보유 전문성" 리포트를 화면 진입 시 build_html()로 그때그때 렌더링 —
    data/processed/CLAUDE.md 2026-08-19 참고). 앱 서버에 team_refer.csv가
    없어도(DB만 붙어 있어도) 조직도가 정상적으로 만들어지도록 DB를 우선
    시도한다. 파일도 DB도 없으면 빈 리스트(호출부가 조직도 없이 기존
    방식으로 폴백할 수 있도록)."""
    try:
        _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from services.data_store import read_processed
        df = read_processed('team_refer')
        if not df.empty:
            # read_processed()는 'researcher_id' 컬럼만 명시적으로 문자열화하고
            # 나머지 컬럼의 빈 셀은 (DB 경로가 아니라 CSV 폴백 경로일 때) NaN으로
            # 남긴다 — build_org_tree()가 upper_dep_id 등에 바로 .strip()을
            # 호출하므로 여기서 직접 한 번 더 채워야 안전하다.
            return df.fillna('').to_dict('records')
    except Exception:
        pass

    path = os.path.join(out_dir, 'team_refer.csv')
    if not os.path.exists(path):
        return []
    import pandas as pd
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    return df.to_dict('records')


def build_org_tree(rows: list) -> list:
    """team_refer.csv 행들을 dep_id(자신의 조직 ID)/upper_dep_id(상위 조직의
    dep_id) 기준으로 계층화한다 — 각 행이 자신의 부모를 명시적으로 갖고 있으므로
    파일에 적힌 행 순서와 무관하게 정확한 계층을 구성한다(예전 team_layer
    스택 방식은 엑셀이 계층 순서대로 적혀 있다는 전제가 깨지면 잘못된 트리가
    만들어졌음). upper_dep_id가 비어 있거나, 가리키는 dep_id가 데이터에 없으면
    최상위 노드로 취급한다. 각 노드의 자식들은 code3(조직 위계·표시 순서 코드)
    오름차순으로 정렬한다.
    반환: 최상위 노드 리스트, 각 노드는
      {project_name, end_name, team_layer(int), researcher_id, name,
       assignment_name, code3, dep_id, upper_dep_id, children: [...]}"""
    nodes: list = []
    nodes_by_id: dict = {}
    for row in rows:
        try:
            layer = int(row.get('team_layer') or 0)
        except (TypeError, ValueError):
            continue
        if layer <= 0:
            continue
        node = {**row, 'team_layer': layer, 'children': []}
        nodes.append(node)
        dep_id = (row.get('dep_id') or '').strip()
        if dep_id:
            nodes_by_id[dep_id] = node

    roots: list = []
    for node in nodes:
        upper_dep_id = (node.get('upper_dep_id') or '').strip()
        parent = nodes_by_id.get(upper_dep_id) if upper_dep_id else None
        (parent['children'] if parent is not None else roots).append(node)

    def _sort(items: list):
        items.sort(key=lambda n: n.get('code3', ''))
        for n in items:
            _sort(n['children'])

    _sort(roots)
    return roots


def nested_nav_html(groups: list) -> str:
    """[(그룹명, [(href, label, count|None), ...]), ...] -> 그룹명을 <details>로
    접고 펼 수 있는 2단 네비게이션 HTML(조직도 org-node와 같은 시각 스타일
    재사용, 기본은 접힌 상태). 연구원↔과제 리포트의 "과제 기준" 사이드바에서
    부서 밑에 '과제' 그룹을 두고, 그 안에 직무 목록을 보여줄 때 쓴다(부서→
    과제→직무 2단 중첩 — 부서→연구원 패턴과 동일한 클릭 경험)."""
    parts = []
    for label, items in groups:
        if not items:
            continue
        inner = nav_items_html(items)
        parts.append(
            f'<details class="org-node"><summary><span class="org-node-head">{html.escape(label)}</span></summary>'
            f'<div class="org-node-body">{inner}</div></details>'
        )
    return ''.join(parts)


def org_search_input_html() -> str:
    """조직도 바로 위에 붙는 이름/사번(또는 과제·직무명) 검색창. 실제 필터링
    동작은 _CONSOLE_SCRIPT의 공용 리스너가 처리한다(연구원/연구원↔연구원/
    연구원↔과제 사이드바가 모두 같은 클래스를 쓰므로 한 군데만 구현하면 됨)."""
    return '<input type="text" class="org-search-input" placeholder="이름 또는 사번으로 검색">'


def nav_items_html(items: list) -> str:
    """[(href, label, count|None), ...] -> nav-item 링크 목록 HTML. 조직도
    리프 노드에 붙는 연구원/과제·직무 목록에 재사용한다."""
    if not items:
        return ''
    rows = ''.join(
        f'<a class="nav-item" href="{href}"><span>{html.escape(label)}</span>'
        + (f'<span class="n-count">{count}</span>' if count is not None else '')
        + '</a>'
        for href, label, count in items
    )
    return f'<div class="org-node-people">{rows}</div>'


def org_tree_html(tree: list, node_content_fn=None) -> str:
    """조직도를 <details>/<summary> 중첩 구조로 렌더링한다(JS 없이 클릭으로
    확장/축소). 라벨은 '{과제명통일}({직책} {성명})' 형식(예: '기계시스템연구팀
    (PL 정재원)'). node_content_fn(node) -> str|None: 해당 조직 노드에 붙일
    추가 콘텐츠(nav_items_html로 만든 연구원/과제 목록 등) — 없으면 생략.
    team_layer 1~2(상위 조직)는 기본으로 펼쳐서 보여준다. 자신에게도, 하위
    조직 전체(재귀적으로)에도 연결된 콘텐츠가 하나도 없는 노드는 아예
    생략한다(회색 텍스트로 보여주지 않음) — 실제 매핑된 대상이 없는 조직을
    구경만 하게 두지 않기 위함. 하위 노드들은 .org-node-body로 감싸 들여쓰기
    (padding-left/border-left, CONSOLE_STYLE 참고)가 적용되게 한다."""
    def _label(node: dict) -> str:
        head = html.escape(node.get('end_name') or node.get('project_name') or '')
        assignment = (node.get('assignment_name') or '').strip()
        person = (node.get('name') or '').strip()
        who = f'{assignment} {person}'.strip()
        who_html = f' <span class="org-node-who">({html.escape(who)})</span>' if who else ''
        return f'<span class="org-node-head">{head}</span>{who_html}'

    def _node_html(node: dict) -> str:
        extra = (node_content_fn(node) if node_content_fn else '') or ''
        children_html = ''.join(_node_html(c) for c in node['children'])
        if not extra and not children_html:
            return ''
        body = extra + (f'<div class="org-node-body">{children_html}</div>' if children_html else '')
        open_attr = ' open' if node['team_layer'] <= 2 else ''
        return f'<details class="org-node"{open_attr}><summary>{_label(node)}</summary>{body}</details>'

    return f'<div class="org-tree">{"".join(_node_html(n) for n in tree)}</div>'


def map_link_html(researcher_id: str) -> str:
    """연구원 카드 우측 상단에 붙던 '전문성 MAP으로 이동' 아이콘. iframe
    안에서 그대로 클릭하면 부모(top) 문서를 이동시켜야 하므로 target="_top"
    필수 — 그래야 iframe 안이 아니라 실제 대시보드가 전문성 MAP 탭으로
    전환된다.

    사용자 요청으로 전문성 MAP 탭 자체가 숨김 처리되어(pages/researcher_similarity_map.py
    의 _MAP_TAB_HIDDEN 참고) "연구원"/"연구원 ↔ 연구원" 리포트의 card-top에서는
    더 이상 호출하지 않는다(process_researcher_expertise.py, process_researcher_similarity.py
    의 card-top 참고) — 숨겨진 탭으로 이어지는 죽은 링크를 남기지 않기 위함.
    함수 자체는 나중에 MAP 탭을 다시 열 경우를 위해 남겨둔다."""
    href = f'/researcher-similarity-map?highlight_researcher={researcher_id}'
    return (
        f'<a class="map-link" href="{href}" target="_top" title="전문성 MAP에서 위치 보기">'
        f'📍 전문성 MAP</a>'
    )


def profile_link_html(researcher_id: str) -> str:
    """연구원 카드 우측 상단에 붙는 '연구원 프로필로 이동' 아이콘 + '새 창으로
    열기' 아이콘. researcher_profile.py의 layout(id=...)이 쿼리 파라미터
    ?id=researcher_id를 그대로 받아 그 사람으로 선택해 보여준다. 기본 아이콘은
    iframe 밖(최상위 대시보드)에서 그대로 이동해야 하므로 target="_top", 새 창
    아이콘은 현재 화면을 유지한 채 프로필만 별도 창/탭으로 열도록 target="_blank"."""
    href = f'/researcher-profile?id={researcher_id}'
    return (
        f'<a class="map-link" href="{href}" target="_top" title="연구원 프로필로 이동">'
        f'👤 프로필</a>'
        f'<a class="map-link" href="{href}" target="_blank" title="연구원 프로필을 새 창으로 열기">'
        f'↗</a>'
    )


def profile_icon_link_html(researcher_id: str) -> str:
    """유사 연구원 표처럼 좁은 공간(테이블 행)에 붙이는 아이콘 전용(텍스트
    없는) 프로필 이동 링크 — profile_link_html의 소형 버전. 이동(target="_top")
    아이콘과 새 창으로 열기(target="_blank") 아이콘을 나란히 붙인다."""
    href = f'/researcher-profile?id={researcher_id}'
    return (
        f'<a class="row-icon-link" href="{href}" target="_top" title="연구원 프로필로 이동">👤</a>'
        f'<a class="row-icon-link" href="{href}" target="_blank" title="연구원 프로필을 새 창으로 열기">↗</a>'
    )


def strength_section_html(fields: list, keywords: list) -> str:
    """강점 분야(chip)와 키워드(chip kw)를 "Strength Field"/"Strength Keywords"
    라벨로 구분해 보여준다 — 둘 다 칩만 이어 붙이면 어떤 게 분야이고 어떤 게
    키워드인지 구분이 안 되던 문제를 라벨로 해소한다(칩 형태 자체는 기존
    그대로 유지). 연구원 보유 전문성 분석.html/연구원 유사도.html이 공유."""
    if not fields and not keywords:
        return '<p class="empty">강점 분야/키워드 데이터 없음</p>'
    parts = []
    if fields:
        chips = ''.join(f'<span class="chip">{html.escape(f)}</span>' for f in fields)
        parts.append(f'<div class="chip-label">Strength Field</div><div class="chip-row">{chips}</div>')
    if keywords:
        chips = ''.join(f'<span class="chip kw">{html.escape(k)}</span>' for k in keywords)
        parts.append(f'<div class="chip-label">Strength Keywords</div><div class="chip-row">{chips}</div>')
    return ''.join(parts)


def _field_row_html(label: str, value: str) -> str:
    v = (value or '').strip()
    if not v or v == '확인 불가':
        return ''
    return f'<dt>{html.escape(label)}</dt><dd>{html.escape(v)}</dd>'


def _milestones_html(milestones: list) -> str:
    items = [m for m in (milestones or []) if str(m or '').strip()]
    if not items:
        return ''
    lis = ''.join(f'<li>{html.escape(str(m))}</li>' for m in items)
    return f'<div class="kv-block"><div class="kv-title">주요 추진 일정</div><ul class="kv-list">{lis}</ul></div>'


def _personnel_html(personnel: list) -> str:
    """process_project_expertise.py가 컨플루언스 문서에서 뽑아 researchers.csv와
    대조한 인력 목록을 카드로 렌더링. researcher_id가 매핑된 사람은 전문성
    MAP으로 바로 이동할 수 있는 링크를 붙이고, 매핑되지 않은 사람은 문서에
    적힌 원문 이름만 "미매칭"으로 표시한다(추측해서 잘못 배정하지 않기 위해)."""
    people = personnel or []
    if not people:
        return ''
    rows = []
    for p in people:
        name = html.escape(p.get('name', ''))
        suffix = p.get('name_suffix', '')
        name_disp = f'{name}({html.escape(suffix)})' if suffix else name
        rid = p.get('researcher_id', '')
        if rid:
            badge = (
                f'<a class="badge matched" href="/researcher-similarity-map?highlight_researcher={rid}" '
                f'target="_top" title="전문성 MAP에서 위치 보기">{html.escape(rid)}</a>'
            )
        else:
            badge = '<span class="badge unmatched">미매칭</span>'
        role = html.escape(p.get('role_description', '') or '(담당 업무 확인 불가)')
        rows.append(
            f'<div class="personnel-row"><div class="personnel-name">{name_disp} {badge}</div>'
            f'<div class="personnel-role">{role}</div></div>'
        )
    return (
        '<div class="kv-block"><div class="kv-title">문서 내 언급된 인력</div>'
        f'<div class="personnel-list">{"".join(rows)}</div></div>'
    )


def project_card_html(item: dict, anchor: str) -> str:
    """process_project_expertise.py가 컨플루언스 문서를 상세 분석한 결과(핵심
    기술/산출물/난제/배경/추진일정/기대효과/키워드/인력) 하나를 카드로
    렌더링. 예전에는 이 카드가 "R&D Project Specialist Agent"의 직무 딥다이브
    매핑을 함께 보여줬지만, 그 기능은 제거되고 문서 분석 자체가 더 상세해지는
    쪽으로 목적이 바뀌었다(data/processed/CLAUDE.md 참고)."""
    keywords = (item.get('keywords_kr') or []) + (item.get('keywords_en') or [])
    chip_row = ''.join(f'<span class="chip">{html.escape(k)}</span>' for k in keywords)

    kv_rows = ''.join([
        _field_row_html('핵심 기술', item.get('core_tech', '')),
        _field_row_html('최종 산출물', item.get('deliverable', '')),
        _field_row_html('기술적 난제', item.get('challenge', '')),
        _field_row_html('연구 배경', item.get('background', '')),
        _field_row_html('기대효과', item.get('expected_impact', '')),
    ])
    overview_html = f'<dl class="kv">{kv_rows}</dl>' if kv_rows else '<p class="empty">분석 데이터 없음</p>'

    extra_html = _milestones_html(item.get('milestones')) + _personnel_html(item.get('personnel'))

    return f'''<div class="card" id="{anchor}">
  <div class="card-top"><h3>{html.escape(item['project_name'])}</h3></div>
  {overview_html}
  <div class="chip-row">{chip_row}</div>
  {extra_html}
</div>'''


# ── 콘솔형 리포트 공용 CSS/셸 ────────────────────────────────────────────────
# 외부 CDN(Bootstrap/marked.js) 없이 완전히 독립적인 정적 페이지. 연구원 유사도/
# 과제 전문성/연구원 전문성 3개 리포트가 모두 동일한 색상 토큰과 사이드바+
# 요약통계+카드 문법을 공유해 한 가족처럼 보이도록 한다.
#
# 예전엔 @media (prefers-color-scheme: dark)로 OS/브라우저가 다크모드면 이
# 색상 토큰도 자동으로 어둡게 바뀌었는데, 이 리포트를 iframe으로 담는
# 대시보드 셸(app.py, dbc.themes.BOOTSTRAP)은 다크모드를 지원하지 않고 항상
# 밝은 테마라, 사용자 환경이 다크모드일 때 리포트만 따로 어두워져 화면이
# 어긋나 보였다(사용자 요청으로 발견). 라이트 토큰을 유일한 값으로 두고
# 미디어쿼리 분기 자체를 제거해 시스템 설정과 무관하게 항상 밝게 고정.
CONSOLE_STYLE = """
  :root {
    --bg: #f3f4f7; --sidebar: #ffffff; --panel: #ffffff; --line: #e2e4ea;
    --ink: #1a1d29; --ink-soft: #6b7080;
    --accent: #4453d6; --accent-weak: rgba(68,83,214,0.08);
    --good: #1f8a5f; --good-weak: rgba(31,138,95,0.1);
    --warn: #a3720a; --warn-weak: rgba(163,114,10,0.1);
    --low: #6b7080; --low-weak: rgba(107,112,128,0.1);
    --danger: #b23b3b; --danger-weak: rgba(178,59,59,0.1);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; display: flex; min-height: 100vh;
  }
  .sidebar {
    width: 500px; flex-shrink: 0; background: var(--sidebar);
    padding: 22px 16px; position: sticky; top: 0; height: 100vh; overflow-y: auto;
  }
  /* 사이드바/본문 사이 드래그 리사이즈 바(_CONSOLE_SCRIPT가 mousedown/mousemove로 폭 조절) */
  .split-divider {
    width: 6px; flex-shrink: 0; cursor: col-resize; background: var(--line);
    position: sticky; top: 0; height: 100vh;
  }
  .split-divider:hover { background: var(--accent); }
  /* 스크롤 시에만 나타나는 맨 위로 이동 버튼(우측 하단 고정) */
  .back-to-top {
    display: none; position: fixed; right: 24px; bottom: 24px; z-index: 20;
    width: 44px; height: 44px; border-radius: 50%; border: none;
    background: var(--accent); color: #fff; font-size: 1.1rem; font-weight: 700;
    cursor: pointer; box-shadow: 0 2px 10px rgba(0,0,0,0.22);
    align-items: center; justify-content: center;
  }
  .back-to-top.show { display: flex; }
  .back-to-top:hover { opacity: 0.85; }
  .sidebar h1 { font-size: 0.98rem; font-weight: 800; margin: 4px 6px 2px; letter-spacing: -0.01em; }
  .sidebar .tagline { font-size: 0.72rem; color: var(--ink-soft); margin: 0 6px 20px; line-height: 1.5; }
  .org-search-input {
    width: 100%; box-sizing: border-box; margin: 0 0 14px; padding: 7px 10px;
    font-size: 0.8rem; border: 1px solid var(--line); border-radius: 8px;
    background: var(--bg); color: var(--ink);
  }
  .org-search-input:focus { outline: none; border-color: var(--accent); }
  .nav-group { margin-bottom: 4px; }
  .nav-group-label {
    font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--ink-soft); font-weight: 700; padding: 10px 6px 4px;
  }
  .nav-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 8px; border-radius: 6px; font-size: 0.82rem;
    text-decoration: none; color: var(--ink);
  }
  .nav-item:hover { background: var(--accent-weak); }
  .nav-item .n-count { font-size: 0.68rem; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
  /* 조직도(팀참조시트 기반) — JS 없이 <details>/<summary> 중첩으로 확장/축소 */
  .org-tree { margin-bottom: 4px; }
  details.org-node { margin: 1px 0; }
  details.org-node > summary {
    cursor: pointer; list-style: none; padding: 6px 8px; border-radius: 6px;
    font-size: 0.8rem; font-weight: 600; color: var(--ink); display: flex; align-items: baseline; gap: 4px;
  }
  details.org-node > summary::-webkit-details-marker { display: none; }
  details.org-node > summary::before { content: '▸'; color: var(--ink-soft); font-size: 0.7rem; }
  details.org-node[open] > summary::before { content: '▾'; }
  details.org-node > summary:hover { background: var(--accent-weak); }
  .org-node-head { font-weight: 700; }
  .org-node-who { color: var(--ink-soft); font-weight: 500; }
  .org-node-body { padding-left: 12px; border-left: 1px solid var(--line); margin-left: 8px; }
  .org-node-people { padding-left: 12px; border-left: 1px solid var(--line); margin: 0 0 4px 8px; }
  main { flex: 1; min-width: 0; padding: 32px 40px 100px; }
  .content { max-width: 960px; }
  .stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr)); gap: 12px; margin-bottom: 28px; }
  .stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
  .stat .num { font-size: 1.5rem; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
  .stat .lbl { font-size: 0.72rem; color: var(--ink-soft); margin-top: 2px; }
  .dept-heading {
    font-size: 0.78rem; font-weight: 700; color: var(--ink-soft); text-transform: uppercase;
    letter-spacing: 0.06em; margin: 32px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line);
  }
  .dept-heading:first-of-type { margin-top: 0; }
  .org-heading { font-size: 0.72rem; color: var(--ink-soft); margin: 16px 0 8px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; margin-bottom: 14px; }
  /* detail-view: 조직도에서 고른 연구원 한 명만 보여준다(전체 목록 나열 대신) —
     기본은 CSS로 전부 숨기고, _CONSOLE_SCRIPT가 클릭한 카드에만 .detail-active를
     붙인다. 카드가 .sim-sections처럼 중첩 래퍼 안에 있어도 맞도록 자손 선택자 사용. */
  body.detail-view .content .card,
  body.detail-view .content .dept-heading,
  body.detail-view .content .org-heading { display: none; }
  body.detail-view .content .card.detail-active { display: block; }
  .detail-placeholder { display: none; }
  body.detail-view .detail-placeholder {
    display: block; color: var(--ink-soft); font-size: 0.88rem;
    border: 1px dashed var(--line); border-radius: 10px; padding: 24px; text-align: center;
  }
  .card-top { display: flex; align-items: center; gap: 10px; margin-bottom: 3px; }
  .card-top h3 { margin: 0; font-size: 1rem; font-weight: 700; }
  /* card-top 우측에 모이는 이동 아이콘 묶음(프로필/전문성 MAP) — 개별
     .map-link가 아니라 이 래퍼에 margin-left:auto를 둬서, 아이콘이 몇 개든
     항상 한 덩어리로 오른쪽에 붙게 한다. */
  .card-icons { margin-left: auto; flex-shrink: 0; display: flex; align-items: center; gap: 6px; }
  .map-link {
    flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px;
    font-size: 0.72rem; font-weight: 600; color: var(--ink-soft); text-decoration: none;
    border: 1px solid var(--line); border-radius: 999px; padding: 3px 10px 3px 8px;
  }
  .map-link:hover { color: var(--accent); border-color: var(--accent); background: var(--accent-weak); }
  .row-icon-link { text-decoration: none; opacity: 0.6; margin-left: 6px; font-size: 0.82rem; }
  .row-icon-link:hover { opacity: 1; }
  .card-sub { font-size: 0.78rem; color: var(--ink-soft); margin-bottom: 12px; }
  .badge { font-size: 0.66rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
  .badge.senior { background: var(--accent-weak); color: var(--accent); }
  .badge.junior { background: var(--low-weak); color: var(--ink-soft); }
  /* project_card_html의 인력 매칭 배지(researcher_id 매핑 성공/실패) */
  a.badge.matched { background: var(--good-weak); color: var(--good); text-decoration: none; }
  a.badge.matched:hover { background: var(--good); color: #fff; }
  .badge.unmatched { background: var(--low-weak); color: var(--ink-soft); }
  .personnel-list { display: flex; flex-direction: column; gap: 8px; }
  .personnel-row { border-top: 1px solid var(--line); padding-top: 8px; }
  .personnel-row:first-child { border-top: none; padding-top: 0; }
  .personnel-name { font-size: 0.78rem; font-weight: 700; display: flex; align-items: center; gap: 8px; }
  .personnel-role { font-size: 0.76rem; color: var(--ink-soft); margin-top: 2px; }
  .chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }
  .chip { font-size: 0.7rem; padding: 3px 9px; border-radius: 6px; background: var(--accent-weak); color: var(--accent); font-weight: 600; }
  .chip.kw { background: var(--bg); color: var(--ink-soft); border: 1px solid var(--line); }
  /* strength_fields/strength_keywords 칩 그룹 위에 붙는 라벨(둘을 구분하기 위함) */
  .chip-label {
    font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent);
    font-weight: 700; margin: 10px 0 4px;
  }
  .chip-label:first-child { margin-top: 0; }
  .table-wrap { overflow-x: auto; }
  table.match-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  table.match-table th {
    text-align: left; font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--ink-soft); font-weight: 700; padding: 6px 8px; border-bottom: 1px solid var(--line);
  }
  table.match-table td { padding: 9px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  table.match-table tr:last-child td { border-bottom: none; }
  .m-name { font-weight: 700; }
  .m-dept { font-size: 0.72rem; color: var(--ink-soft); }
  .m-score { font-variant-numeric: tabular-nums; font-weight: 700; white-space: nowrap; }
  .pill { display: inline-block; font-size: 0.68rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
  .pill.good { background: var(--good-weak); color: var(--good); }
  .pill.warn { background: var(--warn-weak); color: var(--warn); }
  .pill.low { background: var(--low-weak); color: var(--low); }
  .pill.danger { background: var(--danger-weak); color: var(--danger); }
  .m-ev, .m-ev-text { margin: 0; padding-left: 16px; color: var(--ink-soft); font-size: 0.78rem; }
  .m-ev-text { padding-left: 0; }
  .m-ev li { margin: 1px 0; }
  .m-warn { color: var(--danger); font-size: 0.74rem; margin-top: 2px; }
  .empty { color: var(--ink-soft); font-size: 0.82rem; font-style: italic; }
  .kv-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px,1fr)); gap: 16px; margin-top: 4px; }
  .kv-block { background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
  .kv-block .kv-title {
    font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent);
    font-weight: 700; margin-bottom: 6px;
  }
  dl.kv { margin: 0; font-size: 0.78rem; }
  dl.kv dt { color: var(--ink-soft); font-weight: 600; margin-top: 6px; }
  dl.kv dt:first-child { margin-top: 0; }
  dl.kv dd { margin: 1px 0 0; color: var(--ink); }
  /* key_responsibilities/domain_knowledge_skill처럼 문장형 항목 리스트를 보여줄 때 씀(kv-block과 짝) */
  ul.kv-list { margin: 0; padding-left: 18px; font-size: 0.78rem; color: var(--ink); }
  ul.kv-list li { margin-top: 4px; }
  ul.kv-list li:first-child { margin-top: 0; }
  /* CSS 전용 표시 개수 토글(연구원 ↔ 연구원 리포트, JS 없이 radio + 형제 선택자로
     행을 숨김/표시 — 데이터는 이미 서버에서 최대 개수까지 저장돼 있음) */
  input.cnt-radio { display: none; }
  .count-bar {
    display: flex; align-items: center; justify-content: flex-end; gap: 6px;
    margin-bottom: 16px; position: sticky; top: 0; background: var(--bg);
    padding: 6px 0; z-index: 3;
  }
  .count-bar span { font-size: 0.72rem; color: var(--ink-soft); margin-right: 2px; }
  .count-bar label {
    padding: 4px 12px; font-size: 0.78rem; font-weight: 600; color: var(--ink-soft);
    border: 1px solid var(--line); border-radius: 999px; cursor: pointer;
  }
  #count-3:checked ~ .count-bar label[for="count-3"],
  #count-5:checked ~ .count-bar label[for="count-5"],
  #count-10:checked ~ .count-bar label[for="count-10"] {
    background: var(--accent); border-color: var(--accent); color: #fff;
  }
  #count-3:checked ~ .sim-sections table.match-table tbody tr:nth-child(n+4) { display: none; }
  #count-5:checked ~ .sim-sections table.match-table tbody tr:nth-child(n+6) { display: none; }
  @media (max-width: 820px) {
    .sidebar, .split-divider { display: none; }
    main { padding: 24px 18px 80px; }
  }
"""



# 사이드바 폭 드래그 리사이즈 + 프래그먼트 링크(#anchor) 클릭 스크롤. 이 리포트들은
# srcDoc iframe으로 임베드되는데(Dash "보유 전문성" 화면), <a href="#anchor">의
# 브라우저 기본 동작에 맡기면 iframe이 아니라 최상위 Dash 페이지 전체가
# ".../researcher-similarity-map#anchor"로 새로고침되어(버 실측 확인) 화면
# 상태가 전부 날아간다 — 그래서 클릭을 가로채 preventDefault 후 같은 문서 안에서
# 직접 scrollIntoView 한다(이 두 기능을 위해서만 최소한의 JS를 둔다 — 나머지
# 인터랙션은 전부 CSS 전용 유지).
_CONSOLE_SCRIPT = """
(function(){
  var sidebar = document.querySelector('.sidebar');
  var divider = document.getElementById('split-divider');
  if (sidebar && divider) {
    var dragging = false;
    divider.addEventListener('mousedown', function(e){
      dragging = true;
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'col-resize';
      e.preventDefault();
    });
    document.addEventListener('mousemove', function(e){
      if (!dragging) return;
      var w = Math.min(Math.max(e.clientX, 160), 600);
      sidebar.style.width = w + 'px';
    });
    document.addEventListener('mouseup', function(){
      if (!dragging) return;
      dragging = false;
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    });
  }

  document.addEventListener('click', function(e){
    var a = e.target.closest('a[href^="#"]');
    if (!a) return;
    var id = a.getAttribute('href').slice(1);
    var el = id && document.getElementById(id);
    if (!el) return;
    e.preventDefault();
    // detail-view(연구원/연구원↔연구원 리포트): 조직도에서 고른 카드 하나만
    // 보이도록 .detail-active를 옮겨 붙인다. 나머지 카드/구분 헤딩은 CSS가 숨김.
    if (document.body.classList.contains('detail-view')) {
      document.querySelectorAll('.content .card.detail-active').forEach(function(c){
        c.classList.remove('detail-active');
      });
      if (el.classList.contains('card')) {
        el.classList.add('detail-active');
        var placeholder = document.querySelector('.detail-placeholder');
        if (placeholder) placeholder.style.display = 'none';
      }
    }
    el.scrollIntoView({block: 'start'});
    el.style.outline = '2px solid #4453d6';
    el.style.outlineOffset = '2px';
  });

  var backTop = document.getElementById('back-to-top');
  if (backTop) {
    window.addEventListener('scroll', function(){
      backTop.classList.toggle('show', window.scrollY > 400);
    });
    backTop.addEventListener('click', function(){
      window.scrollTo({top: 0, behavior: 'smooth'});
    });
  }

  // 조직도 검색(이름/사번 또는 과제·직무명) — 일치하지 않는 nav-item은 숨기고,
  // 그 결과 화면에 남는 항목이 하나도 없는 조직 노드(details.org-node)는
  // 통째로 숨긴다. 일치 항목이 있으면 펼쳐서 바로 보이게 한다.
  document.querySelectorAll('.org-search-input').forEach(function(input){
    input.addEventListener('input', function(){
      var q = input.value.trim().toLowerCase();
      var root = input.closest('.sidebar') || document;
      root.querySelectorAll('.nav-item').forEach(function(item){
        var match = !q || item.textContent.toLowerCase().indexOf(q) !== -1;
        item.style.display = match ? '' : 'none';
      });
      var nodes = root.querySelectorAll('details.org-node');
      for (var i = nodes.length - 1; i >= 0; i--) {
        var node = nodes[i];
        if (!q) { node.style.display = ''; continue; }
        var hasVisible = Array.prototype.some.call(
          node.querySelectorAll('.nav-item'),
          function(it){ return it.style.display !== 'none'; }
        );
        node.style.display = hasVisible ? '' : 'none';
        if (hasVisible) node.open = true;
      }
    });
  });
})();
"""


def console_page(title: str, sidebar_html: str, body_html: str, detail_view: bool = False) -> str:
    """콘솔형 리포트 공용 페이지 셸. 외부 CDN 없이 완전히 독립적인 정적 HTML
    문서를 만든다(연구원 유사도/과제 전문성/연구원 전문성/매칭 4개 리포트가
    공유). 사이드바/본문 사이 드래그 리사이즈 바와 프래그먼트 링크 스크롤
    보정을 위해 _CONSOLE_SCRIPT를 함께 싣는다(그 외 인터랙션은 CSS 전용).

    detail_view=True면(연구원/연구원↔연구원 리포트) 카드를 전부 나열하지
    않고, 조직도에서 연구원을 클릭해야 그 사람 카드 하나만 보이는 모드로
    전환한다 — <body>에 detail-view 클래스를 붙이면 CONSOLE_STYLE의 관련
    규칙이 카드를 기본 숨김 처리하고, _CONSOLE_SCRIPT의 클릭 핸들러가
    선택된 카드에만 .detail-active를 옮겨 붙인다."""
    body_class = ' class="detail-view"' if detail_view else ''
    placeholder = (
        '<div class="detail-placeholder">◀ 왼쪽 조직도에서 연구원을 선택하면 정보가 표시됩니다.</div>'
        if detail_view else ''
    )
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CONSOLE_STYLE}</style>
</head>
<body{body_class}>
<nav class="sidebar">{sidebar_html}</nav>
<div class="split-divider" id="split-divider"></div>
<main><div class="content">{placeholder}{body_html}</div></main>
<button id="back-to-top" class="back-to-top" title="맨 위로" aria-label="맨 위로">↑</button>
<script>{_CONSOLE_SCRIPT}</script>
</body>
</html>'''


def stat_row_html(stats: list) -> str:
    """[(값, 라벨), ...] -> 요약 통계 카드 행 HTML."""
    cells = ''.join(
        f'<div class="stat"><div class="num">{v}</div><div class="lbl">{html.escape(l)}</div></div>'
        for v, l in stats
    )
    return f'<div class="stat-row">{cells}</div>'


def coverage_stat(analyzed: int, total: int, label: str) -> tuple:
    """실제로 분석/매칭된 인원(또는 과제) 수를 전체 대상 모수 대비로 보여주는
    커버리지 스탯 카드 하나. total이 0이면(모수를 알 수 없으면) analyzed만
    표시한다 — 분모가 0이라 나눌 수 없는 극단적 케이스에서도 안전하게 표시."""
    value = f'{analyzed}/{total}' if total else str(analyzed)
    return (value, label)


def generated_at_stat() -> tuple:
    """리포트를 실제로 생성한 시각(이 함수가 호출되는 시점) — 화면이 "언제 기준"
    데이터인지 한눈에 보여주기 위한 스탯 카드 하나."""
    return (datetime.now().strftime('%Y-%m-%d %H:%M'), '마지막 갱신')
