// 剪辑台主页 · 核心（M13）：项目选择与状态刷新、步骤切换与页面渲染、分镜表保存队列、子窗口、启动。
// 各步骤页面在 step-*.js；外壳（步骤条 / 横幅 / 导航 / 更多菜单）在 wizard.js；项目栏在 sidebar.js。

/* 界面文案：产品可直接改这里 */
const COPY_WARNBAR_TITLE = '需要你留意';
const COPY_STALE_TITLE = '上次留下的任务还在跑';  // KI-71：顶部提示条（D14）
const COPY_SAVE_FAILED = '保存失败：';
const COPY_PROJECT_OPEN_FAILED = '这个项目打不开';
const COPY_WELCOME_TITLE = '欢迎使用剪辑台';
const COPY_WELCOME_FIRST = '素材 → 分析 → 定标准 → 分镜表 → 剪映工程。先新建一个项目吧。';
const COPY_WELCOME_PICK = '选择左边的项目继续，或者新建一个。';
const COPY_WELCOME_NEW = '新建项目';

/* 步骤 key → 页面（返回 HTML）；进入某步时的钩子 */
const STEP_VIEWS = {
  analyze: ()=>viewAnalyze(), browse: ()=>viewBrowse(), criteria: ()=>viewCriteria(),
  result: ()=>viewResult(), export: ()=>viewExport(),
};
const ENTER_HOOKS = {analyze: ()=>enterAnalyze(), browse: ()=>enterBrowse(), criteria: ()=>enterCriteria(), result: ()=>enterResult(), export: ()=>enterExport()};

/* ---------------- 项目 ---------------- */
async function selectProject(name){
  await flushPendingSave();  // 上一个项目还没落盘的分镜表改动先存回它自己
  unsavedFor = null; saveRetries = 0; clearTimeout(saveRetryTimer); saveRetryTimer = null; renderSavebar();  // 存不上的话已经提示过；不带到别的项目
  const draft = crit();
  if(!await flushCriteriaDraft() && draft) criteriaDraftLost(draft);  // ④ 还没发出的答案草稿同理；存不上就长时间提示，不拦切换
  resetResult(); resetExport();
  state.sel = null; state.view = null;  // 进入项目 = 去它的「当前步骤」（refresh 里按 wizard.next 定）
  resetAnalysis(); resetBrowse(); resetCriteria();
  await refreshOrWarn(name);
}

// KI-21：/api/state 失败（项目损坏 / 被删）必须说清原因：警告栏 + toast；所有刷新都走这里
async function refreshOrWarn(name=state.project){
  try { return await refresh(name) !== false; }
  catch(e){ if(e.stale) return false; showProjectError(name, e); return false; }
}
// 打不开的项目：清掉上一个项目的数据、步骤条和导航，state.project 置空 → 任何写操作都发不出去
function showProjectError(name, e){
  clearTimeout(saveTimer); saveTimer = null; unsavedFor = null; renderSavebar();
  stopAnalysisPoll(); resetResult(); resetExport(); resetBrowse(); resetCriteria();
  state.project = null; state.data = null; state.shots = []; state.sel = null; state.view = null;
  $('#title').textContent = name || ''; $('#meta').textContent = '';
  $('#steps').innerHTML = ''; $('#banner').innerHTML = ''; $('#nav').innerHTML = '';
  setStage(`<div class="card error"><h3>${esc(COPY_PROJECT_OPEN_FAILED)}</h3><p>${esc(e.message)}</p></div>`);
  setRail();
  renderWarnbar([e.message]); toast(e.message, TOAST_ERROR_MS);
}
// KI-35：快速切项目时，先发出的请求可能后回来。每次刷新带序号，过期的响应（成功或失败）一律丢掉
let stateSeq = 0;
// 当前页面看的步骤若在新的 wizard 里不可用（或还没有）→ 去 wizard.next；刷新与保存项目设置共用
function resolveView(wizard, viewing){
  const step = wizard.steps.find(s => s.key === viewing);
  return !step || step.status === 'locked' ? wizard.next : viewing;
}
async function refresh(name=state.project){
  if(!name) return;
  if(name === state.project) await flushPendingSave();  // 还在防抖里的分镜表改动先落盘，别被服务端旧数据盖掉
  const seq = ++stateSeq, editsAtSend = editSeq;
  let data;
  try { data = await api('/api/state?project='+encodeURIComponent(name)); }
  catch(e){ if(seq !== stateSeq) e.stale = true; throw e; }
  if(seq !== stateSeq) return false;
  // 等响应的这段时间里又改了分镜表（还没落盘 / 正在存 / 存失败了 / 发请求之后又改过）：保留本地的，不拿服务端的覆盖
  const dirty = name === state.project && (saveTimer !== null || saveQ.queued !== null || saveInflight > 0
    || unsavedFor === name || editSeq !== editsAtSend);
  state.project = name; state.data = data;  // 成功之后才切过去
  if(!dirty) adoptShots(data.shots);
  const wizard = data.wizard || {steps: [], next: 'analyze'};
  const before = state.view;
  state.view = resolveView(wizard, before);  // 当前页不可用了（或刚进项目）→ 去下一步
  if(before === 'export' && state.view !== 'export') leaveExport();  // 被带离 ⑥：对比里的视频先停
  renderWarnbar(data.warnings);
  renderChrome();
  renderView();
  attachRunningJob(data.busy || data.job);
  if(state.view !== before && ENTER_HOOKS[state.view]) ENTER_HOOKS[state.view]();  // 刚进项目就落在 ② 时也要读进度
}

// KI-71：上次剪辑台退出时留下的任务还在后台跑：打开剪辑台就说，而不是等点按钮弹 409
function renderStalebar(stale){
  const bar = $('#stalebar');
  bar.hidden = !stale;
  bar.innerHTML = stale ? `<b>${esc(COPY_STALE_TITLE)}</b><div>${esc(stale.message)}</div>` : '';
}
function renderWarnbar(list){
  const bar = $('#warnbar'), items = Array.isArray(list) ? list : [];
  bar.hidden = !items.length;
  bar.innerHTML = items.length
    ? `<b>${esc(COPY_WARNBAR_TITLE)}</b><ul>${items.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>` : '';
}

/* ---------------- 步骤切换与页面 ---------------- */
function welcomeHtml(){
  const intro = state.projects.length ? COPY_WELCOME_PICK : COPY_WELCOME_FIRST;
  return `<div class="welcome"><h2>${esc(COPY_WELCOME_TITLE)}</h2><p class="hint">${esc(intro)}</p>
    <button class="primary big" data-act="openNew">${esc(COPY_WELCOME_NEW)}</button></div>`;
}
function renderView(){
  const render = state.data ? STEP_VIEWS[state.view] : null;
  const html = state.data ? (render ? render() : '') : welcomeHtml();
  if(!stageIs(html)) setStage(html);  // 内容没变就不重画：分析页的 Key 输入框、滚动位置都不会被轮询打断
  paintResult();  // ⑤ 的各块内容没变就不重画（result-table.js）
  paintCompare();  // ⑥ 对比里的两个视频：重画后重新绑定同步播放
  applyBusyGuard();
}
async function go(key){
  if(key === 'new') return openProjectSettings();  // ① 已完成：回去看 / 改 = 项目设置
  const step = stepOf(key);
  if(!step || !state.data) return;
  if(step.status === 'locked'){ toast(step.hint || ''); return; }
  if(key === 'export' && !exportDoorOpen()){ toast(COPY_EXPORT_NEED_PREVIEW); return; }  // 本地刚改过表时服务端的步骤状态还没更新
  if(state.view === 'export' && key !== 'export') leaveExport();  // 对比里的视频先停
  if(state.view === 'result' && key !== 'result'){ await flushPendingSave(); leaveResult(); }  // 离开 ⑤ 前分镜表改动先落盘，在途的 ⑤ 回包作废
  if(state.view === 'criteria' && key !== 'criteria' && !await flushCriteriaDraft()){ criteriaDraftBlocked(); return; }  // 离开 ④ 前答案草稿先落盘；存不上就留在这里
  if(state.view === 'analyze' && key !== 'analyze') stopAnalysisPoll();
  state.view = key;
  renderChrome();
  renderView();
  const enter = ENTER_HOOKS[key];
  if(enter) enter();
}

/* ---------------- 分镜表保存队列 ---------------- */
let shotsEpoch = 0;  // 分镜表被服务端数据整体换掉（内容真的不同）时 +1；⑤ 据此决定要不要重画表格，本地输入不算
let editSeq = 0;        // 每次本地改分镜表 +1（result-table.js touchResult）：请求发出之后又改过的，旧回包不能盖掉
let saveInflight = 0;   // 正在路上的保存数
let unsavedFor = null, unsavedReason = '';  // 保存失败（忙 / 断网 / 500）、至今没存上的项目名：它的本地表永远不被服务端数据覆盖
function adoptShots(list){
  if(unsavedFor === state.project) return;
  const next = (list||[]).map(s=>({...s}));
  if(JSON.stringify(next) !== JSON.stringify(state.shots)) shotsEpoch += 1;
  state.shots = next;
}
const SAVE_RETRY_MS = 3000, SAVE_RETRY_MAX = 5;  // 服务端说「正在忙」（409 非过期）时，本地改动保留，稍后自动重试
const COPY_UNSAVED = '分镜表的改动还没存上：{reason}。请先别关页面。';
const COPY_UNSAVED_RETRY = '重试保存';
let saveRetryTimer = null, saveRetries = 0;
// 持久警告：存失败且没有自动重试在排队（重试用完了 / 不是「忙」类错误）时一直显示，直到存成功
function renderSavebar(){
  const bar = $('#savebar'), show = unsavedFor !== null && unsavedFor === state.project && saveRetryTimer === null;
  bar.hidden = !show;
  bar.innerHTML = show ? `<b>${esc(COPY_UNSAVED.replace('{reason}', unsavedReason))}</b> `
    + `<button class="primary" data-act="retrySave">${esc(COPY_UNSAVED_RETRY)}</button>` : '';
}
function retrySave(){
  clearTimeout(saveRetryTimer); saveRetryTimer = null; saveRetries = 0;
  return saveShots(true);
}
function retrySaveLater(project){
  clearTimeout(saveRetryTimer); saveRetryTimer = null;
  if(saveRetries >= SAVE_RETRY_MAX) return;
  saveRetries += 1;
  saveRetryTimer = setTimeout(()=>{ saveRetryTimer = null; if(state.project === project) saveShots(true); }, SAVE_RETRY_MS);
}
let saveTimer=null;
function scheduleSave(){ clearTimeout(saveTimer); saveTimer = setTimeout(()=>{ saveTimer = null; saveShots(true); }, 700); }
// 等防抖中的、已排队的、正在发的保存全部落盘；返回最后一次保存是否成功（KI-35 / KI-50）
async function flushPendingSave(){
  if(saveTimer){ clearTimeout(saveTimer); saveTimer = null; saveShots(true); }
  return saveQ.chain;
}
// KI-50：保存走单通道，同一时间只有一个 POST 在路上；排队中的请求合并成一次，发出时用最新快照。
// 项目名在调用时就记下（切项目前 selectProject 已 flush），绝不会把 A 的分镜表存进 B
const saveQ = {chain: Promise.resolve(true), queued: null};
function saveShots(silent){
  if(!state.project) return Promise.resolve(false);  // 当前没有打开的项目（或项目打不开）：绝不写
  renumber();
  const shots = state.shots.map(s=>({...s}));
  if(saveQ.queued && saveQ.queued.project === state.project){
    saveQ.queued.shots = shots;  // 还没发出：直接换成最新快照
    return saveQ.queued.done;
  }
  const slot = {project: state.project, shots};
  slot.done = saveQ.chain.then(()=>{
    if(saveQ.queued === slot) saveQ.queued = null;
    return postShots(slot.project, slot.shots, silent);
  });
  saveQ.queued = slot;
  saveQ.chain = slot.done;
  return slot.done;
}
async function postShots(project, shots, silent){
  // 带上页面读到的 AI 选段指纹：期间被「覆盖」重新选段了，服务端拒收（409 stale），不把旧页面存回去
  const selection_digest = state.project === project && state.data ? state.data.selection_digest : undefined;
  saveInflight += 1;
  try{
    await api('/api/shots?project='+encodeURIComponent(project), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({shots, selection_digest})
    });
    saveRetries = 0; unsavedFor = null; renderSavebar();
    onShotsSaved(project);  // ⑤：防抖后重拉服务端数字（step-result.js）
    return true;  // 不重绘，避免输入框失焦
  }catch(e){
    toast(COPY_SAVE_FAILED+e.message);
    // 过期页面:等本次保存收尾后重新读(refresh 会等保存队列,在队列里直接调用会等自己)
    if(e.status === 409 && e.data && e.data.stale){
      unsavedFor = null;  // 页面本来就过期了：重新读，以服务端为准
      setTimeout(()=>{ refreshOrWarn(project).then(()=>reloadResultNow(project)); }, 0);
    }else{
      unsavedFor = project; unsavedReason = e.message;
      if(e.status === 409) retrySaveLater(project);  // 正在重新选段 / 别处在写：改动还在本地，稍后再试
    }
    renderSavebar();
    return false;
  }finally{ saveInflight -= 1; }
}

/* ---------------- 启动 ---------------- */
async function enterApp(){
  await loadPrefs();
  try{ await loadProjects(); }catch(e){ toast(e.message, TOAST_ERROR_MS); }
  const wanted = new URLSearchParams(location.hash.slice(1)).get('project');  // #project= 只读一次，不做 hash 路由（KI-57）
  if(wanted) await selectProject(wanted);
  else renderView();
}
async function boot(){
  initRail(); initMore();
  if(!await checkFirstRun()) return;
  await enterApp();
}
