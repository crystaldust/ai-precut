// 剪辑台主页 · 快捷键（M13c）：键位解析、冲突检查、「更多 → 快捷键」录制编辑器、全局按键分发。
// 键位用 KeyboardEvent.code（与输入法 / 键盘布局无关）；存在服务端偏好里（/api/prefs，D5），本文件不碰本地存储。
// 默认值与标签必须和 gui/prefs.py 一致（tests/test_frontend_shortcuts.py 比对）。

/* 界面文案：产品可直接改这里 */
const COPY_SHORTCUTS_TITLE = '快捷键';
const COPY_SHORTCUTS_HINT = '点「按下新键」再按想用的键；Esc 取消。⌘Z / Ctrl+Z 固定也是撤销，不能改。设置记在本机，所有项目通用。';
const COPY_RECORD = '按下新键';
const COPY_RECORDING = '请按键…';
const COPY_RESET_KEYS = '恢复默认';
const COPY_DONE = '完成';
const COPY_KEY_CONFLICT = '「{key}」已经用于「{other}」';
const COPY_KEY_COMBO = '不支持组合键，请只按一个键';
const COPY_KEY_BAD = '这个键不能用：只能是单个字母、数字、空格、方向键或常用符号键';
const DEFAULT_SHORTCUTS = {play: 'Space', prev: 'ArrowUp', next: 'ArrowDown', toggle_list: 'KeyS',
  mark_usable: 'KeyA', mark_waste: 'KeyD', mark_unusable: 'KeyX', undo: 'KeyZ'};
const ACTION_LABELS = {play: '播放 / 暂停', prev: '上一段', next: '下一段', toggle_list: '放入 / 移出剪辑列表',
  mark_usable: '标为可用', mark_waste: '标为废片', mark_unusable: '标为不可用', undo: '撤销'};
const KEY_LABELS = {Space: '空格', ArrowUp: '↑', ArrowDown: '↓', ArrowLeft: '←', ArrowRight: '→', Comma: ',',
  Period: '.', Slash: '/', Semicolon: ';', Quote: "'", BracketLeft: '[', BracketRight: ']', Minus: '-',
  Equal: '=', Backquote: '`', Backslash: '\\'};
const KEY_CODE_RE = /^(Key[A-Z]|Digit[0-9]|Space|Arrow(Up|Down|Left|Right)|Comma|Period|Slash|Semicolon|Quote|Bracket(Left|Right)|Minus|Equal|Backquote|Backslash)$/;
const MODIFIER_CODES = new Set(['ShiftLeft', 'ShiftRight', 'ControlLeft', 'ControlRight', 'AltLeft', 'AltRight',
  'MetaLeft', 'MetaRight', 'CapsLock', 'Fn']);
const TYPING_TAGS = ['INPUT', 'TEXTAREA', 'SELECT'];
const NATIVE_SPACE_TAGS = ['VIDEO', 'BUTTON'];  // 焦点在播放器 / 按钮上时，空格交给浏览器原本的行为
const REPEAT_BLOCKED = new Set(['toggle_list', 'mark_usable', 'mark_waste', 'mark_unusable', 'undo']);  // 长按不来回切
const UNDO_ALIAS_CODE = 'KeyZ';
const TOAST_NOTE_MS = 3200;

state.shortcuts = {...DEFAULT_SHORTCUTS};
state.recording = null;   // 正在录制的动作名（编辑器里点了「按下新键」）

function keyLabel(code){
  if(/^(Key|Digit)/.test(code)) return code.slice(-1);
  return KEY_LABELS[code] || code;
}
// 事件 → 动作名；输入框 / 输入法组合 / 带修饰键一律不触发（⌘Z、Ctrl+Z 固定是撤销的别名）
function keyAction(ev, map){
  if(!ev || !map || !ev.code || ev.isComposing) return null;
  const t = ev.target;
  if(t && (TYPING_TAGS.includes(t.tagName) || t.isContentEditable)) return null;
  const mod = ev.metaKey || ev.ctrlKey;
  if(mod && !ev.altKey && !ev.shiftKey && ev.code === UNDO_ALIAS_CODE) return 'undo';
  if(mod || ev.altKey || ev.shiftKey) return null;
  return Object.keys(map).find(a => map[a] === ev.code) || null;
}
function findConflict(map, action, code){
  return Object.keys(map).find(a => a !== action && map[a] === code) || null;
}
function applyPrefs(r){
  if(r && r.shortcuts && typeof r.shortcuts === 'object') state.shortcuts = {...DEFAULT_SHORTCUTS, ...r.shortcuts};
}

/* ---------------- 分发 ---------------- */
function modalOpen(){ return $('#mask').classList.contains('on'); }
function runShortcut(action){
  const withCur = fn => { const s = curSeg(); return s ? fn(s) : undefined; };
  const runners = {
    play: () => togglePlay(), prev: () => moveCur(-1), next: () => moveCur(1),
    toggle_list: () => withCur(toggleList), mark_usable: () => withCur(s => markLevel(s, 3)),
    mark_waste: () => withCur(s => markLevel(s, 1)), mark_unusable: () => withCur(markUnusable),
    undo: () => undoLast(),
  };
  return runners[action] && runners[action]();
}
function onKey(ev){
  if(state.recording) return recordKey(ev);
  if(state.view !== 'browse' || !state.browse || modalOpen()) return;
  const action = keyAction(ev, state.shortcuts);
  if(!action) return;
  const tag = ev.target && ev.target.tagName;
  if(action === 'play' && NATIVE_SPACE_TAGS.includes(tag)) return;
  ev.preventDefault();   // 空格不能滚动页面
  if(ev.repeat && REPEAT_BLOCKED.has(action)) return;
  const out = runShortcut(action);
  if(out && typeof out.catch === 'function') out.catch(e => toast((e && e.message) || String(e), TOAST_ERROR_MS));
}
// 捕获阶段：录制时 Esc 只取消录制，不会同时关掉弹窗
document.addEventListener('keydown', onKey, true);

/* ---------------- 编辑器 ---------------- */
function editorHtml(){
  const rows = Object.keys(ACTION_LABELS).map(id => {
    const rec = state.recording === id;
    return `<tr><td>${esc(ACTION_LABELS[id])}</td><td><kbd>${esc(keyLabel(state.shortcuts[id] || ''))}</kbd></td>`
      + `<td><button class="ghost${rec ? ' on' : ''}" data-act="recordKey" data-action="${esc(id)}">`
      + `${esc(rec ? COPY_RECORDING : COPY_RECORD)}</button></td></tr>`;
  }).join('');
  return `<p class="hint">${esc(COPY_SHORTCUTS_HINT)}</p><table class="keys">${rows}</table>`
    + `<div class="hint key-msg" id="shortcutMsg" role="status"></div>`
    + `<div class="job-actions"><button class="ghost" data-act="resetShortcuts">${esc(COPY_RESET_KEYS)}</button>`
    + `<button class="primary" data-act="closeModal">${esc(COPY_DONE)}</button></div>`;
}
function renderShortcutEditor(){ if(state.modalKind === 'shortcuts') $('#modalBody').innerHTML = editorHtml(); }
function openShortcuts(){
  state.recording = null;
  showModal(COPY_SHORTCUTS_TITLE, editorHtml());
  state.modalKind = 'shortcuts';
}
function shortcutMsg(text){
  const m = $('#shortcutMsg'); if(!m) return;
  m.textContent = text;
}
function startRecord(action){
  if(!ACTION_LABELS[action]) return;
  state.recording = action;
  renderShortcutEditor();
}

function recordKey(ev){
  ev.preventDefault(); ev.stopPropagation();
  if(ev.repeat || ev.isComposing || MODIFIER_CODES.has(ev.code)) return;
  const action = state.recording;
  if(ev.code === 'Escape'){ state.recording = null; renderShortcutEditor(); return; }
  if(ev.metaKey || ev.ctrlKey || ev.altKey || ev.shiftKey) return shortcutMsg(COPY_KEY_COMBO);
  if(!KEY_CODE_RE.test(ev.code || '')) return shortcutMsg(COPY_KEY_BAD);
  if(state.shortcuts[action] === ev.code){ state.recording = null; renderShortcutEditor(); return; }
  const other = findConflict(state.shortcuts, action, ev.code);
  if(other) return shortcutMsg(COPY_KEY_CONFLICT.replace('{key}', keyLabel(ev.code))
    .replace('{other}', ACTION_LABELS[other]));
  return saveShortcut(action, ev.code);
}
async function saveShortcut(action, code){
  state.recording = null;
  try{
    applyPrefs(await postJson('/api/prefs', {shortcuts: {[action]: code}}));  // 冲突 / 非法键位由服务端再校验一次
    renderShortcutEditor();
  }catch(e){ renderShortcutEditor(); shortcutMsg(e.message); }
}
async function resetShortcuts(){
  state.recording = null;
  try{
    applyPrefs(await postJson('/api/prefs/reset', {what: 'shortcuts'}));
    renderShortcutEditor();
  }catch(e){ shortcutMsg(e.message); }
}

Object.assign(ACTIONS, {
  openShortcuts: () => openShortcuts(), recordKey: el => startRecord(el.dataset.action),
  resetShortcuts: () => resetShortcuts(),
});
