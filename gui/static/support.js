// 剪辑台 · 支持入口：一键导出诊断包（GL-19）、「关于 / 第三方许可」（GL-04）、清理缓存（KI-33）、打开项目文件夹。
// 这些都从顶栏「更多」菜单进入（M13）。
// 依赖 base.js 的 state / api / showModal / closeModal / toast，只在调用时才用到。

/* 界面文案：产品可直接改这里 */
const COPY_DIAG_RUNNING = '正在生成诊断包…';
// 导出前的一行说明（与 pipeline/diagnostics.py 文档里的保证一致）
const COPY_DIAG_NOTICE = '诊断包含版本、阶段耗时和日志里的错误行，路径只留文件名、不含素材 / 文稿 / Key；发送前请自己打开看一眼';
const COPY_DIAG_DONE = '诊断包 {name} 已保存到「{folder}」文件夹并在访达中选中，直接拖进微信发给开发者';
const COPY_DIAG_FOLDERS = {Downloads: '下载', Desktop: '桌面'};
const COPY_ABOUT_TITLE = '关于 AI 粗剪 · 第三方许可';
const COPY_ABOUT_VERSION = '版本 {v} · 本软件使用 FFmpeg（LGPL v2.1）等开源软件，许可全文如下';
const COPY_ABOUT_CLOSE = '关闭';
const DIAG_TOAST_MS = 6000;
const COPY_CACHE_TITLE = '清理缓存';             // KI-33（D4）
const COPY_CACHE_INTRO = '会删除下面这些中间文件：镜头切片、没写完的临时文件、已经用完的转写音轨。浏览小样、预览片、新版本和所有分析结果都不会删。删掉的切片会在重新导出、或生成旧版本的 Windows 剪映包时按当时的分镜表重新切（多花几分钟）。';
const COPY_CACHE_TOTAL = '共可释放 {mb} MB';
const COPY_CACHE_EMPTY = '没有可清理的缓存';
const COPY_CACHE_CONFIRM = '清理';
const COPY_CACHE_CANCEL = '取消';
const COPY_CACHE_DONE = '已释放 {mb} MB';

let diagBusy = false;
function setDiagButtons(disabled){
  document.querySelectorAll('[data-act="exportDiag"]').forEach(b => { b.disabled = disabled; });
}
async function exportDiag(){
  if(diagBusy) return;  // 请求进行中：不重复导出
  diagBusy = true; setDiagButtons(true);
  toast(COPY_DIAG_NOTICE + ' · ' + COPY_DIAG_RUNNING, DIAG_TOAST_MS);
  try{
    const j = await api('/api/diagnostics', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({project: state.project || null})});
    const folder = COPY_DIAG_FOLDERS[j.folder] || j.folder || '';
    const done = COPY_DIAG_DONE.replace('{name}', j.name || '').replace('{folder}', folder);
    toast(j.revealed === false && j.message ? j.message : done, DIAG_TOAST_MS);
  }catch(e){ toast(e.message, DIAG_TOAST_MS); }
  finally{ diagBusy = false; setDiagButtons(false); }
}

async function openAbout(){
  let j;
  try{ j = await api('/api/about'); }catch(e){ toast(e.message); return; }
  showModal(COPY_ABOUT_TITLE,
    `<p class="hint">${esc(COPY_ABOUT_VERSION.replace('{v}', j.version || ''))}</p>
     <pre class="notices">${esc(j.notices || '')}</pre>
     <div class="job-actions"><button class="ghost" data-act="closeModal">${esc(COPY_ABOUT_CLOSE)}</button></div>`);
}

/* ---------------- 清理缓存（KI-33） ---------------- */
async function openCache(){
  if(!state.project) return toast('先选项目');
  let j;
  try{ j = await api('/api/cache?project='+encodeURIComponent(state.project)); }
  catch(e){ return toast(e.message, TOAST_ERROR_MS); }
  if(!(j.items||[]).length) return toast(COPY_CACHE_EMPTY);
  const rows = j.items.map(it=>`<li>${esc(it.label)}：<span class="hint">${esc(it.path)}</span> · ${(num(it.bytes)/MB).toFixed(1)} MB</li>`).join('');
  showModal(COPY_CACHE_TITLE, `
    <p class="hint">${esc(COPY_CACHE_INTRO)}</p><ul>${rows}</ul>
    <p>${esc(COPY_CACHE_TOTAL.replace('{mb}', (num(j.total)/MB).toFixed(1)))}</p>
    <div class="job-actions">
      <button class="primary" data-act="cleanCache">${esc(COPY_CACHE_CONFIRM)}</button>
      <button class="ghost" data-act="closeModal">${esc(COPY_CACHE_CANCEL)}</button>
    </div>`);
}
async function cleanCache(){
  const project = state.project;
  if(!project) return;
  try{
    const j = await postJson('/api/cache/clean', {project});
    closeModal(); toast(COPY_CACHE_DONE.replace('{mb}', (num(j.freed)/MB).toFixed(1)));
  }catch(e){ toast(e.message, TOAST_ERROR_MS); }
}
async function openFolder(){
  if(!state.project) return;
  try{ await postJson('/api/open', {project: state.project, target: 'project'}); }
  catch(e){ toast(e.message, TOAST_ERROR_MS); }
}

Object.assign(ACTIONS, {  // KI-53
  exportDiag: ()=>exportDiag(), openAbout: ()=>openAbout(),
  openCache: ()=>openCache(), cleanCache: ()=>cleanCache(), openFolder: ()=>openFolder(),
});
