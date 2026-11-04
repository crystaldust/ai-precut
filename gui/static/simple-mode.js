// 剪辑台主页 · 简单模式（mode=simple）：出片模式选择、⑤ 顶栏 / 空表提示、进入 ⑤ 时自动重新选段。
// 简单模式 = ③ 的剪辑列表就是成片素材：跳过 ④ 定标准，⑤ 的分镜表只含剪辑列表里的片段。
// 步骤状态（④ 为 skipped）来自服务端 wizard；这里只负责渲染，不自己推导。

/* 界面文案：产品可直接改这里 */
const COPY_MODE_LABEL = '出片模式';
const COPY_MODE_FULL = '完整（AI 按标准选段）';
const COPY_MODE_FULL_HINT = '先定标准，AI 按标准选段，剪辑列表里的片段必进片。';
const COPY_MODE_SIMPLE = '简单（只用剪辑列表 · 推荐）';
const COPY_MODE_SIMPLE_HINT = '不定标准：只把「③ 看素材」剪辑列表里的片段按时间排成分镜表。';
const COPY_MODE_SAVED = '已切换出片模式';
const COPY_PREFS_NEW_SIMPLE = '剪辑偏好（可选，影响 ③ 的 AI 分档）';      // 简单模式不按偏好选段，但 ② 的 AI 分档仍参考它
const COPY_PREFS_SETTINGS_SIMPLE = '剪辑偏好（影响 ③ 的 AI 分档）';
const COPY_MODE_SAVED_WITH = '{note}（{mode}）';
const COPY_SIMPLE_TOTAL = '剪辑列表合计';
const COPY_SIMPLE_RESTORE = '恢复为剪辑列表';
const COPY_SIMPLE_RESTORE_ASK = '恢复为剪辑列表？当前手动修改（{n} 处）会被替换，已自动备份';
const COPY_SIMPLE_RESTORED = '已恢复为剪辑列表';
const COPY_SIMPLE_EMPTY = '剪辑列表是空的：先在「③ 看素材」把要用的片段放进剪辑列表';
const COPY_SIMPLE_EMPTY_GO = '去「③ 看素材」';
const MODES = ['full', 'simple'];
const DEFAULT_MODE = 'full';     // 旧项目没存模式 = 完整（与服务端 schema 默认一致）
const NEW_PROJECT_MODE = 'simple';   // 新建项目默认选简单（推荐）

function modeOf(){
  const m = state.data?.project?.mode ?? res()?.data?.mode;
  return MODES.includes(m) ? m : DEFAULT_MODE;
}
function isSimple(){ return modeOf() === 'simple'; }

/* ---------------- 新建 / 项目设置里的出片模式（prefix 区分 id） ---------------- */
function modeFieldHtml(prefix, mode, busy){
  const dis = busy ? ' disabled' : '';
  const radio = (value, label, hint) => `<label><input type="radio" name="${prefix}Mode"`
    + ` data-change="syncModePrefs" data-prefix="${esc(prefix)}" value="${esc(value)}"`
    + `${value === mode ? ' checked' : ''}${dis}> ${esc(label)}</label><div class="hint">${esc(hint)}</div>`;
  return `<div class="field"><label>${esc(COPY_MODE_LABEL)}</label><div class="radios">`
    + radio('simple', COPY_MODE_SIMPLE, COPY_MODE_SIMPLE_HINT) + radio('full', COPY_MODE_FULL, COPY_MODE_FULL_HINT) + '</div>'
    + (busy ? `<div class="hint">${esc(COPY_BUSY.replace('{label}', busy.label))}</div>` : '') + '</div>';
}
// 剪辑偏好区跟着出片模式走：简单模式藏起「必须保留的原话」（只用剪辑列表，用不上），标题说明还影响 ③ 的分档
function prefsTitle(prefix, mode){
  if(mode === 'simple') return prefix === 'np' ? COPY_PREFS_NEW_SIMPLE : COPY_PREFS_SETTINGS_SIMPLE;
  return prefix === 'np' ? COPY_NEW_SECTION_PREFS : COPY_SETTINGS_PREFS_TITLE;
}
function syncModePrefs(prefix){
  const mode = readMode(prefix, prefix === 'np' ? NEW_PROJECT_MODE : modeOf());
  const must = $('#' + prefix + 'MustField'), title = $('#' + prefix + 'PrefsTitle');
  if(must) must.hidden = mode === 'simple';
  if(title) title.textContent = prefsTitle(prefix, mode);
}
function readMode(prefix, fallback = DEFAULT_MODE){   // 读不到勾选项时：新建用推荐默认，设置用当前模式
  const v = $(`input[name="${prefix}Mode"]:checked`)?.value;
  return MODES.includes(v) ? v : fallback;
}
// 保存提示：模式变了就并进原来的提示（比如「需要重新选段」），只出一条
function settingsSavedNote(base){
  return base === COPY_SETTINGS_SAVED ? COPY_MODE_SAVED
    : COPY_MODE_SAVED_WITH.replace('{note}', base).replace('{mode}', COPY_MODE_SAVED);
}
// 项目设置保存之后：模式变了 → 重读状态，并按「进入」当前页处理（⑤ 要重读并可能自动重新选段）
async function afterModeChanged(project, viewBefore){
  if(!await refreshOrWarn(project) || project !== state.project) return;
  const enter = ENTER_HOOKS[state.view];
  if(enter && (state.view === 'result' || state.view !== viewBefore)) enter();
}

/* ---------------- ⑤ 顶栏 / 空表 ---------------- */
function simpleTopHtml(r, live){
  const cur = live ? fmtLong(Math.max(0, Math.round(liveTotal()))) : '', cnt = live ? state.shots.length : '';
  const edited = manualInfo()?.edited === true;
  const restore = edited ? `<button class="ghost r-restore" data-act="openRestoreAi" data-starts-job>${esc(COPY_SIMPLE_RESTORE)}</button>` : '';
  return `<div class="r-stats"><span>${esc(COPY_SIMPLE_TOTAL)} <b id="rCur">${cur}</b></span>${esc(COPY_TOP_SEP)}`
    + `<span>${esc(COPY_TOP_SHOTS)} <b id="rCnt">${cnt}</b></span>${restore}</div>`;
}
function simpleEmptyHtml(){
  return `<div class="empty">${esc(COPY_SIMPLE_EMPTY)}<br><br>`
    + `<button class="primary" data-act="go" data-step="browse">${esc(COPY_SIMPLE_EMPTY_GO)}</button></div>`;
}
// 0 镜头时「生成预览片」置灰；不带 data-starts-job，否则忙碌守卫会把它重新点亮
function previewButtonHtml(){
  return isSimple() && !state.shots.length
    ? `<button class="primary" data-act="makePreview" disabled aria-disabled="true">${esc(COPY_PREVIEW_MAKE)}</button>`
    : `<button class="primary" data-act="makePreview" data-starts-job>${esc(COPY_PREVIEW_MAKE)}</button>`;
}

/* ---------------- 进入 ⑤：过期就自动重新选段（每次进入至多一次） ---------------- */
// 手动没改过 → confirmReselect 直接覆盖；改过 → 它弹出既有的「保留 / 覆盖」询问
// 询问 / 重读状态的等待期间可能切了项目、离开了 ⑤、步骤已经新鲜：提交前再核对一次，不符就静默放弃
function autoReselectStillDue(gen, project){
  if(gen !== resultGen || state.project !== project || state.view !== 'result' || !isSimple()) return false;
  const step = stepOf('result');
  return !!step && step.status === 'stale' && step.action === 'reselect';
}
async function autoReselectOnEnter(gen, project = state.project){
  if(!autoReselectStillDue(gen, project) || currentBusy()) return;
  await confirmReselect({}, {submit: async choice => {
    if(!autoReselectStillDue(gen, project)) return false;
    return startJob('select', {manual: choice});
  }});
}

Object.assign(ACTIONS, {syncModePrefs: el => syncModePrefs(el.dataset.prefix)});
