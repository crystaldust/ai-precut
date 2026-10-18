#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「片段浏览器」可点击原型（《九月一号》真实数据）。

Level 语义（2026-10-18 定）：废片 / 待定 / 可用 —— 是"处置状态"，不是分数。
    废片 = 不进候选
    待定 = AI 拿不准，交给人 30 秒裁决（A 标可用 / D 标废片）
    可用 = 进入选段池，参与话题覆盖

产物：gui/static/prototype.html
打开：http://127.0.0.1:8765/static/prototype.html
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJ = ROOT / "projects/2026-09-01_活动"

CATS = [
    (0, 300, "接待与寒暄", "接待", False),
    (300, 440, "参观教室", "参观", False),
    (440, 545, "讲合同", "讲合同", True),
    (545, 690, "学员年龄", "聊年龄", True),
    (690, 880, "课程与费用", "谈课程", True),
    (880, 1060, "就业承诺", "谈就业", True),
    (1060, 1140, "考证与政策", "讲政策", False),
    (1140, 1660, "食宿与安全", "讲生活", False),
    (1660, 1980, "上课与作息", "讲教学", False),
    (1980, 2130, "皮肤与闲聊", "闲聊", False),
    (2130, 2280, "合同答疑", "答疑", True),
    (2280, 2850, "签约与付款", "签约", True),
    (2850, 3300, "学员故事", "聊学员", False),
]
LOW_CATS = {"食宿与安全", "皮肤与闲聊", "接待与寒暄"}
KEY = ["九千八", "学费", "退费", "退", "就业", "工作", "工资", "岁", "证", "补贴",
       "落户", "合同", "签", "四千", "宿舍", "考试", "结业"]
FILLER = set("嗯啊哦呃唉哎哈呀吧呢对是")


def cat_of(t: float):
    for a, b, name, action, must in CATS:
        if a <= t < b:
            return name, action, must
    return "其他", "其他", False


def overlap(a1, a2, b1, b2):
    return max(0, min(a2, b2) - max(a1, b1))


def build() -> dict:
    segs = json.loads((PROJ / "work/segments.json").read_text(encoding="utf-8"))["segments"]
    shots = json.loads((PROJ / "shots.json").read_text(encoding="utf-8"))["shots"]
    dur = json.loads((PROJ / "work/materials.json").read_text(encoding="utf-8"))["items"][0]["duration"]

    out = []
    for s in segs:
        name, action, must = cat_of(s["start"])
        text, length = s["text"], s["end"] - s["start"]
        hits = [k for k in KEY if k in text]
        filler = sum(1 for c in text if c in FILLER) / max(1, len(text))

        if length < 3 or filler > 0.30:
            level, reason = 1, f"碎句/语气词多（{length:.1f}s，实词少）"
        elif name in LOW_CATS and not hits:
            level, reason = 1, "寒暄或生活闲聊，无关键信息"
        elif not hits and length < 8:
            level, reason = 1, "无关键信息且偏短"
        elif hits and length >= 6:
            level, reason = 3, "含关键信息：" + "、".join(hits[:3])
        else:
            level, reason = 2, "无关键信息但篇幅较长，可能是画面/b-roll，需要你判断"

        clean = text.replace("嗯", "").replace("啊", "").replace("呃", "")
        summary = f"{action}：{clean[:22]}" + ("…" if len(clean) > 22 else "")
        cut = sum(overlap(s["start"], s["end"], sh["in"], sh["out"]) for sh in shots)
        out.append({
            "id": s["id"], "start": round(s["start"], 2), "end": round(s["end"], 2),
            "dur": round(length, 2), "cat": name, "level": level, "reason": reason,
            "summary": summary, "text": text[:120], "must": must, "inCut": cut > 1.0,
        })

    cats = []
    for a, b, name, _, must in CATS:
        items = [x for x in out if x["cat"] == name]
        cut = sum(overlap(x["start"], x["end"], sh["in"], sh["out"])
                  for x in items for sh in shots)
        cats.append({
            "name": name, "must": must,
            "waste": sum(1 for x in items if x["level"] == 1),
            "pending": sum(1 for x in items if x["level"] == 2),
            "usable": sum(1 for x in items if x["level"] == 3),
            "usable_dur": round(sum(x["dur"] for x in items if x["level"] == 3), 1),
            "mat": b - a, "cut": round(cut, 1), "budget": 45 if must else 20,
        })
    return {"dur": dur, "segments": out, "cats": cats}


HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>片段浏览器 · 原型</title>
<style>
:root{--bg:#16181d;--panel:#1e2128;--panel2:#252932;--line:#2f3440;--text:#e8eaf0;
--muted:#9aa2b1;--accent:#4a9eff;--waste:#4b5563;--pending:#f59e0b;--usable:#3ddc84}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,"PingFang SC",sans-serif}
button{font:inherit;cursor:pointer;border:none;border-radius:8px;padding:6px 12px;background:var(--panel2);color:var(--text)}
button:hover{filter:brightness(1.15)}
button.on{background:var(--accent);color:#06121f;font-weight:600}
#app{display:grid;grid-template-columns:1fr 340px;height:100vh}
main{display:flex;flex-direction:column;overflow:hidden}
header{padding:14px 20px 8px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:17px}
.sub{color:var(--muted);font-size:12px;margin-top:2px}
.steps{display:flex;gap:6px;margin-top:10px}
.step{font-size:11px;padding:3px 9px;border-radius:12px;background:var(--panel2);color:var(--muted)}
.step.done{color:var(--usable);background:#16281f}
.step.now{background:var(--accent);color:#06121f;font-weight:600}
.bar{display:flex;gap:8px;align-items:center;padding:10px 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.badge{font-size:11px;color:#2a1c02;background:var(--pending);border-radius:10px;padding:2px 8px;font-weight:700}
.density{height:14px;background:#12141a;border-radius:7px;overflow:hidden;display:flex;margin:0 20px 10px;cursor:pointer}
.density div{height:100%}
.list{flex:1;overflow:auto;padding:0 20px 130px}
.row{display:grid;grid-template-columns:92px 100px 44px 1fr 52px 34px;gap:8px;align-items:center;
padding:7px 8px;border-bottom:1px solid #23262e;cursor:pointer}
.row:hover{background:#1a1d24}
.row.active{background:#1b2740}
.tc{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.cat{font-size:11px;color:#9fb4d8;background:#1d2735;border-radius:6px;padding:2px 6px;text-align:center}
.lv{font-size:11px;font-weight:700;text-align:center;border-radius:5px;padding:2px 0}
.lv1{background:#252a33;color:#8b94a3}.lv2{background:#4a3108;color:#ffc45c}.lv3{background:#123a28;color:#5ce0a0}
.sum{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sum small{color:var(--muted);font-size:11px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dur{color:var(--muted);font-size:12px;text-align:right}
.star{font-size:15px;background:none;padding:0;color:#4b5563}
.star.on{color:#f5c542}
.used{color:var(--usable);font-size:10px;margin-left:4px}
.group{margin:16px 0 6px;font-weight:600;font-size:13px;color:#b9c6da;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.group span{font-weight:400;color:var(--muted);font-size:11px}
.group .num{color:#9fb4d8}
aside{border-left:1px solid var(--line);background:var(--panel);padding:16px;overflow:auto}
aside h2{font-size:13px;margin:0 0 8px;color:#b9c6da}
.summary{background:var(--panel2);border-radius:10px;padding:12px;font-size:12.5px;line-height:1.8}
.summary b{color:var(--accent)}
.q{margin:14px 0;padding-bottom:12px;border-bottom:1px solid #23262e}
.q p{margin:0 0 8px;font-size:12.5px}
.opt{display:block;font-size:12px;color:var(--muted);margin:4px 0;cursor:pointer}
.opt input{margin-right:6px}
.why{font-size:11px;color:#6b7c93;margin-top:6px}
footer{position:fixed;left:0;right:340px;bottom:0;background:var(--panel);border-top:1px solid var(--line);
padding:10px 20px;display:flex;gap:14px;align-items:center}
footer video{width:190px;border-radius:8px;background:#000}
footer .t{font-size:12.5px}
footer .t b{color:var(--accent)}
footer .keys{font-size:11px;color:#6b7c93;margin-top:4px}
.stat{display:flex;gap:12px;font-size:12px;color:var(--muted);margin-bottom:10px;flex-wrap:wrap}
.stat b{color:var(--text)}
</style></head><body>
<div id="app">
<main>
  <header>
    <h1>《九月一号》· 素材浏览</h1>
    <div class="sub">54 分 18 秒 · 140 个片段 · 先看素材，再开始切</div>
    <div class="steps">
      <span class="step done">1 导入</span><span class="step done">2 分析</span>
      <span class="step now">3 浏览与确认</span><span class="step">4 选段</span><span class="step">5 导出</span>
    </div>
  </header>
  <div class="bar">
    <button id="vTime" class="on" onclick="setView('time')">按时间</button>
    <button id="vCat" onclick="setView('cat')">按分类</button>
    <span style="width:12px"></span>
    <button id="fAll" class="on" onclick="setLevel(0)">全部</button>
    <button id="f2" onclick="setLevel(2)">待判断 <span id="pendN2"></span></button>
    <button id="f3" onclick="setLevel(3)">可用</button>
    <button id="fUn" onclick="setLevel(9)">未用</button>
    <span class="badge" id="pendBadge">待你判断 0 段</span>
    <span style="margin-left:auto;color:var(--muted);font-size:12px" id="count"></span>
  </div>
  <div class="density" id="density" title="点击跳转"></div>
  <div class="list" id="list"></div>
</main>
<aside>
  <h2>内容摘要</h2>
  <div class="summary">
    一位母亲带女儿到美业学校报名：看教室、读合同、把美甲换成养生、签字转账 <b>九千八</b>。<br>
    三处关键信息：<b>退费条款</b>、<b>就业承诺</b>、<b>年龄限制（16 岁才能考证）</b>。
    <div class="why">依据：14 个话题 · 37 处关键信息 · 3 位主要说话人 · 签约在 38:00–41:00</div>
  </div>
  <h2 style="margin-top:18px">需要你确认的 3 件事</h2>
  <div class="q">
    <p>1. 这条片子主角是谁？</p>
    <label class="opt"><input type="radio" name="q1">妈妈</label>
    <label class="opt"><input type="radio" name="q1">女儿</label>
    <label class="opt"><input type="radio" name="q1" checked>老师</label>
    <label class="opt"><input type="radio" name="q1">群像</label>
    <div class="why">选了会怎样：主角镜头占比 ≥40%，旁白视角跟着变。</div>
  </div>
  <div class="q">
    <p>2. 必须让观众记住哪些信息？</p>
    <label class="opt"><input type="checkbox" checked>学费九千八</label>
    <label class="opt"><input type="checkbox" checked>退费条款</label>
    <label class="opt"><input type="checkbox" checked>就业承诺</label>
    <label class="opt"><input type="checkbox">年龄限制</label>
    <div class="why">选了会怎样：对应片段强制进候选，不会被当"拖沓"删掉。</div>
  </div>
  <div class="q">
    <p>3. 结尾落在哪个动作？</p>
    <label class="opt"><input type="radio" name="q3">签字</label>
    <label class="opt"><input type="radio" name="q3" checked>转账</label>
    <label class="opt"><input type="radio" name="q3">走出门</label>
    <div class="why">选了会怎样：决定最后 15 秒取哪一段。</div>
  </div>
  <div class="stat" style="margin-top:16px">
    <span>可用 <b id="n3">0</b></span><span>待定 <b id="n2">0</b></span>
    <span>废片 <b id="n1">0</b></span><span>必留 <b id="mustN">0</b></span>
  </div>
</aside>
</div>
<footer>
  <video id="pv" controls preload="metadata"></video>
  <div>
    <div class="t" id="now">点任意一行试听</div>
    <div class="keys">空格 播放/暂停　←/→ 5 秒　A 标可用　D 标废片　S 标必留</div>
  </div>
</footer>
<script>
const DATA = __DATA__;
const PROJ = __PROJ__;
const pv = document.getElementById('pv');
pv.src = '/media/' + encodeURIComponent(PROJ) + '/proxy';
let view='time', filter=0, active=-1, cur=null, must=new Set();
const LV = {1:'废片', 2:'待定', 3:'可用'};
const COLOR = {1:'var(--waste)', 2:'var(--pending)', 3:'var(--usable)'};
const fmt = s => String(Math.floor(s/60)).padStart(2,'0')+':'+(s%60).toFixed(1).padStart(4,'0');

(function density(){
  const d=document.getElementById('density'), total=DATA.dur;
  DATA.segments.forEach(s=>{
    const el=document.createElement('div');
    el.style.width=((s.dur/total)*100).toFixed(3)+'%';
    el.style.background=COLOR[s.level];
    el.title=fmt(s.start)+' '+LV[s.level]+' · '+s.summary;
    el.onclick=e=>{e.stopPropagation(); jump(s.start);};
    d.appendChild(el);
  });
})();

function setView(v){ view=v; document.getElementById('vTime').classList.toggle('on',v==='time');
  document.getElementById('vCat').classList.toggle('on',v==='cat'); render(); }
function setLevel(l){ filter=l; ['fAll','f2','f3','fUn'].forEach((id,k)=>
  document.getElementById(id).classList.toggle('on',[0,2,3,9][k]===l)); render(); }
function pass(s){ if(filter===2) return s.level===2; if(filter===3) return s.level===3;
  if(filter===9) return !s.inCut; return true; }

function row(s,i){
  return `<div class="row" data-i="${i}" onclick="jump(${s.start},${i},${s.end})">
    <div class="tc">${fmt(s.start)}</div>
    <div class="cat">${s.cat}</div>
    <div class="lv lv${s.level}" data-lv="${s.id}" title="${s.reason}">${LV[s.level]}</div>
    <div class="sum">${s.summary}${s.inCut?'<span class="used">已用</span>':''}
      <small>${s.reason}</small></div>
    <div class="dur">${s.dur.toFixed(1)}s</div>
    <button class="star ${must.has(s.id)?'on':''}" onclick="event.stopPropagation();toggleMust('${s.id}',this)">★</button>
  </div>`;
}

function render(){
  const list=document.getElementById('list');
  const idx=DATA.segments.map((s,i)=>({s,i})).filter(x=>pass(x.s));
  document.getElementById('count').textContent=`显示 ${idx.length} / ${DATA.segments.length} 段`;
  if(view==='time'){ list.innerHTML=idx.map(x=>row(x.s,x.i)).join(''); }
  else{
    const g={}; idx.forEach(x=>{(g[x.s.cat] ||= []).push(x);});
    list.innerHTML=Object.entries(g).map(([cat,items])=>{
      const m=DATA.cats.find(c=>c.name===cat)||{usable:0,pending:0,waste:0,usable_dur:0,budget:0,must:false};
      return `<div class="group">${cat}${m.must?' · <span style="color:#ffc45c">必留</span>':''}
        <span>可用 <span class="num">${m.usable}</span> · 待定 <span class="num">${m.pending}</span> ·
        废片 <span class="num">${m.waste}</span> · 可用时长 ${m.usable_dur.toFixed(0)} 秒 · 建议 ${m.budget} 秒</span></div>`
        + items.map(x=>row(x.s,x.i)).join('');
    }).join('');
  }
  const n1=DATA.segments.filter(s=>s.level===1).length;
  const n2=DATA.segments.filter(s=>s.level===2).length;
  const n3=DATA.segments.filter(s=>s.level===3).length;
  document.getElementById('n1').textContent=n1;
  document.getElementById('n2').textContent=n2;
  document.getElementById('n3').textContent=n3;
  document.getElementById('mustN').textContent=must.size;
  document.getElementById('pendBadge').textContent=`待你判断 ${n2} 段`;
  document.getElementById('pendN2').textContent=`(${n2})`;
}

function jump(start,i,end){
  pv.currentTime=Math.max(0,start-0.3); pv.play();
  cur=i; active=i;
  const s=DATA.segments[i];
  document.getElementById('now').innerHTML=`<b>${fmt(start)}–${fmt(end||start+1)}</b>　${s?s.summary:''}<br>
    <span style="color:var(--muted)">${s?s.reason:''}</span>`;
  document.querySelectorAll('.row').forEach(r=>r.classList.remove('active'));
  const el=document.querySelector(`.row[data-i="${i}"]`); if(el) el.classList.add('active');
  clearInterval(window._t);
  window._t=setInterval(()=>{ if(pv.currentTime>=(end||start+999)){pv.pause();clearInterval(window._t);} },120);
}
function toggleMust(id,el){ must.has(id)?must.delete(id):must.add(id);
  el.classList.toggle('on'); document.getElementById('mustN').textContent=must.size; }

function setLevelOf(i, lv){
  const s=DATA.segments[i]; if(!s) return;
  s.level=lv;
  s.reason = lv===3 ? "你标为可用" : "你标为废片";
  render();
  const el=document.querySelector(`.row[data-i="${i}"]`);
  if(el){ el.classList.add('active'); el.scrollIntoView({block:'nearest'}); }
}
document.addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT') return;
  if(e.code==='Space'){ e.preventDefault(); pv.paused?pv.play():pv.pause(); }
  if(e.code==='ArrowRight') pv.currentTime+=5;
  if(e.code==='ArrowLeft') pv.currentTime-=5;
  if(e.key==='a'||e.key==='A'){ if(cur!=null) setLevelOf(cur,3); }
  if(e.key==='d'||e.key==='D'){ if(cur!=null) setLevelOf(cur,1); }
  if(e.key==='s'||e.key==='S'){ if(cur!=null){ const id=DATA.segments[cur].id;
    must.has(id)?must.delete(id):must.add(id); render(); } }
});
const _v=new URLSearchParams(location.search).get('view');
if(_v==='cat'){ setView('cat'); } else { render(); }
</script></body></html>
"""


def main() -> None:
    data = build()
    html = (HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
                .replace("__PROJ__", json.dumps("2026-09-01_活动", ensure_ascii=False)))
    out = ROOT / "gui/static/prototype.html"
    out.write_text(html, encoding="utf-8")
    n = {1: 0, 2: 0, 3: 0}
    for s in data["segments"]:
        n[s["level"]] += 1
    print(f"片段 {len(data['segments'])}：废片 {n[1]} · 待定 {n[2]} · 可用 {n[3]}")
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
