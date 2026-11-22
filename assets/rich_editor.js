// 메일 본문 서식 편집기(components/rich_editor.py) — 인사발령(2026-11-20)에서 시작, 업무분장과 공용.
// .rich-wrap 안의 편집기(.rich-editor, contentEditable)에서 고친 내용을 data-store에 적힌 dcc.Store로 올려 보내고,
// 같은 .rich-wrap의 도구 모음([data-hro-cmd])으로 글꼴·크기·굵게·밑줄·글자색·바탕색 등을 document.execCommand로 적용한다.
// 글자색·바탕색은 기본색 팔레트 → 필요하면 "상세 색…"(색상 선택 창).
// 저장·발송 전에 서버(services/hr_order_mail.sanitize_html)가 허용한 서식만 남긴다.
(function () {
  var saved = null;      // 마지막 선택 영역(도구 모음을 누르면 포커스가 빠지므로 되살린다)
  var savedEd = null;    // 그 선택 영역이 있던 편집기

  function editorOf(el) {
    var wrap = el && el.closest && el.closest('.rich-wrap');
    return wrap ? wrap.querySelector('.rich-editor') : null;
  }

  function sync(ed) {
    var store = ed && ed.getAttribute('data-store');
    if (store && window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props(store, { data: ed.innerHTML });
    }
  }

  function restore(ed) {
    ed.focus();
    if (saved && savedEd === ed) {
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(saved);
    }
  }

  function exec(ed, cmd, val) {
    if (!ed) { return; }
    restore(ed);
    document.execCommand('styleWithCSS', false, cmd !== 'fontSize');
    document.execCommand(cmd, false, val == null ? null : val);
    sync(ed);
  }

  document.addEventListener('selectionchange', function () {
    var sel = window.getSelection();
    if (!sel.rangeCount) { return; }
    var node = sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
    var ed = node && node.closest && node.closest('.rich-editor');
    if (ed) {
      saved = sel.getRangeAt(0).cloneRange();
      savedEd = ed;
    }
  });

  document.addEventListener('input', function (ev) {
    if (ev.target && ev.target.classList && ev.target.classList.contains('rich-editor')) { sync(ev.target); }
  });

  // 버튼: mousedown에서 기본 동작(포커스 이동)을 막아 선택 영역 유지
  document.addEventListener('mousedown', function (ev) {
    var btn = ev.target.closest && ev.target.closest('button[data-hro-cmd]');
    if (btn) {
      ev.preventDefault();
      exec(editorOf(btn), btn.getAttribute('data-hro-cmd'), btn.getAttribute('data-hro-val'));
    }
  });

  // 글꼴·크기 선택
  document.addEventListener('change', function (ev) {
    var t = ev.target;
    if (t && t.tagName === 'SELECT' && t.getAttribute('data-hro-cmd')) {
      if (t.value) { exec(editorOf(t), t.getAttribute('data-hro-cmd'), t.value); }
      t.selectedIndex = 0;
    }
  });

  // 글자색·바탕색(2026-11-22 개정): 라벨을 누르면 기본색 팔레트를 띄우고, 필요할 때만 "상세 색…"으로 색상 선택 창을 연다.
  var PALETTES = {
    foreColor: [['#000000', '검정'], ['#595959', '진회색'], ['#a6a6a6', '회색'], ['#c00000', '진빨강'], ['#ff0000', '빨강'],
                ['#ed7d31', '주황'], ['#bf8f00', '황토'], ['#00b050', '초록'], ['#0070c0', '파랑'], ['#002060', '남색'],
                ['#7030a0', '보라'], ['#ffffff', '흰색']],
    hiliteColor: [['#ffff00', '노랑'], ['#fff2cc', '연노랑'], ['#c6efce', '연두'], ['#92d050', '초록'], ['#ddebf7', '하늘'],
                  ['#9bc2e6', '파랑'], ['#ffc7ce', '연분홍'], ['#ff99cc', '분홍'], ['#fce4d6', '살구'], ['#e7e6e6', '연회색'],
                  ['#bfbfbf', '회색'], ['#000000', '검정']]
  };
  var openPalette = null;

  function closePalette() {
    if (openPalette) { openPalette.remove(); openPalette = null; }
  }

  function applyColor(sw, ed, cmd, color) {
    if (color !== 'transparent') {
      sw.setAttribute('data-hro-color', color);
      sw.style.background = color;
    }
    exec(ed, cmd, color);
  }

  function openDetail(sw, ed, cmd, x, y) {
    var input = document.createElement('input');
    input.type = 'color';
    input.value = /^#[0-9a-f]{6}$/i.test(sw.getAttribute('data-hro-color') || '') ? sw.getAttribute('data-hro-color') : '#000000';
    input.style.cssText = 'position:fixed;opacity:0;left:' + x + 'px;top:' + y + 'px';
    document.body.appendChild(input);
    input.addEventListener('change', function () {
      applyColor(sw, ed, cmd, input.value);
      input.remove();
    });
    input.addEventListener('blur', function () { setTimeout(function () { input.remove(); }, 500); });
    input.click();
  }

  function cell(color, name, onPick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.title = name;
    b.className = 'hro-pal-cell';
    b.style.cssText = 'width:22px;height:22px;border:1px solid #bbb;border-radius:3px;padding:0;cursor:pointer;background:' + color;
    b.addEventListener('mousedown', function (e) { e.preventDefault(); });   // 편집기 선택 영역 유지
    b.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); onPick(); });
    return b;
  }

  document.addEventListener('click', function (ev) {
    if (openPalette && openPalette.contains(ev.target)) { return; }
    var label = ev.target.closest && ev.target.closest('label');
    var sw = label && label.querySelector('.hro-color');
    if (!sw) { closePalette(); return; }
    ev.preventDefault();
    var wasOpenFor = openPalette && openPalette._sw;
    closePalette();
    if (wasOpenFor === sw) { return; }                  // 같은 버튼 다시 누르면 닫기만
    var ed = editorOf(sw);
    var cmd = sw.getAttribute('data-hro-cmd');
    var box = document.createElement('div');
    box._sw = sw;
    box.className = 'hro-palette shadow';
    var r = label.getBoundingClientRect();
    box.style.cssText = 'position:fixed;z-index:2000;background:#fff;border:1px solid #ccc;border-radius:6px;padding:8px;'
      + 'left:' + r.left + 'px;top:' + (r.bottom + 4) + 'px;width:186px';
    var title = document.createElement('div');
    title.textContent = cmd === 'foreColor' ? '글자색' : '바탕색';
    title.style.cssText = 'font-size:12px;color:#666;margin-bottom:6px';
    box.appendChild(title);
    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(6,22px);gap:6px';
    (PALETTES[cmd] || PALETTES.foreColor).forEach(function (c) {
      grid.appendChild(cell(c[0], c[1], function () { closePalette(); applyColor(sw, ed, cmd, c[0]); }));
    });
    box.appendChild(grid);
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:space-between;margin-top:8px;font-size:12px';
    var none = document.createElement('a');
    none.href = '#';
    none.textContent = cmd === 'foreColor' ? '기본(검정)' : '바탕색 없음';
    none.addEventListener('mousedown', function (e) { e.preventDefault(); });
    none.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation(); closePalette();
      applyColor(sw, ed, cmd, cmd === 'foreColor' ? '#000000' : 'transparent');
    });
    var more = document.createElement('a');
    more.href = '#';
    more.className = 'hro-pal-more';
    more.textContent = '상세 색…';
    more.addEventListener('mousedown', function (e) { e.preventDefault(); });
    more.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation(); closePalette();
      openDetail(sw, ed, cmd, r.left, r.bottom);
    });
    row.appendChild(none);
    row.appendChild(more);
    box.appendChild(row);
    document.body.appendChild(box);
    openPalette = box;
  });

  document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { closePalette(); } });

  // 견본 색 처음 표시
  new MutationObserver(function () {
    document.querySelectorAll('.hro-color:not([data-ready])').forEach(function (sw) {
      sw.setAttribute('data-ready', '1');
      sw.style.cssText = 'width:16px;height:16px;border:1px solid #999;border-radius:3px;margin-left:4px;cursor:pointer;'
        + 'background:' + (sw.getAttribute('data-hro-color') || '#000');
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
