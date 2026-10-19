// 剪辑台各页面共用：API token 与转义（GL-05、GL-07）。必须在页面内联脚本之前同步加载。
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
})();
