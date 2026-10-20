// 剪辑台主页 · 重新选段前的询问与恢复为 AI 选段（M14，KI-95）。
// 三个入口都走 confirmReselect：⑤ 改目标时长 / 建议时长、横幅「重新选段」、④ 重新确认（step-criteria.js）。
// 手动改过分镜表（服务端 manual.edited）才询问；没改过（含内容和 AI 选段一样）直接按新 AI 选段覆盖。
// 询问之前先把还没落盘的分镜表存好、再重新读一次状态——不拿过期的「改了几处」去问用户。

/* 界面文案：产品可直接改这里 */
const COPY_RESELECT_TITLE = '你手动改过分镜表（{n} 处）';
const COPY_RESELECT_BODY = '按新的设置重新选段会覆盖这些修改。';
const COPY_RESELECT_REPLACE = '覆盖，用新的 AI 选段';
const COPY_RESELECT_KEEP = '保留我的修改';
const COPY_RESELECT_KEEP_NOTE = '只更新未采用清单和建议';
const COPY_RESELECT_CANCEL = '取消';
const COPY_CHANGES_MORE = '等另外 {n} 处';
const COPY_RESELECT_SAVE_FIRST = '分镜表还没保存成功，先不重新选段';
const COPY_RESELECT_NOT_STARTED = '没能开始重新选段';
const COPY_RESELECT_REREAD = '没能确认分镜表的状态，请再试一次';
const COPY_RESTORE_AI = '恢复为 AI 选段';
const COPY_RESTORE_AI_ASK = '恢复为 AI 选段？当前手动修改（{n} 处）会被替换，已自动备份';
const COPY_RESTORE_AI_GO = '确定';
const COPY_RESTORED_AI = '已恢复为 AI 选段';
const COPY_GATE_CANCELLED = '已取消：答案已保存为草稿';

const reselectUi = {busy: false, resolve: null, restoring: false};
function manualInfo(){ return res()?.data?.manual || state.data?.manual || null; }

function manualBodyHtml(m){
  const items = (m.changes || []).map(c => `<li>${esc(c)}</li>`).join('');
  const more = num(m.more) > 0 ? `<p class="hint">${esc(COPY_CHANGES_MORE.replace('{n}', num(m.more)))}</p>` : '';
  return `<p>${esc(COPY_RESELECT_BODY)}</p><ul class="changes">${items}</ul>${more}
    <div class="job-actions">
      <button class="primary" data-act="reselectReplace">${esc(COPY_RESELECT_REPLACE)}</button>
      <button class="ghost" data-act="reselectKeep">${esc(COPY_RESELECT_KEEP)}</button>
      <button class="ghost" data-act="reselectCancel">${esc(COPY_RESELECT_CANCEL)}</button>
    </div><p class="hint">${esc(COPY_RESELECT_KEEP)}：${esc(COPY_RESELECT_KEEP_NOTE)}</p>`;
}
function askManual(m){
  return new Promise(resolve => {
    reselectUi.resolve = resolve;
    showModal(COPY_RESELECT_TITLE.replace('{n}', num(m.count)), manualBodyHtml(m));
    state.modalKind = 'reselect';
  });
}
function settleReselect(choice){
  const resolve = reselectUi.resolve;
  reselectUi.resolve = null;
  if(resolve) resolve(choice);
}
function reselectDismissed(){ settleReselect(null); }   // Esc / 点遮罩 / closeModal（base.js）：等于取消
function chooseReselect(choice){ settleReselect(choice); closeModal(); }

// 询问只信刚重新读到的 /api/state.manual（state.data）；⑤ 的 /api/result 有 400ms 防抖，可能还是改之前的
// 返回 {choice: 'replace' | 'keep' | null, reason}：null = 取消，或没能做到（reason 是原因，取消时为 null）
async function confirmReselectDetailed(extra, opts = {}){
  const stop = reason => { if(reason) toast(reason, TOAST_ERROR_MS); return {choice: null, reason}; };
  if(reselectUi.busy || !state.project) return {choice: null, reason: null};
  reselectUi.busy = true;
  try{
    if(await flushPendingSave() === false) return stop(COPY_RESELECT_SAVE_FIRST);
    if(!await refreshOrWarn()) return stop(state.project ? COPY_RESELECT_REREAD : null);
    const m = state.data?.manual;
    const choice = m && m.edited === true ? await askManual(m) : 'replace';
    if(choice === null) return {choice: null, reason: null};
    const submit = opts.submit || (c => startJob('select', {...(extra || {}), manual: c}));
    if(await submit(choice) === false) return {choice: null, reason: COPY_RESELECT_NOT_STARTED};  // 起任务失败时 startJob 已经说明原因
    return {choice, reason: null};
  }finally{ reselectUi.busy = false; }
}
// opts.submit：提交动作，默认起选段任务；④ 传自己的。返回 'replace' | 'keep'（已提交）或 null（取消 / 没做成）
async function confirmReselect(extra, opts = {}){ return (await confirmReselectDetailed(extra, opts)).choice; }

/* ---------------- 恢复为 AI 选段 ---------------- */
function openRestoreAi(){
  const m = manualInfo();
  if(!m || m.edited !== true) return;
  showModal(COPY_RESTORE_AI_ASK.replace('{n}', num(m.count)), `<div class="job-actions">
    <button class="primary" data-act="restoreAiGo">${esc(COPY_RESTORE_AI_GO)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_RESELECT_CANCEL)}</button></div>`);
}
async function restoreAi(){
  closeModal();
  const name = state.project;
  if(!name || reselectUi.restoring || reselectUi.busy) return;   // 同一时刻只做一次
  reselectUi.restoring = true; syncResultLock();                  // 从 flush 到服务端回包：分镜表只读
  try{
    if(await flushPendingSave() === false){ toast(COPY_RESELECT_SAVE_FIRST, TOAST_ERROR_MS); return; }  // 排队中的保存会把恢复的表又写回去
    const r = await postJson('/api/result/restore-ai', {project: name});
    applyWizard(r.wizard);
    await refreshOrWarn(name);
    if(state.view === 'result'){ const x = res(); if(x) x.tableSig = null; await loadResult(); paintTable(true); }
    toast(COPY_RESTORED_AI);
  }catch(e){ toast(e.message, TOAST_ERROR_MS); }
  finally{ reselectUi.restoring = false; syncResultLock(); }
}

Object.assign(ACTIONS, {
  reselectReplace: ()=>chooseReselect('replace'), reselectKeep: ()=>chooseReselect('keep'),
  reselectCancel: ()=>chooseReselect(null),
  openRestoreAi: ()=>openRestoreAi(), restoreAiGo: ()=>restoreAi(),
});
