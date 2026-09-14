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
// 기능이 없어 이번 전환에서 함께 빠졌다(자동채움 가이드). 남은 건
// "전체 선택/위로/아래로/선택 삭제" 버튼(.team-refer-sticky-toolbar)이
// 스크롤해도 항상 보이도록 네비게이션 바(.app-navbar)의 실제 렌더링
// 높이를 재 CSS 변수 --app-navbar-height에 채워 넣는 기능뿐이다
// (2026-09-16 추가 — 고정 픽셀을 CSS에 박아두면 폰트 로딩 지연이나 화면
// 폭에 따라 네비게이션 바가 줄바꿈되는 경우 실제 높이와 어긋날 수 있어,
// 페이지 로드/리사이즈/그리드 갱신 때마다 다시 잰다).

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

    // pages/admin.py의 clientside_callback이 team-refer-table의 rowData가
    // 바뀔 때마다(최초 로드 포함) 이 함수를 부른다 — Dash는 React SPA라
    // 브라우저 'load' 이벤트가 실제 네비게이션 바 렌더링보다 먼저 끝나버릴
    // 수 있어(직접 확인 — 'load' 시점에 .app-navbar가 아직 DOM에 없는
    // 경우가 있었음), 그리드가 실제로 화면에 존재해야만 호출되는 이
    // 콜백(이 시점엔 네비게이션 바도 항상 이미 렌더링돼 있음)에서도
    // 다시 잰다.
    window.__syncTeamReferNavbarHeight = syncNavbarHeightVar;
})();
