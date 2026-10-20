// 剪辑台主页 · ④ 的「裁决待定」与播放器（M13d）：一次一段，原文 + 依据 + 播放；A 可用 / D 废片（键位取自快捷键表），
// 「先跳过」放到队尾，「剩下的按 AI 建议」不写任何裁决（P1）。档位的乐观更新与回滚在 step-criteria.js 的 setLevel。
// 播放器只在 ④ 里用一个 <video>：裁决待定的当前段和「分析对不对」里点关键信息都用它。

/* 界面文案：产品可直接改这里 */
const COPY_PENDING_TITLE = '裁决待定';
const COPY_PENDING_NONE = '没有待定的片段了 ✓';
const COPY_PENDING_LEFT = '还有 {n} 段待定';
const COPY_PENDING_USABLE = '可用';
const COPY_PENDING_WASTE = '废片';
const COPY_PENDING_SKIP = '先跳过';
const COPY_AI_REST = '剩下的按 AI 建议';
const COPY_AI_REST_ASK = '剩下 {n} 段待定，按 AI 建议处理？';
const COPY_AI_REST_NOTE = '按 AI 建议 = 这些片段先不进片，不会替你标可用或废片；之后仍可在 ③ 看素材里改。';
const COPY_AI_REST_GO = '按 AI 建议';
const COPY_AI_REST_CANCEL = '取消';
const COPY_AI_REST_DONE = '剩下 {n} 段按 AI 建议：先不进片（之后仍可在 ③ 看素材里改）';
const DECIDE_LEVELS = [1, 3];   // 只能直接裁成废片或可用

function criteriaPlayer(){ return $('#cPv'); }
function criteriaHasCurrent(){ const c = crit(); return !!(c && c.data && !c.aiRest && c.queue.length); }
function pendingSeg(c){ return c.queue.length ? segById(c, c.queue[0]) : null; }

/* ---------------- 播放器 ---------------- */
function mountCriteriaPlayer(project){
  const pv = criteriaPlayer();
  if(!pv) return;
  if(pv.dataset.project !== project){ pv.src = '/media/' + encodeURIComponent(project) + '/proxy'; pv.dataset.project = project; }
  if(pv.cWired) return;   // 只接一次：骨架没换时元素还是同一个
  pv.cWired = true;
  pv.addEventListener('play', startCriteriaStop);
  pv.addEventListener('pause', stopCriteriaStop);
  pv.addEventListener('ended', stopCriteriaStop);
  pv.addEventListener('seeking', () => { const c = crit(); if(c) c.lastT = null; });   // 手动拖动不算「自然播到出点」
}
// 切项目 / 离开：停止并卸掉播放器，不让上一个项目的小样继续播
function unloadCriteriaPlayer(){
  stopCriteriaStop();
  const pv = criteriaPlayer();
  if(!pv) return;
  if(!pv.paused) pv.pause();
  pv.removeAttribute('src');
  delete pv.dataset.project;
  if(typeof pv.load === 'function') pv.load();
}
// 播放中短间隔检查：只在「自然播放跨过出点」时停；用户手动拖到出点之后不会被拦下
let criteriaStopTimer = null;
function startCriteriaStop(){ if(criteriaStopTimer === null) criteriaStopTimer = setInterval(pollCriteriaStop, STOP_POLL_MS); }
function stopCriteriaStop(){ if(criteriaStopTimer !== null){ clearInterval(criteriaStopTimer); criteriaStopTimer = null; } }
function pollCriteriaStop(){
  const c = crit(), pv = criteriaPlayer();
  if(!c || !pv) return stopCriteriaStop();
  const t = pv.currentTime;
  if(c.stopAt !== null && c.lastT !== null && c.lastT < c.stopAt && t >= c.stopAt){ pv.pause(); c.stopAt = null; }
  c.lastT = t;
}
function cuePending(){   // 当前待定段：入点 −0.3 → 出点 +0.3（D15），先摆好位置，空格再播
  const c = crit(), pv = criteriaPlayer(), s = c && pendingSeg(c);
  if(!pv || !s) return;
  pv.currentTime = Math.max(0, num(s.start) - PAD_S);
  c.stopAt = c.cueEnd = num(s.end) + PAD_S;
  c.lastT = null;
}
function jumpCriteriaAt(t){   // 点关键信息：从该时间码试听几秒，不改当前待定段的播放范围
  const c = crit(), pv = criteriaPlayer();
  if(!c || !pv) return;
  pv.currentTime = Math.max(0, t - PAD_S);
  c.stopAt = t + KEYPOINT_LISTEN_S;
  c.lastT = null;
  playQuietly(pv);
}
function togglePlayCriteria(){
  const c = crit(), pv = criteriaPlayer(), s = c && !c.aiRest ? pendingSeg(c) : null;
  if(!pv) return;
  if(!pv.paused){ pv.pause(); return; }
  if(s && c.cueEnd !== null && (pv.currentTime < num(s.start) - PAD_S || pv.currentTime >= c.cueEnd)) cuePending();
  playQuietly(pv);
}

/* ---------------- 裁决待定 ---------------- */
function pendingCardHtml(c, s){
  const key = id => esc(keyLabel(state.shortcuts[id] || ''));
  return `<p class="hint">${esc(COPY_PENDING_LEFT.replace('{n}', c.queue.length))}</p>`
    + `<div class="c-now"><b>${esc(fmt(num(s.start)))}–${esc(fmt(num(s.end)))}</b> <span class="cat">${esc(s.topic || COPY_NO_TOPIC)}</span>`
    + `<p>${esc(s.text ?? '')}</p><p class="why">${esc(s.level_reason || '')}</p></div>`
    + `<div class="c-actions"><button class="primary" data-act="critDecide" data-level="3">${esc(COPY_PENDING_USABLE)} <kbd>${key('mark_usable')}</kbd></button>`
    + `<button data-act="critDecide" data-level="1">${esc(COPY_PENDING_WASTE)} <kbd>${key('mark_waste')}</kbd></button>`
    + `<button class="ghost" data-act="critSkip">${esc(COPY_PENDING_SKIP)}</button>`
    + `<button class="ghost" data-act="critAiRest">${esc(COPY_AI_REST)}</button></div>`;
}
function renderPending(){
  const c = crit();
  if(!criteriaLive(c)) return;
  const cur = pendingSeg(c);
  const body = c.aiRest && cur ? `<p>${esc(COPY_AI_REST_DONE.replace('{n}', c.queue.length))}</p>`
    : (cur ? pendingCardHtml(c, cur) : `<p>${esc(COPY_PENDING_NONE)}</p>`);
  $('#cPending').innerHTML = `<h3>${esc(COPY_PENDING_TITLE)}</h3>${body}`;
  const shown = cur && !c.aiRest ? cur.id : null;
  if(shown !== null && shown !== c.cuedId) cuePending();   // 换了一段才重新摆位置，别打断正在播的
  c.cuedId = shown;
}
function decide(level){
  const c = crit(), cur = c && c.data && !c.aiRest ? pendingSeg(c) : null;
  if(!cur || !DECIDE_LEVELS.includes(level)) return Promise.resolve(false);
  return setLevel(c, cur, level);
}
function skipPending(){
  const c = crit();
  if(!c || !c.data || c.aiRest || c.queue.length < 2) return;
  c.queue = [...c.queue.slice(1), c.queue[0]];
  renderPending();
}
function askAiRest(){
  const c = crit();
  if(!c || !c.data || c.aiRest || !c.queue.length) return;
  showModal(COPY_AI_REST_ASK.replace('{n}', c.queue.length),
    `<p>${esc(COPY_AI_REST_NOTE)}</p><div class="job-actions">`
    + `<button class="primary" data-act="critAiRestGo">${esc(COPY_AI_REST_GO)}</button>`
    + `<button class="ghost" data-act="closeModal">${esc(COPY_AI_REST_CANCEL)}</button></div>`);
  state.modalKind = 'aiRest';
}
function aiRestGo(){   // P1：只在本页标记「已处理」，不发任何写请求；剩下的待定仍是待定
  closeModal();
  const c = crit();
  if(!c || !c.data || !c.queue.length) return;
  c.aiRest = true;
  renderToc(); renderPending();
}

// 快捷键（shortcuts.js 的 onKey 在 ④ 里调用）：只处理 播放 / 下一段（=先跳过）/ 可用 / 废片
const CRITERIA_ACTIONS = new Set(['play', 'next', 'mark_usable', 'mark_waste']);
function runCriteriaShortcut(action){
  const runners = {play: () => togglePlayCriteria(), next: () => skipPending(),
                   mark_usable: () => decide(3), mark_waste: () => decide(1)};
  return runners[action] && runners[action]();
}

Object.assign(ACTIONS, {
  critDecide: el => decide(num(el.dataset.level)), critSkip: () => skipPending(),
  critAiRest: () => askAiRest(), critAiRestGo: () => aiRestGo(),
});
