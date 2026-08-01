"""Club registry for the big five leagues (2026-27) with official ticketing links.

Each entry: (slug, name, short, tla, stadium, primary colour, official ticket URL)

The ticket URLs point at each club's own ticketing section - never a resale or
affiliate site. Clubs restructure their sites occasionally, so `ticket_url` is
best-effort and `TicketLink.confidence` tells the UI how much to trust it.
Anything that 404s falls back to a site-scoped search (see tickets.py).
"""
from __future__ import annotations

# fmt: off
_RAW: dict[str, list[tuple]] = {
    "epl": [
        ("arsenal",        "Arsenal",                  "Arsenal",      "ARS", "Emirates Stadium",        "#EF0107", "https://www.arsenal.com/tickets"),
        ("aston-villa",    "Aston Villa",              "Villa",        "AVL", "Villa Park",              "#95BFE5", "https://www.avfc.co.uk/tickets"),
        ("bournemouth",    "AFC Bournemouth",          "Bournemouth",  "BOU", "Vitality Stadium",        "#DA291C", "https://www.afcb.co.uk/tickets"),
        ("brentford",      "Brentford",                "Brentford",    "BRE", "Gtech Community Stadium", "#E30613", "https://www.brentfordfc.com/ticketing"),
        ("brighton",       "Brighton & Hove Albion",   "Brighton",     "BHA", "Amex Stadium",            "#0057B8", "https://www.brightonandhovealbion.com/tickets"),
        ("chelsea",        "Chelsea",                  "Chelsea",      "CHE", "Stamford Bridge",         "#034694", "https://www.chelseafc.com/tickets"),
        ("crystal-palace", "Crystal Palace",           "Palace",       "CRY", "Selhurst Park",           "#1B458F", "https://www.cpfc.co.uk/tickets"),
        ("everton",        "Everton",                  "Everton",      "EVE", "Hill Dickinson Stadium",  "#003399", "https://www.evertonfc.com/tickets"),
        ("fulham",         "Fulham",                   "Fulham",       "FUL", "Craven Cottage",          "#000000", "https://www.fulhamfc.com/tickets"),
        ("leeds",          "Leeds United",             "Leeds",        "LEE", "Elland Road",             "#FFCD00", "https://www.leedsunited.com"),
        ("liverpool",      "Liverpool",                "Liverpool",    "LIV", "Anfield",                 "#C8102E", "https://www.liverpoolfc.com/tickets"),
        ("man-city",       "Manchester City",          "Man City",     "MCI", "Etihad Stadium",          "#6CABDD", "https://www.mancity.com/tickets"),
        ("man-united",     "Manchester United",        "Man United",   "MUN", "Old Trafford",            "#DA291C", "https://www.manutd.com"),
        ("newcastle",      "Newcastle United",         "Newcastle",    "NEW", "St James' Park",          "#241F20", "https://www.nufc.co.uk/tickets"),
        ("nottm-forest",   "Nottingham Forest",        "Forest",       "NFO", "The City Ground",         "#DD0000", "https://www.nottinghamforest.co.uk/tickets"),
        ("sunderland",     "Sunderland",               "Sunderland",   "SUN", "Stadium of Light",        "#EB172B", "https://www.safc.com/tickets"),
        ("tottenham",      "Tottenham Hotspur",        "Spurs",        "TOT", "Tottenham Hotspur Stadium","#132257","https://www.tottenhamhotspur.com/tickets"),
        ("coventry",        "Coventry City",              "Coventry",      "COV", "Coventry Building Society Arena", "#78D0F3", "https://www.ccfc.co.uk/tickets"),
        ("hull",            "Hull City",                  "Hull City",     "HUL", "MKM Stadium",               "#F5971D", ""),
        ("ipswich",         "Ipswich Town",               "Ipswich",       "IPS", "Portman Road",              "#0044A9", "https://www.itfc.co.uk/tickets"),
    ],
    "laliga": [
        ("alaves",         "Deportivo Alaves",         "Alaves",       "ALA", "Mendizorroza",            "#0761AF", "https://www.deportivoalaves.com/entradas"),
        ("athletic",       "Athletic Club",            "Athletic",     "ATH", "San Mames",               "#EE2523", "https://www.athletic-club.eus/entradas"),
        ("atletico",       "Atletico Madrid",          "Atletico",     "ATM", "Riyadh Air Metropolitano","#CB3524", "https://www.atleticodemadrid.com/entradas"),
        ("barcelona",      "FC Barcelona",             "Barcelona",    "BAR", "Spotify Camp Nou",        "#A50044", "https://www.fcbarcelona.com/en/tickets"),
        ("celta",          "Celta Vigo",               "Celta",        "CEL", "Balaidos",                "#8AC3EE", "https://rccelta.es/entradas"),
        ("elche",          "Elche CF",                 "Elche",        "ELC", "Martinez Valero",         "#00913F", "https://elchecf.es/entradas"),
        ("espanyol",       "RCD Espanyol",             "Espanyol",     "ESP", "RCDE Stadium",            "#0072BC", "https://www.rcdespanyol.com/entradas"),
        ("getafe",         "Getafe CF",                "Getafe",       "GET", "Coliseum",                "#005999", "https://www.getafecf.com/entradas"),
        ("levante",        "Levante UD",               "Levante",      "LEV", "Ciutat de Valencia",      "#0053A0", "https://ticketing.levanteud.com/es"),
        ("osasuna",        "CA Osasuna",               "Osasuna",      "OSA", "El Sadar",                "#D91A21", "https://www.osasuna.es/entradas"),
        ("rayo",           "Rayo Vallecano",           "Rayo",         "RAY", "Vallecas",                "#E53027", "https://www.rayovallecano.es/entradas"),
        ("betis",          "Real Betis",               "Betis",        "BET", "Benito Villamarin",       "#00954C", "https://www.realbetisbalompie.es/entradas"),
        ("real-madrid",    "Real Madrid",              "Real Madrid",  "RMA", "Santiago Bernabeu",       "#FEBE10", "https://www.realmadrid.com/en/tickets"),
        ("real-sociedad",  "Real Sociedad",            "Sociedad",     "RSO", "Reale Arena",             "#0067B1", "https://www.realsociedad.eus/es/entradas"),
        ("sevilla",        "Sevilla FC",               "Sevilla",      "SEV", "Ramon Sanchez-Pizjuan",   "#D80027", "https://entradas.sevillafc.es"),
        ("valencia",       "Valencia CF",              "Valencia",     "VAL", "Mestalla",                "#EE3524", "https://www.valenciacf.com/entradas"),
        ("villarreal",     "Villarreal CF",            "Villarreal",   "VIL", "Estadio de la Ceramica",  "#FFE667", "https://www.villarrealcf.es/entradas"),
        ("malaga",          "Malaga CF",                  "Malaga",        "MAL", "La Rosaleda",               "#0072CE", "https://www.malagacf.com/entradas"),
        ("racing",          "Racing Santander",           "Racing",        "RAC", "El Sardinero",              "#009B48", "https://www.realracingclub.es/entradas"),
        ("deportivo",       "Deportivo La Coruna",        "Deportivo",     "DEP", "Riazor",                    "#0067B2", "https://www.rcdeportivo.es/entradas"),
    ],
    "seriea": [
        ("atalanta",       "Atalanta",                 "Atalanta",     "ATA", "Gewiss Stadium",          "#1D1D1B", "https://www.atalanta.it/biglietteria"),
        ("bologna",        "Bologna",                  "Bologna",      "BOL", "Renato Dall'Ara",         "#1A2F48", "https://www.bolognafc.it/biglietteria"),
        ("cagliari",       "Cagliari",                 "Cagliari",     "CAG", "Unipol Domus",            "#B01B2E", "https://www.cagliaricalcio.com/biglietti"),
        ("como",           "Como",                     "Como",         "COM", "Giuseppe Sinigaglia",     "#003F87", "https://www.comofootball.com/biglietti"),
        ("fiorentina",     "Fiorentina",               "Fiorentina",   "FIO", "Artemio Franchi",         "#592C82", "https://ticketing.acffiorentina.com"),
        ("genoa",          "Genoa",                    "Genoa",        "GEN", "Luigi Ferraris",          "#B3001E", "https://www.genoacfc.it/biglietteria"),
        ("inter",          "Inter",                    "Inter",        "INT", "San Siro",               "#0068A8", "https://www.inter.it/en/tickets"),
        ("juventus",       "Juventus",                 "Juventus",     "JUV", "Allianz Stadium",         "#000000", "https://www.juventus.com/en/tickets"),
        ("lazio",          "Lazio",                    "Lazio",        "LAZ", "Olimpico",                "#87D8F7", "https://www.sslazio.it"),
        ("lecce",          "Lecce",                    "Lecce",        "LEC", "Via del Mare",            "#EE2A24", "https://www.uslecce.it/biglietteria"),
        ("milan",          "AC Milan",                 "Milan",        "MIL", "San Siro",               "#FB090B", "https://www.acmilan.com/en/tickets"),
        ("napoli",         "Napoli",                   "Napoli",       "NAP", "Diego Armando Maradona", "#12A0D7", "https://www.sscnapoli.it/biglietti"),
        ("parma",          "Parma",                    "Parma",        "PAR", "Ennio Tardini",           "#FFD400", "https://www.parmacalcio1913.com/biglietti"),
        ("roma",           "AS Roma",                  "Roma",         "ROM", "Olimpico",                "#8E1F2F", "https://www.asroma.com/en/tickets"),
        ("sassuolo",       "Sassuolo",                 "Sassuolo",     "SAS", "Mapei Stadium",           "#00A752", "https://www.sassuolocalcio.it/biglietteria"),
        ("torino",         "Torino",                   "Torino",       "TOR", "Olimpico Grande Torino",  "#881600", "https://www.torinofc.it/biglietteria"),
        ("udinese",        "Udinese",                  "Udinese",      "UDI", "Bluenergy Stadium",       "#1A1A1A", "https://www.udinese.it/biglietti"),
        ("frosinone",       "Frosinone",                  "Frosinone",     "FRO", "Benito Stirpe",             "#FFD500", "https://www.frosinonecalcio.com/biglietteria"),
        ("monza",           "Monza",                      "Monza",         "MON", "U-Power Stadium",           "#E30613", "https://www.acmonza.com"),
        ("venezia",         "Venezia",                    "Venezia",       "VEN", "Pier Luigi Penzo",          "#FF7900", "https://www.veneziafc.it"),
    ],
    "bundesliga": [
        ("augsburg",       "FC Augsburg",              "Augsburg",     "FCA", "WWK Arena",               "#BA3733", "https://tickets.fcaugsburg.de/fcaugsburg/"),
        ("leverkusen",     "Bayer Leverkusen",         "Leverkusen",   "B04", "BayArena",                "#E32219", "https://www.bayer04.de"),
        ("bayern",         "Bayern Munich",            "Bayern",       "FCB", "Allianz Arena",           "#DC052D", "https://fcbayern.com/en/tickets"),
        ("dortmund",       "Borussia Dortmund",        "Dortmund",     "BVB", "Signal Iduna Park",       "#FDE100", "https://www.bvb.de/tickets"),
        ("gladbach",       "Borussia Monchengladbach", "Gladbach",     "BMG", "Borussia-Park",           "#00A94D", "https://www.borussia.de/tickets"),
        ("frankfurt",      "Eintracht Frankfurt",      "Frankfurt",    "SGE", "Deutsche Bank Park",      "#E1000F", "https://www.eintracht.de"),
        ("koln",           "FC Koln",                  "Koln",         "KOE", "RheinEnergieStadion",     "#ED1C24", "https://www.fc.de"),
        ("freiburg",       "SC Freiburg",              "Freiburg",     "SCF", "Europa-Park Stadion",     "#000000", "https://www.scfreiburg.com/tickets"),
        ("hsv",            "Hamburger SV",             "HSV",          "HSV", "Volksparkstadion",        "#0A5CA8", "https://www.hsv.de/tickets"),
        ("hoffenheim",     "TSG Hoffenheim",           "Hoffenheim",   "TSG", "PreZero Arena",           "#1C63B7", "https://www.tsg-hoffenheim.de/tickets"),
        ("mainz",          "Mainz 05",                 "Mainz",        "M05", "Mewa Arena",              "#C3141E", "https://www.mainz05.de/tickets"),
        ("leipzig",        "RB Leipzig",               "Leipzig",      "RBL", "Red Bull Arena",          "#DD0741", "https://rbleipzig.com/en/tickets"),
        ("stuttgart",      "VfB Stuttgart",            "Stuttgart",    "VFB", "MHPArena",                "#E32219", "https://www.vfb.de/ticketing"),
        ("union-berlin",   "Union Berlin",             "Union",        "FCU", "Alte Forsterei",          "#EB1923", "https://www.fc-union-berlin.de"),
        ("werder",         "Werder Bremen",            "Werder",       "SVW", "Weserstadion",            "#1D9053", "https://www.werder.de/tickets"),
        ("schalke",         "FC Schalke 04",              "Schalke",       "S04", "Veltins-Arena",             "#004D9D", "https://www.schalke04.de/tickets"),
        ("elversberg",      "SV Elversberg",              "Elversberg",    "ELV", "Ursapharm-Arena",           "#E30613", "https://sv07elversberg.de/tickets"),
        ("paderborn",       "SC Paderborn 07",            "Paderborn",     "SCP", "Home Deluxe Arena",         "#005CA9", "https://www.scpaderborn07.de/tickets"),
    ],
    "isl": [
        ("mohun-bagan",       "ATK Mohun Bagan",            "Mohun Bagan",     "MBG", "Vivekananda Yuba Bharati Krirangan",      "#7A1F3D", ""),
        ("bengaluru",         "Bengaluru FC",               "Bengaluru",       "BFC", "Sree Kanteerava Stadium",                 "#0057B8", "https://www.bengalurufc.com"),
        ("chennaiyin",        "Chennaiyin FC",              "Chennaiyin",      "CFC", "Jawaharlal Nehru Stadium",                "#1B4F9C", ""),
        ("goa",               "FC Goa",                     "Goa",             "FCG", "Pandit Jawaharlal Nehru Stadium",         "#F58220", "https://fcgoa.in"),
        ("jamshedpur",        "Jamshedpur FC",              "Jamshedpur",      "JFC", "JRD Tata Sports Complex",                 "#DA291C", "https://www.fcjamshedpur.com"),
        ("kerala-blasters",   "Kerala Blasters",            "Kerala Blasters", "KBFC", "Jawaharlal Nehru International Stadium",  "#FFD700", "https://keralablastersfc.in/tickets/"),
        ("mumbai-city",       "Mumbai City FC",             "Mumbai City",     "MCFC", "Mumbai Football Arena",                   "#6CACE4", "https://www.mumbaicityfc.com"),
        ("northeast-united",  "NorthEast United",           "NorthEast Utd",   "NEU", "Indira Gandhi Athletic Stadium",          "#E4002B", ""),
        ("odisha",            "Odisha FC",                  "Odisha",          "OFC", "Kalinga Stadium",                         "#6A2C91", "https://www.odishafc.com/tickets"),
        ("mohammedan",        "Mohammedan",                 "Mohammedan",      "MDSC", "Kishore Bharati Krirangan",               "#0F5132", ""),
        ("east-bengal",       "East Bengal II",             "East Bengal",     "EBFC", "Vivekananda Yuba Bharati Krirangan",      "#E4002B", ""),
        ("inter-kashi",       "Inter Kashi",                "Inter Kashi",     "IKFC", "Sigra Stadium",                           "#0057B8", ""),
        ("punjab",            "Minerva Punjab",             "Punjab FC",       "PFCI", "Jawaharlal Nehru Stadium",                "#E4002B", ""),
        ("sc-delhi",          "SC Delhi",                   "SC Delhi",        "SCD", "Ambedkar Stadium",                        "#C8102E", "https://www.scdelhi.in/tickets"),
    ],
    "ligue1": [
        ("angers",         "Angers SCO",               "Angers",       "SCO", "Raymond Kopa",            "#000000", "https://www.angers-sco.fr/billetterie"),
        ("auxerre",        "AJ Auxerre",               "Auxerre",      "AJA", "Abbe-Deschamps",          "#0055A4", "https://www.aja.fr/billetterie"),
        ("brest",          "Stade Brestois",           "Brest",        "SB29","Francis-Le Ble",          "#E30613", "https://www.sb29.bzh/billetterie"),
        ("le-havre",       "Le Havre AC",              "Le Havre",     "HAC", "Stade Oceane",            "#0B3C7F", "https://www.hac-foot.com"),
        ("lens",           "RC Lens",                  "Lens",         "RCL", "Bollaert-Delelis",        "#FFCD00", "https://billetterie.rclens.fr/fr/"),
        ("lille",          "LOSC Lille",               "Lille",        "LOSC","Stade Pierre-Mauroy",     "#E01E13", "https://billetterie.losc.fr/fr/"),
        ("lorient",        "FC Lorient",               "Lorient",      "FCL", "Stade du Moustoir",       "#F58220", "https://www.fclorient.bzh/billetterie"),
        ("lyon",           "Olympique Lyonnais",       "Lyon",         "OL",  "Groupama Stadium",        "#1A2C58", "https://www.ol.fr/billetterie"),
        ("marseille",      "Olympique de Marseille",   "Marseille",    "OM",  "Orange Velodrome",        "#2FAEE0", "https://billetterie.om.fr/fr/"),
        ("monaco",         "AS Monaco",                "Monaco",       "ASM", "Stade Louis II",          "#E63329", "https://billetterie.asmonaco.com/fr/"),
        ("nice",           "OGC Nice",                 "Nice",         "OGCN","Allianz Riviera",         "#C8102E", "https://billetterie.ogcnice.com/fr/"),
        ("paris-fc",       "Paris FC",                 "Paris FC",     "PFC", "Stade Jean-Bouin",        "#1B3D7A", "https://www.parisfc.fr/billetterie"),
        ("psg",            "Paris Saint-Germain",      "PSG",          "PSG", "Parc des Princes",        "#004170", "https://www.psg.fr/billetterie"),
        ("rennes",         "Stade Rennais",            "Rennes",       "SRFC","Roazhon Park",            "#E23029", "https://billetterie.staderennais.com/fr/"),
        ("strasbourg",     "RC Strasbourg",            "Strasbourg",   "RCSA","Stade de la Meinau",      "#0089CF", "https://www.rcstrasbourgalsace.fr/billetterie"),
        ("toulouse",       "Toulouse FC",              "Toulouse",     "TFC", "Stadium de Toulouse",     "#5F259F", "https://www.toulousefc.com/fr/billetterie"),
        ("le-mans",         "Le Mans FC",                 "Le Mans",       "LEM", "MMArena",                   "#FFD100", "https://billetterie.lemansfc.fr/fr"),
        ("troyes",          "ESTAC Troyes",               "Troyes",        "EST", "Stade de l'Aube",           "#009EE0", "https://www.estac.fr/billetterie"),
    ],
}
# fmt: on


def _build() -> list[dict]:
    out: list[dict] = []
    for league_id, rows in _RAW.items():
        for slug, name, short, tla, stadium, colour, tickets in rows:
            out.append(
                {
                    "id": slug,
                    "name": name,
                    "short": short,
                    "tla": tla,
                    "league": league_id,
                    "stadium": stadium,
                    "colour": colour,
                    "ticket_url": tickets,
                }
            )
    return out


CLUBS: list[dict] = _build()
CLUB_BY_ID: dict[str, dict] = {c["id"]: c for c in CLUBS}
CLUBS_BY_LEAGUE: dict[str, list[dict]] = {
    lid: [c for c in CLUBS if c["league"] == lid] for lid in _RAW
}

# Loose name -> club lookup so provider payloads with slightly different naming
# ("Man Utd", "Inter Milan", "Bayern Munchen") still resolve to our registry.
_ALIASES: dict[str, str] = {
    "man utd": "man-united",
    "manchester utd": "man-united",
    "spurs": "tottenham",
    "wolverhampton": "wolves",
    "newcastle utd": "newcastle",
    "nottingham": "nottm-forest",
    "brighton hove albion": "brighton",
    "inter milan": "inter",
    "east bengal ii": "east-bengal",
    "mohun bagan": "mohun-bagan",
    "mohun bagan super giant": "mohun-bagan",
    "punjab": "punjab",
    "punjab fc": "punjab",
    "northeast united fc": "northeast-united",
    "mohammedan sc": "mohammedan",
    "delhi fc": "sc-delhi",
    "internazionale": "inter",
    "ac milan": "milan",
    "as roma": "roma",
    "hellas verona": "verona",
    "bayern munchen": "bayern",
    "fc bayern munchen": "bayern",
    "borussia dortmund": "dortmund",
    "1899 hoffenheim": "hoffenheim",
    "1 fc koln": "koln",
    "fc koeln": "koln",
    "monchengladbach": "gladbach",
    "moenchengladbach": "gladbach",
    "paris saint germain": "psg",
    "olympique marseille": "marseille",
    "olympique lyonnais": "lyon",
    "atletico de madrid": "atletico",
    "athletic bilbao": "athletic",
    "real betis balompie": "betis",
    "celta de vigo": "celta",
    "rcd espanyol de barcelona": "espanyol",
}


def _norm(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    keep = [ch.lower() if ch.isalnum() else " " for ch in text]
    return " ".join("".join(keep).split())


_NAME_INDEX: dict[str, str] = {}
for _c in CLUBS:
    for _key in (_c["name"], _c["short"], _c["id"].replace("-", " ")):
        _NAME_INDEX.setdefault(_norm(_key), _c["id"])

# Only keep aliases that still point at a club in the registry. Promotion and
# relegation churn the roster every summer, and a dangling alias would raise
# KeyError deep inside transfer parsing.
_NAME_INDEX.update({k: v for k, v in _ALIASES.items() if v in CLUB_BY_ID})


# Markers that mean "not the first team". A youth or women's side must never
# resolve onto the senior club, or it inherits the wrong crest and ticket link.
_NOT_FIRST_TEAM = {
    "u16", "u17", "u18", "u19", "u20", "u21", "u23", "youth", "juvenil",
    "primavera", "reserve", "reserves", "ii", "b", "women", "w", "fem",
    "femenino", "feminin", "frauen", "academy", "castilla", "atletic",
}
# Club-name noise: legal forms, founding years, and league prefixes. Stripping
# these is what lets "FSV Mainz 05" match the registry's "Mainz 05".
_FILLER = {"fc", "cf", "afc", "ac", "as", "sc", "cd", "rc", "rcd", "ss", "us",
           "ca", "sv", "sg", "tsv", "fsv", "spvgg", "bsc", "vfb", "vfl", "tsg",
           "sd", "ud", "ogc", "losc", "rcs", "aj", "sm", "asm", "ssc", "acf",
           "de", "del", "club", "calcio", "futbol", "football", "fussball",
           "the", "and", "e", "v"}


def resolve_exact(name: str | None) -> dict | None:
    """Strict lookup: only an exact name/short/alias hit counts.

    Safe to use outside the big five (cups, Europe), where fuzzy matching would
    otherwise pull in unrelated clubs.
    """
    if not name:
        return None
    key = _norm(name)
    if not key:
        return None
    club_id = _NAME_INDEX.get(key)
    if club_id:                      # an exact registry/alias hit always wins
        return CLUB_BY_ID.get(club_id)
    if set(key.split()) & _NOT_FIRST_TEAM:
        return None
    return None


def resolve(name: str | None) -> dict | None:
    """Best-effort club lookup by any reasonable spelling of its name.

    Deliberately conservative: a miss is harmless (we fall back to the raw
    name), but a false positive would show Athletic Bilbao's ticket page for
    Brazil's Athletic Club MG.
    """
    if not name:
        return None
    key = _norm(name)
    if not key:
        return None

    if key in _NAME_INDEX:           # exact registry/alias hit wins outright
        return CLUB_BY_ID.get(_NAME_INDEX[key])

    tokens = set(key.split())
    if tokens & _NOT_FIRST_TEAM:
        return None

    # Token pass: every significant word of the registry name must be present,
    # and the query may carry at most one extra significant word.
    significant = {t for t in tokens if t not in _FILLER and not t.isdigit()}
    best: tuple[int, str] | None = None
    for indexed, club_id in _NAME_INDEX.items():
        idx_tokens = {t for t in indexed.split()
                      if t not in _FILLER and not t.isdigit()}
        if not idx_tokens or not idx_tokens <= significant:
            continue
        extra = len(significant - idx_tokens)
        # A single-word registry name ("Athletic", "Milan") is too generic to
        # absorb an unexplained extra word, so it must match exactly.
        if extra > (1 if len(idx_tokens) > 1 else 0):
            continue
        score = len(idx_tokens) * 10 - extra
        if best is None or score > best[0]:
            best = (score, club_id)
    return CLUB_BY_ID.get(best[1]) if best else None
