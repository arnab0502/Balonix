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
from ..providers import apifootball as af
from ..providers import youtube as yt
from ..quota import quota

router = APIRouter(prefix="/api")
provider = build_provider()


@router.get("/meta")
async def meta():
    lo, hi = af.free_window()
    return {
        "leagues": LEAGUES,
        "clubs": CLUBS,
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


@router.get("/player/{player_id}")
async def player(player_id: str):
    if not hasattr(provider, "player"):
        raise HTTPException(404, "player pages need a live provider")
    data = await provider.player(player_id)
    if not data:
        raise HTTPException(404, "player not found")
    return data


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
        "club": club,
        "ticket": ticket_link(club["name"], club["league"], venue=club["stadium"]),
    }


@router.get("/tickets")
async def all_tickets(league: str | None = None):
    clubs = CLUBS_BY_LEAGUE.get(league, CLUBS) if league else CLUBS
    return {
        "clubs": [
            {"id": c["id"], "name": c["name"], "short": c["short"],
             "league": c["league"], "stadium": c["stadium"], "colour": c["colour"],
             "ticket_url": c["ticket_url"]}
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
