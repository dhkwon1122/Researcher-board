/* 연구원 개별 프로필 — 인쇄 레이아웃 편집기(그리드 드래그/리사이즈).
 * Dash가 .pl-canvas의 children을 다시 그려도(모달 열기/기본값 초기화) 매번
 * 새로 바인딩할 필요 없도록, document에 이벤트 위임(delegation)으로 붙인다.
 * 블록 위치의 "정답"은 항상 각 .pl-block의 inline style(gridColumn/gridRow)
 * 이고, 드래그가 끝날 때마다 전체 블록을 다시 읽어 print-layout-store에
 * dash_clientside.set_props로 반영한다(서버 왕복 없이 즉시 저장 상태 갱신).
 */
(function () {
  let dragState = null;

  function cellMetrics(grid) {
    const cols = parseInt(grid.dataset.cols, 10) || 10;
    const rows = parseInt(grid.dataset.rows, 10) || 14;
    const rect = grid.getBoundingClientRect();
    return { cols, rows, cellW: rect.width / cols, cellH: rect.height / rows };
  }

  function getPos(block) {
    const col = block.style.gridColumn.split('/');
    const row = block.style.gridRow.split('/');
    return {
      x: parseInt(col[0], 10) - 1,
      y: parseInt(row[0], 10) - 1,
      w: parseInt((col[1] || 'span 1').replace('span', '').trim(), 10),
      h: parseInt((row[1] || 'span 1').replace('span', '').trim(), 10),
    };
  }

  function setPos(block, x, y, w, h) {
    block.style.gridColumn = (x + 1) + ' / span ' + w;
    block.style.gridRow = (y + 1) + ' / span ' + h;
  }

  function collectLayout(grid) {
    const layout = {};
    grid.querySelectorAll('.pl-block').forEach(function (el) {
      layout[el.dataset.key] = getPos(el);
    });
    return layout;
  }

  document.addEventListener('pointerdown', function (e) {
    const grid = e.target.closest('.pl-grid');
    if (!grid) return;
    const block = e.target.closest('.pl-block');
    if (!block) return;
    const isResize = !!e.target.closest('.pl-resize-handle');
    const metrics = cellMetrics(grid);
    dragState = {
      grid: grid,
      block: block,
      isResize: isResize,
      cols: metrics.cols,
      rows: metrics.rows,
      cellW: metrics.cellW,
      cellH: metrics.cellH,
      startX: e.clientX,
      startY: e.clientY,
      start: getPos(block),
    };
    block.setPointerCapture(e.pointerId);
    block.classList.add('pl-dragging');
    e.preventDefault();
  });

  document.addEventListener('pointermove', function (e) {
    if (!dragState) return;
    const d = dragState;
    const dxCells = Math.round((e.clientX - d.startX) / d.cellW);
    const dyCells = Math.round((e.clientY - d.startY) / d.cellH);

    if (d.isResize) {
      const w = Math.min(Math.max(d.start.w + dxCells, 1), d.cols - d.start.x);
      const h = Math.min(Math.max(d.start.h + dyCells, 1), d.rows - d.start.y);
      setPos(d.block, d.start.x, d.start.y, w, h);
    } else {
      const x = Math.min(Math.max(d.start.x + dxCells, 0), d.cols - d.start.w);
      const y = Math.min(Math.max(d.start.y + dyCells, 0), d.rows - d.start.h);
      setPos(d.block, x, y, d.start.w, d.start.h);
    }
  });

  function endDrag() {
    if (!dragState) return;
    const grid = dragState.grid;
    const block = dragState.block;
    block.classList.remove('pl-dragging');
    dragState = null;
    const layout = collectLayout(grid);
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props('print-layout-store', { data: layout });
    }
  }

  document.addEventListener('pointerup', endDrag);
  document.addEventListener('pointercancel', endDrag);
})();
