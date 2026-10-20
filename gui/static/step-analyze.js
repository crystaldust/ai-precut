// 剪辑台主页 · ② 分析（M13）：11 项人话进度 + 每项耗时，失败说清哪一步和原因，可离开页面。
// 缺告知 / 缺 Key 在本页内联处理；编码器等其它前置条件弹说明（jobs.js 的 showNeedModal，KI-97）。
// 分析不自动重跑（P5）：中断后回来显示「继续分析」，已完成的步骤会跳过。
// 本页只轮询 /api/analysis；顶栏胶囊用 /api/job（jobs.js），两者各一套计时器、互不干扰。

/* 界面文案：产品可直接改这里 */
const COPY_ANALYZE_NOTICE = '分析大约 10–15 分钟，可以关掉窗口，回来接着跑';
const COPY_ANALYZE_LOADING = '正在读取分析进度…';
const COPY_ANALYZE_NOT_STARTED = '还没开始分析：会把素材转写成文字、理解内容并初步选段。';
const COPY_ANALYZE_START = '开始分析';
const COPY_ANALYZE_RUNNING = '正在分析 {done}/{total}';
const COPY_ANALYZE_RUNNING_ELAPSED = '正在分析 {done}/{total} · 已用时 {t}';
const COPY_ANALYZE_STALE_NOTE = '进度暂时读不到（{reason}），下面显示的是上一次的结果';
const COPY_ANALYZE_INTERRUPTED = '上次分析没跑完（已完成 {done}/{total}）';
const COPY_ANALYZE_CONTINUE = '继续分析';
const COPY_ANALYZE_FAILED = '「{label}」失败：{reason}';
const COPY_ANALYZE_NO_REASON = '没有记录到具体原因，请导出诊断包发给开发';
const COPY_ANALYZE_RETRY = '重试（从这一步接着跑）';
const COPY_ANALYZE_GO_KEYS = '去填 Key';
const COPY_ANALYZE_COMPLETE = '分析完成';
const COPY_ANALYZE_NEXT = '去看素材 →';
const COPY_BLOCK_KEYS_TITLE = '还差 API Key';
const COPY_BLOCK_RESUME = '填好了，继续分析';
const STEP_MARKS = {done: '✓', running: '●', failed: '✕', waiting: '○'};
const STEP_STATUS_TEXT = {done: '已完成', running: '进行中', failed: '失败', waiting: '等待'};
const ANALYSIS_POLL_MS = 1500;

// project：data 属于哪个项目；req：请求序号（切项目 / 新请求让旧响应作废）；seq：轮询会话；html 缓存见 app.js 的 renderView
const analysisUi = {data: null, project: null, error: null, req: 0, seq: 0, timer: null};

/* ---------------- 轮询 ---------------- */
function isAnalyzing(){
  const p = analysisUi.project === state.project ? analysisUi.data : null;
  const v = jobUi.view, busy = state.data?.busy;
  return !!(p && p.running) || (!!v && v.status === 'running' && v.task === 'prepare')
    || (!!busy && busy.task === 'prepare' && busy.project === state.project);
}
function resetAnalysis(){
  stopAnalysisPoll();
  analysisUi.data = null; analysisUi.project = null; analysisUi.error = null; analysisUi.req++;
  clearAnalysisBlock();
}
function stopAnalysisPoll(){ analysisUi.seq++; clearTimeout(analysisUi.timer); analysisUi.timer = null; }
async function loadAnalysis(){
  const project = state.project;
  if(!project) return null;
  const req = ++analysisUi.req;
  let data;
  try{ data = await api('/api/analysis?project=' + encodeURIComponent(project)); }
  catch(e){
    if(req === analysisUi.req && project === state.project){ analysisUi.error = e.message; if(state.view === 'analyze') renderView(); }
    return null;
  }
  if(req !== analysisUi.req || project !== state.project) return null;  // 切了项目 / 有更新的请求
  analysisUi.data = data; analysisUi.project = project; analysisUi.error = null;
  if(state.view === 'analyze') renderView();
  renderChip();
  return data;
}
function startAnalysisPoll(){
  stopAnalysisPoll();
  const mine = analysisUi.seq;
  const tick = async ()=>{
    if(analysisUi.seq !== mine || state.view !== 'analyze') return;
    await loadAnalysis();
    if(analysisUi.seq === mine && state.view === 'analyze' && isAnalyzing())
      analysisUi.timer = setTimeout(tick, ANALYSIS_POLL_MS);
  };
  return tick();
}
function enterAnalyze(){ return startAnalysisPoll(); }

/* ---------------- 起任务与前置条件 ---------------- */
function clearAnalysisBlock(){ state.block = null; if(!firstRunUi.resolve) settingsUi.inline = null; }
async function startAnalysis(){
  clearAnalysisBlock();
  await go('analyze');
  await startJob('prepare', undefined, {onBlocked: showAnalysisBlock});
  startAnalysisPoll();
}
async function showAnalysisBlock(e){  // 缺告知 / 缺 Key：就在本页处理，不弹到别处
  const need = e.data.need, project = state.project;
  const block = {need, message: e.message, missing: e.data.missing || [], cfg: null};
  if(need === 'keys'){
    try{ block.cfg = await api('/api/config'); }catch(err){ toast(err.message, TOAST_ERROR_MS); }
    if(project !== state.project) return;  // 等配置的时候切走了项目：别把别人的提示画过来
    settingsUi.inline = cfg=>{ state.block = {...state.block, cfg}; renderView(); };  // 保存 / 清除 Key 后就地重画
  }
  state.block = block;
  renderView();
}
async function analysisConsent(){
  try{ await postJson('/api/config/consent', {}); }catch(e){ toast(e.message, TOAST_ERROR_MS); return; }
  return startAnalysis();
}

/* ---------------- 页面 ---------------- */
function blockHtml(block){
  if(block.need === 'consent')
    return `<div class="card warn"><h3>${esc(COPY_CONSENT_TITLE)}</h3>${consentHtml('analysisConsent')}</div>`;
  const ready = block.cfg && requiredReady(block.cfg, block.missing.length ? block.missing : null);
  return `<div class="card warn"><h3>${esc(COPY_BLOCK_KEYS_TITLE)}</h3><p>${esc(block.message)}</p>
    ${block.cfg ? settingsRowsHtml(block.cfg) : ''}
    <button class="primary" data-act="startAnalysis" data-starts-job${ready ? '' : ' disabled'}>${esc(COPY_BLOCK_RESUME)}</button></div>`;
}
function stepsListHtml(steps){
  return `<ul class="asteps">${steps.map(s=>{
    const status = STEP_MARKS[s.status] ? s.status : 'waiting';
    const time = s.seconds === null || s.seconds === undefined ? '' : fmtMinSec(s.seconds);
    return `<li class="${status}"><span class="ic">${STEP_MARKS[status]}</span><span class="lb">${esc(s.label)}</span>`
      + `<span class="tm">${esc(time || STEP_STATUS_TEXT[status])}</span></li>`;
  }).join('')}</ul>`;
}
function statusCardHtml(p){
  const fill = t => t.replace('{done}', num(p.done)).replace('{total}', num(p.total));
  const button = (cls, act, text, jobBtn) =>
    `<button class="${cls}" data-act="${esc(act)}"${jobBtn ? ' data-starts-job' : ''}>${esc(text)}</button>`;
  if(isAnalyzing()){
    const v = jobUi.view, timed = v && v.elapsed_s !== undefined;
    const headline = fill(timed ? COPY_ANALYZE_RUNNING_ELAPSED : COPY_ANALYZE_RUNNING)
      .replace('{t}', timed ? fmtElapsed(v.elapsed_s) : '');
    return `<div class="card"><h3>${esc(headline)}</h3><p class="hint">${esc(p.notice || COPY_ANALYZE_NOTICE)}</p></div>`;
  }
  if(p.complete)
    return `<div class="card"><h3>${esc(COPY_ANALYZE_COMPLETE)}</h3>
      <button class="primary" data-act="go" data-step="browse">${esc(COPY_ANALYZE_NEXT)}</button></div>`;
  if(p.failed){
    const reason = p.failed.reason || COPY_ANALYZE_NO_REASON;
    return `<div class="card error"><h3>${esc(COPY_ANALYZE_FAILED.replace('{label}', p.failed.label).replace('{reason}', reason))}</h3>
      <div class="job-actions">${button('primary', 'startAnalysis', COPY_ANALYZE_RETRY, true)}
      ${button('ghost', 'openSettings', COPY_ANALYZE_GO_KEYS)}${button('ghost', 'exportDiag', COPY_JOB_DIAG)}</div></div>`;
  }
  const began = num(p.done) > 0;  // P5：中断后不自动重跑，由剪辑师点「继续分析」
  return `<div class="card"><h3>${esc(began ? fill(COPY_ANALYZE_INTERRUPTED) : COPY_ANALYZE_NOT_STARTED)}</h3>
    <p class="hint">${esc(p.notice || COPY_ANALYZE_NOTICE)}</p>
    ${button('primary', 'startAnalysis', began ? COPY_ANALYZE_CONTINUE : COPY_ANALYZE_START, true)}</div>`;
}
function viewAnalyze(progress=(analysisUi.project === state.project ? analysisUi.data : null)){
  if(state.block) return blockHtml(state.block) + (progress ? stepsListHtml(progress.steps || []) : '');
  if(!progress)
    return `<div class="empty">${esc(analysisUi.error || COPY_ANALYZE_LOADING)}</div>`;
  const stale = analysisUi.error
    ? `<p class="hint warn">${esc(COPY_ANALYZE_STALE_NOTE.replace('{reason}', analysisUi.error))}</p>` : '';
  return stale + statusCardHtml(progress) + stepsListHtml(progress.steps || []);
}

Object.assign(ACTIONS, {
  startAnalysis: ()=>startAnalysis(), analysisConsent: ()=>analysisConsent(),
});
