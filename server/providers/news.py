"""Transfer rumours, aggregated from established football desks.

API-Football only carries *completed* moves, so rumours have to come from
journalism. These are all public RSS feeds - no keys, no quota:

  BBC Gossip            a daily curated round-up of the day's transfer talk
  Guardian Transfer Window  the paper's dedicated transfer desk
  Sky Sports            football news wire
  BBC / Guardian football   general feeds, filtered to transfer stories
  90min                 aggregator, kept at a lower trust tier

Each item is tagged with its source tier so the UI can be honest that a
tabloid-sourced "gossip" line is not the same thing as a club announcement.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..cache import cache
from ..config import settings
from ..data.clubs import CLUBS, resolve_exact

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# tier 1 = the outlet's own reporting desk, tier 2 = round-ups and aggregation
FEEDS: list[dict] = [
    {"id": "bbc-gossip", "name": "BBC Gossip", "tier": 1, "rumour_only": True,
     "url": "https://feeds.bbci.co.uk/sport/football/gossip/rss.xml"},
    {"id": "guardian-transfers", "name": "Guardian Transfers", "tier": 1, "rumour_only": True,
     "url": "https://www.theguardian.com/football/transfer-window/rss"},
    {"id": "sky", "name": "Sky Sports", "tier": 1, "rumour_only": False,
     "url": "https://www.skysports.com/rss/12040"},
    {"id": "bbc", "name": "BBC Sport", "tier": 1, "rumour_only": False,
     "url": "https://feeds.bbci.co.uk/sport/football/rss.xml"},
    {"id": "guardian", "name": "Guardian", "tier": 1, "rumour_only": False,
     "url": "https://www.theguardian.com/football/rss"},
    {"id": "90min", "name": "90min", "tier": 2, "rumour_only": False,
     "url": "https://www.90min.com/posts.rss"},
]
FEED_BY_ID = {f["id"]: f for f in FEEDS}

# Words that mark a story as transfer business rather than match reporting.
_TRANSFER_WORDS = re.compile(
    r"\b(transfer|sign(?:ing|s|ed)?|bid|deal|move|loan|target(?:s|ing|ed)?|"
    r"swoop|links?|linked|wants?|agree(?:d|ment)?|medical|fee|clause|"
    r"contract|extension|release|swap|approach|offer|talks|interest(?:ed)?|"
    r"joins?|exit|departure|replace|snap up|eye(?:ing|s)?|pursue|chase)\b",
    re.I,
)


# Evergreen promos that sit in news feeds forever and are not stories.
_JUNK = re.compile(
    r"^(sign up for|subscribe|newsletter|get the|download the|"
    r"live[:,]? |follow live|as it happened|clockwatch|"
    r"quiz[:,]|the fiver|weekly wrap)", re.I)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = (text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " "))
    return " ".join(text.split())


def _when(node: ET.Element) -> str | None:
    for tag in ("pubDate", "published", "updated",
                "{http://purl.org/dc/elements/1.1/}date"):
        el = node.find(tag)
        if el is not None and el.text:
            raw = el.text.strip()
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                pass
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")) \
                               .astimezone(timezone.utc).isoformat()
            except ValueError:
                continue
    return None


def _parse(xml: str, feed: dict) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry")

    out: list[dict] = []
    for node in items:
        def text(*tags):
            for t in tags:
                el = node.find(t)
                if el is not None and (el.text or "").strip():
                    return el.text.strip()
            return ""

        title = _strip_html(text("title", "{http://www.w3.org/2005/Atom}title"))
        if not title:
            continue
        link = text("link", "guid")
        if not link:
            el = node.find("{http://www.w3.org/2005/Atom}link")
            link = el.get("href", "") if el is not None else ""
        summary = _strip_html(text(
            "description", "{http://www.w3.org/2005/Atom}summary",
            "{http://purl.org/rss/1.0/modules/content/}encoded"))

        blob = f"{title} {summary}"
        if _JUNK.search(title):
            continue
        if not feed["rumour_only"] and not _TRANSFER_WORDS.search(blob):
            continue

        image = None
        for tag in ("{http://search.yahoo.com/mrss/}thumbnail",
                    "{http://search.yahoo.com/mrss/}content", "enclosure"):
            el = node.find(tag)
            if el is not None and el.get("url"):
                image = el.get("url")
                break

        out.append({
            "id": f"{feed['id']}:{abs(hash(link or title)) & 0xFFFFFFFF:08x}",
            "title": title,
            "summary": summary[:320],
            "url": link,
            "published": _when(node),
            "source": feed["name"],
            "source_id": feed["id"],
            "tier": feed["tier"],
            "desk": feed["rumour_only"],   # a dedicated transfer desk, not general news
            "image": image,
            "clubs": _clubs_mentioned(blob),
        })
    return out


def _clubs_mentioned(text: str) -> list[dict]:
    """Tag a story with any big-five/ISL club it names.

    Exact registry names only - fuzzy matching on prose would tag half the
    league every time someone writes "united".
    """
    found: dict[str, dict] = {}
    low = text.lower()
    for club in CLUBS:
        for label in (club["name"], club["short"]):
            if len(label) < 5:
                continue
            if label.lower() in low:
                found[club["id"]] = {"id": club["id"], "short": club["short"],
                                     "colour": club["colour"], "league": club["league"]}
                break
    return list(found.values())[:4]


class FeedError(RuntimeError):
    pass


# Validators from the last fetch, so we can revalidate instead of re-download.
# The Guardian returns 304 with an empty body, which costs the publisher (and
# us) essentially nothing.
_VALIDATORS: dict[str, dict[str, str]] = {}
_LAST_BODY: dict[str, str] = {}


async def _fetch_feed(feed: dict) -> list[dict]:
    async def fetch():
        headers = dict(_UA)
        prev = _VALIDATORS.get(feed["id"]) or {}
        if prev.get("etag"):
            headers["If-None-Match"] = prev["etag"]
        elif prev.get("last_modified"):
            headers["If-Modified-Since"] = prev["last_modified"]

        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0),
                                     follow_redirects=True) as c:
            r = await c.get(feed["url"], headers=headers)

        # Unchanged since last time: reuse what we already parsed.
        if r.status_code == 304 and _LAST_BODY.get(feed["id"]):
            return _LAST_BODY[feed["id"]]

        # Raise rather than return empty: the cache serves the last good copy
        # on failure, so a blip does not blank a source.
        if r.status_code == 429:
            raise FeedError(f"{feed['id']} rate-limited us (429)")
        if r.status_code != 200:
            raise FeedError(f"{feed['id']} returned HTTP {r.status_code}")
        if "<" not in r.text[:200]:
            raise FeedError(f"{feed['id']} did not return XML")

        _VALIDATORS[feed["id"]] = {
            "etag": r.headers.get("etag", ""),
            "last_modified": r.headers.get("last-modified", ""),
        }
        _LAST_BODY[feed["id"]] = r.text
        return r.text

    try:
        xml = await cache.get_or_set(f"news:{feed['id']}", settings.ttl_rumours, fetch)
    except Exception:
        # Last good copy beats an empty source.
        xml = _LAST_BODY.get(feed["id"], "")
    return _parse(xml, feed) if xml else []


def _dedupe(rows: list[dict]) -> list[dict]:
    """Round-ups repeat each other; keep the highest-trust telling of a story."""
    seen: dict[str, dict] = {}
    for row in rows:
        words = re.findall(r"[a-z]{4,}", row["title"].lower())
        key = " ".join(sorted(words)[:6]) or row["title"].lower()
        prev = seen.get(key)
        if prev is None or (row["tier"], row["published"] or "") < \
                           (prev["tier"], prev["published"] or ""):
            seen[key] = row
    return list(seen.values())


async def rumours(source: str | None = None, club: str | None = None,
                  limit: int = 80) -> dict:
    import asyncio

    feeds = [f for f in FEEDS if not source or f["id"] == source]
    results = await asyncio.gather(*(_fetch_feed(f) for f in feeds),
                                   return_exceptions=True)
    rows: list[dict] = []
    live_sources: list[str] = []
    for feed, res in zip(feeds, results):
        if isinstance(res, Exception) or not res:
            continue
        live_sources.append(feed["id"])
        rows.extend(res)

    rows = _dedupe(rows)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    rows = [r for r in rows if not r["published"] or r["published"] >= cutoff]
    if club:
        rows = [r for r in rows if any(c["id"] == club for c in r["clubs"])]
    rows.sort(key=lambda r: r["published"] or "", reverse=True)

    return {
        "rumours": rows[:limit],
        "total": len(rows),
        "sources": [{"id": f["id"], "name": f["name"], "tier": f["tier"],
                     "live": f["id"] in live_sources} for f in FEEDS],
        "fetched": datetime.now(timezone.utc).isoformat(),
    }
