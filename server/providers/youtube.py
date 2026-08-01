"""YouTube channel feed for the podcast tab.

Deliberately keyless by default: a channel's RSS feed
(`/feeds/videos.xml?channel_id=UC...`) returns the latest 15 uploads with
titles, thumbnails, publish dates and view counts, costs nothing and has no
quota. That covers the common case.

Set `TF_YOUTUBE_API_KEY` to also pull the full back catalogue via the YouTube
Data API (free tier, 10,000 units/day; a `playlistItems` page of 50 videos
costs 1 unit, so a whole channel is a rounding error).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from ..cache import cache
from ..config import CACHE_DIR, settings

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


class YouTubeError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0), headers=_UA,
                             follow_redirects=True)


def parse_channel_ref(raw: str) -> tuple[str, str]:
    """Work out what the user put in TF_YOUTUBE_CHANNEL.

    Accepts a bare channel id, an @handle, a /channel/UC... URL, a /@handle
    URL, or a legacy /c/Name or /user/Name URL.
    Returns (kind, value) where kind is "id" or "handle" or "path".
    """
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        raise YouTubeError("no channel configured")
    if _CHANNEL_ID_RE.match(raw):
        return "id", raw
    if raw.startswith("@"):
        return "handle", raw[1:]
    if "youtube.com" in raw or "youtu.be" in raw:
        m = re.search(r"/channel/(UC[\w-]{22})", raw)
        if m:
            return "id", m.group(1)
        m = re.search(r"/@([\w.\-]+)", raw)
        if m:
            return "handle", m.group(1)
        m = re.search(r"/(?:c|user)/([\w.\-]+)", raw)
        if m:
            return "path", m.group(1)
        raise YouTubeError(f"could not read a channel out of {raw!r}")
    return "handle", raw.lstrip("@")


async def resolve_channel_id(raw: str) -> str:
    """Turn whatever was configured into a UC... channel id.

    Scrapes the public channel page, which needs no API key. Cached for a
    month - a channel id never changes.
    """
    kind, value = parse_channel_ref(raw)
    if kind == "id":
        return value

    key = f"yt:channelid:{kind}:{value.lower()}"

    async def fetch():
        urls = ([f"https://www.youtube.com/@{value}"] if kind == "handle"
                else [f"https://www.youtube.com/c/{value}",
                      f"https://www.youtube.com/user/{value}"])
        async with _client() as c:
            for url in urls:
                try:
                    r = await c.get(url)
                except httpx.HTTPError:
                    continue
                if r.status_code != 200:
                    continue
                # Order matters. A bare `"channelId"` search picks up the
                # *recommended* channels in the sidebar; these three are the
                # page's own identity.
                for pat in (
                    r'"rssUrl":"https://www\.youtube\.com/feeds/videos\.xml\?channel_id=(UC[\w-]{22})"',
                    r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
                    r'"channelMetadataRenderer":\{.*?"externalId":"(UC[\w-]{22})"',
                ):
                    m = re.search(pat, r.text, re.S)
                    if m:
                        return m.group(1)
        raise YouTubeError(f"could not resolve channel {raw!r} - check the handle")

    return await cache.get_or_set(key, 2_592_000, fetch)


def _text(node, path: str, default: str = "") -> str:
    el = node.find(path, _NS)
    return (el.text or default) if el is not None else default


def _parse_feed(xml: str) -> dict:
    root = ET.fromstring(xml)
    channel = {
        "id": _text(root, "yt:channelId"),
        "title": _text(root, "atom:title"),
        "url": "",
    }
    link = root.find("atom:link[@rel='alternate']", _NS)
    if link is not None:
        channel["url"] = link.get("href", "")

    videos = []
    for e in root.findall("atom:entry", _NS):
        group = e.find("media:group", _NS)
        thumb = group.find("media:thumbnail", _NS) if group is not None else None
        stats = group.find("media:community/media:statistics", _NS) if group is not None else None
        rating = group.find("media:community/media:starRating", _NS) if group is not None else None
        desc = group.find("media:description", _NS) if group is not None else None
        vid = _text(e, "yt:videoId")
        if not vid:
            continue
        videos.append({
            "id": vid,
            "title": _text(e, "atom:title"),
            "published": _text(e, "atom:published"),
            "updated": _text(e, "atom:updated"),
            "description": (desc.text or "") if desc is not None else "",
            "thumbnail": thumb.get("url") if thumb is not None
                         else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "views": int(stats.get("views")) if stats is not None and stats.get("views") else None,
            "likes": int(rating.get("count")) if rating is not None and rating.get("count") else None,
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    videos.sort(key=lambda v: v["published"], reverse=True)
    return {"channel": channel, "videos": videos}


async def feed(channel_id: str) -> dict:
    """Latest ~15 uploads. No API key, no quota."""
    async def fetch():
        async with _client() as c:
            r = await c.get("https://www.youtube.com/feeds/videos.xml",
                            params={"channel_id": channel_id})
            if r.status_code != 200:
                raise YouTubeError(f"feed returned HTTP {r.status_code}")
            return r.text

    xml = await cache.get_or_set(f"yt:feed:{channel_id}", settings.ttl_videos, fetch)
    return _parse_feed(xml)


# --------------------------------------------------------------------------
# Keyless fallback: read the channel page directly
#
# Not every channel is served an RSS feed - YouTube 404s the feed for some
# channels even when they have plenty of public uploads. When that happens we
# read `ytInitialData` off the channel tabs instead. Still no API key.
# --------------------------------------------------------------------------
_TABS = ("videos", "streams", "podcasts", "shorts")


def _initial_data(html: str) -> dict | None:
    m = (re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", html, re.S)
         or re.search(r'ytInitialData"\]\s*=\s*(\{.*?\});', html, re.S))
    if not m:
        return None
    try:
        return __import__("json").loads(m.group(1))
    except ValueError:
        return None


def _walk_lockups(node, out: list, seen: set) -> None:
    """Collect every lockupViewModel (YouTube's current grid item shape)."""
    if isinstance(node, dict):
        lock = node.get("lockupViewModel")
        if isinstance(lock, dict) and lock.get("contentId"):
            vid = lock["contentId"]
            if (len(vid) == 11 and vid not in seen
                    and "VIDEO" in (lock.get("contentType") or "VIDEO")):
                meta = (lock.get("metadata") or {}).get("lockupMetadataViewModel") or {}
                title = ((meta.get("title") or {}).get("content") or "").strip()
                if title:
                    seen.add(vid)
                    out.append({"id": vid, "title": title,
                                **_lockup_extras(lock, meta)})
        for v in node.values():
            _walk_lockups(v, out, seen)
    elif isinstance(node, list):
        for v in node:
            _walk_lockups(v, out, seen)


def _lockup_extras(lock: dict, meta: dict) -> dict:
    thumb = None
    sources = (((lock.get("contentImage") or {}).get("thumbnailViewModel") or {})
               .get("image") or {}).get("sources") or []
    if sources:
        thumb = max(sources, key=lambda s: s.get("width") or 0).get("url")

    parts: list[str] = []
    for row in _iter_metadata_rows(meta):
        for part in row.get("metadataParts") or []:
            text = ((part.get("text") or {}).get("content") or "").strip()
            if text:
                parts.append(text)

    views = None
    published = None
    for text in parts:
        low = text.lower()
        if "view" in low and views is None:
            views = _parse_count(text)
        elif "ago" in low and published is None:
            published = text
    return {
        "thumbnail": thumb or f"https://i.ytimg.com/vi/{lock['contentId']}/hqdefault.jpg",
        "views": views,
        "published": None,          # the page only gives relative time
        "published_text": published,
        "likes": None,
        "description": "",
        "url": f"https://www.youtube.com/watch?v={lock['contentId']}",
    }


def _iter_metadata_rows(node):
    if isinstance(node, dict):
        if "metadataRows" in node and isinstance(node["metadataRows"], list):
            yield from node["metadataRows"]
        for v in node.values():
            yield from _iter_metadata_rows(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_metadata_rows(v)


_REL_UNITS = {"second": 1/86400, "minute": 1/1440, "hour": 1/24, "day": 1,
              "week": 7, "month": 30.44, "year": 365.25}


def _relative_days(text: str | None) -> float:
    """'Streamed 10 months ago' -> ~304 days. Used only to order the merged
    tabs, since the channel page gives relative times rather than dates."""
    if not text:
        return 10 ** 6
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)", text.lower())
    if not m:
        return 10 ** 6
    return int(m.group(1)) * _REL_UNITS[m.group(2)]


def _parse_count(text: str) -> int | None:
    m = re.search(r"([\d.,]+)\s*([KMB])?", text.replace(",", ""))
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    return int(n * {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(m.group(2) or "", 1))


async def scrape_channel(raw: str) -> dict:
    """Read uploads straight off the channel page. No key, no quota."""
    kind, value = parse_channel_ref(raw)
    base = (f"https://www.youtube.com/channel/{value}" if kind == "id"
            else f"https://www.youtube.com/@{value}" if kind == "handle"
            else f"https://www.youtube.com/c/{value}")

    async def fetch():
        videos: list[dict] = []
        seen: set[str] = set()
        title = ""
        channel_id = value if kind == "id" else ""
        async with _client() as c:
            for tab in _TABS:
                try:
                    r = await c.get(f"{base}/{tab}")
                except httpx.HTTPError:
                    continue
                if r.status_code != 200:
                    continue
                if not title:
                    t = re.search(r'<meta property="og:title" content="([^"]*)"', r.text)
                    title = t.group(1) if t else ""
                if not channel_id:
                    m = re.search(r'"externalId":"(UC[\w-]{22})"', r.text)
                    channel_id = m.group(1) if m else ""
                data = _initial_data(r.text)
                if data:
                    _walk_lockups(data, videos, seen)
        if not videos:
            raise YouTubeError("no videos found on the channel page")
        # Tabs are each newest-first, so the merged list needs re-sorting.
        videos.sort(key=lambda v: _relative_days(v.get("published_text")))
        return {"channel": {"id": channel_id, "title": title,
                            "url": f"https://www.youtube.com/channel/{channel_id}"
                                   if channel_id else base},
                "videos": videos}

    return await cache.get_or_set(f"yt:scrape:{kind}:{value.lower()}",
                                  settings.ttl_videos, fetch)


# --------------------------------------------------------------------------
# Optional: full back catalogue via the Data API
# --------------------------------------------------------------------------
async def catalogue(channel_id: str, limit: int = 200) -> list[dict]:
    """Every upload, newest first. Needs TF_YOUTUBE_API_KEY."""
    if not settings.youtube_api_key:
        return []

    async def fetch():
        uploads = "UU" + channel_id[2:]      # uploads playlist id
        out, page = [], None
        async with _client() as c:
            while len(out) < limit:
                params = {"part": "snippet,contentDetails", "playlistId": uploads,
                          "maxResults": 50, "key": settings.youtube_api_key}
                if page:
                    params["pageToken"] = page
                r = await c.get("https://www.googleapis.com/youtube/v3/playlistItems",
                                params=params)
                if r.status_code != 200:
                    raise YouTubeError(f"data api HTTP {r.status_code}: {r.text[:120]}")
                data = r.json()
                for item in data.get("items", []):
                    sn = item.get("snippet") or {}
                    vid = ((item.get("contentDetails") or {}).get("videoId")
                           or (sn.get("resourceId") or {}).get("videoId"))
                    if not vid:
                        continue
                    thumbs = sn.get("thumbnails") or {}
                    best = (thumbs.get("maxres") or thumbs.get("standard")
                            or thumbs.get("high") or thumbs.get("medium") or {})
                    out.append({
                        "id": vid,
                        "title": sn.get("title"),
                        "published": sn.get("publishedAt"),
                        "description": sn.get("description") or "",
                        "thumbnail": best.get("url")
                                     or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                        "views": None, "likes": None,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                    })
                page = data.get("nextPageToken")
                if not page:
                    break
        return out[:limit]

    return await cache.get_or_set(f"yt:catalogue:{channel_id}:{limit}",
                                  settings.ttl_videos, fetch)


async def videos(raw_channel: str, full: bool = False) -> dict:
    channel_id = await resolve_channel_id(raw_channel)

    # RSS is the nicest source (real timestamps), but YouTube does not serve a
    # feed for every channel, so fall back to reading the channel page.
    try:
        data = await feed(channel_id)
        if not data["videos"]:
            raise YouTubeError("feed was empty")
        data["source"] = "rss"
    except YouTubeError:
        data = await scrape_channel(raw_channel)
        data = {"channel": dict(data["channel"]), "videos": list(data["videos"])}
        data["source"] = "channel-page"
    data["channel"]["id"] = data["channel"].get("id") or channel_id

    if full and settings.youtube_api_key:
        try:
            extra = await catalogue(channel_id)
        except YouTubeError:
            extra = []
        if extra:
            seen = {v["id"] for v in data["videos"]}
            merged = data["videos"] + [v for v in extra if v["id"] not in seen]
            merged.sort(key=lambda v: v["published"] or "", reverse=True)
            data["videos"] = merged
            data["source"] = "rss+api"
    data["count"] = len(data["videos"])
    return data
