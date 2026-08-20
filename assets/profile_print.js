// pages/researcher_profile.py의 "프로필 인쇄 (A4)" 버튼과, 헤드리스 브라우저
// 기반 서버사이드 PDF 첨부 발송(services/profile_pdf.py) 양쪽이 공유하는
// 인쇄 준비 로직. 버튼 클릭 흐름에서는 클릭 콜백이 이 함수를 먼저 부른 뒤
// window.print()까지 이어서 실행하고(afterprint에서 정리), PDF 첨부 발송
// 흐름에서는 헤드리스 브라우저가 이 함수만 호출한 뒤(window.print() 없이)
// 곧바로 page.pdf()로 캡처한다 — 단일 사용 헤드리스 페이지라 정리가 필요
// 없다. Dash는 assets/ 아래 .js 파일을 모든 페이지에 자동으로 실어준다.
window.__prepareProfilePrint = function() {
    // assets/custom.css의 이름 없는(unnamed) @page는 조직별 비교(A3
    // landscape) 화면 전용이라, 인쇄/PDF 캡처 동안만 <style>을 head 맨
    // 뒤에 추가해 같은 unnamed @page를 A4로 임시 덮어쓴다(소스 순서상
    // 나중 규칙이 이겨 A3보다 우선 적용됨). 버튼 클릭 흐름에서는
    // afterprint에서 제거(researcher_profile.py의 clientside_callback
    // 참고), PDF 캡처(헤드리스, 단일 사용 페이지)에서는 그대로 둬도 무방.
    var STYLE_ID = 'profile-print-a4-page-size';
    var existing = document.getElementById(STYLE_ID);
    if (existing) { existing.remove(); }
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = '@media print { @page { size: A4 portrait; margin: 14mm 16mm; } }';
    document.head.appendChild(style);

    // 논문/특허 실적 상세(제목이 길면 줄바꿈되는 표)가 한 페이지를
    // 넘지 않도록, 인쇄 직전에 각 .print-page-block의 실제 렌더링
    // 높이를 재서 페이지 예산을 넘으면 표 뒤쪽 행부터 순서대로
    // 숨기고 "외 N건 더"를 채운다. 서버(파이썬)에서는 제목 줄바꿈
    // 등을 미리 정확히 알 수 없어 행 수를 고정으로 자르지 않고,
    // 이렇게 실측 기반으로 동적으로 결정한다.
    //
    // .profile-print-only는 화면에서 display:none이라 평소에는
    // 실제 렌더링 높이를 잴 수 없고, beforeprint 시점에도(적어도
    // 헤드리스 크로미움에서는 실측 결과 0으로 확인됨) 인쇄 레이아웃이
    // 아직 적용되지 않는다. 그래서 인쇄용 폰트 크기(10.5px 등,
    // assets/custom.css @media print 규칙과 동일)를 흉내낸 임시
    // <style>을 붙이고, 컨테이너를 화면 밖(왼쪽 -99999px)에 실제
    // 페이지 폭으로 잠깐 표시해 진짜 레이아웃으로 측정한 뒤 원래
    // 상태로 되돌린다 — 화면에는 전혀 보이지 않는다. 재인쇄해도 항상
    // 전체 행을 먼저 다시 보이는 상태로 되돌린 뒤 다시 계산해(멱등)
    // 반복 클릭에 따라 누적으로 더 잘려나가지 않게 한다.
    var container = document.getElementById('profile-print-content');
    if (!container) { return; }

    var PAGE_CONTENT_WIDTH_PX = (210 - 16 * 2) * 96 / 25.4;
    // 화면 밖에 임시로 렌더링해 재는 높이가 실제 인쇄 결과보다
    // 살짝(실측 30~50px 안팎) 작게 나오는 오차가 있어(오프스크린
    // 렌더링과 실제 인쇄 파이프라인의 미세한 레이아웃 차이로
    // 추정), 안전 여백을 넉넉히 빼서 경계선에서 한 페이지를
    // 넘기지 않게 한다.
    var PAGE_HEIGHT_SAFETY_MARGIN_PX = 80;
    var PAGE_HEIGHT_PX = (297 - 14 * 2) * 96 / 25.4 - PAGE_HEIGHT_SAFETY_MARGIN_PX;

    var MEASURE_STYLE_ID = 'profile-print-measure-style';
    var existingMeasureStyle = document.getElementById(MEASURE_STYLE_ID);
    if (existingMeasureStyle) { existingMeasureStyle.remove(); }
    var measureStyle = document.createElement('style');
    measureStyle.id = MEASURE_STYLE_ID;
    measureStyle.textContent =
        '#profile-print-content.__pp-measuring, #profile-print-content.__pp-measuring * {' +
        'font-size:10.5px !important; line-height:1.45 !important;}' +
        '#profile-print-content.__pp-measuring .print-title{font-size:30px !important;}' +
        '#profile-print-content.__pp-measuring .print-page2-title{font-size:16px !important;}' +
        '#profile-print-content.__pp-measuring{display:block !important; position:fixed !important;' +
        'left:-99999px !important; top:0 !important; width:' + PAGE_CONTENT_WIDTH_PX + 'px !important;}';
    document.head.appendChild(measureStyle);
    container.classList.add('__pp-measuring');

    document.querySelectorAll('.print-page-block').forEach(function(block) {
        // 논문·특허 표가 한 블록(페이지)을 같이 쓰므로(제한 사항:
        // 합쳐서 1페이지), 표별로 각자 맞추는 게 아니라 블록
        // 전체(둘 합계) 높이가 예산을 넘지 않을 때까지, 그 순간
        // 행이 더 많이 남은 표에서 한 줄씩 줄여 균형 있게 맞춘다.
        var entries = [];
        block.querySelectorAll('.print-autofit-table').forEach(function(table) {
            var tbody = table.querySelector('.print-autofit-body');
            var note = table.parentElement ? table.parentElement.querySelector('.print-autofit-note') : null;
            if (!tbody) { return; }
            var rows = tbody.rows;
            for (var i = 0; i < rows.length; i++) { rows[i].style.display = ''; }
            if (note) { note.style.display = 'none'; note.textContent = ''; }
            entries.push({rows: rows, visible: rows.length, note: note});
        });
        if (!entries.length) { return; }

        while (block.getBoundingClientRect().height > PAGE_HEIGHT_PX) {
            var target = null;
            for (var e = 0; e < entries.length; e++) {
                if (entries[e].visible > 1 && (!target || entries[e].visible > target.visible)) {
                    target = entries[e];
                }
            }
            if (!target) { break; }
            target.rows[target.visible - 1].style.display = 'none';
            target.visible--;
        }

        entries.forEach(function(entry) {
            var removedCount = entry.rows.length - entry.visible;
            if (removedCount > 0 && entry.note) {
                entry.note.textContent = '외 ' + removedCount + '건 더';
                entry.note.style.display = '';
            }
        });
    });

    container.classList.remove('__pp-measuring');
    measureStyle.remove();
};
