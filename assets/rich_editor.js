// 메일 본문 서식 편집기(components/rich_editor.py) — 인사발령(2026-11-20)에서 시작, 업무분장과 공용.
// .rich-wrap 안의 편집기(.rich-editor, contentEditable)에서 고친 내용을 data-store에 적힌 dcc.Store로 올려 보내고,
// 같은 .rich-wrap의 도구 모음([data-hro-cmd])으로 글꼴·크기·굵게·밑줄·글자색·바탕색 등을 document.execCommand로 적용한다.
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

  // 글자색·바탕색: 견본(.hro-color)이 든 라벨을 누르면 색상 선택 창을 열고, 고른 색을 적용·견본에 표시
  document.addEventListener('click', function (ev) {
    var label = ev.target.closest && ev.target.closest('label');
    var sw = label && label.querySelector('.hro-color');
    if (!sw) { return; }
    ev.preventDefault();
    var ed = editorOf(sw);
    var input = document.createElement('input');
    input.type = 'color';
    input.value = sw.getAttribute('data-hro-color') || '#000000';
    input.style.position = 'fixed';
    input.style.opacity = '0';
    input.style.left = ev.clientX + 'px';
    input.style.top = ev.clientY + 'px';
    document.body.appendChild(input);
    input.addEventListener('change', function () {
      sw.setAttribute('data-hro-color', input.value);
      sw.style.background = input.value;
      exec(ed, sw.getAttribute('data-hro-cmd'), input.value);
      input.remove();
    });
    input.addEventListener('blur', function () { setTimeout(function () { input.remove(); }, 500); });
    input.click();
  });

  // 견본 색 처음 표시
  new MutationObserver(function () {
    document.querySelectorAll('.hro-color:not([data-ready])').forEach(function (sw) {
      sw.setAttribute('data-ready', '1');
      sw.style.cssText = 'width:16px;height:16px;border:1px solid #999;border-radius:3px;margin-left:4px;cursor:pointer;'
        + 'background:' + (sw.getAttribute('data-hro-color') || '#000');
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
