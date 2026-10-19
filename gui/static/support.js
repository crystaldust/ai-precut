// 剪辑台 · 支持入口：一键导出诊断包（GL-19）与「关于 / 第三方许可」（GL-04）。
// 依赖 index.html 内联脚本里的 state / api / showModal / closeModal / toast，只在调用时才用到。

/* 界面文案：产品可直接改这里 */
const COPY_DIAG_BUTTON = '导出诊断包';
const COPY_DIAG_RUNNING = '正在生成诊断包…';
// 导出前的一行说明（与 pipeline/diagnostics.py 文档里的保证一致）
const COPY_DIAG_NOTICE = '诊断包含版本、阶段耗时和日志里的错误行，路径只留文件名、不含素材 / 文稿 / Key；发送前请自己打开看一眼';
const COPY_DIAG_DONE = '诊断包 {name} 已保存到「{folder}」文件夹并在访达中选中，直接拖进微信发给开发者';
const COPY_DIAG_FOLDERS = {Downloads: '下载', Desktop: '桌面'};
const COPY_ABOUT_BUTTON = '关于 / 第三方许可';
const COPY_ABOUT_TITLE = '关于 AI 粗剪 · 第三方许可';
const COPY_ABOUT_VERSION = '版本 {v} · 本软件使用 FFmpeg（LGPL v2.1）等开源软件，许可全文如下';
const COPY_ABOUT_CLOSE = '关闭';
const DIAG_TOAST_MS = 6000;

let diagBusy = false;
function setDiagButtons(disabled){
  document.querySelectorAll('[onclick="exportDiag()"]').forEach(b => { b.disabled = disabled; });
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
     <div class="job-actions"><button class="ghost" onclick="closeModal()">${esc(COPY_ABOUT_CLOSE)}</button></div>`);
}
