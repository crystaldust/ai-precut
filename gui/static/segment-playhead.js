// ③ 编辑起止弹窗的播放头（segment-edit.js 之后加载，共用全局作用域，所以这里的名字都以 se / SE_ 开头）。
// 白线 + 时间气泡 + 「播放头」输入框：点 / 拖时间轴移动，空格播放 / 暂停，← → 微调；不存盘，每次打开从原始开始时间起。
// 手柄拖动与播放头互不影响：拖手柄时画面预览手柄那一帧，松手回到播放头；拖到播放头附近（SE_SNAP_PX）会吸附上去。
// 手柄、播放头、选中条、点击共用 seTimeToPx / sePxToTime 一套坐标（手柄中心走 [6, 宽-6]）。
// 按手柄时 WebKit 会把焦点挪到轨道：轨道 focus 监听在 pointerDrag 期间把焦点还给手柄，方向键才继续动手柄。

/* 界面文案：产品可直接改这里 */
const COPY_SE_PLAYHEAD = '播放头';

const SE_SNAP_PX = 8;            // 拖手柄靠近播放头多少像素内吸附
const SE_THUMB_PX = 12;          // 原生手柄宽度（WebKit）：手柄中心只在 [6, 宽-6] 上走
const SE_PX_EPS = 1e-6;
const SE_HANDLES = [['start', 'seStart'], ['end', 'seEnd']];

/* ---------------- 坐标：手柄、播放头、选中条、点击共用一套 ---------------- */
const seFrac = (win, v) => Math.min(1, Math.max(0, (v - win.lo) / (win.hi - win.lo || 1)));
const seTrackSpan = width => Math.max(1, width - SE_THUMB_PX);
const seTimeToPx = (win, width, v) => SE_THUMB_PX / 2 + seFrac(win, v) * seTrackSpan(width);
const sePxToTime = (win, width, px) => win.lo + (px - SE_THUMB_PX / 2) / seTrackSpan(width) * (win.hi - win.lo);
const seLeftCss = f => `calc(${SE_THUMB_PX / 2}px + (100% - ${SE_THUMB_PX}px) * ${f.toFixed(4)})`;   // 与上面的 px 公式一致，不用量宽度
const seWidthCss = f => `calc((100% - ${SE_THUMB_PX}px) * ${f.toFixed(4)})`;
const seTrackWidth = () => $('.se-track').getBoundingClientRect().width;

/* ---------------- 页面结构 ---------------- */
function sePlayheadHtml(){
  return `<div class="se-ph" id="sePh"><span class="se-ph-chip" id="sePhChip"></span></div>`;
}
function sePlayheadFieldHtml(){
  return `<label>${esc(COPY_SE_PLAYHEAD)} <input type="text" inputmode="decimal" autocomplete="off" id="sePhTxt" `
    + `data-input="segPlayheadText" data-change="segPlayheadCommit"></label>`
    + `<span class="se-err se-ph-err" id="sePhErr" aria-live="polite"></span>`;
}
function seChipShift(linePx, chipW, trackW){   // 气泡相对播放头线的左偏移：居中，但不超出时间轴两端
  return Math.min(Math.max(-chipW / 2, -linePx), trackW - linePx - chipW);
}
function sePaintPlayhead(ed){
  const win = windowOf(ed), line = $('#sePh'), chip = $('#sePhChip'), err = $('#sePhErr'), track = $('.se-track');
  line.style.left = seLeftCss(seFrac(win, ed.playhead));
  line.classList.toggle('snapped', !!ed.snapped && sameTime(ed[ed.snapped], ed.playhead));
  chip.textContent = fmtMS(ed.playhead);
  const w = seTrackWidth();
  chip.style.left = (w > SE_THUMB_PX ? seChipShift(seTimeToPx(win, w, ed.playhead), chip.offsetWidth, w) : -chip.offsetWidth / 2) + 'px';
  if(!ed.phEditing && !ed.phBad) setField('#sePhTxt', fmtMS(ed.playhead));   // 正在打字的框不重写
  err.textContent = ed.phBad ? COPY_SE_ERR_FORMAT : '';   // 单独一块：播放头写错不影响保存
  [['min', win.lo], ['max', win.hi], ['now', ed.playhead]].forEach(([k, v]) => track.setAttribute('aria-value' + k, v));
  track.setAttribute('aria-valuetext', fmtMS(ed.playhead));
}

/* ---------------- 播放头位置 ---------------- */
function seClampPh(ed, t){
  const win = windowOf(ed);
  return Math.min(win.hi, Math.max(win.lo, round2(num(t))));
}
// 任何方式动了播放头都清掉「格式不对」并把框重写成格式化的值；唯一例外：视频跟随时用户还在框里打字
function seMovePlayhead(ed, t, follow){
  ed.playhead = seClampPh(ed, t);
  if(!follow) ed.phEditing = false;
  if(!ed.phEditing) ed.phBad = false;
  sePaintPlayhead(ed);
}
function seSetPlayhead(ed, t){    // 动播放头，并让视频定位到那里
  seMovePlayhead(ed, t);
  seekEdit(ed, ed.playhead);
}
function seFollow(ed, v){   // 视频在播时播放头跟着走；拖手柄 / 拖播放头期间不跟
  if(state.segEdit !== ed || ed.dragging || ed.scrubbing || v.paused !== false) return;
  seMovePlayhead(ed, v.currentTime, true);
}
function seWirePlayhead(ed){
  const v = $('#seVideo'), track = $('.se-track'), stop = () => { ed.scrubbing = false; };
  v.addEventListener('timeupdate', () => seFollow(ed, v));
  $('#sePhTxt').addEventListener('blur', () => { ed.phEditing = false; });
  track.addEventListener('focus', () => {   // 按手柄时 WebKit 的 mousedown 会把焦点挪到轨道：还给手柄；Tab / 点轨道才选播放头
    const h = ed.pointerDrag && SE_HANDLES.find(x => x[0] === ed.keyHandle);
    if(h) $('#' + h[1]).focus({preventScroll: true}); else ed.keyHandle = 'playhead';
  });
  track.addEventListener('pointerdown', e => seTrackDown(ed, track, e));
  track.addEventListener('pointermove', e => {
    if(!ed.scrubbing) return;
    if(e.buttons === 0) stop();   // 松手事件丢了：不再跟着鼠标跑
    else seScrubTo(ed, track, e);
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(t => track.addEventListener(t, stop));
}

/* ---------------- 点击 / 拖动时间轴 ---------------- */
function seTimeAtX(ed, rect, x){   // x → 窗口里的时间，落在 0.1 的格子上
  const tenth = Math.round(1 / SE_STEP_S);
  return seClampPh(ed, Math.round(sePxToTime(windowOf(ed), rect.width, x - rect.left) * tenth) / tenth);
}
function seScrubTo(ed, track, e){ seSetPlayhead(ed, seTimeAtX(ed, track.getBoundingClientRect(), e.clientX)); }
function seTrackDown(ed, track, e){
  if(state.segEdit !== ed || e.button || (e.target && SE_HANDLES.some(h => h[1] === e.target.id))) return;   // 按在手柄上：手柄自己（wireHandles）；其余都是移动播放头
  ed.keyHandle = 'playhead';
  track.focus({preventScroll: true});   // 焦点离开手柄，方向键动播放头
  ed.scrubbing = true;
  try{ track.setPointerCapture(e.pointerId); }
  catch(err){ /* 指针已失效（比如按下后立刻抬起）：照样能点，只是拖出时间轴后收不到移动 */ }
  seScrubTo(ed, track, e);
}
document.addEventListener('pointerup', () => { const ed = state.segEdit; if(ed) ed.pointerDrag = false; });
document.addEventListener('pointercancel', () => { const ed = state.segEdit; if(ed) ed.pointerDrag = false; });

/* ---------------- 吸附：只在指针拖手柄时 ---------------- */
// 返回要吸到的值（播放头的两位小数），不满足条件返回 null：没在指针拖动、不在 SE_SNAP_PX 内、会短于最短选段、超出 [0, 总长]。
function seSnapValue(ed, which, raw){
  const width = seTrackWidth();
  if(!ed.pointerDrag || width <= SE_THUMB_PX) return null;
  const win = windowOf(ed);
  if(Math.abs(seTimeToPx(win, width, raw) - seTimeToPx(win, width, ed.playhead)) > SE_SNAP_PX + SE_PX_EPS) return null;
  const to = round2(ed.playhead);
  const fits = which === 'start' ? to >= 0 && ed.end - to >= SE_MIN_LEN_S - SE_EPS_S
                                 : to <= ed.mat + SE_EPS_S && to - ed.start >= SE_MIN_LEN_S - SE_EPS_S;
  return fits ? to : null;
}

/* ---------------- 空格：播放 / 暂停 ---------------- */
function seTogglePlay(ed){
  const v = $('#seVideo'), win = windowOf(ed);
  if(v.paused === false && !v.ended){   // 在播：暂停，播放头停在当前画面
    v.pause(); ed.stopAt = null; stopEditPoll(ed);
    seMovePlayhead(ed, v.currentTime);
    return;
  }
  seMovePlayhead(ed, ed.playhead >= win.hi - SE_EPS_S ? ed.start : ed.playhead);   // 已在右端：回到选段开始再播
  playEdit(ed, ed.playhead, win.hi);   // 从播放头播到时间轴右端
}
function seInModal(t){   // 弹窗里的元素，或没有焦点（WebKit 点完遮罩里的空白后落在 body 上）
  return !t || t.tagName === 'BODY' || t.tagName === 'HTML' || $('#mask').contains(t);
}
function seSpaceTarget(e){   // 弹窗开着的空格（输入法选字、带 Ctrl / Meta / Alt 的除外）
  const ed = state.segEdit;
  if(!ed || state.modalKind !== 'segedit' || (e.code !== 'Space' && e.key !== ' ') || !seInModal(e.target)) return null;
  return e.isComposing || e.keyCode === SE_IME_KEYCODE || e.ctrlKey || e.metaKey || e.altKey ? null : ed;
}
// 捕获阶段：赶在 <video> 原生控件、按钮、输入框之前拿到空格，preventDefault + stopPropagation 之后它们都不会再响应。
// shortcuts.js 的捕获监听在弹窗开着时直接 return，两者不冲突。
function seOnSpaceKey(e){
  const ed = seSpaceTarget(e);
  if(!ed) return;
  e.preventDefault(); e.stopPropagation();
  if(!e.repeat) seTogglePlay(ed);
}
function seOnSpaceKeyUp(e){   // Firefox 的按钮在 keyup 时才触发点击
  if(!seSpaceTarget(e)) return;
  e.preventDefault(); e.stopPropagation();
}
document.addEventListener('keydown', seOnSpaceKey, true);
document.addEventListener('keyup', seOnSpaceKeyUp, true);

/* ---------------- 方向键与输入框 ---------------- */
// 返回是否处理了这个键（处理了才 preventDefault）
function sePlayheadKey(tg, e, delta){
  if(tg.slider){ seSetPlayhead(tg.ed, seSnapStep(seClampPh(tg.ed, tg.ed.playhead), delta)); return true; }
  const t = parseTime(e.target.value);
  if(Number.isNaN(t)) return false;   // 写不出数字就不动
  e.target.value = fmtMS(seClampPh(tg.ed, t + delta));
  segPlayheadText(e.target);
  segPlayheadCommit(e.target);
  return true;
}
function segPlayheadText(el){   // 边打边动播放头线（不改写正在打的框，视频等打完再定位）
  const ed = state.segEdit;
  if(!ed) return;
  const t = parseTime(el.value);
  ed.phBad = Number.isNaN(t);
  ed.phEditing = true;
  if(!ed.phBad) ed.playhead = seClampPh(ed, t);
  sePaintPlayhead(ed);
}
function segPlayheadCommit(el){   // 打完（失焦 / 回车）：整理成 m:ss.s（超出窗口的夹回去），视频定到那里
  const ed = state.segEdit;
  if(!ed || ed.phBad) return;
  el.value = fmtMS(ed.playhead);
  seSetPlayhead(ed, ed.playhead);
}

Object.assign(ACTIONS, {segPlayheadText: el => segPlayheadText(el), segPlayheadCommit: el => segPlayheadCommit(el)});
