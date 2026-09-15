// pages/admin.py의 "팀/리더 참조" 그리드(id="team-refer-table", 래퍼
// id="team-refer-grid-wrap") 전용 보강 스크립트.
//
// 2026-09-17: dash_table.DataTable → dash-ag-grid(AG Grid Community)로
// 그리드 엔진을 교체하면서, 이 파일이 예전에 직접 구현했던 기능들
// (자동채움 가이드용 <datalist> 연결, 클릭 위치로 커서 이동, F2로 편집
// 모드 진입, 행 드래그 재정렬)이 전부 사라졌다 — 전부 AG Grid가 기본으로
// 제공하거나(더블클릭/Enter/F2 편집 진입, 클릭 위치 커서, 컬럼 리사이즈),
// 성능 문제로 완전히 제거됐거나(행 드래그, 여러 차례 수정에도 화면이
// 멈추는 현상이 반복돼 사용자 요청으로 삭제), AG Grid Community에 대응
// 기능이 없어 이번 전환에서 함께 빠졌다(자동채움 가이드).
//
// 2026-09-18: 엑셀에서 드래그해 복사한 여러 행/열 값을 이 그리드에
// 붙여넣는 기능을 새로 추가했다 — AG Grid Community에는 이 기능
// (클립보드 붙여넣기)이 전혀 없다(격리된 프로브 앱으로 직접 확인:
// 셀 1개짜리 값도 안 들어감). AG Grid Enterprise를 켜면 되지만
// 정식 라이선스 없이는 콘솔에 "License Key Not Found" 경고가 계속
// 뜨고(무기한 트라이얼 사용은 라이선스 위반), 애초에 AG Grid로 옮긴
// 이유(무료 오픈소스, MIT)와도 상충돼 여기서 직접 구현했다. AG Grid의
// 내장 클립보드 서비스를 쓰지 않고 브라우저 표준 'paste' 이벤트를
// 직접 가로채, 탭/줄바꿈으로 구분된 텍스트를 파싱해 포커스된 셀부터
// rowNode.setDataValue()로 채워 넣는다 — 이 API는 일반 셀 편집과 같은
// 경로로 값이 바뀐 걸 알려서, Dash 쪽 rowData State가 별도 콜백 없이도
// 그대로 최신값을 갖게 된다(격리 프로브로 확인).
(function () {
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

    // "구분" 컬럼은 agSelectCellEditor로 이 3개 값만 고르게 제한돼 있다
    // (pages/admin.py의 _WORK_TYPE_OPTIONS, 2026-09-17 확정) — 붙여넣기는
    // 그 에디터를 거치지 않고 값을 직접 넣으므로, 여기서도 같은 허용
    // 목록을 그대로 지켜야 한다(둘이 어긋나면 여기부터 고칠 것).
    var WORK_TYPE_OPTIONS = ['', 'R&D', 'R&D_Support', 'Staff'];

    var GRID_ID = 'team-refer-table';
    var GRID_WRAP_ID = 'team-refer-grid-wrap';
    var pasteHandlerAttached = false;

    async function handleTeamReferPaste(e) {
        if (!window.dash_ag_grid || !window.dash_ag_grid.getApiAsync) { return; }
        var api = await window.dash_ag_grid.getApiAsync(GRID_ID);
        if (!api) { return; }
        // 셀이 실제로 편집 중(더블클릭/F2로 진입, <input> 표시 중)이면 그
        // 입력창에 값 하나만 붙여넣는 브라우저 기본 동작을 그대로 둔다 —
        // 여러 셀 채우기는 "편집 중이 아닌, 포커스만 된" 상태에서만 한다
        // (엑셀에서 셀 하나를 클릭한 뒤 바로 붙여넣는 것과 같은 흐름).
        if (api.getEditingCells().length > 0) { return; }
        var focused = api.getFocusedCell();
        if (!focused) { return; }

        var clipboardData = e.clipboardData || window.clipboardData;
        var text = clipboardData ? clipboardData.getData('text/plain') : '';
        if (!text) { return; }
        e.preventDefault();

        var lines = text.replace(/\r/g, '').split('\n');
        // 엑셀에서 복사하면 마지막에 빈 줄이 하나 더 붙어 온다 — 그대로
        // 두면 존재하지 않는 다음 행에 빈 값을 덮어써 실제 데이터를
        // 지울 위험이 있어 제거한다.
        while (lines.length && lines[lines.length - 1] === '') { lines.pop(); }
        if (!lines.length) { return; }

        var editableCols = api.getAllDisplayedColumns().filter(function (c) {
            return c.getColDef().editable;
        });
        var startColIdx = editableCols.findIndex(function (c) {
            return c.getColId() === focused.column.getColId();
        });
        if (startColIdx === -1) { return; }  // 'No.' 등 편집 불가 컬럼에 포커스된 경우

        var startRowIdx = focused.rowIndex;
        var rowCount = api.getDisplayedRowCount();

        lines.forEach(function (line, i) {
            var rowIdx = startRowIdx + i;
            // 그리드 마지막 행을 넘어가면 새 행을 만들지 않고 그냥 버린다
            // (행 추가는 "행 추가" 버튼의 책임 — 여기서 조용히 행을
            // 늘리면 _rid/조직코드 재배번 등 다른 콜백과 어긋날 수 있음).
            if (rowIdx >= rowCount) { return; }
            var rowNode = api.getDisplayedRowAtIndex(rowIdx);
            if (!rowNode) { return; }
            var cells = line.split('\t');
            cells.forEach(function (value, j) {
                var col = editableCols[startColIdx + j];
                if (!col) { return; }  // 그리드 마지막 컬럼을 넘어가면 버림
                var field = col.getColId();
                if (field === '구분' && WORK_TYPE_OPTIONS.indexOf(value) === -1) {
                    return;  // 드롭다운 허용 목록 밖 값은 붙여넣지 않고 기존 값 유지
                }
                rowNode.setDataValue(field, value);
            });
        });
    }

    function attachPasteHandler() {
        if (pasteHandlerAttached) { return; }
        var wrap = document.getElementById(GRID_WRAP_ID);
        if (!wrap) { return; }
        wrap.addEventListener('paste', handleTeamReferPaste);
        pasteHandlerAttached = true;
    }

    // pages/admin.py의 clientside_callback이 team-refer-table의 rowData가
    // 바뀔 때마다(최초 로드 포함) 이 함수를 부른다 — Dash는 React SPA라
    // 브라우저 'load' 이벤트가 실제 네비게이션 바 렌더링보다 먼저 끝나버릴
    // 수 있어(직접 확인 — 'load' 시점에 .app-navbar가 아직 DOM에 없는
    // 경우가 있었음), 그리드가 실제로 화면에 존재해야만 호출되는 이
    // 콜백(이 시점엔 네비게이션 바도, 그리드 래퍼도 항상 이미 렌더링돼
    // 있음)에서 붙여넣기 리스너도 함께 등록한다(최초 1회만, 이후 호출은
    // pasteHandlerAttached 플래그로 무시).
    window.__syncTeamReferNavbarHeight = function () {
        syncNavbarHeightVar();
        attachPasteHandler();
    };
})();
