// 剪辑台主页 · ① 新建项目弹窗与「更多 → 项目设置」（M13）。
// 时长输入沿用 KI-92：分 + 秒自由填写（10 秒–60 分钟），放在预设上面，换预设不覆盖手填值。
// 剪辑偏好（FR-14）：信息 / 情绪、片子给谁看、必须保留的原话（最多 3 句）；创建后直接开始分析。

/* 界面文案：产品可直接改这里 */
const COPY_NEW_TITLE = '新建项目';
const COPY_NEW_SECTION_MATERIAL = '素材与成片';
const COPY_NEW_SECTION_PREFS = '剪辑偏好（可跳过）';
const COPY_NEW_TARGET_LABEL = '成片时长（自己定，预设只给默认值）';
const COPY_TARGET_RANGE = '时长要在 10 秒到 60 分钟之间（秒填 0–59 的整数）';
const COPY_TONE_LABEL = '更想保留';
const COPY_TONE_INFO = '信息';
const COPY_TONE_EMOTION = '情绪';
const COPY_TONE_BALANCED_LEGACY = '均衡（改版前的设置）';  // P4：旧项目的偏好是均衡时才出现
const COPY_AUDIENCE = '片子给谁看';
const COPY_AUDIENCE_PLACEHOLDER = '例如：准备报名的家长';
const COPY_MUST_LINES = '必须保留的原话（每行一句，最多 3 句）';
const COPY_MUST_LINES_HINT = '这些句子无论档位如何都会进片。';
const COPY_MUST_LINES_TOO_MANY = '必须保留的原话最多 3 句';
const COPY_CREATE = '创建并开始分析';
const COPY_CANCEL = '取消';
const COPY_SETTINGS_TITLE_PROJECT = '项目设置';
const COPY_SETTINGS_PREFS_TITLE = '剪辑偏好';
const COPY_SETTINGS_SAVE = '保存';
const COPY_SETTINGS_SAVED = '项目设置已保存';
const COPY_SETTINGS_NOTE = '分析之后改了剪辑偏好或预设：「② 分析」会标为「需要更新」，不会自动重跑。';
const COPY_CREATED = '项目已创建';
const TARGET_MIN_SEC = 10, TARGET_MAX_SEC = 3600;  // 与 pipeline/schema.py 的 TARGET_MIN / TARGET_MAX 一致
const MUST_LINES_MAX = 3;                          // 与 gui/project_routes.py 的 MUST_LINES_MAX 一致
const DEFAULT_TONE = 'info';                       // P4：新建默认「信息」

/* 时长输入：分 + 秒两个框，任意时长（10 秒–60 分钟），不受预设限制 */
function durationFields(prefix, sec){
  sec = Math.round(num(sec));
  const m = sec ? Math.floor(sec/60) : '', s = sec ? sec%60 : '';
  return `<div style="display:flex;gap:6px;align-items:center">
    <input id="${prefix}Min" type="number" min="0" max="60" step="1" value="${m}" style="width:80px" data-input="markTargetTouched"> 分
    <input id="${prefix}Sec" type="number" min="0" max="59" step="1" value="${s}" style="width:80px" data-input="markTargetTouched"> 秒
  </div>`;
}
function readDuration(prefix){
  const part = id => { const v = String($('#'+prefix+id)?.value ?? '').trim();
    return v === '' ? 0 : (/^\d+$/.test(v) ? Number(v) : NaN); };
  const m = part('Min'), s = part('Sec');
  if(!(s < 60)) return 0;  // NaN 也走这里
  const total = m*60 + s;
  return total >= TARGET_MIN_SEC && total <= TARGET_MAX_SEC ? total : 0;
}
function markTargetTouched(){ state.npTouched = true; }
/* ---------------- 剪辑偏好字段（新建与项目设置共用，prefix 区分 id） ---------------- */
function prefsFieldsHtml(prefix, cal){
  const tone = cal.tone || DEFAULT_TONE;
  const options = [['info', COPY_TONE_INFO], ['emotion', COPY_TONE_EMOTION],
                   ...(tone === 'balanced' ? [['balanced', COPY_TONE_BALANCED_LEGACY]] : [])];
  const radios = options.map(([value, label]) =>
    `<label><input type="radio" name="${prefix}Tone" value="${esc(value)}"${value === tone ? ' checked' : ''}> ${esc(label)}</label>`).join('');
  return `<div class="field"><label>${esc(COPY_TONE_LABEL)}</label><div class="radios">${radios}</div></div>
    <div class="field"><label>${esc(COPY_AUDIENCE)}</label>
      <input id="${prefix}Audience" placeholder="${esc(COPY_AUDIENCE_PLACEHOLDER)}" value="${esc(cal.audience || '')}"></div>
    <div class="field"><label>${esc(COPY_MUST_LINES)}</label>
      <textarea id="${prefix}Must" rows="3">${esc(cal.must_lines || '')}</textarea>
      <div class="hint">${esc(COPY_MUST_LINES_HINT)}</div></div>`;
}
// 读表单里的偏好；原话超过 3 句 → toast 并返回 null（不提交）
function readCalibration(prefix){
  const tone = $(`input[name="${prefix}Tone"]:checked`)?.value || DEFAULT_TONE;
  const audience = String($('#'+prefix+'Audience')?.value ?? '').trim();
  const lines = String($('#'+prefix+'Must')?.value ?? '').split(/[\n；]/).map(x=>x.trim()).filter(Boolean);
  if(lines.length > MUST_LINES_MAX){ toast(COPY_MUST_LINES_TOO_MANY); return null; }
  return {tone, audience, must_lines: lines.join('\n')};
}
function presetWarningsHtml(warnings){
  return (warnings||[]).map(w=>`<div class="hint" style="color:var(--warn)">${esc(w)}</div>`).join('');
}

/* ---------------- ① 新建项目 ---------------- */
async function openNew(){
  state.npTouched = false;
  let presets, warnings;
  try{ ({presets, warnings} = await api('/api/presets')); }
  catch(e){ toast(e.message, TOAST_ERROR_MS); return; }
  state.presets = presets;
  showModal(COPY_NEW_TITLE, `
    <h3>${esc(COPY_NEW_SECTION_MATERIAL)}</h3>
    <div class="field"><label>素材文件</label>
      <div style="display:flex;gap:8px">
        <input id="npPath" placeholder="点右边选择…" readonly>
        <button class="ghost" data-act="pickFile">选择</button>
      </div></div>
    <div class="field"><label>项目名（文件夹名，别用斜杠）</label><input id="npName" placeholder="例如 2026-09-15_探店"></div>
    <div class="field"><label>片名（会显示在剪映草稿上）</label><input id="npTitle" placeholder="例如 九月一号"></div>
    <div class="field"><label>${esc(COPY_NEW_TARGET_LABEL)}</label>${durationFields('np', 0)}</div>
    <div class="field"><label>风格预设</label>
      <select id="npPreset" data-change="syncTarget">${presets.map(p=>`<option value="${esc(p.key)}">${esc(p.name)} · ${esc(p.platform)}</option>`).join('')}</select>
      ${presetWarningsHtml(warnings)}
    </div>
    <details class="prefs" id="npPrefs"><summary>${esc(COPY_NEW_SECTION_PREFS)}</summary>${prefsFieldsHtml('np', {tone: DEFAULT_TONE})}</details>
    <button class="primary" data-act="createAndAnalyze">${esc(COPY_CREATE)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_CANCEL)}</button>`);
  syncTarget();
}
function syncTarget(){  // 换预设只在剪辑师还没自己填过时长时带出默认值
  if(state.npTouched || !$('#npMin')) return;
  const sec = Math.round(num((state.presets||[]).find(x=>x.key===$('#npPreset')?.value)?.duration));
  $('#npMin').value = sec ? String(Math.floor(sec/60)) : '';
  $('#npSec').value = sec ? String(sec%60) : '';
}
async function pickFile(){
  let path;
  try{ ({path} = await postJson('/api/pick', {})); }
  catch(e){ toast(e.message, TOAST_ERROR_MS); return; }
  if(path){ $('#npPath').value = path; if(!$('#npName').value){
    $('#npName').value = path.split('/').pop().replace(/\.[^.]+$/,'');
    $('#npTitle').value = $('#npName').value; } }
}
let creating = false;  // 创建中：重复点击不再发第二个 /api/new
async function createAndAnalyze(){
  if(creating) return;
  const material=$('#npPath').value, name=$('#npName').value.trim(), title=$('#npTitle').value.trim();
  const preset=$('#npPreset').value, target=readDuration('np');
  if(!material) return toast('先选素材');
  if(!target) return toast(COPY_TARGET_RANGE);
  if(!name) return toast('填个项目名');
  const calibration = readCalibration('np');
  if(!calibration) return;
  creating = true;
  const button = $('[data-act="createAndAnalyze"]');
  if(button) button.disabled = true;
  try{
    try{
      await postJson('/api/new', {material, name, title, preset, target, calibration});
    }catch(e){ toast(e.message, TOAST_ERROR_MS); return; }  // 创建失败：弹窗不关，不起任务
    closeModal();
    try{ await loadProjects(); }  // KI-57：只切到刚建的项目，不再按地址栏 hash 抢着切别的
    catch(e){ toast(e.message, TOAST_ERROR_MS); }  // 项目栏没刷出来也要继续进新项目
    await selectProject(name);
    await startAnalysis();  // 创建即开始分析；缺 Key / 告知在 ② 页内联处理
    toast(COPY_CREATED);
  }finally{
    creating = false;
    if(button) button.disabled = false;
  }
}

/* ---------------- 更多 → 项目设置 ---------------- */
async function openProjectSettings(){
  if(!state.project || !state.data) return toast('先选项目');
  const project = state.project;  // 弹窗是为这个项目开的：等待期间切走就不再打开
  const cfg = state.data.project;
  const cal = {...(cfg.calibration || {}), tone: (cfg.calibration || {}).tone || 'balanced'};  // 没存过 = 均衡（旧默认）
  let presets, warnings;
  try{ ({presets, warnings} = await api('/api/presets')); }
  catch(e){ return toast(e.message, TOAST_ERROR_MS); }
  if(project !== state.project) return;
  const options = presets.map(p=>`<option value="${esc(p.key)}"${p.key === cfg.preset ? ' selected' : ''}>${esc(p.name)} · ${esc(p.platform)}</option>`).join('');
  showModal(COPY_SETTINGS_TITLE_PROJECT, `
    <div class="field"><label>片名（会显示在剪映草稿上）</label><input id="psTitle" value="${esc(cfg.title || '')}"></div>
    <div class="field"><label>风格预设</label><select id="psPreset">${options}</select>${presetWarningsHtml(warnings)}</div>
    <h3>${esc(COPY_SETTINGS_PREFS_TITLE)}</h3>
    ${prefsFieldsHtml('ps', cal)}
    <p class="hint">${esc(COPY_SETTINGS_NOTE)}</p>
    <button class="primary" data-act="saveProjectSettings">${esc(COPY_SETTINGS_SAVE)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_CANCEL)}</button>`);
}
async function saveProjectSettings(){
  const project = state.project;
  const calibration = readCalibration('ps');
  if(!project || !calibration) return;
  let r;
  try{
    r = await postJson('/api/project/settings', {project, title: $('#psTitle').value.trim(),
                                                  preset: $('#psPreset').value, calibration});
  }catch(e){ toast(e.message, TOAST_ERROR_MS); return; }
  if(project !== state.project){ closeModal(); return; }  // 保存期间切走了项目：不把别人的状态画进当前页面
  state.data = {...state.data, project: r.project, wizard: r.wizard};  // ② 可能因此变成「需要更新」
  state.view = resolveView(r.wizard, state.view);  // 当前页若因此不可用了，和刷新一样回到下一步
  closeModal(); renderChrome(); renderView(); toast(COPY_SETTINGS_SAVED);
  loadProjects().catch(e=>toast(e.message, TOAST_ERROR_MS));
}

Object.assign(ACTIONS, {
  markTargetTouched: ()=>markTargetTouched(), syncTarget: ()=>syncTarget(),
  openNew: ()=>openNew(), pickFile: ()=>pickFile(), createAndAnalyze: ()=>createAndAnalyze(),
  openProjectSettings: ()=>openProjectSettings(), saveProjectSettings: ()=>saveProjectSettings(),
});
