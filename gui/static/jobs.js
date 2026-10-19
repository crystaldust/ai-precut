// 剪辑台 · 任务弹窗（GL-17 / GL-22）与 Windows 导出入口（GL-14）。
// 运行中可「取消任务」；失败 / 已取消后可「重试 / 关闭」；已有任务在跑时可「查看进行中的任务」。
// 依赖 index.html 内联脚本里的 $ / state / api / showModal / closeModal / logLine / toast / refresh，
// 只在调用时才用到，所以本文件可以先于内联脚本加载。

/* 界面文案：产品可直接改这里 */
const JOB_TITLES = {prepare:'正在处理素材', build:'正在生成成片', select:'正在重新选段',
                    export:'正在导出 Windows 剪映包'};
const JOB_DONE = {prepare:'处理完成', build:'新版本已生成', select:'已按新时长重新选段',
                  export:'Windows 剪映包已导出'};
const COPY_JOB_TITLE_FALLBACK = '进行中的任务';
const COPY_JOB_PREPARING = '准备中…';
const COPY_JOB_CANCEL = '取消任务';
const COPY_JOB_RETRY = '重试';
const COPY_JOB_CLOSE = '关闭';
const COPY_JOB_VIEW_RUNNING = '查看进行中的任务';
const COPY_JOB_ACK = '知道了';
const COPY_JOB_FINISHED = '[完成]';
const COPY_JOB_CANCELLED = '[已取消] 已经生成的内容会保留，下次接着处理';
const COPY_JOB_FAILED = '[失败] 看上面的报错；也可以把这段日志发给开发者';
const COPY_JOB_LOST = '[连接中断] 剪辑台没有响应：';
const COPY_JOB_CANCEL_SENT = '[取消] 已请求停止…';
const COPY_JOB_ERROR = '[错误] ';
const COPY_JOB_DONE_WITH_WARNINGS = '完成了，但有需要你留意的提示（上面以 [!] 开头的行），看完再关';
const COPY_EXPORT_WINDOWS = '导出 Windows 剪映包';
const COPY_EXPORTED = '已导出 {name}（{mb} MB）';
const COPY_REVEAL = '在访达中显示';
const COPY_MAC_DRAFT = 'Mac 剪映草稿名：';
const JOB_POLL_MS = 900;
const JOB_POLL_FIRST_MS = 500;
const JOB_POLL_RETRY_MS = 1500;
const JOB_POLL_MAX_MISSES = 5;   // 连续这么多次连不上就判定中断，给出按钮，不再死等
const JOB_DONE_CLOSE_MS = 700;

const jobUi = {last: null, id: null, polling: null};

// canRetry=false：弹窗里是「查看」来的任务（可能是别的项目 / 别的参数），不能让「重试」去重跑它
function jobActionsHtml(kind, canRetry = true){
  const btn = (cls, fn, text) => `<button class="${cls}" onclick="${fn}">${esc(text)}</button>`;
  if(kind === 'running') return btn('danger', 'cancelJob()', COPY_JOB_CANCEL);
  if(kind === 'conflict') return btn('primary', 'attachJob()', COPY_JOB_VIEW_RUNNING)
                                + btn('ghost', 'closeModal()', COPY_JOB_CLOSE);
  if(kind === 'ack') return btn('primary', 'closeModal()', COPY_JOB_ACK);
  return (canRetry ? btn('primary', 'retryJob()', COPY_JOB_RETRY) : '') + btn('ghost', 'closeModal()', COPY_JOB_CLOSE);
}
function setJobActions(kind){ const a = $('#jobActions'); if(a) a.innerHTML = jobActionsHtml(kind, !!jobUi.last); }
// 任务还在跑、正在看进度时，Esc / 点遮罩不关弹窗（取消要明确点「取消任务」）
function modalDismissable(){ return jobUi.polling === null; }
function jobModal(task){
  showModal(JOB_TITLES[task] || COPY_JOB_TITLE_FALLBACK,
    `<div class="log" id="log">${esc(COPY_JOB_PREPARING)}</div><div class="job-actions" id="jobActions"></div>`);
}

function startJob(task, extra){
  if(!state.project){ toast('先选项目'); return; }
  if(task==='build' && !state.shots.length){ toast('分镜表是空的，先生成镜头'); return; }
  jobUi.last = {task, extra};
  jobUi.id = null;
  jobModal(task); setJobActions('running');
  return api('/api/job', {method:'POST', headers:{'Content-Type':'application/json'},
                          body: JSON.stringify({project: state.project, task, ...(extra||{})})})
    .then(({job_id})=>{
      jobUi.id = job_id;
      try{ pollJob(job_id, task); }  // 轮询出错不是「启动失败」
      catch(e){ jobUi.polling = null; logLine(COPY_JOB_LOST + e.message); setJobActions('ended'); }
    }, e=>onJobStartError(e, task, extra));
}
function onJobStartError(e, task, extra){
  const d = e.data || {};
  const again = ()=>startJob(task, extra);
  if(e.status===409 && d.need==='consent'){ closeModal(); return openConsent(again); }
  if(e.status===409 && d.need==='keys'){ closeModal(); toast(e.message, 3500); return openSettings(again, d.missing); }
  logLine(COPY_JOB_ERROR + e.message);
  if(e.status===409 && d.job_id){ jobUi.id = d.job_id; setJobActions('conflict'); }
  else setJobActions('ended');
}
function attachJob(){
  if(!jobUi.id) return;
  jobUi.last = null;
  jobModal(null); setJobActions('running'); pollJob(jobUi.id, null);
}
function attachRunningJob(job){
  // 切回正在跑任务的项目时重新显示进度（已有弹窗时不打扰）
  if(!job || !job.id || $('#mask').classList.contains('on')) return;
  jobUi.last = null;  // 不知道它当初的参数，结束后只给「关闭」
  jobUi.id = job.id;
  jobModal(job.task); setJobActions('running'); pollJob(job.id, job.task);
}
function retryJob(){ if(jobUi.last) startJob(jobUi.last.task, jobUi.last.extra); }
async function cancelJob(){
  if(!jobUi.id) return;
  try{
    await api('/api/job/'+encodeURIComponent(jobUi.id)+'/cancel',
              {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    logLine(COPY_JOB_CANCEL_SENT);
  }catch(e){ logLine(COPY_JOB_ERROR + e.message); }
}

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
      logLine(COPY_JOB_LOST + e.message); setJobActions('ended'); return;
    }
    if(jobUi.polling !== id) return;
    task = j.task || task;
    if(JOB_TITLES[task]) $('#modalTitle').textContent = JOB_TITLES[task];
    const el = $('#log');
    if(el){ el.textContent = (j.log||[]).join('\n') || '…'; el.scrollTop = el.scrollHeight; }
    if(j.status==='running'){ setTimeout(tick, JOB_POLL_MS); return; }
    jobUi.polling = null;
    if(j.status==='done') return onJobDone(j, task);
    logLine('\n' + (j.status==='cancelled' ? COPY_JOB_CANCELLED : COPY_JOB_FAILED));
    setJobActions('ended');
    refresh().catch(()=>{});
  };
  setTimeout(tick, JOB_POLL_FIRST_MS);
}
function onJobDone(j, task){
  logLine('\n' + COPY_JOB_FINISHED);
  setJobActions('ack');
  const warned = (j.log||[]).some(l=>String(l).startsWith('[!]'));
  setTimeout(async ()=>{
    try{ await refresh(); }catch(e){ /* 列表刷新失败不影响任务结果 */ }
    // 必留合计超过目标：处理素材 / 重新选段后自动问一次想剪成多长
    if((task==='prepare' || task==='select') && state.data?.selection?.over_target){ openTarget(true); return; }
    // 有警告：日志留着让人看完，不自动关
    if(warned){ logLine(COPY_JOB_DONE_WITH_WARNINGS); return; }
    closeModal();
    toast(JOB_DONE[task] || COPY_JOB_FINISHED);
  }, JOB_DONE_CLOSE_MS);
}

/* ---------------- 版本卡片：Windows 导出（GL-14） ---------------- */
function versionExportHtml(v, i){
  const done = v.windows_zip
    ? `<span class="hint">${esc(COPY_EXPORTED.replace('{name}', v.windows_zip).replace('{mb}', num(v.windows_mb)))}</span>
       <button class="ghost" onclick="revealExport(${num(i)})">${esc(COPY_REVEAL)}</button>` : '';
  return `<div class="m ver-export">
      <button class="ghost" onclick="exportVersion(${num(i)})">${esc(COPY_EXPORT_WINDOWS)}</button>${done}
    </div>`;
}
function exportVersion(i){
  const v = (state.data?.versions || [])[i];
  if(v) startJob('export', {version: v.name});
}
async function revealExport(i){
  const v = (state.data?.versions || [])[i];
  if(!v) return;
  try{
    await api('/api/open', {method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify({project: state.project, target:'export', version: v.name})});
  }catch(e){ toast(e.message); }
}
