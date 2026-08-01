"""Static league metadata for the big five.

`api_id` values are API-Football league ids and are stable across seasons.
"""
from __future__ import annotations

LEAGUES: list[dict] = [
    {
        "id": "epl",
        "api_id": 39,
        "name": "Premier League",
        "short": "Premier League",
        "country": "England",
        "flag": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
        "accent": "#38f08a",
        "tickets": "https://www.premierleague.com/tickets",
    },
    {
        "id": "laliga",
        "api_id": 140,
        "name": "LaLiga",
        "short": "LaLiga",
        "country": "Spain",
        "flag": "\U0001F1EA\U0001F1F8",
        "accent": "#ff6b3d",
        "tickets": "https://www.laliga.com/en-GB/tickets",
    },
    {
        "id": "seriea",
        "api_id": 135,
        "name": "Serie A",
        "short": "Serie A",
        "country": "Italy",
        "flag": "\U0001F1EE\U0001F1F9",
        "accent": "#3d8bff",
        "tickets": "https://www.legaseriea.it/en/tickets",
    },
    {
        "id": "bundesliga",
        "api_id": 78,
        "name": "Bundesliga",
        "short": "Bundesliga",
        "country": "Germany",
        "flag": "\U0001F1E9\U0001F1EA",
        "accent": "#ff3d5e",
        "tickets": "https://www.bundesliga.com/en/bundesliga/tickets",
    },
    {
        "id": "isl",
        "api_id": 323,
        "name": "Indian Super League",
        "short": "ISL",
        "country": "India",
        "flag": "\U0001F1EE\U0001F1F3",
        "accent": "#ff9d3d",
        "tickets": "https://www.indiansuperleague.com/tickets",
    },
    {
        "id": "ligue1",
        "api_id": 61,
        "name": "Ligue 1",
        "short": "Ligue 1",
        "country": "France",
        "flag": "\U0001F1EB\U0001F1F7",
        "accent": "#c47bff",
        "tickets": "https://www.ligue1.com/tickets",
    },
]

LEAGUE_BY_ID = {lg["id"]: lg for lg in LEAGUES}
LEAGUE_BY_API_ID = {lg["api_id"]: lg for lg in LEAGUES}
LEAGUE_IDS = [lg["id"] for lg in LEAGUES]


def current_season() -> int:
    """European season start year (a season runs Aug -> May)."""
    from datetime import date

    today = date.today()
    return today.year if today.month >= 7 else today.year - 1
