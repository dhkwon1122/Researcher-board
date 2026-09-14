// pages/admin.py의 "팀/리더 참조" 그리드(dash_table.DataTable,
// id="team-refer-table", 래퍼 id="team-refer-grid-wrap") 전용 보강 스크립트.
// dash_table 자체에는 없는 3가지를 추가한다(2026-09-03):
//
//  1) 자동채움 가이드(드롭다운) — 편집 중인 셀의 <input>에
//     list="du-datalist::{컬럼명}"을 걸어 브라우저 네이티브 자동완성
//     목록(<datalist>)을 띄운다. 후보는 pages/admin.py의
//     team_refer_sync_suggestions 콜백이 team-refer-suggestions Store에
//     써 둔 값(그 컬럼에 이미 쓰인 값들 — 상위부서ID만 예외로 부서ID 값)을
//     그대로 쓴다. dash_table 자체 dropdown(presentation='dropdown')은
//     react-select 기반이라 목록에 없는 값은 아예 입력할 수 없어(선택
//     전용) "가이드"가 아니라 "제한"이 되므로, 자유 입력이 계속 가능한
//     datalist로 구현했다.
//
//  2) 편집 중인 셀에서 마우스로 클릭한 위치로 커서 이동 — dash_table은
//     셀이 활성화되는 모든 mouseup에서 setSelectionRange(0, 전체길이)로
//     강제 전체선택해버려(async-table.js의 zr 핸들러, is_focused 여부와
//     무관하게 항상 실행됨) 클릭 위치가 항상 무시되고 텍스트 끝에서부터만
//     수정해야 했다. dash_table의 처리가 끝난 다음 macrotask(setTimeout 0)
//     에서, 캔버스로 실제 폰트 폭을 재 클릭 좌표에 해당하는 글자 인덱스를
//     계산해 커서를 그 자리로 다시 옮긴다.
//
//  3) F2로 편집 모드 진입 — dash_table은 셀이 활성화되면(클릭이든 Tab/
//     Enter로 이동해오든) 항상 <input>을 보여주지만, 실제로 방향키가
//     "텍스트 내 커서 이동"으로 동작하는지 "옆 셀로 이동"으로 동작하는지는
//     dash_table 내부의 is_focused라는 별도 상태값에 달려 있다(둘 다
//     화면에는 똑같이 <input>이 보여서 구분이 안 된다) — Tab/Enter로 옮겨온
//     셀은 항상 is_focused=false(방향키=셀 이동, Backspace=셀 전체 지우기)
//     이고, 더블클릭해야만 is_focused=true(방향키=텍스트 내 커서 이동,
//     Backspace=글자 하나만 삭제)로 바뀐다. dash_table은 F2를 전혀 처리하지
//     않아 이 is_focused=true 전환을 마우스 없이는 할 방법이 없었다(직접
//     is_focused를 조작할 수 있는 공개 API도 없음 — Dash 컴포넌트 내부
//     React state라 우리 쪽 JS에서 흉내 낼 수도 없다). 그래서 F2를 누르면
//     실제 더블클릭과 똑같은 합성 dblclick 이벤트를 그 셀(<td>)에 실제로
//     발생시켜 dash_table 스스로 is_focused=true로 전환하게 하고, 그 다음
//     커서만 엑셀의 F2와 동일하게 맨 끝으로 옮긴다 — 이후 방향키/Backspace는
//     전부 dash_table의 정상적인 "편집 모드" 동작을 그대로 따른다(별도
//     가로채기 불필요).
//
//  4) 같은 부모(형제) 그룹 안에서만 행 전체를 드래그해 순서를 바꾼다
//     (2026-09-14 추가, 행 안의 데이터는 그대로 유지). services/
//     team_refer_store.py의 list_editable_rows()가 이제 계층적으로(부모
//     별로 묶어서) 정렬해 반환하므로, 같은 부모 밑 조직끼리는 항상 화면에
//     붙어서 보인다 — 그 인접한 블록 안에서만 드래그를 허용하고(다른
//     그룹 행 위로 드롭을 시도하면 조용히 무시), 드롭되면 재배치된 두
//     행에 "그 그룹이 이미 갖고 있던 조직코드 값들"을 새 순서에 맞게
//     재배당한다(새 번호를 만들지 않음 — 다른 그룹과 충돌하지 않음).
//     헤더 클릭 정렬이 활성화돼 있으면(sort_by 있음) 이 "형제끼리 붙어
//     있음" 가정이 깨지므로 드래그 자체를 비활성화한다.
//
//  5) "전체 선택/해제/위로/아래로/선택 삭제" 버튼(pages/admin.py의
//     .team-refer-sticky-toolbar)이 스크롤해도 항상 보이도록, 네비게이션
//     바(.app-navbar, sticky top)의 실제 렌더링 높이를 재서 CSS 변수
//     --app-navbar-height에 채워 넣는다(2026-09-16 추가 — 사용자가 아래쪽
//     행을 체크하려면 위로 스크롤해 버튼을 누르고 다시 아래로 스크롤해
//     결과를 봐야 해서 불편하다고 요청). 고정 픽셀을 CSS에 그대로 박아두면
//     폰트 로딩 지연이나 화면 폭에 따라 네비게이션 바가 줄바꿈되는 경우
//     실제 높이와 어긋날 수 있어, 페이지 로드/리사이즈 때마다 다시 잰다.

(function () {
    var GRID_WRAP_ID = 'team-refer-grid-wrap';
    var initialized = false;
    var datalistCols = [];  // 자동채움 대상 컬럼명(마지막 동기화 기준)

    function syncNavbarHeightVar() {
        var navbar = document.querySelector('.app-navbar');
        if (!navbar) { return; }
        var height = navbar.getBoundingClientRect().height;
        if (height > 0) {
            document.documentElement.style.setProperty('--app-navbar-height', height + 'px');
        }
    }
    // 네비게이션 바는 이 앱의 모든 페이지에 공통으로 있는 전역 레이아웃이라
    // 이 그리드가 화면에 없어도(다른 페이지) 그냥 실행되지만, CSS 변수만
    // 세팅할 뿐이라 다른 화면에 영향은 없다.
    syncNavbarHeightVar();
    window.addEventListener('load', syncNavbarHeightVar);
    window.addEventListener('resize', syncNavbarHeightVar);

    function datalistIdFor(col) {
        return 'du-datalist::' + col;
    }

    function rebuildDatalists(suggestions) {
        suggestions = suggestions || {};
        datalistCols = Object.keys(suggestions);
        datalistCols.forEach(function (col) {
            var id = datalistIdFor(col);
            var el = document.getElementById(id);
            if (!el) {
                el = document.createElement('datalist');
                el.id = id;
                document.body.appendChild(el);
            }
            el.innerHTML = '';
            (suggestions[col] || []).forEach(function (v) {
                var opt = document.createElement('option');
                opt.value = v;
                el.appendChild(opt);
            });
        });
    }

    function applyDatalistToInput(input) {
        var td = input.closest('td[data-dash-column]');
        if (!td) { return; }
        var col = td.getAttribute('data-dash-column');
        if (datalistCols.indexOf(col) === -1) { return; }
        input.setAttribute('list', datalistIdFor(col));
        input.setAttribute('autocomplete', 'off');
    }

    // 클릭 x좌표 → 글자 인덱스. <input>은 실제 텍스트가 DOM 텍스트 노드로
    // 노출되지 않아 caretRangeFromPoint류 API를 못 쓰므로, 같은 폰트로
    // 캔버스에 글자 폭을 재 누적하며 클릭 지점을 추정한다.
    var __measureCanvas = null;
    function caretIndexFromClick(input, clientX) {
        var text = input.value || '';
        if (!text) { return 0; }
        if (!__measureCanvas) { __measureCanvas = document.createElement('canvas'); }
        var ctx = __measureCanvas.getContext('2d');
        var style = window.getComputedStyle(input);
        ctx.font = [style.fontStyle, style.fontWeight, style.fontSize, style.fontFamily].join(' ');
        var rect = input.getBoundingClientRect();
        var paddingLeft = parseFloat(style.paddingLeft) || 0;
        var borderLeft = parseFloat(style.borderLeftWidth) || 0;
        var relativeX = clientX - rect.left - paddingLeft - borderLeft + (input.scrollLeft || 0);
        if (relativeX <= 0) { return 0; }
        var cumulative = 0;
        for (var i = 0; i < text.length; i++) {
            var w = ctx.measureText(text[i]).width;
            if (cumulative + w / 2 > relativeX) { return i; }
            cumulative += w;
        }
        return text.length;
    }

    // 실제 더블클릭과 최대한 비슷하게(mousedown/up/click을 두 번, 그 다음
    // dblclick) 합성 이벤트를 발생시킨다 — dash_table의 onDoubleClick이
    // React 합성 이벤트 경유라, 단순히 dblclick 하나만 dispatch해도 대부분
    // 동작하지만 혹시 내부적으로 click 카운트/좌표를 참고할 경우까지
    // 대비해 실제 더블클릭 시퀀스를 그대로 재현한다.
    function simulateDoubleClick(target) {
        var rect = target.getBoundingClientRect();
        var opts = {
            bubbles: true, cancelable: true, view: window,
            clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2,
        };
        ['mousedown', 'mouseup', 'click', 'mousedown', 'mouseup', 'click', 'dblclick'].forEach(function (type) {
            target.dispatchEvent(new MouseEvent(type, opts));
        });
    }

    function setupInteractionFixes(wrap) {
        // 2) 클릭 위치로 커서 이동. row_selectable(체크박스, 2026-09-15 추가)
        // 컬럼도 <input>이지만 type="checkbox"라 setSelectionRange을 아예
        // 지원하지 않아(호출 시 DOMException) 텍스트 입력(기본 type="text")
        // 에만 적용한다.
        wrap.addEventListener('mouseup', function (e) {
            var input = e.target;
            if (!input || input.tagName !== 'INPUT') { return; }
            if (input.type && input.type !== 'text') { return; }
            var clientX = e.clientX;
            setTimeout(function () {
                // dash_table의 자체 처리(select-all)가 이미 끝난 뒤(macrotask)
                // 클릭 좌표 기준으로 다시 덮어쓴다. 그 사이 다른 셀로 포커스가
                // 옮겨갔으면(예: 매우 빠른 연속 클릭) 건드리지 않는다.
                if (document.activeElement !== input) { return; }
                var pos = caretIndexFromClick(input, clientX);
                input.setSelectionRange(pos, pos);
            }, 0);
        });

        // 1) 새로 생기는 편집용 <input>에 자동채움 가이드(list) 연결.
        var observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                if (!m.addedNodes) { return; }
                m.addedNodes.forEach(function (node) {
                    if (node.nodeType !== 1) { return; }
                    if (node.tagName === 'INPUT') {
                        applyDatalistToInput(node);
                    } else if (node.querySelectorAll) {
                        node.querySelectorAll('input').forEach(applyDatalistToInput);
                    }
                });
            });
        });
        observer.observe(wrap, { childList: true, subtree: true });

        // 3) F2 → 합성 더블클릭으로 dash_table의 is_focused=true 전환을
        // 실제로 일으킨 뒤, 커서를 맨 끝으로(엑셀의 F2와 동일).
        wrap.addEventListener('keydown', function (e) {
            if (e.key !== 'F2') { return; }
            var active = document.activeElement;
            var td = (active && active.tagName === 'TD') ? active : (active && active.closest && active.closest('td[data-dash-column]'));
            if (!td) { return; }
            e.preventDefault();
            simulateDoubleClick(td);
            requestAnimationFrame(function () {
                var input = td.querySelector('input');
                if (input) {
                    input.focus();
                    var len = input.value ? input.value.length : 0;
                    input.setSelectionRange(len, len);
                }
            });
        });
    }

    // pages/admin.py의 clientside_callback이 team-refer-suggestions Store가
    // 바뀔 때마다(최초 로드 포함) 이 함수를 부른다.
    window.__syncTeamReferSuggestions = function (suggestions) {
        rebuildDatalists(suggestions);
        if (!initialized) {
            var wrap = document.getElementById(GRID_WRAP_ID);
            if (wrap) {
                setupInteractionFixes(wrap);
                initialized = true;
            }
        }
        return '';
    };

    // ── 4) 형제 그룹 안에서만 행 드래그 재정렬 ──────────────────────────────
    var LEVEL_COLS = ['1단계부서명', '2단계부서명', '3단계부서명'];
    var DEP_CODE_COL = '조직코드';
    var dragInitialized = false;

    // _sort_key()(pages/admin.py)와 동일한 발상 — 숫자로 보이는 조직코드는
    // 숫자로, 아니면 문자열로 비교한다(자릿수가 다른 값이 섞여 있어도
    // "10"이 "9"보다 앞에 오는 문자열 비교 오류를 피한다).
    function depCodeCompare(a, b) {
        var sa = (a || '').toString().trim();
        var sb = (b || '').toString().trim();
        var na = /^-?\d+$/.test(sa);
        var nb = /^-?\d+$/.test(sb);
        if (na && nb) { return parseInt(sa, 10) - parseInt(sb, 10); }
        if (na !== nb) { return na ? -1 : 1; }
        return sa < sb ? -1 : (sa > sb ? 1 : 0);
    }

    // 행 하나(현재 data 배열의 원소, {"1단계부서명": ..., ...})의 "형제
    // 그룹" 키. team_hierarchy._own_path()와 동일한 규칙(1→2→3단계 순서로
    // 읽다가 처음 빈 값을 만나면 그 행 자신의 레벨) — 그 앞 단계까지의
    // 값이 곧 부모를 가리키므로 그걸 그룹 키로 쓴다.
    function rowGroupKeyFromRow(row) {
        var l1 = (row[LEVEL_COLS[0]] || '').toString().trim();
        var l2 = (row[LEVEL_COLS[1]] || '').toString().trim();
        var l3 = (row[LEVEL_COLS[2]] || '').toString().trim();
        if (l3) { return 'lvl3::' + l1 + '::' + l2; }
        if (l2) { return 'lvl2::' + l1; }
        return 'root';
    }

    function trIndex(tr) {
        var parent = tr && tr.parentElement;
        if (!parent) { return -1; }
        return Array.prototype.indexOf.call(parent.children, tr);
    }

    // sort_action='custom'이라(pages/admin.py 참고) DataTable이 자체적으로
    // 행 순서를 바꾸지 않는다 — 렌더링된 <tr> 순서가 항상 data 배열 순서와
    // 정확히 일치하므로, DOM 위치 인덱스를 그대로 배열 인덱스로 쓸 수 있다.
    function rowGroupKeyOfTr(tr) {
        var idx = trIndex(tr);
        var rows = window.__teamReferRows || [];
        if (idx < 0 || idx >= rows.length) { return null; }
        return rowGroupKeyFromRow(rows[idx]);
    }

    function markRowsDraggable(wrap) {
        var trs = wrap.querySelectorAll('tbody tr');
        trs.forEach(function (tr) { tr.draggable = true; });
    }

    // 행 하나의 "자기 경로"(1단계→2단계→3단계, 빈 값을 만나면 중단) —
    // 이 경로가 다른 행의 경로 접두사(strict prefix)이면 그 행은 이 행의
    // 하위 조직(자손)이라는 뜻. 부모 행만 옮기고 자식 행을 남겨두면
    // 계층이 깨지므로, 드래그 시 이 접두사 관계로 "행 + 그 하위 전체"를
    // 하나의 블록으로 묶어 함께 옮긴다.
    function rowOwnPath(row) {
        var l1 = (row[LEVEL_COLS[0]] || '').toString().trim();
        var l2 = (row[LEVEL_COLS[1]] || '').toString().trim();
        var l3 = (row[LEVEL_COLS[2]] || '').toString().trim();
        var path = [];
        if (l1) { path.push(l1); } else { return path; }
        if (!l2) { return path; }
        path.push(l2);
        if (!l3) { return path; }
        path.push(l3);
        return path;
    }

    function isDescendantPath(path, ancestorPath) {
        if (path.length <= ancestorPath.length) { return false; }
        for (var i = 0; i < ancestorPath.length; i++) {
            if (path[i] !== ancestorPath[i]) { return false; }
        }
        return true;
    }

    // rows[idx](드래그 대상 행)과 그 바로 뒤에 이어지는 하위 조직 행들을
    // 하나의 연속 구간 [start, end)로 묶는다. list_editable_rows()가
    // 깊이 우선(부모→자식) 순서로 평탄화해 반환하므로, 자손 행은 항상
    // 부모 바로 다음부터 연속해서 나온다.
    function subtreeRange(rows, idx) {
        var path = rowOwnPath(rows[idx]);
        var end = idx + 1;
        while (end < rows.length && isDescendantPath(rowOwnPath(rows[end]), path)) {
            end++;
        }
        return [idx, end];
    }

    function setupRowDrag(wrap) {
        var draggedTr = null;
        var draggedGroup = null;

        // team-refer-sync-tooltip/suggestions 등 <data> 변화를 지켜보는
        // 다른 서버 왕복 콜백들이 뒤이어 tooltip_data 등 다른 prop을 갱신하면
        // DataTable이 <tbody>를 다시 그려(새 <tr> 노드로 교체) 직접 설정해둔
        // draggable 속성이 사라진다 — 한 번만 markRowsDraggable을 부르는
        // 대신, 이후 새로 생기는 <tr>도 계속 draggable=true가 되도록 지켜본다.
        var rowObserver = new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                if (!m.addedNodes) { return; }
                m.addedNodes.forEach(function (node) {
                    if (node.nodeType !== 1) { return; }
                    if (node.tagName === 'TR') {
                        node.draggable = true;
                    } else if (node.querySelectorAll) {
                        node.querySelectorAll('tr').forEach(function (tr) { tr.draggable = true; });
                    }
                });
            });
        });
        rowObserver.observe(wrap, { childList: true, subtree: true });

        wrap.addEventListener('dragstart', function (e) {
            if (window.__teamReferSortActive) { e.preventDefault(); return; }
            var tr = e.target.closest && e.target.closest('tr');
            if (!tr) { return; }
            draggedTr = tr;
            draggedGroup = rowGroupKeyOfTr(tr);
            try { e.dataTransfer.setData('text/plain', 'team-refer-row'); } catch (err) { /* 일부 브라우저는 무시 */ }
            e.dataTransfer.effectAllowed = 'move';
        });

        wrap.addEventListener('dragover', function (e) {
            if (!draggedTr) { return; }
            var tr = e.target.closest && e.target.closest('tr');
            if (!tr || tr === draggedTr) { return; }
            if (draggedGroup === null || rowGroupKeyOfTr(tr) !== draggedGroup) { return; }
            // 그룹이 일치할 때만 preventDefault로 드롭을 허용한다 — 이걸
            // 안 부르면 브라우저가 드롭 자체를 막아, 다른 그룹 위로는
            // 자연스럽게 아무 반응이 없는(=거부되는) 것처럼 보인다.
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });

        wrap.addEventListener('drop', function (e) {
            if (!draggedTr) { return; }
            var sourceTr = draggedTr;
            var group = draggedGroup;
            draggedTr = null;
            draggedGroup = null;

            var targetTr = e.target.closest && e.target.closest('tr');
            if (!targetTr || targetTr === sourceTr) { return; }
            if (group === null || rowGroupKeyOfTr(targetTr) !== group) { return; }
            e.preventDefault();

            var sourceIdx = trIndex(sourceTr);
            var targetIdx = trIndex(targetTr);
            if (sourceIdx < 0 || targetIdx < 0) { return; }

            var rows = (window.__teamReferRows || []).slice();
            if (sourceIdx >= rows.length || targetIdx >= rows.length) { return; }

            // 드래그한 행 하나만 옮기면 하위 조직(자손) 행들과 분리돼
            // 계층이 깨진다 — 드래그 행과 그 하위 전체를 하나의 블록으로
            // 함께 옮긴다.
            var sourceRange = subtreeRange(rows, sourceIdx);
            var targetRange = subtreeRange(rows, targetIdx);

            // 이동 전 이 그룹이 갖고 있던 조직코드 값들을 오름차순으로 모아둔다
            // — 이동 후 같은 값들을 새 순서에 맞게 재배당할 재료.
            var codesBefore = [];
            for (var i = 0; i < rows.length; i++) {
                if (rowGroupKeyFromRow(rows[i]) === group) { codesBefore.push(rows[i][DEP_CODE_COL] || ''); }
            }
            codesBefore.sort(depCodeCompare);

            var block = rows.splice(sourceRange[0], sourceRange[1] - sourceRange[0]);
            var insertAt = targetRange[0] > sourceRange[0] ? targetRange[0] - block.length : targetRange[0];
            rows.splice.apply(rows, [insertAt, 0].concat(block));

            var idxAfter = [];
            for (var j = 0; j < rows.length; j++) {
                if (rowGroupKeyFromRow(rows[j]) === group) { idxAfter.push(j); }
            }
            idxAfter.forEach(function (idx, k) {
                rows[idx][DEP_CODE_COL] = codesBefore[k];
            });

            window.__teamReferRows = rows;
            if (window.dash_clientside && window.dash_clientside.set_props) {
                window.dash_clientside.set_props('team-refer-table', { data: rows });
            }
        });

        wrap.addEventListener('dragend', function () {
            draggedTr = null;
            draggedGroup = null;
        });
    }

    // pages/admin.py의 clientside_callback이 team-refer-table의 data 또는
    // sort_by가 바뀔 때마다(최초 로드 포함) 이 함수를 부른다.
    window.__teamReferOnDataChange = function (rows, sortBy) {
        // Dash는 React SPA라 브라우저 'load' 이벤트가 실제 네비게이션 바
        // 렌더링보다 먼저 끝나버릴 수 있어(직접 확인 — 'load' 시점에
        // .app-navbar가 아직 DOM에 없는 경우가 있었음), window.onload에만
        // 기대지 않고 이 콜백(그리드가 실제로 화면에 존재해야만 호출되므로
        // 이 시점엔 네비게이션 바도 항상 이미 렌더링돼 있음)에서도 다시
        // 재본다 — 이미 맞게 세팅돼 있으면 다시 재도 비용이 거의 없다.
        syncNavbarHeightVar();
        window.__teamReferRows = rows || [];
        window.__teamReferSortActive = !!(sortBy && sortBy.length);
        var wrap = document.getElementById(GRID_WRAP_ID);
        if (!wrap) { return ''; }
        if (!dragInitialized) {
            setupRowDrag(wrap);
            dragInitialized = true;
        }
        // DataTable이 새 data로 <tr>를 다시 그리는 건 이 콜백 이후에
        // 비동기로 일어날 수 있어, 한 프레임 뒤에 draggable을 다시 건다.
        requestAnimationFrame(function () { markRowsDraggable(wrap); });
        return '';
    };
})();
