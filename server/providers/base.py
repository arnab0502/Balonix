"""Provider protocol + the normalized shapes every provider must emit.

Adding a new data source means implementing this one class. Nothing above the
provider layer (routers, frontend) knows which source is in use.

Normalized shapes
-----------------
Match      {id, league, league_name, kickoff, status:{type,minute,label},
            home:{...Side}, away:{...Side}, venue, round, tickets:{...}}
Side       {id, name, short, tla, colour, score}
Event      {minute, type, team, player, assist, detail}
Standing   {rank, team, played, win, draw, loss, gf, ga, gd, points, form}
Transfer   {id, date, player:{...}, from:{...}, to:{...}, fee:{...},
            league, kind, status, source}
"""
from __future__ import annotations

from typing import Protocol


class FootballProvider(Protocol):
    name: str

    async def fixtures_by_date(self, day: str) -> list[dict]:
        """All big-5 matches kicking off on `day` (YYYY-MM-DD)."""

    async def live(self) -> list[dict]:
        """Every match currently in play. One upstream call, all leagues."""

    async def match(self, match_id: str) -> dict | None:
        """Full detail: events, lineups, stats, h2h."""

    async def standings(self, league_id: str) -> list[dict]: ...

    async def scorers(self, league_id: str) -> list[dict]: ...

    async def transfers(self, league_id: str | None, limit: int) -> list[dict]: ...

    async def team(self, team_id: str) -> dict | None:
        """Squad, recent form, upcoming fixtures."""

    async def search(self, query: str) -> dict: ...
