// 确认与提问页（KI-53：从 confirm.html 内联脚本外置）。
const PROJECT = new URLSearchParams(location.search).get('project') || '';
const COPY_ANSWERS_UNREADABLE = '上次保存的答案读不出来，请重新作答';
const COPY_SAVE_FAILED = '保存失败';
const COPY_WARN_TITLE = '需要你留意';
// KI-05：「保存并确认」后服务端自动起「重新选段」任务，这里跟踪它
const COPY_NEXT_STEP = '点「保存并确认」后会按你的选择自动重新选段；你手动改过的分镜表不会被覆盖';
const COPY_SAVED = '已保存';
const COPY_CONFIRMED = '已确认';
const COPY_RESELECT_RUNNING = '已保存 · 正在按你的答案重新选段…';
const COPY_RESELECT_DONE = '选段完成：回到剪辑台查看新的分镜表';
const COPY_RESELECT_FAILED = '重新选段失败：';
const COPY_RESELECT_CANCELLED = '重新选段已取消（答案已保存）';
const COPY_RESELECT_BLOCKED = '答案已保存，但没能开始重新选段：';
const COPY_RESELECT_UNKNOWN = '看不到任务进度，请回剪辑台查看';
const COPY_REGEN_RUNNING = '正在按新规则重新生成决策问题（要调用 DeepSeek，约半分钟）…';
const COPY_REGEN_DONE = '决策问题已重新生成：请重新作答后「保存并确认」';
const COPY_REGEN_FAILED = '重新生成失败：';
const COPY_REGEN_BLOCKED = '没能开始重新生成：';
const JOB_POLL_MS = 1000;
const JOB_PROBLEM = /^\[(x|!)\]\s*/;
const TOAST_MS = 1600, TOAST_ERROR_MIN_MS = 6000, TOAST_MS_PER_CHAR = 120;
let DATA = null, ANSWERS = {};

async function load(){
  const r = await fetch('/api/confirm?project='+encodeURIComponent(PROJECT));
  if(!r.ok){ const e = await r.json().catch(()=>({}));
    document.getElementById('summary').textContent = e.error || '加载失败'; return; }
  DATA = await r.json(); ANSWERS = DATA.answers || {};
  if(DATA.answers_unreadable) document.getElementById('status').textContent = COPY_ANSWERS_UNREADABLE;
  renderWarnings(DATA.warnings);
  document.getElementById('title').textContent = '确认与提问';
  document.getElementById('sub').textContent =
    DATA.fallback ? '（问题由兜底模板生成）这一步决定后面怎么剪。' : '这一步决定后面怎么剪。答完点「保存并确认」。';
  const s = DATA.summary || {};
  document.getElementById('summary').textContent = s.summary || '（暂无摘要）';
  document.getElementById('keypoints').innerHTML = (s.key_points||[]).map(p=>
    `<div class="kp"><b>${fmt(num(p.at))}</b>${esc(p.text)} <span style="color:#6b7c93">· ${esc(p.why||'')}</span></div>`).join('');
  document.getElementById('cast').textContent = (s.cast||[]).length
    ? '主要角色：' + (s.cast||[]).map(c=>`${c.name}（${c.desc}）`).join('、') : '';
  renderStale();
  renderQuestions();
}
// KI-86：旧版程序生成的决策问题（主角选项是人名）：说明原因，给「重新生成」入口
function renderStale(){
  const stale = !!(DATA && DATA.stale_questions);
  document.getElementById('staleCard').style.display = stale ? 'block' : 'none';
  document.getElementById('staleHint').textContent = stale ? (DATA.stale_hint || '') : '';
}
async function regenerate(){
  const btn = document.getElementById('btnRegen');
  btn.disabled = true;
  try{
    const r = await fetch('/api/job', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({project: PROJECT, task: 'questions'})});
    const j = await r.json().catch(()=>({}));
    if(!r.ok) return setRegenStatus(COPY_REGEN_BLOCKED + (j.error || r.status), true);
    const job = await pollJob(j.job_id, setRegenStatus, COPY_REGEN_RUNNING);
    if(job && job.status === 'done'){ setRegenStatus(COPY_REGEN_DONE); toast(COPY_REGEN_DONE); return load(); }
    if(job) setRegenStatus(COPY_REGEN_FAILED + (lastProblem(job.log) || job.status), true);
  } finally { btn.disabled = false; }
}
function setRegenStatus(text, isError){
  document.getElementById('regenStatus').textContent = text;
  if(isError) toastError(text);
}
// 损坏文件 / AI 兜底等提示（与剪辑台警告栏同源，M8）
function renderWarnings(list){
  const el = document.getElementById('warnstrip'), items = Array.isArray(list) ? list : [];
  el.style.display = items.length ? 'block' : 'none';
  el.innerHTML = items.length ? `<b>${esc(COPY_WARN_TITLE)}</b><ul>${items.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>` : '';
}
function fmt(sec){ return String(Math.floor(sec/60)).padStart(2,'0')+':'+(sec%60).toFixed(1).padStart(4,'0'); }

function renderQuestions(){
  const box = document.getElementById('questions');
  box.innerHTML = (DATA.questions||[]).map((q,qi)=>{
    const chosen = ANSWERS[q.id];
    return `<div class="q"><p><span class="n">${qi+1}.</span>${esc(q.text)}</p>`
      + q.options.map((o,oi)=>{
          const sel = q.type==='multi' ? asList(chosen).includes(o.label) : chosen===o.label;
          return `<label class="opt ${sel?'sel':''}" data-act="pick" data-q="${num(qi)}" data-o="${num(oi)}">
            <input type="${q.type==='multi'?'checkbox':'radio'}" ${sel?'checked':''} tabindex="-1">
            ${esc(o.label)}<small>选了会怎样：${esc(o.effect||'')}</small></label>`;
        }).join('')
      + `</div>`;
  }).join('');
}
// data-q / data-o 只放数字下标，选项文本不进属性（GL-07）
function pick(qi, oi){
  const q = DATA.questions[qi], label = q.options[oi].label;
  if(q.type==='multi'){  // 不可变更新：不原地改磁盘读来的数组（KI-49）
    const arr = asList(ANSWERS[q.id]);
    ANSWERS = {...ANSWERS, [q.id]: arr.includes(label) ? arr.filter(x=>x!==label) : [...arr, label]};
  } else {
    ANSWERS = {...ANSWERS, [q.id]: label};
  }
  renderQuestions();
}
async function save(confirmed){
  const r = await fetch('/api/confirm/answers', {method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({project:PROJECT, answers:ANSWERS, confirmed})});
  if(!r.ok){ const e = await r.json().catch(()=>({})); return toastError(e.error || COPY_SAVE_FAILED); }
  const j = await r.json().catch(()=>({}));
  if(j.job_id) return watchJob(j.job_id);
  if(j.job_error) return setStatus(COPY_RESELECT_BLOCKED + j.job_error, true);
  toast(confirmed ? COPY_CONFIRMED : COPY_SAVED);
  setStatus(confirmed ? COPY_CONFIRMED : COPY_SAVED);
}
function setStatus(text, isError){
  document.getElementById('status').textContent = text;  // textContent：日志原文不进 HTML
  if(isError) toastError(text);
}
// 最后一行 [x] / [!] 日志就是失败原因（aicut 的人话）
function lastProblem(log){
  const lines = (Array.isArray(log) ? log : []).map(String).filter(l => JOB_PROBLEM.test(l));
  return lines.length ? lines[lines.length - 1].replace(JOB_PROBLEM, '') : '';
}
// 轮询到任务结束，返回任务快照；看不到进度返回 null（已用 report 说明）
async function pollJob(id, report, runningText){
  report(runningText);
  for(;;){
    const r = await fetch('/api/job/' + encodeURIComponent(id)).catch(() => null);
    if(!r || !r.ok){ report(COPY_RESELECT_UNKNOWN, true); return null; }
    const job = await r.json().catch(() => ({}));
    if(job.status !== 'running') return job;
    await new Promise(res => setTimeout(res, JOB_POLL_MS));
  }
}
async function watchJob(id){
  const job = await pollJob(id, setStatus, COPY_RESELECT_RUNNING);
  if(!job) return;
  if(job.status === 'done') return setStatus(COPY_RESELECT_DONE), toast(COPY_RESELECT_DONE);
  if(job.status === 'cancelled') return setStatus(COPY_RESELECT_CANCELLED, true);
  setStatus(COPY_RESELECT_FAILED + (lastProblem(job.log) || job.status), true);
}
function toast(t, ms=TOAST_MS){ const el=document.getElementById('toast'); el.textContent=t; el.classList.add('on');
  clearTimeout(el._t); el._t=setTimeout(()=>el.classList.remove('on'), ms); }
// 错误要看得完：至少 6 秒，按字数加长（KI-21）
function toastError(t){ toast(t, Math.max(TOAST_ERROR_MIN_MS, String(t).length * TOAST_MS_PER_CHAR)); }
Object.assign(ACTIONS, {  // KI-53：页面里没有 on* 属性
  // 选项是 <label> 包着 <input>：阻止默认动作，免得浏览器再替 input 点一次、多选被切换两次
  pick: (el, ev)=>{ ev.preventDefault(); pick(num(el.dataset.q), num(el.dataset.o)); },
  save: el=>save(el.dataset.confirmed === '1'),
  regenerate: ()=>regenerate(),
});
document.getElementById('nextstep').textContent = COPY_NEXT_STEP;
load();
