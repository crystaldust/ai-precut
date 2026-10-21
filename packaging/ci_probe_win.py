# -*- coding: utf-8 -*-
"""Windows CI 探针（里程碑 16 Task 1）：h264_mf / libopenh264 各编 5 秒 1080p 并 ffprobe；--keyring 做凭据管理器往返。

只在 CI 里用，不进包。任何一个编码器失败只报告；两个都失败才退出码 1。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(os.environ.get("AICUT_FFMPEG_OUT") or ROOT / "vendor") / "bin"  # 与 fetch_ffmpeg_win.py 一致
ENCODERS = ("h264_mf", "libopenh264")
TIMEOUT_S = 300
SRC = ["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=5",
       "-f", "lavfi", "-i", "sine=frequency=440:duration=5"]
COMMON = ["-b:v", "12M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest"]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=TIMEOUT_S)


def encode(encoder: str, out: Path, extra: list[str]) -> tuple[bool, float, str]:
    cmd = [str(BIN / "ffmpeg.exe"), "-hide_banner", "-y", *SRC, "-c:v", encoder, *extra, *COMMON, str(out)]
    start = time.monotonic()
    try:
        r = run(cmd)
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - start, f"超时（>{TIMEOUT_S}s）"
    return r.returncode == 0, time.monotonic() - start, (r.stderr or "")[-600:]


def probe(path: Path) -> str:
    r = run([str(BIN / "ffprobe.exe"), "-v", "error", "-show_streams", "-of", "json", str(path)])
    if r.returncode != 0:
        return f"ffprobe 失败：{(r.stderr or '').strip()[:200]}"
    streams = json.loads(r.stdout).get("streams", [])
    return "; ".join(f"{s.get('codec_type')}: codec={s.get('codec_name')} profile={s.get('profile')} "
                     f"pix_fmt={s.get('pix_fmt')}" for s in streams)


def keyring_roundtrip() -> int:
    """凭据管理器读写删；服务名 ai-cut-ci，绝不碰真实的 ai-cut。"""
    import keyring
    service, user, secret = "ai-cut-ci", "probe", "secret-1"
    keyring.set_password(service, user, secret)
    try:
        if keyring.get_password(service, user) != secret:
            raise RuntimeError("keyring 读回的值不一致")
    finally:
        try:
            keyring.delete_password(service, user)
        except Exception as exc:  # 清理失败不能盖住原始错误
            print(f"清理 keyring 条目失败：{exc}", file=sys.stderr)
    if keyring.get_password(service, user) is not None:
        raise RuntimeError("keyring 删除后仍能读到")
    print(f"keyring 读写删通过：{keyring.get_keyring()}")
    return 0


def main() -> int:
    if "--keyring" in sys.argv[1:]:
        return keyring_roundtrip()
    out_dir = ROOT / "build" / "probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    ok_count = 0
    for enc in ENCODERS:
        out = out_dir / f"{enc}.mp4"
        # 先试 -profile:v high；被拒就退回不带 profile，并如实报告
        ok, secs, err = encode(enc, out, ["-profile:v", "high"])
        profile_note = "-profile:v high 可用"
        if not ok:
            print(f"[{enc}] -profile:v high 被拒或失败：{err.strip()[-300:]}")
            ok, secs, err = encode(enc, out, [])
            profile_note = "不带 -profile:v"
        if ok:
            ok_count += 1
            print(f"[{enc}] 成功（{profile_note}），耗时 {secs:.1f}s，大小 {out.stat().st_size} 字节")
            print(f"[{enc}] {probe(out)}")
        else:
            print(f"[{enc}] 失败，耗时 {secs:.1f}s：{err.strip()}")
    print(f"可用编码器 {ok_count}/{len(ENCODERS)}")
    return 0 if ok_count else 1


if __name__ == "__main__":
    sys.exit(main())
