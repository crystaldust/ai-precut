#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把最小测试草稿再复制一份（只留 draft_content.json），合成 A/B 双格式测试包。"""
import json, shutil, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src_zip = ROOT / "dist/JianYing_Test_01.zip"
work = Path("/tmp/pack2")
if work.exists():
    shutil.rmtree(work)
work.mkdir()
with zipfile.ZipFile(src_zip) as z:
    z.extractall(work)

a = work / "drafts/JianYing_Test_01"
b = work / "drafts/JianYing_Test_B_contentonly"
shutil.copytree(a, b)
(b / "draft_info.json").unlink()
meta = json.loads((b / "draft_meta_info.json").read_text(encoding="utf-8"))
meta["draft_name"] = b.name
(b / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

notes = work / "README.txt"
txt = notes.read_text(encoding="utf-8-sig")
txt = txt.replace("三、装了什么", """三、包里有两个草稿（用来定位问题）
  - JianYing_Test_01：同时带 draft_info.json 和 draft_content.json（新版格式优先）
  - JianYing_Test_B_contentonly：只带 draft_content.json（旧版 5.x 格式）
  两个都会装上。先试 01；如果 01 打不开，再试 B。哪个能打开，就把哪个结果告诉我们。

四、装了什么""", 1)
for old, new in [("四、看什么（这是验证重点）", "五、看什么（这是验证重点）"),
                 ("五、如果出问题，请回传", "六、如果出问题，请回传"),
                 ("六、怎么卸载", "七、怎么卸载")]:
    txt = txt.replace(old, new, 1)
notes.write_text(txt, encoding="utf-8-sig")

out = ROOT / "dist/JianYing_Test_Pack.zip"
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for f in sorted(work.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(work))
print(f"打包：{out}  {out.stat().st_size/1e6:.1f} MB")
