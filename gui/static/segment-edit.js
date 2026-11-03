// 剪辑台主页 · ③ 编辑起止（弹窗）：一条时间轴两个手柄 + 两个 m:ss.s 输入框，边调边在小视频里看。
// 保存走 cliplist.js 的 applyMark（乐观更新 → 每段排队 → 合并服务端结果 → 撤销），本文件只管弹窗和校验。
// 校验与服务端一致：开始 ≥ 0、结束 − 开始 ≥ 0.5 秒、结束 ≤ 素材总长。选段之间允许重叠。

/* 界面文案：产品可直接改这里 */
const COPY_SE_TITLE = '编辑起止';
const COPY_SE_START = '开始';
const COPY_SE_END = '结束';
const COPY_SE_PLAY = '▶ 播放选段';
const COPY_SE_RESET = '恢复原始';
const COPY_SE_CANCEL = '取消';
const COPY_SE_SAVE = '保存';
const COPY_SE_SAVE_LIST = '保存并加到剪辑列表';
const COPY_SE_DUR = '时长 {d} 秒';
const COPY_SE_ORIGINAL = '原始 {a}–{b}';
const COPY_SE_HINT = '拖动两端的手柄，或直接输入时间（1:02.3 或 62.3）。手柄范围是原始起止前后各 {n} 秒；输入框可以超出这个范围。';
const COPY_SE_ERR_FORMAT = '时间格式不对，请写成 1:02.3 或直接写秒数';
const COPY_SE_ERR_SHORT = '选段至少 {n} 秒';
const COPY_SE_ERR_LONG = '结束时间不能超过素材总长 {d}';
const COPY_SE_STALE = '片段列表刚刷新，请重新打开编辑';

const SE_WINDOW_S = 10;          // 手柄范围：原始起止前后各 10 秒
const SE_MIN_LEN_S = 0.5;        // 与服务端一致的最短选段
const SE_STEP_S = 0.1;
const SE_END_PREVIEW_S = 1;      // 拖结束手柄：从结束前 1 秒播到结束
const SE_EPS_S = 1e-6;
const SE_BOUNDS_PATH = '/api/browse/bounds';

state.segEdit = null;   // 弹窗开着时：{b, seg, base, start, end, mat, bad, stopAt, lastT, timer}

/* ---------------- 时间格式 ---------------- */
function fmtMS(sec){   // 62.3 → 1:02.3；有百分位才显示两位（显示的就是发出去的，输入回去也能被接受）
  const t = Math.round(Math.max(0, num(sec)) * 100), frac = t % 10 ? 2 : 1;
  const s = ((t % 6000) / 100).toFixed(frac).padStart(frac + 3, '0');
  return `${Math.floor(t / 6000)}:${s}`;
}
function parseTime(text){   // 'm:ss.s' 或纯秒数；解析不了返回 NaN
  const t = String(text ?? '').trim().replace('：', ':');
  let m = /^(\d+(?:\.\d+)?)$/.exec(t);
  if(m) return Number(m[1]);
  m = /^(\d+):(\d{1,2}(?:\.\d+)?)$/.exec(t);
  return m && Number(m[2]) < 60 ? Number(m[1]) * 60 + Number(m[2]) : NaN;
}
const round2 = x => Math.round(x * 100) / 100;   // 与服务端一致：先取两位小数再校验 / 发送
const floor2 = x => Math.floor(x * 100 + SE_EPS_S) / 100;
const sameTime = (a, z) => Math.abs(a - z) < 0.005;
function baseOf(s){ return {start: num(s.base_start ?? s.start), end: num(s.base_end ?? s.end)}; }   // 旧数据没有 base_*：当作没改过
function boundsChipTitle(s){
  const b = baseOf(s);
  return COPY_SE_ORIGINAL.replace('{a}', fmtMS(b.start)).replace('{b}', fmtMS(b.end));
}
// 保存 / 撤销后只改这一行的时间、时长、「已调整」
function paintBoundsCells(s){
  const i = num(s._i), row = document.getElementById('r' + i);
  if(row) row.classList.toggle('edited', !!s.bounds_edited);
  const tc = document.getElementById('tc' + i), du = document.getElementById('du' + i), chip = document.getElementById('ed' + i);
  if(tc) tc.textContent = fmt(num(s.start));
  if(du) du.textContent = num(s.dur).toFixed(1) + 's';
  if(chip) chip.setAttribute('title', boundsChipTitle(s));
}

/* ---------------- 校验与范围 ---------------- */
function materialDuration(ed, video){   // 优先用服务端给的总长；没有就用视频自己报的；再没有就取最后一段的结尾
  const d = num(ed.b.data.material_duration), v = video ? num(video.duration) : 0;
  const last = Math.max(0, ...ed.b.segs.map(s => num(s.end)));
  return floor2(Math.max(d || v || last, ed.base.end, num(ed.seg.end)));   // 向下取到百分位：显示的上限输入回去一定被接受
}
function windowOf(ed){
  const tenth = Math.round(1 / SE_STEP_S);   // 两端对齐到 0.1 的格子：手柄上的值和显示 / 发送的值一致
  const lo = Math.floor(Math.max(0, ed.base.start - SE_WINDOW_S) * tenth + SE_EPS_S) / tenth;
  const hi = Math.ceil(Math.min(ed.mat, ed.base.end + SE_WINDOW_S) * tenth - SE_EPS_S) / tenth;   // 可能比总长多一格：拖到头时在 segEditSlider 里夹回总长
  return {lo, hi: Math.max(lo, hi)};
}
function editError(ed){   // 空串 = 可以保存
  if(ed.bad.start || ed.bad.end) return COPY_SE_ERR_FORMAT;
  if(ed.end - ed.start < SE_MIN_LEN_S - SE_EPS_S) return COPY_SE_ERR_SHORT.replace('{n}', SE_MIN_LEN_S);
  if(ed.end > ed.mat + SE_EPS_S) return COPY_SE_ERR_LONG.replace('{d}', fmtMS(ed.mat));
  return '';
}

/* ---------------- 弹窗 ---------------- */
function timeFieldHtml(which, label){
  return `<label>${esc(label)} <input type="text" inputmode="decimal" autocomplete="off" id="${which === 'start' ? 'seStartTxt' : 'seEndTxt'}" `
    + `data-input="segEditText" data-change="segEditCommit" data-which="${esc(which)}"></label>`;
}
function sliderHtml(which){
  return `<input type="range" id="${which === 'start' ? 'seStart' : 'seEnd'}" data-input="segEditSlider" data-change="segEditSliderDone" data-which="${esc(which)}" `
    + `aria-label="${esc(which === 'start' ? COPY_SE_START : COPY_SE_END)}">`;
}
function segEditHtml(ed){
  return `<div class="seg-edit"><video id="seVideo" controls preload="metadata"></video>`
    + `<p class="se-text">${esc(COPY_SE_ORIGINAL.replace('{a}', fmtMS(ed.base.start)).replace('{b}', fmtMS(ed.base.end)))}　${esc(segText(ed.seg).slice(0, NOW_PREVIEW_CHARS))}</p>`
    + `<div class="se-track"><div class="se-fill" id="seFill"></div>${sliderHtml('start')}${sliderHtml('end')}</div>`
    + `<div class="se-scale"><span id="seLo"></span><span id="seHi"></span></div>`
    + `<div class="se-fields">${timeFieldHtml('start', COPY_SE_START)}${timeFieldHtml('end', COPY_SE_END)}<span class="se-dur" id="seDur"></span></div>`
    + `<div class="se-err" id="seErr" role="alert"></div>`
    + `<p class="hint">${esc(COPY_SE_HINT.replace('{n}', SE_WINDOW_S))}</p>`
    + `<div class="job-actions"><button class="ghost" data-act="segEditReset">${esc(COPY_SE_RESET)}</button>`
    + `<button class="ghost" id="sePlay" data-act="segEditPlay">${esc(COPY_SE_PLAY)}</button><span class="se-gap"></span>`
    + `<button class="ghost" data-act="closeModal">${esc(COPY_SE_CANCEL)}</button>`
    + `<button class="primary" id="seSave" data-act="segEditSave">${esc(COPY_SE_SAVE)}</button>`
    + `<button class="primary" id="seSaveList" data-act="segEditSaveList">${esc(COPY_SE_SAVE_LIST)}</button></div></div>`;
}
function setField(id, v){ const e = $(id); if(e) e.value = v; }
function paintSliders(ed, win){
  [['#seStart', ed.start], ['#seEnd', ed.end]].forEach(([id, v]) => {
    const r = $(id);
    if(!r) return;
    r.min = win.lo; r.max = win.hi; r.step = SE_STEP_S;
    r.value = Math.min(win.hi, Math.max(win.lo, v));
    r.setAttribute('aria-valuetext', fmtMS(v));
  });
  const span = win.hi - win.lo || 1, pct = v => Math.min(100, Math.max(0, (v - win.lo) / span * 100));
  const fill = $('#seFill');
  if(fill){ fill.style.left = pct(ed.start).toFixed(2) + '%'; fill.style.width = Math.max(0, pct(ed.end) - pct(ed.start)).toFixed(2) + '%'; }
  const lo = $('#seLo'), hi = $('#seHi');
  if(lo) lo.textContent = fmtMS(win.lo);
  if(hi) hi.textContent = fmtMS(win.hi);
}
// skip：正在输入的那个框不重写（不然边打边被改格式）
function paintEdit(ed, skip){
  if(state.segEdit !== ed) return;
  paintSliders(ed, windowOf(ed));
  if(skip !== 'start' && !ed.bad.start) setField('#seStartTxt', fmtMS(ed.start));
  if(skip !== 'end' && !ed.bad.end) setField('#seEndTxt', fmtMS(ed.end));
  const err = editError(ed), dur = $('#seDur'), msg = $('#seErr');
  if(dur) dur.textContent = COPY_SE_DUR.replace('{d}', Math.max(0, ed.end - ed.start).toFixed(1));
  if(msg) msg.textContent = err;
  ['#seSave', '#seSaveList', '#sePlay'].forEach(id => { const e = $(id); if(e) e.disabled = !!err; });
}

function openSegEdit(seg){
  const b = bs();
  if(!b || !seg || state.view !== 'browse' || modalOpen()) return false;
  const pv = $('#bPv');
  if(pv && !pv.paused) pv.pause();   // 主播放器让出声音
  const ed = {b, seg, base: baseOf(seg), start: num(seg.start), end: num(seg.end), mat: 0, bad: {}, stopAt: null, lastT: null, timer: null};
  ed.mat = materialDuration(ed, null);
  state.segEdit = ed;
  showModal(COPY_SE_TITLE, segEditHtml(ed));
  state.modalKind = 'segedit';
  wireVideo(ed);
  paintEdit(ed);
  const first = $('#seStartTxt');
  if(first) first.focus();   // 键盘用户直接能改开始时间
  return true;
}
function wireVideo(ed){
  const v = $('#seVideo');
  if(!v) return;
  v.addEventListener('loadedmetadata', () => {
    if(state.segEdit !== ed) return;
    ed.mat = materialDuration(ed, v);   // 服务端没给总长时，用视频自己报的
    v.currentTime = ed.start;
    paintEdit(ed);
  });
  v.addEventListener('seeking', () => { ed.lastT = null; });   // 手动拖进度条不算「自然播到出点」
  v.addEventListener('ended', () => stopEditPoll(ed));
  v.src = '/media/' + encodeURIComponent(ed.b.project) + '/proxy';
  v.currentTime = ed.start;
}
// 关弹窗（含被别的弹窗顶掉）：停视频、释放视频、清计时器
function segEditClosed(){
  const ed = state.segEdit;
  if(!ed) return;
  state.segEdit = null;
  stopEditPoll(ed);
  const v = $('#seVideo');
  if(!v) return;
  v.pause();
  v.removeAttribute('src');
  if(typeof v.load === 'function') v.load();
}

/* ---------------- 播放：只播到出点就停 ---------------- */
function startEditPoll(ed){ if(ed.timer === null) ed.timer = setInterval(() => pollEdit(ed), STOP_POLL_MS); }
function stopEditPoll(ed){ if(ed.timer !== null){ clearInterval(ed.timer); ed.timer = null; } }
function pollEdit(ed){
  const v = $('#seVideo');
  if(state.segEdit !== ed || !v) return stopEditPoll(ed);
  const t = num(v.currentTime);
  if(ed.stopAt !== null && ed.lastT !== null && ed.lastT < ed.stopAt && t >= ed.stopAt){ v.pause(); ed.stopAt = null; stopEditPoll(ed); }
  ed.lastT = t;
}
function seekEdit(ed, t){
  const v = $('#seVideo');
  if(!v) return;
  ed.stopAt = null; ed.lastT = null;
  v.pause();
  v.currentTime = Math.max(0, t);
}
function playEdit(ed, from, to){
  const v = $('#seVideo');
  if(!v) return;
  v.currentTime = Math.max(0, from);
  ed.stopAt = to; ed.lastT = null;
  startEditPoll(ed);
  playQuietly(v);
}

/* ---------------- 输入 ---------------- */
function segEditSlider(el){   // 拖动中：只定位画面（end 手柄松手后才播）
  const ed = state.segEdit;
  if(!ed) return;
  const v = round2(Math.min(num(el.value), ed.mat));   // 手柄最右可能比总长多一格
  if(el.dataset.which === 'start'){ ed.start = round2(Math.max(0, Math.min(v, ed.end - SE_MIN_LEN_S))); ed.bad.start = false; }
  else{ ed.end = round2(Math.min(ed.mat, Math.max(v, ed.start + SE_MIN_LEN_S))); ed.bad.end = false; }
  paintEdit(ed);
  if(editError(ed)) return;
  seekEdit(ed, el.dataset.which === 'start' ? ed.start : endPreviewFrom(ed));
}
function endPreviewFrom(ed){ return Math.max(ed.start, ed.end - SE_END_PREVIEW_S); }
function segEditSliderDone(el){   // 松手（change）：结束手柄从结束前 1 秒播到结束
  const ed = state.segEdit;
  if(ed && el.dataset.which === 'end' && !editError(ed)) playEdit(ed, endPreviewFrom(ed), ed.end);
}
function segEditText(el){   // 边打边校验（不改写正在打的框）
  const ed = state.segEdit;
  if(!ed) return;
  const which = el.dataset.which, t = parseTime(el.value);
  ed.bad[which] = Number.isNaN(t);
  if(!ed.bad[which]) ed[which] = round2(t);
  paintEdit(ed, which);
}
function segEditCommit(el){   // 打完（失焦 / 回车）：整理成 m:ss.s，并把视频定到那里
  const ed = state.segEdit;
  if(!ed) return;
  const which = el.dataset.which;
  if(ed.bad[which]) return;
  el.value = fmtMS(ed[which]);
  paintEdit(ed);
  if(!editError(ed)) seekEdit(ed, which === 'start' ? ed.start : endPreviewFrom(ed));
}
function segEditPlay(){
  const ed = state.segEdit;
  if(ed && !editError(ed)) playEdit(ed, ed.start, ed.end);
}
function segEditReset(){
  const ed = state.segEdit;
  if(!ed) return;
  ed.start = ed.base.start; ed.end = ed.base.end; ed.bad = {};
  paintEdit(ed);
  seekEdit(ed, ed.start);
}

/* ---------------- 保存 ---------------- */
// 弹窗先关（乐观更新，和标记一样）；回到原始值时发 null（服务端清掉调整）；没变就不发请求
function segEditFresh(ed){ return bs() === ed.b && state.view === 'browse' && state.project === ed.b.project && ed.b.segs.includes(ed.seg); }
// 浏览状态被换掉（切项目 / 换步骤 / 重新读取）：弹窗里的段已经不是页面上那一段了，直接关（app.js 的 renderView、step-browse.js 的 reset / enter 调用）
function closeStaleSegEdit(){ if(state.segEdit && !segEditFresh(state.segEdit)) closeModal(); }
function segEditSave(must){
  const ed = state.segEdit;
  if(!ed || editError(ed)) return false;
  if(!segEditFresh(ed)){ closeModal(); toast(COPY_SE_STALE, TOAST_NOTE_MS); return false; }
  const {seg, base} = ed, start = round2(ed.start), end = round2(ed.end);
  const atBase = sameTime(start, base.start) && sameTime(end, base.end);
  const unchanged = sameTime(start, num(seg.start)) && sameTime(end, num(seg.end));
  closeModal();
  if(unchanged) return must && !seg.must_keep ? toggleList(seg) : false;
  const to = atBase ? base : {start, end};
  const change = {start: to.start, end: to.end, dur: round2(to.end - to.start), bounds_edited: !atBase,
                  ...(must ? {must_keep: true, unusable: false} : {})};
  const body = {...(atBase ? {start: null, end: null} : to), ...(must ? {must: true} : {})};
  return applyMark(seg, change, 'bounds', SE_BOUNDS_PATH, body);
}
// 撤销（cliplist.js 的 restoreSeg 调用）：起止不同就把之前的起止 / null 发回去
function restoreBounds(seg, to, opts){
  if(!('start' in to) || to.start === undefined) return true;
  const same = sameTime(num(to.start), num(seg.start)) && sameTime(num(to.end), num(seg.end)) && !to.bounds_edited === !seg.bounds_edited;
  if(same) return true;
  const change = {start: to.start, end: to.end, dur: to.dur, bounds_edited: !!to.bounds_edited};
  return applyMark(seg, change, 'bounds', SE_BOUNDS_PATH, to.bounds_edited ? {start: to.start, end: to.end} : {start: null, end: null}, opts);
}

Object.assign(ACTIONS, {
  segEditSlider: el => segEditSlider(el), segEditSliderDone: el => segEditSliderDone(el), segEditText: el => segEditText(el), segEditCommit: el => segEditCommit(el),
  segEditPlay: () => segEditPlay(), segEditReset: () => segEditReset(),
  segEditSave: () => segEditSave(false), segEditSaveList: () => segEditSave(true),
});
