// 剪辑台主页 · ⑥ 导出（M14）：本次导出（Mac 剪映 / Windows 包）、历史版本卡片、打开剪映、剪映正在运行的提示。
// 对比两版、回到这一版在 export-compare.js。所有版本数据来自 /api/state.versions（gui/views.py 的版本卡片）。

/* 界面文案：产品可直接改这里 */
const COPY_EXPORT_CURRENT_TITLE = '本次导出';
const COPY_EXPORT_CURRENT = '当前分镜表 {n} 镜 · {dur} · 预览片 {at}';
const COPY_EXPORT_CURRENT_NO_PREVIEW = '当前分镜表 {n} 镜 · {dur} · 还没有预览片';
const COPY_EXPORT_AS_NEW = '会导出为 {v}（版本号自动 +1，不会覆盖旧版）';
const COPY_EXPORT_AS_SAME = '当前分镜表已经是 {v}，再导出另一种导出物不会新开版本';
const COPY_EXPORT_MAC = '导出到 Mac 剪映';
const COPY_EXPORT_WIN = '生成 Windows 剪映包';
const COPY_IN_JIANYING = '已在 Mac 剪映里：{draft}';
const COPY_NO_JIANYING = '没检测到剪映专业版，装好后在剪映的本地草稿里找「{draft}」';
const COPY_OPEN_JIANYING = '打开剪映';
const COPY_WIN_USAGE = '拷到 Windows 解压，双击 INSTALL.bat';
const COPY_WIN_DONE = '已生成 {name}（{mb} MB）';
const COPY_REVEAL = '在访达中显示';
const COPY_HISTORY = '历史版本';
const COPY_CURRENT_TAG = '当前';
const COPY_EXPORT_EMPTY = '还没有导出过';
const COPY_VER_FACTS = '{at} · {n} 镜 · {dur}';
const COPY_MAC_DRAFT = 'Mac 剪映：{draft}';
const COPY_MAC_DRAFT_LEGACY = 'Mac 剪映草稿名：{draft}（改版前生成，未记录是否导入过）';
const COPY_NO_PREVIEW = '这一版只有工程，没有预览片';
const COPY_BLOCKED_FALLBACK = '这一版含 {n} 段已标为不可用的片段，不能生成 Windows 剪映包';
const COPY_JY_RUNNING_TITLE = '剪映正在运行';
const COPY_JY_RUNNING_BODY = '导出到 Mac 剪映前请先退出剪映（⌘Q），否则剪映会覆盖草稿库。';
const COPY_JY_RUNNING_GO = '我已关掉，继续';
const COPY_EXPORT_CANCEL = '取消';
const COPY_NO_TIME = '—';
const VERSION_NUM = /^v(\d+)$/;

const jianyingUi = {again: null};
// 注意：结果是纯文本，拼进 innerHTML / 属性前必须再过 esc()（vars 里可能有磁盘上的片名、字幕）
function fillCopy(tpl, vars){ return String(tpl).replace(/\{(\w+)\}/g, (m, k) => k in vars ? String(vars[k]) : m); }
function exportVersions(){ return state.data?.versions || []; }
function fmtClock(iso){
  const d = iso ? new Date(iso) : null;
  if(!d || Number.isNaN(d.getTime())) return COPY_NO_TIME;
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function isBlocked(v){ return num(v.unusable_hits) > 0 || !!v.blocked; }   // KI-100
function currentVersion(){ return exportVersions().find(v => v.current) || null; }
function exportReady(){ return state.data?.preview?.status === 'fresh' && state.shots.length > 0; }
function nextVersionName(){
  const top = Math.max(0, ...exportVersions().map(v => Number((VERSION_NUM.exec(v.name) || [])[1]) || 0));
  return state.data?.next_version || 'v' + (top + 1);
}

/* ---------------- 本次导出 ---------------- */
function exportButton(act, label){
  if(!exportReady())   // 不带 data-starts-job：忙碌守卫会把 disabled 改回去（jobs.js applyBusyGuard）
    return `<button class="primary" data-act="${esc(act)}" disabled title="${esc(COPY_EXPORT_NEED_PREVIEW)}">${esc(label)}</button>`;
  return `<button class="primary" data-act="${esc(act)}" data-starts-job>${esc(label)}</button>`;
}
function macStateHtml(cur){
  const mac = cur && cur.exports && cur.exports.mac;
  if(!mac) return exportButton('exportMac', COPY_EXPORT_MAC);
  const draft = cur.draft || mac.draft || '';
  const open = state.data?.jianying?.installed
    ? `<button class="ghost" data-act="openJianying">${esc(COPY_OPEN_JIANYING)}</button>`
    : `<span class="hint">${esc(fillCopy(COPY_NO_JIANYING, {draft}))}</span>`;   // KI-98：没检测到就不给「打开剪映」
  return `<button class="ghost" disabled>${esc(fillCopy(COPY_IN_JIANYING, {draft}))}</button>${open}`;
}
function windowsDoneHtml(v, i){
  return `<span class="hint">${esc(fillCopy(COPY_WIN_DONE, {name: v.windows_zip, mb: num(v.windows_mb)}))}</span>
    <button class="ghost" data-act="revealExport" data-i="${num(i)}">${esc(COPY_REVEAL)}</button>
    <span class="hint">${esc(COPY_WIN_USAGE)}</span>`;
}
function currentExportHtml(){
  const cur = currentVersion();
  const total = state.shots.reduce((a, s) => a + num(s.out) - num(s.in), 0);
  const at = state.data?.preview?.status === 'none' ? null : state.data?.preview?.at;
  const facts = fillCopy(at ? COPY_EXPORT_CURRENT : COPY_EXPORT_CURRENT_NO_PREVIEW,
                     {n: state.shots.length, dur: fmtLong(Math.max(0, Math.round(total))), at: fmtClock(at)});
  const as = cur ? fillCopy(COPY_EXPORT_AS_SAME, {v: cur.name}) : fillCopy(COPY_EXPORT_AS_NEW, {v: nextVersionName()});
  const win = cur && isBlocked(cur) ? blockedNoteHtml(cur) : cur && cur.windows_zip ? windowsDoneHtml(cur, exportVersions().indexOf(cur)) : exportButton('exportWindows', COPY_EXPORT_WIN);
  return `<section class="ver x-cur"><h3>${esc(COPY_EXPORT_CURRENT_TITLE)} <span class="hint">${esc(facts)}</span></h3>
    <div class="m">${esc(as)}</div>
    <div class="ver-export">${macStateHtml(cur)}${win}</div>
    ${exportReady() ? '' : `<div class="m">${esc(COPY_EXPORT_NEED_PREVIEW)}</div>`}</section>`;
}
function startExport(target){
  if(!exportReady()){ toast(COPY_EXPORT_NEED_PREVIEW); return false; }
  return startJob('build', {target});
}
function exportMac(){ return startExport('mac'); }
function exportWindows(){ return startExport('windows'); }
function closeJianyingModal(again){   // 409 need=close_jianying（jobs.js onJobStartError）：关掉剪映再继续同一个请求
  jianyingUi.again = again;
  showModal(COPY_JY_RUNNING_TITLE, `<p>${esc(COPY_JY_RUNNING_BODY)}</p><div class="job-actions">
    <button class="primary" data-act="jianyingClosedGo">${esc(COPY_JY_RUNNING_GO)}</button>
    <button class="ghost" data-act="jianyingCancel">${esc(COPY_EXPORT_CANCEL)}</button></div>`);
}
function jianyingCancel(){ jianyingUi.again = null; closeModal(); }
function jianyingClosedGo(){
  const again = jianyingUi.again;
  jianyingUi.again = null;
  closeModal();
  if(!again) return undefined;
  if(!exportReady()){ toast(COPY_EXPORT_NEED_PREVIEW); return undefined; }   // 等待期间预览片过期了 / 项目换了：不重发
  return again();
}

/* ---------------- 历史版本卡片 ---------------- */
function macLineHtml(v){
  const mac = v.exports && v.exports.mac;
  const draft = v.draft || (mac && mac.draft);
  if(mac) return `<div class="m">${esc(fillCopy(COPY_MAC_DRAFT, {draft}))}</div>`;
  if(v.legacy && draft) return `<div class="m">${esc(fillCopy(COPY_MAC_DRAFT_LEGACY, {draft}))}</div>`;   // KI-102：新版本没导入过就不显示
  return '';
}
function blockedNoteHtml(v){
  return `<div class="m blocked-note">${esc(v.blocked || fillCopy(COPY_BLOCKED_FALLBACK, {n: num(v.unusable_hits)}))}</div>`;
}
function windowsLineHtml(v, i){
  if(isBlocked(v)) return blockedNoteHtml(v);
  const body = v.windows_zip ? windowsDoneHtml(v, i)
    : `<button class="ghost" data-act="exportVersion" data-i="${num(i)}" data-starts-job>${esc(COPY_EXPORT_WIN)}</button>`;
  return `<div class="m ver-export">${body}</div>`;
}
function restoreButtonHtml(v, i){
  if(!v.has_snapshot) return `<button class="ghost" disabled title="${esc(COPY_RESTORE_NO_SNAPSHOT)}">${esc(COPY_RESTORE)}</button>`;
  return `<button class="ghost" data-act="askRestore" data-i="${num(i)}" data-starts-job>${esc(COPY_RESTORE)}</button>`;
}
function versionCardHtml(v, i){
  const cls = ['ver', isBlocked(v) ? 'blocked' : '', v.current ? 'cur' : ''].filter(Boolean).join(' ');
  const tag = v.current ? ` <span class="tag">${esc(COPY_CURRENT_TAG)}</span>` : '';
  const facts = fillCopy(COPY_VER_FACTS, {at: v.mtime, n: num(v.shots), dur: fmtLong(num(v.duration))});
  const video = v.preview
    ? `<video src="/media/${encodeURIComponent(state.project)}/preview/${encodeURIComponent(v.name)}" controls preload="metadata"></video>`
    : `<p class="hint">${esc(COPY_NO_PREVIEW)}</p>`;
  return `<div class="${cls}"><h3>${compareBoxHtml(i)}${esc(v.name)}${tag} <span class="hint">${esc(facts)}</span></h3>
    ${macLineHtml(v)}${windowsLineHtml(v, i)}${video}
    <div class="m">${restoreButtonHtml(v, i)}</div></div>`;
}
function viewExport(){
  const vs = exportVersions();
  const cards = vs.length ? vs.map(versionCardHtml).join('') : `<div class="empty">${esc(COPY_EXPORT_EMPTY)}</div>`;
  return currentExportHtml() + `<div class="toolbar"><h3>${esc(COPY_HISTORY)}</h3>${compareToolbarHtml()}</div>`
    + comparePanelHtml() + cards;
}

/* ---------------- 动作 ---------------- */
function exportVersion(i){
  const v = exportVersions()[i];
  if(v) startJob('export', {version: v.name});
}
async function revealExport(i){
  const v = exportVersions()[i];
  if(!v) return;
  try{ await postJson('/api/open', {project: state.project, target: 'export', version: v.name}); }
  catch(e){ toast(e.message, TOAST_ERROR_MS); }
}
async function openJianying(){
  try{ await postJson('/api/open', {project: state.project, target: 'jianying'}); }
  catch(e){ toast(e.message, TOAST_ERROR_MS); }
}
function enterExport(){ return refreshOrWarn(); }   // 版本、预览片状态、剪映检测结果都以服务端为准

Object.assign(ACTIONS, {
  exportMac: ()=>exportMac(), exportWindows: ()=>exportWindows(), jianyingClosedGo: ()=>jianyingClosedGo(), jianyingCancel: ()=>jianyingCancel(),
  exportVersion: el=>exportVersion(num(el.dataset.i)), revealExport: el=>revealExport(num(el.dataset.i)),
  openJianying: ()=>openJianying(),
});
