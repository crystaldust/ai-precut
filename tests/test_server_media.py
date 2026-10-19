"""GL-21：/media/ 路由先按 / 切分再逐段 percent-decode，中文/空格项目名能播放。"""
import json
from urllib.parse import quote

import pytest

from conftest import call, make_project

NAME = "九月 一号"
VIDEO = b"\x00" * 1000


def test_proxy_chinese_space_project_200(gui_server):
    make_project(gui_server.root, NAME, **{"work/proxy.mp4": VIDEO})
    status, body, _ = call(gui_server, "GET", f"/media/{quote(NAME)}/proxy")
    assert status == 200
    assert len(body) == len(VIDEO)


def test_proxy_range_chinese_project_206(gui_server):
    make_project(gui_server.root, NAME, **{"work/proxy.mp4": VIDEO})
    status, body, headers = call(gui_server, "GET", f"/media/{quote(NAME)}/proxy",
                                 headers={"Range": "bytes=10-19"})
    assert status == 206
    assert len(body) == 10
    assert headers["content-range"] == "bytes 10-19/1000"


def test_preview_chinese_project_200(gui_server):
    make_project(gui_server.root, NAME, **{"output/v1/preview.mp4": VIDEO})
    status, body, _ = call(gui_server, "GET", f"/media/{quote(NAME)}/preview/v1")
    assert status == 200
    assert len(body) == len(VIDEO)


def test_encoded_slash_in_project_rejected(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "GET", "/media/a%2F..%2Fb/proxy")
    assert status == 400


def test_encoded_traversal_version_rejected(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "GET", "/media/p1/preview/%2E%2E")
    assert status == 400


@pytest.mark.parametrize("seg", ["a%2Fb", "%2e%2e", "%2E%2E", "a%5Cb", "a%00b", "%2d%2dhelp",
                                 "%20p1"])
def test_encoded_bad_project_segment_rejected(gui_server, seg):
    make_project(gui_server.root, **{"work/proxy.mp4": VIDEO})
    status, _, _ = call(gui_server, "GET", f"/media/{seg}/proxy")
    assert status == 400


@pytest.mark.parametrize("seg", ["v1%2F..", "%2e%2e", "v1%5C..", "v1%00"])
def test_encoded_bad_version_rejected(gui_server, seg):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "GET", f"/media/p1/preview/{seg}")
    assert status == 400


def test_symlink_escape_not_served(gui_server):
    secret = gui_server.root / "secret.bin"
    secret.write_bytes(b"secret")
    pdir = make_project(gui_server.root)
    (pdir / "work/proxy.mp4").symlink_to(secret)
    status, body, _ = call(gui_server, "GET", "/media/p1/proxy")
    assert status == 404
    assert b"secret" not in body


def test_directory_in_place_of_file_is_404(gui_server):
    pdir = make_project(gui_server.root)
    (pdir / "work/proxy.mp4").mkdir()
    status, body, _ = call(gui_server, "GET", "/media/p1/proxy")
    assert status == 404
    assert "error" in json.loads(body)


# ---------------------------------------------------------------- KI-30：Range 按 RFC 9110 解析
DATA = bytes(range(256)) * 4  # 1000+ 字节、内容可区分
DATA = DATA[:1000]


@pytest.mark.parametrize("rng, status, body, crange", [
    ("bytes=-100", 206, DATA[-100:], "bytes 900-999/1000"),
    ("bytes=990-", 206, DATA[990:], "bytes 990-999/1000"),
    ("bytes=1000-", 416, b"", "bytes */1000"),
    ("bytes=5-2", 200, DATA, None),
    ("bytes=0-99999", 206, DATA, "bytes 0-999/1000"),
    ("bytes=0-1,5-6", 200, DATA, None),
    ("items=0-1", 200, DATA, None),
    ("bytes=-0", 416, b"", "bytes */1000"),
    ("bytes=10-19", 206, DATA[10:20], "bytes 10-19/1000"),
])
def test_range_semantics(gui_server, rng, status, body, crange):
    make_project(gui_server.root, **{"work/proxy.mp4": DATA})
    got_status, got, headers = call(gui_server, "GET", "/media/p1/proxy",
                                    headers={"Range": rng})
    assert got_status == status and got == body
    assert headers.get("content-range") == crange
    assert headers["x-content-type-options"] == "nosniff"


def test_range_on_empty_file_is_416(gui_server):
    make_project(gui_server.root, **{"work/proxy.mp4": b""})
    status, _, headers = call(gui_server, "GET", "/media/p1/proxy",
                              headers={"Range": "bytes=0-"})
    assert status == 416 and headers["content-range"] == "bytes */0"


@pytest.mark.parametrize("header, size, expected", [
    (None, 10, None), ("", 10, None),
    ("bytes=0-4", 10, (0, 4)), ("bytes=-3", 10, (7, 9)), ("bytes=-30", 10, (0, 9)),
    ("bytes=8-", 10, (8, 9)), ("bytes=10-", 10, "unsatisfiable"), ("bytes=-0", 10, "unsatisfiable"),
    ("bytes=4-2", 10, None), ("bytes=0-1,3-4", 10, None), ("items=0-1", 10, None),
    ("bytes=a-b", 10, None), ("bytes=-", 10, None), ("bytes=0-0", 0, "unsatisfiable"),
])
def test_parse_range_unit(header, size, expected):
    from gui import media
    assert media.parse_range(header, size) == expected


# ---------------------------------------------------------------- 审查修复 L11：HEAD 只回头
def test_head_static_and_media(gui_server):
    make_project(gui_server.root, **{"work/proxy.mp4": DATA})
    status, body, headers = call(gui_server, "HEAD", "/static/common.js", token=False)
    assert status == 200 and body == b"" and int(headers["content-length"]) > 0
    status, body, headers = call(gui_server, "HEAD", "/media/p1/proxy",
                                 headers={"Range": "bytes=0-9"})
    assert status == 206 and body == b"" and headers["content-range"] == "bytes 0-9/1000"
    status, body, headers = call(gui_server, "HEAD", "/")
    assert status == 200 and body == b"" and "content-security-policy" in headers


def test_huge_range_numbers_are_416_not_500(gui_server):  # 审查修复 L14
    from gui import media
    assert media.parse_range("bytes=" + "9" * 5000 + "-", 10) == "unsatisfiable"
    assert media.parse_range("bytes=-" + "9" * 40, 10) == "unsatisfiable"
    make_project(gui_server.root, **{"work/proxy.mp4": DATA})
    status, _, _ = call(gui_server, "GET", "/media/p1/proxy",
                        headers={"Range": "bytes=" + "9" * 15 + "-"})
    assert status == 416
