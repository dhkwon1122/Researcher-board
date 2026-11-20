// pages/hr_order.py(인사발령) 본문 서식 편집기 전용(2026-11-20).
// 본문 칸(#hro-body-editor, contentEditable)에서 고친 내용을 dcc.Store(#hro-body)로 올려 보내고,
// 도구 모음([data-hro-cmd])의 글꼴·크기·굵게·밑줄·글자색·바탕색 등을 document.execCommand로 적용한다.
// 저장·발송 전에 서버(services/hr_order_mail.sanitize_html)가 허용한 서식만 남긴다.
(function () {
  var saved = null;   // 편집기 안의 마지막 선택 영역(도구 모음을 누르면 포커스가 빠지므로 되살린다)

  function editor() { return document.getElementById('hro-body-editor'); }

  function sync() {
    var ed = editor();
    if (ed && window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props('hro-body', { data: ed.innerHTML });
    }
  }

  function restore() {
    var ed = editor();
    if (!ed) { return false; }
    ed.focus();
    if (saved) {
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(saved);
    }
    return true;
  }

  function exec(cmd, val) {
    if (!restore()) { return; }
    document.execCommand('styleWithCSS', false, cmd !== 'fontSize');
    document.execCommand(cmd, false, val == null ? null : val);
    sync();
  }

  document.addEventListener('selectionchange', function () {
    var ed = editor();
    var sel = window.getSelection();
    if (ed && sel.rangeCount && ed.contains(sel.anchorNode)) {
      saved = sel.getRangeAt(0).cloneRange();
    }
  });

  document.addEventListener('input', function (ev) {
    if (ev.target && ev.target.id === 'hro-body-editor') { sync(); }
  });

  // 버튼: mousedown에서 기본 동작(포커스 이동)을 막아 선택 영역 유지
  document.addEventListener('mousedown', function (ev) {
    var btn = ev.target.closest && ev.target.closest('button[data-hro-cmd]');
    if (btn) {
      ev.preventDefault();
      exec(btn.getAttribute('data-hro-cmd'), btn.getAttribute('data-hro-val'));
    }
  });

  // 글꼴·크기 선택
  document.addEventListener('change', function (ev) {
    var t = ev.target;
    if (t && t.tagName === 'SELECT' && t.getAttribute('data-hro-cmd')) {
      if (t.value) { exec(t.getAttribute('data-hro-cmd'), t.value); }
      t.selectedIndex = 0;
    }
  });

  // 글자색·바탕색: 견본(.hro-color)을 누르면 색상 선택 창을 열고, 고른 색을 적용·견본에 표시
  document.addEventListener('click', function (ev) {
    var sw = ev.target.closest && ev.target.closest('label') && ev.target.closest('label').querySelector('.hro-color');
    if (!sw) { return; }
    ev.preventDefault();
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
      exec(sw.getAttribute('data-hro-cmd'), input.value);
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
