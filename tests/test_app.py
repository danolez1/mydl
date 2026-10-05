import json
import time

import pytest
from fastapi import HTTPException
from yt_dlp.utils import DownloadError

NAME = "0123456789abcdef.mp4"


def test_parse_proxy_lines(mod):
    got = mod.parse_proxy_lines(
        [
            "1.2.3.4:8080",
            "http://5.6.7.8:3128",
            "socks5://9.9.9.9:1080",
            "# a comment",
            "",
            "not a proxy",
            "1.2.3.4:99999",
            "1.2.3.4:0",
            "1.2.3.4:8080",
        ]
    )
    assert got == ["http://1.2.3.4:8080", "http://5.6.7.8:3128", "http://9.9.9.9:1080"]


def test_hosts_and_site_options(mod):
    assert mod._host("https://WWW.YouTube.com/watch?v=1") == "www.youtube.com"
    assert mod.is_youtube_host("www.youtube.com")
    assert mod.is_youtube_host("youtu.be")
    assert not mod.is_youtube_host("notyoutube.org")
    assert mod.site_opts_for("www.tiktok.com")["format"] == "best"
    assert mod.site_opts_for("evil-tiktok.com") == {}
    assert "extractor_args" in mod.site_opts_for("instagram.com")


def test_retryable_errors(mod):
    assert mod.is_retryable(DownloadError("HTTP Error 429: Too Many Requests"))
    assert mod.is_retryable(DownloadError("Sign in to confirm"))
    assert not mod.is_retryable(DownloadError("Unsupported URL: ftp://x"))


def test_ydl_options(mod):
    opts = mod.base_ydl_opts("https://youtu.be/x", audio=False, proxy="http://1.2.3.4:80")
    assert opts["format"] == "bv*+ba/b" and opts["proxy"] == "http://1.2.3.4:80"
    assert opts["noplaylist"] is True
    audio = mod.base_ydl_opts("https://youtu.be/x", audio=True, proxy=None)
    assert audio["format"] == "bestaudio/best" and "proxy" not in audio


def test_proxy_is_banned_after_repeated_failures_and_cleared_by_success(mod):
    p = "http://1.2.3.4:80"
    for _ in range(mod.PROXY_BAN_FAILS - 1):
        mod.proxy_record_fail(p)
    assert not mod.proxy_is_banned(p)
    mod.proxy_record_fail(p)
    assert mod.proxy_is_banned(p) and mod.proxy_banned_count() == 1
    mod.proxy_record_success(p)
    assert not mod.proxy_is_banned(p)


def test_expired_bans_are_pruned(mod):
    mod.PROXY_HEALTH["http://1.2.3.4:80"] = {"fails": 3, "banned_until": time.time() - 1}
    assert mod.proxy_prune_health() == 1 and not mod.PROXY_HEALTH


def test_proxy_pool_always_starts_direct_and_skips_banned(mod):
    assert mod._proxy_pool() == [None]
    mod.PROXIES.extend(["http://1.1.1.1:1", "http://2.2.2.2:2"])
    mod.PROXY_HEALTH["http://1.1.1.1:1"] = {"fails": 3, "banned_until": time.time() + 60}
    pool = mod._proxy_pool()
    assert pool[0] is None and pool[1:] == ["http://2.2.2.2:2"]


def test_rotate_retries_then_succeeds(mod):
    mod.PROXIES.extend(["http://1.1.1.1:1"])
    seen = []

    def fn(proxy, arg):
        seen.append(proxy)
        if proxy is None:
            raise DownloadError("HTTP Error 403")
        return arg * 2

    result, proxy = mod.rotate(fn, 21)
    assert (result, proxy) == (42, "http://1.1.1.1:1") and seen == [None, "http://1.1.1.1:1"]


def test_rotate_gives_up_on_a_non_retryable_error(mod):
    def fn(proxy):
        raise DownloadError("Unsupported URL")

    with pytest.raises(HTTPException) as err:
        mod.rotate(fn)
    assert err.value.status_code == 400


def test_rotate_reports_exhaustion_as_502(mod):
    def fn(proxy):
        raise DownloadError("timed out")

    with pytest.raises(HTTPException) as err:
        mod.rotate(fn)
    assert err.value.status_code == 502


def test_rotate_turns_other_errors_into_500(mod):
    def fn(proxy):
        raise RuntimeError("boom")

    with pytest.raises(HTTPException) as err:
        mod.rotate(fn)
    assert err.value.status_code == 500


def test_cache_key_is_stable_and_separates_audio(mod):
    assert mod.cache_key("u", False) == mod.cache_key("u", False)
    assert mod.cache_key("u", False) != mod.cache_key("u", True)
    assert len(mod.cache_key("u", False)) == 16


def test_cache_lookup_needs_a_fresh_entry_with_its_file(mod):
    key = "k"
    mod.CACHE[key] = {"file": NAME, "created_at": time.time()}
    assert mod.cache_lookup(key) is None  # file missing
    (mod.CACHE_DIR / NAME).write_bytes(b"x")
    assert mod.cache_lookup(key) is not None
    mod.CACHE[key]["created_at"] = time.time() - mod.CACHE_TTL_SEC - 1
    assert mod.cache_lookup(key) is None  # expired


def test_cache_eviction_removes_the_oldest_first(mod, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_MAX_BYTES", 150)
    for i, age in enumerate((300, 200, 100)):
        name = f"{i:016x}.mp4"
        (mod.CACHE_DIR / name).write_bytes(b"x" * 100)
        mod.CACHE[f"k{i}"] = {"file": name, "created_at": time.time() - age, "size": 100}
    assert mod._enforce_cache_size() == 2
    assert list(mod.CACHE) == ["k2"]
    assert not (mod.CACHE_DIR / f"{0:016x}.mp4").exists()


def test_healthz(client, mod):
    body = client.get("/healthz").json()
    assert body["ok"] is True and body["proxies"] == 0 and body["cache_entries"] == 0


def test_files_rejects_names_that_are_not_cache_files(client):
    assert client.get("/files/..%2Fsecret").status_code == 404
    assert client.get("/files/notahash.mp4").status_code == 404
    assert client.get(f"/files/{NAME}").status_code == 404


def test_files_serves_a_cached_file_as_an_attachment(client, mod):
    (mod.CACHE_DIR / NAME).write_bytes(b"video")
    r = client.get(f"/files/{NAME}")
    assert r.status_code == 200 and r.content == b"video"
    assert NAME in r.headers["content-disposition"]


def test_download_of_another_site_returns_the_direct_url(client, mod, monkeypatch):
    monkeypatch.setattr(mod, "extract_url", lambda proxy, url, audio: "https://cdn.example/v.mp4")
    r = client.post("/download", json={"url": "https://www.tiktok.com/@a/video/1"})
    assert r.status_code == 200
    assert r.json()["download_url"] == "https://cdn.example/v.mp4"
    assert r.json()["source"] == "direct" and r.json()["cached"] is False


def test_download_rejects_a_bad_type(client):
    assert client.post("/download", json={"url": "https://x.io", "type": "gif"}).status_code == 422


def test_youtube_download_is_cached_for_the_second_request(client, mod, monkeypatch):
    calls = []

    def fake_download(proxy, url, audio, key):
        calls.append(key)
        name = f"{key}.mp4"
        (mod.CACHE_DIR / name).write_bytes(b"data")
        return name, "video/mp4", 4

    monkeypatch.setattr(mod, "download_to_disk", fake_download)
    body = {"url": "https://www.youtube.com/watch?v=abc"}
    first = client.post("/download", json=body).json()
    second = client.post("/download", json=body).json()
    assert first["cached"] is False and first["source"] == "youtube"
    assert second["cached"] is True and second["source"] == "cache"
    assert len(calls) == 1
    assert json.loads(mod.CACHE_INDEX.read_text())


def test_public_base_overrides_the_file_url(client, mod, monkeypatch):
    monkeypatch.setattr(mod, "PUBLIC_BASE", "https://dl.example.com")
    monkeypatch.setattr(mod, "extract_url", lambda *a: "x")
    (mod.CACHE_DIR / NAME).write_bytes(b"x")
    mod.CACHE["k"] = {"file": NAME, "created_at": time.time(), "size": 1}
    monkeypatch.setattr(mod, "cache_key", lambda url, audio: "k")
    r = client.post("/download", json={"url": "https://youtu.be/abc"}).json()
    assert r["download_url"] == f"https://dl.example.com/files/{NAME}"


def test_index_and_download_pages_render(client, mod, monkeypatch):
    assert client.get("/").status_code == 200
    monkeypatch.setattr(mod, "extract_url", lambda proxy, url, audio: "https://cdn.example/v.mp4")
    r = client.get("/dl", params={"url": "https://x.com/a/status/1"})
    assert r.status_code == 200 and "https://cdn.example/v.mp4" in r.text


def test_dl_requires_a_url(client):
    assert client.get("/dl").status_code == 422
