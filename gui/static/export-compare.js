// 剪辑台主页 · ⑥ 导出的对比两版与「回到这一版」（M14，KI-94）。
// 对比：勾选两个版本 → GET /api/versions/compare → 两个预览片并排同时播放 + 镜头差异；回到这一版：确认后恢复该版分镜表并去 ⑤。

/* 界面文案：产品可直接改这里 */
const COPY_COMPARE = '对比两版';
const COPY_COMPARE_PICK = '选两个版本';
const COPY_COMPARE_CLOSE = '关闭对比';
const COPY_PLAY_BOTH = '同时播放';
const COPY_COMPARE_LOADING = '正在比较…';
const COPY_COMPARE_FAILED = '没能比较这两版：{reason}';
const COPY_COMPARE_RETRY = '重试';
const COPY_COMPARE_NO_PREVIEW = '这一版没有预览片';
const COPY_DIFF_SUMMARY = '新增 {a} · 删除 {r} · 改字幕 {s} · 改入出点 {t}';
const COPY_DIFF_REORDERED = '镜头顺序也变了';
const COPY_DIFF_NONE = '两版的分镜表没有区别';
const COPY_DIFF_ADDED = '新增第 {n} 镜「{sub}」';
const COPY_DIFF_REMOVED = '删除了 {tc} 那一镜';
const COPY_DIFF_SUB = '第 {n} 镜字幕：「{before}」→「{after}」';
const COPY_DIFF_RETIMED = '第 {n} 镜改了入出点';
const COPY_DIFF_MORE = '等另外 {n} 条';
const COPY_RESTORE = '回到这一版';
const COPY_RESTORE_TITLE = '回到 {v}';
const COPY_RESTORE_ASK = '用 {v} 的分镜表替换当前分镜表？当前的分镜表会自动备份，不会删除任何版本。';
const COPY_RESTORE_GO = '确定';
const COPY_VERSION_RESTORED = '已回到 {v} 的分镜表（{n} 镜）';
const COPY_RESTORED_OTHER = '「{project}」{text}';
const COPY_RESTORE_DROPPED = '；已去掉 {n} 个含不可用片段的镜头';
const COPY_RESTORE_NO_SNAPSHOT = '这一版是改版前生成的，没有留存分镜表，不能回到这一版';
const COPY_RESTORE_SAVE_FIRST = '分镜表还没保存成功，先不回到这一版';
const DIFF_LIST_MAX = 8;
const DIFF_SUB_CHARS = 12;
const DIFF_SUBTITLE_CHARS = 30;   // 改字幕明细里「之前 / 之后」各最多显示这么多字
const ELLIPSIS = '…';
const SECONDS_PER_MIN_C = 60;
const RESTORED_TOAST_MS = 3500;
const COMPARE_VIDEOS = ['#xvA', '#xvB'];

const exportUi = {compare: false, picks: [], data: null, error: null, pair: null, seq: 0,
                  restoring: new Set(), bound: []};   // restoring：正在回到某一版的项目名（按项目，切项目不会互相释放）
function versionNum(name){ return Number((VERSION_NUM.exec(name) || [])[1]) || 0; }

/* ---------------- 状态 ---------------- */
function unbindCompare(){
  exportUi.bound.forEach(b => { b.v.removeEventListener('play', b.onPlay); b.v.removeEventListener('pause', b.onPause); });
  exportUi.bound = [];
}
function pauseCompare(){   // 暂停并卸载：不让离开 ⑥ 之后还在后台缓冲 / 出声
  unbindCompare();
  COMPARE_VIDEOS.forEach(sel => {
    const v = $(sel);
    if(!v) return;
    if(typeof v.pause === 'function') v.pause();
    if(typeof v.removeAttribute === 'function') v.removeAttribute('src');
    if(typeof v.load === 'function') v.load();
  });
}
// 两个预览片的播放 / 暂停互相跟随（拖进度不跟随）；元素被换掉（页面重画）后在 renderView 里重新绑
function paintCompare(){
  if(!exportUi.compare || state.view !== 'export') return;
  const vids = COMPARE_VIDEOS.map(sel => $(sel));
  if(vids.some(v => !v)) return;
  exportUi.bound = exportUi.bound.filter(b => {
    const keep = vids.includes(b.v);
    if(!keep){ b.v.removeEventListener('play', b.onPlay); b.v.removeEventListener('pause', b.onPause); }
    return keep;
  });
  vids.forEach((v, k) => {
    if(exportUi.bound.some(b => b.v === v)) return;
    const other = () => vids[1 - k];
    const onPlay = () => { if(other().paused) playQuietly(other()); };
    const onPause = () => { if(!other().paused) other().pause(); };
    v.addEventListener('play', onPlay); v.addEventListener('pause', onPause);
    exportUi.bound.push({v, onPlay, onPause});
  });
}
function stopCompare(){   // 暂停并清空对比状态（不重画）
  pauseCompare();
  exportUi.compare = false; exportUi.picks = []; exportUi.data = null; exportUi.error = null; exportUi.pair = null; exportUi.seq += 1;
}
function closeCompare(){ stopCompare(); renderView(); }
function leaveExport(){ stopCompare(); }   // 离开 ⑥ / 切项目 / 刷新后被带离 ⑥：视频随页面一起换掉前先停
function resetExport(){ stopCompare(); }   // 不清 restoring：别的项目里还在进行的「回到这一版」要自己收尾
function toggleCompare(){
  if(exportUi.compare) return closeCompare();
  exportUi.compare = true;
  renderView();
}

/* ---------------- 页面片段（step-export.js 的 viewExport 拼进去） ---------------- */
function compareToolbarHtml(){
  if(exportVersions().length < 2) return '';
  const label = exportUi.compare ? COPY_COMPARE_CLOSE : COPY_COMPARE;
  const hint = exportUi.compare ? ` <span class="hint">${esc(COPY_COMPARE_PICK)}</span>` : '';
  return `<button class="ghost" data-act="toggleCompare">${esc(label)}</button>${hint}`;
}
function compareBoxHtml(i){
  if(!exportUi.compare) return '';
  const v = exportVersions()[i];
  const on = v && exportUi.picks.includes(v.name) ? ' checked' : '';
  return `<input type="checkbox" data-change="pickCompare" data-i="${num(i)}"${on}> `;
}
function sideHtml(side, id){
  const src = side.preview
    ? `<video id="${id}" src="/media/${encodeURIComponent(state.project)}/preview/${encodeURIComponent(side.name)}" controls preload="metadata"></video>`
    : `<p class="hint">${esc(COPY_COMPARE_NO_PREVIEW)}</p>`;
  return `<div class="cmp-side"><h4>${esc(side.name)} <span class="hint">${num(side.shots)} 镜 · ${fmtLong(num(side.duration))}</span></h4>${src}</div>`;
}
function clock(sec){ sec = num(sec); return String(Math.floor(sec / SECONDS_PER_MIN_C)).padStart(2, '0') + ':' + String(Math.floor(sec % SECONDS_PER_MIN_C)).padStart(2, '0'); }
function cut(text, max){ const t = String(text ?? ''); return t.length > max ? t.slice(0, max) + ELLIPSIS : t; }
function diffLines(d){
  const n = x => num(x.index) + 1;
  return [
    ...d.added.map(x => fillCopy(COPY_DIFF_ADDED, {n: n(x), sub: String((x.shot || {}).sub || '').slice(0, DIFF_SUB_CHARS)})),
    ...d.removed.map(x => fillCopy(COPY_DIFF_REMOVED, {tc: clock((x.shot || {}).in)})),
    ...d.sub_changed.map(x => fillCopy(COPY_DIFF_SUB, {n: n(x), before: cut(x.before, DIFF_SUBTITLE_CHARS), after: cut(x.after, DIFF_SUBTITLE_CHARS)})),
    ...d.retimed.map(x => fillCopy(COPY_DIFF_RETIMED, {n: n(x)})),
  ];
}
function diffHtml(data){
  const d = data.diff;
  if(!d) return `<p class="hint">${esc(data.note || '')}</p>`;
  const summary = fillCopy(COPY_DIFF_SUMMARY, {a: d.added.length, r: d.removed.length, s: d.sub_changed.length, t: d.retimed.length})
    + (d.reordered ? ' · ' + COPY_DIFF_REORDERED : '');
  const lines = diffLines(d);
  const more = lines.length - DIFF_LIST_MAX;
  if(!lines.length && !d.reordered) return `<p>${esc(COPY_DIFF_NONE)}</p>`;
  return `<p><b>${esc(summary)}</b></p><ul class="changes">${lines.slice(0, DIFF_LIST_MAX).map(l => `<li>${esc(l)}</li>`).join('')}</ul>`
    + (more > 0 ? `<p class="hint">${esc(fillCopy(COPY_DIFF_MORE, {n: more}))}</p>` : '');
}
function comparePanelHtml(){
  if(!exportUi.compare) return '';
  const data = exportUi.data;
  if(exportUi.error) return `<section class="ver cmp"><p class="blocked-note">${esc(fillCopy(COPY_COMPARE_FAILED, {reason: exportUi.error}))}</p>
    <button class="primary" data-act="retryCompare">${esc(COPY_COMPARE_RETRY)}</button></section>`;
  if(!data) return `<section class="ver cmp"><p class="hint">${esc(exportUi.picks.length === 2 ? COPY_COMPARE_LOADING : COPY_COMPARE_PICK)}</p></section>`;
  return `<section class="ver cmp"><div class="cmp-vids">${sideHtml(data.a, 'xvA')}${sideHtml(data.b, 'xvB')}</div>
    <div class="toolbar"><button class="primary" data-act="playBoth">${esc(COPY_PLAY_BOTH)}</button>
      <button class="ghost" data-act="closeCompare">${esc(COPY_COMPARE_CLOSE)}</button></div>${diffHtml(data)}</section>`;
}

/* ---------------- 选版本与加载 ---------------- */
async function loadCompare(a, b){
  const seq = ++exportUi.seq, project = state.project;
  exportUi.pair = [a, b]; exportUi.error = null;
  try{
    const data = await api(`/api/versions/compare?project=${encodeURIComponent(project)}&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
    if(seq !== exportUi.seq || state.project !== project || state.view !== 'export') return;   // 期间又选了别的 / 离开了：丢掉
    exportUi.data = data;
  }catch(e){
    if(seq !== exportUi.seq || state.project !== project) return;
    exportUi.error = e.message;   // 面板里说明原因并给「重试」，不停在「正在比较…」
  }
  renderView();
}
function retryCompare(){ return exportUi.pair ? loadCompare(...exportUi.pair) : undefined; }
function pickCompare(i){
  const v = exportVersions()[i];
  if(!v || !exportUi.compare) return;
  const rest = exportUi.picks.filter(n => n !== v.name);
  exportUi.picks = rest.length < exportUi.picks.length ? rest : [...rest, v.name].slice(-2);   // 选第三个：替换最早选的
  exportUi.data = null; exportUi.error = null; exportUi.pair = null; exportUi.seq += 1;
  if(exportUi.picks.length < 2){ renderView(); return; }
  const [a, b] = [...exportUi.picks].sort((x, y) => versionNum(x) - versionNum(y));   // a = 较早那版
  renderView();
  return loadCompare(a, b);
}
function whenReady(v){   // 元数据没到时设 currentTime 会被忽略：等 loadedmetadata（出错也放行）
  if(v.readyState >= 1) return Promise.resolve();
  return new Promise(resolve => { ['loadedmetadata', 'error'].forEach(t => v.addEventListener(t, resolve, {once: true})); });
}
async function playBoth(){
  const vids = COMPARE_VIDEOS.map(sel => $(sel)).filter(Boolean);
  await Promise.all(vids.map(whenReady));
  vids.forEach(v => { v.currentTime = 0; });
  vids.forEach(v => playQuietly(v));
}

/* ---------------- 回到这一版 ---------------- */
function askRestore(i){
  const v = exportVersions()[i];
  if(!v) return;
  if(!v.has_snapshot){ toast(COPY_RESTORE_NO_SNAPSHOT, TOAST_ERROR_MS); return; }
  showModal(fillCopy(COPY_RESTORE_TITLE, {v: v.name}), `<p>${esc(fillCopy(COPY_RESTORE_ASK, {v: v.name}))}</p><div class="job-actions">
    <button class="primary" data-act="restoreVersionGo" data-v="${esc(v.name)}">${esc(COPY_RESTORE_GO)}</button>
    <button class="ghost" data-act="closeModal">${esc(COPY_EXPORT_CANCEL)}</button></div>`);
}
async function restoreVersion(name){
  closeModal();
  const project = state.project;
  if(!project || exportUi.restoring.has(project)) return;   // 同一项目同一时刻只做一次
  exportUi.restoring.add(project);
  const here = () => state.project === project;   // 等待期间可能切到了别的项目：别动那个项目的页面
  try{
    if(await flushPendingSave() === false){ toast(COPY_RESTORE_SAVE_FIRST, TOAST_ERROR_MS); return; }   // 排队中的保存会把恢复的表又盖掉
    const r = await postJson('/api/versions/restore', {project, version: name});
    const dropped = Array.isArray(r.dropped) ? r.dropped.length : 0;
    const text = fillCopy(COPY_VERSION_RESTORED, {v: name, n: num(r.count)}) + (dropped ? fillCopy(COPY_RESTORE_DROPPED, {n: dropped}) : '');
    if(!here()){ toast(fillCopy(COPY_RESTORED_OTHER, {project, text}), RESTORED_TOAST_MS); return; }   // 只说一声，不改当前页面
    toast(text, RESTORED_TOAST_MS);
    applyWizard(r.wizard);
    await refreshOrWarn(project);
    if(here()) await go('result');
  }catch(e){ toast(here() ? e.message : fillCopy(COPY_RESTORED_OTHER, {project, text: e.message}), TOAST_ERROR_MS); }   // 409（任务在跑 / 没有快照 / 镜头都不可用）：原因说出来，停在 ⑥
  finally{ exportUi.restoring.delete(project); }
}

Object.assign(ACTIONS, {
  toggleCompare: ()=>toggleCompare(), closeCompare: ()=>closeCompare(), playBoth: ()=>playBoth(),
  pickCompare: el=>pickCompare(num(el.dataset.i)), retryCompare: ()=>retryCompare(),
  askRestore: el=>askRestore(num(el.dataset.i)),
  restoreVersionGo: el=>restoreVersion(el.dataset.v),
});
