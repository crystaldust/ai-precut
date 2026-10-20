// 剪辑台主页 · ③ 的标记与剪辑列表（M13c）：S 放入 / 移出剪辑列表、A 可用、D 废片、X 不可用、Z 撤销（P8），以及右侧剪辑列表面板。
// 乐观更新：先改界面，再发请求；失败回滚并说出服务端原因。同一段的请求排队发（后一次等前一次回来）。
// 剪辑列表与「不可用」互斥，后按的生效（P9）；合计 / 超出 / 建议时长全部用服务端算的 clip_list，前端不再算一遍取整。

/* 界面文案：产品可直接改这里 */
const COPY_LIST_TITLE = '剪辑列表';
const COPY_LIST_COUNT = '{n} 段';
const COPY_LIST_SUM = '合计 {total} / 目标 {target}';
const COPY_LIST_EMPTY = '还没有片段：选中一段，按 S 放进来';
const COPY_LIST_REMOVE = '移出剪辑列表';
const COPY_OVER = '已超出目标 {over}，进片时全部保留';
const COPY_OVER_SUGGEST = '，建议把目标改为 {suggested}';
const COPY_CLEARED_UNUSABLE = '已取消不可用并放入剪辑列表';
const COPY_CLEARED_LIST = '已移出剪辑列表并标为不可用';
const COPY_REMOVED_SHOTS = '已从分镜表移除 {n} 镜';
const COPY_NOTHING_TO_UNDO = '没有可撤销的操作';
const COPY_UNDONE = '已撤销';
const COPY_UNDO_DROPPED = '撤销没成功，这一步已放弃';
const COPY_RESTORED = '已恢复 {n} 镜';
const COPY_NOT_RESTORED = '{n} 镜没能恢复（分镜表已改动）';
const COPY_ROLLED_BACK = '没保存上，已恢复原样：';
const UNDO_MAX = 50;   // P8：最多撤销 50 步，切项目 / 刷新后清空
const LEVEL_NAMES = {1: '废片', 2: '待定', 3: '可用'};
const PERCENT_MAX = 100;
const TOAST_MS_PER_CHAR = 120;
const MARK_FIELDS = ['level', 'level_reason', 'override', 'must_keep', 'unusable'];  // 服务端回的 segment 里只取这几项（topic 是显示名，不能被原名盖掉）

function bs(){ return state.browse; }
function curSeg(){ const b = bs(); return b && b.cur !== null ? b.segs[b.cur] : null; }
function snap(s){ return {must_keep: s.must_keep, unusable: s.unusable, level: s.level, override: s.override, level_reason: s.level_reason}; }

// 向导步骤状态直接用响应里的：⑤ 可能变「需要更新」。只重画步骤条 / 横幅 / 导航，不重画当前页
function applyWizard(w){
  if(!w || !Array.isArray(w.steps) || !state.data) return;
  state.data = {...state.data, wizard: w};
  renderSteps(); renderBanner(); renderNav();
}

/* ---------------- 请求队列：每段一条，放在模块里（按段 id），不挂在 seg 对象上 ---------------- */
// epoch：这一段只要有一次失败就 +1，排在它后面、还没发出的请求全部作废（不再发），界面回到服务端确认过的状态
const markQueues = new Map();
function queueOf(id){
  if(!markQueues.has(id)) markQueues.set(id, {chain: Promise.resolve(), n: 0, epoch: 0});
  return markQueues.get(id);
}
function pendingCount(){ let n = 0; markQueues.forEach(q => { n += q.n; }); return n; }
function resetMarks(){ markQueues.clear(); }

function announce(kind, r){
  const notes = [];
  if(kind === 'must' && r.cleared === 'unusable') notes.push(COPY_CLEARED_UNUSABLE);
  if(kind === 'unusable' && r.cleared === 'must_keep') notes.push(COPY_CLEARED_LIST);
  const gone = kind === 'unusable' && Array.isArray(r.removed_shots) ? r.removed_shots.length : 0;
  if(gone) notes.push(COPY_REMOVED_SHOTS.replace('{n}', gone));
  if(notes.length) toast(notes.join('；'), TOAST_NOTE_MS);
}
function restoreNote(r){
  const notes = [COPY_RESTORED.replace('{n}', num(r.restored))];
  if(num(r.not_restored)) notes.push(COPY_NOT_RESTORED.replace('{n}', num(r.not_restored)));
  return notes.join('；');
}
// 撤销栈在按键当时按顺序入栈；这一段有请求失败时，还没确认的条目一起作废（撤销只会指向服务端确认过的状态）
function pushUndo(b, entry){
  b.undo.push(entry);
  while(b.undo.length > UNDO_MAX) b.undo.shift();
}
function dropPendingEntries(b, id){
  b.undo = b.undo.filter(e => { if(e.id === id && !e.done){ e.dropped = true; return false; } return true; });
}
function confirmMarks(b, seg, change, r){
  const cur = {...(b.confirmed.get(seg.id) || snap(seg))}, src = r.segment || change;
  MARK_FIELDS.forEach(k => { if(k in src) cur[k] = src[k]; });
  b.confirmed.set(seg.id, cur);
}
function failMark(b, seg, message){
  Object.assign(seg, b.confirmed.get(seg.id));    // 回到服务端确认过的状态，不是按键当时的快照
  dropPendingEntries(b, seg.id);
  refreshSeg(seg);
  toast(COPY_ROLLED_BACK + message, Math.max(TOAST_ERROR_MS, String(message).length * TOAST_MS_PER_CHAR));
}

// 乐观更新 → 排队发请求 → 成功合并服务端结果；失败对账。opts.record=false：撤销自身；opts.restore：要放回的镜头
async function applyMark(seg, change, kind, path, body, opts = {}){
  const b = bs();
  if(!b) return false;
  const q = queueOf(seg.id), epoch = q.epoch;
  const entry = opts.record === false ? null : {id: seg.id, before: snap(seg), removed: [], done: false, dropped: false};
  q.n += 1;
  Object.assign(seg, change);
  if(entry) pushUndo(b, entry);
  refreshSeg(seg);
  const send = {...body, ...(opts.restore && opts.restore.length ? {restore_shots: opts.restore} : {})};
  // 失败时在链内立刻 epoch+1：排在后面的请求轮到时一定看得到，不会抢在界面对账之前发出去
  const run = q.chain.then(async () => {
    if(q.epoch !== epoch) return {skipped: true};
    try{ return {r: await postJson(path, {project: b.project, id: seg.id, ...send})}; }
    catch(e){ q.epoch += 1; return {err: e}; }
  });
  q.chain = run.then(() => {}, () => {});
  const {r, err, skipped} = await run;
  q.n -= 1;
  if(bs() !== b || skipped) return false;          // 切项目了 / 前面失败、这次作废：不碰界面
  if(err){ failMark(b, seg, err.message); return false; }
  confirmMarks(b, seg, change, r);
  if(!q.n && r.segment) MARK_FIELDS.forEach(k => { if(k in r.segment) seg[k] = r.segment[k]; });  // 后面还有排队的请求时不覆盖它的乐观值
  if(r.clip_list) b.clip = r.clip_list;
  applyWizard(r.wizard);
  if(entry){ entry.done = true; entry.removed = kind === 'unusable' && Array.isArray(r.removed_shots) ? r.removed_shots : []; }
  refreshSeg(seg);
  if(entry) announce(kind, r);
  if(opts.restore && opts.restore.length) b.note = restoreNote(r);
  settleAfterSave(r);
  return true;
}
// 响应拼不出来（warning）：写已经成功，重新读取；镜头有变动（X 移除 / 撤销放回）：重读才能更新「已用 / 未用」
function settleAfterSave(r){
  const shotsChanged = (Array.isArray(r.removed_shots) && r.removed_shots.length) || num(r.restored) > 0;
  if(r.warning){ toast(r.warning, TOAST_NOTE_MS); resyncBrowse(); refreshOrWarn(); }
  else if(shotsChanged) resyncBrowse();
}

/* ---------------- 四种标记 ---------------- */
function toggleList(seg){
  const want = !seg.must_keep;
  const change = want && seg.unusable ? {must_keep: true, unusable: false} : {must_keep: want};  // P9：放入列表 = 取消不可用
  return applyMark(seg, change, 'must', '/api/browse/must', {must: want});
}
function markUnusable(seg){
  const want = !seg.unusable;
  const change = want && seg.must_keep ? {unusable: true, must_keep: false} : {unusable: want};  // P9：不可用 = 移出列表
  return applyMark(seg, change, 'unusable', '/api/browse/unusable', {unusable: want});
}
function markLevel(seg, level){
  if(seg.override && seg.level === level) return Promise.resolve(false);   // 已经是人工标的这一档
  const change = {level, override: true, level_reason: `人工改为${LEVEL_NAMES[level]}`};
  return applyMark(seg, change, 'level', '/api/browse/level', {level});
}

/* ---------------- 撤销（P8）：恢复到这次标记之前的状态，必要时发几个反向请求 ---------------- */
async function restoreSeg(seg, to, removed){
  if(to.unusable !== seg.unusable){
    const change = to.unusable && seg.must_keep ? {unusable: true, must_keep: false} : {unusable: to.unusable};
    const opts = {record: false, restore: to.unusable ? [] : removed};   // 撤销 X：把 X 移除的镜头放回手动分镜表
    if(!await applyMark(seg, change, 'unusable', '/api/browse/unusable', {unusable: to.unusable}, opts)) return false;
  }
  const quiet = {record: false};
  if(to.must_keep !== seg.must_keep
     && !await applyMark(seg, {must_keep: to.must_keep}, 'must', '/api/browse/must', {must: to.must_keep}, quiet)) return false;
  if(!to.override && seg.override)
    return applyMark(seg, {level: to.level, override: false, level_reason: to.level_reason}, 'level', '/api/browse/level', {level: null}, quiet);
  if(to.override && seg.level !== to.level)
    return applyMark(seg, {level: to.level, override: true, level_reason: to.level_reason}, 'level', '/api/browse/level', {level: to.level}, quiet);
  return true;
}
// 取最近一条有效的撤销条目：先等这一段在途的请求落地；已作废 / 段已不存在的条目直接丢掉，不会卡住撤销栈
async function nextUndo(b){
  while(b.undo.length){
    const e = b.undo.pop();
    await queueOf(e.id).chain;
    if(bs() !== b) return null;
    const seg = b.segs.find(s => s.id === e.id);
    if(!e.dropped && seg) return {entry: e, seg};
  }
  return null;
}
async function undoLast(){
  const b = bs();
  if(!b) return false;
  const found = await nextUndo(b);
  if(bs() !== b) return false;
  if(!found){ toast(COPY_NOTHING_TO_UNDO); return false; }
  const {entry, seg} = found;
  let ok = await restoreSeg(seg, entry.before, entry.removed);
  if(!ok && bs() === b) ok = await restoreSeg(seg, entry.before, entry.removed);   // 重试一次
  if(bs() !== b) return false;
  if(!ok){ toast(COPY_UNDO_DROPPED, TOAST_ERROR_MS); return false; }              // 还是不行：丢掉这一条，不卡住后面的
  setCurrent(seg); toast(b.note || COPY_UNDONE, TOAST_NOTE_MS); b.note = null;
  return true;
}

/* ---------------- 重画：只动受影响的行 / 计数 / 面板 ---------------- */
function refreshSeg(seg){
  paintRow(seg); paintDensityCell(seg); paintGroups(); renderFilters(); renderNote();
  renderClipPanel(pendingCount() ? localClip() : undefined);   // 还有在途的改动：面板把它们合并进去，不被别的响应盖掉
}
// 请求还在路上时面板先按本地标记显示（顺序：服务端已有的在前，新放入的在后）；回来后换成服务端的数
function localClip(){
  const b = bs(), base = b.clip || {items: [], target: 0};
  const order = new Map((base.items || []).map((it, i) => [it.id, i]));
  const rank = s => order.has(s.id) ? order.get(s.id) : order.size;
  const marked = b.segs.filter(s => s.must_keep && !s.unusable).sort((x, y) => rank(x) - rank(y));
  const items = marked.map(s => ({id: s.id, start: s.start, end: s.end, dur: s.dur, topic: s.topic, text: s.text}));
  const total = items.reduce((n, it) => n + num(it.dur), 0);
  const over = total > num(base.target);
  return {...base, items, total, over_target: over, over_by: over ? total - num(base.target) : 0,
          suggested_target: over ? base.suggested_target : null};
}
function clipItemHtml(it, b){
  const seg = b.segs.find(s => s.id === it.id);
  if(!seg) return '';
  const i = num(seg._i);
  return `<li><span class="clip-item" data-act="jumpClip" data-i="${num(i)}"><b>${fmt(num(it.start))}</b> `
    + `${esc(String(it.text ?? '').slice(0, 24))}</span>`
    + `<button class="ghost" data-act="removeClip" data-i="${num(i)}" title="${esc(COPY_LIST_REMOVE)}" aria-label="${esc(COPY_LIST_REMOVE)}">✕</button></li>`;
}
function panelHtml(clip, b){
  const items = clip.items || [], total = num(clip.total), target = num(clip.target);
  const pct = target > 0 ? Math.min(PERCENT_MAX, total / target * PERCENT_MAX) : 0;
  const over = clip.over_target
    ? `<div class="p-over">${esc(COPY_OVER.replace('{over}', fmtLong(num(clip.over_by)))
        + (clip.suggested_target ? COPY_OVER_SUGGEST.replace('{suggested}', fmtLong(num(clip.suggested_target))) : ''))}</div>` : '';
  return `<h3>${esc(COPY_LIST_TITLE)} <span class="n">${esc(COPY_LIST_COUNT.replace('{n}', items.length))}</span></h3>`
    + `<div class="p-sum">${esc(COPY_LIST_SUM.replace('{total}', fmtLong(total)).replace('{target}', fmtLong(target)))}</div>`
    + `<div class="p-bar${clip.over_target ? ' over' : ''}"><i style="width:${pct.toFixed(1)}%"></i></div>${over}`
    + (items.length ? `<ul>${items.map(it => clipItemHtml(it, b)).join('')}</ul>`
                    : `<div class="hint">${esc(COPY_LIST_EMPTY)}</div>`);
}
function renderClipPanel(clip){
  const b = bs();
  if(!b) return;
  $('#bPanel').innerHTML = panelHtml(clip || b.clip || {items: [], total: 0, target: 0}, b);
}

Object.assign(ACTIONS, {
  toggleListIdx: el => { const b = bs(); return b && toggleList(b.segs[num(el.dataset.i)]); },
  markUnusableIdx: el => { const b = bs(); return b && markUnusable(b.segs[num(el.dataset.i)]); },
  jumpClip: el => jumpSeg(num(el.dataset.i)),
  removeClip: el => { const b = bs(), s = b && b.segs[num(el.dataset.i)]; return s && s.must_keep ? toggleList(s) : undefined; },
});
