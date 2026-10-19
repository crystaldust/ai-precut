// 素材浏览页（KI-53：从 browse.html 内联脚本外置）。
const PROJECT = new URLSearchParams(location.search).get('project') || '';
const LV = {1:'废片',2:'待定',3:'可用'};
const COPY_WARN_TITLE = '需要你留意';
const COPY_SAVE_FAILED = '没保存上，已恢复原样';
const TOAST_MS = 1600, TOAST_ERROR_MIN_MS = 6000, TOAST_MS_PER_CHAR = 120;
const COLOR = {1:'var(--waste)',2:'var(--pending)',3:'var(--usable)'};
const pv = document.getElementById('pv');
let DATA = null, view='time', filter=0, cur=null;
const fmt = s => String(Math.floor(s/60)).padStart(2,'0')+':'+(s%60).toFixed(1).padStart(4,'0');

async function load(){
  const r = await fetch('/api/browse?project='+encodeURIComponent(PROJECT));
  if(!r.ok){ const e = await r.json().catch(()=>({}));
    document.getElementById('list').innerHTML =
      `<div class="empty">${esc(e.error || '还没有分析结果')}<br><br>先在剪辑台里跑「处理素材」</div>`; return; }
  DATA = await r.json();
  DATA.segments.forEach((s, i) => { s._i = i; });  // data-i 只放数字下标（GL-07）
  pv.src = '/media/'+encodeURIComponent(PROJECT)+'/proxy';
  document.getElementById('title').textContent = DATA.project.title || PROJECT;
  document.getElementById('sub').textContent =
    `素材 ${(DATA.material_duration/60).toFixed(1)} 分钟 · ${DATA.segments.length} 段 · 目标 ${DATA.project.target_duration}s`;
  renderWarnings(DATA.warnings);
  renderSummary(); density(); render();
}
// 损坏文件 / AI 兜底等提示（与剪辑台警告栏同源，M8）
function renderWarnings(list){
  const el = document.getElementById('warnstrip'), items = Array.isArray(list) ? list : [];
  el.style.display = items.length ? 'block' : 'none';
  el.innerHTML = items.length ? `<b>${esc(COPY_WARN_TITLE)}</b><ul>${items.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>` : '';
}
function toast(t, ms=TOAST_MS){ const el=document.getElementById('toast'); el.textContent=t; el.classList.add('on');
  clearTimeout(el._t); el._t=setTimeout(()=>el.classList.remove('on'), ms); }
// 错误要看得完：至少 6 秒，按字数加长
function toastError(t){ toast(t, Math.max(TOAST_ERROR_MIN_MS, String(t).length * TOAST_MS_PER_CHAR)); }
// 写失败（项目损坏 409 / 人工裁决文件损坏 409 等）：回滚界面上的乐观更新，并说出服务端原因
async function postOrRollback(path, body, rollback){
  let r = null;
  try { r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)}); }
  catch(e){ rollback(); toastError(COPY_SAVE_FAILED + '：' + e.message); return false; }
  if(r.ok) return true;
  const e = await r.json().catch(()=>({}));
  rollback(); toastError(e.error ? `${COPY_SAVE_FAILED}：${e.error}` : COPY_SAVE_FAILED);
  return false;
}
function renderSummary(){
  const s = DATA.summary || {};
  document.getElementById('summary').innerHTML =
    esc(s.summary || '（暂无摘要）') + (s.fallback ? '<div style="color:#8a6a3a;font-size:11px;margin-top:6px">（兜底摘要）</div>' : '');
  const box = document.getElementById('keypoints');
  box.innerHTML = (s.key_points||[]).map(p=>
    `<div class="kp" data-act="jumpAt" data-t="${num(p.at)}"><b>${fmt(num(p.at))}</b>${esc(p.text)}
       <span style="color:#6b7c93">· ${esc(p.why||'')}</span></div>`).join('') || '<div class="kp">—</div>';
  document.getElementById('castBox').innerHTML =
    (s.cast||[]).map(c=>`<span>${esc(c.name)}<span style="color:#6b7c93"> · ${esc(c.desc)}</span></span>`).join('');
}
function density(){
  const d = document.getElementById('density'); d.innerHTML='';
  const total = DATA.material_duration || 1;
  DATA.segments.forEach(s=>{
    const el = document.createElement('div');
    el.style.width = ((s.dur/total)*100).toFixed(3)+'%';
    el.style.background = COLOR[s.level];
    el.title = fmt(s.start)+' '+LV[s.level]+' · '+(s.topic||'');
    el.onclick = e=>{e.stopPropagation(); jump(s.start, s.id, s.end);};
    d.appendChild(el);
  });
}
function setView(v){ view=v;
  document.getElementById('vTime').classList.toggle('on',v==='time');
  document.getElementById('vCat').classList.toggle('on',v==='cat'); render(); }
function setFilter(f){ filter=f;
  [['fAll',0],['f2',2],['f3',3],['f1',1],['fUn',9]].forEach(([id,v])=>
    document.getElementById(id).classList.toggle('on', v===f)); render(); }
function pass(s){
  if(filter===9) return !s.inCut;
  if(filter===0) return true;
  return s.level===filter;
}
function row(s){
  const lv = num(s.level);
  return `<div class="row" data-id="${esc(s.id)}" data-act="jumpSeg" data-i="${num(s._i)}">
    <div class="tc">${fmt(num(s.start))}</div>
    <div class="cat" title="${esc(s.topic||'')}">${esc(s.topic||'—')}</div>
    <div class="lv lv${lv}" title="${esc(s.level_reason||'')}">${esc(LV[lv])}</div>
    <div class="sum">${esc(String(s.text ?? '').slice(0,60))}${s.inCut?'<span class="used">已用</span>':''}
      <small>${esc(s.level_reason||'')}${s.visual_flags?.length?' · 画面:'+s.visual_flags.map(esc).join('/'):''}</small></div>
    <div class="dur">${num(s.dur).toFixed(1)}s</div>
    <button class="star ${s.must_keep?'on':''}" data-act="toggleMustIdx" data-i="${num(s._i)}">★</button>
  </div>`;
}
function jumpSeg(i){ const s = DATA.segments[i]; jump(num(s.start), s.id, num(s.end)); }
function toggleMustIdx(i){ toggleMust(DATA.segments[i].id); }

function render(){
  if(!DATA) return;
  const list = document.getElementById('list');
  const items = DATA.segments.filter(pass);
  document.getElementById('count').textContent = `显示 ${items.length} / ${DATA.segments.length} 段`;
  if(view==='time'){ list.innerHTML = items.map(row).join(''); }
  else{
    const groups = {};
    items.forEach(s=>{ (groups[s.topic||'未归类'] ||= []).push(s); });
    list.innerHTML = Object.entries(groups).map(([name, arr])=>{
      const t = (DATA.topics||[]).find(x=>x.name===name) || {};
      const usable = arr.filter(s=>s.level===3).length;
      return `<div class="group">${esc(name)}${t.must?' · <span style="color:#ffc45c">必留</span>':''}
        <span>${arr.length} 句 · 可用 <span class="num">${usable}</span> ·
        可用时长 ${num(t.usable_dur).toFixed(0)}s · 预算 ${num(t.budget)}s</span></div>`
        + arr.map(row).join('');
    }).join('');
  }
  const n = {1:0,2:0,3:0};
  DATA.segments.forEach(s=>n[s.level]++);
  document.getElementById('n1').textContent=n[1];
  document.getElementById('n2').textContent=n[2];
  document.getElementById('n3').textContent=n[3];
  document.getElementById('nM').textContent=DATA.segments.filter(s=>s.must_keep).length;
  document.getElementById('pendBadge').textContent=`待判断 ${n[2]}`;
}

function jump(start, id, end){
  pv.currentTime = Math.max(0, start-0.3); playQuietly(pv);
  cur = id || null;
  const s = DATA.segments.find(x=>x.id===cur);
  document.getElementById('now').innerHTML = `<b>${fmt(start)}–${fmt(end||start+1)}</b>　${s?esc(String(s.text ?? '').slice(0,40)):''}<br>
    <span style="color:var(--muted)">${s?esc(s.level_reason||''):''}</span>`;
  document.querySelectorAll('.row').forEach(r=>r.classList.toggle('active', r.dataset.id===cur));
  clearInterval(window._t);
  window._t = setInterval(()=>{ if(pv.currentTime>=(end||start+999)){pv.pause();clearInterval(window._t);} },120);
}
async function setLevel(id, level){
  const s = DATA.segments.find(x=>x.id===id); if(!s) return;
  const prev = {level: s.level, level_reason: s.level_reason, override: s.override};
  s.level = level; s.level_reason = `人工改为${LV[level]}`; s.override = true;
  render();
  if(!await postOrRollback('/api/browse/level', {project:PROJECT, id, level}, ()=>Object.assign(s, prev))) render();
}
async function toggleMust(id){
  const s = DATA.segments.find(x=>x.id===id); if(!s) return;
  const prev = s.must_keep;
  s.must_keep = !prev;
  render();
  if(!await postOrRollback('/api/browse/must', {project:PROJECT, id, must:s.must_keep}, ()=>{ s.must_keep = prev; })) render();
}
document.addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT') return;
  if(e.code==='Space'){ e.preventDefault(); pv.paused?playQuietly(pv):pv.pause(); }
  if(e.code==='ArrowRight') pv.currentTime+=5;
  if(e.code==='ArrowLeft') pv.currentTime-=5;
  if(!cur) return;
  if(e.key==='a'||e.key==='A') setLevel(cur,3);
  if(e.key==='d'||e.key==='D') setLevel(cur,1);
  if(e.key==='s'||e.key==='S') toggleMust(cur);
});
const KEYPOINT_LISTEN_S = 4;  // 点关键信息试听的秒数
Object.assign(ACTIONS, {  // KI-53：页面里没有 on* 属性
  setView: el=>setView(el.dataset.v), setFilter: el=>setFilter(num(el.dataset.v)),
  jumpAt: el=>jump(num(el.dataset.t), null, num(el.dataset.t) + KEYPOINT_LISTEN_S),
  jumpSeg: el=>jumpSeg(num(el.dataset.i)), toggleMustIdx: el=>toggleMustIdx(num(el.dataset.i)),
});
load();
