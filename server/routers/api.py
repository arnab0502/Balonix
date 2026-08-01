"""JSON API. Everything the frontend needs, and nothing it does not."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from ..cache import cache
from ..config import settings
from ..data.clubs import CLUB_BY_ID, CLUBS, CLUBS_BY_LEAGUE
from ..data.leagues import LEAGUES, LEAGUE_BY_ID
from ..data.tickets import ticket_link
from ..providers import build_provider
from ..providers.composite import TEAM_IDS
from ..providers import apifootball as af
from ..providers import youtube as yt
from ..providers import news
from ..quota import quota

router = APIRouter(prefix="/api")
provider = build_provider()


def _with_logo(club: dict) -> dict:
    """Attach the club's crest so every view can show a real badge."""
    api = TEAM_IDS.get(club["id"])
    return {**club, "logo": api.get("logo") if api else None}


@router.get("/meta")
async def meta():
    lo, hi = af.free_window()
    return {
        "leagues": LEAGUES,
        "clubs": [_with_logo(c) for c in CLUBS],
        "provider": provider.name,
        "live": settings.is_live,
        "quota": quota.snapshot(),
        "real_data_window": {"from": lo.isoformat(), "to": hi.isoformat()},
        "plan": "paid" if settings.unrestricted else "free",
        "capabilities": {
            "live_scores": settings.is_live,
            "calendar": "unrestricted" if settings.unrestricted else "today+/-1",
            "standings": "real" if settings.unrestricted else "simulated",
            "scorers": "real" if settings.unrestricted else "simulated",
            "squads": "real" if settings.unrestricted else "simulated",
            "transfers": "real" if settings.is_live else "simulated",
            "tickets": "real",
        },
    }


@router.get("/home")
async def home():
    """Everything the landing page needs, in one round trip.

    Built so the page is never empty: out of season there are no live games
    and often none today either, so it falls back to the next fixtures on the
    calendar and leans on transfers, rumours and the podcast.
    """
    import asyncio
    from datetime import datetime, timezone

    today = date.today()

    async def safe(coro, default):
        try:
            return await coro
        except Exception:
            return default

    live_data, transfers_data, rumour_data, video_data = await asyncio.gather(
        safe(provider.live("big5") if provider.name == "composite" else provider.live(), {}),
        safe(provider.transfers(None, 8, window="season", group="flat")
             if provider.name == "composite" else provider.transfers(None, 8), {}),
        safe(news.rumours(limit=40), {}),
        safe(yt.videos(settings.youtube_channel) if settings.youtube_channel else _none(), {}),
    )

    live = [m for m in (live_data.get("matches") or [])]

    # Walk forward until we find a day with fixtures, so "next up" is real.
    upcoming: list = []
    upcoming_day = None
    for offset in range(0, 21):
        day = (today + timedelta(days=offset)).isoformat()
        got = await safe(provider.fixtures_by_date(day), {})
        rows = [m for m in (got.get("matches") or [])
                if (m.get("status") or {}).get("type") == "scheduled"]
        if rows:
            upcoming, upcoming_day = rows, day
            break

    results = []
    for offset in range(1, 8):
        day = (today - timedelta(days=offset)).isoformat()
        got = await safe(provider.fixtures_by_date(day), {})
        rows = [m for m in (got.get("matches") or [])
                if (m.get("status") or {}).get("type") == "finished"]
        if rows:
            results = rows[:5]
            break

    leaders = []
    for lg in LEAGUES:
        table = await safe(provider.standings(lg["id"]), {})
        rows = table.get("table") or []
        if rows:
            leaders.append({"league": lg, "season": table.get("season"),
                            "top": rows[:3]})

    return {
        "live": live[:6],
        "live_count": len(live),
        "elsewhere_count": len(live_data.get("elsewhere") or []),
        "upcoming": upcoming[:6],
        "upcoming_day": upcoming_day,
        "results": results,
        "leaders": leaders,
        "transfers": (transfers_data.get("transfers") or [])[:6],
        "transfer_total": transfers_data.get("total_matching") or 0,
        "transfer_window": transfers_data.get("window_label"),
        # Lead with the dedicated transfer desks; general football news only
        # fills the gaps.
        "rumours": sorted(
            (rumour_data.get("rumours") or []),
            key=lambda r: (not r.get("desk"), r.get("tier", 9),
                           -(len(r.get("clubs") or []))),
        )[:5],
        "episodes": (video_data.get("videos") or [])[:3],
        "channel": video_data.get("channel"),
        "counts": {
            "leagues": len(LEAGUES),
            "clubs": len(CLUBS),
            "episodes": video_data.get("count") or 0,
        },
        "generated": datetime.now(timezone.utc).isoformat(),
    }


async def _none():
    return {}


@router.get("/matches")
async def matches(day: str = Query(default_factory=lambda: date.today().isoformat())):
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "day must be YYYY-MM-DD")
    return await provider.fixtures_by_date(day)


@router.get("/live")
async def live(scope: str = Query("big5", pattern="^(big5|all)$")):
    result = await provider.live(scope) if provider.name == "composite" else await provider.live()
    if isinstance(result, list):
        result = {"matches": result, "source": provider.name, "simulated": True}
    result.setdefault("poll_seconds", quota.suggested_poll_seconds())
    return result


@router.get("/match/{match_id}")
async def match(match_id: str):
    data = await provider.match(match_id)
    if not data:
        raise HTTPException(404, "match not found")
    return data


@router.get("/league/{league_id}/standings")
async def standings(league_id: str):
    if league_id not in LEAGUE_BY_ID:
        raise HTTPException(404, "unknown league")
    data = await provider.standings(league_id)
    data["league"] = LEAGUE_BY_ID[league_id]
    return data


@router.get("/league/{league_id}/scorers")
async def scorers(league_id: str):
    if league_id not in LEAGUE_BY_ID:
        raise HTTPException(404, "unknown league")
    data = await provider.scorers(league_id)
    data["league"] = LEAGUE_BY_ID[league_id]
    return data


@router.get("/league/{league_id}/honours")
async def honours(league_id: str, count: int = Query(8, ge=1, le=15)):
    if league_id not in LEAGUE_BY_ID:
        raise HTTPException(404, "unknown league")
    if not hasattr(provider, "honours"):
        return {"honours": [], "source": "unavailable"}
    data = await provider.honours(league_id, count)
    data["league"] = LEAGUE_BY_ID[league_id]
    return data


@router.get("/league/{league_id}/fixtures")
async def league_fixtures(league_id: str,
                          when: str = Query("next", pattern="^(next|last)$"),
                          count: int = Query(20, ge=1, le=50)):
    if league_id not in LEAGUE_BY_ID:
        raise HTTPException(404, "unknown league")
    if not hasattr(provider, "league_fixtures"):
        return {"matches": [], "source": "unavailable"}
    data = await provider.league_fixtures(league_id, when, count)
    data["league"] = LEAGUE_BY_ID[league_id]
    return data


@router.get("/transfers")
async def transfers(
    league: str | None = None,
    limit: int = Query(250, ge=1, le=1000),
    window: str = Query("season", pattern="^(season|year|all)$"),
    q: str = "",
    group: str = Query("club", pattern="^(club|flat)$"),
):
    if league and league not in LEAGUE_BY_ID:
        raise HTTPException(404, "unknown league")
    if provider.name == "composite":
        return await provider.transfers(league, limit, window=window,
                                        query=q, group=group)
    rows = await provider.transfers(league, limit)
    return {"transfers": rows, "clubs": [], "source": "simulated", "simulated": True}


@router.post("/transfers/sync")
async def transfers_sync(limit: int = Query(None, ge=1, le=500)):
    if not hasattr(provider, "sweep_transfers"):
        raise HTTPException(400, "live transfers unavailable in mock mode")
    return await provider.sweep_transfers(limit)


@router.post("/squads/sync")
async def squads_sync(limit: int = Query(None, ge=1, le=500)):
    """Pull real squads. This is what makes player search work."""
    if not hasattr(provider, "sweep_squads"):
        raise HTTPException(400, "squads unavailable in mock mode")
    return await provider.sweep_squads(limit)


@router.get("/team/{team_id}")
async def team(team_id: str):
    data = await provider.team(team_id)
    if not data:
        raise HTTPException(404, "unknown team")
    return data


@router.get("/team/{team_id}/lineup")
async def team_lineup(team_id: str):
    """Probable XI after the window - derived, clearly not a teamsheet."""
    if team_id not in CLUB_BY_ID:
        raise HTTPException(404, "unknown club")
    if not hasattr(provider, "probable_xi"):
        return {"available": False, "reason": "needs a live provider"}
    return await provider.probable_xi(team_id)


@router.get("/player/{player_id}")
async def player(player_id: str):
    if not hasattr(provider, "player"):
        raise HTTPException(404, "player pages need a live provider")
    data = await provider.player(player_id)
    if not data:
        raise HTTPException(404, "player not found")
    return data


@router.get("/rumours")
async def rumours(source: str | None = None, club: str | None = None,
                  limit: int = Query(80, ge=1, le=200)):
    """Transfer talk aggregated from football news desks (RSS, no API key)."""
    if source and source not in news.FEED_BY_ID:
        raise HTTPException(404, "unknown source")
    return await news.rumours(source=source, club=club, limit=limit)


@router.get("/videos")
async def videos(full: bool = False):
    """Podcast episodes from the configured YouTube channel."""
    if not settings.youtube_channel:
        return {"configured": False, "videos": [], "channel": None,
                "note": "Set TF_YOUTUBE_CHANNEL in .env to your channel "
                        "handle (e.g. @candidfootball) and restart."}
    try:
        data = await yt.videos(settings.youtube_channel, full=full)
    except yt.YouTubeError as exc:
        raise HTTPException(502, str(exc))
    data["configured"] = True
    data["has_api_key"] = bool(settings.youtube_api_key)
    if settings.youtube_title:
        data["channel"]["title"] = settings.youtube_title
    return data


@router.get("/search")
async def search(q: str = ""):
    return await provider.search(q)


@router.get("/tickets/{club_id}")
async def tickets(club_id: str):
    club = CLUB_BY_ID.get(club_id)
    if not club:
        raise HTTPException(404, "unknown club")
    return {
        "club": _with_logo(club),
        "ticket": ticket_link(club["name"], club["league"], venue=club["stadium"]),
    }


@router.get("/tickets")
async def all_tickets(league: str | None = None):
    clubs = CLUBS_BY_LEAGUE.get(league, CLUBS) if league else CLUBS
    return {
        "clubs": [
            {"id": c["id"], "name": c["name"], "short": c["short"],
             "tla": c["tla"], "league": c["league"], "stadium": c["stadium"],
             "colour": c["colour"], "ticket_url": c["ticket_url"],
             "logo": (TEAM_IDS.get(c["id"]) or {}).get("logo")}
            for c in clubs
        ]
    }


@router.get("/health")
async def health():
    return {
        "ok": True,
        "provider": provider.name,
        "live": settings.is_live,
        "quota": quota.snapshot(),
        "cache": cache.stats(),
    }
