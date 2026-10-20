// 剪辑台主页 · ⑤ 未采用清单（M14）：可用但不在当前分镜表里的片段 + 原因 + 试听 + 加回。
// 加回 = 按时间插入分镜表（第一个入点比它晚的镜头之前），算一次手动修改：乐观更新 → 走保存队列 → 失败回滚。

/* 界面文案：产品可直接改这里 */
const COPY_UNUSED_TITLE = '未采用清单（{n}）';
const COPY_UNUSED_EMPTY = '没有未采用的可用片段';
const COPY_AUDITION = '试听';
const COPY_ADD_BACK = '加回';
const COPY_ADDED_BACK = '已加回第 {n} 镜（算一次手动修改）';
const COPY_ADD_BACK_GONE = '这一段已经不在清单里了';

function unusedItems(){
  const r = res();
  return r && r.data && Array.isArray(r.data.unused) ? r.data.unused.filter(u => !r.adding.has(u.id)) : [];
}
function unusedRowHtml(u, dis){
  const must = u.cause === 'must';
  return `<div class="un${must ? ' must' : ''}">
    <span class="tc">${fmt(num(u.start))}</span> <b>${esc(u.topic)}</b>
    <span class="cause">${esc(u.cause_label)}</span>
    <div class="un-text">${esc(u.text)}</div>
    <div class="un-btns"><button class="ghost" data-act="audition" data-id="${esc(u.id)}">${esc(COPY_AUDITION)}</button>
    <button class="ghost" data-act="addBack" data-id="${esc(u.id)}"${dis}>${esc(COPY_ADD_BACK)}</button></div></div>`;
}
function unusedHtml(list, locked){
  const head = `<h3>${esc(COPY_UNUSED_TITLE.replace('{n}', list.length))}</h3>`;
  if(!list.length) return head + `<p class="hint">${esc(COPY_UNUSED_EMPTY)}</p>`;
  return head + list.map(u => unusedRowHtml(u, locked ? ' disabled' : '')).join('');
}
function paintUnused(){
  const r = res();
  if(!r || state.view !== 'result') return;
  setIf('#rUnused', unusedHtml(unusedItems(), resultLocked()));
}
// 试听/替代句里的段不一定还在清单里（刚加回），所以也在每镜的替代句里找
function findSeg(id){
  const r = res();
  if(!r || !r.data) return null;
  const hit = (r.data.unused || []).find(u => u.id === id);
  if(hit) return hit;
  for(const note of Object.values(r.data.notes || {})){
    const alt = (note.alternatives || []).find(a => a.id === id);
    if(alt) return alt;
  }
  return null;
}
function audition(id){
  const u = findSeg(id), r = res();
  if(!u || !r) return;
  setPlayerMode('material');
  const v = activeVideo();
  if(!v) return;
  v.currentTime = Math.max(0, num(u.start) - PAD_S);
  r.stopAt = num(u.end) + PAD_S;
  playQuietly(v);
}
function insertByTime(shots, shot){
  const at = shots.findIndex(s => num(s.in) > num(shot.in));
  const idx = at < 0 ? shots.length : at;
  return [...shots.slice(0, idx), shot, ...shots.slice(idx)];
}
async function addBack(id){
  const r = res();
  if(!r || r.adding.has(id) || !editable()) return;
  const u = (r.data?.unused || []).find(x => x.id === id);
  if(!u){ toast(COPY_ADD_BACK_GONE); return; }
  r.adding.add(id);
  const shot = {id: nextShotId(), in: num(u.shot.in), out: num(u.shot.out), sub: String(u.shot.sub ?? ''), note: u.topic || ''};
  state.shots = insertByTime(state.shots, shot);   // 以当前本地表为准（剪辑师可能刚手动排过序）
  afterEdit(); paintUnused();
  try{
    const ok = await saveShots(true);   // 失败时 postShots 已经说明原因
    if(state.result !== r) return;
    if(!ok) state.shots = state.shots.filter(s => s !== shot);
    else toast(COPY_ADDED_BACK.replace('{n}', state.shots.indexOf(shot) + 1));
    afterEdit();
    clearTimeout(r.reloadTimer); r.reloadTimer = null;
    await loadResult();   // 成功要看清单更新，失败要让 touched / 闸门回到服务端的结论；行在这之前一直隐藏
  }finally{
    r.adding.delete(id);
    if(state.result === r) paintUnused();
  }
}

Object.assign(ACTIONS, {audition: el=>audition(el.dataset.id), addBack: el=>addBack(el.dataset.id)});
