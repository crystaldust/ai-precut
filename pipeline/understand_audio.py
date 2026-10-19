# -*- coding: utf-8 -*-
"""a 路：从音轨给每个句子算声音特征。

只回答"怎么说"的问题，不判断内容：
  * rms_db / rel_db —— 这句话有多响，相对全片平均偏多少
  * speech_rate —— 字/秒（说得多快，快=急/兴奋）
  * pause_after —— 说完到下一句之间的停顿（长=犹豫/换话题）
  * overlap —— 时间上与他人的语音重叠（若 ASR 输出允许重叠）
  * interrupt —— 抢话代理指标：换人且几乎无停顿（ASR 分段不重叠时用这个）

这些信号后面会与文字、画面一起进入三档判定（废片/待定/可用）。
"""
from __future__ import annotations

import json
import math
import statistics
import wave
from pathlib import Path

from pipeline import schema

try:  # Python ≤3.12 有 C 实现的 audioop，比纯 Python 快一个数量级
    import audioop
except ImportError:  # pragma: no cover - 3.13+ 才走这里
    audioop = None


def wav_meta(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        return {
            "channels": w.getnchannels(),
            "rate": w.getframerate(),
            "sampwidth": w.getsampwidth(),
            "frames": w.getnframes(),
            "duration": w.getnframes() / max(1, w.getframerate()),
        }


def _rms_db(frames: bytes, sampwidth: int) -> float:
    if not frames:
        return -120.0
    if audioop is not None:
        rms = audioop.rms(frames, sampwidth)
    else:  # pragma: no cover
        import array

        samples = array.array("h", frames)
        rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))
    if rms <= 0:
        return -120.0
    full_scale = float(1 << (8 * sampwidth - 1))
    return max(-120.0, 20.0 * math.log10(rms / full_scale))


def _speech_rate(text: str, duration: float) -> float:
    chars = sum(1 for c in text if c.strip())
    return round(chars / duration, 2) if duration > 0 else 0.0


def _overlaps(a: dict, b: dict) -> bool:
    lo, hi = max(a["start"], b["start"]), min(a["end"], b["end"])
    return (hi - lo) > 0.3


def analyze(wav_path: Path, segments: list[dict], *, pad: float = 0.0) -> dict:
    """返回 {"meta":..., "segments":[{...原字段, signals:{...}}]}"""
    meta = wav_meta(wav_path)
    if meta["sampwidth"] != 2:
        raise ValueError("只支持 16-bit PCM wav（当前 %d 字节/采样）" % meta["sampwidth"])
    rate, width = meta["rate"], meta["sampwidth"]

    enriched: list[dict] = []
    levels: list[float] = []
    with wave.open(str(wav_path), "rb") as w:
        for i, seg in enumerate(segments):
            start = max(0.0, seg["start"] - pad)
            end = min(meta["duration"], seg["end"] + pad)
            w.setpos(min(int(start * rate), meta["frames"]))
            frames = w.readframes(max(0, int((end - start) * rate)))
            db = _rms_db(frames, width)
            levels.append(db)

            nxt = segments[i + 1] if i + 1 < len(segments) else None
            pause_after = round(max(0.0, nxt["start"] - seg["end"]), 2) if nxt else 0.0
            overlap = any(_overlaps(seg, other) for j, other in enumerate(segments)
                          if j != i and other.get("speaker") != seg.get("speaker"))
            # ASR 分段通常不重叠，用"换人且几乎没停顿"作为抢话代理
            interrupt = bool(
                nxt
                and nxt.get("speaker") != seg.get("speaker")
                and 0 <= (nxt["start"] - seg["end"]) < 0.25
            )

            item = dict(seg)
            item["signals"] = {
                "rms_db": round(db, 1),
                "speech_rate": _speech_rate(seg.get("text", ""), seg["end"] - seg["start"]),
                "pause_after": pause_after,
                "overlap": bool(overlap),
                "interrupt": interrupt,
                "duration": round(seg["end"] - seg["start"], 2),
            }
            enriched.append(item)

    median = statistics.median(levels) if levels else -120.0
    for item in enriched:
        item["signals"]["rel_db"] = round(item["signals"]["rms_db"] - median, 1)

    return {"meta": meta, "median_db": round(median, 1), "segments": enriched}


def run(wav_path: Path, segments_path: Path, out_path: Path) -> dict:
    segments = schema.read_field(segments_path, "segments")  # 结构不对 → CorruptJSON（带文件名）
    result = analyze(Path(wav_path), segments)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return result


if __name__ == "__main__":  # pragma: no cover - 手工调试用
    import sys

    project = Path(sys.argv[1])
    res = run(project / "work/audio/asr.wav",
              project / "work/segments.json",
              project / "work/segments_audio.json")
    print(f"句子 {len(res['segments'])} 条，中位响度 {res['median_db']} dB")
