// 剪辑台 · 设置（API Key）与首次使用的数据外发告知（GL-02）。
// Key 明文只在输入框里出现一次：保存后立即清空，不进 state、不进 toast；界面只显示服务端给的掩码。
// 依赖 index.html 内联脚本里的 $ / api / showModal / closeModal / toast（调用时才用到）。

/* 界面文案：产品可直接改这里 */
const COPY_SETTINGS_TITLE = '设置 · API Key';
const COPY_KEY_CONFIGURED = '已配置 {masked}';
const COPY_KEY_FROM_ENV = '（来自环境变量，此处修改不生效）';
const COPY_KEY_FROM_LEGACY = '（来自旧版文件 ~/.mediakit/api_key；在这里保存新 Key 即可替换）';
const COPY_KEY_LEGACY_LEFT = '（旧版明文文件 ~/.mediakit/api_key 仍在电脑上，剪辑台已不再读取；不需要的话请自己删除它）';
const CLEARABLE_SOURCES = ['keyring', 'file'];  // env / 旧版文件不归剪辑台管，不给「清除」
const COPY_KEY_NOT_SET = '未配置';
const COPY_KEY_PLACEHOLDER = '粘贴 Key';
const COPY_KEY_SAVE = '保存';
const COPY_KEY_CLEAR = '清除';
const COPY_KEY_SAVED = '已保存';
const COPY_KEY_CLEARED = '已清除';
const COPY_KEY_EMPTY = '先粘贴 Key';
const COPY_KEY_STORAGE = 'Key 只保存在本机钥匙串，不会写进日志或项目文件。';
const COPY_SHOW_CONSENT = '查看数据外发说明';
const COPY_SETTINGS_DONE = '完成';
const COPY_SETTINGS_CLOSE = '关闭';
const COPY_KEYS_STILL_MISSING = '还缺 Key，暂不开始分析；填好后再点「开始分析」';
const COPY_CONSENT_TITLE = '使用前请知悉：哪些数据会发到云端';
const COPY_CONSENT_INTRO = '原片和画面不会离开这台电脑。为了完成粗剪，会有两类数据发到云端：';
const COPY_CONSENT_FLOWS = [
  '素材的音轨（16kHz 单声道）→ 火山引擎语音识别，用于转写成文字',
  '转写出的文字 → DeepSeek，用于理解内容、找出重要片段',
];
const COPY_CONSENT_KEYS = '两个服务的 API Key 只保存在本机钥匙串，不会写进日志或项目文件。';
const COPY_CONSENT_OK = '我知道了，继续';
const COPY_CONSENT_LATER = '暂不使用';
const COPY_FIRST_RUN_UNREACHABLE = '剪辑台服务没有响应';
const COPY_FIRST_RUN_RETRY = '重试';
const COPY_FIRST_RUN_KEYS_TITLE = '填写 API Key';
const COPY_FIRST_RUN_KEYS_INTRO = '分析要用到下面两个服务，都填好才能开始。';
const COPY_FIRST_RUN_ENTER = '进入剪辑台';
const SETTINGS_TOAST_MS = 3500;
const PROVIDER_KEY_RE = /^[a-z]{1,32}$/;  // provider 名会拼进 id / data-provider，只认服务端白名单的形状

// then：填好 Key 后要继续做的事（如重新起任务）；required：这次必须有的 Key（来自服务端 409 的 missing）
// inline：Key 在页面里内联填写时（首次打开闸门 / ② 分析页）的回调，保存或清除后拿到最新配置就地重画，不弹设置窗口
const settingsUi = {then: null, required: null, inline: null};

// inlineAct：页内（首次打开闸门 / ② 分析页）的告知——没有「暂不使用」，按钮触发这个动作；缺省是弹窗版
function consentHtml(inlineAct = null){
  const ok = inlineAct ? `<button class="primary" data-act="${esc(inlineAct)}">${esc(COPY_CONSENT_OK)}</button>`
                  : `<button class="primary" id="consentOk">${esc(COPY_CONSENT_OK)}</button>
      <button class="ghost" data-act="closeModal">${esc(COPY_CONSENT_LATER)}</button>`;
  return `<p>${esc(COPY_CONSENT_INTRO)}</p>
    <ul class="consent-flows">${COPY_CONSENT_FLOWS.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>
    <p class="hint">${esc(COPY_CONSENT_KEYS)}</p>
    <div class="job-actions">${ok}</div>`;
}

function keyStatusText(p){
  const left = p.legacy_file ? COPY_KEY_LEGACY_LEFT : '';  // 审查修复 L18
  if(!p.configured) return COPY_KEY_NOT_SET + left;
  const from = {env: COPY_KEY_FROM_ENV, legacy: COPY_KEY_FROM_LEGACY}[p.source] || '';
  return COPY_KEY_CONFIGURED.replace('{masked}', p.masked || '') + from + left;
}

function settingsRowsHtml(cfg){
  return (cfg.providers || []).filter(p=>PROVIDER_KEY_RE.test(p.key)).map(p=>`
    <div class="field">
      <label>${esc(p.label)} <span class="hint">· ${esc(p.hint)}</span></label>
      <div class="hint key-status">${esc(keyStatusText(p))}</div>
      <div class="key-row">
        <input type="password" autocomplete="off" spellcheck="false" id="key_${esc(p.key)}" placeholder="${esc(COPY_KEY_PLACEHOLDER)}">
        <button class="primary" data-act="saveKey" data-provider="${esc(p.key)}">${esc(COPY_KEY_SAVE)}</button>
        ${p.configured && CLEARABLE_SOURCES.includes(p.source) ? `<button class="danger" data-act="deleteKey" data-provider="${esc(p.key)}">${esc(COPY_KEY_CLEAR)}</button>` : ''}
      </div>
    </div>`).join('');
}

// 页内填 Key 就地重画时，别把另一个输入框里已经敲了一半的内容清掉（刚保存成功的那个本来就已清空）
function keepKeyInputs(cfg, redraw){
  const keys = (cfg.providers || []).map(p=>p.key).filter(k=>PROVIDER_KEY_RE.test(k));
  const typed = keys.map(k=>[k, $('#key_'+k)?.value || '']);
  const result = redraw();
  typed.forEach(([k, v])=>{ const input = $('#key_'+k); if(input && v) input.value = v; });
  return result;
}

function openConsent(then){
  showModal(COPY_CONSENT_TITLE, consentHtml());
  $('#consentOk').onclick = async ()=>{
    try{
      const cfg = await api('/api/config/consent', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      closeModal();
      if(then) return then();  // 交给服务端判断还缺哪个 Key（409 need=keys 会带上 missing）
      if(cfg.providers.some(p=>!p.configured)) return openSettings(null);
    }catch(e){ toast(e.message); }
  };
}

async function openSettings(then, required){
  let cfg;
  try{ cfg = await api('/api/config'); }catch(e){ toast(e.message); return; }
  settingsUi.then = then || null;
  settingsUi.required = Array.isArray(required) ? required : null;
  showModal(COPY_SETTINGS_TITLE, settingsRowsHtml(cfg) + `
    <p class="hint">${esc(COPY_KEY_STORAGE)} <a href="#" data-act="showConsent">${esc(COPY_SHOW_CONSENT)}</a></p>
    <div class="job-actions">
      <button class="primary" data-act="finishSettings">${esc(COPY_SETTINGS_DONE)}</button>
      <button class="ghost" data-act="closeSettings">${esc(COPY_SETTINGS_CLOSE)}</button>
    </div>`);
}

function requiredReady(cfg, required){
  const need = required || (cfg.providers || []).map(p=>p.key);
  const ok = new Set((cfg.providers || []).filter(p=>p.configured).map(p=>p.key));
  return need.every(k=>ok.has(k));
}

function closeSettings(){  // 只关闭，不继续之前的操作
  settingsUi.then = null; settingsUi.required = null;
  closeModal();
}

// 「完成」：这次需要的 Key 都齐了才继续（否则只关闭），绝不会 409 → 再弹设置 → 死循环
async function finishSettings(cfg){
  const {then, required} = settingsUi;
  closeSettings();
  if(!then) return;
  if(!cfg){ try{ cfg = await api('/api/config'); }catch(e){ toast(e.message); return; } }
  if(requiredReady(cfg, required)) return then();
  toast(COPY_KEYS_STILL_MISSING, SETTINGS_TOAST_MS);
}

async function saveKey(provider){
  const el = $('#key_'+provider);
  const value = (el?.value || '').trim();
  if(!value){ toast(COPY_KEY_EMPTY); return; }
  try{
    const cfg = await api('/api/config/key', {method:'POST', headers:{'Content-Type':'application/json'},
                                              body: JSON.stringify({provider, value})});
    if(el) el.value = '';  // 保存成功才清空；失败时保留，方便改了再存
    toast(COPY_KEY_SAVED);
    if(settingsUi.inline) return keepKeyInputs(cfg, ()=>settingsUi.inline(cfg));  // 页内填 Key：就地重画，不弹设置窗口
    if(settingsUi.then && requiredReady(cfg, settingsUi.required)) return finishSettings(cfg);
    return openSettings(settingsUi.then, settingsUi.required);
  }catch(e){ toast(e.message, SETTINGS_TOAST_MS); }
}

async function deleteKey(provider){
  try{
    const cfg = await api('/api/config/key/delete', {method:'POST', headers:{'Content-Type':'application/json'},
                                                      body: JSON.stringify({provider})});
    toast(COPY_KEY_CLEARED);
    if(settingsUi.inline) return keepKeyInputs(cfg, ()=>settingsUi.inline(cfg));
    return openSettings(settingsUi.then, settingsUi.required);
  }catch(e){ toast(e.message); }
}

/* ---------------- 首次打开闸门（D17）：全屏外发告知 → 内联填两个 Key → 进入 ----------------
   没有「暂不使用」；两个 Key 都 configured（含来自环境变量）才放行。不再用弹窗和 toast。 */
const firstRunUi = {resolve: null, cfg: null};

function firstRunPassed(cfg){
  return !!cfg.consent && (cfg.providers || []).every(p=>p.configured);
}
function renderFirstRunError(e){
  setStage(`<div class="card error gate"><h2>${esc(COPY_FIRST_RUN_UNREACHABLE)}</h2>
    <p class="hint">${esc(e.message)}</p>
    <button class="primary" data-act="firstRunRetry">${esc(COPY_FIRST_RUN_RETRY)}</button></div>`);
}
function renderFirstRun(cfg){
  firstRunUi.cfg = cfg;
  if(!cfg.consent){
    setStage(`<div class="card gate"><h2>${esc(COPY_CONSENT_TITLE)}</h2>${consentHtml('firstRunConsent')}</div>`);
    return;
  }
  const ready = firstRunPassed(cfg);
  setStage(`<div class="card gate"><h2>${esc(COPY_FIRST_RUN_KEYS_TITLE)}</h2>
    <p>${esc(COPY_FIRST_RUN_KEYS_INTRO)}</p>${settingsRowsHtml(cfg)}
    <p class="hint">${esc(COPY_KEY_STORAGE)}</p>
    <div class="job-actions"><button class="primary" data-act="firstRunEnter"${ready ? '' : ' disabled'}>${esc(COPY_FIRST_RUN_ENTER)}</button></div></div>`);
}
function finishFirstRun(){
  $('#app').classList.remove('first-run');
  settingsUi.inline = null;
  const done = firstRunUi.resolve;
  firstRunUi.resolve = null;
  if(done) done(true);
}
// 返回 Promise<true>：配置齐全时立刻放行；否则显示闸门，等用户走完才放行
async function checkFirstRun(){
  const gate = fn => new Promise(resolve=>{
    firstRunUi.resolve = resolve; settingsUi.inline = renderFirstRun; $('#app').classList.add('first-run'); fn();
  });
  let cfg;
  try{ cfg = await api('/api/config'); }
  catch(e){ return gate(()=>renderFirstRunError(e)); }
  return firstRunPassed(cfg) ? true : gate(()=>renderFirstRun(cfg));
}
async function firstRunRetry(){
  let cfg;
  try{ cfg = await api('/api/config'); }catch(e){ return renderFirstRunError(e); }
  return firstRunPassed(cfg) ? finishFirstRun() : renderFirstRun(cfg);
}
async function firstRunConsent(){
  try{ renderFirstRun(await api('/api/config/consent', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})); }
  catch(e){ toast(e.message, SETTINGS_TOAST_MS); }
}
function firstRunEnter(){ if(firstRunUi.cfg && firstRunPassed(firstRunUi.cfg)) finishFirstRun(); }

Object.assign(ACTIONS, {  // KI-53：设置弹窗与外发告知的按钮
  openSettings: ()=>openSettings(), saveKey: el=>saveKey(el.dataset.provider),
  deleteKey: el=>deleteKey(el.dataset.provider), finishSettings: ()=>finishSettings(),
  closeSettings: ()=>closeSettings(), showConsent: (el, ev)=>{ ev.preventDefault(); openConsent(); },
  firstRunConsent: ()=>firstRunConsent(), firstRunRetry: ()=>firstRunRetry(), firstRunEnter: ()=>firstRunEnter(),
});
