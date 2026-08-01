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
# Competitions whose minutes we treat as comparable when ranking a signing.
_COVERED_IDS = {lg["api_id"] for lg in LEAGUES} | {3, 848}   # + Europa, Conference


def _slug(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _club_key(side: dict) -> str:
    """A stable identity for a transfer's club side.

    Prefer the already-resolved registry id over slugging the raw name: two
    records for the same real move sometimes spell a club differently
    ("Manchester United" vs "Manchester Utd"), which would otherwise slug to
    two different keys and defeat de-duplication entirely.
    """
    return side.get("id") or f"~{_slug(side.get('name'))}"


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
            rows = await af.live_matches(covered_only=(scope == "big5"))
            payload = {"matches": _tag(rows, "apifootball", False),
                       "source": "apifootball", "simulated": False,
                       "scope": scope,
                       "poll_seconds": quota.suggested_poll_seconds()}
            return payload
        except QuotaExceeded:
            stale = cache.peek_stale("af:live")
            if stale is not None:
                rows = [af._match(r) for r in stale]
                rows = [m for m in rows if m["league"] in af.COVERED_API_IDS.values()]
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
                    rows = [m for m in rows if m["league"] in af.COVERED_API_IDS.values()]
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

    async def honours(self, league_id: str, count: int = 8) -> dict:
        """Recent winners of a competition."""
        meta = LEAGUE_BY_ID.get(league_id)
        if not meta or not settings.is_live:
            return {"honours": [], "source": "unavailable"}
        latest = current_season()
        seasons = [latest - i for i in range(1, count + 1)]
        rows = await af.honours(meta["api_id"], seasons)
        return {"honours": rows, "source": "apifootball", "simulated": False}

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

    async def _full_roster(self, club_id: str) -> list[dict]:
        """A club's squad, from both endpoints unioned.

        `/players/squads` alone is incomplete - for Real Madrid it returned 39
        players and omitted Endrick, Carvajal, Modric, Ceballos and Alaba,
        while `/players?team=` had 51. Neither is a superset of the other:
        the squad list carries shirt numbers and brand-new signings who have
        not played yet, the season list carries everyone who actually
        appeared. Merged, keyed on player id, squad-list fields winning where
        both have a value.
        """
        api_id = TEAM_IDS[club_id]["api_id"]
        squad = await af.squad(api_id)
        by_id: dict[int, dict] = {p["id"]: p for p in squad if p.get("id")}

        try:
            club = CLUB_BY_ID.get(club_id)
            season, _ = await self._season(club["league"]) if club else (None, None)
            if season:
                for p in await af.team_season_players(api_id, season):
                    pid = p.get("id")
                    if not pid:
                        continue
                    if pid in by_id:
                        # Fill only what the squad list left blank.
                        for k in ("position", "photo", "age"):
                            if not by_id[pid].get(k) and p.get(k):
                                by_id[pid][k] = p[k]
                    else:
                        by_id[pid] = {
                            "id": pid, "name": p.get("name"),
                            "photo": p.get("photo"), "age": p.get("age"),
                            "number": None,
                            "position": p.get("position"),
                            "position_long": p.get("position"),
                        }
        except QuotaExceeded:
            raise
        except Exception:
            pass  # squad list alone is still better than nothing

        return list(by_id.values())

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
                players = await self._full_roster(club_id)
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
                # Upstream occasionally reports a club transferring a player
                # to itself (literally, or via two spellings that resolve to
                # the same registry id, e.g. "East Bengal 2" / "East Bengal
                # II"). Not a real transfer - drop it before it can land in
                # both a club's In and Out columns for the same non-event.
                if _club_key(row["from"]) == _club_key(row["to"]):
                    continue
                key = (_slug(row["player"].get("name")),
                       _club_key(row["from"]), _club_key(row["to"]))
                prev = best.get(key)
                if prev is None or (row["fee"]["amount"], row["date"]) > \
                        (prev["fee"]["amount"], prev["date"]):
                    best[key] = row

        # API-Football sometimes reports the same real move with the two legs
        # swapped - e.g. "Napoli -> Man Utd" one day and "Man Utd -> Napoli"
        # the next, or a fringe loan out to a non-registry club reported once
        # each direction - which the key above does not catch, since from/to
        # are reversed. Left alone, a player shows up in both a club's In and
        # Out columns for what is really one event. Collapse same-player
        # moves between the same pair of counterparties down to whichever
        # telling is most recent.
        #
        # _club_key falls back to a slugged name when a club has no registry
        # id (most non-big-five/ISL counterparties), so this still collapses
        # correctly as long as that name is spelled the same both times -
        # true for the vast majority of cases, since it is the same upstream
        # record either way.
        by_pair: dict[tuple, dict] = {}
        for row in best.values():
            pair = frozenset({_club_key(row["from"]), _club_key(row["to"])})
            key = (_slug(row["player"].get("name")), pair)
            prev = by_pair.get(key)
            if prev is None or row["date"] > prev["date"]:
                by_pair[key] = row

        rows = [t for t in by_pair.values() if t["from"]["league"] or t["to"]["league"]]
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

    async def team_generic(self, api_id: int) -> dict | None:
        """Club page for a team outside the tracked registry - mostly
        Champions League qualifying/group opponents from leagues we do not
        otherwise cover. There is no local record for these clubs, so this
        skips standings, tickets and the transfer sweep and sticks to what
        the API can answer directly: identity, real fixtures and squad."""
        if not settings.is_live:
            return None
        info = await af.team_info(api_id)
        if not info.get("name"):
            return None

        upcoming, recent, roster = await asyncio.gather(
            af.team_fixtures(api_id, "next", 8),
            af.team_fixtures(api_id, "last", 8),
            af.squad(api_id),
        )
        team_key = f"api-{api_id}"
        return {
            "club": {"id": team_key, "name": info["name"], "short": info["name"],
                     "tla": info["name"][:3].upper(), "colour": "#7a8699",
                     "logo": info.get("logo"), "stadium": info.get("stadium") or ""},
            "league": None,
            "standing": None,
            "form": None,
            "tickets": None,
            "upcoming": _tag(upcoming, "apifootball", False),
            "recent": _tag(recent, "apifootball", False),
            "fixtures_source": "apifootball",
            "squad": [{**p, "club": team_key} for p in roster],
            "squad_source": "apifootball" if roster else "simulated",
            "transfers": [],
            "transfers_source": "apifootball",
            "generic": True,
        }

    # ------------------------------------------------------------ probable XI
    async def probable_xi(self, team_id: str) -> dict:
        """A likely starting XI, grounded in who actually starts.

        Built from four real signals rather than a guess: the club's most-used
        formation, the grid slots of its most recent XI in that shape, how
        often each player has started, and who is currently unavailable.
        Explicitly labelled probable - it is not a published teamsheet.
        """
        club = CLUB_BY_ID.get(team_id)
        api = TEAM_IDS.get(team_id)
        if not club or not api or not settings.is_live:
            return {"available": False, "reason": "no data for this club"}

        api_id = api["api_id"]
        meta = LEAGUE_BY_ID[club["league"]]
        season, _ = await self._season(club["league"])

        # The roster must be the CURRENT squad, not last season's appearance
        # list: a summer signing has no record at this club yet, so ranking
        # off that list alone made Tonali invisible at Spurs.
        squad_entry = self._squad_store().get("clubs", {}).get(team_id) or {}
        roster = squad_entry.get("players") or []

        stats_here = {p["id"]: p for p in await af.team_season_players(api_id, season)}

        # Who arrived this window, and where from. Reads the deduplicated,
        # swap-collapsed list (see _build_merged) rather than this club's raw
        # sweep rows - a player whose Man Utd record was reported both as an
        # arrival and a departure (a known upstream data glitch) would
        # otherwise count as a signing here even after their latest real event
        # was actually leaving.
        since = window_start("season")
        arrivals_by_id: dict[int, dict] = {
            t["player"]["id"]: t
            for t in self._merged_transfers(since)
            if t["player"].get("id") and t["to"].get("id") == team_id
        }

        players: list[dict] = []
        for r in roster:
            pid = r.get("id")
            if not pid:
                continue
            here = stats_here.get(pid)
            if here:
                players.append({**here, "name": r.get("name") or here.get("name"),
                                "photo": r.get("photo") or here.get("photo"),
                                "position": here.get("position") or r.get("position"),
                                "from_elsewhere": None})
                continue
            # No record at this club. If they just signed, rank them on what
            # they did at their previous club instead of dropping them.
            elsewhere = None
            if pid in arrivals_by_id and len(arrivals_by_id) <= 30:
                elsewhere = await af.player_season_best(pid, season)
                # A Championship regular outranking a Premier League starter is
                # not a useful signal, so only credit starts from competitions
                # we cover.
                if elsewhere and elsewhere.get("league_api_id") not in _COVERED_IDS:
                    elsewhere = {**elsewhere, "starts": 0, "unproven": True}
            players.append({
                "id": pid, "name": r.get("name"), "photo": r.get("photo"),
                "position": (elsewhere or {}).get("position") or r.get("position"),
                "starts": (elsewhere or {}).get("starts") or 0,
                "apps": (elsewhere or {}).get("apps") or 0,
                "minutes": (elsewhere or {}).get("minutes") or 0,
                "rating": (elsewhere or {}).get("rating"),
                "goals": (elsewhere or {}).get("goals") or 0,
                "assists": (elsewhere or {}).get("assists") or 0,
                "from_elsewhere": (elsewhere or {}).get("at"),
                "unproven": bool((elsewhere or {}).get("unproven")),
            })

        # Anyone with a record here but no longer in the squad has left.
        players.sort(key=lambda r: (-(r["starts"] or 0), -(r["minutes"] or 0)))
        if not players:
            players = list(stats_here.values())
        if not players:
            return {"available": False, "reason": "no squad data for this season"}

        stats = await af.team_statistics(api_id, meta["api_id"], season)
        used = [l for l in (stats.get("lineups") or []) if l.get("formation")]
        used.sort(key=lambda l: -(l.get("played") or 0))
        formation = used[0]["formation"] if used else None

        shape = await af.recent_lineup_shape(api_id, season, formation)
        try:
            injured = {p["id"]: p for p in await af.team_injuries(api_id, season)}
        except Exception:
            injured = {}

        by_id = {p["id"]: p for p in players}
        pools: dict[str, list] = {"G": [], "D": [], "M": [], "F": []}
        for p in players:
            if p["id"] in injured:
                continue
            pools.get(_pos_bucket(p["position"]), pools["M"]).append(p)

        # New arrivals since the window opened, so they can be badged.
        new_ids = set(arrivals_by_id)

        picked: set[int] = set()

        def take(bucket: str, fallback: bool = True):
            """Best available player for a position band, by starts."""
            for cand in pools.get(bucket, []):
                if cand["id"] not in picked:
                    picked.add(cand["id"])
                    return cand
            if not fallback:
                return None
            # Position dry (every forward injured, say) - take the best of
            # whoever is left rather than leaving a hole in the XI.
            for other in ("F", "M", "D", "G"):
                for cand in pools.get(other, []):
                    if cand["id"] not in picked:
                        picked.add(cand["id"])
                        return cand
            return None

        xi: list[dict] = []
        if shape and shape.get("slots"):
            slots = shape["slots"]
            # Fill each position band with the best available players, then
            # seat them. Simply letting whoever held a slot keep it meant a
            # 31-start signing sat behind a 14-start incumbent; ranking the
            # band first and preferring a player's own slot second gives both
            # the right personnel and the right shape.
            by_band: dict[str, list[int]] = {}
            for i, slot in enumerate(slots):
                by_band.setdefault(_pos_bucket(slot.get("pos")), []).append(i)

            assigned: dict[int, dict] = {}
            for band, idxs in by_band.items():
                pool = [p for p in pools.get(band, []) if p["id"] not in picked]
                chosen = pool[:len(idxs)]
                # Short of bodies in this band (every forward injured, say):
                # top up from whoever is left.
                if len(chosen) < len(idxs):
                    spare = [p for other in ("F", "M", "D", "G")
                             for p in pools.get(other, [])
                             if p["id"] not in picked and p not in chosen]
                    chosen += spare[:len(idxs) - len(chosen)]
                for p in chosen:
                    picked.add(p["id"])

                free = list(idxs)
                seated: dict[int, dict] = {}
                # A player who held one of these slots keeps it.
                for p in chosen:
                    for i in list(free):
                        if slots[i].get("id") == p["id"]:
                            seated[i] = p
                            free.remove(i)
                            break
                for p in chosen:
                    if p in seated.values():
                        continue
                    if not free:
                        break
                    seated[free.pop(0)] = p
                assigned.update(seated)

            for i, slot in enumerate(slots):
                pick = assigned.get(i)
                if not pick:
                    continue
                held = slot.get("id") == pick["id"]
                xi.append({**pick, "grid": slot.get("grid"),
                           "slot_pos": slot.get("pos"),
                           "basis": "held" if held else "promoted",
                           "replaces": None if held else slot.get("name"),
                           "new_signing": pick["id"] in new_ids})
            formation = shape.get("formation") or formation
        else:
            for bucket, n in (("G", 1), ("D", 4), ("M", 4), ("F", 2)):
                for _ in range(n):
                    pick = take(bucket)
                    if pick:
                        xi.append({**pick, "grid": None, "slot_pos": bucket,
                                   "basis": "starts", "replaces": None,
                                   "new_signing": pick["id"] in new_ids})

        # Every arrival, with where they came from. A signing occasionally has
        # no roster entry at all - a returning loanee like Disasi is
        # contractually Chelsea's but appears in neither player endpoint until
        # he is re-registered. List him anyway, flagged, so the count here
        # always matches the In column on the transfers tab.
        by_pid = {p["id"]: p for p in players}
        arrivals = []
        for pid, t in arrivals_by_id.items():
            p = by_pid.get(pid)
            arrivals.append({
                **(p or {"id": pid, "name": t["player"].get("name"),
                         "photo": t["player"].get("logo"), "starts": 0,
                         "apps": 0, "minutes": 0, "rating": None,
                         "position": None}),
                "new_signing": True,
                "from_club": t["from"].get("name"),
                "signed": t.get("date"),
                "in_xi": pid in picked,
                "in_squad": p is not None,
            })
        arrivals.sort(key=lambda a: (a.get("signed") or ""), reverse=True)

        # The rest of the squad - a plain roster listing, not a predicted
        # bench. Guessing who sits on the bench adds nothing the XI does not
        # already say, so everyone outside the XI is simply listed, with
        # injured players flagged inline rather than split into their own
        # bucket. That keeps the arithmetic honest: XI + rest == squad size.
        rest = [{**p,
                 "new_signing": p["id"] in new_ids,
                 "in_squad": True,
                 "unavailable": injured[p["id"]].get("reason") if p["id"] in injured else None}
                for p in players if p["id"] not in picked]

        # A signing with no roster entry (an unregistered returning loanee)
        # still belongs in the squad list, flagged, rather than vanishing.
        seen = picked | {p["id"] for p in rest}
        for pid, t in arrivals_by_id.items():
            if pid in seen:
                continue
            rest.append({
                "id": pid, "name": t["player"].get("name"),
                "photo": t["player"].get("logo"), "position": None,
                "starts": 0, "apps": 0, "minutes": 0, "rating": None,
                "goals": 0, "assists": 0, "unavailable": None,
                "new_signing": True, "in_squad": False,
                "from_club": t["from"].get("name"),
            })

        rest.sort(key=lambda p: (-(p.get("starts") or 0), -(p.get("minutes") or 0)))

        return {
            "available": True,
            "club": {"id": team_id, "name": club["name"], "short": club["short"],
                     "colour": club["colour"], "logo": api.get("logo")},
            "season": _season_label(season),
            "formation": formation,
            "formation_usage": used[:3],
            "xi": xi,
            "squad": rest,
            "squad_total": len(xi) + len(rest),
            "unavailable_count": sum(1 for p in rest if p.get("unavailable")),
            "new_signings": len(new_ids),
            "arrivals": arrivals,
            "basis": ("most-used shape and recent XI" if shape
                      else "appearances only - no recent lineup published"),
        }

    async def probable_xi_generic(self, api_id: int) -> dict:
        """Same idea as probable_xi(), scaled down for a club outside the
        tracked registry: there is no local season, no synced squad snapshot
        and no transfer sweep to rank signings against, so this leans on the
        two things the API can give for any club - the current squad and its
        most recently published starting XI."""
        if not settings.is_live:
            return {"available": False, "reason": "no data for this club"}

        info = await af.team_info(api_id)
        if not info.get("name"):
            return {"available": False, "reason": "unknown club"}

        roster = await af.squad(api_id)
        if not roster:
            return {"available": False, "reason": "no squad data for this club"}

        shape = await af.recent_lineup_shape(api_id, None, None, count=6)
        by_id = {p["id"]: p for p in roster if p.get("id")}

        xi: list[dict] = []
        picked: set[int] = set()
        if shape and shape.get("slots"):
            for slot in shape["slots"]:
                pid = slot.get("id")
                base = by_id.get(pid, {})
                xi.append({
                    "id": pid, "name": base.get("name") or slot.get("name"),
                    "photo": base.get("photo"), "position": base.get("position"),
                    "number": base.get("number"),
                    "grid": slot.get("grid"), "slot_pos": slot.get("pos"),
                    "starts": None, "basis": "recent lineup",
                    "replaces": None, "new_signing": False,
                })
                if pid:
                    picked.add(pid)

        rest = [{**p, "starts": None, "new_signing": False, "in_squad": True,
                 "unavailable": None}
                for p in roster if p.get("id") not in picked]

        return {
            "available": True,
            "club": {"id": f"api-{api_id}", "name": info["name"], "short": info["name"],
                     "colour": "#7a8699", "logo": info.get("logo")},
            "season": None,
            "formation": shape.get("formation") if shape else None,
            "formation_usage": [],
            "xi": xi,
            "squad": rest,
            "squad_total": len(xi) + len(rest),
            "unavailable_count": 0,
            "new_signings": 0,
            "arrivals": [],
            "basis": ("most recently published lineup" if shape
                      else "squad list only - no recent lineup published"),
        }

    async def search(self, query: str) -> dict:
        q = _fold(query)
        if not q:
            return {"teams": [], "players": [], "leagues": []}

        teams = [{**c, "logo": (TEAM_IDS.get(c["id"]) or {}).get("logo")}
                 for c in CLUBS
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

    def _latest_signing(self, player_id: int) -> dict | None:
        """Where a player most recently moved TO, per the transfer store.

        Only trusted for the current window - an older record would be stale
        next to real appearance history.
        """
        since = window_start("season")
        best = None
        for row in self._merged_transfers(since):
            if row["player"].get("id") != player_id:
                continue
            if best is None or (row.get("date") or "") > (best.get("date") or ""):
                best = row
        if not best:
            return None
        dest = best["to"]
        club = CLUB_BY_ID.get(dest.get("id")) if dest.get("id") else None
        if not club and not dest.get("name"):
            return None
        return {
            "club": dest.get("id"),
            "club_name": club["short"] if club else dest.get("name"),
            "club_colour": club["colour"] if club else "#7a8699",
            "club_logo": dest.get("logo"),
        }

    async def _current_club(self, player_id: int) -> dict:
        """Most recent *club* for a player. National sides are skipped."""
        blank = {"club": None, "club_name": None, "club_colour": None}

        # A completed transfer beats appearance history. /players/teams only
        # lists seasons a player actually PLAYED, so between seasons a summer
        # signing still reads as their old club - Cucurella showed as Chelsea
        # for weeks after joining Real Madrid, because 2026-27 had not started.
        signing = self._latest_signing(player_id)
        if signing:
            return signing

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

        history = await self._career_by_competition(pid)
        return {
            "profile": profile,
            "current_club": club,
            "season": _season_label(season),
            "stats": stats,
            "totals": totals,
            "career": career,
            "competitions": history["competitions"],
            "seasons_covered": history["seasons"],
            "rankings": await self._league_rankings(pid, history["latest_by_league"]),
            "transfers": transfers[:20],
            "source": "apifootball",
            "simulated": False,
        }

    async def _career_by_competition(self, pid: int, max_seasons: int = 10) -> dict:
        """Season-by-season stats, grouped by competition.

        One upstream call per season, cached for a week, capped so a 15-season
        career does not cost 15 calls every time the page opens.
        """
        try:
            seasons = (await af.player_seasons(pid))[:max_seasons]
        except Exception:
            return {"competitions": [], "seasons": [], "latest_by_league": {}}

        buckets: dict[str, dict] = {}
        latest_by_league: dict[int, int] = {}
        for season in seasons:
            try:
                rows = await af.player_stats(pid, season)
            except Exception:
                continue
            for row in rows:
                name = row.get("league") or "Unknown"
                b = buckets.setdefault(name, {
                    "competition": name, "logo": row.get("league_logo"),
                    "country": row.get("country"), "seasons": [],
                    "apps": 0, "goals": 0, "assists": 0, "minutes": 0,
                    "yellow": 0, "red": 0, "_ratings": [],
                })
                b["seasons"].append({**row, "season": season,
                                     "season_label": _season_label(season)})
                for k in ("apps", "goals", "assists", "minutes", "yellow", "red"):
                    b[k] += row.get(k) or 0
                if row.get("rating"):
                    b["_ratings"].append(row["rating"])
                api_id = row.get("league_api_id")
                if api_id and season > latest_by_league.get(api_id, 0):
                    latest_by_league[api_id] = season

        out = []
        for b in buckets.values():
            ratings = b.pop("_ratings")
            b["rating"] = round(sum(ratings) / len(ratings), 2) if ratings else None
            b["seasons"].sort(key=lambda r: r["season"], reverse=True)
            b["span"] = (f"{b['seasons'][-1]['season_label']} – {b['seasons'][0]['season_label']}"
                         if len(b["seasons"]) > 1 else b["seasons"][0]["season_label"])
            out.append(b)
        out.sort(key=lambda b: (-b["apps"], b["competition"]))
        return {"competitions": out, "seasons": seasons,
                "latest_by_league": latest_by_league}

    async def _league_rankings(self, pid: int, latest_by_league: dict) -> list[dict]:
        """Where the player sits on a competition's leaderboards.

        Ranked against the published top-20 charts, so a player outside them
        simply has no rank - we do not invent one.
        """
        out = []
        for api_id, season in list(latest_by_league.items())[:6]:
            meta = next((lg for lg in LEAGUES if lg["api_id"] == api_id), None)
            if not meta:
                continue
            entry = {"league": meta["short"], "league_id": meta["id"],
                     "accent": meta["accent"], "season": _season_label(season)}
            try:
                scorers = await af.topscorers(api_id, season)
                hit = next((r for r in scorers if r["player_id"] == pid), None)
                if hit:
                    entry["goals_rank"] = hit["rank"]
                    entry["goals"] = hit["goals"]
                    entry["of"] = len(scorers)
            except Exception:
                pass
            try:
                assists = await af.topassists(api_id, season)
                hit = next((r for r in assists if r["player_id"] == pid), None)
                if hit:
                    entry["assists_rank"] = hit["rank"]
                    entry["assists"] = hit["assists"]
                    entry["of"] = entry.get("of") or len(assists)
            except Exception:
                pass
            if entry.get("goals_rank") or entry.get("assists_rank"):
                out.append(entry)
        return out

    async def league_fixtures(self, league_id: str, when: str = "next",
                              count: int = 20) -> dict:
        meta = LEAGUE_BY_ID.get(league_id)
        if not meta or not settings.is_live:
            return {"matches": [], "source": "unavailable"}
        season = current_season()
        rows = await af.league_fixtures(meta["api_id"], season, when, count)
        # Between seasons there are no results yet (and sometimes no fixtures
        # published), so fall back to the last completed campaign either way.
        fallback_season = None
        if not rows:
            fallback_season = season - 1
            rows = await af.league_fixtures(meta["api_id"], fallback_season, when, count)
        return {"matches": _tag(rows, "apifootball", False),
                "source": "apifootball", "simulated": False, "when": when,
                "season": _season_label(fallback_season or season),
                "note": (f"The {_season_label(season)} season has no "
                         f"{'results' if when == 'last' else 'fixtures'} yet - "
                         f"showing {_season_label(fallback_season)}."
                         if fallback_season else None)}


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


# Lineups say G/D/M/F; the players endpoint says Goalkeeper/Defender/
# Midfielder/Attacker. Taking the first letter silently turned every
# "Attacker" into a midfielder and left the striker slot to youth players.
_POS_WORDS = {
    "goalkeeper": "G", "keeper": "G", "gk": "G", "g": "G",
    "defender": "D", "defence": "D", "d": "D",
    "midfielder": "M", "midfield": "M", "m": "M",
    "attacker": "F", "forward": "F", "striker": "F", "f": "F",
}


def _pos_bucket(pos: str | None) -> str:
    if not pos:
        return "M"
    return _POS_WORDS.get(pos.strip().lower(), "M")


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
