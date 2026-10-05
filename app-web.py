import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import random
import re
import time
from collections.abc import Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from yt_dlp.utils import DownloadError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----- config -----

PROXY_FILE = os.getenv("PROXY_FILE", "proxies.txt")
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
COOKIES_PATH = COOKIES_FILE if os.path.exists(COOKIES_FILE) else None
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
)
CACHE_DIR = Path(os.getenv("CACHE_DIR", "cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SEC = int(os.getenv("CACHE_TTL_SEC", "3600"))
CACHE_INDEX = CACHE_DIR / "index.json"
CACHE_MAX_BYTES = int(os.getenv("CACHE_MAX_BYTES", str(5 * 1024 * 1024 * 1024)))  # 5 GiB
PUBLIC_BASE = os.getenv("PUBLIC_BASE", "").rstrip("/")
PROXY_SOCKET_TIMEOUT = int(os.getenv("PROXY_SOCKET_TIMEOUT", "8"))
REQUEST_TIMEOUT_SEC = int(os.getenv("REQUEST_TIMEOUT_SEC", "300"))

PROXY_SOURCES = [
    s.strip() for s in os.getenv(
        "PROXY_SOURCES",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt,"
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt,"
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all",
    ).split(",") if s.strip()
]
PROXY_REFRESH_INTERVAL_SEC = int(os.getenv("PROXY_REFRESH_INTERVAL_SEC", str(86400)))
MAX_PROXY_ATTEMPTS = int(os.getenv("MAX_PROXY_ATTEMPTS", "20"))
PROXY_BAN_FAILS = int(os.getenv("PROXY_BAN_FAILS", "3"))
PROXY_BAN_SEC = int(os.getenv("PROXY_BAN_SEC", str(2 * 3600)))

mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("audio/ogg", ".opus")
mimetypes.add_type("audio/mp4", ".m4a")

RETRYABLE_TOKENS = (
    "403", "429", "timeout", "timed out", "connection",
    "unable to connect", "tunnel", "proxy", "reset by peer",
    "remote end closed", "econnrefused", "ssl", "transport",
    "unable to download webpage", "407",
    "login", "requested content is not available", "rate-limit",
    "rate limit", "empty media response", "private", "unavailable",
    "consent", "challenge", "checkpoint", "blocked",
    "sign in", "captcha", "geo", "restricted",
    "no video could be found", "authentication", "nsfw",
    "unable to extract", "no video formats", "no formats found",
    "video not available", "not available", "status code 0",
    "json", "graphql",
)

SITE_OPTS: dict[str, dict] = {
    "instagram.com": {
        "extractor_args": {"instagram": {"include_stories": ["1"]}},
        "format": "best",
    },
    "twitter.com": {"format": "best"},
    "x.com": {"format": "best"},
    "tiktok.com": {"format": "best"},
    "youtube.com": {"format": "bv*+ba/b"},
    "youtu.be": {"format": "bv*+ba/b"},
}

_SITE_MATCHERS = [(host, "." + host, opts) for host, opts in SITE_OPTS.items()]
_PROXY_LINE_RE = re.compile(r"^(?:(?:https?|socks[45])://)?([0-9]{1,3}(?:\.[0-9]{1,3}){3}):([0-9]{1,5})$")
_FINAL_NAME_RE = re.compile(r"^[0-9a-f]{16}\.[A-Za-z0-9]+$")
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")

# ----- helpers -----


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_youtube_host(host: str) -> bool:
    return host.endswith(_YOUTUBE_HOSTS)


def site_opts_for(host: str) -> dict:
    for suffix, dot_suffix, opts in _SITE_MATCHERS:
        if host == suffix or host.endswith(dot_suffix):
            return opts
    return {}


def parse_proxy_lines(lines: Iterable[str]) -> list[str]:
    out: set[str] = set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _PROXY_LINE_RE.match(line)
        if not m:
            continue
        host, port = m.group(1), m.group(2)
        if not (0 < int(port) <= 65535):
            continue
        out.add(f"http://{host}:{port}")
    return sorted(out)


def load_proxies() -> list[str]:
    try:
        with open(PROXY_FILE) as f:
            return parse_proxy_lines(f)
    except FileNotFoundError:
        logger.warning("%s not found; running with no proxies", PROXY_FILE)
        return []


def load_index() -> dict:
    if CACHE_INDEX.exists():
        try:
            return json.loads(CACHE_INDEX.read_text())
        except Exception:
            logger.exception("cache index unreadable; starting empty")
    return {}


# ----- state -----

PROXIES: list[str] = load_proxies()
CACHE: dict = load_index()
PROXY_HEALTH: dict[str, dict] = {}
_cache_lock = asyncio.Lock()
_proxy_lock = asyncio.Lock()


def proxy_is_banned(proxy: str | None) -> bool:
    if not proxy:
        return False
    h = PROXY_HEALTH.get(proxy)
    return bool(h and h.get("banned_until", 0) > time.time())


def proxy_record_success(proxy: str | None) -> None:
    if proxy:
        PROXY_HEALTH.pop(proxy, None)


def proxy_record_fail(proxy: str | None) -> None:
    if not proxy:
        return
    h = PROXY_HEALTH.setdefault(proxy, {"fails": 0, "banned_until": 0})
    h["fails"] += 1
    if h["fails"] >= PROXY_BAN_FAILS:
        h["banned_until"] = time.time() + PROXY_BAN_SEC


def proxy_banned_count() -> int:
    now = time.time()
    return sum(1 for h in PROXY_HEALTH.values() if h.get("banned_until", 0) > now)


def proxy_prune_health() -> int:
    now = time.time()
    stale = [p for p, h in PROXY_HEALTH.items() if 0 < h.get("banned_until", 0) <= now]
    for p in stale:
        PROXY_HEALTH.pop(p, None)
    return len(stale)


def is_retryable(err: Exception) -> bool:
    msg = str(err).lower()
    return any(tok in msg for tok in RETRYABLE_TOKENS)


def _proxy_pool() -> list[str | None]:
    if not PROXIES:
        return [None]
    available = [p for p in PROXIES if not proxy_is_banned(p)]
    n = min(max(MAX_PROXY_ATTEMPTS - 1, 0), len(available))
    pool: list[str | None] = [None]
    if n:
        pool.extend(random.sample(available, n))
    return pool


def rotate(fn, *args, **kwargs):
    pool = _proxy_pool()
    last_err: Exception | None = None
    attempts = 0
    for attempts, proxy in enumerate(pool, 1):
        try:
            result = fn(proxy, *args, **kwargs)
            proxy_record_success(proxy)
            return result, proxy
        except DownloadError as e:
            last_err = e
            msg = str(e).replace("\n", " ")[:200]
            if not is_retryable(e):
                logger.error("rotate.giveup attempt=%d proxy=%s err=%r", attempts, proxy, msg)
                raise HTTPException(400, f"yt-dlp: {msg}")
            proxy_record_fail(proxy)
            logger.warning("rotate.retry attempt=%d proxy=%s err=%r", attempts, proxy, msg)
        except Exception as e:
            logger.exception("rotate.fatal attempt=%d proxy=%s", attempts, proxy)
            raise HTTPException(500, str(e))
    logger.error("rotate.exhausted attempts=%d last=%r", attempts, str(last_err)[:200])
    raise HTTPException(502, f"all {attempts} proxies exhausted: {last_err}")


# ----- yt-dlp opts -----


def base_ydl_opts(url: str, audio: bool, proxy: str | None) -> dict:
    site = site_opts_for(_host(url))
    extractor_args = dict(site.get("extractor_args", {}))
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": PROXY_SOCKET_TIMEOUT,
        "http_headers": {"User-Agent": USER_AGENT},
        "format": "bestaudio/best" if audio else site.get("format", "best"),
    }
    if extractor_args:
        opts["extractor_args"] = extractor_args
    if COOKIES_PATH:
        opts["cookiefile"] = COOKIES_PATH
    if proxy:
        opts["proxy"] = proxy
    return opts


def _first_entry(info: Any) -> Any:
    if "entries" in info:
        entries = list(info["entries"])
        if not entries:
            raise DownloadError("no entries")
        return entries[0]
    return info


def extract_url(proxy: str | None, url: str, audio: bool) -> str:
    opts = base_ydl_opts(url, audio, proxy)
    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=False)
        if not info:
            raise DownloadError("no info")
        info = _first_entry(info)
        u = info.get("url")
        if u:
            return u
        for fmt in info.get("formats", []) or []:
            cand = fmt.get("url")
            if cand:
                return cand
        raise DownloadError("no direct url in info")


_PARTIAL_RE = re.compile(r"\.(part|ytdl)$|^[0-9a-f]{16}\.f\d+\.")


def _cleanup_partial(key: str) -> None:
    for fp in CACHE_DIR.glob(f"{key}*"):
        if _PARTIAL_RE.search(fp.name):
            fp.unlink(missing_ok=True)


def download_to_disk(proxy: str | None, url: str, audio: bool, key: str) -> tuple[str, str, int]:
    _cleanup_partial(key)
    opts = base_ydl_opts(url, audio, proxy)
    opts["outtmpl"] = str(CACHE_DIR / f"{key}.%(ext)s")
    opts["noprogress"] = True
    if audio:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
    else:
        opts["merge_output_format"] = "mp4"
    logger.info("dl.start proxy=%s key=%s audio=%s", proxy, key, audio)
    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=True)
        if not info:
            raise DownloadError("no info from download")
        info = _first_entry(info)
        final = Path(ydl.prepare_filename(info))
    if not final.exists():
        for sib in final.parent.glob(f"{final.stem}.*"):
            if not sib.name.endswith((".part", ".ytdl")):
                final = sib
                break
    if not final.exists():
        raise DownloadError(f"final file missing: {final}")
    ct = mimetypes.guess_type(final.name)[0] or "application/octet-stream"
    return final.name, ct, final.stat().st_size


# ----- proxy refresh -----


async def fetch_proxies() -> list[str]:
    async def fetch_one(client: httpx.AsyncClient, src: str) -> tuple[str, list[str]]:
        try:
            r = await client.get(src)
            r.raise_for_status()
            parsed = parse_proxy_lines(r.text.splitlines())
            logger.info("proxy.source.ok src=%s parsed=%d", src, len(parsed))
            return src, parsed
        except Exception as e:
            logger.warning("proxy.source.fail src=%s err=%s", src, e)
            return src, []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
        results = await asyncio.gather(*[fetch_one(client, s) for s in PROXY_SOURCES])
    merged: set[str] = set()
    for _, items in results:
        merged.update(items)
    return sorted(merged)


async def refresh_proxies() -> int:
    global PROXIES
    new_list = await fetch_proxies()
    async with _proxy_lock:
        changed = set(new_list) != set(PROXIES)
        if changed:
            Path(PROXY_FILE).write_text("\n".join(new_list) + "\n")
            PROXIES = new_list
    logger.info("proxy.refresh count=%d changed=%s", len(new_list), changed)
    return len(new_list)


async def proxy_refresh_loop():
    while True:
        try:
            await refresh_proxies()
        except Exception:
            logger.exception("proxy refresh failed")
        await asyncio.sleep(PROXY_REFRESH_INTERVAL_SEC)


# ----- cache -----


def cache_key(url: str, audio: bool) -> str:
    return hashlib.sha256(f"{url}|{int(audio)}".encode()).hexdigest()[:16]


def cache_lookup(key: str) -> dict | None:
    entry = CACHE.get(key)
    if not entry:
        return None
    if (time.time() - entry["created_at"]) > CACHE_TTL_SEC:
        return None
    if not (CACHE_DIR / entry["file"]).exists():
        return None
    return entry


def _flush_index() -> None:
    CACHE_INDEX.write_text(json.dumps(CACHE))


def cache_total_bytes() -> int:
    return sum(v.get("size", 0) for v in CACHE.values())


def _enforce_cache_size() -> int:
    total = cache_total_bytes()
    if total <= CACHE_MAX_BYTES:
        return 0
    by_age = sorted(CACHE.items(), key=lambda kv: kv[1].get("created_at", 0))
    removed = 0
    for k, v in by_age:
        if total <= CACHE_MAX_BYTES:
            break
        (CACHE_DIR / v["file"]).unlink(missing_ok=True)
        total -= v.get("size", 0)
        CACHE.pop(k, None)
        removed += 1
    if removed:
        logger.info("cache.lru evicted=%d remaining=%d bytes=%d", removed, len(CACHE), total)
    return removed


async def cache_put(key: str, entry: dict) -> None:
    async with _cache_lock:
        CACHE[key] = entry
        _enforce_cache_size()
        _flush_index()


async def cleanup_loop():
    while True:
        try:
            now = time.time()
            expired = [
                k for k, v in list(CACHE.items())
                if (now - v.get("created_at", 0)) > CACHE_TTL_SEC
                or not (CACHE_DIR / v["file"]).exists()
            ]
            removed = 0
            for k in expired:
                entry = CACHE.pop(k, None)
                if entry:
                    (CACHE_DIR / entry["file"]).unlink(missing_ok=True)
                    removed += 1
            indexed = {v["file"] for v in CACHE.values()}
            for fp in CACHE_DIR.iterdir():
                if fp.name == "index.json" or fp.name in indexed:
                    continue
                if not _FINAL_NAME_RE.match(fp.name):
                    continue
                if (now - fp.stat().st_mtime) > CACHE_TTL_SEC:
                    fp.unlink(missing_ok=True)
                    removed += 1
            if removed:
                async with _cache_lock:
                    _flush_index()
                logger.info("cache.cleanup evicted=%d remaining=%d", removed, len(CACHE))
            pruned = proxy_prune_health()
            if pruned:
                logger.info("proxy.prune cleared=%d remaining=%d", pruned, len(PROXY_HEALTH))
        except Exception:
            logger.exception("cache.cleanup error")
        await asyncio.sleep(300)


# ----- app -----


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ARG001
    _ = _app
    logger.info(
        "boot proxies=%d cookies=%s cache_dir=%s ttl=%ds entries=%d",
        len(PROXIES), bool(COOKIES_PATH), CACHE_DIR, CACHE_TTL_SEC, len(CACHE),
    )
    tasks = [
        asyncio.create_task(cleanup_loop()),
        asyncio.create_task(proxy_refresh_loop()),
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates("templates")


class VideoURL(BaseModel):
    url: str
    type: Literal["video", "audio"] = "video"


def file_url(request: Request, filename: str) -> str:
    if PUBLIC_BASE:
        return f"{PUBLIC_BASE}/files/{filename}"
    return str(request.url_for("get_file", filename=filename))


async def _with_timeout(fn, *args, label: str):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args), timeout=REQUEST_TIMEOUT_SEC
        )
    except TimeoutError as e:
        raise HTTPException(504, f"{label} timeout after {REQUEST_TIMEOUT_SEC}s") from e


async def fetch_or_cache(url: str, audio: bool, request: Request) -> dict:
    if not url:
        raise HTTPException(400, "no url")
    host = _host(url)

    if not is_youtube_host(host):
        direct, proxy = await _with_timeout(rotate, extract_url, url, audio, label="extract")
        logger.info("direct.extract host=%s proxy=%s", host, proxy)
        return {
            "download_url": direct,
            "cached": False,
            "source": "direct",
            "proxy_used": proxy,
        }

    key = cache_key(url, audio)
    hit = cache_lookup(key)
    if hit:
        age = int(time.time() - hit["created_at"])
        logger.info("cache.hit key=%s file=%s age=%ds", key, hit["file"], age)
        return {
            "download_url": file_url(request, hit["file"]),
            "cached": True,
            "source": "cache",
            "expires_in_sec": max(0, CACHE_TTL_SEC - age),
            "content_type": hit.get("content_type"),
        }
    (filename, ct, size), proxy = await _with_timeout(
        rotate, download_to_disk, url, audio, key, label="download"
    )
    entry = {
        "file": filename,
        "source": url,
        "audio": audio,
        "created_at": time.time(),
        "content_type": ct,
        "size": size,
        "proxy": proxy,
    }
    await cache_put(key, entry)
    logger.info("cache.miss key=%s file=%s proxy=%s", key, filename, proxy)
    return {
        "download_url": file_url(request, filename),
        "cached": False,
        "source": "youtube",
        "expires_in_sec": CACHE_TTL_SEC,
        "content_type": ct,
        "proxy_used": proxy,
    }


@app.post("/download")
async def post_download(video: VideoURL, request: Request):
    return await fetch_or_cache(video.url, video.type == "audio", request)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/dl")
async def get_dl(request: Request, url: str = Query(...), type: str = "video"):
    result = await fetch_or_cache(url, type == "audio", request)
    return templates.TemplateResponse(
        request, "download.html", {"dl_url": result["download_url"]}
    )


@app.get("/files/{filename}", name="get_file")
async def get_file(filename: str):
    if not _FINAL_NAME_RE.match(filename):
        raise HTTPException(404, "not found")
    fp = CACHE_DIR / filename
    if not fp.exists():
        raise HTTPException(404, "not found")
    return FileResponse(
        fp,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/healthz")
async def health():
    return {
        "ok": True,
        "proxies": len(PROXIES),
        "proxies_banned": proxy_banned_count(),
        "max_proxy_attempts": MAX_PROXY_ATTEMPTS,
        "proxy_refresh_interval_sec": PROXY_REFRESH_INTERVAL_SEC,
        "cookies": bool(COOKIES_PATH),
        "cache_entries": len(CACHE),
        "cache_bytes": cache_total_bytes(),
        "cache_max_bytes": CACHE_MAX_BYTES,
        "cache_ttl_sec": CACHE_TTL_SEC,
        "request_timeout_sec": REQUEST_TIMEOUT_SEC,
    }


@app.post("/admin/refresh-proxies")
async def admin_refresh_proxies():
    count = await refresh_proxies()
    return {"ok": True, "proxies": count}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3000)
