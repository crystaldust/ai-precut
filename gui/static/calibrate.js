// 剪辑偏好页（KI-53：从 calibrate.html 内联脚本外置）。
const PROJECT = new URLSearchParams(location.search).get('project') || '';
async function load(){
  const r = await fetch('/api/calibrate?project='+encodeURIComponent(PROJECT));
  const d = await r.json();
  if(d.error){ document.getElementById('preview').textContent = d.error; return; }
  const c = d.calibration || {};
  document.getElementById('tone').value = c.tone || 'balanced';
  document.getElementById('audience').value = c.audience || '';
  document.getElementById('must_lines').value = c.must_lines || '';
  updatePreview(d.directive);
}
function updatePreview(directive){
  document.getElementById('preview').textContent = directive || '（未填写，使用默认规则）';
}
async function save(){
  const body = {project: PROJECT, calibration: {
    tone: document.getElementById('tone').value,
    audience: document.getElementById('audience').value,
    must_lines: document.getElementById('must_lines').value,
  }};
  const r = await fetch('/api/calibrate', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  const d = await r.json();
  if(d.ok){ updatePreview(d.directive); toast('已保存，重新跑一次分析后生效'); }
  else toast(d.error || '保存失败');
}
function toast(t){ const el=document.getElementById('toast'); el.textContent=t; el.classList.add('on');
  clearTimeout(el._t); el._t=setTimeout(()=>el.classList.remove('on'),1800); }
['tone','audience','must_lines'].forEach(id=>
  document.getElementById(id).addEventListener('input', ()=>{
    const t=document.getElementById('tone').value;
    const a=document.getElementById('audience').value.trim();
    const m=document.getElementById('must_lines').value.trim();
    const parts=[];
    if(a) parts.push('观众是'+a);
    if(t==='info') parts.push('优先保留信息与事实，情绪镜头次之');
    if(t==='emotion') parts.push('优先保留情绪、冲突与细节，事实次之');
    if(m) parts.push('以下原话必须保留：'+m);
    updatePreview(parts.length ? '剪辑偏好（来自剪辑员，优先级高于默认规则）：'+parts.join('；')+'。' : '');
  }));
Object.assign(ACTIONS, {  // KI-53：页面里没有 on* 属性
  save: ()=>save(),
  goBrowse: ()=>{ location.href = '/static/browse.html?project=' + encodeURIComponent(PROJECT); },
});
load();
