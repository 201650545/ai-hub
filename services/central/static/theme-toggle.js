/* theme-toggle.js —— 深色模式切换按钮逻辑（首页 / dashboard 共用）
 * data-theme 在 <head> 内联脚本已据 localStorage 预置，此处只负责点击翻转。
 * 图标的显隐由 theme.css 按 :root[data-theme] 控制，无需 JS 操心。
 */
(function () {
  var d = document.documentElement;
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', function () {
    var next = d.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    d.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) {}
  });
})();
