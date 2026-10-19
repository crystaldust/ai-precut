# -*- coding: utf-8 -*-
"""转写结果绑定素材指纹（审查修复 M7，KI-62 的延伸）。

音轨的完成标记已经认素材指纹（换了素材会重抽音轨），但 transcript_raw.json 以「存在」判完成：
不绑定的话，新素材的音轨会配上旧素材的转写。转写成功后记下素材指纹；之后指纹变了就作废旧转写并说明，
下游（分段文稿、逐句标注、分档）各自按输入哈希重算。没有记录的旧项目：视为一致并补记（同 D7）。
"""
from __future__ import annotations

from pathlib import Path

from pipeline import media_io, schema

STAMP_FILE = "transcript_source.json"
RAW_FILE = "transcript_raw.json"
MATERIAL_CHANGED = ("[!] 素材换过了（和上次转写时不是同一个文件），旧的转写结果作废，"
                    "重新转写（会再调用一次云端转写）")


def write(work: Path, material: Path | str) -> None:
    if (fp := media_io.source_fingerprint(material)) is not None:
        schema.write_json(Path(work) / STAMP_FILE, {"source": fp})


def invalidate_if_replaced(work: Path, material: Path | str) -> bool:
    """素材换了就删掉旧转写并返回 True；素材暂时不可访问 / 没有旧转写 → False。"""
    work = Path(work)
    raw = work / RAW_FILE
    want = media_io.source_fingerprint(material)
    if want is None or not raw.exists():
        return False
    stored = schema.read_json_lenient(work / STAMP_FILE, None)
    have = stored.get("source") if isinstance(stored, dict) else None
    if have is None:
        write(work, material)  # 旧项目：补记
        return False
    if have == want:
        return False
    print(MATERIAL_CHANGED)
    raw.unlink(missing_ok=True)
    (work / STAMP_FILE).unlink(missing_ok=True)
    return True
