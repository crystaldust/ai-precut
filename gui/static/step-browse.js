// 剪辑台主页 · ③ 看素材（M13c）：摘要卡、分布条、片段列表（按时间 / 按话题 + 七个筛选）、播放器。
// 标记（S / A / D / X / Z）与剪辑列表面板在 cliplist.js；快捷键在 shortcuts.js。
// 页面骨架是固定的（viewBrowse 恒返回同一段 HTML，轮询刷新不会重画它）；内容由 enterBrowse 加载后分块填进去。
// 勾选与批量操作在 batch-select.js。
// 140 段要滚得动：筛选 / 换当前段 / 标记只切 class 和文字，不重画整张列表（只有切视图 / 切筛选才重画列表）。

/* 界面文案：产品可直接改这里 */
const COPY_BROWSE_LOADING = '加载中…';
const COPY_BROWSE_EMPTY = '还没有分析结果';
const COPY_NO_SUMMARY = '（暂无摘要）';
const COPY_FALLBACK_SUMMARY = '（兜底摘要）';
const COPY_WARN_TITLE = '需要你留意';
const COPY_KEY_POINTS = '关键信息';
const COPY_SPEAKERS = '说话人';
const COPY_VIEW_TIME = '按时间';
const COPY_VIEW_TOPIC = '按话题';
const COPY_ADD_LIST = '＋ 剪辑列表';
const COPY_IN_LIST = '✓ 剪辑列表';
const COPY_TAG_IN_LIST = '已在剪辑列表';
const COPY_TAG_UNUSABLE = '不可用';
const COPY_TAG_USED = '已用';
const COPY_MARK_UNUSABLE = '标为不可用';
const COPY_NOW_HINT = '按 ↓ 选一段，空格播放，S 放入剪辑列表';
const COPY_GROUP_STATS = '可用 {u} · 待定 {p} · 废片 {w} · 可用时长 {d}';
const COPY_NO_TOPIC = '未归类';
const COPY_NOT_IN_FILTER = '当前这一段已不在「{f}」里（切换筛选后会隐藏）';

const FILTERS = [['all', '全部'], ['pending', '待定'], ['usable', '可用'], ['waste', '废片'],
                 ['list', '剪辑列表'], ['unusable', '不可用'], ['unused', '未用']];
// 待定 / 可用 / 废片不含不可用的段；未用 = 不在当前分镜表里（KI-99：没有手动分镜表时看 AI 选段）
const FILTER_TESTS = {
  all: () => true, pending: s => s.level === 2 && !s.unusable, usable: s => s.level === 3 && !s.unusable,
  waste: s => s.level === 1 && !s.unusable, list: s => !!s.must_keep, unusable: s => !!s.unusable, unused: s => !s.inCut,
};
const VISUAL_TAGS = {soft: '虚焦', shaky: '抖动', dark: '过暗', still: '静止'};
const PAD_S = 0.3;                // 试听前后各多放 0.3 秒（D15）
const KEYPOINT_LISTEN_S = 4;      // 点关键信息试听的秒数
const TEXT_PREVIEW_CHARS = 60;
const NOW_PREVIEW_CHARS = 40;
const STOP_POLL_MS = 40;         // 播放中每 40ms 看一次有没有跨过出点

let browseGen = 0;   // 每次进入 / 重置 +1：过期的加载结果一律丢掉（同 stateSeq 思路）
const BROWSE_SKELETON = `<div class="browse">
  <div class="b-top"><div class="card b-summary" id="bSummary"></div><div class="b-density" id="bDensity"></div></div>
  <div class="b-main">
    <section class="b-left"><div class="b-bar" id="bFilters"></div><div class="b-note" id="bNote" role="status"></div><div class="b-list" id="bList"></div>
      <div class="b-batch" id="bBatch" hidden></div></section>
    <aside class="b-right"><video id="bPv" controls preload="metadata"></video><div class="b-now" id="bNow"></div>
      <div class="b-panel" id="bPanel"></div></aside>
  </div></div>`;
function viewBrowse(){ return BROWSE_SKELETON; }

function resetBrowse(){ browseGen += 1; state.browse = null; resetMarks(); unloadPlayer(); }
// 切项目 / 项目没有分析结果：停止并卸掉播放器，不让上一个项目的小样继续播
function unloadPlayer(){
  stopStopPoll();
  const pv = $('#bPv');
  if(!pv) return;
  if(!pv.paused) pv.pause();
  pv.removeAttribute('src');
  if(typeof pv.load === 'function') pv.load();
}
function wirePlayer(pv){   // 只接一次：重复进入 ③ 时骨架没换，元素还是同一个
  if(pv.bWired) return;
  pv.bWired = true;
  pv.addEventListener('play', startStopPoll);
  pv.addEventListener('pause', stopStopPoll);
  pv.addEventListener('ended', stopStopPoll);
  pv.addEventListener('seeking', () => { const b = bs(); if(b) b.lastT = null; });   // 手动拖动不算「自然播到出点」
}

async function enterBrowse(){
  const project = state.project;
  if(!project) return;
  const gen = ++browseGen;
  state.browse = null;
  $('#bList').innerHTML = `<div class="empty">${esc(COPY_BROWSE_LOADING)}</div>`;
  const c = crit();   // ④ 里还在路上的档位改动先落地，再读
  if(c && c.levelChain) await c.levelChain;
  if(gen !== browseGen) return;
  let data;
  try{ data = await api('/api/browse?project=' + encodeURIComponent(project)); }
  catch(e){
    if(gen === browseGen){ $('#bList').innerHTML = `<div class="empty">${esc(e.message || COPY_BROWSE_EMPTY)}</div>`; unloadPlayer(); }
    return;
  }
  if(gen !== browseGen || project !== state.project || state.view !== 'browse') return;
  const segs = (data.segments || []).map((s, i) => ({...s, _i: i}));
  state.browse = {gen, project, data, segs, clip: data.clip_list, view: 'time', filter: 'all', targetEditing: false,
                  sel: new Set(), selAnchor: null, batchBusy: false, cur: null, stopAt: null, cueEnd: null, lastT: null, shown: [], undo: [], note: null, groups: [],
                  confirmed: new Map(segs.map(s => [s.id, snap(s)]))};
  const pv = $('#bPv');
  pv.src = '/media/' + encodeURIComponent(project) + '/proxy';
  wirePlayer(pv);
  renderSummary(); renderDensity(); renderList(); renderFilters(); renderNow(); renderClipPanel(); renderNote(); paintBatchBar();
}

/* ---------------- 摘要卡、分布条 ---------------- */
function renderSummary(){
  const b = bs(), sum = b.data.summary || {};
  const warns = Array.isArray(b.data.warnings) ? b.data.warnings : [];
  const points = (sum.key_points || []).map(p =>
    `<div class="kp" data-act="jumpAt" data-t="${num(p.at)}"><b>${fmt(num(p.at))}</b>${esc(p.text)}`
    + `<span class="why"> · ${esc(p.why || '')}</span></div>`).join('') || '<div class="kp">—</div>';
  const cast = (b.data.speakers || []).map(c => `<span>${esc(c.name)} · ${esc(fmtLong(num(c.seconds)))}</span>`).join('');
  $('#bSummary').innerHTML =
    (warns.length ? `<div class="b-warn"><b>${esc(COPY_WARN_TITLE)}</b><ul>${warns.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : '')
    + `<p>${esc(sum.summary || COPY_NO_SUMMARY)}${sum.fallback ? `<small> ${esc(COPY_FALLBACK_SUMMARY)}</small>` : ''}</p>`
    + `<h4>${esc(COPY_KEY_POINTS)}</h4>${points}`
    + (cast ? `<h4>${esc(COPY_SPEAKERS)}</h4><div class="cast">${cast}</div>` : '');
}
function densityClass(s){ return `d lv${num(s.level)}${s.unusable ? ' unusable' : ''}`; }
function paintDensityCell(s){ const d = document.getElementById('d' + num(s._i)); if(d) d.className = densityClass(s); }
function renderDensity(){
  const b = bs(), last = b.segs.length ? num(b.segs[b.segs.length - 1].end) : 0;
  const total = num(b.data.material_duration) || last || 1;
  $('#bDensity').innerHTML = b.segs.map(s =>
    `<div class="${densityClass(s)}" id="d${num(s._i)}" style="width:${(num(s.dur) / total * 100).toFixed(3)}%" `
    + `data-act="jumpSeg" data-i="${num(s._i)}" title="${esc(fmt(num(s.start)) + ' ' + (LEVEL_NAMES[s.level] || '') + ' · ' + (s.topic || ''))}"></div>`).join('');
}

/* ---------------- 筛选条与列表 ---------------- */
function renderFilters(){
  const b = bs();
  const view = [['time', COPY_VIEW_TIME], ['topic', COPY_VIEW_TOPIC]].map(([k, label]) =>
    `<button data-act="setView" data-v="${esc(k)}"${b.view === k ? ' class="on"' : ''}>${esc(label)}</button>`).join('');
  const chips = FILTERS.map(([k, label]) =>
    `<button data-act="setFilter" data-v="${esc(k)}"${b.filter === k ? ' class="on"' : ''}>`
    + `${esc(label)} ${b.segs.filter(FILTER_TESTS[k]).length}</button>`).join('');
  $('#bFilters').innerHTML = pickAllHtml() + `<span class="view-toggle">${view}</span><span class="chips">${chips}</span>`;
  paintPickAll();
}
function rowHtml(s){
  const i = num(s._i), b = bs(), lv = num(s.level);
  const cls = ['row', b && b.cur === i ? 'current' : '', s.must_keep ? 'in-list' : '', s.unusable ? 'unusable' : '', b && b.sel.has(i) ? 'picked' : ''].filter(Boolean).join(' ');
  const flags = (s.visual_flags || []).filter(f => VISUAL_TAGS[f]).map(f => `<span class="vt">${esc(VISUAL_TAGS[f])}</span>`).join('');
  return `<div class="${cls}" id="r${i}" data-act="jumpSeg" data-i="${num(i)}">${pickHtml(s)}`
    + `<div class="tc">${fmt(num(s.start))}</div>`
    + `<div class="lv lv${lv}" id="lv${i}">${esc(LEVEL_NAMES[lv] || '')}</div>`
    + `<div class="cat" title="${esc(s.topic || '')}">${esc(s.topic || '—')}</div>`
    + `<div class="sum">${esc(String(s.text ?? '').slice(0, TEXT_PREVIEW_CHARS))}`
    + `<span class="tag-list">${esc(COPY_TAG_IN_LIST)}</span><span class="tag-un">${esc(COPY_TAG_UNUSABLE)}</span>`
    + (s.inCut ? `<span class="used">${esc(COPY_TAG_USED)}</span>` : '')
    + `<small><span id="rs${i}">${esc(s.level_reason || '')}</span>${flags}</small></div>`
    + `<div class="dur">${num(s.dur).toFixed(1)}s</div>`
    + `<button class="add" id="t${i}" data-act="toggleListIdx" data-i="${num(i)}">${esc(s.must_keep ? COPY_IN_LIST : COPY_ADD_LIST)}</button>`
    + `<button class="ban" data-act="markUnusableIdx" data-i="${num(i)}" title="${esc(COPY_MARK_UNUSABLE)}" aria-label="${esc(COPY_MARK_UNUSABLE)}">⊘</button></div>`;
}
function groupStats(all){
  const live = all.filter(s => !s.unusable), count = lv => live.filter(s => s.level === lv).length;
  const usableSec = live.filter(s => s.level === 3).reduce((n, s) => n + num(s.dur), 0);
  return COPY_GROUP_STATS.replace('{u}', count(3)).replace('{p}', count(2)).replace('{w}', count(1))
    .replace('{d}', fmtLong(Math.round(usableSec)));
}
function segsOfTopic(name){ return bs().segs.filter(s => (s.topic || COPY_NO_TOPIC) === name); }
function groupHtml(name, k, rows){
  return `<div class="group">${esc(name)}<span id="g${num(k)}">${esc(groupStats(segsOfTopic(name)))}</span></div>` + rows.map(rowHtml).join('');
}
function paintGroups(){   // 标记后只更新组头的数字
  const b = bs();
  (b.groups || []).forEach((name, k) => { const g = document.getElementById('g' + k); if(g) g.textContent = groupStats(segsOfTopic(name)); });
}
function renderList(){
  const b = bs(), list = $('#bList'), keep = list.scrollTop;
  const items = b.segs.filter(FILTER_TESTS[b.filter]);
  if(b.view === 'time'){
    list.innerHTML = items.map(rowHtml).join('');
    b.groups = [];
    b.shown = items.map(s => s._i);
  }else{
    const groups = new Map();
    items.forEach(s => { const k = s.topic || COPY_NO_TOPIC; groups.set(k, [...(groups.get(k) || []), s]); });
    b.groups = [...groups.keys()];
    list.innerHTML = [...groups].map(([name, rows], k) => groupHtml(name, k, rows)).join('');
    b.shown = [...groups.values()].flat().map(s => s._i);
  }
  list.scrollTop = keep;
  pruneSelection(); paintPickAll();
}
function setView(v){
  const b = bs();
  if(!b || !['time', 'topic'].includes(v)) return;
  b.view = v; clearSelection(); renderList(); renderFilters();
}
function setFilter(v){
  const b = bs();
  if(!b || !FILTER_TESTS[v]) return;
  b.filter = v; clearSelection(); renderList(); renderFilters(); renderNote();
}
// 当前段被标记后可能不再符合筛选：行不会消失（不重画列表），在列表上方轻轻提一句
function renderNote(){
  const b = bs(), s = curSeg(), note = $('#bNote');
  if(!b || !note) return;
  const label = (FILTERS.find(f => f[0] === b.filter) || [])[1];
  note.textContent = s && !FILTER_TESTS[b.filter](s) ? COPY_NOT_IN_FILTER.replace('{f}', label) : '';
}
// 镜头有变动 / 响应没拼出来之后，静默重读一遍：原地更新（在途的标记不覆盖），不重建页面状态
async function resyncBrowse(){
  const b = bs();
  if(!b) return;
  let data;
  try{ data = await api('/api/browse?project=' + encodeURIComponent(b.project)); }catch(e){ return; }
  if(bs() !== b) return;
  const fresh = new Map((data.segments || []).map(s => [s.id, s]));
  if(fresh.size !== b.segs.length || !b.segs.every(s => fresh.has(s.id))) return enterBrowse();
  b.data = data;
  b.segs.forEach(s => {
    const f = fresh.get(s.id), busy = (markQueues.get(s.id) || {}).n;
    if(busy){ s.inCut = f.inCut; return; }
    Object.assign(s, f);
    b.confirmed.set(s.id, snap(s));
  });
  b.targetOverride = null;   // 重读成功：以服务端为准（别处改过也一样），不再需要本地覆盖
  if(!pendingCount()) adoptClip(b, data.clip_list);
  renderDensity(); renderList(); renderFilters(); renderNote(); renderClipPanel(pendingCount() ? localClip() : undefined);
}
// 标记之后只改这一行：class、按钮字、档位标签、依据——不重画列表
function paintRow(s){
  const i = num(s._i), row = document.getElementById('r' + i);
  if(!row) return;
  row.classList.toggle('in-list', !!s.must_keep);
  row.classList.toggle('unusable', !!s.unusable);
  const add = document.getElementById('t' + i);
  if(add) add.textContent = s.must_keep ? COPY_IN_LIST : COPY_ADD_LIST;
  const lv = document.getElementById('lv' + i);
  if(lv){ lv.textContent = LEVEL_NAMES[s.level] || ''; lv.className = 'lv lv' + num(s.level); }
  const why = document.getElementById('rs' + i);
  if(why) why.textContent = s.level_reason || '';
}

/* ---------------- 当前段与播放器 ---------------- */
function renderNow(){
  const s = curSeg(), now = $('#bNow');
  now.innerHTML = s
    ? `<b>${esc(fmt(num(s.start)))}–${esc(fmt(num(s.end)))}</b>　${esc(String(s.text ?? '').slice(0, NOW_PREVIEW_CHARS))}`
      + `<br><span class="why">${esc(s.level_reason || '')}</span>`
    : `<span class="why">${esc(COPY_NOW_HINT)}</span>`;
}
function setCurrent(s){   // 只换焦点框，不动播放器
  const b = bs(), prev = b.cur;
  b.cur = s._i;
  if(prev !== null && prev !== s._i){ const old = document.getElementById('r' + prev); if(old) old.classList.remove('current'); }
  const row = document.getElementById('r' + s._i);
  if(row){ row.classList.add('current'); if(typeof row.scrollIntoView === 'function') row.scrollIntoView({block: 'nearest'}); }
  renderNow(); renderNote();
}
function cueSeg(s){   // 入点 −0.3 → 出点 +0.3
  const b = bs(), pv = $('#bPv');
  pv.currentTime = Math.max(0, num(s.start) - PAD_S);
  b.stopAt = b.cueEnd = num(s.end) + PAD_S;
  b.lastT = null;
}
function jumpSeg(i){
  const b = bs(), s = b && b.segs[i];
  if(!s) return;
  setCurrent(s); cueSeg(s); playQuietly($('#bPv'));
}
function jumpAt(t){   // 点关键信息：从该时间码试听几秒，不改当前段，也不动「当前段的播放范围」
  const b = bs(), pv = $('#bPv');
  if(!b) return;
  pv.currentTime = Math.max(0, t - PAD_S);
  b.stopAt = t + KEYPOINT_LISTEN_S;
  b.lastT = null;
  playQuietly(pv);
}
function moveCur(delta){
  const b = bs();
  if(!b || !b.shown.length) return;
  const pos = b.shown.indexOf(b.cur);
  const next = pos < 0 ? 0 : Math.min(b.shown.length - 1, Math.max(0, pos + delta));
  const s = b.segs[b.shown[next]];
  setCurrent(s); cueSeg(s);
}
function togglePlay(){
  const b = bs(), pv = $('#bPv'), s = curSeg();
  if(!pv.paused){ pv.pause(); return; }
  if(s && b.cueEnd !== null && (pv.currentTime < num(s.start) - PAD_S || pv.currentTime >= b.cueEnd)) cueSeg(s);
  playQuietly(pv);
}
// 播放中短间隔检查：只在「自然播放跨过出点」时停；用户手动拖到出点之后不会被拦下
let stopTimer = null;
function startStopPoll(){ if(stopTimer === null) stopTimer = setInterval(pollStop, STOP_POLL_MS); }
function stopStopPoll(){ if(stopTimer !== null){ clearInterval(stopTimer); stopTimer = null; } }
function pollStop(){
  const b = bs(), pv = $('#bPv');
  if(!b || !pv) return stopStopPoll();
  const t = pv.currentTime;
  if(b.stopAt !== null && b.lastT !== null && b.lastT < b.stopAt && t >= b.stopAt){ pv.pause(); b.stopAt = null; }
  b.lastT = t;
}

Object.assign(ACTIONS, {
  setView: el => setView(el.dataset.v), setFilter: el => setFilter(el.dataset.v),
  jumpSeg: el => jumpSeg(num(el.dataset.i)), jumpAt: el => jumpAt(num(el.dataset.t)),
});
