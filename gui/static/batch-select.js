// 剪辑台主页 · ③ 批量选择（KI-103）：行首勾选框、Shift 连选、全选（当前筛选）、列表下方的操作栏、
// 批量标记（一个请求，整批成功或整批回滚）与整批撤销（一次 Z 一个请求）。
// 依赖：cliplist.js（队列 / 撤销栈 / 乐观更新工具）与 step-browse.js（列表骨架、b.shown）；动作注册在文件末尾。

/* 界面文案：产品可直接改这里 */
const COPY_BATCH_PICK_ALL = '全选';
const COPY_BATCH_PICK_ROW = '选择 {t}';
const COPY_BATCH_PICKED = '已选 {n} 段';
const COPY_BATCH_ADD = '放入剪辑列表';
const COPY_BATCH_REMOVE = '移出剪辑列表';
const COPY_BATCH_USABLE = '标为可用';
const COPY_BATCH_WASTE = '标为废片';
const COPY_BATCH_UNUSABLE = '标为不可用';
const COPY_BATCH_CLEAR = '取消选择';
const COPY_BATCH_DONE_ADD = '已放入剪辑列表 {n} 段';
const COPY_BATCH_DONE_REMOVE = '已移出剪辑列表 {n} 段';
const COPY_BATCH_DONE_USABLE = '已标为可用 {n} 段';
const COPY_BATCH_DONE_WASTE = '已标为废片 {n} 段';
const COPY_BATCH_DONE_UNUSABLE = '已标为不可用 {n} 段';
const COPY_BATCH_CLEARED_UNUSABLE = '其中 {n} 段已取消不可用';
const COPY_BATCH_CLEARED_LIST = '其中 {n} 段已移出剪辑列表';
const COPY_BATCH_SKIPPED = '另有 {n} 段本来就是这样，没有改';
const COPY_BATCH_NOOP = '所选的段都已经是这样，不需要改';
const LEVEL_USABLE = 3;
const LEVEL_WASTE = 1;

// 每种批量操作怎样改一段：返回 null = 这段已经是目标状态（跳过）；change 是本地乐观值，item 是发给服务端的字段
function levelPlan(level){
  return s => (s.override && s.level === level) ? null
    : {change: {level, override: true, level_reason: `人工改为${LEVEL_NAMES[level]}`}, item: {level}};
}
const BATCH_KINDS = {
  add: {label: COPY_BATCH_ADD, done: COPY_BATCH_DONE_ADD, plan: s => s.must_keep ? null
    : s.unusable ? {change: {must_keep: true, unusable: false}, item: {must_keep: true, unusable: false}}   // P9：放入 = 取消不可用
                 : {change: {must_keep: true}, item: {must_keep: true}}},
  remove: {label: COPY_BATCH_REMOVE, done: COPY_BATCH_DONE_REMOVE, plan: s => s.must_keep
    ? {change: {must_keep: false}, item: {must_keep: false}} : null},
  usable: {label: COPY_BATCH_USABLE, done: COPY_BATCH_DONE_USABLE, plan: levelPlan(LEVEL_USABLE)},
  waste: {label: COPY_BATCH_WASTE, done: COPY_BATCH_DONE_WASTE, plan: levelPlan(LEVEL_WASTE)},
  unusable: {label: COPY_BATCH_UNUSABLE, done: COPY_BATCH_DONE_UNUSABLE, plan: s => s.unusable ? null
    : {change: {unusable: true, must_keep: false}, item: {unusable: true}}},   // P9：不可用 = 移出列表
};

/* ---------------- 勾选框与全选 ---------------- */
function pickHtml(s){
  const i = num(s._i), b = bs();
  return `<input type="checkbox" class="pick" id="pk${i}" data-act="pickIdx" data-i="${num(i)}"`
    + `${b && b.sel.has(i) ? ' checked' : ''} aria-label="${esc(COPY_BATCH_PICK_ROW.replace('{t}', fmt(num(s.start))))}">`;
}
function pickState(b){
  const n = b.shown.filter(i => b.sel.has(i)).length;
  return {checked: b.shown.length > 0 && n === b.shown.length, partial: n > 0 && n < b.shown.length};
}
function pickAllHtml(){
  const b = bs(), st = pickState(b);
  return `<label class="pick-all"><input type="checkbox" id="bPickAll" data-act="pickAll"${st.checked ? ' checked' : ''}`
    + `${b.shown.length ? '' : ' disabled'}> ${esc(COPY_BATCH_PICK_ALL)} ${b.shown.length}</label>`;
}
function paintPickAll(){   // indeterminate 只能用属性设
  const b = bs(), box = $('#bPickAll');
  if(!b || !box) return;
  const st = pickState(b);
  box.checked = st.checked; box.indeterminate = st.partial;
}
function paintBatchBar(){
  const b = bs(), bar = $('#bBatch');
  if(!b || !bar) return;
  bar.hidden = !b.sel.size;
  if(!b.sel.size){ bar.innerHTML = ''; return; }
  const dis = b.batchBusy ? ' disabled' : '';
  const buttons = Object.keys(BATCH_KINDS).map(k =>
    `<button data-act="batchDo" data-k="${esc(k)}"${dis}>${esc(BATCH_KINDS[k].label)}</button>`).join('');
  bar.innerHTML = `<span class="count">${esc(COPY_BATCH_PICKED.replace('{n}', b.sel.size))}</span>${buttons}`
    + `<button class="ghost" data-act="batchClear"${dis}>${esc(COPY_BATCH_CLEAR)}</button>`;
}
// 只切勾选框和行的 class，不重画列表
function setPicked(b, indexes, on){
  indexes.forEach(i => {
    if(on) b.sel.add(i); else b.sel.delete(i);
    const box = document.getElementById('pk' + i), row = document.getElementById('r' + i);
    if(box) box.checked = on;
    if(row) row.classList.toggle('picked', on);
  });
}
function paintSelection(){ paintPickAll(); paintBatchBar(); }
function clearSelection(){
  const b = bs();
  if(!b) return;
  setPicked(b, [...b.sel], false);
  b.selAnchor = null;
  paintSelection();
}
function pruneSelection(){   // 重画列表后：只留下还看得到的段
  const b = bs();
  if(!b || !b.sel.size) return;
  const shown = new Set(b.shown);
  [...b.sel].forEach(i => { if(!shown.has(i)) b.sel.delete(i); });
  if(b.selAnchor !== null && !shown.has(b.selAnchor)) b.selAnchor = null;
  paintBatchBar();
}
// 鼠标点击后让焦点回到页面，接着按 ↓ / S 才有效；键盘空格（detail 为 0）要留着焦点，不然 Tab 走不下去
function blurAfterMouse(el, ev){ if(ev && ev.detail > 0 && el && typeof el.blur === 'function') el.blur(); }
function pickIdx(el, ev){
  const b = bs(), i = num(el.dataset.i);
  if(!b || !b.segs[i]) return;
  const on = !b.sel.has(i), pos = b.shown.indexOf(i);
  const from = b.selAnchor === null ? -1 : b.shown.indexOf(b.selAnchor);
  const span = ev && ev.shiftKey && from >= 0 && pos >= 0
    ? b.shown.slice(Math.min(from, pos), Math.max(from, pos) + 1) : [i];
  setPicked(b, span, on);
  b.selAnchor = i;
  blurAfterMouse(el, ev);
  paintSelection();
}
function pickAll(el, ev){
  const b = bs();
  if(!b || !b.shown.length) return;
  const all = pickState(b).checked;
  setPicked(b, b.shown, !all);
  b.selAnchor = null;
  blurAfterMouse(el, ev);
  paintSelection();
}

/* ---------------- 批量请求：乐观更新 → 排在所涉各段的队列之后发一个请求 → 成功合并 / 失败整批回滚 ---------------- */
function repaintBatch(){   // 逐行已画好，其余只画一次
  paintGroups(); renderFilters(); renderNote();
  renderClipPanel(pendingCount() ? localClip() : undefined);
  paintBatchBar();
}
function paintSegs(rows){ rows.forEach(({seg}) => { paintRow(seg); paintDensityCell(seg); }); }

async function sendBatch(b, rows, extra, entry){
  const qs = rows.map(({seg}) => queueOf(seg.id));
  qs.forEach(q => { q.n += 1; });
  if(entry) pushUndo(b, entry);
  rows.forEach(({seg, change}) => Object.assign(seg, change));
  paintSegs(rows); repaintBatch();
  const waits = qs.map(q => q.chain), epochs = qs.map(q => q.epoch);   // 同 applyMark：排队期间有一段失败过，这批作废
  const run = Promise.all(waits).then(async () => {
    if(qs.some((q, k) => q.epoch !== epochs[k])) return {skipped: true};
    try{ return {r: await postJson('/api/browse/batch', {project: b.project, items: rows.map(({seg, item}) => ({id: seg.id, ...item})), ...extra})}; }
    catch(e){ qs.forEach(q => { q.epoch += 1; }); return {err: e}; }   // 排在后面的单段请求作废
  });
  const tail = run.then(() => {});
  qs.forEach(q => { q.chain = tail; });
  const {r, err, skipped} = await run;
  qs.forEach(q => { q.n -= 1; });
  if(bs() !== b) return null;                       // 切项目了：不碰界面
  if(err || skipped) return failBatch(b, rows, err, entry);
  const fresh = new Map((r.segments || []).map(s => [s.id, s]));
  rows.forEach(({seg, change}) => {
    const src = fresh.get(seg.id);
    confirmMarks(b, seg, change, {segment: src});
    if(src && !queueOf(seg.id).n) MARK_FIELDS.forEach(k => { if(k in src) seg[k] = src[k]; });
  });
  if(r.clip_list) b.clip = r.clip_list;
  applyWizard(r.wizard);
  if(entry){ entry.done = true; entry.removed = Array.isArray(r.removed_shots) ? r.removed_shots : []; }
  paintSegs(rows); repaintBatch();
  return r;
}
function failBatch(b, rows, err, entry){
  rows.forEach(({seg}) => { Object.assign(seg, b.confirmed.get(seg.id)); dropPendingEntries(b, seg.id); });
  if(entry){ entry.dropped = true; b.undo = b.undo.filter(e => e !== entry); }
  paintSegs(rows); repaintBatch();
  if(err) toast(COPY_ROLLED_BACK + err.message, Math.max(TOAST_ERROR_MS, String(err.message).length * TOAST_MS_PER_CHAR));
  resyncBrowse();   // 非 2xx 也可能已经写了一部分：以服务端为准
  return null;
}

function batchSummary(kind, r, done, skipped){
  const notes = [BATCH_KINDS[kind].done.replace('{n}', done)];
  const cleared = Object.values(r.cleared || {});
  const count = name => cleared.filter(v => v === name).length;
  if(kind === 'add' && count('unusable')) notes.push(COPY_BATCH_CLEARED_UNUSABLE.replace('{n}', count('unusable')));
  if(kind === 'unusable' && count('must_keep')) notes.push(COPY_BATCH_CLEARED_LIST.replace('{n}', count('must_keep')));
  const gone = Array.isArray(r.removed_shots) ? r.removed_shots.length : 0;
  if(gone) notes.push(COPY_REMOVED_SHOTS.replace('{n}', gone));
  if(skipped) notes.push(COPY_BATCH_SKIPPED.replace('{n}', skipped));
  return notes.join('；');
}
async function applyBatch(kind){
  const b = bs(), spec = BATCH_KINDS[kind];
  if(!b || !spec || b.batchBusy || !b.sel.size) return false;
  b.batchBusy = true; paintBatchBar();
  try{
    while(pendingCount()){ await settleMarks(); if(bs() !== b) return false; }   // 单段在途的先落地
    if(!b.sel.size) return false;   // 等待期间切了筛选 / 取消了选择：什么都不做
    const picked = b.segs.filter(s => b.sel.has(s._i));
    const rows = picked.flatMap(seg => { const p = spec.plan(seg); return p ? [{seg, ...p}] : []; });
    if(!rows.length){ toast(COPY_BATCH_NOOP, TOAST_NOTE_MS); return false; }
    const entry = {batch: rows.map(({seg}) => ({id: seg.id, before: snap(seg)})), removed: [], done: false, dropped: false};
    const r = await sendBatch(b, rows, {}, entry);
    if(!r || bs() !== b) return false;
    toast(batchSummary(kind, r, rows.length, picked.length - rows.length), TOAST_NOTE_MS);
    const doneIdx = picked.map(s => s._i);   // 只清这一批的勾选，在途期间新勾的保留
    setPicked(b, doneIdx, false);
    if(doneIdx.includes(b.selAnchor)) b.selAnchor = null;
    settleAfterSave(r);
    return true;
  }finally{
    if(bs() === b){ b.batchBusy = false; paintSelection(); }
  }
}

/* ---------------- 整批撤销：用每段的 before 快照拼一个请求（镜头一并放回） ---------------- */
function sameMarks(a, c){ return !a.must_keep === !c.must_keep && !a.unusable === !c.unusable && !a.override === !c.override && a.level === c.level; }
async function undoBatch(b, entry){
  const byId = new Map(b.segs.map(s => [s.id, s]));
  const rows = entry.batch.flatMap(({id, before}) => {
    const seg = byId.get(id);
    if(!seg || sameMarks(snap(seg), before)) return [];
    const item = {id, must_keep: !!before.must_keep, unusable: !!before.unusable, level: before.override ? before.level : null};
    return [{seg, change: {...before}, item}];
  });
  if(!rows.length) return true;
  const restore = entry.removed && entry.removed.length ? {restore_shots: entry.removed} : {};
  const r = await sendBatch(b, rows, restore, null);
  if(!r) return false;
  if(restore.restore_shots) b.note = restoreNote(r);
  settleAfterSave(r);
  return true;
}

Object.assign(ACTIONS, {
  pickIdx: (el, ev) => pickIdx(el, ev), pickAll: (el, ev) => pickAll(el, ev),
  batchDo: el => applyBatch(el.dataset.k), batchClear: () => clearSelection(),
});
