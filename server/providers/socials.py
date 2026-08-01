"""Football social feeds, read through Nitter.

X/Twitter's own API is paid and heavily rate limited, and the public
syndication endpoint answers 429 almost immediately. Nitter mirrors a public
timeline as RSS with no key and no quota, which is the only keyless route
that actually returns current posts - verified against 14 of 15 accounts.

Nitter instances come and go, so `TF_NITTER_HOSTS` takes a comma separated
list and each account falls through them in order. If every host is down the
tab degrades to empty rather than erroring; nothing else in the app depends
on it.
"""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..cache import cache
from ..config import settings
from ..data.clubs import CLUBS

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# tier 1 = breaks stories first-hand, tier 2 = reliable but mostly aggregation
ACCOUNTS: list[dict] = [
    {"handle": "FabrizioRomano",  "name": "Fabrizio Romano",  "tier": 1, "beat": "transfers"},
    {"handle": "David_Ornstein",  "name": "David Ornstein",   "tier": 1, "beat": "transfers"},
    {"handle": "MatteMoretto",    "name": "Matteo Moretto",   "tier": 1, "beat": "transfers"},
    {"handle": "Santi_J_FM",      "name": "Santi Aouna",      "tier": 1, "beat": "transfers"},
    {"handle": "gerardromero",    "name": "Gerard Romero",    "tier": 1, "beat": "transfers"},
    {"handle": "GuillemBalague",  "name": "Guillem Balague",  "tier": 1, "beat": "transfers"},
    {"handle": "JamesOlley",      "name": "James Olley",      "tier": 1, "beat": "news"},
    {"handle": "LaurensJulien",   "name": "Julien Laurens",   "tier": 1, "beat": "news"},
    {"handle": "TheAthleticFC",   "name": "The Athletic FC",  "tier": 1, "beat": "news"},
    {"handle": "SkySportsNews",   "name": "Sky Sports News",  "tier": 1, "beat": "news"},
    {"handle": "BBCSport",        "name": "BBC Sport",        "tier": 1, "beat": "news"},
    {"handle": "OptaJoe",         "name": "OptaJoe",          "tier": 2, "beat": "stats"},
    {"handle": "ESPNFC",          "name": "ESPN FC",          "tier": 2, "beat": "news"},
    {"handle": "brfootball",      "name": "B/R Football",     "tier": 2, "beat": "news"},
]
ACCOUNT_BY_HANDLE = {a["handle"].lower(): a for a in ACCOUNTS}

_RT = re.compile(r"^RT by @[\w]+:\s*", re.I)


def _hosts() -> list[str]:
    return [h.strip().rstrip("/") for h in settings.nitter_hosts.split(",") if h.strip()]


def _when(text: str | None) -> str | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text.strip()).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = (text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " "))
    return " ".join(text.split())


def _clubs_mentioned(text: str) -> list[dict]:
    found: dict[str, dict] = {}
    low = text.lower()
    for club in CLUBS:
        for label in (club["name"], club["short"]):
            if len(label) < 5:
                continue
            if label.lower() in low:
                found[club["id"]] = {"id": club["id"], "short": club["short"],
                                     "colour": club["colour"]}
                break
    return list(found.values())[:4]


def _parse(xml: str, account: dict) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    out = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title") or "")
        if not title:
            continue
        retweet = bool(_RT.match(title))
        title = _RT.sub("", title)
        link = (item.findtext("link") or "").strip()
        # Point links at x.com - a Nitter permalink may outlive its instance.
        link = re.sub(r"^https?://[^/]+/", "https://x.com/", link)
        out.append({
            "id": f"{account['handle']}:{abs(hash(link or title)) & 0xFFFFFFFF:08x}",
            "text": title,
            "url": link,
            "published": _when(item.findtext("pubDate")),
            "handle": account["handle"],
            "author": account["name"],
            "tier": account["tier"],
            "beat": account["beat"],
            "retweet": retweet,
            "clubs": _clubs_mentioned(title),
        })
    return out


async def _fetch_account(account: dict) -> list[dict]:
    async def fetch():
        last = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0),
                                     headers=_UA, follow_redirects=True) as c:
            for host in _hosts():
                try:
                    r = await c.get(f"{host}/{account['handle']}/rss")
                except httpx.HTTPError as exc:
                    last = exc
                    continue
                if r.status_code == 200 and "<rss" in r.text[:400]:
                    return r.text
                last = RuntimeError(f"{host} -> HTTP {r.status_code}")
        raise RuntimeError(f"no nitter host served @{account['handle']}: {last}")

    try:
        xml = await cache.get_or_set(f"social:{account['handle']}",
                                     settings.ttl_socials, fetch)
    except Exception:
        return []
    return _parse(xml, account)


async def posts(handle: str | None = None, beat: str | None = None,
                limit: int = 100) -> dict:
    accounts = [a for a in ACCOUNTS
                if (not handle or a["handle"].lower() == handle.lower())
                and (not beat or a["beat"] == beat)]

    results = await asyncio.gather(*(_fetch_account(a) for a in accounts),
                                   return_exceptions=True)
    rows: list[dict] = []
    live: set[str] = set()
    for account, res in zip(accounts, results):
        if isinstance(res, Exception) or not res:
            continue
        live.add(account["handle"])
        rows.extend(res)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    rows = [r for r in rows if not r["published"] or r["published"] >= cutoff]
    rows.sort(key=lambda r: r["published"] or "", reverse=True)

    return {
        "posts": rows[:limit],
        "total": len(rows),
        "accounts": [{"handle": a["handle"], "name": a["name"], "tier": a["tier"],
                      "beat": a["beat"], "live": a["handle"] in live}
                     for a in ACCOUNTS],
        "fetched": datetime.now(timezone.utc).isoformat(),
    }
