// 剪辑台主页 · ⑤ 看结果（M14，闸门 B）：页面骨架、顶栏摘要、就地改目标时长、预览片、闸门「看过了，去导出」。
// 分镜表与播放器在 result-table.js，未采用清单在 result-unused.js，重新选段询问与恢复为 AI 选段在 reselect.js。
// 页面骨架是固定的（viewResult 恒返回同一段 HTML，刷新不会重画它）；各块由 paintResult 按需填入，内容没变就不写。
// 服务端数字（覆盖率、未采用、预览片是否新鲜）来自 GET /api/result，进入 ⑤ / 每次保存成功 / 任务结束后重拉（序号防乱序）。

/* 界面文案：产品可直接改这里 */
const COPY_TOP_TARGET = '目标';
const COPY_TOP_CHANGE = '改';
const COPY_TOP_CUR = '当前';
const COPY_TOP_SHOTS = '镜头';
const COPY_TOP_CLIP = '剪辑列表';
const COPY_TOP_CLIP_COUNT = '{c}/{m} 进片';
const COPY_TOP_OK = ' ✓';
const COPY_TOP_SEP = ' · ';
const COPY_TARGET_OK = '确定';
const COPY_TARGET_CANCEL = '取消';
const COPY_RESULT_OVER = '剪辑列表共 {must}，超过目标 {target} · 建议改为 {suggest}';
const COPY_OVER_APPLY = '改为 {suggest}';
const COPY_PREVIEW_NONE = '还没有预览片';
const COPY_PREVIEW_MAKE = '生成预览片';
const COPY_PREVIEW_OUTDATED = '分镜表改过了 · 重新生成预览片';
const COPY_PREVIEW_UNUSABLE = '有片段标成了不可用 · 重新生成预览片';
const COPY_PREVIEW_EMPTY_TABLE = '分镜表是空的，先生成镜头';
const COPY_PREVIEW_SAVE_FIRST = '分镜表还没保存成功，先不生成预览片';
const COPY_GATE_B = '看过了，去导出 →';
const COPY_GATE_B_HINT = '先生成当前分镜表的预览片';
const COPY_ANALYSIS_UPDATED_MANUAL = '分析结果更新了：分镜表仍是你手动改的那一版；需要时点「恢复为 AI 选段」';  // Q6
const COPY_EXPORT_NEED_PREVIEW = '先在「⑤ 看结果」生成当前分镜表的预览片';  // 与 gui/wizard.py 的 LOCKED_EXPORT_HINT 一致
const RESULT_RELOAD_MS = 400;   // 保存成功后重拉 ⑤ 数据的防抖：连续保存只拉一次

let resultGen = 0;   // 每次进入 / 离开 / 重置 +1：过期的 /api/result 回包一律丢掉
const RESULT_SKELETON = `<div class="res">
  <div class="r-top" id="rTop"></div>
  <div class="r-cols">
    <section class="r-left" id="rTable"></section>
    <aside class="r-right">
      <div class="r-player" id="rPlayer">
        <div class="r-mode" id="rMode"></div><div id="rVideo"></div><div class="r-note" id="rPvNote"></div><div class="r-tools" id="rTools"></div>
      </div>
      <section class="r-unused" id="rUnused"></section>
    </aside>
  </div></div>`;
function viewResult(){ return RESULT_SKELETON; }
function res(){ return state.result; }
function newResult(){
  return {project: state.project, data: null, mode: 'preview', open: new Set(), adding: new Set(), editing: false,
          touched: false, reloadTimer: null, loadSeq: 0, stopAt: null, html: {}, playerKey: null, tableSig: null,
          lockPainted: false};
}
function resetResult(){
  resultGen += 1;
  const r = res();
  if(r && r.reloadTimer) clearTimeout(r.reloadTimer);
  state.result = null;
}
function leaveResult(){   // 离开 ⑤：在途回包作废，页面上的块随骨架一起被换掉，缓存清空
  resultGen += 1;
  const r = res();
  if(!r) return;
  if(r.reloadTimer){ clearTimeout(r.reloadTimer); r.reloadTimer = null; }
  r.html = {}; r.playerKey = null; r.tableSig = null; r.stopAt = null;
}
function enterResult(){
  resultGen += 1;
  if(!res() || res().project !== state.project) state.result = newResult();
  const r = res();
  r.html = {}; r.playerKey = null; r.tableSig = null;
  paintResult(true);
  return loadResult();
}
function setIf(sel, html){   // 内容没变就不写：输入框和滚动位置不被刷新打断
  const r = res();
  if(r.html[sel] === html) return;
  r.html[sel] = html;
  $(sel).innerHTML = html;
}
async function loadResult(){
  const r = res(), gen = resultGen, name = state.project;
  if(!r || !name) return;
  const seq = ++r.loadSeq, editsAtSend = editSeq;
  let data;
  try{ data = await api('/api/result?project=' + encodeURIComponent(name)); }
  catch(e){ if(gen === resultGen && seq === r.loadSeq) toast(e.message, TOAST_ERROR_MS); return; }
  if(gen !== resultGen || seq !== r.loadSeq || state.result !== r || state.project !== name) return;
  r.data = data;
  if(editSeq === editsAtSend) r.touched = false;   // 请求发出之后又改过表：服务端这份不是最新的，仍按「改过」算
  if(state.data) state.data = {...state.data, manual: data.manual, preview: {status: data.preview.status}};  // ④ / 闸门读这份
  applyWizard(data.wizard);
  paintResult();
  renderNav();
}
function reloadResultNow(project){ if(state.view === 'result' && state.project === project) return loadResult(); }
// 保存成功（app.js postShots 调用）：防抖后重拉
function onShotsSaved(project){
  const r = res();
  if(!r || state.view !== 'result' || state.project !== project) return;
  clearTimeout(r.reloadTimer);
  r.reloadTimer = setTimeout(()=>{ r.reloadTimer = null; if(state.result === r && state.view === 'result') loadResult(); }, RESULT_RELOAD_MS);
}
function onResultJobDone(task){   // 在 ⑤ 时重新选段 / 生成预览片结束：重拉，预览片完成后回到预览片模式
  const r = res();
  if(!r) return;
  if(task === 'preview') r.mode = 'preview';
  r.tableSig = null;
  return loadResult();
}
function paintResult(force){
  const r = res();
  if(!r || state.view !== 'result') return;
  paintTop(); paintTable(force); paintPlayer(); paintUnused();
  applyBusyGuard();  // 刚画出来的「改」「生成预览片」等启动类按钮：有任务在跑就置灰
}

/* ---------------- 预览片状态 ---------------- */
function previewData(){ const r = res(); return r && r.data ? r.data.preview : null; }
function previewStatus(){   // 本地改过表还没重拉时，新鲜的预览片也按「过期」算
  const r = res(), pv = previewData();
  const status = pv ? pv.status : (state.data?.preview?.status || 'none');
  return r && r.touched && status === 'fresh' ? 'outdated' : status;
}
function previewNoteHtml(pv){
  const status = previewStatus();
  if(status === 'fresh') return '';
  const unusable = pv && Array.isArray(pv.reasons) && pv.reasons.includes('unusable') && !res().touched;
  const text = status === 'none' ? COPY_PREVIEW_NONE : (unusable ? COPY_PREVIEW_UNUSABLE : COPY_PREVIEW_OUTDATED);
  return `<span class="hint">${esc(text)}</span> <button class="primary" data-act="makePreview" data-starts-job>${esc(COPY_PREVIEW_MAKE)}</button>`;
}
async function makePreview(){
  if(!state.project) return;
  if(!state.shots.length){ toast(COPY_PREVIEW_EMPTY_TABLE); return; }
  if(await flushPendingSave() === false){ toast(COPY_PREVIEW_SAVE_FIRST, TOAST_ERROR_MS); return; }
  return startJob('preview');
}
// ⑥ 的门（Q2）：有历史版本就能进；否则要有当前分镜表的新鲜预览片。步骤条、闸门 B、键盘激活都走 go()，同一处拦
function exportDoorOpen(){
  if((state.data?.versions || []).length) return true;
  const status = state.view === 'result' ? previewStatus() : (state.data?.preview?.status || 'none');
  return status === 'fresh';
}
function resultGateHtml(){   // 闸门 B：当前分镜表的预览片已生成才可点
  if(previewStatus() === 'fresh') return `<button class="primary" data-act="go" data-step="export">${esc(COPY_GATE_B)}</button>`;
  return `<button class="primary" data-act="gateBHint" aria-disabled="true" title="${esc(COPY_GATE_B_HINT)}">${esc(COPY_GATE_B)}</button>`;
}

/* ---------------- 顶栏 ---------------- */
function liveTotal(){ return state.shots.reduce((a, s) => a + num(s.out) - num(s.in), 0); }
function paintLive(){
  const cur = $('#rCur'), cnt = $('#rCnt');
  if(cur) cur.textContent = fmtLong(Math.max(0, Math.round(liveTotal())));
  if(cnt) cnt.textContent = String(state.shots.length);
}
function targetHtml(r, tb){
  if(r.editing) return `${esc(COPY_TOP_TARGET)} ${durationFields('tgt', num(tb.target))}
    <button class="primary" data-act="applyTarget" data-starts-job>${esc(COPY_TARGET_OK)}</button>
    <button class="ghost" data-act="cancelTarget">${esc(COPY_TARGET_CANCEL)}</button>`;
  return `${esc(COPY_TOP_TARGET)} <b>${fmtLong(num(tb.target))}</b> <button class="ghost" data-act="editTarget" data-starts-job>${esc(COPY_TOP_CHANGE)}</button>`;
}
function clipHtml(tb){
  const count = num(tb.clip?.count), covered = num(tb.clip?.covered), missing = covered < count;
  const text = COPY_TOP_CLIP_COUNT.replace('{c}', covered).replace('{m}', count) + (count && !missing ? COPY_TOP_OK : '');
  return `${esc(COPY_TOP_CLIP)} <b${missing ? ' class="warn"' : ''}>${esc(text)}</b>`;
}
function overHtml(tb){
  if(!tb.over_target) return '';
  const suggest = num(tb.suggested_target);
  const text = COPY_RESULT_OVER.replace('{must}', fmtMinSec(tb.must_total)).replace('{target}', fmtMinSec(tb.target))
    .replace('{suggest}', fmtMinSec(suggest));
  const apply = suggest ? ` <button class="primary" data-act="applySuggested" data-starts-job>${esc(COPY_OVER_APPLY.replace('{suggest}', fmtMinSec(suggest)))}</button>` : '';
  return `<div class="r-over">⚠ ${esc(text)}${apply}</div>`;
}
function manualNoteHtml(r){   // Q6：重新分析后分镜表仍是手动那一版
  const reasons = stepOf('result')?.reasons || [];
  return r.data && r.data.source === 'manual' && reasons.includes('scored')
    ? `<div class="r-over">${esc(COPY_ANALYSIS_UPDATED_MANUAL)}</div>` : '';
}
function topHtml(r, live){
  const tb = r.data?.topbar;
  if(!tb) return '';
  const cur = live ? fmtLong(Math.max(0, Math.round(liveTotal()))) : '', cnt = live ? state.shots.length : '';
  const edited = manualInfo()?.edited === true;
  const restore = edited ? `<button class="ghost r-restore" data-act="openRestoreAi" data-starts-job>${esc(COPY_RESTORE_AI)}</button>` : '';
  return `<div class="r-stats"><span>${targetHtml(r, tb)}</span>${esc(COPY_TOP_SEP)}<span>${esc(COPY_TOP_CUR)} <b id="rCur">${cur}</b></span>`
    + `${esc(COPY_TOP_SEP)}<span>${esc(COPY_TOP_SHOTS)} <b id="rCnt">${cnt}</b></span>${esc(COPY_TOP_SEP)}<span>${clipHtml(tb)}</span>${restore}</div>`
    + overHtml(tb) + manualNoteHtml(r);
}
function paintTop(){
  const r = res();
  if(r.html['#rTop'] !== topHtml(r, false)){
    r.html['#rTop'] = topHtml(r, false);
    $('#rTop').innerHTML = topHtml(r, true);
  }
  paintLive();
}
function editTarget(){ const r = res(); if(r){ r.editing = true; paintTop(); } }
function cancelTarget(){ const r = res(); if(r){ r.editing = false; paintTop(); } }
async function applyTarget(){
  const t = readDuration('tgt');
  if(!t){ toast(COPY_TARGET_RANGE); return; }
  if(await confirmReselect({target: t}) === null) return;   // 取消 / 没起来：编辑框和输入的时长都保留
  cancelTarget();                                             // 任务确实起来了才关
}
async function applySuggested(){
  const suggest = num(res()?.data?.topbar?.suggested_target);
  if(suggest) await confirmReselect({target: suggest});
}

Object.assign(ACTIONS, {
  editTarget: ()=>editTarget(), cancelTarget: ()=>cancelTarget(), applyTarget: ()=>applyTarget(),
  applySuggested: ()=>applySuggested(), makePreview: ()=>makePreview(),
  gateBHint: ()=>toast(COPY_GATE_B_HINT), retrySave: ()=>retrySave(),
});
