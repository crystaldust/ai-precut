// 剪辑台主页 · ⑤ 看结果（M13b 暂住）：现有分镜表（表格、选中行设入出点、试听、↑↓ ✕ ⧉ 空镜、按时间排序）
// 加「改目标时长」。正式版（顶栏摘要、预览片、未采用清单）在后续里程碑替换这个文件。
// 分镜表的保存队列在 app.js（saveShots / scheduleSave / flushPendingSave），这里只调用。

/* 界面文案：产品可直接改这里 */
const COPY_MUST_KEEP_OVER = '必留内容共 {must}，超过目标 {target}';
const COPY_MUST_KEEP_OVER_TITLE = '必留内容超过目标时长';
const COPY_TARGET_TITLE = '目标时长';
const COPY_TARGET_ASK = '想剪成多长？';
const COPY_TARGET_BUTTON = '按这个时长重新选段';
const COPY_TARGET_LATER = '先不改';
const COPY_TARGET_MANUAL_NOTE = '你已经手动编辑过分镜表，重新选段的结果不会覆盖它，只会更新「看素材」里的建议';
const COPY_TARGET_CHANGE = '改目标时长';
const COPY_SHOTS_EMPTY = '分镜表还是空的';
const COPY_SHOTS_EMPTY_HINT = '先去「③ 看素材」挑片段，或在「④ 定标准」确认后自动生成分镜表。';
const COPY_SHOTS_HELP = '选中一行 → 用下面的播放器定位 → 点「设为入点/出点」。改动会自动保存。';

/* ---------------- 播放器与入出点 ---------------- */
// 播放器条只在换项目 / 重新进入时建一次：之后每次重画都保留 <video>，当前播放位置不丢
let shotbarFor = null;
function resetShotBar(){ shotbarFor = null; stopPlaySel(); }
function renderShotBar(){
  const bar = $('#shotbar');
  if(state.view!=='result' || !state.shots.length){ resetShotBar(); bar.hidden = true; bar.innerHTML=''; return; }
  bar.hidden = false;
  if(shotbarFor === state.project) return;
  shotbarFor = state.project;
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
    <span class="hint" style="margin-left:auto">${esc(COPY_SHOTS_HELP)}</span>`;
  const v = $('#pv2');
  if(v) v.addEventListener('timeupdate', ()=>{ const c = $('#cur2'); if(c) c.textContent = fmt(v.currentTime); });
}
function activeVideo(){ return $('#pv2') || null; }
let playTimer = null;  // 「试听这一镜」的结束检查；重播 / 切项目 / 播放器条被拆掉时都要清
function stopPlaySel(){ if(playTimer !== null){ clearInterval(playTimer); playTimer = null; } }
function playSel(){
  const v = activeVideo(); if(!v || state.sel==null) return;
  const s = state.shots[state.sel];
  stopPlaySel();
  v.currentTime = s.in; playQuietly(v);
  playTimer = setInterval(()=>{ if(v.currentTime >= s.out){ v.pause(); stopPlaySel(); } }, 120);
}
function currentTime(){ const v=activeVideo(); return v ? v.currentTime : 0; }
function mark(which){
  if(state.sel==null){ toast('先在分镜表里选中一行'); return; }
  const s = state.shots[state.sel];
  if(which==='in'){ s.in = +currentTime().toFixed(2); if(s.out <= s.in) s.out = +(s.in+3).toFixed(2); }
  else { s.out = +currentTime().toFixed(2); if(s.out <= s.in) s.in = Math.max(0, s.out-3); }
  saveShots().then(()=>{ toast(which==='in'?'已设为入点':'已设为出点'); });
}

/* ---------------- 分镜表 ---------------- */
function viewShots(){
  if(!state.shots.length) return `<div class="empty">${esc(COPY_SHOTS_EMPTY)}<br><span class="hint">${esc(COPY_SHOTS_EMPTY_HINT)}</span><br><br>
    <button class="primary" data-act="go" data-step="browse">去「③ 看素材」</button>
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
  return `<div class="toolbar">
      <button class="ghost" data-act="openTarget" data-starts-job>${esc(COPY_TARGET_CHANGE)}</button>
      <button class="ghost" data-act="addBlank">＋ 空镜（当前位置）</button>
      <button class="ghost" data-act="sortShots">按时间排序</button>
      <span class="hint">共 ${state.shots.length} 镜 · 总时长 ${fmt(total)}</span>
    </div>
    <table><thead><tr><th>#</th><th>入点</th><th>出点</th><th>时长</th><th>字幕</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>`;  // 操作说明在下方播放器条上（renderShotBar）
}
// GL-22：选中行只切高亮，不重绘整表，字幕框才不会在点进去时失焦
function pick(i){
  state.sel = i;
  document.querySelectorAll('#stage tbody tr').forEach((tr, j)=>tr.classList.toggle('sel', j===i));
  if(state.shots[i]) seekNoSwitch(state.shots[i].in);
}
function seekNoSwitch(t){ const v=$('#pv2'); if(v) v.currentTime = t; }
function edit(i, key, val){ state.shots[i][key]=val; scheduleSave(); }
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
  state.sel=j; saveShots(true); renderView();
}
function dup(i){
  const s={...state.shots[i], id:''};
  state.shots.splice(i+1,0,s); state.sel=i+1; saveShots(true); renderView();
}
function del(i){
  state.shots.splice(i,1); state.sel=null; saveShots(true); renderView(); toast('已删除');
}
function addBlank(){
  const t = +currentTime().toFixed(2);
  state.shots.push({id:'', in:t, out:+(t+3).toFixed(2), sub:'', note:''});
  state.sel = state.shots.length-1;
  saveShots(true).then(()=>{ toast('已加一个 3 秒空镜'); renderView(); });
}
function sortShots(){
  state.shots.sort((a,b)=>a.in-b.in); state.sel=null; saveShots(true); renderView(); toast('已按时间排序');
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
    <button class="primary" data-act="saveTarget" data-starts-job>${esc(COPY_TARGET_BUTTON)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_TARGET_LATER)}</button>`);
}
function saveTarget(){
  const t = readDuration('tgt');
  if(!t) return toast(COPY_TARGET_RANGE);
  closeModal();
  startJob('select', {target: t});
}

Object.assign(ACTIONS, {
  openTarget: ()=>openTarget(false), saveTarget: ()=>saveTarget(),
  mark: el=>mark(el.dataset.which), playSel: ()=>playSel(),
  addBlank: ()=>addBlank(), sortShots: ()=>sortShots(),
  pick: el=>pick(num(el.dataset.i)), move: el=>move(num(el.dataset.i), num(el.dataset.d)),
  dup: el=>dup(num(el.dataset.i)), del: el=>del(num(el.dataset.i)),
  editSub: el=>edit(num(el.dataset.i), 'sub', el.value),
});
