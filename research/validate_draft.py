#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_draft.py —— 静态校验一份剪映旧格式草稿（不做 GUI 打开，纯结构自洽性检查）

用法：
    python3 validate_draft.py <草稿目录> [--ref-schema base_template_11.0.json]

检查项：
  A. 必需文件是否存在：draft_content.json / draft_meta_info.json / draft_info.json（Mac 入口；非明文只 WARN）
  B. draft_content.json 顶层必需字段
  C. id 唯一性 & 格式（草稿 id 大写带连字符；素材 id 32 hex）
  D. segment.material_id 与 extra_material_refs 是否可解析
  E. timerange 单位/范围：source 落在素材时长内、同轨 target 不重叠、
     draft.duration == 所有 target 结束时间的最大值
  F. 素材 path 是否为绝对路径且文件存在
  G. 文本素材 content 是否为合法 JSON 且含 text/styles
  H. 与参考 schema（剪映 11.0 自己写出的 template.tmp）对比 materials 分类是否齐全
  I. 至少有一个视频片段；给了 expect 时与时间线核对视频/文字片段数与成片时长

退出码：0 = 全部通过（可能有 WARN）；1 = 有 FAIL
"""
import argparse
import json
import os
import re
import sys

REQUIRED_TOP = ["canvas_config", "config", "duration", "fps", "id", "materials",
                "tracks", "version", "new_version", "keyframes"]
ALLOWED_TRACK = {"video", "audio", "text", "effect", "filter", "sticker", "adjust"}
HEX32 = re.compile(r"^[0-9a-f]{32}$")
# 成片时长核对容差：切片实际时长可能比请求短 1 帧左右，再加微秒取整
VIDEO_END_TOLERANCE_US = 100_000

fails, warns, oks = [], [], []


def ok(msg):
    oks.append(msg)


def warn(msg):
    warns.append(msg)


def fail(msg):
    fails.append(msg)


DEFAULT_REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "base_template_11.0.json")


def _result():
    return {"fails": list(fails), "warns": list(warns), "oks": list(oks)}


def check(draft_dir, ref_schema=DEFAULT_REF, expect=None, relocate=None):
    """校验一个草稿目录，返回 {"fails", "warns", "oks"}（不打印）。

    expect：{"videos", "texts", "video_end_us"}，与时间线核对（可选）。
    relocate：(安装后前缀, 实际目录)，dry-run 时素材路径指向尚不存在的安装位置，
    校验 F 段按映射后的路径检查存在性。
    模块级列表在冻结版里会被同进程重复调用累积，所以每次先清空（GL-11）。
    并发调用仍不安全（GL-17）。
    """
    fails.clear()
    warns.clear()
    oks.clear()
    d = os.path.abspath(draft_dir)

    # ---------- A. 文件
    fc = os.path.join(d, "draft_content.json")
    fm = os.path.join(d, "draft_meta_info.json")
    fi = os.path.join(d, "draft_info.json")
    for p in (fc, fm, fi):
        if os.path.exists(p):
            ok("存在 %s (%d bytes)" % (os.path.basename(p), os.path.getsize(p)))
        else:
            fail("缺少 %s" % os.path.basename(p))
    if os.path.exists(fi):
        try:
            with open(fi, "r", encoding="utf-8") as f:
                json.load(f)
        except Exception:
            # 剪映打开过的草稿会把 draft_info.json 改写成加密格式（实测 九月一号_v3），只提示
            warn("draft_info.json 不是明文 JSON（剪映打开过后会改写为加密格式）")
    if not os.path.exists(fc):
        return _result()

    # ---------- 解析
    try:
        with open(fc, "r", encoding="utf-8") as f:
            c = json.load(f)
    except Exception as e:
        fail("draft_content.json 不是合法 UTF-8 JSON：%r" % (e,))
        return _result()
    ok("draft_content.json 可解析为 JSON")

    # ---------- B. 顶层字段
    for k in REQUIRED_TOP:
        if k not in c:
            fail("缺少顶层字段 %r" % k)
    if not fails:
        ok("顶层必需字段齐全（%d 个）" % len(REQUIRED_TOP))

    # ---------- C. id
    did = c.get("id", "")
    if not did:
        fail("草稿 id 为空")
    elif not re.match(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$", did):
        warn("草稿 id 不是大写带连字符 UUID：%r（剪映通常如此，但非硬性）" % did)
    else:
        ok("草稿 id 格式正确：%s" % did)

    mats = c.get("materials", {})
    all_mats = {}
    bad_id = 0
    for cat, lst in mats.items():
        if not isinstance(lst, list):
            fail("materials.%s 不是数组" % cat)
            continue
        for it in lst:
            mid = it.get("id", "")
            if not HEX32.match(mid or ""):
                bad_id += 1
                warn("materials.%s 里有非 32-hex id：%r" % (cat, mid))
            if mid in all_mats:
                fail("素材 id 重复：%s（%s 与 %s）" % (mid, all_mats[mid], cat))
            all_mats[mid] = cat
    ok("素材总数 %d，覆盖 %d 个分类" % (len(all_mats), len([k for k, v in mats.items() if v])))
    if bad_id == 0:
        ok("所有素材 id 均为 32 位 hex")

    # ---------- D. 引用解析
    seg_count = 0
    dangling = 0
    for t in c.get("tracks", []):
        for s in t.get("segments", []):
            mid = s.get("material_id")
            if mid not in all_mats:
                fail("segment %s 的 material_id=%r 在 materials 中不存在" % (s.get("id"), mid))
            for r in s.get("extra_material_refs", []):
                if r not in all_mats:
                    dangling += 1
                    warn("segment %s 的 extra_material_refs 指向不存在的素材 %s" % (s.get("id"), r))
    if dangling == 0:
        ok("所有 extra_material_refs 均可解析")

    # ---------- E. timerange
    dur = c.get("duration")
    if not isinstance(dur, int):
        fail("duration 不是整数（应为微秒）")
    ends = []
    for t in c.get("tracks", []):
        tt = t.get("type")
        if tt not in ALLOWED_TRACK:
            fail("未知轨道类型 %r" % tt)
        rngs = []
        for s in t.get("segments", []):
            seg_count += 1
            tg = s.get("target_timerange") or {}
            st, dt = tg.get("start"), tg.get("duration")
            if not isinstance(st, int) or not isinstance(dt, int):
                fail("segment %s 的 target_timerange 不是整数微秒" % s.get("id"))
                continue
            if st < 0 or dt <= 0:
                fail("segment %s 的 target_timerange 非法：%r" % (s.get("id"), tg))
            rngs.append((st, st + dt))
            ends.append(st + dt)

            src = s.get("source_timerange")
            mat = mats.get(all_mats.get(s.get("material_id"), ""), [])
            mat = next((x for x in mat if x.get("id") == s.get("material_id")), None)
            if src:
                ss, sd = src.get("start"), src.get("duration")
                if not isinstance(ss, int) or not isinstance(sd, int):
                    fail("segment %s 的 source_timerange 不是整数微秒" % s.get("id"))
                elif mat and isinstance(mat.get("duration"), int):
                    if ss + sd > mat["duration"]:
                        fail("segment %s 取值超出素材时长：source %d+%d > material.duration %d"
                             % (s.get("id"), ss, sd, mat["duration"]))
            # 变速一致性：source.duration / target.duration ≈ speed
            if src and s.get("speed") not in (None, 1.0) and dt:
                exp = (src.get("duration") or 0) / float(dt)
                if abs(exp - float(s["speed"])) > 0.02:
                    warn("segment %s 的 speed=%.3f 与 source/target 比 %.3f 不一致"
                         % (s.get("id"), float(s["speed"]), exp))
        rngs.sort()
        for (a1, a2), (b1, b2) in zip(rngs, rngs[1:]):
            if b1 < a2:
                fail("轨道 %s 内片段重叠：[%d,%d) 与 [%d,%d)" % (tt, a1, a2, b1, b2))
    if ends and dur != max(ends):
        fail("draft.duration=%d 与最长片段结束时间 %d 不一致" % (dur, max(ends)))
    elif ends:
        ok("duration=%d 微秒（%.2f s），与最长片段一致" % (dur, dur / 1e6))
    ok("共 %d 个 segment" % seg_count)

    # ---------- F. 素材路径
    for cat in ("videos", "audios", "images"):
        for it in mats.get(cat, []):
            p = _relocated(it.get("path") or "", relocate)
            if not p:
                warn("materials.%s[%s] 没有 path" % (cat, it.get("id")))
            elif not os.path.isabs(p):
                fail("materials.%s 的 path 不是绝对路径：%r" % (cat, p))
            elif not os.path.exists(p):
                fail("materials.%s 的 path 在本机不存在：%r" % (cat, p))
            elif p.startswith("file://"):
                fail("path 不应带 file:// 前缀：%r" % p)
            else:
                ok("%s 路径可访问：%s" % (cat, p))

    # ---------- G. 文本素材
    for it in mats.get("texts", []):
        try:
            inner = json.loads(it.get("content", ""))
        except Exception:
            fail("texts[%s].content 不是合法 JSON 字符串" % it.get("id"))
            continue
        if "text" not in inner or "styles" not in inner:
            fail("texts[%s].content 缺 text/styles" % it.get("id"))
            continue
        n = len(inner["text"])
        for st in inner["styles"]:
            r = st.get("range")
            if not r or len(r) != 2 or r[1] > n:
                fail("texts[%s] 的 styles.range=%r 超出文本长度 %d" % (it.get("id"), r, n))
        ok("字幕内容：%r（%d 字，%d 个 style）" % (inner["text"][:20], n, len(inner["styles"])))

    # ---------- H. 与 11.0 schema 对比
    if os.path.exists(ref_schema):
        with open(ref_schema, "r", encoding="utf-8") as f:
            ref = json.load(f)
        missing_cat = sorted(set(ref.get("materials", {})) - set(mats))
        missing_top = sorted(set(ref) - set(c))
        if missing_cat:
            warn("materials 缺少 11.0 分类：%s" % ", ".join(missing_cat))
        if missing_top:
            warn("缺少 11.0 顶层字段：%s" % ", ".join(missing_top))
        if not missing_cat and not missing_top:
            ok("与剪映 11.0 自身 schema 相比无缺字段")
        if "version" in ref and c.get("version") != ref["version"]:
            warn("version=%r 与 11.0 的 %r 不同" % (c.get("version"), ref["version"]))

    # ---------- I. 内容完整性
    _check_contents(c, expect)
    return _result()


def _relocated(path, relocate):
    if relocate and path.startswith(relocate[0] + os.sep):
        return relocate[1] + path[len(relocate[0]):]
    return path


def _segments(c, track_type):
    return [s for t in c.get("tracks", []) if t.get("type") == track_type
            for s in t.get("segments", [])]


def _check_contents(c, expect):
    videos, texts = _segments(c, "video"), _segments(c, "text")
    if not videos:
        fail("草稿里没有任何视频片段")
    if not expect:
        return
    if len(videos) != expect["videos"]:
        fail("视频片段数 %d 与时间线 %d 不一致" % (len(videos), expect["videos"]))
    if len(texts) != expect["texts"]:
        fail("文字片段数 %d 与时间线 %d 不一致" % (len(texts), expect["texts"]))
    ends = [(s.get("target_timerange") or {}).get("start", 0)
            + (s.get("target_timerange") or {}).get("duration", 0) for s in videos]
    end = max(ends) if ends else 0
    if abs(end - expect["video_end_us"]) > VIDEO_END_TOLERANCE_US:
        fail("视频成片时长 %.3fs 与时间线 %.3fs 不一致"
             % (end / 1e6, expect["video_end_us"] / 1e6))
    else:
        ok("与时间线一致：视频 %d 段、文字 %d 段、成片 %.2fs" % (len(videos), len(texts), end / 1e6))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("draft_dir")
    ap.add_argument("--ref-schema", default=DEFAULT_REF)
    args = ap.parse_args()
    res = check(args.draft_dir, args.ref_schema)
    report(os.path.abspath(args.draft_dir))  # report 读模块级列表，必须在 check 之后
    return 1 if res["fails"] else 0


def report(d):
    print("=" * 68)
    print("草稿目录：", d)
    for m in oks:
        print("  [ OK ]", m)
    for m in warns:
        print("  [WARN]", m)
    for m in fails:
        print("  [FAIL]", m)
    print("-" * 68)
    print("结果：OK=%d  WARN=%d  FAIL=%d  =>  %s"
          % (len(oks), len(warns), len(fails), "PASS" if not fails else "FAIL"))
    print("=" * 68)


if __name__ == "__main__":
    sys.exit(main())
