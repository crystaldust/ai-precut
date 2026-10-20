// 剪辑台主页 · ④ 的「分析对不对」（M13d，可选）：摘要 + 话题 / 关键信息 / 说话人三个证据入口。
// 话题可改名（只改显示名，P3：选段 / 答案仍按原名匹配）；展开话题后每段可改档位（走 /api/browse/level，与 ③ 同一份裁决）。
// 默认折叠，不看也能直接去裁决 / 答题（P7：这一块不拦闸门）。

/* 界面文案：产品可直接改这里 */
const COPY_ANALYSIS_TITLE = '分析对不对';
const COPY_ANALYSIS_OPTIONAL = '（可选）';
const COPY_EVIDENCE_SHOW = '展开证据';
const COPY_EVIDENCE_HIDE = '收起证据';
const COPY_TOPICS = '话题';
const COPY_TOPIC_NAME = '话题名';
const COPY_TOPIC_SEGS = '{n} 段';
const COPY_LEVEL_CHOICES = [[3, '可用'], [2, '待定'], [1, '废片']];
const TOPIC_NAME_MAX = 20;   // 与服务端 pipeline/topic_names.py 的 DISPLAY_MAX 一致（测试比对）
const SEG_PREVIEW_CHARS = 50;

function levelSelectHtml(s, idx){
  return `<select data-change="critLevel" data-i="${num(idx)}" aria-label="${esc(COPY_ANALYSIS_TITLE)}">`
    + COPY_LEVEL_CHOICES.map(([v, label]) => `<option value="${v}"${s.level === v ? ' selected' : ''}>${esc(label)}</option>`).join('')
    + '</select>';
}
function topicSegsHtml(c, raw){
  return c.segs.map((s, idx) => [s, idx]).filter(([s]) => s.topic_raw === raw).map(([s, idx]) =>
    `<div class="c-seg${s.unusable ? ' unusable' : ''}"><b>${esc(fmt(num(s.start)))}</b>`
    + `<span>${esc(String(s.text ?? '').slice(0, SEG_PREVIEW_CHARS))}</span>${levelSelectHtml(s, idx)}</div>`).join('');
}
function topicsHtml(c){
  const rows = (c.data.topics || []).map((t, k) => {
    const open = c.openTopics.includes(k);
    return `<div class="c-topic"><button class="ghost" data-act="critTopicToggle" data-i="${num(k)}">${open ? '▾' : '▸'}</button>`
      + `<input value="${esc(t.topic)}" maxlength="${TOPIC_NAME_MAX}" data-change="critRename" data-i="${num(k)}" aria-label="${esc(COPY_TOPIC_NAME)}">`
      + `<span class="hint">${esc(COPY_TOPIC_SEGS.replace('{n}', num(t.count)))}</span></div>`
      + (open ? `<div class="c-segs">${topicSegsHtml(c, t.topic_raw)}</div>` : '');
  }).join('');
  return `<h4>${esc(COPY_TOPICS)}</h4>${rows}`;
}
function keyPointsHtml(c){
  const points = ((c.data.summary || {}).key_points || []).map(p =>
    `<div class="kp" data-act="critJumpAt" data-t="${num(p.at)}"><b>${esc(fmt(num(p.at)))}</b>${esc(p.text)}`
    + `<span class="why"> · ${esc(p.why || '')}</span></div>`).join('');
  return points ? `<h4>${esc(COPY_KEY_POINTS)}</h4>${points}` : '';
}
function speakersHtml(c){
  const cast = (c.data.speakers || []).map(s => `<span>${esc(s.name)} · ${esc(fmtLong(num(s.seconds)))}</span>`).join('');
  return cast ? `<h4>${esc(COPY_SPEAKERS)}</h4><div class="cast">${cast}</div>` : '';
}
// 正在输入话题名 / 操作下拉时，后台回包触发的重画先挂起（不冲掉输入），失去焦点后再画；force = 用户自己的操作
function analysisBusy(){
  const root = $('#cAnalysis'), a = document.activeElement;
  return !!(root && a && typeof root.contains === 'function' && root.contains(a));
}
function renderAnalysis(force){
  const c = crit();
  if(!criteriaLive(c)) return;
  if(!force && analysisBusy()){ c.analysisDirty = true; return; }
  c.analysisDirty = false;
  const sum = c.data.summary || {};
  $('#cAnalysis').innerHTML = `<h3>${esc(COPY_ANALYSIS_TITLE)}<small> ${esc(COPY_ANALYSIS_OPTIONAL)}</small></h3>`
    + `<p>${esc(sum.summary || COPY_NO_SUMMARY)}${sum.fallback ? `<small> ${esc(COPY_FALLBACK_SUMMARY)}</small>` : ''}</p>`
    + `<button class="ghost" data-act="critToggleAnalysis">${esc(c.analysisOpen ? COPY_EVIDENCE_HIDE : COPY_EVIDENCE_SHOW)}</button>`
    + (c.analysisOpen ? topicsHtml(c) + keyPointsHtml(c) + speakersHtml(c) : '');
}

function toggleTopic(k){
  const c = crit();
  if(!c || !c.data) return;
  c.openTopics = c.openTopics.includes(k) ? c.openTopics.filter(x => x !== k) : [...c.openTopics, k];
  renderAnalysis(true);
}
async function renameTopic(k, value){
  const c = crit(), t = c && c.data && (c.data.topics || [])[k];
  if(!t) return;
  const display = String(value ?? '').trim();
  if(display === t.topic || (display === '' && t.topic === t.topic_raw)) return;
  try{   // 空 = 恢复原名；重名 / 超长等由服务端说明原因
    const r = await postJson('/api/topics/rename', {project: c.project, name: t.topic_raw, display});
    if(state.criteria !== c) return;
    const shown = (r.topic_names && r.topic_names[t.topic_raw]) || t.topic_raw;
    c.data = {...c.data, topics: c.data.topics.map((x, i) => i === k ? {...x, topic: shown} : x)};
    c.segs.forEach(s => { if(s.topic_raw === t.topic_raw) s.topic = shown; });
  }catch(e){
    if(state.criteria !== c) return;
    toast(e.message, TOAST_ERROR_MS);
  }
  renderAnalysis(true); renderPending();   // 失败时也重画：输入框回到原来的名字
}
function changeSegLevel(idx, level){
  const c = crit(), seg = c && c.data && c.segs[idx];
  if(!seg || !COPY_LEVEL_CHOICES.some(([v]) => v === level) || seg.level === level) return Promise.resolve(false);
  return setLevel(c, seg, level);
}

document.addEventListener('focusout', () => setTimeout(() => {   // 输入框 / 下拉失去焦点后补画挂起的那一次
  const c = crit();
  if(criteriaLive(c) && c.analysisDirty && !analysisBusy()) renderAnalysis(true);
}, 0));

Object.assign(ACTIONS, {
  critToggleAnalysis: () => { const c = crit(); if(c && c.data){ c.analysisOpen = !c.analysisOpen; renderAnalysis(true); } },
  critTopicToggle: el => toggleTopic(num(el.dataset.i)),
  critRename: el => renameTopic(num(el.dataset.i), el.value),
  critLevel: el => changeSegLevel(num(el.dataset.i), num(el.value)),
  critJumpAt: el => jumpCriteriaAt(num(el.dataset.t)),
});
