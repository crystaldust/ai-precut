// 剪辑台主页（KI-53：从 index.html 内联脚本外置；事件一律走 common.js 的委托，不用 on* 属性）。
const $ = s => document.querySelector(s);
const state = { project:null, data:null, tab:'preview', sel:null, shots:[], dirty:false };
let proxyVideo = null;

/* 目标时长 / 必留超时长的界面文案（M2）：产品可直接改这里 */
const COPY_MUST_KEEP_OVER = '必留内容共 {must}，超过目标 {target}';
const COPY_MUST_KEEP_OVER_TITLE = '必留内容超过目标时长';
const COPY_TARGET_TITLE = '目标时长';
const COPY_TARGET_ASK = '想剪成多长？';
const COPY_TARGET_BUTTON = '按这个时长重新选段';
const COPY_TARGET_LATER = '先不改';
const COPY_TARGET_MANUAL_NOTE = '你已经手动编辑过分镜表，重新选段的结果不会覆盖它，只会更新「浏览素材」里的建议';
const COPY_NEW_TARGET_LABEL = '成片时长（自己定，预设只给默认值）';
const COPY_TARGET_RANGE = '时长要在 10 秒到 60 分钟之间（秒填 0–59 的整数）';
const TARGET_MIN_SEC = 10, TARGET_MAX_SEC = 3600;  // 与 pipeline/schema.py 的 TARGET_MIN / TARGET_MAX 一致
const COPY_WARNBAR_TITLE = '需要你留意';
const COPY_CONFIRM_ENTRY = '确认与提问';  // KI-05：确认页入口（确认后自动按答案重新选段）
const TOAST_ERROR_MS = 6000;
const COPY_STALE_TITLE = '上次留下的任务还在跑';  // KI-71：顶部提示条（D14）
const COPY_LLM_USAGE = 'LLM 已用 {n} tokens';    // KI-32：只显示 tokens，不折算金额（D3）
const COPY_LLM_USAGE_CAP = '（上限 {n}）';
const COPY_TOKENS_WAN = '{n} 万';
const TOKENS_WAN = 10000;
const COPY_CACHE_TITLE = '清理缓存';             // KI-33（D4）
const COPY_CACHE_INTRO = '会删除下面这些中间文件：镜头切片、没写完的临时文件、已经用完的转写音轨。分析代理、预览片、成片和所有分析结果都不会删。删掉的切片会在重新生成成片、或导出旧版本的 Windows 剪映包时按当时的分镜表重新切（多花几分钟）。';
const COPY_CACHE_TOTAL = '共可释放 {mb} MB';
const COPY_CACHE_EMPTY = '没有可清理的缓存';
const COPY_CACHE_CONFIRM = '清理';
const COPY_CACHE_CANCEL = '取消';
const COPY_CACHE_DONE = '已释放 {mb} MB';
const COPY_SAVE_FAILED = '保存失败：';
const COPY_BUILD_SAVE_FAILED = '分镜表还没保存成功，先不生成成片';  // KI-35
const MB = 1e6;
/* 任务弹窗文案在 /static/jobs.js，设置与外发告知文案在 /static/settings.js */

/* ---------------- 基础 ---------------- */
function toast(msg, ms=1800){
  const t = $('#toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove('on'), ms);
}
async function api(path, opt){
  const r = await fetch(path, opt);
  const j = await r.json().catch(()=>({}));
  if(!r.ok){  // 状态码和响应体挂在 Error 上：任务弹窗要据此区分 409 冲突 / 缺告知 / 缺 Key
    const e = new Error(j.error || ('请求失败 '+r.status)); e.status = r.status; e.data = j; throw e;
  }
  return j;
}
function fmt(sec){
  sec = Math.max(0, sec||0);
  const m = Math.floor(sec/60), s = sec%60;
  return `${String(m).padStart(2,'0')}:${s.toFixed(1).padStart(4,'0')}`;
}
function fmtMinSec(sec){
  sec = Math.round(num(sec));
  return sec>=60 ? `${Math.floor(sec/60)} 分 ${sec%60} 秒` : `${sec} 秒`;
}
function fmtLong(sec){
  const h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=Math.floor(sec%60);
  return h? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
          : `${m}:${String(s).padStart(2,'0')}`;
}

/* ---------------- 项目 ---------------- */
async function loadProjects(){
  const {projects, stale_job} = await api('/api/projects');
  renderStalebar(stale_job);
  const ul = $('#projects'); ul.innerHTML='';
  if(!projects.length){ ul.innerHTML = '<li><span>还没有项目</span></li>'; return; }
  projects.forEach(p=>{
    const li = document.createElement('li');
    li.innerHTML = `<b>${esc(p.title||p.name)}</b><span>${p.versions.length? '已出片 '+p.versions.map(esc).join(' / ') : '未出片'}</span>`;
    li.onclick = ()=>selectProject(p.name);
    if(p.name===state.project) li.classList.add('on');
    ul.appendChild(li);
  });
}

async function selectProject(name){
  await flushPendingSave();  // 上一个项目还没落盘的分镜表改动先存回它自己
  state.sel = null;
  if(!await refreshOrWarn(name)) return;
  document.querySelectorAll('#projects li').forEach(li=>li.classList.remove('on'));
  [...document.querySelectorAll('#projects li')].forEach(li=>{
    if(li.querySelector('b')?.textContent === (state.data?.project?.title||name)) li.classList.add('on');
  });
}

// KI-21：/api/state 失败（项目损坏 / 被删）必须说清原因：警告栏 + toast；所有刷新都走这里
async function refreshOrWarn(name=state.project){
  try { return await refresh(name) !== false; }
  catch(e){ if(e.stale) return false; showProjectError(name, e); return false; }
}
// 打不开的项目：清掉上一个项目的数据、收起操作栏，state.project 置空 → 任何写操作都发不出去
function showProjectError(name, e){
  clearTimeout(saveTimer); saveTimer = null;
  state.project = null; state.data = null; state.shots = []; state.sel = null;
  $('#title').textContent = name || ''; $('#meta').textContent = '';
  $('#steps').innerHTML = ''; $('#body').innerHTML = '';
  $('#actions').style.display = 'none'; $('#tabs').style.display = 'none';
  $('#shotbar').style.display = 'none'; $('#shotbar').innerHTML = '';
  renderWarnbar([e.message]); toast(e.message, TOAST_ERROR_MS);
}
// KI-35：快速切项目时，先发出的请求可能后回来。每次刷新带序号，过期的响应（成功或失败）一律丢掉
let stateSeq = 0;
async function refresh(name=state.project){
  if(!name) return;
  const seq = ++stateSeq;
  let data;
  try { data = await api('/api/state?project='+encodeURIComponent(name)); }
  catch(e){ if(seq !== stateSeq) e.stale = true; throw e; }
  if(seq !== stateSeq) return false;
  state.project = name; state.data = data;  // 成功之后才切过去
  const d = state.data, c = d.project;
  $('#title').textContent = c.title || c.name;
  const md = d.material_duration ? `素材 ${fmtLong(d.material_duration)} · ` : '';
  $('#meta').textContent = `${md}预设 ${c.preset} · 平台 ${c.platform} · 目标 ${c.target_duration ? fmtLong(num(c.target_duration)) : '—'}${usageText(d.llm_usage)}`;
  renderWarnbar(d.warnings);
  $('#steps').innerHTML = d.stages.map(s=>`<div class="step ${s.done?'done':''}">${s.done?'✓':'○'} ${esc(s.label)}</div>`).join('');
  $('#actions').style.display='flex';
  $('#tabs').style.display='flex';
  state.shots = (d.shots||[]).map(s=>({...s}));
  $('#shotCount').textContent = state.shots.length? `(${state.shots.length})` : '';
  $('#btnPrepare').textContent = d.stages.filter(s=>s.done).length>=4 ? '① 重新处理（会跳过已完成）' : '① 处理素材';
  renderTab();
  attachRunningJob(d.job);
}

// KI-71：上次剪辑台退出时留下的任务还在后台跑：打开剪辑台就说，而不是等点按钮弹 409
function renderStalebar(stale){
  const bar = $('#stalebar');
  bar.style.display = stale ? 'block' : 'none';
  bar.innerHTML = stale ? `<b>${esc(COPY_STALE_TITLE)}</b><div>${esc(stale.message)}</div>` : '';
}
function fmtTokens(n){
  n = num(n);
  return n >= TOKENS_WAN ? COPY_TOKENS_WAN.replace('{n}', (n / TOKENS_WAN).toFixed(1)) : String(n);
}
function usageText(u){
  if(!u || !num(u.total_tokens)) return '';
  const cap = u.budget ? COPY_LLM_USAGE_CAP.replace('{n}', fmtTokens(u.budget)) : '';
  return ' · ' + COPY_LLM_USAGE.replace('{n}', fmtTokens(u.total_tokens)) + cap;
}

function renderWarnbar(list){
  const bar = $('#warnbar'), items = Array.isArray(list) ? list : [];
  bar.style.display = items.length ? 'block' : 'none';
  bar.innerHTML = items.length
    ? `<b>${esc(COPY_WARNBAR_TITLE)}</b><ul>${items.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>` : '';
}

/* ---------------- Tab ---------------- */
function switchTab(name){
  state.tab = name;
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on', x.dataset.tab===name));
  renderTab();
}
document.querySelectorAll('.tab').forEach(t=>{ t.onclick = ()=>switchTab(t.dataset.tab); });

function renderShotBar(){
  const bar = $('#shotbar');
  if(state.tab!=='shots' || !state.shots.length){ bar.style.display='none'; bar.innerHTML=''; return; }
  bar.style.display='flex';
  const src = `/media/${encodeURIComponent(state.project)}/proxy`;
  bar.innerHTML = `
    <video id="pv2" src="${src}" preload="metadata" controls></video>
    <div>
      <div class="timebar" style="margin:0 0 8px">当前位置 <b id="cur2">00:00.0</b></div>
      <div style="display:flex;gap:8px">
        <button class="ghost" data-act="mark" data-which="in">设为入点</button>
        <button class="ghost" data-act="mark" data-which="out">设为出点</button>
        <button class="ghost" data-act="playSel">试听这一镜</button>
      </div>
    </div>
    <span class="hint" style="margin-left:auto">选中一行 → 定位 → 设为入/出点。改动自动保存。</span>`;
}

function renderTab(){
  const b = $('#body');
  if(!state.data){ return; }
  if(state.tab==='preview') b.innerHTML = viewPreview();
  if(state.tab==='script') b.innerHTML = viewScript();
  if(state.tab==='shots') b.innerHTML = viewShots();
  if(state.tab==='junk') b.innerHTML = viewJunk();
  if(state.tab==='versions') b.innerHTML = viewVersions();
  afterRender();
  renderShotBar();
}

/* ---------------- 预览 ---------------- */
function viewPreview(){
  const d = state.data;
  if(!d.has_proxy) return `<div class="empty">还没处理素材<br><br>
    <button class="primary" data-act="startJob" data-task="prepare">开始处理</button><br>
    <span class="hint">大约 5–15 分钟，取决于素材时长</span></div>`;
  const src = `/media/${encodeURIComponent(state.project)}/proxy`;
  return `<div class="player">
    <div>
      <video id="pv" src="${src}" controls preload="metadata"></video>
      <div class="timebar">当前位置 <b id="cur">00:00.0</b>
        <button class="ghost" data-act="mark" data-which="in">设为入点</button>
        <button class="ghost" data-act="mark" data-which="out">设为出点</button>
      </div>
      <div class="hint" style="margin-top:8px">在「分镜表」里选中一行，再用这两个按钮把当前位置填进该镜头。</div>
    </div>
    <div>
      <h3 style="margin-top:0">怎么用</h3>
      <ol style="color:var(--muted);padding-left:18px;line-height:2">
        <li>点「① 处理素材」：抽音轨、转写、找废片。</li>
        <li>去「文稿」里挑要的句子，点 <b>＋</b> 加进分镜表。</li>
        <li>去「分镜表」里排序、改出入点、改字幕。</li>
        <li>点「② 生成成片」，等它跑完，去剪映里精修。</li>
      </ol>
      <p class="hint">这段代理视频是 540p 的，只用来挑素材和定位，不影响成片画质。</p>
    </div>
  </div>`;
}

function afterRender(){
  ['#pv','#pv2'].forEach(sel=>{
    const v = $(sel);
    if(!v) return;
    v.addEventListener('timeupdate', ()=>{
      const c = sel==='#pv' ? $('#cur') : $('#cur2');
      if(c) c.textContent = fmt(v.currentTime);
    });
  });
}
function activeVideo(){ return $('#pv2') || $('#pv') || null; }
function playSel(){
  const v = activeVideo(); if(!v || state.sel==null) return;
  const s = state.shots[state.sel];
  v.currentTime = s.in; playQuietly(v);
  clearTimeout(playSel._t);
  playSel._t = setInterval(()=>{ if(v.currentTime >= s.out){ v.pause(); clearInterval(playSel._t); } }, 120);
}

function currentTime(){ const v=activeVideo(); return v ? v.currentTime : 0; }
function mark(which){
  if(state.sel==null){ toast('先在分镜表里选中一行'); return; }
  const s = state.shots[state.sel];
  if(which==='in'){ s.in = +currentTime().toFixed(2); if(s.out <= s.in) s.out = +(s.in+3).toFixed(2); }
  else { s.out = +currentTime().toFixed(2); if(s.out <= s.in) s.in = Math.max(0, s.out-3); }
  saveShots().then(()=>{ toast(which==='in'?'已设为入点':'已设为出点'); });
}

/* ---------------- 文稿 ---------------- */
function viewScript(){
  const segs = state.data.segments || [];
  if(!segs.length) return `<div class="empty">还没有文稿<br><br>
    <button class="primary" data-act="startJob" data-task="prepare">开始处理</button></div>`;
  return `<p class="hint">点句子可以跳到视频对应位置；点 <b>＋</b> 把它加进分镜表。</p>` +
    segs.map((s,i)=>`<div class="seg">
      <div class="t">${fmt(num(s.start))}</div>
      <div class="x" data-act="seek" data-t="${num(s.start)}">${esc(s.text)}</div>
      <div><button class="ghost" title="加入分镜表" data-act="addFromSeg" data-i="${num(i)}">＋</button></div>
    </div>`).join('');
}
function seek(t){
  if(state.tab!=='preview'){ state.tab='preview'; document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on', x.dataset.tab==='preview')); renderTab(); }
  setTimeout(()=>{ const v=$('#pv')||activeVideo(); if(v){ v.currentTime=t; playQuietly(v); } }, 60);
}
function addFromSeg(i){
  const s = state.data.segments[i];
  state.shots.push({id:'', in:+s.start.toFixed(2), out:+s.end.toFixed(2), sub:s.text, note:''});
  renumber();
  saveShots().then(()=>{ toast('已加入分镜表'); state.tab='shots';
    document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on', x.dataset.tab==='shots'));
    renderTab(); });
}

/* ---------------- 分镜表 ---------------- */
function viewShots(){
  if(!state.shots.length) return `<div class="empty">分镜表还是空的<br><br>
    <button class="primary" data-act="goScript">去文稿里挑句子</button>
    <button class="ghost" data-act="addBlank">加一个空镜（用当前位置）</button></div>`;
  const rows = state.shots.map((s,i)=>`
    <tr class="${state.sel===i?'sel':''}" data-act="pick" data-i="${num(i)}">
      <td class="tc">${String(i+1).padStart(2,'0')}</td>
      <td class="tc">${fmt(s.in)}</td>
      <td class="tc">${fmt(s.out)}</td>
      <td class="tc">${(s.out-s.in).toFixed(1)}s</td>
      <td><textarea class="sub-edit" data-input="editSub" data-i="${num(i)}" placeholder="字幕（留空=无字幕空镜）">${esc(s.sub)}</textarea></td>
      <td class="row-btns">
        <button title="上移" data-act="move" data-i="${num(i)}" data-d="-1">↑</button>
        <button title="下移" data-act="move" data-i="${num(i)}" data-d="1">↓</button>
        <button title="复制" data-act="dup" data-i="${num(i)}">⧉</button>
        <button class="danger" title="删除" data-act="del" data-i="${num(i)}">✕</button>
      </td>
    </tr>`).join('');
  const total = state.shots.reduce((a,s)=>a+(s.out-s.in),0);
  return `<div style="display:flex;gap:10px;align-items:center;margin-bottom:10px">
      <button class="primary" data-act="startJob" data-task="build">生成成片</button>
      <button class="ghost" data-act="addBlank">＋ 空镜（当前位置）</button>
      <button class="ghost" data-act="sortShots">按时间排序</button>
      <span class="hint">共 ${state.shots.length} 镜 · 总时长 ${fmt(total)}</span>
    </div>
    <table><thead><tr><th>#</th><th>入点</th><th>出点</th><th>时长</th><th>字幕</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="hint">选中一行 → 用上面的播放器定位 → 点「设为入点/出点」。改动会自动保存。</p>`;
}
function goScript(){ state.tab='script'; document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on', x.dataset.tab==='script')); renderTab(); }
// GL-22：选中行只切高亮，不重绘整表，字幕框才不会在点进去时失焦
function pick(i){
  state.sel = i;
  document.querySelectorAll('#body tbody tr').forEach((tr, j)=>tr.classList.toggle('sel', j===i));
  if(state.shots[i]) seekNoSwitch(state.shots[i].in);
}
function seekNoSwitch(t){ ['#pv','#pv2'].forEach(s=>{ const v=$(s); if(v) v.currentTime = t; }); }
let saveTimer=null;
function edit(i, key, val){ state.shots[i][key]=val; scheduleSave(); }
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
    if(silent!==true && silent!==undefined) return true;
    const c=$('#shotCount'); if(c && project===state.project) c.textContent = `(${state.shots.length})`;
    return true;  // 不重绘，避免输入框失焦
  }catch(e){ toast(COPY_SAVE_FAILED+e.message); return false; }
}
const SHOT_ID_RE = /^[A-Za-z0-9_-]{1,32}$/;
// 新 id = 现有 shNN 的最大编号 +1，删镜头后不会和留下的镜头撞号（GL-23）
function nextShotId(){
  const nums = state.shots.map(s=>/^sh(\d+)$/.exec(s.id||'')).filter(Boolean).map(m=>+m[1]);
  return 'sh'+String((nums.length ? Math.max(...nums) : 0)+1).padStart(2,'0');
}
// 补齐缺失 id、修正重复/非法 id（也能修好历史上已经存进 shots.json 的重复 id）
function renumber(){
  const seen = new Set();
  state.shots.forEach(s=>{
    if(!s.id || seen.has(s.id) || !SHOT_ID_RE.test(s.id)) s.id = nextShotId();
    seen.add(s.id);
  });
}
function move(i,d){
  const j=i+d; if(j<0||j>=state.shots.length) return;
  [state.shots[i],state.shots[j]]=[state.shots[j],state.shots[i]];
  state.sel=j; saveShots(true); renderTab();
}
function dup(i){
  const s={...state.shots[i], id:''};
  state.shots.splice(i+1,0,s); state.sel=i+1; saveShots(true); renderTab();
}
function del(i){
  state.shots.splice(i,1); state.sel=null; saveShots(true); renderTab(); toast('已删除');
}
function addBlank(){
  const t = +currentTime().toFixed(2);
  state.shots.push({id:'', in:t, out:+(t+3).toFixed(2), sub:'', note:''});
  state.sel = state.shots.length-1;
  saveShots(true).then(()=>{ toast('已加一个 3 秒空镜'); renderTab(); });
}
function sortShots(){
  state.shots.sort((a,b)=>a.in-b.in); state.sel=null; saveShots(true); renderTab(); toast('已按时间排序');
}

/* ---------------- 废片 ---------------- */
function viewJunk(){
  const items = state.data.junk || [];
  if(!items.length) return `<div class="empty">没有检测到技术废片<br><span class="hint">这类"一镜到底"素材，废片主要在内容层，去文稿里判断更准</span></div>`;
  return `<table><thead><tr><th>起</th><th>止</th><th>时长</th><th>原因</th><th>建议</th></tr></thead>
    <tbody>${items.map(j=>`<tr>
      <td class="tc">${esc(j.start_tc)}</td><td class="tc">${esc(j.end_tc)}</td>
      <td class="tc">${esc(j.duration)}s</td><td>${esc(j.reason)}</td>
      <td>${esc(j.suggest)}</td></tr>`).join('')}</tbody></table>`;
}

/* ---------------- 版本 ---------------- */
function viewVersions(){
  const vs = state.data.versions || [];
  if(!vs.length) return `<div class="empty">还没有出过片<br><br>
    <button class="primary" data-act="startJob" data-task="build">生成第一版</button></div>`;
  return vs.map((v, i)=>`<div class="ver">
    <h3>${esc(v.name)} <span class="hint">${num(v.shots)} 镜 · ${fmtLong(num(v.duration))} · ${esc(v.mtime)}</span></h3>
    <div class="m">${esc(COPY_MAC_DRAFT)}<b>${esc(v.draft)}</b></div>
    ${versionExportHtml(v, i)}
    ${v.preview? `<video src="/media/${encodeURIComponent(state.project)}/preview/${encodeURIComponent(v.name)}" controls preload="metadata"></video>` : '<p class="hint">这一版只有工程，没有预览片</p>'}
  </div>`).join('');
}

/* ---------------- 任务弹窗：见 /static/jobs.js ---------------- */
function logLine(t){ const el=$('#log'); if(el){ el.textContent += (el.textContent?'\n':'')+t; el.scrollTop=el.scrollHeight; } }
function showModal(title, html){
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = html;
  $('#mask').classList.add('on');
}
function closeModal(){ $('#mask').classList.remove('on'); }
// 与其它弹窗一致：Esc / 点遮罩空白处关闭（任务运行中除外，见 jobs.js 的 modalDismissable）
document.addEventListener('keydown', e=>{
  if(e.key === 'Escape' && $('#mask').classList.contains('on') && modalDismissable()) closeModal();
});
$('#mask').addEventListener('click', e=>{
  const mask = $('#mask');
  if(e.target === mask && modalDismissable()) closeModal();
});

/* ---------------- 生成成片弹窗 ---------------- */
function openBuild(){
  showModal('生成成片', `
    <p class="hint">会按分镜表切镜头、渲染预览，并生成剪映工程（版本号自动 +1，不会覆盖旧版）。</p>
    <label style="display:flex;gap:8px;align-items:center;margin:10px 0">
      <input type="checkbox" id="noDraft"> 只出预览（剪映正开着的时候选这个）
    </label>
    <button class="primary" data-act="doBuild">开始</button>
    <button class="ghost" data-act="closeModal">取消</button>`);
}
function doBuild(){
  const noDraft = $('#noDraft')?.checked;
  closeModal();
  startJob('build', {no_draft: noDraft});
}

/* ---------------- 目标时长 ---------------- */
function openTarget(fromOverrun){
  if(!state.project) return toast('先选项目');
  const sel = state.data?.selection || {};
  const cur = num(state.data?.project?.target_duration);
  const over = fromOverrun && sel.over_target;
  const value = over ? num(sel.suggested_target) : cur;
  const head = over ? COPY_MUST_KEEP_OVER.replace('{must}', fmtMinSec(sel.must_keep_total))
                                         .replace('{target}', fmtMinSec(cur)) : '';
  const manual = state.data?.shots_from_selection === false && state.shots.length;
  showModal(over ? COPY_MUST_KEEP_OVER_TITLE : COPY_TARGET_TITLE, `
    ${head ? `<p>${esc(head)}</p>` : ''}
    <div class="field"><label>${esc(COPY_TARGET_ASK)}</label>${durationFields('tgt', value)}</div>
    ${manual ? `<p class="hint">${esc(COPY_TARGET_MANUAL_NOTE)}</p>` : ''}
    <button class="primary" data-act="saveTarget">${esc(COPY_TARGET_BUTTON)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_TARGET_LATER)}</button>`);
}
function saveTarget(){
  const t = readDuration('tgt');
  if(!t) return toast(COPY_TARGET_RANGE);
  closeModal();
  startJob('select', {target: t});
}

/* 时长输入：分 + 秒两个框，任意时长（10 秒–60 分钟），不受预设限制 */
function durationFields(prefix, sec){
  sec = Math.round(num(sec));
  const m = sec ? Math.floor(sec/60) : '', s = sec ? sec%60 : '';
  return `<div style="display:flex;gap:6px;align-items:center">
    <input id="${prefix}Min" type="number" min="0" max="60" step="1" value="${m}" style="width:80px" data-input="markTargetTouched"> 分
    <input id="${prefix}Sec" type="number" min="0" max="59" step="1" value="${s}" style="width:80px" data-input="markTargetTouched"> 秒
  </div>`;
}
function readDuration(prefix){
  const part = id => { const v = String($('#'+prefix+id)?.value ?? '').trim();
    return v === '' ? 0 : (/^\d+$/.test(v) ? Number(v) : NaN); };
  const m = part('Min'), s = part('Sec');
  if(!(s < 60)) return 0;  // NaN 也走这里
  const total = m*60 + s;
  return total >= TARGET_MIN_SEC && total <= TARGET_MAX_SEC ? total : 0;
}
function markTargetTouched(){ state.npTouched = true; }

/* ---------------- 新建项目 ---------------- */
async function openNew(){
  state.npTouched = false;
  const {presets, warnings} = await api('/api/presets');
  state.presets = presets;
  const presetWarn = (warnings||[]).map(w=>`<div class="hint" style="color:var(--warn)">${esc(w)}</div>`).join('');
  showModal('新建项目', `
    <div class="field"><label>素材文件</label>
      <div style="display:flex;gap:8px">
        <input id="npPath" placeholder="点右边选择…" readonly>
        <button class="ghost" data-act="pickFile">选择</button>
      </div></div>
    <div class="field"><label>项目名（文件夹名，别用斜杠）</label><input id="npName" placeholder="例如 2026-09-15_探店"></div>
    <div class="field"><label>片名（会显示在剪映草稿上）</label><input id="npTitle" placeholder="例如 九月一号"></div>
    <div class="field"><label>${esc(COPY_NEW_TARGET_LABEL)}</label>${durationFields('np', 0)}</div>
    <div class="field"><label>风格预设</label>
      <select id="npPreset" data-change="syncTarget">${presets.map(p=>`<option value="${esc(p.key)}">${esc(p.name)} · ${esc(p.platform)}</option>`).join('')}</select>
      ${presetWarn}
    </div>
    <button class="primary" data-act="createProject">创建</button>
    <button class="ghost" data-act="closeModal">取消</button>`);
  syncTarget();
}
function syncTarget(){  // 换预设只在剪辑师还没自己填过时长时带出默认值
  if(state.npTouched || !$('#npMin')) return;
  const sec = Math.round(num((state.presets||[]).find(x=>x.key===$('#npPreset')?.value)?.duration));
  $('#npMin').value = sec ? String(Math.floor(sec/60)) : '';
  $('#npSec').value = sec ? String(sec%60) : '';
}
async function pickFile(){
  const {path} = await api('/api/pick', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  if(path){ $('#npPath').value = path; if(!$('#npName').value){
    $('#npName').value = path.split('/').pop().replace(/\.[^.]+$/,'');
    $('#npTitle').value = $('#npName').value; } }
}
async function createProject(){
  const material=$('#npPath').value, name=$('#npName').value.trim(), title=$('#npTitle').value.trim();
  const preset=$('#npPreset').value, target=readDuration('np');
  if(!material) return toast('先选素材');
  if(!target) return toast(COPY_TARGET_RANGE);
  if(!name) return toast('填个项目名');
  try{
    await api('/api/new', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({material, name, title, preset, target})});
    closeModal();
    await loadProjects();  // KI-57：只切到刚建的项目，不再按地址栏 hash 抢着切别的
    await selectProject(name);
    toast('项目已创建');
  }catch(e){ toast(e.message); }
}

/* ---------------- 其它 ---------------- */
// KI-36：App（pywebview）里 window.open 无效，先请桌面壳开新窗口；浏览器模式（opened=false）才自己开标签
async function openSubpage(page){
  if(!state.project) return toast('先选项目');
  const project = state.project;
  try{
    const r = await api('/api/window', {method:'POST', headers:{'Content-Type':'application/json'},
                                        body: JSON.stringify({project, page})});
    if(r.opened) return;
  }catch(e){ return toast(e.message); }
  window.open(`/static/${page}.html?project=` + encodeURIComponent(project), '_blank');
}
function openCalibrate(){ return openSubpage('calibrate'); }
function openConfirm(){ return openSubpage('confirm'); }
function openBrowse(){ return openSubpage('browse'); }

/* ---------------- 清理缓存（KI-33） ---------------- */
async function openCache(){
  if(!state.project) return toast('先选项目');
  let j;
  try{ j = await api('/api/cache?project='+encodeURIComponent(state.project)); }
  catch(e){ return toast(e.message, TOAST_ERROR_MS); }
  if(!(j.items||[]).length) return toast(COPY_CACHE_EMPTY);
  const rows = j.items.map(it=>`<li>${esc(it.label)}：<span class="hint">${esc(it.path)}</span> · ${(num(it.bytes)/MB).toFixed(1)} MB</li>`).join('');
  showModal(COPY_CACHE_TITLE, `
    <p class="hint">${esc(COPY_CACHE_INTRO)}</p><ul>${rows}</ul>
    <p>${esc(COPY_CACHE_TOTAL.replace('{mb}', (num(j.total)/MB).toFixed(1)))}</p>
    <div class="job-actions">
      <button class="primary" data-act="cleanCache">${esc(COPY_CACHE_CONFIRM)}</button>
      <button class="ghost" data-act="closeModal">${esc(COPY_CACHE_CANCEL)}</button>
    </div>`);
}
async function cleanCache(){
  const project = state.project;
  if(!project) return;
  try{
    const j = await api('/api/cache/clean', {method:'POST', headers:{'Content-Type':'application/json'},
                                             body: JSON.stringify({project})});
    closeModal(); toast(COPY_CACHE_DONE.replace('{mb}', (num(j.freed)/MB).toFixed(1)));
  }catch(e){ toast(e.message, TOAST_ERROR_MS); }
}
async function openFolder(){ await api('/api/open', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project:state.project, target:'project'})}); }
async function openJianying(){ await api('/api/open', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project:state.project, target:'jianying'})}); }

/* ---------------- 事件委托（KI-53：页面里没有 on* 属性） ---------------- */
Object.assign(ACTIONS, {
  markTargetTouched: ()=>markTargetTouched(),
  openNew: ()=>openNew(), openBuild: ()=>openBuild(), openConfirm: ()=>openConfirm(),
  openBrowse: ()=>openBrowse(), openCalibrate: ()=>openCalibrate(), openTarget: ()=>openTarget(false),
  openFolder: ()=>openFolder(), openJianying: ()=>openJianying(), openCache: ()=>openCache(),
  cleanCache: ()=>cleanCache(), startJob: el=>startJob(el.dataset.task), doBuild: ()=>doBuild(),
  saveTarget: ()=>saveTarget(), pickFile: ()=>pickFile(), createProject: ()=>createProject(),
  syncTarget: ()=>syncTarget(), closeModal: ()=>closeModal(), mark: el=>mark(el.dataset.which),
  playSel: ()=>playSel(), seek: el=>seek(num(el.dataset.t)), addFromSeg: el=>addFromSeg(num(el.dataset.i)),
  goScript: ()=>goScript(), addBlank: ()=>addBlank(), sortShots: ()=>sortShots(),
  pick: el=>pick(num(el.dataset.i)), move: el=>move(num(el.dataset.i), num(el.dataset.d)),
  dup: el=>dup(num(el.dataset.i)), del: el=>del(num(el.dataset.i)),
  editSub: el=>edit(num(el.dataset.i), 'sub', el.value),
});

$('#btnSettings').textContent = COPY_SETTINGS_ENTRY;
$('#btnConfirm').textContent = COPY_CONFIRM_ENTRY;
loadProjects().then(()=>{
  const h = new URLSearchParams(location.hash.slice(1));
  const p = h.get('project');
  if(p) selectProject(p).then(()=>{ const t=h.get('tab'); if(t) switchTab(t); });
});
checkFirstRun();
