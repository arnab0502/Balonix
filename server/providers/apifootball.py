"""API-Football (v3) adapter.

Verified capabilities of the *Free* plan against this account:

  /fixtures?live=all      OK   - all in-play matches, events included inline
  /fixtures?date=D        OK   - but only for today +/- 1 day
  /fixtures?season=2026   BLOCKED - free plans are capped at seasons 2022-2024
  /standings?season=2026  BLOCKED - same season cap
  /transfers?team=X       OK   - not season-gated, 274 rows for a big club
  /players, /lineups      partial - season-gated like fixtures

So this adapter serves live scores, the three-day fixture window and transfers.
Standings / scorers / the wider calendar come from another source; see
`composite.py`, which stitches the sources together and falls back to the
simulated season for anything nobody can supply.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import httpx

from ..cache import cache
from ..config import settings
from ..data.clubs import CLUB_BY_ID, CLUBS, resolve as resolve_club, resolve_exact
from ..data.leagues import CONTINENTAL, LEAGUE_BY_API_ID, LEAGUE_BY_ID, LEAGUES
from ..data.tickets import ticket_link
from ..quota import QuotaExceeded, quota

# Every competition we cover, keyed by API-Football league id.
COVERED_API_IDS = {lg["api_id"]: lg["id"] for lg in LEAGUES}

_LIVE_STATUSES = {"1H", "2H", "HT", "ET", "BT", "P", "LIVE", "INT"}
_DONE_STATUSES = {"FT", "AET", "PEN", "WO", "AWD"}
_OFF_STATUSES = {"PST", "CANC", "ABD", "SUSP", "TBD"}


class ApiFootballError(RuntimeError):
    pass


class RateLimited(ApiFootballError):
    pass


class _MinuteLimiter:
    """Spaces calls out to respect the plan's per-minute ceiling.

    The free plan rejects bursts with a 429 that still costs a round trip but
    returns no data, so pacing is cheaper than retrying.
    """

    def __init__(self, per_minute: int) -> None:
        self.interval = 60.0 / max(1, per_minute)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            gap = loop.time() - self._last
            if gap < self.interval:
                await asyncio.sleep(self.interval - gap)
            self._last = asyncio.get_running_loop().time()


class ApiFootballClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._limiter = _MinuteLimiter(settings.rate_limit_per_min)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"https://{settings.api_host}",
                headers={"x-apisports-key": settings.api_key},
                timeout=httpx.Timeout(45.0, connect=15.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, path: str, bucket: str, **params) -> list[dict]:
        """One budgeted, rate-paced upstream call.

        Raises QuotaExceeded before spending anything. A rate-limit rejection
        is refunded and retried, since it never delivered data.
        """
        quota.spend(bucket)  # raises if the bucket is dry
        client = await self._http()

        for attempt in range(3):
            await self._limiter.wait()
            try:
                resp = await client.get(path, params=params)
            except httpx.HTTPError as exc:
                quota.refund(bucket)
                raise ApiFootballError(f"network error: {exc}") from exc

            if resp.status_code == 429:
                if attempt == 2:
                    quota.refund(bucket)
                    raise RateLimited("per-minute limit hit after 3 attempts")
                await asyncio.sleep(self._limiter.interval * (attempt + 2))
                continue

            if resp.status_code >= 400:
                quota.refund(bucket)
                raise ApiFootballError(f"HTTP {resp.status_code}")

            payload = resp.json()
            errors = payload.get("errors")
            if errors and isinstance(errors, dict):
                if "rateLimit" in errors:
                    if attempt == 2:
                        quota.refund(bucket)
                        raise RateLimited(errors["rateLimit"])
                    await asyncio.sleep(self._limiter.interval * (attempt + 2))
                    continue
                # A plan/param error is a real answer: the budget was spent.
                raise ApiFootballError("; ".join(f"{k}: {v}" for k, v in errors.items()))
            return payload.get("response") or []
        quota.refund(bucket)
        raise RateLimited("exhausted retries")


client = ApiFootballClient()


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------
def _status(raw: dict) -> dict:
    short = (raw.get("short") or "NS").upper()
    elapsed = raw.get("elapsed")
    extra = raw.get("extra")
    if short in _DONE_STATUSES:
        return {"type": "finished", "minute": 90,
                "label": "FT" if short == "FT" else short}
    if short in _OFF_STATUSES:
        return {"type": "postponed", "minute": None, "label": raw.get("long") or short}
    if short == "HT":
        return {"type": "live", "minute": 45, "label": "HT"}
    if short in _LIVE_STATUSES:
        minute = elapsed or 0
        label = f"{minute}+{extra}'" if extra else f"{minute}'"
        return {"type": "live", "minute": minute, "label": label}
    return {"type": "scheduled", "minute": None, "label": "NS"}


def _side(team: dict, goals, league_id: str | None = None) -> dict:
    # Only trust the club registry inside the big five. Outside it, names like
    # "Athletic Club MG U20" or Bhutan's "Premier League" sides would otherwise
    # fuzzy-match onto Athletic Bilbao and inherit the wrong ticket link.
    if league_id in CONTINENTAL:
        # Champions League sides come from every domestic league, so an exact
        # registry hit from any of them is correct here.
        club = resolve_exact(team.get("name"))
    elif league_id:
        club = resolve_club(team.get("name"))
        if club and club["league"] != league_id:
            club = None
    else:
        # Cups and Europe have no big-five league id, but an exact registry hit
        # is still trustworthy - unlike the fuzzy match, which once mapped
        # "Athletic Club MG U20" onto Athletic Bilbao.
        club = resolve_exact(team.get("name"))
    return {
        "id": club["id"] if club else f"api-{team.get('id')}",
        "api_id": team.get("id"),
        "name": team.get("name") or "Unknown",
        "short": club["short"] if club else (team.get("name") or "Unknown"),
        "tla": club["tla"] if club else (team.get("name") or "???")[:3].upper(),
        "colour": club["colour"] if club else "#7a8699",
        "logo": team.get("logo"),
        "score": goals if goals is not None else 0,
    }


def _event(raw: dict, home_api_id: int | None) -> dict:
    team = raw.get("team") or {}
    kind = (raw.get("type") or "").lower()
    time_ = raw.get("time") or {}
    minute = time_.get("elapsed") or 0
    if time_.get("extra"):
        minute += time_["extra"]
    return {
        "minute": minute,
        "type": {"goal": "goal", "card": "card", "subst": "subst"}.get(kind, kind or "other"),
        "side": "home" if team.get("id") == home_api_id else "away",
        "team": team.get("name"),
        "player": (raw.get("player") or {}).get("name"),
        "player_id": (raw.get("player") or {}).get("id"),
        "assist": (raw.get("assist") or {}).get("name"),
        "detail": raw.get("detail"),
    }


def _ticket_for(home_name: str | None, league_id: str | None, venue: str | None):
    """Box-office link for a fixture, or None when we cannot be certain."""
    if league_id and league_id not in CONTINENTAL:
        return ticket_link(home_name, league_id, venue=venue)
    club = resolve_exact(home_name)
    if club:
        return ticket_link(club["name"], club["league"], venue=venue)
    if league_id:                       # continental, unknown club
        return ticket_link(home_name, league_id, venue=venue)
    return None


def _match(raw: dict, *, detail: bool = False) -> dict:
    fx = raw.get("fixture") or {}
    lg = raw.get("league") or {}
    teams = raw.get("teams") or {}
    goals = raw.get("goals") or {}
    home_raw, away_raw = teams.get("home") or {}, teams.get("away") or {}

    league_id = COVERED_API_IDS.get(lg.get("id"))
    meta = LEAGUE_BY_ID.get(league_id or "")
    venue = (fx.get("venue") or {}).get("name")

    match = {
        "id": str(fx.get("id")),
        "league": league_id or f"api-{lg.get('id')}",
        "league_name": lg.get("name") or "",
        "league_country": lg.get("country"),
        "league_logo": lg.get("logo"),
        "league_accent": meta["accent"] if meta else "#7a8699",
        "round": lg.get("round") or "",
        "kickoff": fx.get("date"),
        "status": _status(fx.get("status") or {}),
        "home": _side(home_raw, goals.get("home"), league_id),
        "away": _side(away_raw, goals.get("away"), league_id),
        "venue": venue,
        "referee": fx.get("referee"),
        "tickets": _ticket_for(home_raw.get("name"), league_id, venue),
        "source": "apifootball",
    }

    events = raw.get("events") or []
    if events:
        match["events"] = [_event(e, home_raw.get("id")) for e in events]

    if detail:
        match.setdefault("events", [])
        match["stats"] = _stats(raw.get("statistics") or [], home_raw.get("id"))
        match["lineups"] = _lineups(raw.get("lineups") or [], home_raw.get("id"))
        score = raw.get("score") or {}
        match["periods"] = {
            "halftime": score.get("halftime"),
            "fulltime": score.get("fulltime"),
        }
    return match


_STAT_KEYS = {
    "Ball Possession": "possession",
    "Total Shots": "shots",
    "Shots on Goal": "shots_on_target",
    "Corner Kicks": "corners",
    "Fouls": "fouls",
    "Offsides": "offsides",
    "expected_goals": "xg",
    "Passes %": "pass_accuracy",
}


def _stats(raw: list[dict], home_api_id: int | None) -> dict | None:
    if not raw:
        return None
    out: dict[str, list] = {}
    for block in raw:
        is_home = (block.get("team") or {}).get("id") == home_api_id
        idx = 0 if is_home else 1
        for item in block.get("statistics") or []:
            key = _STAT_KEYS.get(item.get("type") or "")
            if not key:
                continue
            value = item.get("value")
            if isinstance(value, str) and value.endswith("%"):
                value = value[:-1]
            try:
                value = float(value) if value is not None else 0
            except (TypeError, ValueError):
                value = 0
            slot = out.setdefault(key, [0, 0])
            slot[idx] = int(value) if float(value).is_integer() else round(value, 2)
    return out or None


def _lineups(raw: list[dict], home_api_id: int | None) -> dict | None:
    if not raw:
        return None
    out: dict[str, dict] = {}
    for block in raw:
        team = block.get("team") or {}
        key = "home" if team.get("id") == home_api_id else "away"
        club = resolve_club(team.get("name"))

        def players(section):
            return [
                {
                    "id": (p.get("player") or {}).get("id"),
                    "name": (p.get("player") or {}).get("name"),
                    "number": (p.get("player") or {}).get("number"),
                    "position": (p.get("player") or {}).get("pos"),
                    "grid": (p.get("player") or {}).get("grid"),
                }
                for p in section or []
            ]

        out[key] = {
            "team": club["short"] if club else team.get("name"),
            "colour": club["colour"] if club else (team.get("colors") or {}).get("player", {}).get("primary", "#7a8699"),
            "formation": block.get("formation"),
            "coach": (block.get("coach") or {}).get("name"),
            "starters": players(block.get("startXI")),
            "bench": players(block.get("substitutes")),
        }
    return out or None


# --------------------------------------------------------------------------
# Public calls (all cached + budgeted)
# --------------------------------------------------------------------------
async def live_matches(covered_only: bool = True) -> list[dict]:
    async def fetch():
        rows = await client.get("/fixtures", "live", live="all")
        return rows

    rows = await cache.get_or_set("af:live", settings.ttl_live, fetch)
    matches = [_match(r) for r in rows]
    if covered_only:
        matches = [m for m in matches if m["league"] in COVERED_API_IDS.values()]
    matches.sort(key=lambda m: (m["league"], m["kickoff"] or ""))
    return matches


async def fixtures_on(day: str, covered_only: bool = True) -> list[dict]:
    """Only reliable for today +/- 1 day on the free plan."""
    async def fetch():
        return await client.get("/fixtures", "core", date=day, timezone="UTC")

    rows = await cache.get_or_set(f"af:fixtures:{day}", settings.ttl_fixtures, fetch)
    matches = [_match(r) for r in rows]
    if covered_only:
        matches = [m for m in matches if m["league"] in COVERED_API_IDS.values()]
    matches.sort(key=lambda m: (m["kickoff"] or "", m["league"]))
    return matches


def free_window() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=1), today + timedelta(days=1)


def in_free_window(day: str) -> bool:
    """Paid plans have no date gate; free plans only serve today +/- 1 day."""
    if settings.unrestricted:
        return True
    lo, hi = free_window()
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return False
    return lo <= d <= hi


# --------------------------------------------------------------------------
# Standings / scorers  (paid plans only)
# --------------------------------------------------------------------------
def _standing_row(raw: dict) -> dict:
    team = raw.get("team") or {}
    club = resolve_club(team.get("name"))
    allg = raw.get("all") or {}
    goals = allg.get("goals") or {}
    return {
        "rank": raw.get("rank"),
        "team": {
            "id": club["id"] if club else f"api-{team.get('id')}",
            "api_id": team.get("id"),
            "name": team.get("name"),
            "short": club["short"] if club else team.get("name"),
            "tla": club["tla"] if club else (team.get("name") or "???")[:3].upper(),
            "colour": club["colour"] if club else "#7a8699",
            "logo": team.get("logo"),
        },
        "played": allg.get("played") or 0,
        "win": allg.get("win") or 0,
        "draw": allg.get("draw") or 0,
        "loss": allg.get("lose") or 0,
        "gf": goals.get("for") or 0,
        "ga": goals.get("against") or 0,
        "gd": raw.get("goalsDiff") or 0,
        "points": raw.get("points") or 0,
        "form": (raw.get("form") or "")[-5:],
        "description": raw.get("description"),
    }


async def standings(league_api_id: int, season: int) -> list[dict]:
    async def fetch():
        return await client.get("/standings", "core", league=league_api_id, season=season)

    rows = await cache.get_or_set(
        f"af:standings:{league_api_id}:{season}", settings.ttl_standings, fetch
    )
    if not rows:
        return []
    groups = ((rows[0].get("league") or {}).get("standings")) or []
    table: list[dict] = []
    for group in groups:
        table.extend(_standing_row(r) for r in group)
    table.sort(key=lambda r: r["rank"] or 999)
    return table


async def topscorers(league_api_id: int, season: int) -> list[dict]:
    async def fetch():
        return await client.get("/players/topscorers", "core",
                                league=league_api_id, season=season)

    rows = await cache.get_or_set(
        f"af:scorers:{league_api_id}:{season}", settings.ttl_standings, fetch
    )
    out: list[dict] = []
    for i, entry in enumerate(rows, 1):
        p = entry.get("player") or {}
        stats = (entry.get("statistics") or [{}])[0]
        team = stats.get("team") or {}
        goals = stats.get("goals") or {}
        club = resolve_club(team.get("name"))
        out.append({
            "rank": i,
            "player": p.get("name"),
            "player_id": p.get("id"),
            "photo": p.get("photo"),
            "team": club["short"] if club else team.get("name"),
            "team_id": club["id"] if club else None,
            "colour": club["colour"] if club else "#7a8699",
            "logo": team.get("logo"),
            "goals": goals.get("total") or 0,
            "assists": goals.get("assists") or 0,
            "penalties": (stats.get("penalty") or {}).get("scored") or 0,
            "appearances": (stats.get("games") or {}).get("appearences") or 0,
            "minutes": (stats.get("games") or {}).get("minutes") or 0,
        })
    return out


# --------------------------------------------------------------------------
# Squads  (backs real player search)
# --------------------------------------------------------------------------
_POS_SHORT = {"Goalkeeper": "GK", "Defender": "DF", "Midfielder": "MF", "Attacker": "FW"}


async def search_players(term: str) -> list[dict]:
    """Global player lookup.

    `/players/squads` is incomplete - loanees and late window signings are
    routinely missing (Rashford is at Barcelona but absent from their squad
    payload), so squad-only search has permanent holes. This endpoint searches
    every player API-Football knows about.
    """
    term = term.strip()
    if len(term) < 4:  # upstream rejects shorter search terms
        return []

    async def fetch():
        return await client.get("/players/profiles", "core", search=term)

    rows = await cache.get_or_set(f"af:psearch:{term.lower()}", 86400, fetch)
    out = []
    for r in rows:
        p = r.get("player") or {}
        if not p.get("id"):
            continue
        out.append({
            "id": p["id"],
            "name": p.get("name"),
            "firstname": p.get("firstname"),
            "lastname": p.get("lastname"),
            "age": p.get("age"),
            "nationality": p.get("nationality"),
            "photo": p.get("photo"),
            "number": p.get("number"),
            "position": _POS_SHORT.get(p.get("position"), p.get("position")),
            "position_long": p.get("position"),
        })
    return out


def _num(v):
    """API-Football sends nulls all over the per-player stats."""
    return v if isinstance(v, (int, float)) else None


def _match_player(entry: dict) -> dict:
    p = entry.get("player") or {}
    s = (entry.get("statistics") or [{}])[0]
    games = s.get("games") or {}
    goals = s.get("goals") or {}
    passes = s.get("passes") or {}
    duels = s.get("duels") or {}
    dribbles = s.get("dribbles") or {}
    tackles = s.get("tackles") or {}
    shots = s.get("shots") or {}
    cards = s.get("cards") or {}
    fouls = s.get("fouls") or {}
    rating = games.get("rating")
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "photo": p.get("photo"),
        "number": games.get("number"),
        "position": games.get("position"),
        "rating": round(float(rating), 1) if rating else None,
        "minutes": _num(games.get("minutes")) or 0,
        "captain": bool(games.get("captain")),
        "substitute": bool(games.get("substitute")),
        "goals": _num(goals.get("total")) or 0,
        "assists": _num(goals.get("assists")) or 0,
        "saves": _num(goals.get("saves")),
        "shots": _num(shots.get("total")),
        "shots_on": _num(shots.get("on")),
        "passes": _num(passes.get("total")),
        "key_passes": _num(passes.get("key")),
        "pass_accuracy": _num(passes.get("accuracy")),
        "duels_won": _num(duels.get("won")),
        "duels_total": _num(duels.get("total")),
        "dribbles": _num(dribbles.get("success")),
        "tackles": _num(tackles.get("total")),
        "interceptions": _num(tackles.get("interceptions")),
        "fouls_committed": _num(fouls.get("committed")),
        "yellow": _num(cards.get("yellow")) or 0,
        "red": _num(cards.get("red")) or 0,
    }


async def fixture_players(fixture_id: str | int, home_api_id: int | None) -> dict | None:
    """Per-player ratings and match stats, split home/away.

    Ratings are present for essentially everyone; the detailed columns
    (duels, dribbles, tackles) are populated for roughly 70% of players.
    """
    async def fetch():
        return await client.get("/fixtures/players", "detail", fixture=fixture_id)

    rows = await cache.get_or_set(f"af:fxplayers:{fixture_id}", 300, fetch)
    if not rows:
        return None
    out: dict[str, list] = {"home": [], "away": []}
    for block in rows:
        side = "home" if (block.get("team") or {}).get("id") == home_api_id else "away"
        out[side] = [_match_player(p) for p in block.get("players") or []]
    for side in out:
        out[side].sort(key=lambda p: (-(p["rating"] or 0), p["substitute"]))
    return out if (out["home"] or out["away"]) else None


async def head_to_head(a_api_id: int, b_api_id: int, count: int = 10) -> list[dict]:
    """Real previous meetings between two clubs, most recent first."""
    async def fetch():
        return await client.get("/fixtures/headtohead", "detail",
                                h2h=f"{a_api_id}-{b_api_id}", last=count)

    rows = await cache.get_or_set(
        f"af:h2h:{min(a_api_id, b_api_id)}-{max(a_api_id, b_api_id)}:{count}",
        settings.ttl_standings, fetch)
    matches = [_match(r) for r in rows]
    matches.sort(key=lambda m: m["kickoff"] or "", reverse=True)
    return matches


async def fixture_injuries(fixture_id: str | int, home_api_id: int | None) -> dict | None:
    """Players unavailable for a fixture, split home/away, with the reason."""
    async def fetch():
        return await client.get("/injuries", "detail", fixture=fixture_id)

    rows = await cache.get_or_set(f"af:injuries:{fixture_id}", 1800, fetch)
    if not rows:
        return None
    out: dict[str, list] = {"home": [], "away": []}
    seen: set[tuple] = set()
    for r in rows:
        p = r.get("player") or {}
        side = "home" if (r.get("team") or {}).get("id") == home_api_id else "away"
        # The endpoint repeats the same player across rows for one fixture.
        key = (side, p.get("id") or p.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out[side].append({
            "id": p.get("id"), "name": p.get("name"), "photo": p.get("photo"),
            "type": p.get("type"), "reason": p.get("reason"),
        })
    return out if (out["home"] or out["away"]) else None


async def team_fixtures(api_team_id: int, when: str = "next", count: int = 8) -> list[dict]:
    """A club's real fixtures across every competition it plays in.

    `when` is "next" or "last". Covers cups and Europe too, not just the
    domestic league, which is what you actually want on a club page.
    """
    param = "next" if when == "next" else "last"
    ttl = 1800 if when == "next" else settings.ttl_fixtures

    async def fetch():
        return await client.get("/fixtures", "core", team=api_team_id,
                                **{param: count}, timezone="UTC")

    rows = await cache.get_or_set(
        f"af:teamfx:{api_team_id}:{param}:{count}", ttl, fetch
    )
    matches = [_match(r) for r in rows]
    matches.sort(key=lambda m: m["kickoff"] or "", reverse=(when == "last"))
    return matches


async def final_result(league_api_id: int, season: int) -> dict | None:
    """Who won a competition in a given season, from its Final fixture."""
    async def fetch():
        return await client.get("/fixtures", "core", league=league_api_id,
                                season=season, round="Final")

    rows = await cache.get_or_set(f"af:final:{league_api_id}:{season}", 2592000, fetch)
    if not rows:
        return None
    raw = rows[0]
    teams, goals, score = raw.get("teams") or {}, raw.get("goals") or {}, raw.get("score") or {}
    home, away = teams.get("home") or {}, teams.get("away") or {}
    pens = score.get("penalty") or {}
    home_won = bool(home.get("winner"))
    winner, runner_up = (home, away) if home_won else (away, home)

    def side(t):
        club = resolve_exact(t.get("name"))
        return {"id": club["id"] if club else None, "name": t.get("name"),
                "short": club["short"] if club else t.get("name"),
                "logo": t.get("logo"),
                "colour": club["colour"] if club else "#7a8699"}

    # Report the score from the winner's side, otherwise "Real Madrid beat
    # Dortmund 0-2" reads backwards whenever the winner was the away team.
    wg, lg_ = ((goals.get("home"), goals.get("away")) if home_won
               else (goals.get("away"), goals.get("home")))
    line = f"{wg or 0}-{lg_ or 0}"
    if pens.get("home") is not None:
        wp, lp = ((pens["home"], pens["away"]) if home_won
                  else (pens["away"], pens["home"]))
        line += f" ({wp}-{lp} pens)"
    return {
        "season": season,
        "season_label": f"{season}/{str(season + 1)[-2:]}",
        "date": (raw.get("fixture") or {}).get("date", "")[:10],
        "venue": ((raw.get("fixture") or {}).get("venue") or {}).get("name"),
        "winner": side(winner),
        "runner_up": side(runner_up),
        "score": line,
        "on_penalties": pens.get("home") is not None,
        "fixture_id": str((raw.get("fixture") or {}).get("id") or ""),
    }


async def honours(league_api_id: int, seasons: list[int]) -> list[dict]:
    """Roll of honour, most recent first. One call per season, cached a month."""
    out = []
    for season in seasons:
        try:
            row = await final_result(league_api_id, season)
        except Exception:
            continue
        if row:
            out.append(row)
    return out


async def team_season_players(api_team_id: int, season: int) -> list[dict]:
    """Every player's season record for a club, including how often they
    actually started. `games.lineups` is the signal a probable XI needs."""
    async def fetch():
        rows, page = [], 1
        while page <= 5:
            batch = await client.get("/players", "core", team=api_team_id,
                                     season=season, page=page)
            rows.extend(batch)
            if len(batch) < 20:
                break
            page += 1
        return rows

    raw = await cache.get_or_set(f"af:teamplayers:{api_team_id}:{season}",
                                 settings.ttl_standings, fetch)
    out: list[dict] = []
    for entry in raw:
        p = entry.get("player") or {}
        best = None
        for st in entry.get("statistics") or []:
            games = st.get("games") or {}
            starts = games.get("lineups") or 0
            if best is None or starts > best["starts"]:
                goals = st.get("goals") or {}
                rating = games.get("rating")
                best = {
                    "starts": starts,
                    "apps": games.get("appearences") or 0,
                    "minutes": games.get("minutes") or 0,
                    "position": games.get("position"),
                    "rating": round(float(rating), 2) if rating else None,
                    "goals": goals.get("total") or 0,
                    "assists": goals.get("assists") or 0,
                }
        if not best:
            continue
        out.append({"id": p.get("id"), "name": p.get("name"),
                    "photo": p.get("photo"), "age": p.get("age"), **best})
    out.sort(key=lambda r: (-r["starts"], -r["minutes"]))
    return out


async def team_statistics(api_team_id: int, league_api_id: int, season: int) -> dict:
    async def fetch():
        return await client.get("/teams/statistics", "core", team=api_team_id,
                                league=league_api_id, season=season)

    raw = await cache.get_or_set(
        f"af:teamstats:{api_team_id}:{league_api_id}:{season}",
        settings.ttl_standings, fetch)
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    return raw or {}


async def recent_lineup_shape(api_team_id: int, season: int,
                              formation: str | None, count: int = 6) -> dict | None:
    """The club's most recent real XI in a given formation.

    Used as the template for a probable XI: it supplies genuine grid slots
    ("2:4" = second row, fourth across), which the squad data cannot.
    """
    async def fetch():
        fixtures = await client.get("/fixtures", "core", team=api_team_id,
                                    season=season, last=count)
        shapes = []
        for fx in fixtures:
            fid = (fx.get("fixture") or {}).get("id")
            if not fid:
                continue
            blocks = await client.get("/fixtures/lineups", "core", fixture=fid)
            for b in blocks:
                if (b.get("team") or {}).get("id") != api_team_id:
                    continue
                shapes.append({
                    "formation": b.get("formation"),
                    "date": (fx.get("fixture") or {}).get("date", ""),
                    "slots": [
                        {"grid": (p.get("player") or {}).get("grid"),
                         "pos": (p.get("player") or {}).get("pos"),
                         "id": (p.get("player") or {}).get("id"),
                         "name": (p.get("player") or {}).get("name")}
                        for p in b.get("startXI") or []
                    ],
                })
        return shapes

    shapes = await cache.get_or_set(f"af:shapes:{api_team_id}:{season}:{count}",
                                    settings.ttl_standings, fetch)
    if not shapes:
        return None
    if formation:
        match = next((s for s in shapes if s["formation"] == formation), None)
        if match:
            return match
    return shapes[0]


async def team_injuries(api_team_id: int, season: int) -> list[dict]:
    """Who was unavailable for the club's MOST RECENT fixture.

    `/injuries?team=&season=` returns every injury record of the whole season,
    so taking it wholesale marks players unavailable who were fit again months
    ago - it wiped Bruno Fernandes and Casemiro out of a probable XI. Records
    carry the fixture they relate to, so we keep only the latest matchday.
    """
    async def fetch():
        return await client.get("/injuries", "core", team=api_team_id, season=season)

    rows = await cache.get_or_set(f"af:teaminj:{api_team_id}:{season}", 3600, fetch)
    if not rows:
        return []

    latest = max(((r.get("fixture") or {}).get("date") or "") for r in rows)
    if not latest:
        return []

    seen, out = set(), []
    for r in rows:
        if ((r.get("fixture") or {}).get("date") or "") != latest:
            continue
        p = r.get("player") or {}
        if not p.get("id") or p["id"] in seen:
            continue
        seen.add(p["id"])
        out.append({"id": p.get("id"), "name": p.get("name"),
                    "reason": p.get("reason"), "type": p.get("type"),
                    "as_of": latest[:10]})
    return out


async def team_info(api_team_id: int) -> dict:
    """Team identity, including whether it is a national side.

    Needed because /players/teams mixes clubs and national teams together, and
    a player's country can easily have the most recent season - which would
    otherwise make Rashford's 'current club' read England.
    """
    async def fetch():
        return await client.get("/teams", "core", id=api_team_id)

    rows = await cache.get_or_set(f"af:team:{api_team_id}", 2592000, fetch)
    if not rows:
        return {"id": api_team_id, "name": None, "national": False}
    t = (rows[0] or {}).get("team") or {}
    return {
        "id": t.get("id"),
        "name": t.get("name"),
        "national": bool(t.get("national")),
        "country": t.get("country"),
        "logo": t.get("logo"),
        "founded": t.get("founded"),
    }


async def player_teams(player_id: int) -> list[dict]:
    """Clubs a player has been registered with, most recent season first."""
    async def fetch():
        return await client.get("/players/teams", "core", player=player_id)

    rows = await cache.get_or_set(f"af:pteams:{player_id}", settings.ttl_squads, fetch)
    out = []
    for row in rows:
        team = row.get("team") or {}
        seasons = row.get("seasons") or []
        out.append({
            "api_id": team.get("id"),
            "name": team.get("name"),
            "logo": team.get("logo"),
            "seasons": seasons,
            "latest": max(seasons) if seasons else None,
        })
    # National teams have no club seasons; keep clubs with a known season first.
    out.sort(key=lambda t: (t["latest"] is None, -(t["latest"] or 0)))
    return out


async def player_profile(player_id: int) -> dict | None:
    async def fetch():
        return await client.get("/players/profiles", "core", player=player_id)

    rows = await cache.get_or_set(f"af:profile:{player_id}", settings.ttl_squads, fetch)
    if not rows:
        return None
    p = (rows[0] or {}).get("player") or {}
    birth = p.get("birth") or {}
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "firstname": p.get("firstname"),
        "lastname": p.get("lastname"),
        "age": p.get("age"),
        "birth_date": birth.get("date"),
        "birth_place": birth.get("place"),
        "birth_country": birth.get("country"),
        "nationality": p.get("nationality"),
        "height": p.get("height"),
        "weight": p.get("weight"),
        "number": p.get("number"),
        "position": _POS_SHORT.get(p.get("position"), p.get("position")),
        "position_long": p.get("position"),
        "photo": p.get("photo"),
    }


async def player_stats(player_id: int, season: int) -> list[dict]:
    """Per-competition statistics for one season."""
    async def fetch():
        return await client.get("/players", "core", id=player_id, season=season)

    rows = await cache.get_or_set(
        f"af:pstats:{player_id}:{season}", settings.ttl_standings, fetch
    )
    if not rows:
        return []
    out = []
    for block in (rows[0].get("statistics") or []):
        games = block.get("games") or {}
        goals = block.get("goals") or {}
        cards = block.get("cards") or {}
        team = block.get("team") or {}
        league = block.get("league") or {}
        if not games.get("appearences"):
            continue
        rating = games.get("rating")
        out.append({
            "league": league.get("name"),
            "league_api_id": league.get("id"),
            "league_logo": league.get("logo"),
            "country": league.get("country"),
            "team": team.get("name"),
            "team_logo": team.get("logo"),
            "team_api_id": team.get("id"),
            "apps": games.get("appearences") or 0,
            "lineups": games.get("lineups") or 0,
            "minutes": games.get("minutes") or 0,
            "position": games.get("position"),
            "rating": round(float(rating), 2) if rating else None,
            "goals": goals.get("total") or 0,
            "assists": goals.get("assists") or 0,
            "yellow": cards.get("yellow") or 0,
            "red": cards.get("red") or 0,
        })
    out.sort(key=lambda s: (-s["apps"], s["league"] or ""))
    return out


async def player_seasons(player_id: int) -> list[int]:
    """Every season API-Football holds data for, newest first."""
    async def fetch():
        return await client.get("/players/seasons", "core", player=player_id)

    rows = await cache.get_or_set(f"af:pseasons:{player_id}", settings.ttl_squads, fetch)
    return sorted({int(y) for y in rows if str(y).isdigit()}, reverse=True)


async def topassists(league_api_id: int, season: int) -> list[dict]:
    async def fetch():
        return await client.get("/players/topassists", "core",
                                league=league_api_id, season=season)

    rows = await cache.get_or_set(
        f"af:assists:{league_api_id}:{season}", settings.ttl_standings, fetch)
    out = []
    for i, entry in enumerate(rows, 1):
        p = entry.get("player") or {}
        stats = (entry.get("statistics") or [{}])[0]
        goals = stats.get("goals") or {}
        out.append({"rank": i, "player_id": p.get("id"), "player": p.get("name"),
                    "assists": goals.get("assists") or 0,
                    "goals": goals.get("total") or 0})
    return out


async def league_fixtures(league_api_id: int, season: int, when: str = "next",
                          count: int = 20) -> list[dict]:
    """A competition's own fixture list, next or last."""
    param = "next" if when == "next" else "last"
    ttl = 1800 if when == "next" else settings.ttl_fixtures

    async def fetch():
        return await client.get("/fixtures", "core", league=league_api_id,
                                season=season, **{param: count}, timezone="UTC")

    rows = await cache.get_or_set(
        f"af:lgfx:{league_api_id}:{season}:{param}:{count}", ttl, fetch)
    matches = [_match(r) for r in rows]
    matches.sort(key=lambda m: m["kickoff"] or "", reverse=(when == "last"))
    return matches


async def player_transfers(player_id: int) -> list[dict]:
    async def fetch():
        return await client.get("/transfers", "core", player=player_id)

    rows = await cache.get_or_set(
        f"af:ptransfers:{player_id}", settings.ttl_transfers, fetch
    )
    moves = _parse_transfer_rows(rows)
    moves.sort(key=lambda t: t["date"] or "", reverse=True)
    return moves


async def squad(api_team_id: int) -> list[dict]:
    async def fetch():
        return await client.get("/players/squads", "core", team=api_team_id)

    rows = await cache.get_or_set(
        f"af:squad:{api_team_id}", settings.ttl_squads, fetch
    )
    if not rows:
        return []
    players = rows[0].get("players") or []
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "number": p.get("number"),
            "position": _POS_SHORT.get(p.get("position"), p.get("position") or "MF"),
            "position_long": p.get("position"),
            "age": p.get("age"),
            "photo": p.get("photo"),
        }
        for p in players
    ]


async def match_detail(match_id: str) -> dict | None:
    async def fetch():
        return await client.get("/fixtures", "detail", id=match_id)

    rows = await cache.get_or_set(f"af:match:{match_id}", 120, fetch)
    return _match(rows[0], detail=True) if rows else None


# --------------------------------------------------------------------------
# Transfers - the one rich thing the free plan gives us in full
# --------------------------------------------------------------------------
def _parse_transfer_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for entry in rows:
        player = entry.get("player") or {}
        for mv in entry.get("transfers") or []:
            teams = mv.get("teams") or {}
            src, dst = teams.get("out") or {}, teams.get("in") or {}
            src_club = resolve_club(src.get("name"))
            dst_club = resolve_club(dst.get("name"))
            fee_raw = (mv.get("type") or "").strip()
            kind, amount = _classify_fee(fee_raw)
            out.append({
                "id": f"af-{player.get('id')}-{mv.get('date')}-{dst.get('id')}",
                "date": mv.get("date"),
                "player": {
                    "id": player.get("id"),
                    "name": player.get("name"),
                    "logo": player.get("photo"),
                    "position": None,
                    "age": None,
                    "nationality": None,
                },
                "from": {
                    "id": src_club["id"] if src_club else None,
                    "name": src.get("name"),
                    "logo": src.get("logo"),
                    "league": src_club["league"] if src_club else None,
                },
                "to": {
                    "id": dst_club["id"] if dst_club else None,
                    "name": dst.get("name"),
                    "logo": dst.get("logo"),
                    "league": dst_club["league"] if dst_club else None,
                },
                "league": dst_club["league"] if dst_club else (src_club["league"] if src_club else None),
                "fee": {"amount": amount, "label": fee_raw or "Undisclosed", "kind": kind},
                "status": "done",
                "source": "API-Football",
            })
    return out


def _classify_fee(raw: str) -> tuple[str, int]:
    text = (raw or "").strip().lower()
    if not text or text in ("n/a", "-"):
        return "transfer", 0
    if "loan" in text:
        return "loan", 0
    if "free" in text:
        return "free", 0
    # "€ 25.0M", "£ 8M", "€ 500K"
    import re

    m = re.search(r"([\d.,]+)\s*([mk])", text)
    if m:
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            return "transfer", 0
        return "transfer", int(value * (1_000_000 if m.group(2) == "m" else 1_000))
    return "transfer", 0


async def transfers_for_team(api_team_id: int) -> list[dict]:
    async def fetch():
        return await client.get("/transfers", "core", team=api_team_id)

    rows = await cache.get_or_set(
        f"af:transfers:{api_team_id}", settings.ttl_transfers, fetch
    )
    return _parse_transfer_rows(rows)
