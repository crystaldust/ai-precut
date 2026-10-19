"""GL-21：/media/ 路由先按 / 切分再逐段 percent-decode，中文/空格项目名能播放。"""
import json
from urllib.parse import quote

import pytest

from conftest import call, make_project

NAME = "九月 一号"
VIDEO = b"\x00" * 1000


def test_proxy_chinese_space_project_200(gui_server):
    make_project(gui_server.root, NAME, **{"work/proxy.mp4": VIDEO})
    status, body, _ = call(gui_server, "GET", f"/media/{quote(NAME)}/proxy", token=False)
    assert status == 200
    assert len(body) == len(VIDEO)


def test_proxy_range_chinese_project_206(gui_server):
    make_project(gui_server.root, NAME, **{"work/proxy.mp4": VIDEO})
    status, body, headers = call(gui_server, "GET", f"/media/{quote(NAME)}/proxy",
                                 token=False, headers={"Range": "bytes=10-19"})
    assert status == 206
    assert len(body) == 10
    assert headers["content-range"] == "bytes 10-19/1000"


def test_preview_chinese_project_200(gui_server):
    make_project(gui_server.root, NAME, **{"output/v1/preview.mp4": VIDEO})
    status, body, _ = call(gui_server, "GET", f"/media/{quote(NAME)}/preview/v1", token=False)
    assert status == 200
    assert len(body) == len(VIDEO)


def test_encoded_slash_in_project_rejected(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "GET", "/media/a%2F..%2Fb/proxy", token=False)
    assert status == 400


def test_encoded_traversal_version_rejected(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "GET", "/media/p1/preview/%2E%2E", token=False)
    assert status == 400


@pytest.mark.parametrize("seg", ["a%2Fb", "%2e%2e", "%2E%2E", "a%5Cb", "a%00b", "%2d%2dhelp",
                                 "%20p1"])
def test_encoded_bad_project_segment_rejected(gui_server, seg):
    make_project(gui_server.root, **{"work/proxy.mp4": VIDEO})
    status, _, _ = call(gui_server, "GET", f"/media/{seg}/proxy", token=False)
    assert status == 400


@pytest.mark.parametrize("seg", ["v1%2F..", "%2e%2e", "v1%5C..", "v1%00"])
def test_encoded_bad_version_rejected(gui_server, seg):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "GET", f"/media/p1/preview/{seg}", token=False)
    assert status == 400


def test_symlink_escape_not_served(gui_server):
    secret = gui_server.root / "secret.bin"
    secret.write_bytes(b"secret")
    pdir = make_project(gui_server.root)
    (pdir / "work/proxy.mp4").symlink_to(secret)
    status, body, _ = call(gui_server, "GET", "/media/p1/proxy", token=False)
    assert status == 404
    assert b"secret" not in body


def test_directory_in_place_of_file_is_404(gui_server):
    pdir = make_project(gui_server.root)
    (pdir / "work/proxy.mp4").mkdir()
    status, body, _ = call(gui_server, "GET", "/media/p1/proxy", token=False)
    assert status == 404
    assert "error" in json.loads(body)
