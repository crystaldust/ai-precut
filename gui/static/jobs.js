// 剪辑台 · 任务（GL-17 / GL-22）：启动、轮询、取消 / 重试，任务胶囊，启动类按钮置灰（M13 D16）。
// 分析 / 重新选段只在顶栏胶囊里露面（② 页自己就是进度）；生成新版本 / 导出 Windows 包仍自动弹出日志窗口。
// 依赖 base.js 的 $ / state / api / showModal / closeModal / logLine / toast 和 app.js 的 refreshOrWarn / go，
// 只在调用时才用到，所以本文件可以先于它们加载。

/* 界面文案：产品可直接改这里 */
const JOB_TITLES = {prepare:'正在分析', build:'正在生成新版本', select:'正在重新选段',
                    export:'正在生成 Windows 剪映包', questions:'正在重新出题'};
const JOB_LABELS = {prepare:'分析', build:'生成新版本', select:'重新选段',
                    export:'生成 Windows 剪映包', questions:'重新出题'};
const JOB_DONE = {prepare:'分析完成', build:'新版本已生成', select:'已重新选段',
                  export:'Windows 剪映包已生成', questions:'决策问题已重新生成'};
const MODAL_TASKS = new Set(['build', 'export']);  // 这两个任务自动弹日志窗口，其余只在胶囊里
const AFTER_DONE_GO = {prepare: ['analyze', 'browse'], select: ['criteria', 'result']};  // [正在看的步骤, 完成后去]
const COPY_JOB_TITLE_FALLBACK = '进行中的任务';
const COPY_JOB_PREPARING = '准备中…';
const COPY_JOB_CANCEL = '取消任务';
const COPY_JOB_RETRY = '重试';
const COPY_JOB_CLOSE = '关闭';
const COPY_JOB_VIEW_RUNNING = '查看进行中的任务';
const COPY_JOB_ACK = '知道了';
const COPY_JOB_DIAG = '导出诊断包';  // 失败 / 中断后给开发者交现场（GL-19，见 support.js）
const COPY_JOB_FINISHED = '[完成]';
const COPY_JOB_CANCELLED = '[已取消] 已经生成的内容会保留，下次接着处理';
const COPY_JOB_FAILED = '[失败] 看上面的报错；也可以把这段日志发给开发者';
const COPY_JOB_LOST = '[连接中断] 剪辑台没有响应：';
const COPY_JOB_CANCEL_SENT = '[取消] 已请求停止…';
const COPY_JOB_ERROR = '[错误] ';
const COPY_JOB_DONE_WITH_WARNINGS = '完成了，但有需要你留意的提示（上面以 [!] 开头的行），看完再关';
const COPY_JOB_DONE_OTHER = '「{project}」：{done}';
const COPY_JOB_SAVE_FIRST = '分镜表还没保存成功，先不生成新版本';  // KI-35：生成前先把改动存盘
const COPY_CHIP_PROGRESS = '{title} {done}/{total}';
const COPY_CHIP_WORKING = '{title}…';
const COPY_CHIP_ELAPSED = ' · {t}';
const COPY_CHIP_LESS_THAN_MIN = '不到 1 分钟';
const COPY_CHIP_MINUTES = '{n} 分钟';
const COPY_CHIP_FAILED = '失败 · 查看';
const COPY_CHIP_CANCELLED = '已取消 · 查看';
const COPY_CHIP_WARNED = '完成，有提示 · 查看';
const COPY_BUSY = '正在{label}，完成后再试';
const COPY_NEED_TITLE = '这台 Mac 暂时不能分析';  // KI-97：任务前置检查不通过且不是告知 / Key（如编码器不可用）
const JOB_POLL_MS = 900;
const JOB_POLL_FIRST_MS = 500;
const JOB_POLL_RETRY_MS = 1500;
const JOB_POLL_MAX_MISSES = 5;   // 连续这么多次连不上就判定中断，给出按钮，不再死等
const JOB_DONE_CLOSE_MS = 700;
const SECONDS_PER_MIN = 60;
const NEED_TOAST_MS = 3500;

// view：最近一次轮询到的任务快照（胶囊用）；与 state.modalKind === 'job' 一起决定要不要往日志窗口写
const jobUi = {last: null, id: null, polling: null, view: null};

// canRetry=false：弹窗里是「查看」来的任务（可能是别的项目 / 别的参数），不能让「重试」去重跑它
function jobActionsHtml(kind, canRetry = true){
  const btn = (cls, act, text) => `<button class="${esc(cls)}" data-act="${esc(act)}">${esc(text)}</button>`;
  if(kind === 'running') return btn('danger', 'cancelJob', COPY_JOB_CANCEL);
  if(kind === 'conflict') return btn('primary', 'attachJob', COPY_JOB_VIEW_RUNNING)
                                + btn('ghost', 'closeModal', COPY_JOB_CLOSE);
  if(kind === 'ack') return btn('primary', 'closeModal', COPY_JOB_ACK);
  return (canRetry ? btn('primary', 'retryJob', COPY_JOB_RETRY) : '')
    + btn('ghost', 'exportDiag', COPY_JOB_DIAG) + btn('ghost', 'closeModal', COPY_JOB_CLOSE);
}
function setJobActions(kind){ const a = $('#jobActions'); if(a) a.innerHTML = jobActionsHtml(kind, !!jobUi.last); }
function jobModalOpen(){ return state.modalKind === 'job'; }
// 任务还在跑、正在看进度时，Esc / 点遮罩不关弹窗（取消要明确点「取消任务」）；别的弹窗不受后台任务影响
function modalDismissable(){ return jobUi.polling === null || !jobModalOpen(); }
function jobModal(task){
  showModal(JOB_TITLES[task] || COPY_JOB_TITLE_FALLBACK,
    `<div class="log" id="log">${esc(COPY_JOB_PREPARING)}</div><div class="job-actions" id="jobActions"></div>`);
  state.modalKind = 'job';
}

/* ---------------- 启动 ---------------- */
// opts.modal：是否弹日志窗口（默认只有 build / export）；opts.onBlocked(e, again)：缺告知 / 缺 Key 时由调用方在页内处理
async function startJob(task, extra, opts = {}){
  if(!state.project){ toast('先选项目'); return; }
  if(task==='build' && !state.shots.length){ toast('分镜表是空的，先生成镜头'); return; }
  // KI-35：防抖中 / 排队中的分镜表保存先落盘，否则新版本用的是改之前的字幕
  if(task==='build' && await flushPendingSave() === false){ toast(COPY_JOB_SAVE_FIRST); return; }
  jobUi.last = {task, extra, opts};
  jobUi.id = null;
  jobUi.view = null;
  const modal = opts.modal ?? MODAL_TASKS.has(task);
  if(modal){ jobModal(task); setJobActions('running'); }
  renderChip();
  return api('/api/job', {method:'POST', headers:{'Content-Type':'application/json'},
                          body: JSON.stringify({project: state.project, task, ...(extra||{})})})
    .then(({job_id})=>{
      jobUi.id = job_id;
      jobUi.view = {id: job_id, task, status: 'running'};  // 胶囊立刻出现，不等第一次轮询
      renderChip(); applyBusyGuard();
      try{ pollJob(job_id, task); }  // 轮询出错不是「启动失败」
      catch(e){ jobUi.polling = null; logLine(COPY_JOB_LOST + e.message); setJobActions('ended'); }
    }, e=>onJobStartError(e, task, extra, opts, modal));
}
function showNeedModal(message){  // KI-97：encoder 及不认识的前置条件 → 说清原因 + 导出诊断包
  showModal(COPY_NEED_TITLE, `<p>${esc(message)}</p><div class="job-actions">
    <button class="primary" data-act="exportDiag">${esc(COPY_JOB_DIAG)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_JOB_ACK)}</button></div>`);
}
function onJobStartError(e, task, extra, opts = {}, modal = MODAL_TASKS.has(task)){
  const d = e.data || {};
  const again = ()=>startJob(task, extra, opts);
  const blocked = e.status === 409 && d.need;
  if(blocked && jobModalOpen()) closeModal();
  jobUi.last = blocked ? null : jobUi.last;
  renderChip();
  if(blocked && (d.need === 'consent' || d.need === 'keys') && opts.onBlocked) return opts.onBlocked(e, again);
  if(blocked && d.need === 'consent') return openConsent(again);
  if(blocked && d.need === 'keys'){ toast(e.message, NEED_TOAST_MS); return openSettings(again, d.missing); }
  if(blocked) return showNeedModal(e.message);
  if(!modal){  // 没有日志窗口：原因用提示说；别的任务占着时改为盯着它
    toast(e.message, TOAST_ERROR_MS);
    if(e.status===409 && d.job_id) attachRunningJob({id: d.job_id, task: d.task});
    return;
  }
  logLine(COPY_JOB_ERROR + e.message);
  if(e.status===409 && d.job_id){ jobUi.id = d.job_id; setJobActions('conflict'); }
  else setJobActions('ended');
}
function attachJob(){
  if(!jobUi.id) return;
  jobUi.last = null;
  jobModal(null); setJobActions('running'); pollJob(jobUi.id, null);
}
function trackJob(id, task){   // 别处（④ 闸门）已经起好的任务：胶囊立刻出现，接着轮询
  jobUi.last = null;
  jobUi.id = id;
  jobUi.view = {id, task, status: 'running'};
  renderChip(); applyBusyGuard();
  pollJob(id, task);
}
function attachRunningJob(job){
  // 切回正在跑任务的项目 / 刚打开剪辑台时接着盯它（只在胶囊里露面，不弹窗）
  if(!job || !job.id || jobUi.polling === job.id) return;
  jobUi.last = null;  // 不知道它当初的参数，结束后只给「关闭」
  jobUi.id = job.id;
  pollJob(job.id, job.task);
  if(job.task === 'prepare' && state.view === 'analyze' && typeof startAnalysisPoll === 'function') startAnalysisPoll();
}
function retryJob(){ if(jobUi.last) startJob(jobUi.last.task, jobUi.last.extra, jobUi.last.opts); }
async function cancelJob(){
  if(!jobUi.id) return;
  try{
    await api('/api/job/'+encodeURIComponent(jobUi.id)+'/cancel',
              {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    logLine(COPY_JOB_CANCEL_SENT);
  }catch(e){ logLine(COPY_JOB_ERROR + e.message); }
}

/* ---------------- 轮询与收尾 ---------------- */
function pollJob(id, task){
  let misses = 0;
  jobUi.polling = id;
  const tick = async ()=>{
    if(jobUi.polling !== id) return;  // 已经换成别的任务 / 别的弹窗，旧轮询作废
    let j;
    try{ j = await api('/api/job/'+encodeURIComponent(id)); misses = 0; }
    catch(e){
      if(e.status !== 404 && ++misses < JOB_POLL_MAX_MISSES){ setTimeout(tick, JOB_POLL_RETRY_MS); return; }
      jobUi.polling = null;
      jobUi.view = {id, task, status: 'failed', log: []}; renderChip();
      logLine(COPY_JOB_LOST + e.message); setJobActions('ended'); return;
    }
    if(jobUi.polling !== id) return;
    task = j.task || task;
    jobUi.view = {id, task, status: j.status, elapsed_s: j.elapsed_s, project: j.project, log: j.log || []};
    renderChip(); applyBusyGuard();
    if(jobModalOpen() && JOB_TITLES[task]) $('#modalTitle').textContent = JOB_TITLES[task];
    const el = $('#log');
    if(el){ el.textContent = (j.log||[]).join('\n') || '…'; el.scrollTop = el.scrollHeight; }
    if(j.status==='running'){ setTimeout(tick, JOB_POLL_MS); return; }
    jobUi.polling = null;
    if(j.status==='done') return onJobDone(j, task);
    logLine('\n' + (j.status==='cancelled' ? COPY_JOB_CANCELLED : COPY_JOB_FAILED));
    setJobActions('ended');
    if(isOtherProject(j)) return;
    refreshOrWarn();
    afterJobEnd(task);
  };
  setTimeout(tick, JOB_POLL_FIRST_MS);
}
function afterJobDone(task){  // 正在看 ② 时分析完成 → 去 ③；正在看 ④ 时重新选段完成 → 去 ⑤；重新出题完成 → 重读 ④ 的题目
  if(task === 'questions' && state.view === 'criteria') return enterCriteria();
  const rule = AFTER_DONE_GO[task];
  if(rule && state.view === rule[0]) return go(rule[1]);
}
// 任务属于别的项目：只刷新项目栏的「当前步骤」并说一声，不动正在看的页面（不跳步骤、不弹改时长）
function isOtherProject(j){ return !!j.project && j.project !== state.project; }
async function onOtherProjectDone(j, task){
  try{ await loadProjects(); }catch(e){ toast(e.message, TOAST_ERROR_MS); return; }
  toast(COPY_JOB_DONE_OTHER.replace('{project}', j.project).replace('{done}', JOB_DONE[task] || COPY_JOB_FINISHED));
}
function onJobDone(j, task){
  const modal = jobModalOpen();
  if(modal){ logLine('\n' + COPY_JOB_FINISHED); setJobActions('ack'); }
  const warned = (j.log||[]).some(l=>String(l).startsWith('[!]'));
  setTimeout(async ()=>{
    if(isOtherProject(j)){ await onOtherProjectDone(j, task); if(jobModalOpen()) closeModal(); return; }
    await refreshOrWarn();  // 刷新失败不影响任务结果，但要在警告栏说出原因
    await afterJobDone(task);
    afterJobEnd(task);
    // 必留合计超过目标：分析 / 重新选段后自动问一次想剪成多长
    if((task==='prepare' || task==='select') && state.data?.selection?.over_target){ openTarget(true); return; }
    // 有警告：日志留着让人看完，不自动关
    if(warned){
      if(jobModalOpen()) logLine(COPY_JOB_DONE_WITH_WARNINGS);
      else { jobUi.view = {...jobUi.view, warned: true}; renderChip(); }
      return;
    }
    if(jobModalOpen()) closeModal();
    toast(JOB_DONE[task] || COPY_JOB_FINISHED);
  }, modal ? JOB_DONE_CLOSE_MS : 0);
}
function afterJobEnd(task){  // ② 页要拿最后一次进度（失败原因 / 完成）
  if(task === 'prepare' && typeof loadAnalysis === 'function') loadAnalysis();
}

/* ---------------- 任务胶囊（D16） ---------------- */
function fmtElapsed(sec){
  const mins = Math.floor(num(sec) / SECONDS_PER_MIN);
  return mins < 1 ? COPY_CHIP_LESS_THAN_MIN : COPY_CHIP_MINUTES.replace('{n}', mins);
}
// 纯函数：任务快照 + 全局忙碌信息 + ② 的进度 → {text, cls} 或 null（隐藏）
function chipModel(view, busy, progress){
  if(view && view.status && view.status !== 'running'){
    if(view.seen) return null;
    if(view.status === 'done') return view.warned ? {text: COPY_CHIP_WARNED, cls: 'warn'} : null;
    return {text: view.status === 'cancelled' ? COPY_CHIP_CANCELLED : COPY_CHIP_FAILED, cls: 'failed'};
  }
  const task = (view && view.status === 'running') ? view.task : (busy && busy.task);
  if(!task) return null;
  const title = JOB_TITLES[task] || COPY_JOB_TITLE_FALLBACK;
  if(task !== 'prepare') return {text: COPY_CHIP_WORKING.replace('{title}', title), cls: ''};
  let text = progress && num(progress.total)
    ? COPY_CHIP_PROGRESS.replace('{title}', title).replace('{done}', num(progress.done)).replace('{total}', num(progress.total))
    : title;
  if(view && view.elapsed_s !== undefined) text += COPY_CHIP_ELAPSED.replace('{t}', fmtElapsed(view.elapsed_s));
  return {text, cls: ''};
}
function renderChip(){
  const progress = typeof analysisUi !== 'undefined' && analysisUi.project === state.project ? analysisUi.data : null;
  const m = chipModel(jobUi.view, state.data?.busy, progress);
  const chip = $('#chip');
  chip.hidden = !m;
  chip.textContent = m ? m.text : '';
  chip.classList.toggle('failed', !!m && m.cls === 'failed');
  chip.classList.toggle('warn', !!m && m.cls === 'warn');
  return m;
}
function openJobDetail(){  // 点胶囊：看日志 / 取消 / 重试 / 导出诊断包
  const v = jobUi.view;
  if(!v){ return; }
  jobModal(v.task);
  const el = $('#log');
  if(el) el.textContent = (v.log || []).join('\n') || COPY_JOB_PREPARING;
  const running = v.status === 'running';
  setJobActions(running ? 'running' : 'ended');
  if(!running) jobUi.view = {...v, seen: true};
  renderChip();
}
// 全局只有一个任务在跑：有任务时所有启动类按钮置灰并说明
function currentBusy(){
  const v = jobUi.view;
  if(v && v.status === 'running') return {label: JOB_LABELS[v.task] || COPY_JOB_TITLE_FALLBACK};
  const busy = state.data?.busy;
  return busy && !(v && v.id === busy.id) ? {label: busy.label || JOB_LABELS[busy.task] || COPY_JOB_TITLE_FALLBACK} : null;
}
function applyBusyGuard(){
  const busy = currentBusy();
  document.querySelectorAll('[data-starts-job]').forEach(b=>{
    b.disabled = !!busy;
    if(busy) b.setAttribute('title', COPY_BUSY.replace('{label}', busy.label));
    else b.removeAttribute('title');
  });
  return busy;
}

Object.assign(ACTIONS, {  // KI-53：任务弹窗与胶囊的按钮
  cancelJob: ()=>cancelJob(), attachJob: ()=>attachJob(), retryJob: ()=>retryJob(),
  openJobDetail: ()=>openJobDetail(),
});
