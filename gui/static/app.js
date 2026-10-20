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
const FOCUS_REFRESH_MIN_MS = 2000;  // 从子窗口回到主页时刷新步骤状态，但别连着刷

/* 步骤 key → 页面（返回 HTML）；进入某步时的钩子 */
const STEP_VIEWS = {
  analyze: ()=>viewAnalyze(), browse: ()=>viewBrowse(), criteria: ()=>viewCriteria(),
  result: ()=>viewShots(), export: ()=>viewExport(),
};
const ENTER_HOOKS = {analyze: ()=>enterAnalyze(), browse: ()=>enterBrowse()};

/* ---------------- 项目 ---------------- */
async function selectProject(name){
  await flushPendingSave();  // 上一个项目还没落盘的分镜表改动先存回它自己
  resetShotBar();
  state.sel = null; state.view = null;  // 进入项目 = 去它的「当前步骤」（refresh 里按 wizard.next 定）
  resetAnalysis(); resetBrowse();
  await refreshOrWarn(name);
}

// KI-21：/api/state 失败（项目损坏 / 被删）必须说清原因：警告栏 + toast；所有刷新都走这里
async function refreshOrWarn(name=state.project){
  try { return await refresh(name) !== false; }
  catch(e){ if(e.stale) return false; showProjectError(name, e); return false; }
}
// 打不开的项目：清掉上一个项目的数据、步骤条和导航，state.project 置空 → 任何写操作都发不出去
function showProjectError(name, e){
  clearTimeout(saveTimer); saveTimer = null;
  stopAnalysisPoll(); resetShotBar(); resetBrowse();
  state.project = null; state.data = null; state.shots = []; state.sel = null; state.view = null;
  $('#title').textContent = name || ''; $('#meta').textContent = '';
  $('#steps').innerHTML = ''; $('#banner').innerHTML = ''; $('#nav').innerHTML = '';
  $('#shotbar').hidden = true; $('#shotbar').innerHTML = '';
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
  const seq = ++stateSeq;
  let data;
  try { data = await api('/api/state?project='+encodeURIComponent(name)); }
  catch(e){ if(seq !== stateSeq) e.stale = true; throw e; }
  if(seq !== stateSeq) return false;
  // 等响应的这段时间里又改了分镜表（还没落盘）：保留本地的，不拿服务端的覆盖
  const dirty = name === state.project && (saveTimer !== null || saveQ.queued !== null);
  state.project = name; state.data = data;  // 成功之后才切过去
  if(!dirty) state.shots = (data.shots||[]).map(s=>({...s}));
  const wizard = data.wizard || {steps: [], next: 'analyze'};
  const before = state.view;
  state.view = resolveView(wizard, before);  // 当前页不可用了（或刚进项目）→ 去下一步
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
  renderShotBar();
  applyBusyGuard();
}
async function go(key){
  if(key === 'new') return openProjectSettings();  // ① 已完成：回去看 / 改 = 项目设置
  const step = stepOf(key);
  if(!step || !state.data) return;
  if(step.status === 'locked'){ toast(step.hint || ''); return; }
  if(state.view === 'result' && key !== 'result') await flushPendingSave();  // 离开 ⑤ 前分镜表改动先落盘
  if(state.view === 'analyze' && key !== 'analyze') stopAnalysisPoll();
  state.view = key;
  renderChrome();
  renderView();
  const enter = ENTER_HOOKS[key];
  if(enter) enter();
}

/* ---------------- 分镜表保存队列 ---------------- */
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
  try{
    await api('/api/shots?project='+encodeURIComponent(project), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({shots})
    });
    return true;  // 不重绘，避免输入框失焦
  }catch(e){ toast(COPY_SAVE_FAILED+e.message); return false; }
}

/* ---------------- 子窗口（④ 暂住期仍用） ---------------- */
// KI-36：App（pywebview）里 window.open 无效，先请桌面壳开新窗口；浏览器模式（opened=false）才自己开标签
const SUBPAGES = ['confirm'];  // ③ 已并入主页，calibrate 已并入项目设置；只剩 ④ 的确认窗口
async function openSubpage(page){
  if(!SUBPAGES.includes(page)) return;
  if(!state.project) return toast('先选项目');
  const project = state.project;
  try{
    const r = await api('/api/window', {method:'POST', headers:{'Content-Type':'application/json'},
                                        body: JSON.stringify({project, page})});
    if(r.opened) return;
  }catch(e){ return toast(e.message); }
  window.open(`/static/${page}.html?project=` + encodeURIComponent(project), '_blank');
}
// 从子窗口回到主页：步骤状态可能变了（标了必留、确认了答案……），刷新一下；连着触发只刷一次
let lastFocusRefresh = 0;
function onWindowFocus(){
  if(!state.project || state.view !== 'criteria') return;
  const now = Date.now();
  if(now - lastFocusRefresh < FOCUS_REFRESH_MIN_MS) return;
  lastFocusRefresh = now;
  refreshOrWarn();
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
