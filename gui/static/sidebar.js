// 剪辑台主页 · 项目栏（M13）：进入项目后收成 48px 窄条，鼠标移上去或点 ☰ 浮出 240px；「固定」存在服务端偏好里。
// 固定状态走 /api/prefs（端口会顺延，浏览器本地存储按源隔离会丢；M12 承诺前端不用本地存储）。

/* 界面文案：产品可直接改这里 */
const CIRCLED = '①②③④⑤⑥';
const COPY_NO_PROJECTS = '还没有项目';
const COPY_PIN = '固定';
const COPY_UNPIN = '取消固定';
const COPY_VERSIONS_DONE = '已出 {v}';
const COPY_VERSIONS_NONE = '未出片';
const COPY_PREFS_WARNING_MS = 6000;
const COPY_PREFS_LOAD_FAILED = '读不到界面偏好，先用默认设置：{reason}';

function stepText(step){
  if(!step) return '';
  const n = num(step.n);
  return `${CIRCLED[n - 1] || n} ${step.label || ''}`;
}
function projectLabel(p){ return p.title || p.name; }

function projectItemHtml(p){
  const versions = (p.versions || []).length ? COPY_VERSIONS_DONE.replace('{v}', p.versions.join(' / ')) : COPY_VERSIONS_NONE;
  const sub = [stepText(p.step), versions].filter(Boolean).join(' · ');
  return `<li class="proj${p.name === state.project ? ' on' : ''}" data-act="selectProject" data-name="${esc(p.name)}">`
    + `<b>${esc(projectLabel(p))}</b><span>${esc(sub)}</span></li>`;
}
function renderProjects(projects=state.projects){
  const html = projects.length ? projects.map(projectItemHtml).join('')
                               : `<li><span>${esc(COPY_NO_PROJECTS)}</span></li>`;
  $('#projects').innerHTML = html;
  return html;
}
async function loadProjects(){
  const {projects, stale_job} = await api('/api/projects');
  state.projects = projects || [];
  renderStalebar(stale_job);
  renderProjects();
  setRail();
}

/* 「wide」：展开占位（没打开项目 / 已固定）；「narrow」：48px 窄条；「float」：窄条上浮出的 240px 面板 */
function railMode(inProject, pinned, open){
  if(!inProject || pinned) return 'wide';
  return open ? 'float' : 'narrow';
}
function setRail(){
  const inProject = !!state.project;
  const mode = railMode(inProject, state.pinned, state.railOpen);
  const current = state.projects.find(p => p.name === state.project);
  $('#app').classList.toggle('in-project', inProject);
  $('#app').classList.toggle('pinned', state.pinned);
  $('#rail').classList.toggle('open', mode === 'float');
  $('#btnPin').setAttribute('aria-pressed', state.pinned ? 'true' : 'false');
  $('#btnPin').textContent = state.pinned ? COPY_UNPIN : COPY_PIN;
  $('#railInitial').textContent = current ? Array.from(projectLabel(current))[0] || '' : '';
}
function toggleRail(){ state.railOpen = !state.railOpen; setRail(); }
function initRail(){  // addEventListener，不是内联事件（CSP）
  const rail = $('#rail');
  rail.addEventListener('mouseenter', ()=>{ if(state.project && !state.pinned){ state.railOpen = true; setRail(); } });
  rail.addEventListener('mouseleave', ()=>{ state.railOpen = false; setRail(); });
}

async function togglePin(){
  try{
    const r = await postJson('/api/prefs', {sidebar_pinned: !state.pinned});
    state.pinned = r.sidebar_pinned === true;
  }catch(e){ toast(e.message, TOAST_ERROR_MS); return; }  // 保存失败就保持原样，不假装固定了
  setRail();
}
async function loadPrefs(){
  try{
    const r = await api('/api/prefs');
    state.pinned = r.sidebar_pinned === true;
    if(r.warning) toast(r.warning, COPY_PREFS_WARNING_MS);
  }catch(e){ toast(COPY_PREFS_LOAD_FAILED.replace('{reason}', e.message), COPY_PREFS_WARNING_MS); }  // 用默认值，不挡住使用
  setRail();
}

Object.assign(ACTIONS, {
  selectProject: el=>{ state.railOpen = false; return selectProject(el.dataset.name); },
  toggleRail: ()=>toggleRail(), togglePin: ()=>togglePin(),
});
