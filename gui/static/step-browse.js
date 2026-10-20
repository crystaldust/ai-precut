// 剪辑台主页 · ③ 看素材（M13b 暂住）：整页版本随后上线；现在这一步只有一张说明卡片，
// 按钮仍打开原来的「看素材」窗口（browse.html），保证全流程照样能走完。

/* 界面文案：产品可直接改这里 */
const COPY_BROWSE_TITLE = '③ 看素材';
const COPY_BROWSE_INTRO = '浏览每个片段的档位和判定依据，挑要的、标废片。改过之后「⑤ 看结果」会提示需要重新选段。';
const COPY_BROWSE_ENTRY = '打开看素材窗口';
const COPY_BROWSE_TEMP = '整页的看素材（键盘挑片段、剪辑列表）还在做，先用窗口版。';

function viewBrowse(){
  return `<div class="card"><h3>${esc(COPY_BROWSE_TITLE)}</h3><p>${esc(COPY_BROWSE_INTRO)}</p>
    <button class="primary" data-act="openBrowse">${esc(COPY_BROWSE_ENTRY)}</button>
    <p class="hint">${esc(COPY_BROWSE_TEMP)}</p></div>`;
}
Object.assign(ACTIONS, {openBrowse: ()=>openSubpage('browse')});
