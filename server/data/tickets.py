"""Resolve a fixture to an official ticketing destination.

Rules, in order:
  1. Home club's own ticketing page (always preferred - it is the box office).
  2. Neutral-venue / cup-final override, if the fixture is flagged as such.
  3. League-wide ticket portal for the competition.
  4. A site-scoped web search for the club's ticket page, so the link is never
     dead - the user lands on a search that surfaces the real box office.

We deliberately never emit resale/secondary-market links.
"""
from __future__ import annotations

from urllib.parse import quote_plus

from .clubs import CLUB_BY_ID, resolve as resolve_club
from .leagues import LEAGUE_BY_ID


def _search_fallback(club_name: str) -> str:
    return "https://duckduckgo.com/?q=" + quote_plus(f"{club_name} official tickets buy")


def ticket_link(home_team: str | None, league_id: str | None = None, *, venue: str | None = None) -> dict:
    """Return {url, label, source, confidence} for a fixture's home side."""
    club = resolve_club(home_team)

    if club and club.get("ticket_url"):
        # If the match is played away from the club's usual ground (neutral
        # venue, temporary stadium), the club box office is still the right
        # seller, so we keep the link but flag the venue mismatch.
        neutral = bool(venue and club["stadium"] and _loose(venue) != _loose(club["stadium"]))
        return {
            "url": club["ticket_url"],
            "label": f"Tickets - {club['short']}",
            "source": "club",
            "venue": venue or club["stadium"],
            "neutral_venue": neutral,
            "confidence": "high",
        }

    if club:
        # Known club, but we have no trustworthy box-office URL for it (its
        # domain is parked or dead). A scoped search beats a parked page.
        return {
            "url": _search_fallback(club["name"]),
            "label": f"Find tickets - {club['short']}",
            "source": "search", "venue": venue or club["stadium"],
            "neutral_venue": False, "confidence": "low",
        }

    league = LEAGUE_BY_ID.get(league_id or "")
    if league and league.get("tickets"):
        return {
            "url": league["tickets"],
            "label": f"Tickets - {league['short']}",
            "source": "league",
            "venue": venue,
            "neutral_venue": False,
            "confidence": "medium",
        }

    name = home_team or "football"
    return {
        "url": _search_fallback(name),
        "label": f"Find tickets - {name}",
        "source": "search",
        "venue": venue,
        "neutral_venue": False,
        "confidence": "low",
    }


def _loose(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def club_ticket_url(club_id: str) -> str | None:
    club = CLUB_BY_ID.get(club_id)
    return club["ticket_url"] if club else None
