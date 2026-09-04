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

(function () {
    var GRID_WRAP_ID = 'team-refer-grid-wrap';
    var initialized = false;
    var datalistCols = [];  // 자동채움 대상 컬럼명(마지막 동기화 기준)

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
        // 2) 클릭 위치로 커서 이동.
        wrap.addEventListener('mouseup', function (e) {
            var input = e.target;
            if (!input || input.tagName !== 'INPUT') { return; }
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
})();
