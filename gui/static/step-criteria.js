// 剪辑台主页 · ④ 定标准（M13d，闸门 A）：左侧小目录 + 三块（分析对不对 / 裁决待定 / 决策问题）+ 底部闸门。
// 本文件：页面骨架与加载、目录、决策问题（点选即自动存草稿）、「重新出题」、闸门、档位修改（两块共用）。
// 分析对不对在 criteria-analysis.js，裁决待定与播放器在 criteria-pending.js。
// 页面骨架是固定的（viewCriteria 恒返回同一段 HTML，轮询刷新不会重画它）；内容由 enterCriteria 加载后分块填进去。
// P1：「剩下的按 AI 建议」不写任何裁决——剩下的待定保持待定、不进片；P7：三块的完成情况只显示，都不拦闸门。

/* 界面文案：产品可直接改这里 */
const COPY_TOC_TITLE = '本步完成情况';
const COPY_TOC_LABELS = {analysis: '分析对不对', pending: '裁决待定', questions: '决策问题'};
const COPY_TOC_OPTIONAL = '可选';
const COPY_TOC_PENDING_LEFT = '还有 {n} 段待定';
const COPY_TOC_PENDING_HANDLED = '已处理';
const COPY_TOC_ANSWERED = '已答 {a}/{m}';
const COPY_QUESTIONS_TITLE = '决策问题';
const COPY_NO_QUESTIONS = '还没有决策问题';
const COPY_REGEN = '重新出题';
const COPY_FALLBACK_Q = '（兜底模板生成）';
const COPY_EFFECT = '选了会怎样：';
const COPY_ANSWERS_UNREADABLE = '上次保存的答案读不出来，请重新作答';
const COPY_DRAFT_SAVING = '正在保存…';
const COPY_DRAFT_SAVED = '已保存';
const COPY_GATE = '确认，生成分镜表';
const COPY_GATE_ASK = '还有 {n} 段待定，按 AI 建议处理？';
const COPY_GATE_ASK_NOTE = '按 AI 建议 = 这些片段先不进片，不会替你标可用或废片；之后仍可在 ③ 看素材里改。';
const COPY_GATE_GO = '按 AI 建议，继续';
const COPY_GATE_BACK = '回去裁决';
const COPY_GATE_SAVE_FIRST = '答案还没保存成功，先不确认';
const COPY_GATE_NOT_READY = '还没有决策问题，先点「重新出题」';
const COPY_GATE_LEVEL_FAILED = '有档位改动没保存成功，先不确认：请看提示后重试';
const COPY_DRAFT_BLOCKED = '答案还没存上：{reason}。先留在这一步，再点一次会重试';
const COPY_DRAFT_LOST = '项目「{project}」最后一次答案没存上：{reason}。回到它那里再改一次';
const TOAST_PERSISTENT_MS = 20000;
const COPY_RESELECT_RUNNING = '已保存 · 正在按你的答案重新选段…';
const COPY_RESELECT_BLOCKED = '答案已保存，但没能开始重新选段：';
const COPY_CUSTOM = '自定义';
const COPY_CUSTOM_LABEL = '第 {n} 题 · 自定义';
const COPY_CUSTOM_NOTE = '写下你的想法，确认后由 AI 换算成选段规则';
const COPY_CUSTOM_PLACEHOLDER = '比如：结尾落在妈妈的拥抱';
const COPY_EXTRA_TITLE = '其他想法（自定义）';
const COPY_EXTRA_PLACEHOLDER = '上面的问题没覆盖到的想法，比如：不要出现价格';
const COPY_UNDERSTOOD = 'AI 理解为：';
const COPY_NOT_UNDERSTOOD = '上次没能换算成选段规则：';
const CUSTOM_EXTRA = '_extra';     // 与服务端 questions.CUSTOM_EXTRA 一致
const CUSTOM_MAX_CHARS = 200;      // 与服务端 questions.MAX_CUSTOM_CHARS 一致
const ANSWER_SAVE_DEBOUNCE_MS = 500;
const SECTION_IDS = {analysis: 'cAnalysis', pending: 'cPending', questions: 'cQuestions'};
const LEVEL_FIELDS = ['level', 'level_reason', 'override', 'unusable'];  // 服务端回的 segment 里只取这几项

let criteriaGen = 0;   // 每次进入 / 重置 +1：过期的加载结果一律丢掉（同 stateSeq 思路）
const CRIT_SKELETON = `<div class="crit">
  <nav class="c-toc" id="cToc"></nav>
  <div class="c-main">
    <section class="card" id="cAnalysis"></section>
    <section class="card" id="cPending"></section>
    <section class="card" id="cQuestions"></section>
  </div>
  <aside class="c-aside"><video id="cPv" controls preload="metadata"></video></aside></div>`;
function viewCriteria(){ return CRIT_SKELETON; }
function crit(){ return state.criteria; }
// 渲染只在 ④ 的骨架还在页面上时才做：离开 ④ 之后才回来的响应只改状态，不碰 DOM（骨架已被换掉）
function criteriaLive(c){ return !!c && !!c.data && state.view === 'criteria' && state.criteria === c; }
function segById(c, id){ return c.segs.find(s => s.id === id) || null; }
function levelSnap(s){ return {level: s.level, level_reason: s.level_reason, override: s.override, unusable: s.unusable}; }

function resetCriteria(){
  criteriaGen += 1;
  const c = state.criteria;
  if(c && c.draftTimer) clearTimeout(c.draftTimer);
  state.criteria = null;
  unloadCriteriaPlayer();
}

/* ---------------- 加载 ---------------- */
function newCriteria(gen, project, data){
  const segs = (data.segments || []).map(s => ({...s}));
  const custom = {...(data.custom || {})}, qids = (data.questions || []).map(q => q.id);
  return {gen, project, data, segs, answers: {...(data.answers || {})},
          custom, customOn: Object.keys(custom).filter(k => qids.includes(k)),   // 选了「自定义」的题（含还没填字的）
          queue: (data.pending || []).map(p => p.id).filter(id => segs.some(s => s.id === id)),
          aiRest: false, gating: false, status: data.answers_unreadable ? COPY_ANSWERS_UNREADABLE : '',
          analysisOpen: false, openTopics: [], analysisDirty: false, levelFailures: 0, draftError: null, cuedId: null, cueEnd: null, stopAt: null, lastT: null,
          draftTimer: null, dirty: false, draftChain: Promise.resolve(true),
          levelChain: Promise.resolve(), inflight: new Map(), confirmed: new Map(segs.map(s => [s.id, levelSnap(s)]))};
}
async function enterCriteria(){
  const project = state.project;
  if(!project) return;
  const gen = ++criteriaGen;
  const old = crit();
  state.criteria = {gen, project, data: null, loading: true};   // 加载期间 A / D 等一律不生效
  await flushCriteriaDraft(old);              // 回到 ④ 前先把还没发出的草稿、档位改动和 ③ 的标记落地，重读不会盖掉它们
  if(old && old.levelChain) await old.levelChain;
  await settleMarks();
  if(gen !== criteriaGen) return;
  const live = () => gen === criteriaGen && project === state.project && state.view === 'criteria';
  let data;
  try{ data = await api('/api/confirm?project=' + encodeURIComponent(project)); }
  catch(e){
    if(!live()) return;
    state.criteria = {gen, project, data: null};
    ['cToc', 'cAnalysis', 'cPending'].forEach(id => { $('#' + id).innerHTML = ''; });
    $('#cQuestions').innerHTML = failureHtml(e);
    return;
  }
  if(!live()) return;
  state.criteria = newCriteria(gen, project, data);
  mountCriteriaPlayer(project);
  renderCriteria();
}
function failureHtml(e){   // 404 = 还没有决策问题：给「重新出题」；其它（损坏等）原样说出原因
  const text = e.status === 404 ? COPY_NO_QUESTIONS : (e.message || COPY_NO_QUESTIONS);
  return `<h3>${esc(COPY_QUESTIONS_TITLE)}</h3><p>${esc(text)}</p>`
    + `<button class="primary" data-act="critRegen" data-starts-job>${esc(COPY_REGEN)}</button>`;
}
function renderCriteria(){ renderToc(); renderAnalysis(); renderPending(); renderQuestions(); applyBusyGuard(); }

/* ---------------- 左小目录（P7） ---------------- */
function tocItems(c){
  const qs = c.data.questions || [], left = c.queue.length, handled = left === 0 || c.aiRest;
  const answered = qs.filter(q => asList(c.answers[q.id]).length || hasCustom(c, q.id)).length;
  return [
    {key: 'analysis', done: false, text: COPY_TOC_OPTIONAL},
    {key: 'pending', done: handled, text: handled ? COPY_TOC_PENDING_HANDLED : COPY_TOC_PENDING_LEFT.replace('{n}', left)},
    {key: 'questions', done: answered === qs.length, text: COPY_TOC_ANSWERED.replace('{a}', answered).replace('{m}', qs.length)},
  ].map(i => ({...i, label: COPY_TOC_LABELS[i.key]}));
}
function renderToc(){
  const c = crit();
  if(!criteriaLive(c)) return;
  $('#cToc').innerHTML = `<h4>${esc(COPY_TOC_TITLE)}</h4>` + tocItems(c).map(i =>
    `<button class="toc-item${i.done ? ' done' : ''}" data-act="critJump" data-sec="${esc(i.key)}">`
    + `<span class="mark">${i.done ? '✓' : '○'}</span>${esc(i.label)}<small>${esc(i.text)}</small></button>`).join('');
}
function jumpToSection(key){
  const id = SECTION_IDS[key], sec = id && document.getElementById(id);
  if(sec && typeof sec.scrollIntoView === 'function') sec.scrollIntoView({block: 'start'});
}

/* ---------------- 决策问题 ---------------- */
function optionHtml(q, qi, o, oi, chosen){
  const sel = q.type === 'multi' ? asList(chosen).includes(o.label) : chosen === o.label;
  return `<label class="opt${sel ? ' sel' : ''}" data-act="critPick" data-q="${num(qi)}" data-o="${num(oi)}">`
    + `<input type="${q.type === 'multi' ? 'checkbox' : 'radio'}"${sel ? ' checked' : ''} tabindex="-1">`
    + `${esc(o.label)}<small>${esc(COPY_EFFECT + (o.effect || ''))}</small></label>`;
}
function renderQuestions(){
  const c = crit();
  if(!criteriaLive(c)) return;
  const d = c.data, stale = d.stale_questions ? `<div class="b-warn">${esc(d.stale_hint || '')}</div>` : '';
  const qs = (d.questions || []).map((q, qi) =>
    `<div class="q"><p><span class="n">${qi + 1}.</span>${esc(q.text)}</p>`
    + (q.options || []).map((o, oi) => optionHtml(q, qi, o, oi, c.answers[q.id])).join('')
    + customOptHtml(c, q, qi) + '</div>').join('');
  const extra = `<div class="q c-extra"><p>${esc(COPY_EXTRA_TITLE)}</p>`
    + customBoxHtml(c, CUSTOM_EXTRA, 'X', 'data-extra="1"', COPY_EXTRA_PLACEHOLDER, COPY_EXTRA_TITLE) + '</div>';
  $('#cQuestions').innerHTML = `<h3>${esc(COPY_QUESTIONS_TITLE)}`
    + (d.fallback ? `<small> ${esc(COPY_FALLBACK_Q)}</small>` : '') + `</h3>${stale}${qs}${extra}`
    + `<div class="c-actions"><button class="ghost" data-act="critRegen" data-starts-job>${esc(COPY_REGEN)}</button>`
    + `<span class="hint" id="cStatus" role="status">${esc(c.status)}</span></div>`;
  applyBusyGuard();
}
function setStatus(c, text, isError){
  c.status = text;
  const el = document.getElementById('cStatus');
  if(el) el.innerHTML = esc(text);
  if(isError) toast(text, Math.max(TOAST_ERROR_MS, String(text).length * TOAST_MS_PER_CHAR));
}
// data-q / data-o 只放数字下标，选项文本不进属性（GL-07）；不可变更新：不原地改磁盘读来的数组（KI-49）
function pickAnswer(qi, oi){
  const c = crit(), q = c && c.data && (c.data.questions || [])[qi], o = q && (q.options || [])[oi];
  if(!o) return;
  const cur = c.answers[q.id];
  const next = q.type === 'multi'
    ? (asList(cur).includes(o.label) ? asList(cur).filter(x => x !== o.label) : [...asList(cur), o.label]) : o.label;
  c.answers = {...c.answers, [q.id]: next};
  if(q.type !== 'multi') c.customOn = c.customOn.filter(k => k !== q.id);   // 单选：选了选项就不再用自定义
  scheduleDraft(c);
  c.status = COPY_DRAFT_SAVING;
  renderToc(); renderQuestions();
}

/* ---------------- 自定义：每题一个（单选 = 替换选项，多选 = 并存）+ 题后「其他想法」；确认后由 AI 换算成规则 ---------------- */
function customText(c, key){ return typeof c.custom[key] === 'string' ? c.custom[key] : ''; }
function hasCustom(c, key){ return customText(c, key).trim() !== '' && (key === CUSTOM_EXTRA || c.customOn.includes(key)); }
// 发给服务端的答案：只带选了「自定义」且写了字的；一条都没有就不带 custom（= 清空）
function answerBody(c){
  const keys = Object.keys(c.custom).filter(k => hasCustom(c, k));
  if(!keys.length) return {answers: c.answers};
  return {answers: c.answers, custom: Object.fromEntries(keys.map(k => [k, customText(c, k).trim()]))};
}
// idx 只放 'Q<下标>' / 'X'，题目 id 与文字不进 id 属性（GL-07）
function customBoxHtml(c, key, idx, attr, placeholder, label){
  const text = customText(c, key), u = (c.data.custom_understood || {})[key];
  const hint = u ? `<small class="c-understood" id="cu${idx}"${text.trim() === String((c.data.custom || {})[key] || '') ? '' : ' hidden'}>`
    + `${esc(u.rules ? COPY_UNDERSTOOD + u.rules : COPY_NOT_UNDERSTOOD + (u.note || ''))}</small>` : '';
  return `<div class="c-custom"><input type="text" id="ci${idx}" maxlength="${CUSTOM_MAX_CHARS}" data-input="critCustomInput" ${attr}`
    + ` value="${esc(text)}" placeholder="${esc(placeholder)}" aria-label="${esc(label)}">${hint}</div>`;
}
// 「自定义」的勾选框可以用 Tab 走到、空格选中（点击冒泡到 label 的 data-act）
function customOptHtml(c, q, qi){
  const on = c.customOn.includes(q.id), label = COPY_CUSTOM_LABEL.replace('{n}', num(qi) + 1);
  return `<label class="opt${on ? ' sel' : ''}" data-act="critCustomPick" data-q="${num(qi)}">`
    + `<input type="${q.type === 'multi' ? 'checkbox' : 'radio'}"${on ? ' checked' : ''} aria-label="${esc(label)}">`
    + `${esc(COPY_CUSTOM)}<small>${esc(COPY_CUSTOM_NOTE)}</small></label>`
    + (on ? customBoxHtml(c, q.id, 'Q' + num(qi), `data-q="${num(qi)}"`, COPY_CUSTOM_PLACEHOLDER, label) : '');
}
function pickCustom(qi){
  const c = crit(), q = c && c.data && (c.data.questions || [])[qi];
  if(!q) return;
  const on = c.customOn.includes(q.id), keep = on && q.type !== 'multi';   // 单选再点一次还是它：只把光标放进输入框
  if(!keep){
    c.customOn = on ? c.customOn.filter(k => k !== q.id) : [...c.customOn, q.id];
    if(!on && q.type !== 'multi'){ const {[q.id]: _replaced, ...rest} = c.answers; c.answers = rest; }
    scheduleDraft(c);
    c.status = COPY_DRAFT_SAVING;
    renderToc(); renderQuestions();
  }
  const box = (keep || !on) && document.getElementById('ciQ' + qi);
  if(box && typeof box.focus === 'function') box.focus();
}
// 打字时不重画题目（会丢焦点）：只更新状态、目录、上次换算提示的显隐
function inputCustom(el){
  const c = crit();
  if(!c || !c.data) return;
  const qi = num(el.dataset.q), q = el.dataset.extra === '1' ? null : (c.data.questions || [])[qi];
  const key = q ? q.id : el.dataset.extra === '1' ? CUSTOM_EXTRA : null;
  if(!key || (q && !c.customOn.includes(key))) return;
  const value = String(el.value || '').slice(0, CUSTOM_MAX_CHARS);
  c.custom = {...c.custom, [key]: value};
  const hint = document.getElementById('cu' + (q ? 'Q' + qi : 'X'));
  if(hint) hint.hidden = value.trim() !== String((c.data.custom || {})[key] || '');
  scheduleDraft(c);
  if(c.status !== COPY_DRAFT_SAVING) setStatus(c, COPY_DRAFT_SAVING);   // role=status：别每个字都播报一次
  renderToc();
}

/* ---------------- 草稿自动保存：防抖 + 单通道，点闸门 / 重新出题 / 离开前先 flush ---------------- */
function scheduleDraft(c){
  clearTimeout(c.draftTimer);
  c.dirty = true;
  c.draftTimer = setTimeout(() => { c.draftTimer = null; saveDraft(c); }, ANSWER_SAVE_DEBOUNCE_MS);
}
function saveDraft(c){
  c.draftChain = c.draftChain.then(async () => {
    if(!c.dirty) return true;
    c.dirty = false;
    try{
      const r = await postJson('/api/confirm/answers', {project: c.project, ...answerBody(c)});  // 不带 confirmed：草稿不动确认状态
      c.draftError = null;
      if(state.criteria === c){ setStatus(c, c.dirty ? COPY_DRAFT_SAVING : COPY_DRAFT_SAVED); applyWizard(r.wizard); }   // 又点了别的选项就别说「已保存」
      return true;
    }catch(e){
      c.dirty = true;   // 留着，下一次 flush（闸门 / 再点选项）会重试
      c.draftError = e.message;
      if(state.criteria === c) setStatus(c, e.message, true);
      return false;
    }
  });
  return c.draftChain;
}
function flushCriteriaDraft(c = crit()){
  if(!c || !c.data) return Promise.resolve(true);
  if(c.draftTimer){ clearTimeout(c.draftTimer); c.draftTimer = null; }
  return c.dirty ? saveDraft(c) : c.draftChain;
}
async function regenerate(){
  await flushCriteriaDraft();
  return startJob('questions', {}, {modal: false});   // 完成后 jobs.js 会重新进入 ④
}

/* ---------------- 档位修改（分析对不对的下拉与裁决待定的 A / D 共用）：乐观更新 → 排队发 → 失败回到服务端确认过的状态 ---------------- */
function syncQueue(c, seg){
  const inQueue = c.queue.includes(seg.id), want = seg.level === 2 && !seg.unusable;
  if(want === inQueue) return;
  if(!want){ c.queue = c.queue.filter(id => id !== seg.id); return; }
  const at = c.queue.findIndex(id => segById(c, id).start > seg.start);   // 按时间放回，不是排到最后
  c.queue = at < 0 ? [...c.queue, seg.id] : [...c.queue.slice(0, at), seg.id, ...c.queue.slice(at)];
}
function renderLevelChange(c, force){
  renderToc(); renderPending();
  if(c.analysisOpen) renderAnalysis(force);   // force：回滚时必须重画，下拉框要回到原值
}
function setLevel(c, seg, level){
  const optimistic = {level, override: true, level_reason: `人工改为${LEVEL_NAMES[level]}`};
  Object.assign(seg, optimistic);
  c.inflight.set(seg.id, (c.inflight.get(seg.id) || 0) + 1);
  syncQueue(c, seg);
  renderLevelChange(c);
  const run = c.levelChain.then(() => sendLevel(c, seg, level, optimistic));
  c.levelChain = run.catch(() => {});   // 闸门 / 切步骤等这条链走完（含回滚）再往下
  return run;
}
async function sendLevel(c, seg, level, optimistic){
  let r = null, err = null;
  try{ r = await postJson('/api/browse/level', {project: c.project, id: seg.id, level}); }
  catch(e){ err = e; c.levelFailures += 1; }
  const left = c.inflight.get(seg.id) - 1;
  c.inflight.set(seg.id, left);
  if(state.criteria !== c) return false;   // 页面状态已经换了（切项目 / 重新进入）：不碰
  if(err) toast(COPY_ROLLED_BACK + err.message, Math.max(TOAST_ERROR_MS, String(err.message).length * TOAST_MS_PER_CHAR));
  else{
    const got = {...optimistic};
    if(r.segment) LEVEL_FIELDS.forEach(k => { if(k in r.segment) got[k] = r.segment[k]; });
    c.confirmed.set(seg.id, {...c.confirmed.get(seg.id), ...got});
    applyWizard(r.wizard);
  }
  if(!left){ Object.assign(seg, c.confirmed.get(seg.id)); syncQueue(c, seg); }   // 后面还有排队的改动时不覆盖它的乐观值
  renderLevelChange(c, !!err);
  return !err;
}

/* ---------------- 闸门（底部导航里的主按钮，见 wizard.js） ---------------- */
function gateNavHtml(){
  return `<span class="gate-wrap"><button class="primary" data-act="gate" data-starts-job>${esc(COPY_GATE)}</button></span>`;
}
function gate(){
  const c = crit();
  if(!c || !c.data){ toast(COPY_GATE_NOT_READY, TOAST_ERROR_MS); return; }
  const left = c.aiRest ? 0 : c.queue.length;
  return left > 0 ? askGate(left) : submitGate();
}
function askGate(n){   // 先问，不拦：「按 AI 建议，继续」不写任何裁决（P1）
  showModal(COPY_GATE_ASK.replace('{n}', n),
    `<p>${esc(COPY_GATE_ASK_NOTE)}</p><div class="job-actions">`
    + `<button class="primary" data-act="gateGo">${esc(COPY_GATE_GO)}</button>`
    + `<button class="ghost" data-act="closeModal">${esc(COPY_GATE_BACK)}</button></div>`);
  state.modalKind = 'gate';
}
function gateGo(){
  closeModal();
  const c = crit();
  if(!c) return;
  c.aiRest = true;
  renderToc(); renderPending();
  return submitGate();
}
async function submitGate(){
  const c = crit();
  if(!c || !c.data || c.gating) return;
  c.gating = true;
  const failedBefore = c.levelFailures;
  try{
    await c.levelChain;   // 还在路上的档位改动先落地；其中有失败的就不确认（之前已经提示过的失败不算）
    if(c.levelFailures > failedBefore){ setStatus(c, COPY_GATE_LEVEL_FAILED, true); return; }
    if(!await flushCriteriaDraft(c)){ toast(COPY_GATE_SAVE_FIRST, TOAST_ERROR_MS); return; }   // 先把最后一次点选存下来
    let r = null;   // KI-95：手动改过分镜表先问「覆盖 / 保留 / 取消」；取消 = 不确认，答案已作为草稿保存
    const {choice, reason} = await confirmReselectDetailed({}, {submit: async manual => {
      r = await postJson('/api/confirm/answers', {project: c.project, ...answerBody(c), confirmed: true, manual});
    }});
    if(choice === null){   // 真的取消才说「已取消」；没存上 / 没读到 / 没起来要说真实原因
      if(state.criteria === c) setStatus(c, reason || COPY_GATE_CANCELLED, !!reason);
      return;
    }
    const here = state.criteria === c && state.project === c.project;
    if(here) applyWizard(r.wizard);
    if(r.job_id){
      trackJob(r.job_id, 'select');   // 完成后 jobs.js 带我们去 ⑤（项目没换的话）
      if(here) setStatus(c, COPY_RESELECT_RUNNING);
    }else if(r.job_error && here) setStatus(c, COPY_RESELECT_BLOCKED + r.job_error, true);
  }catch(e){
    if(state.criteria === c) setStatus(c, e.message, true); else toast(e.message, TOAST_ERROR_MS);
  }finally{ c.gating = false; }
}

Object.assign(ACTIONS, {
  // 选项是 <label> 包着 <input>：阻止默认动作，免得浏览器再替 input 点一次、多选被切换两次
  critPick: (el, ev) => { ev.preventDefault(); pickAnswer(num(el.dataset.q), num(el.dataset.o)); },
  critCustomPick: (el, ev) => { ev.preventDefault(); pickCustom(num(el.dataset.q)); },
  critCustomInput: el => inputCustom(el),
  critJump: el => jumpToSection(el.dataset.sec), critRegen: () => regenerate(),
  gate: () => gate(), gateGo: () => gateGo(),
});

// 草稿存不上时拦住离开 ④（go）：留在原地说清原因，再点一次就是重试
function criteriaDraftBlocked(){
  const c = crit();
  setStatus(c, COPY_DRAFT_BLOCKED.replace('{reason}', c.draftError || ''), true);
}
function criteriaDraftLost(c){
  toast(COPY_DRAFT_LOST.replace('{project}', c.project).replace('{reason}', c.draftError || ''), TOAST_PERSISTENT_MS);
}
