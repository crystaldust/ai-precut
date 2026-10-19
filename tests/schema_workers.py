"""跨进程测试的 worker（multiprocessing spawn 要求可按模块名导入）。"""
from pathlib import Path


def bump_counter(path: str, times: int) -> None:
    from pipeline import schema
    for _ in range(times):
        schema.update(Path(path), lambda c: {**c, "n": c.get("n", 0) + 1})
