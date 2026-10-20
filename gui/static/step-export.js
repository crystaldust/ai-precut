// 剪辑台主页 · ⑥ 导出（M13b 暂住）：版本卡片、生成新版本（导出到 Mac 剪映）、生成 Windows 剪映包、打开剪映。
// 正式版（对比两版、回到这一版）在后续里程碑替换这个文件。

/* 界面文案：产品可直接改这里 */
const COPY_EXPORT_NEW = '生成新版本（导出到 Mac 剪映）';
const COPY_EXPORT_OPEN_JIANYING = '打开剪映';
const COPY_EXPORT_EMPTY = '还没有导出过';
const COPY_BUILD_TITLE = '生成新版本';
const COPY_BUILD_INTRO = '会按分镜表切镜头、渲染预览片，并生成剪映工程（版本号自动 +1，不会覆盖旧版）。';
const COPY_BUILD_PREVIEW_ONLY = '这次只生成预览片，不导出到剪映（剪映开着时用）';
const COPY_BUILD_START = '开始';
const COPY_BUILD_CANCEL = '取消';
const COPY_EXPORT_WINDOWS = '生成 Windows 剪映包';
const COPY_EXPORTED = '已生成 {name}（{mb} MB）';
const COPY_REVEAL = '在访达中显示';
const COPY_MAC_DRAFT = 'Mac 剪映草稿名：';
const COPY_NO_PREVIEW = '这一版只有工程，没有预览片';

/* ---------------- 版本卡片：Windows 导出（GL-14） ---------------- */
function versionExportHtml(v, i){
  const done = v.windows_zip
    ? `<span class="hint">${esc(COPY_EXPORTED.replace('{name}', v.windows_zip).replace('{mb}', num(v.windows_mb)))}</span>
       <button class="ghost" data-act="revealExport" data-i="${num(i)}">${esc(COPY_REVEAL)}</button>` : '';
  return `<div class="m ver-export">
      <button class="ghost" data-act="exportVersion" data-i="${num(i)}" data-starts-job>${esc(COPY_EXPORT_WINDOWS)}</button>${done}
    </div>`;
}
function exportVersion(i){
  const v = (state.data?.versions || [])[i];
  if(v) startJob('export', {version: v.name});
}
async function revealExport(i){
  const v = (state.data?.versions || [])[i];
  if(!v) return;
  try{ await postJson('/api/open', {project: state.project, target: 'export', version: v.name}); }
  catch(e){ toast(e.message); }
}

function viewExport(){
  const vs = state.data?.versions || [];
  const head = `<div class="toolbar">
      <button class="primary" data-act="openBuild" data-starts-job>${esc(COPY_EXPORT_NEW)}</button>
      <button class="ghost" data-act="openJianying">${esc(COPY_EXPORT_OPEN_JIANYING)}</button>
    </div>`;
  if(!vs.length) return head + `<div class="empty">${esc(COPY_EXPORT_EMPTY)}</div>`;
  return head + vs.map((v, i)=>`<div class="ver">
    <h3>${esc(v.name)} <span class="hint">${num(v.shots)} 镜 · ${fmtLong(num(v.duration))} · ${esc(v.mtime)}</span></h3>
    <div class="m">${esc(COPY_MAC_DRAFT)}<b>${esc(v.draft)}</b></div>
    ${versionExportHtml(v, i)}
    ${v.preview? `<video src="/media/${encodeURIComponent(state.project)}/preview/${encodeURIComponent(v.name)}" controls preload="metadata"></video>` : `<p class="hint">${esc(COPY_NO_PREVIEW)}</p>`}
  </div>`).join('');
}

/* ---------------- 生成新版本弹窗 ---------------- */
function openBuild(){
  showModal(COPY_BUILD_TITLE, `
    <p class="hint">${esc(COPY_BUILD_INTRO)}</p>
    <label style="display:flex;gap:8px;align-items:center;margin:10px 0">
      <input type="checkbox" id="noDraft"> ${esc(COPY_BUILD_PREVIEW_ONLY)}
    </label>
    <button class="primary" data-act="doBuild" data-starts-job>${esc(COPY_BUILD_START)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_BUILD_CANCEL)}</button>`);
}
function doBuild(){
  const noDraft = $('#noDraft')?.checked;
  closeModal();
  return startJob('build', {no_draft: noDraft});
}
async function openJianying(){
  try{ await postJson('/api/open', {project: state.project, target: 'jianying'}); }
  catch(e){ toast(e.message, TOAST_ERROR_MS); }
}

Object.assign(ACTIONS, {
  exportVersion: el=>exportVersion(num(el.dataset.i)), revealExport: el=>revealExport(num(el.dataset.i)),
  openBuild: ()=>openBuild(), doBuild: ()=>doBuild(), openJianying: ()=>openJianying(),
});
