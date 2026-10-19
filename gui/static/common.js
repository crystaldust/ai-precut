// 剪辑台各页面共用：API token、转义（GL-05、GL-07）与事件委托（KI-53）。必须在其它脚本之前同步加载。
(function(){
  const meta = document.querySelector('meta[name="aicut-token"]');
  const TOKEN = meta ? meta.content : '';
  const TOKEN_HEADER = 'X-AICUT-Token';
  const nativeFetch = window.fetch.bind(window);

  function isApi(input){
    const raw = typeof input === 'string' ? input : (input && input.url) || '';
    const u = new URL(raw, location.href);
    return u.origin === location.origin && u.pathname.startsWith('/api/');
  }

  // 所有同源 /api/ 请求自动带 token；<video src> 走 /media/，不需要
  window.fetch = (input, init) => {
    if (!isApi(input)) return nativeFetch(input, init);
    const opt = {...(init || {})};
    const base = opt.headers || (typeof input === 'string' ? {} : input.headers);
    const headers = new Headers(base || {});
    headers.set(TOKEN_HEADER, TOKEN);
    opt.headers = headers;
    return nativeFetch(input, opt);
  };

  // 所有动态文本进 innerHTML / 属性前都过 esc()；属性必须用双引号包住
  window.esc = t => String(t ?? '').replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // 来自 LLM / 磁盘的“数字”先过 num()，再拼进模板或内联事件
  window.num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
  // 磁盘上的答案可能是旧版本 / 手改的：多选值统一成数组再用（KI-49）
  // 没有代理片 / 被浏览器拦下自动播放时 play() 会 reject：播放器自己会显示状态，这里不再抛未处理的 Promise
  window.playQuietly = video => { const p = video.play(); if (p && typeof p.catch === 'function') p.catch(() => {}); };
  window.asList = v => Array.isArray(v) ? v : (typeof v === 'string' && v ? [v] : []);

  // KI-53：CSP 不允许内联事件。元素上写 data-act / data-input / data-change="动作名"，
  // 各脚本把动作注册进 ACTIONS（fn(元素, 事件)）。只取最内层带属性的元素：
  // 行里的按钮被点时只执行按钮的动作，相当于原来的 event.stopPropagation()。
  window.ACTIONS = Object.create(null);  // 没有原型：动作名不会撞上 toString 之类
  function dispatchAction(attr, ev){
    const start = ev.target;
    const target = start && typeof start.closest === 'function' ? start.closest(`[${attr}]`) : null;
    if (!target) return;
    const fn = window.ACTIONS[target.getAttribute(attr)];
    if (typeof fn === 'function') fn(target, ev);
  }
  window.dispatchAction = dispatchAction;
  document.addEventListener('click', ev => dispatchAction('data-act', ev));
  document.addEventListener('input', ev => dispatchAction('data-input', ev));
  document.addEventListener('change', ev => dispatchAction('data-change', ev));
})();
