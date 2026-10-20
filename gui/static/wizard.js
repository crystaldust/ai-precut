// 剪辑台主页 · 向导外壳（M13）：顶栏标题、步骤条、横幅、底部导航、「更多」菜单。
// 步骤状态全部来自服务端 state.data.wizard（gui/wizard.py）；这里只负责渲染和切换，不自己推导。

/* 界面文案：产品可直接改这里 */
const COPY_NO_PROJECT_TITLE = '还没有选择项目';
const COPY_LLM_USAGE = 'LLM 已用 {n} tokens';    // KI-32：只显示 tokens，不折算金额（D3）
const COPY_LLM_USAGE_CAP = '（上限 {n}）';
const COPY_TOKENS_WAN = '{n} 万';
const TOKENS_WAN = 10000;
const COPY_PREV = '← 上一步';
const COPY_NEXT = '下一步：{label} →';
const COPY_GO_LABELS = {browse: '去看素材', criteria: '去定标准', result: '去看结果', export: '去导出'};
const COPY_BANNER_ACTIONS = {reanalyze: '重新分析', reselect: '重新选段'};
const COPY_MANUAL_SHOTS_NOTE = '你手动改过分镜表，重新选段只更新建议，不会覆盖它（后续版本会让你选择覆盖或保留）';
const STEP_NAMES = ['新建', '分析', '看素材', '定标准', '看结果', '导出'];  // ①–⑥，与服务端 gui/wizard.py 的 STEPS 一致（tests/test_terms.py 比对）
const STEP_STATUSES = ['locked', 'done', 'stale', 'available'];  // class 名只认这几个
const STATUS_MARK = {done: ' ✓', stale: ' ⚠'};
const VIEW_ORDER = ['analyze', 'browse', 'criteria', 'result', 'export'];  // ① 新建是弹窗，不在页面序列里

const MORE_PROJECT_ITEMS = [
  {key: 'settings', act: 'openProjectSettings', label: '项目设置'},
  {key: 'folder', act: 'openFolder', label: '打开项目文件夹'},
  {key: 'cache', act: 'openCache', label: '清理缓存'},
];
const MORE_COMMON_ITEMS = [
  {key: 'keys', act: 'openSettings', label: '设置 · API Key'},
  {key: 'shortcuts', act: 'openShortcuts', label: '快捷键'},
  {key: 'diag', act: 'exportDiag', label: '导出诊断包'},
  {key: 'about', act: 'openAbout', label: '关于 / 第三方许可'},
];

function stepOf(key){ return (state.data?.wizard?.steps || []).find(s => s.key === key) || null; }

/* ---------------- 顶栏标题 ---------------- */
function fmtTokens(n){
  n = num(n);
  return n >= TOKENS_WAN ? COPY_TOKENS_WAN.replace('{n}', (n / TOKENS_WAN).toFixed(1)) : String(n);
}
function usageText(u){
  if(!u || !num(u.total_tokens)) return '';
  const cap = u.budget ? COPY_LLM_USAGE_CAP.replace('{n}', fmtTokens(u.budget)) : '';
  return ' · ' + COPY_LLM_USAGE.replace('{n}', fmtTokens(u.total_tokens)) + cap;
}
function renderTitle(){
  const d = state.data;
  if(!d){ $('#title').textContent = COPY_NO_PROJECT_TITLE; $('#meta').textContent = ''; return; }
  const c = d.project;
  $('#title').textContent = c.title || c.name;
  const md = d.material_duration ? `素材 ${fmtLong(d.material_duration)} · ` : '';
  $('#meta').textContent = `${md}预设 ${c.preset} · 平台 ${c.platform} · 目标 ${c.target_duration ? fmtLong(num(c.target_duration)) : '—'}${usageText(d.llm_usage)}`;
}

/* ---------------- 步骤条 ---------------- */
function stepButtonHtml(s, viewing){
  const status = STEP_STATUSES.includes(s.status) ? s.status : 'available';
  const cls = ['step', 'st-' + status, s.key === viewing ? 'current' : ''].filter(Boolean).join(' ');
  const disabled = status === 'locked' ? ' aria-disabled="true"' : '';
  const title = s.hint || s.banner || '';  // 悬停原因：未到 → 先完成哪步；需要更新 → 为什么
  return `<button class="${cls}" data-act="go" data-step="${esc(s.key)}"${disabled} title="${esc(title)}">`
    + `${esc(CIRCLED[num(s.n) - 1] || '')}${esc(s.label || STEP_NAMES[num(s.n) - 1] || '')}${STATUS_MARK[status] || ''}</button>`;
}
function stepsHtml(wizard, viewing){
  return (wizard?.steps || []).map(s => stepButtonHtml(s, viewing)).join('<span class="step-sep">→</span>');
}
function renderSteps(wizard=state.data?.wizard, viewing=state.view){
  const html = stepsHtml(wizard, viewing);
  $('#steps').innerHTML = html;
  return html;
}

/* ---------------- 横幅 ---------------- */
function bannerHtml(step){
  if(!step || !step.banner) return '';
  const stale = step.status === 'stale';
  const label = COPY_BANNER_ACTIONS[step.action];
  if(!label) return `<div class="banner${stale ? ' stale' : ''}"><span>${esc(step.banner)}</span></div>`;
  const [text, ...rest] = String(step.banner).split(' · ');  // 「原因 · 动作（说明）」
  const note = /（([^）]*)）/.exec(rest.join(' · '));
  return `<div class="banner stale"><span>${esc(text)}</span>`
    + `<button class="primary" data-act="${esc(step.action)}" data-starts-job>${esc(label)}</button>`
    + (note ? `<span class="note">${esc(note[1])}</span>` : '') + '</div>';
}
function renderBanner(){
  const step = stepOf(state.view);
  const manual = state.data?.shots_from_selection === false && state.shots.length;
  const extra = step && step.key === 'result' && step.status === 'stale' && manual
    ? `<div class="banner note"><span>${esc(COPY_MANUAL_SHOTS_NOTE)}</span></div>` : '';
  const html = bannerHtml(step) + extra;
  $('#banner').innerHTML = html;
  return html;
}

/* ---------------- 底部导航 ---------------- */
function navModel(wizard, viewing){
  const steps = wizard?.steps || [];
  const at = VIEW_ORDER.indexOf(viewing);
  const status = key => steps.find(s => s.key === key)?.status;
  const link = key => key && status(key) ? {key, enabled: status(key) !== 'locked'} : null;
  const prev = link(VIEW_ORDER[at - 1]);
  const next = link(VIEW_ORDER[at + 1]);
  return {prev: at > 0 ? prev : null,
          next: next ? {...next, label: COPY_GO_LABELS[next.key] || ''} : null};
}
function navButtonHtml(item, cls, text){
  const hint = stepOf(item.key)?.hint || '';
  return `<button class="${cls}" data-act="go" data-step="${esc(item.key)}"`
    + (item.enabled ? '' : ` aria-disabled="true" title="${esc(hint)}"`) + `>${esc(text)}</button>`;
}
function renderNav(wizard=state.data?.wizard, viewing=state.view){
  const m = navModel(wizard, viewing);
  const next = viewing === 'criteria' ? gateNavHtml()   // 闸门步骤的「下一步」就是闸门按钮（step-criteria.js）
    : (m.next ? navButtonHtml(m.next, 'primary', COPY_NEXT.replace('{label}', m.next.label)) : '<span></span>');
  const html = wizard ? (m.prev ? navButtonHtml(m.prev, 'ghost', COPY_PREV) : '<span></span>') + next : '';
  $('#nav').innerHTML = html;
  return html;
}

/* ---------------- 更多菜单 ---------------- */
function moreItems(hasProject){ return hasProject ? [...MORE_PROJECT_ITEMS, ...MORE_COMMON_ITEMS] : MORE_COMMON_ITEMS; }
function moreHtml(){
  return moreItems(!!state.project).map(i =>
    `<button data-act="moreItem" data-item="${esc(i.key)}">${esc(i.label)}</button>`).join('');
}
function closeMore(){ $('#moreMenu').classList.remove('on'); }
function toggleMore(){
  if($('#moreMenu').classList.contains('on')) return closeMore();
  $('#moreMenu').innerHTML = moreHtml();
  $('#moreMenu').classList.add('on');
}
function moreItem(key){
  closeMore();
  const item = moreItems(!!state.project).find(i => i.key === key);
  const run = item && ACTIONS[item.act];
  if(typeof run === 'function') return run(null, null);
}
function initMore(){  // 点菜单外面 / 按 Esc 收起
  document.addEventListener('click', ev=>{
    const inside = ev.target && typeof ev.target.closest === 'function' && ev.target.closest('.more-wrap');
    if(!inside) closeMore();
  });
  document.addEventListener('keydown', ev=>{ if(ev.key === 'Escape') closeMore(); });
}

/* ---------------- 外壳整体重绘（步骤状态变了就调用） ---------------- */
function renderChrome(){
  renderTitle(); renderSteps(); renderBanner(); renderNav();
  renderChip(); applyBusyGuard(); setRail();
}

Object.assign(ACTIONS, {
  go: el=>go(el.dataset.step), toggleMore: ()=>toggleMore(), moreItem: el=>moreItem(el.dataset.item),
  reanalyze: ()=>startAnalysis(), reselect: ()=>startJob('select', {}),
});
