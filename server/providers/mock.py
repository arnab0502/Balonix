"""Seeded mock provider - a fully simulated big-5 season.

This is not random noise. It generates a real double round-robin schedule per
league, plays every fixture through a strength model, and derives standings,
form, scorers and transfers from those results. Everything is seeded, so the
same match always has the same score, lineup and events across restarts.

The season is anchored ~150 days behind today so that whenever you open the
app you get a plausible mid-season picture: matches played, matches live right
now, and fixtures still to come.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta, timezone

from ..data.clubs import CLUB_BY_ID, CLUBS, CLUBS_BY_LEAGUE
from ..data.leagues import LEAGUES, LEAGUE_BY_ID
from ..data.tickets import ticket_link

# --------------------------------------------------------------------------
# Club strength
# --------------------------------------------------------------------------
RATING: dict[str, int] = {
    # Premier League
    "man-city": 90, "liverpool": 90, "arsenal": 89, "newcastle": 83, "chelsea": 85,
    "aston-villa": 82, "man-united": 82, "tottenham": 81, "brighton": 79,
    "nottm-forest": 78, "bournemouth": 77, "crystal-palace": 77, "fulham": 76,
    "brentford": 75, "everton": 74, "west-ham": 74, "wolves": 71, "leeds": 71,
    "sunderland": 70, "burnley": 69,
    # LaLiga
    "real-madrid": 92, "barcelona": 90, "atletico": 86, "athletic": 81,
    "villarreal": 80, "betis": 78, "real-sociedad": 78, "sevilla": 75,
    "valencia": 74, "celta": 74, "osasuna": 73, "girona": 73, "rayo": 73,
    "mallorca": 72, "getafe": 72, "espanyol": 71, "alaves": 70, "elche": 68,
    "levante": 68, "oviedo": 67,
    # Serie A
    "inter": 88, "napoli": 86, "juventus": 84, "milan": 84, "atalanta": 84,
    "roma": 82, "lazio": 79, "fiorentina": 78, "bologna": 78, "como": 76,
    "torino": 73, "udinese": 72, "genoa": 71, "cagliari": 70, "parma": 70,
    "sassuolo": 69, "lecce": 68, "verona": 68, "pisa": 66, "cremonese": 66,
    # Bundesliga
    "bayern": 91, "leverkusen": 85, "dortmund": 84, "leipzig": 82,
    "frankfurt": 80, "stuttgart": 79, "freiburg": 77, "mainz": 75,
    "werder": 74, "gladbach": 74, "wolfsburg": 74, "hoffenheim": 73,
    "augsburg": 71, "union-berlin": 71, "koln": 70, "st-pauli": 69,
    "heidenheim": 69, "hsv": 69,
    # Ligue 1
    "psg": 91, "marseille": 83, "monaco": 82, "lille": 80, "lyon": 79,
    "nice": 77, "lens": 77, "strasbourg": 76, "rennes": 75, "brest": 73,
    "toulouse": 73, "nantes": 70, "auxerre": 70, "paris-fc": 69,
    "lorient": 68, "angers": 68, "le-havre": 68, "metz": 67,
}

# --------------------------------------------------------------------------
# Name pools, by league locale, for squad generation
# --------------------------------------------------------------------------
_FIRST = {
    "epl": ["Harry", "Jack", "Callum", "Reece", "Marcus", "Declan", "Ollie", "Kai",
            "Tyrone", "Ethan", "Lewis", "Jarrod", "Conor", "Aaron", "Finley",
            "Morgan", "Rhys", "Kobbie", "Jude", "Elliot", "Alfie", "Bukayo"],
    "laliga": ["Alvaro", "Sergio", "Pablo", "Javier", "Iker", "Marcos", "Nico",
               "Unai", "Dani", "Rodrigo", "Hugo", "Adrian", "Gerard", "Aitor",
               "Ander", "Bryan", "Joselu", "Fermin", "Lamine", "Ivan", "Oscar"],
    "seriea": ["Matteo", "Lorenzo", "Giacomo", "Federico", "Nicolo", "Andrea",
               "Davide", "Alessandro", "Riccardo", "Gianluca", "Simone",
               "Tommaso", "Samuele", "Cesare", "Filippo", "Mattia", "Luca"],
    "bundesliga": ["Leon", "Jonas", "Maximilian", "Florian", "Niklas", "Jamal",
                   "Lukas", "Tim", "Benedikt", "Marius", "Kevin", "Julian",
                   "Fabian", "Sven", "Moritz", "Karim", "Robin", "Dennis"],
    "isl": ["Sunil", "Rahul", "Sandesh", "Anirudh", "Lallianzuala", "Jeakson",
            "Liston", "Brandon", "Ashique", "Manvir", "Rahim", "Vikram",
            "Naorem", "Deepak", "Pritam", "Amrinder", "Gurpreet", "Nikhil"],
    "ligue1": ["Lucas", "Hugo", "Theo", "Maxence", "Enzo", "Bilal", "Nathan",
               "Amine", "Warren", "Ousmane", "Rayan", "Malo", "Quentin",
               "Ismael", "Yanis", "Adrien", "Kylian", "Bradley"],
}
_LAST = {
    "epl": ["Whitfield", "Barrowman", "Ashcroft", "Kentish", "Halloway", "Denby",
            "Marlowe", "Ridley", "Featherstone", "Cadogan", "Bramley", "Stanhope",
            "Ashworth", "Colborne", "Harkness", "Wren", "Tolliver", "Grimshaw"],
    "laliga": ["Serrano", "Bermudez", "Palencia", "Quintana", "Arribas", "Vidal",
               "Cardenas", "Nieto", "Zubiaurre", "Olmedo", "Renteria", "Bustos",
               "Aranda", "Villaverde", "Escudero", "Carrasco", "Peralta"],
    "seriea": ["Bellandi", "Moretti", "Ferraro", "Cassano", "Rinaldi", "Zanetti",
               "Locatelli", "Barbieri", "Grassi", "Silvestri", "Marchetti",
               "Vitali", "Pellegrino", "Fontana", "Ruggeri", "Baldini"],
    "bundesliga": ["Vollmer", "Brandhoff", "Kestner", "Reinhardt", "Lindemann",
                   "Osterloh", "Wagenknecht", "Siedler", "Hartmann", "Brenner",
                   "Kohlmann", "Neuhaus", "Steinbach", "Wendler", "Fritsch"],
    "isl": ["Chhetri", "Bheke", "Jhingan", "Thapa", "Singh", "Colaco",
            "Fernandes", "Kuruniyan", "Yadav", "Mandal", "Ali", "Pratap",
            "Krishna", "Sarkar", "Gill", "Kotal", "Nongdamba", "Rana"],
    "ligue1": ["Lavigne", "Marchand", "Boucher", "Delacroix", "Vidal", "Fournier",
               "Rousseau", "Mercier", "Chevalier", "Beaumont", "Guillard",
               "Perrin", "Thevenin", "Sarr", "Diakite", "Ferreira"],
}
_INTL_FIRST = ["Gabriel", "Rafael", "Matheus", "Joao", "Vinicius", "Emiliano",
               "Santiago", "Facundo", "Mohammed", "Yusuf", "Kwame", "Sadio",
               "Victor", "Alphonso", "Takumi", "Hwang", "Nikola", "Luka"]
_INTL_LAST = ["Silva", "Oliveira", "Nascimento", "Cardoso", "Alvarez", "Romero",
              "Fernandez", "Traore", "Diallo", "Osei", "Adeyemi", "Okafor",
              "Tanaka", "Petrovic", "Modric", "Kovacevic", "Haaland"]

_POSITIONS = ["GK"] + ["DF"] * 8 + ["MF"] * 8 + ["FW"] * 6
_FORMATIONS = ["4-3-3", "4-2-3-1", "3-4-2-1", "4-4-2", "3-5-2", "4-1-4-1"]
_NATIONS = {
    "epl": "England", "laliga": "Spain", "seriea": "Italy",
    "bundesliga": "Germany", "ligue1": "France", "isl": "India",
}
_INTL_NATIONS = ["Brazil", "Argentina", "Portugal", "Netherlands", "Belgium",
                 "Croatia", "Senegal", "Morocco", "Nigeria", "Japan", "Norway",
                 "Denmark", "Uruguay", "Colombia", "Ghana", "Sweden", "Serbia"]


def _rng(*parts) -> random.Random:
    """Deterministic RNG keyed on any tuple of values."""
    seed = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(seed[:16], 16))


def _rating(club_id: str) -> int:
    return RATING.get(club_id, 72)


# --------------------------------------------------------------------------
# Squads
# --------------------------------------------------------------------------
_SQUAD_CACHE: dict[str, list[dict]] = {}


def squad(club_id: str) -> list[dict]:
    if club_id in _SQUAD_CACHE:
        return _SQUAD_CACHE[club_id]
    club = CLUB_BY_ID[club_id]
    league = club["league"]
    rng = _rng("squad", club_id)
    players: list[dict] = []
    used: set[str] = set()
    for i in range(23):
        for _ in range(12):
            if rng.random() < 0.62:
                first = _FIRST.get(league) or _INTL_FIRST
                last = _LAST.get(league) or _INTL_LAST
                name = f"{rng.choice(first)} {rng.choice(last)}"
                nation = _NATIONS.get(league) or rng.choice(_INTL_NATIONS)
            else:
                name = f"{rng.choice(_INTL_FIRST)} {rng.choice(_INTL_LAST)}"
                nation = rng.choice(_INTL_NATIONS)
            if name not in used:
                break
        used.add(name)
        pos = _POSITIONS[i % len(_POSITIONS)]
        players.append(
            {
                "id": f"{club_id}-p{i}",
                "name": name,
                "number": i + 1,
                "position": pos,
                "age": rng.randint(18, 35),
                "nationality": nation,
                "club": club_id,
                "rating_base": _rating(club_id) + rng.randint(-6, 6),
                "market_value": _market_value(rng, _rating(club_id), pos),
            }
        )
    _SQUAD_CACHE[club_id] = players
    return players


def _market_value(rng: random.Random, club_rating: int, pos: str) -> int:
    base = max(1, (club_rating - 60) ** 2 * 0.22)
    pos_mult = {"GK": 0.55, "DF": 0.8, "MF": 1.05, "FW": 1.35}[pos]
    val = base * pos_mult * rng.uniform(0.35, 2.4)
    return int(round(val, 0) * 1_000_000)


# --------------------------------------------------------------------------
# Schedule
# --------------------------------------------------------------------------
def _season_start() -> date:
    """Anchor the simulated season ~150 days back, on a Saturday."""
    anchor = date.today() - timedelta(days=150)
    return anchor - timedelta(days=(anchor.weekday() - 5) % 7)


def _round_robin(teams: list[str]) -> list[list[tuple[str, str]]]:
    """Circle method. Returns first-half rounds; second half is the mirror."""
    ts = list(teams)
    if len(ts) % 2:
        ts.append("__bye__")
    n = len(ts)
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = ts[i], ts[n - 1 - i]
            if "__bye__" in (a, b):
                continue
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        ts = [ts[0]] + [ts[-1]] + ts[1:-1]
    return rounds


_SCHEDULE_CACHE: dict[str, list[dict]] = {}


def schedule(league_id: str) -> list[dict]:
    """Every fixture of the simulated season for one league, kickoff-sorted."""
    if league_id in _SCHEDULE_CACHE:
        return _SCHEDULE_CACHE[league_id]

    clubs = [c["id"] for c in CLUBS_BY_LEAGUE[league_id]]
    rng = _rng("schedule", league_id)
    rng.shuffle(clubs)
    first = _round_robin(clubs)
    second = [[(b, a) for a, b in rnd] for rnd in first]
    all_rounds = first + second

    start = _season_start()
    # Offsets are days from the Saturday anchor: Friday night through Monday
    # night, the way a real matchweek is actually spread.
    slots = [
        (-1, 19, 30),           # Friday night
        (0, 11, 30), (0, 14, 0), (0, 14, 0), (0, 16, 30),   # Saturday
        (1, 13, 0), (1, 15, 15), (1, 17, 45),               # Sunday
        (2, 19, 45),            # Monday night
    ]

    fixtures: list[dict] = []
    for md, pairs in enumerate(all_rounds):
        week = start + timedelta(days=7 * md)
        for idx, (offset, hh, mm) in ((i, slots[i % len(slots)]) for i in range(len(pairs))):
            home, away = pairs[idx]
            kickoff = datetime.combine(
                week + timedelta(days=offset), datetime.min.time()
            ).replace(hour=hh, minute=mm, tzinfo=timezone.utc)
            fixtures.append(
                {
                    "id": f"{league_id}-{md + 1}-{home}-{away}",
                    "league": league_id,
                    "round": md + 1,
                    "home_id": home,
                    "away_id": away,
                    "kickoff": kickoff,
                }
            )
    fixtures.sort(key=lambda f: f["kickoff"])
    _SCHEDULE_CACHE[league_id] = fixtures
    return fixtures


def _all_fixtures() -> list[dict]:
    out: list[dict] = []
    for lg in LEAGUES:
        out.extend(schedule(lg["id"]))
    return out


# --------------------------------------------------------------------------
# Result simulation
# --------------------------------------------------------------------------
def _goal_minutes(rng: random.Random, n: int) -> list[int]:
    mins = sorted(rng.randint(2, 94) for _ in range(n))
    # nudge duplicates apart so the timeline reads cleanly
    for i in range(1, len(mins)):
        if mins[i] <= mins[i - 1]:
            mins[i] = min(95, mins[i - 1] + 1)
    return mins


def simulate(fixture: dict) -> dict:
    """Final score + timed events for a fixture. Stable for a given fixture id."""
    rng = _rng("result", fixture["id"])
    hr, ar = _rating(fixture["home_id"]), _rating(fixture["away_id"])
    edge = (hr - ar) / 10.0 + 0.35  # home advantage

    lam_h = max(0.25, 1.35 + edge * 0.42)
    lam_a = max(0.25, 1.35 - edge * 0.42)

    def poisson(lam: float) -> int:
        # Knuth
        import math

        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return min(k, 7)
            k += 1

    hg, ag = poisson(lam_h), poisson(lam_a)

    h_squad, a_squad = squad(fixture["home_id"]), squad(fixture["away_id"])
    h_attack = [p for p in h_squad[:16] if p["position"] in ("FW", "MF")]
    a_attack = [p for p in a_squad[:16] if p["position"] in ("FW", "MF")]

    events: list[dict] = []
    for side, count, pool, team_id in (
        ("home", hg, h_attack, fixture["home_id"]),
        ("away", ag, a_attack, fixture["away_id"]),
    ):
        for minute in _goal_minutes(rng, count):
            scorer = rng.choice(pool)
            assist = rng.choice([p for p in pool if p["id"] != scorer["id"]] or pool)
            detail = "Penalty" if rng.random() < 0.11 else "Normal Goal"
            events.append(
                {
                    "minute": minute,
                    "type": "goal",
                    "side": side,
                    "team": team_id,
                    "player": scorer["name"],
                    "player_id": scorer["id"],
                    "assist": None if detail == "Penalty" else assist["name"],
                    "detail": detail,
                }
            )

    for side, sq, team_id in (("home", h_squad, fixture["home_id"]),
                              ("away", a_squad, fixture["away_id"])):
        for _ in range(rng.randint(0, 3)):
            p = rng.choice(sq[:14])
            events.append({
                "minute": rng.randint(12, 90), "type": "card", "side": side,
                "team": team_id, "player": p["name"], "player_id": p["id"],
                "assist": None,
                "detail": "Red Card" if rng.random() < 0.08 else "Yellow Card",
            })
        for _ in range(3):
            off, on = rng.choice(sq[:11]), rng.choice(sq[11:])
            events.append({
                "minute": rng.randint(55, 88), "type": "subst", "side": side,
                "team": team_id, "player": on["name"], "player_id": on["id"],
                "assist": off["name"], "detail": "Substitution",
            })

    events.sort(key=lambda e: e["minute"])

    poss_h = max(28, min(72, int(50 + edge * 5 + rng.randint(-7, 7))))
    stats = {
        "possession": [poss_h, 100 - poss_h],
        "shots": [hg * 3 + rng.randint(2, 9), ag * 3 + rng.randint(2, 9)],
        "shots_on_target": [hg + rng.randint(1, 4), ag + rng.randint(1, 4)],
        "corners": [rng.randint(2, 11), rng.randint(2, 11)],
        "fouls": [rng.randint(6, 17), rng.randint(6, 17)],
        "offsides": [rng.randint(0, 5), rng.randint(0, 5)],
        "xg": [round(hg * 0.8 + rng.uniform(0.2, 1.1), 2),
               round(ag * 0.8 + rng.uniform(0.2, 1.1), 2)],
        "pass_accuracy": [rng.randint(74, 92), rng.randint(74, 92)],
    }
    return {"home_goals": hg, "away_goals": ag, "events": events, "stats": stats}


# --------------------------------------------------------------------------
# Status from wall clock
# --------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status(kickoff: datetime) -> dict:
    now = _now()
    elapsed = (now - kickoff).total_seconds() / 60.0
    if elapsed < 0:
        return {"type": "scheduled", "minute": None,
                "label": kickoff.strftime("%H:%M")}
    if elapsed < 45:
        return {"type": "live", "minute": max(1, int(elapsed)),
                "label": f"{max(1, int(elapsed))}'"}
    if elapsed < 60:
        return {"type": "live", "minute": 45, "label": "HT"}
    if elapsed < 105:
        m = int(45 + (elapsed - 60))
        return {"type": "live", "minute": m, "label": f"{m}'"}
    if elapsed < 112:
        return {"type": "live", "minute": 90, "label": "90+"}
    return {"type": "finished", "minute": 90, "label": "FT"}


def _visible_score(sim: dict, status: dict) -> tuple[int, int]:
    if status["type"] == "scheduled":
        return 0, 0
    if status["type"] == "finished":
        return sim["home_goals"], sim["away_goals"]
    minute = status["minute"] or 0
    h = sum(1 for e in sim["events"] if e["type"] == "goal" and e["side"] == "home" and e["minute"] <= minute)
    a = sum(1 for e in sim["events"] if e["type"] == "goal" and e["side"] == "away" and e["minute"] <= minute)
    return h, a


def _side(club_id: str, score: int) -> dict:
    c = CLUB_BY_ID[club_id]
    return {"id": c["id"], "name": c["name"], "short": c["short"], "tla": c["tla"],
            "colour": c["colour"], "score": score}


def _to_match(fixture: dict, *, detail: bool = False) -> dict:
    sim = simulate(fixture)
    status = _status(fixture["kickoff"])
    hs, as_ = _visible_score(sim, status)
    home, away = CLUB_BY_ID[fixture["home_id"]], CLUB_BY_ID[fixture["away_id"]]
    league = LEAGUE_BY_ID[fixture["league"]]

    match = {
        "id": fixture["id"],
        "league": fixture["league"],
        "league_name": league["name"],
        "league_accent": league["accent"],
        "round": f"Matchday {fixture['round']}",
        "kickoff": fixture["kickoff"].isoformat(),
        "status": status,
        "home": _side(fixture["home_id"], hs),
        "away": _side(fixture["away_id"], as_),
        "venue": home["stadium"],
        "tickets": ticket_link(home["name"], fixture["league"], venue=home["stadium"]),
    }
    if not detail:
        return match

    minute = 200 if status["type"] == "finished" else (status["minute"] or 0)
    shown = [e for e in sim["events"] if e["minute"] <= minute] \
        if status["type"] != "scheduled" else []
    match["events"] = shown
    match["stats"] = None if status["type"] == "scheduled" else sim["stats"]
    match["lineups"] = {
        "home": _lineup(fixture["home_id"], fixture["id"]),
        "away": _lineup(fixture["away_id"], fixture["id"]),
    }
    match["h2h"] = _h2h(fixture["home_id"], fixture["away_id"], exclude=fixture["id"])
    match["form"] = {
        "home": _form(fixture["home_id"], before=fixture["kickoff"]),
        "away": _form(fixture["away_id"], before=fixture["kickoff"]),
    }
    return match


def _lineup(club_id: str, match_id: str) -> dict:
    rng = _rng("lineup", club_id, match_id)
    sq = squad(club_id)
    club = CLUB_BY_ID[club_id]
    return {
        "team": club["short"],
        "colour": club["colour"],
        "formation": rng.choice(_FORMATIONS),
        "coach": f"{rng.choice(_FIRST.get(club['league']) or _INTL_FIRST)} "
                 f"{rng.choice(_LAST.get(club['league']) or _INTL_LAST)}",
        "starters": [
            {**{k: p[k] for k in ("id", "name", "number", "position")},
             "rating": round(min(9.8, max(5.2, p["rating_base"] / 11 + rng.uniform(-0.9, 1.4))), 1)}
            for p in sq[:11]
        ],
        "bench": [{k: p[k] for k in ("id", "name", "number", "position")} for p in sq[11:19]],
    }


def _played_before(club_id: str, before: datetime | None = None) -> list[dict]:
    league = CLUB_BY_ID[club_id]["league"]
    cutoff = before or _now()
    out = []
    for f in schedule(league):
        if f["kickoff"] >= cutoff:
            continue
        if club_id not in (f["home_id"], f["away_id"]):
            continue
        out.append(f)
    return out


def _form(club_id: str, before: datetime | None = None, n: int = 5) -> str:
    letters = []
    for f in _played_before(club_id, before)[-n:]:
        sim = simulate(f)
        h, a = sim["home_goals"], sim["away_goals"]
        is_home = f["home_id"] == club_id
        mine, theirs = (h, a) if is_home else (a, h)
        letters.append("W" if mine > theirs else "D" if mine == theirs else "L")
    return "".join(letters)


def _h2h(a: str, b: str, exclude: str | None = None, n: int = 5) -> list[dict]:
    league = CLUB_BY_ID[a]["league"]
    out = []
    for f in schedule(league):
        if f["id"] == exclude or f["kickoff"] >= _now():
            continue
        if {f["home_id"], f["away_id"]} != {a, b}:
            continue
        sim = simulate(f)
        out.append({
            "id": f["id"],
            "date": f["kickoff"].date().isoformat(),
            "home": CLUB_BY_ID[f["home_id"]]["short"],
            "away": CLUB_BY_ID[f["away_id"]]["short"],
            "score": f"{sim['home_goals']}-{sim['away_goals']}",
        })
    return out[-n:]


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
_TRANSFER_KINDS = [
    ("transfer", 0.52), ("loan", 0.24), ("free", 0.14), ("end_of_loan", 0.10),
]


def _fee_label(kind: str, amount: int) -> str:
    if kind == "free":
        return "Free transfer"
    if kind == "end_of_loan":
        return "End of loan"
    if kind == "loan":
        return "Loan" if amount == 0 else f"Loan fee EUR {amount / 1e6:.1f}m"
    if amount >= 1_000_000:
        return f"EUR {amount / 1e6:.1f}m"
    return "Undisclosed"


_TRANSFER_CACHE: list[dict] | None = None


def all_transfers() -> list[dict]:
    """A rolling window of completed + rumoured moves across the big five."""
    global _TRANSFER_CACHE
    if _TRANSFER_CACHE is not None:
        return _TRANSFER_CACHE

    rng = _rng("transfers", _season_start().isoformat())
    today = date.today()
    out: list[dict] = []

    for i in range(320):
        to_club = CLUB_BY_ID[rng.choice([c["id"] for c in CLUBS])]
        # 70% of incoming business comes from another big-5 club, else "abroad"
        if rng.random() < 0.70:
            from_club = CLUB_BY_ID[rng.choice([c["id"] for c in CLUBS if c["id"] != to_club["id"]])]
            from_name, from_league = from_club["name"], from_club["league"]
            from_id = from_club["id"]
        else:
            from_name = rng.choice([
                "Ajax", "Benfica", "Porto", "Sporting CP", "Feyenoord", "Club Brugge",
                "Celtic", "Rangers", "Galatasaray", "Fenerbahce", "Shakhtar Donetsk",
                "Red Bull Salzburg", "River Plate", "Boca Juniors", "Palmeiras",
                "Flamengo", "Santos", "Al Hilal", "Al Nassr", "Inter Miami",
                "LAFC", "Dinamo Zagreb", "PSV", "AZ Alkmaar", "Olympiacos",
            ])
            from_league, from_id = None, None

        pool = squad(to_club["id"])
        player = rng.choice(pool)

        kind = rng.choices([k for k, _ in _TRANSFER_KINDS],
                           weights=[w for _, w in _TRANSFER_KINDS])[0]
        if kind in ("free", "end_of_loan"):
            amount = 0
        elif kind == "loan":
            amount = 0 if rng.random() < 0.55 else rng.randrange(1, 12) * 1_000_000
        else:
            base = player["market_value"]
            amount = int(base * rng.uniform(0.6, 1.9) / 500_000) * 500_000

        # Spread across the last 75 days and the next 20 (rumours ahead of time)
        offset = rng.randint(-75, 20)
        when = today + timedelta(days=offset)
        status = "done" if offset <= 0 else "rumour"
        if status == "done" and rng.random() < 0.12:
            status = "rumour"

        out.append({
            "id": f"tr-{i}",
            "date": when.isoformat(),
            "player": {
                "id": player["id"],
                "name": player["name"],
                "position": player["position"],
                "age": player["age"],
                "nationality": player["nationality"],
                "market_value": player["market_value"],
            },
            "from": {"id": from_id, "name": from_name, "league": from_league},
            "to": {"id": to_club["id"], "name": to_club["name"], "league": to_club["league"]},
            "league": to_club["league"],
            "fee": {"amount": amount, "label": _fee_label(kind, amount), "kind": kind},
            "status": status,
            "source": rng.choice(["Club statement", "Fabrizio Romano", "Sky Sport",
                                  "L'Equipe", "Marca", "Bild", "The Athletic",
                                  "Gazzetta dello Sport", "Relevo"]),
        })

    out.sort(key=lambda t: (t["date"], t["fee"]["amount"]), reverse=True)
    _TRANSFER_CACHE = out
    return out


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------
class MockProvider:
    name = "mock"

    async def fixtures_by_date(self, day: str) -> list[dict]:
        target = date.fromisoformat(day)
        out = [_to_match(f) for f in _all_fixtures() if f["kickoff"].date() == target]
        out.sort(key=lambda m: (m["kickoff"], m["league"]))
        return out

    async def live(self) -> list[dict]:
        out = []
        for f in _all_fixtures():
            st = _status(f["kickoff"])
            if st["type"] == "live":
                out.append(_to_match(f))
        out.sort(key=lambda m: m["kickoff"])
        return out

    async def match(self, match_id: str) -> dict | None:
        for f in _all_fixtures():
            if f["id"] == match_id:
                return _to_match(f, detail=True)
        return None

    async def standings(self, league_id: str) -> list[dict]:
        table: dict[str, dict] = {}
        for c in CLUBS_BY_LEAGUE[league_id]:
            table[c["id"]] = {
                "team": {"id": c["id"], "name": c["name"], "short": c["short"],
                         "tla": c["tla"], "colour": c["colour"]},
                "played": 0, "win": 0, "draw": 0, "loss": 0,
                "gf": 0, "ga": 0, "points": 0, "form": "",
            }
        now = _now()
        for f in schedule(league_id):
            if f["kickoff"] >= now:
                continue
            st = _status(f["kickoff"])
            if st["type"] != "finished":
                continue
            sim = simulate(f)
            h, a = sim["home_goals"], sim["away_goals"]
            for club_id, gf, ga in ((f["home_id"], h, a), (f["away_id"], a, h)):
                row = table[club_id]
                row["played"] += 1
                row["gf"] += gf
                row["ga"] += ga
                if gf > ga:
                    row["win"] += 1
                    row["points"] += 3
                elif gf == ga:
                    row["draw"] += 1
                    row["points"] += 1
                else:
                    row["loss"] += 1

        rows = list(table.values())
        for row in rows:
            row["gd"] = row["gf"] - row["ga"]
            row["form"] = _form(row["team"]["id"])
        rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"]["name"]))
        for i, row in enumerate(rows, 1):
            row["rank"] = i
        return rows

    async def scorers(self, league_id: str) -> list[dict]:
        tally: dict[str, dict] = {}
        now = _now()
        for f in schedule(league_id):
            if f["kickoff"] >= now:
                continue
            st = _status(f["kickoff"])
            sim = simulate(f)
            minute = 200 if st["type"] == "finished" else (st["minute"] or 0)
            if st["type"] == "scheduled":
                continue
            for e in sim["events"]:
                if e["type"] != "goal" or e["minute"] > minute:
                    continue
                rec = tally.setdefault(e["player_id"], {
                    "player": e["player"], "player_id": e["player_id"],
                    "team": CLUB_BY_ID[e["team"]]["short"],
                    "team_id": e["team"], "colour": CLUB_BY_ID[e["team"]]["colour"],
                    "goals": 0, "assists": 0, "penalties": 0,
                })
                rec["goals"] += 1
                if e["detail"] == "Penalty":
                    rec["penalties"] += 1
                if e["assist"]:
                    a = tally.setdefault(f"assist-{e['assist']}", {
                        "player": e["assist"], "player_id": f"assist-{e['assist']}",
                        "team": CLUB_BY_ID[e["team"]]["short"],
                        "team_id": e["team"], "colour": CLUB_BY_ID[e["team"]]["colour"],
                        "goals": 0, "assists": 0, "penalties": 0,
                    })
                    a["assists"] += 1
        rows = [r for r in tally.values() if r["goals"] > 0]
        rows.sort(key=lambda r: (-r["goals"], -r["assists"], r["player"]))
        for i, r in enumerate(rows[:30], 1):
            r["rank"] = i
        return rows[:30]

    async def transfers(self, league_id: str | None, limit: int) -> list[dict]:
        rows = all_transfers()
        if league_id:
            rows = [t for t in rows
                    if t["to"]["league"] == league_id or t["from"]["league"] == league_id]
        return rows[:limit]

    async def team(self, team_id: str) -> dict | None:
        club = CLUB_BY_ID.get(team_id)
        if not club:
            return None
        now = _now()
        fixtures = [f for f in schedule(club["league"])
                    if team_id in (f["home_id"], f["away_id"])]
        recent = [_to_match(f) for f in fixtures if f["kickoff"] < now][-6:]
        upcoming = [_to_match(f) for f in fixtures if f["kickoff"] >= now][:6]
        table = await self.standings(club["league"])
        row = next((r for r in table if r["team"]["id"] == team_id), None)
        return {
            "club": club,
            "league": LEAGUE_BY_ID[club["league"]],
            "standing": row,
            "form": _form(team_id),
            "squad": squad(team_id),
            "recent": list(reversed(recent)),
            "upcoming": upcoming,
            "transfers": [t for t in all_transfers()
                          if t["to"]["id"] == team_id or t["from"]["id"] == team_id][:12],
            "tickets": ticket_link(club["name"], club["league"], venue=club["stadium"]),
        }

    async def search(self, query: str) -> dict:
        q = query.strip().lower()
        if not q:
            return {"teams": [], "players": [], "leagues": []}
        teams = [c for c in CLUBS if q in c["name"].lower() or q in c["short"].lower()][:8]
        leagues = [lg for lg in LEAGUES if q in lg["name"].lower()][:5]
        players: list[dict] = []
        for c in teams[:4] or CLUBS[:12]:
            for p in squad(c["id"]):
                if q in p["name"].lower():
                    players.append({**p, "club_name": c["short"]})
                if len(players) >= 8:
                    break
        return {"teams": teams, "players": players[:8], "leagues": leagues}
