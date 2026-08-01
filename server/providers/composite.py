"""Stitches the real API-Football feed together with the simulated season.

On a paid plan every view is backed by real data:

  live scores      /fixtures?live=all
  full calendar    /fixtures?date=          (any date)
  match detail     /fixtures?id=
  standings        /standings
  top scorers      /players/topscorers
  squads           /players/squads          (also backs player search)
  transfers        /transfers?team=         (full 96-club sweep)

The simulated season stays as a fallback for outages and for the free plan,
and every response carries `source` / `simulated` so the UI can label it.
"""
from __future__ import annotations

import asyncio
import json
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..cache import cache
from ..config import CACHE_DIR, settings
from ..data.clubs import CLUBS, CLUB_BY_ID
from ..data.leagues import LEAGUE_BY_ID, LEAGUES, current_season
from ..data.tickets import ticket_link
from ..quota import QuotaExceeded, quota
from . import apifootball as af
from .mock import MockProvider

_TEAM_IDS_PATH = Path(__file__).resolve().parent.parent / "data" / "team_ids.json"
_TRANSFER_STORE = CACHE_DIR / "transfers.json"
_SQUAD_STORE = CACHE_DIR / "squads.json"
_SWEEP_STATE = CACHE_DIR / "sweep.json"

try:
    TEAM_IDS: dict[str, dict] = json.loads(_TEAM_IDS_PATH.read_text())
except (OSError, ValueError):
    TEAM_IDS = {}

API_ID_TO_CLUB = {v["api_id"]: k for k, v in TEAM_IDS.items()}


def _slug(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _fold(text: str | None) -> str:
    """Accent-insensitive lowercase, keeping spaces (for search matching)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def _tag(rows, source: str, simulated: bool):
    for r in rows if isinstance(rows, list) else [rows]:
        if isinstance(r, dict):
            r["source"] = source
            r["simulated"] = simulated
    return rows


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data))
    except (OSError, TypeError):
        pass


class _JsonStore:
    """Memoised JSON file, reloaded only when it changes on disk.

    The transfer store is ~40MB; parsing it costs about a second and 140MB of
    allocation, and it used to be parsed twice per request. Now it is parsed
    once per write.
    """

    def __init__(self, path: Path, default: dict) -> None:
        self.path = path
        self.default = default
        self._data: dict | None = None
        self._mtime: float | None = None
        self._derived: dict = {}

    def _stamp(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def load(self) -> dict:
        stamp = self._stamp()
        if self._data is None or stamp != self._mtime:
            self._data = _read(self.path, dict(self.default))
            self._mtime = stamp
            self._derived.clear()
        return self._data

    def save(self, data: dict) -> None:
        _write(self.path, data)
        self._data = data
        self._mtime = self._stamp()
        self._derived.clear()

    def derive(self, key, build):
        """Cache something computed from the store until the store changes."""
        self.load()
        if key not in self._derived:
            self._derived[key] = build()
        return self._derived[key]


def _prune_transfers(store: dict, retention_days: int) -> tuple[dict, int]:
    """Drop rows older than the retention window.

    The raw feed reaches back to 1926 and only ~29% of rows are from the last
    three years, so this is most of the file for none of the value.
    """
    cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
    dropped = 0
    for entry in store.get("clubs", {}).values():
        rows = entry.get("rows") or []
        kept = [r for r in rows if (r.get("date") or "") >= cutoff]
        dropped += len(rows) - len(kept)
        entry["rows"] = kept
    return store, dropped


class CompositeProvider:
    name = "composite"

    def __init__(self) -> None:
        self.sim = MockProvider()
        self._season_cache: dict[str, tuple[int, bool]] = {}
        self._transfers = _JsonStore(_TRANSFER_STORE, {"clubs": {}, "updated": None})
        self._squads = _JsonStore(_SQUAD_STORE, {"clubs": {}, "updated": None})

    # ----------------------------------------------------------------- season
    async def _season(self, league_id: str) -> tuple[int, bool]:
        """Pick the season to show, and whether it is under way.

        A season that has not kicked off yet has an all-zero table, which is
        useless to look at, so we fall back to the last completed one and let
        the UI say which season it is showing.
        """
        if league_id in self._season_cache:
            return self._season_cache[league_id]

        meta = LEAGUE_BY_ID[league_id]
        season = current_season()
        try:
            table = await af.standings(meta["api_id"], season)
            started = any(r["played"] for r in table)
            if not started:
                season, started = season - 1, True
        except Exception:
            started = True
        self._season_cache[league_id] = (season, started)
        return season, started

    # ----------------------------------------------------------------- live
    async def live(self, scope: str = "big5") -> dict:
        try:
            rows = await af.live_matches(big5_only=(scope == "big5"))
            payload = {"matches": _tag(rows, "apifootball", False),
                       "source": "apifootball", "simulated": False,
                       "scope": scope,
                       "poll_seconds": quota.suggested_poll_seconds()}
            if not rows and scope == "big5":
                other = await af.live_matches(big5_only=False)
                payload["elsewhere"] = _tag(other[:40], "apifootball", False)
                payload["note"] = ("No big-five matches in play. "
                                   f"{len(other)} live worldwide.")
            return payload
        except QuotaExceeded:
            stale = cache.peek_stale("af:live")
            if stale is not None:
                rows = [af._match(r) for r in stale]
                rows = [m for m in rows if m["league"] in af.BIG5_API_IDS.values()]
                return {"matches": _tag(rows, "apifootball-cached", False),
                        "source": "apifootball-cached", "simulated": False,
                        "note": "Daily live budget spent - showing last fetched scores.",
                        "poll_seconds": 0}
            rows = await self.sim.live()
            return {"matches": _tag(rows, "simulated", True), "source": "simulated",
                    "simulated": True, "poll_seconds": 0,
                    "note": "Daily live budget spent - showing simulated matches."}
        except Exception as exc:
            rows = await self.sim.live()
            return {"matches": _tag(rows, "simulated", True), "source": "simulated",
                    "simulated": True, "poll_seconds": 0, "note": f"Upstream error: {exc}"}

    # ------------------------------------------------------------- fixtures
    async def fixtures_by_date(self, day: str) -> dict:
        if settings.is_live and af.in_free_window(day):
            try:
                rows = await af.fixtures_on(day)
                if rows:
                    return {"matches": _tag(rows, "apifootball", False),
                            "source": "apifootball", "simulated": False, "date": day}
                return {"matches": [], "source": "apifootball", "simulated": False,
                        "date": day, "real_result_empty": True,
                        "note": "No big-five fixtures scheduled on this date."}
            except QuotaExceeded:
                stale = cache.peek_stale(f"af:fixtures:{day}")
                if stale is not None:
                    rows = [af._match(r) for r in stale]
                    rows = [m for m in rows if m["league"] in af.BIG5_API_IDS.values()]
                    return {"matches": _tag(rows, "apifootball-cached", False),
                            "source": "apifootball-cached", "simulated": False, "date": day,
                            "note": "Request budget spent - cached fixtures."}
            except Exception:
                pass
        rows = await self.sim.fixtures_by_date(day)
        note = None
        if settings.is_live:
            lo, hi = af.free_window()
            note = (f"Free plan only serves real fixtures for {lo} to {hi}. "
                    "This day is simulated.")
        return {"matches": _tag(rows, "simulated", True), "source": "simulated",
                "simulated": True, "date": day, "note": note}

    async def match(self, match_id: str) -> dict | None:
        if match_id.isdigit() and settings.is_live:
            try:
                m = await af.match_detail(match_id)
                if m:
                    m["source"], m["simulated"] = "apifootball", False
                    await self._enrich_match(m)
                    return m
            except Exception:
                pass
        m = await self.sim.match(match_id)
        if m:
            m["source"], m["simulated"] = "simulated", True
        return m

    async def _enrich_match(self, m: dict) -> None:
        """Add player ratings, real head-to-head and unavailable players.

        Each is optional and independently guarded - a match page must still
        render if one of these endpoints has nothing for this fixture.
        """
        home_api = (m.get("home") or {}).get("api_id")
        away_api = (m.get("away") or {}).get("api_id")
        started = (m.get("status") or {}).get("type") in ("live", "finished")

        if started:
            try:
                m["player_stats"] = await af.fixture_players(m["id"], home_api)
            except Exception:
                m["player_stats"] = None

        if home_api and away_api:
            try:
                rows = await af.head_to_head(home_api, away_api, 10)
                m["h2h"] = [r for r in rows if r["id"] != m["id"]][:8]
                m["h2h_summary"] = _h2h_summary(m["h2h"], home_api)
            except Exception:
                m["h2h"] = []

        try:
            m["unavailable"] = await af.fixture_injuries(m["id"], home_api)
        except Exception:
            m["unavailable"] = None

    # ------------------------------------------------------------- standings
    async def standings(self, league_id: str) -> dict:
        meta = LEAGUE_BY_ID[league_id]
        if settings.is_live:
            try:
                season, _ = await self._season(league_id)
                table = await af.standings(meta["api_id"], season)
                if table:
                    return {"table": table, "source": "apifootball", "simulated": False,
                            "season": _season_label(season),
                            "note": (None if season == current_season()
                                     else f"The {_season_label(current_season())} season has not "
                                          f"kicked off yet - showing final {_season_label(season)} "
                                          f"standings.")}
            except Exception as exc:
                pass
        rows = await self.sim.standings(league_id)
        return {"table": rows, "source": "simulated", "simulated": True,
                "note": "Live standings unavailable - showing the simulated season."}

    async def scorers(self, league_id: str) -> dict:
        meta = LEAGUE_BY_ID[league_id]
        if settings.is_live:
            try:
                season, _ = await self._season(league_id)
                rows = await af.topscorers(meta["api_id"], season)
                if not rows and season == current_season():
                    season -= 1
                    rows = await af.topscorers(meta["api_id"], season)
                if rows:
                    return {"scorers": rows, "source": "apifootball", "simulated": False,
                            "season": _season_label(season),
                            "note": (None if season == current_season()
                                     else f"No goals scored in {_season_label(current_season())} "
                                          f"yet - showing the {_season_label(season)} chart.")}
            except Exception:
                pass
        rows = await self.sim.scorers(league_id)
        return {"scorers": rows, "source": "simulated", "simulated": True,
                "note": "Live scorer chart unavailable - showing the simulated season."}

    # --------------------------------------------------------------- squads
    def _squad_store(self) -> dict:
        return self._squads.load()

    async def sweep_squads(self, limit: int | None = None) -> dict:
        """Pull real squads so player search has something to search."""
        if not settings.is_live:
            return {"swept": 0, "reason": "mock mode"}
        store = self._squad_store()
        club_ids = [c["id"] for c in CLUBS if c["id"] in TEAM_IDS]
        todo = [c for c in club_ids if c not in store["clubs"]] or club_ids
        if limit:
            todo = todo[:limit]

        swept, failed = [], []
        for club_id in todo:
            if not quota.can_spend("core", 1):
                break
            try:
                players = await af.squad(TEAM_IDS[club_id]["api_id"])
            except QuotaExceeded:
                break
            except Exception as exc:
                failed.append({"club": club_id, "error": str(exc)[:120]})
                continue
            store["clubs"][club_id] = {
                "fetched": datetime.now(timezone.utc).isoformat(),
                "players": players,
            }
            swept.append(club_id)

        store["updated"] = datetime.now(timezone.utc).isoformat()
        self._squads.save(store)
        self._player_index = None  # force rebuild
        return {"swept": len(swept), "failed": failed,
                "covered": len(store["clubs"]), "total_clubs": len(club_ids)}

    _player_index: list[dict] | None = None

    def _players(self) -> list[dict]:
        if self._player_index is not None:
            return self._player_index
        store = self._squad_store()
        index: list[dict] = []
        for club_id, entry in store.get("clubs", {}).items():
            club = CLUB_BY_ID.get(club_id)
            if not club:
                continue
            for p in entry.get("players", []):
                if not p.get("name"):
                    continue
                index.append({
                    **p,
                    "club": club_id,
                    "club_name": club["short"],
                    "club_colour": club["colour"],
                    "league": club["league"],
                    "_fold": _fold(p["name"]),
                })
        self._player_index = index
        return index

    # ------------------------------------------------------------ transfers
    def _load_store(self) -> dict:
        return self._transfers.load()

    def _sweep_cursor(self) -> int:
        return int(_read(_SWEEP_STATE, {}).get("cursor", 0))

    def _set_cursor(self, cursor: int) -> None:
        _write(_SWEEP_STATE, {"cursor": cursor,
                              "at": datetime.now(timezone.utc).isoformat()})

    async def sweep_transfers(self, limit: int | None = None) -> dict:
        if not settings.is_live or settings.transfer_source != "apifootball":
            return {"swept": 0, "reason": "live transfers disabled"}

        limit = limit or settings.transfer_sweep_size
        club_ids = [c["id"] for c in CLUBS if c["id"] in TEAM_IDS]
        if not club_ids:
            return {"swept": 0, "reason": "no team id map"}

        cursor = self._sweep_cursor()
        store = self._load_store()
        swept, failed = [], []

        for i in range(min(limit, len(club_ids))):
            if not quota.can_spend("core", 1):
                break
            club_id = club_ids[(cursor + i) % len(club_ids)]
            try:
                rows = await af.transfers_for_team(TEAM_IDS[club_id]["api_id"])
            except QuotaExceeded:
                break
            except Exception as exc:
                failed.append({"club": club_id, "error": str(exc)[:120]})
                continue
            store["clubs"][club_id] = {
                "fetched": datetime.now(timezone.utc).isoformat(),
                "rows": rows,
            }
            swept.append(club_id)

        self._set_cursor((cursor + len(swept) + len(failed)) % len(club_ids))
        store["updated"] = datetime.now(timezone.utc).isoformat()
        store, dropped = _prune_transfers(store, settings.transfer_retention_days)
        self._transfers.save(store)
        return {"swept": len(swept), "clubs": swept, "failed": failed,
                "covered": len(store["clubs"]), "total_clubs": len(club_ids),
                "pruned": dropped, "next_cursor": self._sweep_cursor()}

    def _merged_transfers(self, cutoff: str) -> list[dict]:
        return self._transfers.derive(("merged", cutoff),
                                      lambda: self._build_merged(cutoff))

    def _build_merged(self, cutoff: str) -> list[dict]:
        """De-duplicated moves on or after `cutoff` (YYYY-MM-DD).

        Both clubs report a deal, often a day apart, so the key is the move
        itself rather than the reported date."""
        covered = self._load_store().get("clubs", {})
        best: dict[tuple, dict] = {}
        for entry in covered.values():
            for row in entry.get("rows", []):
                if not row.get("date") or row["date"] < cutoff:
                    continue
                key = (_slug(row["player"].get("name")),
                       _slug(row["from"].get("name")),
                       _slug(row["to"].get("name")))
                prev = best.get(key)
                if prev is None or (row["fee"]["amount"], row["date"]) > \
                        (prev["fee"]["amount"], prev["date"]):
                    best[key] = row
        rows = [t for t in best.values() if t["from"]["league"] or t["to"]["league"]]
        rows.sort(key=lambda t: (t["date"], t["fee"]["amount"]), reverse=True)
        return rows

    async def transfers(self, league_id: str | None, limit: int,
                        window: str = "season", query: str = "",
                        group: str = "club") -> dict:
        store = self._load_store()
        covered = store.get("clubs", {})

        if not covered:
            rows = await self.sim.transfers(league_id, limit)
            return {"transfers": rows, "clubs": [], "source": "simulated",
                    "simulated": True,
                    "coverage": {"clubs": 0, "total": len(TEAM_IDS)},
                    "note": "No transfer sweep has run yet. "
                            "POST /api/transfers/sync to pull real data."}

        cutoff = window_start(window)
        rows = self._merged_transfers(cutoff)
        if league_id:
            rows = [t for t in rows
                    if t["to"]["league"] == league_id or t["from"]["league"] == league_id]
        if query:
            q = _fold(query)
            rows = [t for t in rows if q in _fold(t["player"].get("name"))
                    or q in _fold(t["from"].get("name"))
                    or q in _fold(t["to"].get("name"))]

        flat = rows[:limit]
        oldest = min((e.get("fetched") or "" for e in covered.values()), default=None)
        payload = {
            "transfers": flat,
            "source": "apifootball", "simulated": False,
            "total_matching": len(rows),
            "window": window, "window_label": window_label(window), "since": cutoff,
            "coverage": {"clubs": len(covered), "total": len(TEAM_IDS),
                         "oldest_fetch": oldest, "updated": store.get("updated")},
        }
        if group == "club":
            payload["clubs"] = _group_by_club(rows, league_id)
        return payload

    # ------------------------------------------------------------ team/search
    async def team(self, team_id: str) -> dict | None:
        club = CLUB_BY_ID.get(team_id)
        if not club:
            return None
        data = await self.sim.team(team_id)
        if not data:
            return None

        api = TEAM_IDS.get(team_id)
        if api:
            data["club"] = {**data["club"], "logo": api.get("logo"), "api_id": api["api_id"]}
            # Real fixtures across every competition, not the simulated season.
            try:
                upcoming = await af.team_fixtures(api["api_id"], "next", 10)
                recent = await af.team_fixtures(api["api_id"], "last", 10)
                if upcoming or recent:
                    data["upcoming"] = _tag(upcoming, "apifootball", False)
                    data["recent"] = _tag(recent, "apifootball", False)
                    data["fixtures_source"] = "apifootball"
            except Exception:
                data["fixtures_source"] = "simulated"
        data.setdefault("fixtures_source", "simulated")

        # real squad when we have it
        entry = self._squad_store().get("clubs", {}).get(team_id)
        if entry and entry.get("players"):
            data["squad"] = [{**p, "club": team_id} for p in entry["players"]]
            data["squad_source"] = "apifootball"
        else:
            data["squad_source"] = "simulated"

        # real league position
        try:
            st = await self.standings(club["league"])
            row = next((r for r in st["table"] if r["team"]["id"] == team_id), None)
            if row:
                data["standing"] = row
                data["form"] = row.get("form") or data.get("form")
                data["standing_source"] = st["source"]
        except Exception:
            pass

        tstore = self._load_store().get("clubs", {}).get(team_id)
        if tstore:
            data["transfers"] = tstore["rows"][:24]
            data["transfers_source"] = "apifootball"
        else:
            data["transfers_source"] = "simulated"
        return data

    async def search(self, query: str) -> dict:
        q = _fold(query)
        if not q:
            return {"teams": [], "players": [], "leagues": []}

        teams = [c for c in CLUBS
                 if q in _fold(c["name"]) or q in _fold(c["short"])][:8]
        leagues = [lg for lg in LEAGUES if q in _fold(lg["name"])][:5]

        local = [p for p in self._players() if q in p["_fold"]]
        local.sort(key=lambda p: (
            0 if p["_fold"].startswith(q) else
            1 if any(w.startswith(q) for w in p["_fold"].split()) else 2,
            p["name"],
        ))
        players = [{k: v for k, v in p.items() if k != "_fold"} for p in local[:12]]
        seen_ids = {p.get("id") for p in players}
        remote_used = False

        # /players/squads misses loanees and late signings, so top up from the
        # global player index whenever the local squads come up short.
        if settings.is_live and len(players) < 5 and len(query.strip()) >= 4:
            try:
                for p in await af.search_players(query):
                    if p["id"] in seen_ids:
                        continue
                    seen_ids.add(p["id"])
                    club = await self._current_club(p["id"])
                    players.append({**p, **club, "remote": True})
                    remote_used = True
                    if len(players) >= 12:
                        break
            except Exception:
                pass

        return {"teams": teams, "players": players, "leagues": leagues,
                "player_index_size": len(self._players()),
                "used_global_search": remote_used}

    async def _has_club_football(self, stats: list[dict]) -> bool:
        for s in stats:
            if not await self._is_national(s.get("team_api_id")):
                return True
        return False

    async def _is_national(self, api_team_id: int | None) -> bool:
        if not api_team_id:
            return False
        if api_team_id in API_ID_TO_CLUB:   # one of our 96, definitely a club
            return False
        try:
            return (await af.team_info(api_team_id)).get("national", False)
        except Exception:
            return False

    async def _current_club(self, player_id: int) -> dict:
        """Most recent *club* for a player. National sides are skipped."""
        blank = {"club": None, "club_name": None, "club_colour": None}
        try:
            teams = await af.player_teams(player_id)
        except Exception:
            return blank
        for t in teams:
            if t["latest"] is None or await self._is_national(t["api_id"]):
                continue
            club_id = API_ID_TO_CLUB.get(t["api_id"])
            club = CLUB_BY_ID.get(club_id) if club_id else None
            return {
                "club": club_id,
                "club_name": club["short"] if club else t["name"],
                "club_colour": club["colour"] if club else "#7a8699",
                "club_logo": t.get("logo"),
            }
        return blank

    # ---------------------------------------------------------------- player
    async def player(self, player_id: str) -> dict | None:
        if not settings.is_live or not player_id.isdigit():
            return None
        pid = int(player_id)
        profile = await af.player_profile(pid)
        if not profile:
            return None

        # A new season often only has international fixtures in it, which makes
        # for a bare page, so fall back until we find club football.
        season = current_season()
        stats = await af.player_stats(pid, season)
        if not await self._has_club_football(stats):
            prev = await af.player_stats(pid, season - 1)
            if prev:
                season, stats = season - 1, prev

        try:
            transfers = _dedupe_moves(await af.player_transfers(pid))
        except Exception:
            transfers = []
        try:
            teams = await af.player_teams(pid)
        except Exception:
            teams = []

        club = await self._current_club(pid)
        career = []
        for t in teams:
            club_id = API_ID_TO_CLUB.get(t["api_id"])
            career.append({**t, "club": club_id,
                           "league": CLUB_BY_ID[club_id]["league"] if club_id else None})

        totals = {
            "apps": sum(s["apps"] for s in stats),
            "goals": sum(s["goals"] for s in stats),
            "assists": sum(s["assists"] for s in stats),
            "minutes": sum(s["minutes"] for s in stats),
            "yellow": sum(s["yellow"] for s in stats),
            "red": sum(s["red"] for s in stats),
        }
        rated = [s["rating"] for s in stats if s["rating"]]
        totals["rating"] = round(sum(rated) / len(rated), 2) if rated else None

        return {
            "profile": profile,
            "current_club": club,
            "season": _season_label(season),
            "stats": stats,
            "totals": totals,
            "career": career,
            "transfers": transfers[:20],
            "source": "apifootball",
            "simulated": False,
        }


def window_start(window: str = "season") -> str:
    """Cutoff date for the transfer feed.

    "season" means everything since the current window opened, i.e. after the
    previous campaign finished. European seasons end in May, so the window is
    anchored to 1 June - that is what "this season's transfers" means.
    """
    today = date.today()
    if window == "all":
        # Only as far back as we actually retain on disk.
        return (today - timedelta(days=settings.transfer_retention_days)).isoformat()
    if window == "year":
        return (today - timedelta(days=365)).isoformat()
    year = today.year if today.month >= 6 else today.year - 1
    return date(year, 6, 1).isoformat()


def window_label(window: str = "season") -> str:
    if window == "all":
        years = max(1, round(settings.transfer_retention_days / 365))
        return f"Last {years} years"
    if window == "year":
        return "Last 12 months"
    start = date.fromisoformat(window_start("season"))
    return f"{start.year}/{str(start.year + 1)[-2:]} season"


def _h2h_summary(rows: list[dict], home_api_id: int | None) -> dict:
    """Wins/draws/losses from the perspective of this fixture's home side."""
    won = drew = lost = gf = ga = 0
    for r in rows:
        if (r["status"] or {}).get("type") != "finished":
            continue
        is_home = (r["home"] or {}).get("api_id") == home_api_id
        mine = r["home"]["score"] if is_home else r["away"]["score"]
        theirs = r["away"]["score"] if is_home else r["home"]["score"]
        gf += mine
        ga += theirs
        if mine > theirs:
            won += 1
        elif mine == theirs:
            drew += 1
        else:
            lost += 1
    return {"played": won + drew + lost, "won": won, "drew": drew,
            "lost": lost, "gf": gf, "ga": ga}


def _season_label(year: int) -> str:
    return f"{year}/{str(year + 1)[-2:]}"


def _words(text: str | None) -> list[str]:
    """Lowercase alphanumeric tokens, punctuation stripped ('J. Sancho' -> j, sancho)."""
    if not text:
        return []
    return [w for w in "".join(
        ch if ch.isalnum() else " " for ch in _fold(text)).split() if w]


def _looks_like_the_player(club: dict, player_name: str | None) -> bool:
    """Upstream sometimes files the player's own name as the club
    ('Manchester United -> Sancho Jadon'), often with the names reversed so a
    plain subset test misses it. Match on surname instead, and only when the
    'club' is unknown to our registry - a real club never trips this.
    """
    if club.get("id"):            # resolved to one of our 96 clubs: genuine
        return False
    club_words = set(_words(club.get("name")))
    player_words = [w for w in _words(player_name) if len(w) > 2]
    if not club_words or not player_words:
        return False
    surname = player_words[-1]
    return surname in club_words


def _dedupe_moves(rows: list[dict]) -> list[dict]:
    """Same move, two spellings ('Manchester Utd' / 'Manchester United')."""
    best: dict[tuple, dict] = {}
    for row in rows:
        name = row["player"].get("name")
        if _looks_like_the_player(row["to"], name) or \
           _looks_like_the_player(row["from"], name):
            continue
        key = (row.get("date"), _slug(row["from"].get("name"))[:12],
               _slug(row["to"].get("name"))[:12])
        prev = best.get(key)
        if prev is None or (row["fee"]["amount"] or 0) > (prev["fee"]["amount"] or 0):
            best[key] = row
    out = list(best.values())
    out.sort(key=lambda t: t["date"] or "", reverse=True)
    return out


def _group_by_club(rows: list[dict], league_id: str | None) -> list[dict]:
    """Bucket moves under the big-five club involved, split into in and out."""
    buckets: dict[str, dict] = {}

    def bucket(club_id: str) -> dict:
        club = CLUB_BY_ID[club_id]
        if club_id not in buckets:
            buckets[club_id] = {
                "club": {"id": club_id, "name": club["name"], "short": club["short"],
                         "tla": club["tla"], "colour": club["colour"],
                         "league": club["league"],
                         "logo": (TEAM_IDS.get(club_id) or {}).get("logo")},
                "in": [], "out": [], "spent": 0, "received": 0,
            }
        return buckets[club_id]

    for t in rows:
        to_id, from_id = t["to"].get("id"), t["from"].get("id")
        if to_id and to_id in CLUB_BY_ID and (not league_id or CLUB_BY_ID[to_id]["league"] == league_id):
            b = bucket(to_id)
            b["in"].append(t)
            b["spent"] += t["fee"]["amount"] or 0
        if from_id and from_id in CLUB_BY_ID and (not league_id or CLUB_BY_ID[from_id]["league"] == league_id):
            b = bucket(from_id)
            b["out"].append(t)
            b["received"] += t["fee"]["amount"] or 0

    out = list(buckets.values())
    for b in out:
        b["count"] = len(b["in"]) + len(b["out"])
        b["net"] = b["received"] - b["spent"]
    out.sort(key=lambda b: (-b["count"], b["club"]["name"]))
    return out


def build_provider():
    if settings.effective_provider == "mock":
        return MockProvider()
    return CompositeProvider()
