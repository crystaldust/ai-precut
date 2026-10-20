// 剪辑台主页 · 基础设施（M13 从 index.js 拆出）：状态、请求、提示、格式化、弹窗。
// 事件一律走 common.js 的委托（data-act / data-input / data-change），不用 on* 属性。
const $ = s => document.querySelector(s);
const state = {
  project: null, data: null, view: null,          // view：正在看的步骤 key（analyze / browse / criteria / result / export）
  sel: null, shots: [], projects: [], presets: [],
  pinned: false, railOpen: false, npTouched: false, modalKind: null,
  browse: null,                                   // ③ 看素材的页面状态（step-browse.js）；切项目 / 重新进入即清空
  criteria: null,                                 // ④ 定标准的页面状态（step-criteria.js）；同上
  result: null,                                   // ⑤ 看结果的页面状态（step-result.js）；同上
  block: null,                                    // ② 页内联的前置条件：{need: 'consent'|'keys', message, missing, cfg}
};

const TOAST_ERROR_MS = 6000;
const MB = 1e6;
const POST_HEADERS = {'Content-Type': 'application/json'};

function toast(msg, ms=1800){
  const t = $('#toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove('on'), ms);
}
async function api(path, opt){
  const r = await fetch(path, opt);
  const j = await r.json().catch(()=>({}));
  if(!r.ok){  // 状态码和响应体挂在 Error 上：任务弹窗要据此区分 409 冲突 / 缺告知 / 缺 Key
    const e = new Error(j.error || ('请求失败 '+r.status)); e.status = r.status; e.data = j; throw e;
  }
  return j;
}
function postJson(path, body){
  return api(path, {method: 'POST', headers: POST_HEADERS, body: JSON.stringify(body ?? {})});
}
function fmt(sec){
  sec = Math.max(0, sec||0);
  const m = Math.floor(sec/60), s = sec%60;
  return `${String(m).padStart(2,'0')}:${s.toFixed(1).padStart(4,'0')}`;
}
function fmtMinSec(sec){
  sec = Math.round(num(sec));
  return sec>=60 ? `${Math.floor(sec/60)} 分 ${sec%60} 秒` : `${sec} 秒`;
}
function fmtLong(sec){
  const h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=Math.floor(sec%60);
  return h? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
          : `${m}:${String(s).padStart(2,'0')}`;
}

// 主区内容的缓存：renderView 发现内容没变就不重画（轮询不会打断输入框和滚动）
let stageHtml = null;
function setStage(html){ stageHtml = html; $('#stage').innerHTML = html; }
function stageIs(html){ return html === stageHtml; }

/* ---------------- 弹窗 ---------------- */
function logLine(t){ const el=$('#log'); if(el){ el.textContent += (el.textContent?'\n':'')+t; el.scrollTop=el.scrollHeight; } }
function showModal(title, html){
  if(state.modalKind === 'reselect') reselectDismissed();  // 被别的弹窗顶掉的询问等于取消（reselect.js）
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = html;
  $('#mask').classList.add('on');
  state.modalKind = null;  // 任务日志窗口由 jobs.js 的 jobModal 在 showModal 之后标成 'job'
}
function closeModal(){
  if(state.modalKind === 'reselect') reselectDismissed();  // 重新选段询问被关掉 = 取消（reselect.js）
  $('#mask').classList.remove('on'); state.modalKind = null; state.recording = null;
}
// Esc / 点遮罩空白处关闭（任务运行中除外，见 jobs.js 的 modalDismissable）
document.addEventListener('keydown', e=>{
  if(e.key === 'Escape' && $('#mask').classList.contains('on') && modalDismissable()) closeModal();
});
$('#mask').addEventListener('click', e=>{
  const mask = $('#mask');
  if(e.target === mask && modalDismissable()) closeModal();
});
Object.assign(ACTIONS, {closeModal: ()=>closeModal()});
