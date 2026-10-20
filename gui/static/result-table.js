// 剪辑台主页 · ⑤ 分镜表与播放器（M14）：分镜表（字幕可改、为什么选它、替代句、↑↓ ✕ ⧉、＋空镜、按时间排序）、
// 一个播放器两种模式（预览片 / 素材）、选中行设入出点、试听。
// 保存队列在 app.js（saveShots / scheduleSave / flushPendingSave）；页面骨架与顶栏在 step-result.js；
// 重画规则（GL-22）：选中行 / 展开替代句只切 class；轮询刷新不重画表格和播放器，字幕框不会失焦。

/* 界面文案：产品可直接改这里 */
const COPY_SHOTS_EMPTY = '分镜表还是空的';
const COPY_SHOTS_EMPTY_HINT = '先去「③ 看素材」挑片段，或在「④ 定标准」确认后自动生成分镜表。';
const COPY_SHOTS_HELP = '选中一行 → 定位 → 点「设为入点/出点」。改动会自动保存。';
const COPY_SHOTS_LOCKED = '正在重新选段，完成后再改分镜表';
const COPY_RESTORING = '正在恢复为 AI 选段，请稍等';
const COPY_SUB_PLACEHOLDER = '字幕（留空=无字幕空镜）';
const COPY_WHY = '为什么选它：';
const COPY_ALT_BUTTON = '▸ 替代句 {n}';
const COPY_BLANK = '＋ 空镜（当前位置）';
const COPY_SORT = '按时间排序';
const COPY_SHOTS_SUMMARY = '共 {n} 镜 · 总时长 {t}';
const COPY_GO_BROWSE = '去「③ 看素材」';
const COPY_BLANK_EMPTY = '加一个空镜';
const COPY_MODE_PREVIEW = '预览片';
const COPY_MODE_MATERIAL = '素材';
const COPY_POSITION = '当前位置';
const COPY_MARK_IN = '设为入点';
const COPY_MARK_OUT = '设为出点';
const COPY_PLAY_SHOT = '试听这一镜';
const COPY_PICK_FIRST = '先在分镜表里选中一行';
const COPY_MARKED_IN = '已设为入点';
const COPY_MARKED_OUT = '已设为出点';
const COPY_DELETED = '已删除';
const COPY_SORTED = '已按时间排序';
const COPY_BLANK_ADDED = '已加一个 3 秒空镜';
const BLANK_SHOT_S = 3;

/* ---------------- 是否可编辑（E10：重新选段期间只读） ---------------- */
// 正在重新选段（本项目）：服务端对分镜表写入一律 409，这里同步置灰
function resultLocked(){
  if(reselectUi.restoring) return true;  // 恢复为 AI 选段：从 flush 到服务端回包之间不许再改
  const v = jobUi.view;
  if(v && v.status === 'running') return v.task === 'select' && (!v.project || v.project === state.project);
  const b = state.data?.busy;
  return !!b && b.task === 'select' && b.project === state.project && !(v && v.id === b.id);
}
function editable(){
  if(!resultLocked()) return true;
  toast(reselectUi.restoring ? COPY_RESTORING : COPY_SHOTS_LOCKED);
  return false;
}
// 任务开始 / 结束时（applyBusyGuard 调用）：只读状态变了就重画表格
function syncResultLock(){
  const r = res();
  if(r && state.view === 'result' && r.lockPainted !== resultLocked()) paintTable(true);
}
// 本地改过分镜表：预览片立刻视为过期（服务端的结论在保存后重拉才到）
function touchResult(){
  editSeq += 1;
  const r = res();
  if(r && !r.touched){ r.touched = true; renderNav(); paintPlayer(); }
}
function afterEdit(){ touchResult(); paintTable(true); paintLive(); }

/* ---------------- 播放器：一个 <video>，两种模式 ---------------- */
function activeVideo(){ return $('#rPv') || null; }
function materialVideo(){ const r = res(); return r && r.mode === 'material' ? activeVideo() : null; }
function onVideoTime(){
  const r = res(), v = activeVideo();
  if(!r || !v) return;
  const cur = $('#rCurT');
  if(cur) cur.textContent = fmt(v.currentTime);
  if(r.stopAt !== null && v.currentTime >= r.stopAt){ v.pause(); r.stopAt = null; }
}
function videoHtml(r, pv){
  if(r.mode === 'material') return `<video id="rPv" src="/media/${encodeURIComponent(state.project)}/proxy" preload="metadata" controls></video>`;
  return pv && pv.url ? `<video id="rPv" src="${esc(pv.url)}" preload="metadata" controls></video>` : '';
}
function modeHtml(r){
  const btn = (mode, text) => `<button class="ghost${r.mode === mode ? ' on' : ''}" data-act="playerMode" data-mode="${esc(mode)}">${esc(text)}</button>`;
  return btn('preview', COPY_MODE_PREVIEW) + btn('material', COPY_MODE_MATERIAL);
}
function toolsHtml(r){
  if(r.mode !== 'material') return '';
  return `${esc(COPY_POSITION)} <b id="rCurT">00:00.0</b>
    <button class="ghost" data-act="mark" data-which="in">${esc(COPY_MARK_IN)}</button>
    <button class="ghost" data-act="mark" data-which="out">${esc(COPY_MARK_OUT)}</button>
    <button class="ghost" data-act="playSel">${esc(COPY_PLAY_SHOT)}</button>
    <span class="hint">${esc(COPY_SHOTS_HELP)}</span>`;
}
// 只在换项目 / 预览片换了 / 模式切换时重建 <video>：轮询刷新不会打断正在播放的画面
function paintPlayer(){
  const r = res();
  if(!r || state.view !== 'result') return;
  const pv = previewData();
  const key = [state.project, r.mode, r.mode === 'preview' && pv ? pv.url : ''].join('|');
  if(key !== r.playerKey){
    r.playerKey = key; r.stopAt = null;
    $('#rVideo').innerHTML = videoHtml(r, pv);
    const v = activeVideo();
    if(v) v.addEventListener('timeupdate', onVideoTime);
  }
  setIf('#rMode', modeHtml(r));
  setIf('#rPvNote', previewNoteHtml(pv));
  setIf('#rTools', toolsHtml(r));
}
function setPlayerMode(mode){
  const r = res();
  if(!r || r.mode === mode) return;
  r.mode = mode;
  paintPlayer();
}
function seekNoSwitch(t){ const v = activeVideo(); if(v) v.currentTime = t; }
function playSel(){
  const v = materialVideo(), r = res();
  if(!v || state.sel == null || !state.shots[state.sel]) return;
  const s = state.shots[state.sel];
  v.currentTime = num(s.in); r.stopAt = num(s.out); playQuietly(v);
}
function currentTime(){ const v = materialVideo(); return v ? v.currentTime : 0; }
function mark(which){
  if(!editable()) return;
  if(state.sel == null || !state.shots[state.sel]){ toast(COPY_PICK_FIRST); return; }
  const s = state.shots[state.sel];
  if(which === 'in'){ s.in = +currentTime().toFixed(2); if(s.out <= s.in) s.out = +(s.in + 3).toFixed(2); }
  else { s.out = +currentTime().toFixed(2); if(s.out <= s.in) s.in = Math.max(0, s.out - 3); }
  afterEdit();   // 这一行的入 / 出点马上显示新值
  saveShots().then(ok=>{ if(ok) toast(which === 'in' ? COPY_MARKED_IN : COPY_MARKED_OUT); });
}

/* ---------------- 分镜表 ---------------- */
function noteOf(r, id){ return (r && r.data && r.data.notes && r.data.notes[id]) || null; }
function whyHtml(note, i){
  if(!note) return '';
  const alts = Array.isArray(note.alternatives) ? note.alternatives.length : 0;
  const topic = note.topic ? ` · ${esc(note.topic)}` : '';
  const btn = alts ? ` <button class="link" data-act="toggleAlt" data-i="${num(i)}">${esc(COPY_ALT_BUTTON.replace('{n}', alts))}</button>` : '';
  return `<div class="why">${esc(COPY_WHY)}${esc(note.why)}${topic}${btn}</div>`;
}
function altRowHtml(note, i, open, dis){
  const alts = note && Array.isArray(note.alternatives) ? note.alternatives : [];
  if(!alts.length) return '';
  const items = alts.map(a => `<li><span class="tc">${fmt(num(a.start))}</span> ${esc(a.text)}
      <button class="ghost" data-act="audition" data-id="${esc(a.id)}">${esc(COPY_AUDITION)}</button>
      <button class="ghost" data-act="addBack" data-id="${esc(a.id)}"${dis}>${esc(COPY_ADD_BACK)}</button></li>`).join('');
  return `<tr class="alt${open ? ' open' : ''}" id="alt${num(i)}"><td></td><td colspan="4"><ul class="alts">${items}</ul></td></tr>`;
}
function shotRowHtml(s, i, r, locked){
  const ro = locked ? ' readonly' : '', dis = locked ? ' disabled' : '';
  const note = noteOf(r, s.id);
  return `<tr class="shot${state.sel === i ? ' sel' : ''}" data-act="pick" data-i="${num(i)}">
      <td class="tc">${String(i + 1).padStart(2, '0')}</td>
      <td class="tc">${fmt(num(s.in))}–${fmt(num(s.out))}</td>
      <td class="tc">${(num(s.out) - num(s.in)).toFixed(1)}s</td>
      <td><textarea class="sub-edit" data-input="editSub" data-i="${num(i)}"${ro} placeholder="${esc(COPY_SUB_PLACEHOLDER)}">${esc(s.sub)}</textarea>${whyHtml(note, i)}</td>
      <td class="row-btns">
        <button title="上移" data-act="move" data-i="${num(i)}" data-d="-1"${dis}>↑</button>
        <button title="下移" data-act="move" data-i="${num(i)}" data-d="1"${dis}>↓</button>
        <button title="复制" data-act="dup" data-i="${num(i)}"${dis}>⧉</button>
        <button class="danger" title="删除" data-act="del" data-i="${num(i)}"${dis}>✕</button>
      </td></tr>${altRowHtml(note, i, r.open.has(s.id), dis)}`;
}
function tableHtml(r, locked){
  const dis = locked ? ' disabled' : '';
  if(!state.shots.length) return `<div class="empty">${esc(COPY_SHOTS_EMPTY)}<br><span class="hint">${esc(COPY_SHOTS_EMPTY_HINT)}</span><br><br>
    <button class="primary" data-act="go" data-step="browse">${esc(COPY_GO_BROWSE)}</button>
    <button class="ghost" data-act="addBlank"${dis}>${esc(COPY_BLANK_EMPTY)}</button></div>`;
  const total = state.shots.reduce((a, s) => a + num(s.out) - num(s.in), 0);
  const summary = COPY_SHOTS_SUMMARY.replace('{n}', state.shots.length).replace('{t}', fmt(total));
  return `<div class="toolbar">
      <button class="ghost" data-act="addBlank"${dis}>${esc(COPY_BLANK)}</button>
      <button class="ghost" data-act="sortShots"${dis}>${esc(COPY_SORT)}</button>
      <span class="hint">${esc(summary)}</span>${locked ? `<span class="lock">${esc(COPY_SHOTS_LOCKED)}</span>` : ''}
    </div>
    <table><thead><tr><th>#</th><th>入点–出点</th><th>时长</th><th>字幕</th><th></th></tr></thead>
    <tbody>${state.shots.map((s, i) => shotRowHtml(s, i, r, locked)).join('')}</tbody></table>`;
}
// 重画判据：镜头骨架（id / 入出点）+ 注解 + 只读状态 + 整体换表次数；字幕文字不算（正在输入的不能被重画打断）
function tableSig(r, locked){
  return JSON.stringify([state.shots.map(s => [s.id, s.in, s.out]), r.data ? r.data.notes : null, locked, shotsEpoch]);
}
function paintTable(force){
  const r = res();
  if(!r || state.view !== 'result') return;
  const locked = resultLocked(), sig = tableSig(r, locked);
  if(!force && (sig === r.tableSig || saveTimer !== null || saveQ.queued !== null)) return;
  r.tableSig = sig; r.lockPainted = locked;
  $('#rTable').innerHTML = tableHtml(r, locked);
}
// GL-22：选中行只切高亮，不重画整表，字幕框才不会在点进去时失焦
function pick(i){
  state.sel = i;
  document.querySelectorAll('#rTable tr.shot').forEach((tr, j) => tr.classList.toggle('sel', j === i));
  const s = state.shots[i];
  if(!s) return;
  setPlayerMode('material');
  seekNoSwitch(num(s.in));
}
function toggleAlt(i){
  const r = res(), s = state.shots[i];
  if(!r || !s) return;
  const open = !r.open.has(s.id);
  open ? r.open.add(s.id) : r.open.delete(s.id);
  const row = $('#alt' + num(i));
  if(row) row.classList.toggle('open', open);
}

/* ---------------- 编辑 ---------------- */
function edit(i, key, val){
  if(resultLocked() || !state.shots[i]) return;
  state.shots[i][key] = val;
  touchResult(); scheduleSave();
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
function move(i, d){
  const j = i + d;
  if(!editable() || j < 0 || j >= state.shots.length) return;
  [state.shots[i], state.shots[j]] = [state.shots[j], state.shots[i]];
  state.sel = j; saveShots(true); afterEdit();
}
function dup(i){
  if(!editable() || !state.shots[i]) return;
  state.shots.splice(i + 1, 0, {...state.shots[i], id: ''}); state.sel = i + 1; saveShots(true); afterEdit();
}
function del(i){
  if(!editable() || !state.shots[i]) return;
  state.shots.splice(i, 1); state.sel = null; saveShots(true); afterEdit(); toast(COPY_DELETED);
}
function addBlank(){
  if(!editable()) return;
  const t = +currentTime().toFixed(2);
  state.shots.push({id: '', in: t, out: +(t + BLANK_SHOT_S).toFixed(2), sub: '', note: ''});
  state.sel = state.shots.length - 1;
  afterEdit();
  saveShots(true).then(ok=>{ if(ok) toast(COPY_BLANK_ADDED); });
}
function sortShots(){
  if(!editable()) return;
  state.shots = [...state.shots].sort((a, b) => a.in - b.in); state.sel = null;
  saveShots(true); afterEdit(); toast(COPY_SORTED);
}

Object.assign(ACTIONS, {
  mark: el=>mark(el.dataset.which), playSel: ()=>playSel(), playerMode: el=>setPlayerMode(el.dataset.mode),
  addBlank: ()=>addBlank(), sortShots: ()=>sortShots(), toggleAlt: el=>toggleAlt(num(el.dataset.i)),
  pick: (el, ev)=>{   // 点字幕框是在编辑，不是选中这一行
    if(ev && ev.target && typeof ev.target.closest === 'function' && ev.target.closest('[data-input]')) return;
    pick(num(el.dataset.i));
  },
  move: el=>move(num(el.dataset.i), num(el.dataset.d)),
  dup: el=>dup(num(el.dataset.i)), del: el=>del(num(el.dataset.i)),
  editSub: el=>edit(num(el.dataset.i), 'sub', el.value),
});
