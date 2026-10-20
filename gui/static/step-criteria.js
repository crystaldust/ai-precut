// 剪辑台主页 · ④ 定标准（M13b 暂住）：整页版本随后上线；现在这一步只有一张说明卡片，
// 按钮仍打开原来的「确认与提问」窗口（confirm.html）。确认后自动按答案重新选段（KI-05）。

/* 界面文案：产品可直接改这里 */
const COPY_CRITERIA_TITLE = '④ 定标准';
const COPY_CRITERIA_INTRO = '裁决待定的片段、回答 3–5 个决策问题；确认后会保存答案并重新选段，生成分镜表。';
const COPY_CONFIRM_ENTRY = '打开定标准窗口';  // KI-05：确认页入口
const COPY_CRITERIA_TEMP = '整页的定标准还在做，先用窗口版。';

function viewCriteria(){
  return `<div class="card"><h3>${esc(COPY_CRITERIA_TITLE)}</h3><p>${esc(COPY_CRITERIA_INTRO)}</p>
    <button class="primary" data-act="openConfirm">${esc(COPY_CONFIRM_ENTRY)}</button>
    <p class="hint">${esc(COPY_CRITERIA_TEMP)}</p></div>`;
}
Object.assign(ACTIONS, {openConfirm: ()=>openSubpage('confirm')});
