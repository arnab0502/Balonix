# TotalFootball

Everything about football in one place: a FotMob-style live-score app, a
transfer feed, and a direct link to the official box office for every match.

Covers the **Champions League, the big five and the Indian Super League** —
110 domestic clubs.

```bash
./run.sh          # then open http://127.0.0.1:8000
```

No Node, no build step. FastAPI serves a vanilla-JS single-page app.

---

## What it does

| | |
|---|---|
| **Matches** | Date strip, live block, fixtures grouped by competition, per-league colour coding |
| **Match detail** | Score hero, event timeline, stat bars, pitch-view lineups, **player ratings**, real head-to-head with a W-D-L summary, **unavailable players** with reasons |
| **Leagues** | Standings with European/relegation cut-offs, **fixtures and results**, top scorers, **roll of honour**, club ticket directory |
| **Transfers** | Filterable feed across the big five by league and deal type |
| **Clubs** | Squad, results, upcoming fixtures, recent business, ticket link |
| **Tickets** | Every fixture links to the **home club's own box office** — never a resale site |
| **Players** | Profile, season stats, **full career grouped by competition** with per-season rows, **league rankings**, clubs, transfer history |
| **Home** | Adaptive hero (live scores, else the next real fixture), stat rail, rumour mill, latest transfers, league leaders, newest episodes |
| **Rumours** | Transfer talk aggregated from BBC Gossip, Guardian Transfers, Sky, BBC, Guardian and 90min — filterable by source, searchable, club-tagged |
| **Search** | Clubs, players, competitions — player names open the player page |
| **Podcast** | Your YouTube channel's episodes, searchable, with an inline player |

### Mobile

Built for phones, not just shrunk down:

- Left rail becomes a swipe-to-close drawer with a scrim and body-scroll lock;
  a 4-item bottom tab bar handles primary nav
- `env(safe-area-inset-*)` respected, so nothing hides under a home indicator
- Standings and scorer tables drop secondary columns (`W/D/L`, `GF/GA`, apps)
  instead of scrolling sideways — the page never scrolls horizontally
- Match rows stay on one line; the ticket button collapses to a 🎟 icon
- Search input is 16px so iOS does not zoom on focus
- Tap targets are >= 44px, with tap-highlight suppressed
- Landscape phones reclaim vertical space; `prefers-reduced-motion` honoured

---

## Data sources

The app runs on **API-Football, Pro plan (7,500 requests/day)**. On Pro there
is no season or date gate, so **every view is backed by real data**:

| Feature | Source |
|---|---|
| Live scores, any competition worldwide | `/fixtures?live=all` — one call, events inline |
| Full fixture calendar, any date | `/fixtures?date=` |
| Match detail: events, stats, lineups | `/fixtures?id=` |
| Standings | `/standings` |
| Top scorers | `/players/topscorers` |
| Squads | `/players/squads` |
| Player ratings + match stats | `/fixtures/players` |
| Head-to-head | `/fixtures/headtohead` |
| Unavailable players | `/injuries?fixture=` |
| Player search fallback | `/players/profiles?search=` |
| Player detail | `/players/profiles`, `/players`, `/players/teams`, `/transfers?player=` |
| Transfers | `/transfers?team=` — all 96 clubs |
| Ticket links | Local registry, see below |

Every response still carries a `source` field and the UI shows a **Live data**
pill, so if anything ever falls back to the simulated season you will know.

### Season handling

A season that hasn't kicked off yet has an all-zero table, which is useless to
look at. So the app checks whether the current season has any games played and
falls back to the last completed one, labelling it (`Season 2025/26`). It
switches over automatically once the new season starts.

---

## The request budget

Pro gives 7,500/day. A heavy day uses a few hundred, so this is comfortable —
but the guards are still in place because they cost nothing.

**Ring-fenced buckets** (`.env`):

```
TF_BUDGET_CORE=3000     fixtures, standings, scorers, squads, transfers
TF_BUDGET_LIVE=2500     live score polling
TF_BUDGET_DETAIL=1500   opening individual matches
TF_BUDGET_RESERVE=500   never spent
```

**Disk-backed cache** — restarts don't re-spend quota, and if the budget ever
runs out the app serves the last good answer rather than an error.

**Rate limiting** — Pro allows ~450 calls/minute; the client paces at 300 and
**refunds** any 429 to the daily budget rather than charging for a rejected
call.

**First-run warm-up** — on a cold start the server pulls all 96 squads and all
96 transfer histories in the background (~190 requests, about 2.5% of a day)
so player search and the transfer feed work immediately.

Watch it in the sidebar widget or `GET /api/health`.

---

## Player search

Search is backed by a local index of all 96 club squads (~2,970 players), which
is instant and costs nothing.

**`/players/squads` is incomplete**, though — loanees and late-window signings
are routinely missing. Marcus Rashford is registered at Barcelona per
`/players/teams` but absent from Barcelona's squad payload, so a squad-only
index has permanent holes.

So when the local index returns fewer than 5 hits, the app tops up from
`/players/profiles?search=`, which covers every player API-Football knows.
Rashford, Sancho, Grealish and Sterling all resolve this way. Results are
cached for a day.

Two related fixes worth knowing about:

- **Current club skips national teams.** `/players/teams` mixes clubs and
  countries together, and a player's country often has the most recent season,
  which made Rashford's club read "England". Teams are now checked for the
  `national` flag.
- **Season falls back past internationals.** A new season may only contain
  World Cup and friendly fixtures, which made for a bare page; the app falls
  back a season until it finds club football.

---

## Transfers

Full coverage: all 96 big-five clubs swept.

**Grouped by club** by default — each club is a card showing ins and outs
split into two columns, with a deal-type breakdown (permanent / loan / free).
Switch to **Latest** for a flat reverse-chronological feed. Both views support
search by player or club name, plus league and deal-type filters.

**Scoped to the current window.** The feed defaults to moves since **1 June**,
i.e. everything after last season finished — that is what "this season's
transfers" means. `Last 12 months` and `All time` are one click away.

Deals reported by both clubs (usually a day apart) are de-duplicated on
player + both endpoints, keeping whichever record carries a fee.

### One real data limitation: fees

API-Football's **fee data effectively stopped after 2024**. Measured across the
full 69,501-row sweep:

| Season year | Rows | With a fee | Coverage |
|---|---|---|---|
| 2026 | 5,045 | 2 | 0.0% |
| 2025 | 7,366 | 14 | 0.2% |
| 2024 | 3,867 | 803 | 20.8% |
| 2023 | 3,748 | 801 | 21.4% |

So for any recent window, fees are essentially unavailable from this provider,
and a "net spend" figure would read €0 for nearly every club. Rather than show
a meaningless number, club cards lead with **deal mix** and money appears only
when a fee actually exists.

If fees matter to you, Transfermarkt is the source that has them. Both public
`transfermarkt-api` mirrors were down when this was built (500 / deployment
disabled), but `server/providers/` is a clean interface for slotting in a
self-hosted one — the transfer merge already prefers whichever record carries
a fee.

---

## Rumour mill

`server/providers/news.py` aggregates public RSS feeds — **no API key, no
quota**. API-Football only carries completed moves, so rumours have to come
from journalism.

| Source | Tier | Notes |
|---|---|---|
| BBC Gossip | 1 | dedicated daily transfer round-up |
| Guardian Transfer Window | 1 | dedicated transfer desk |
| Sky Sports, BBC Sport, Guardian | 1 | general football, filtered to transfer stories |
| 90min | 2 | aggregator, lower trust tier |

Stories from the general feeds are keyword-filtered; the two dedicated desks
pass through whole. Items are de-duplicated on title keywords (round-ups
repeat each other) keeping the highest-trust telling, and tagged with any club
they name using **exact** registry matches — fuzzy matching on prose would tag
half the league every time a writer typed "united".

The home page leads with the dedicated desks and falls back to general news.

---

## The pitch

`web/js/pitch.js` renders both the real lineups and the probable XI. Pure
CSS and inline SVG — no images, no libraries:

- proper markings (boxes, six-yard, D-arcs, centre circle, penalty and corner
  arcs) drawn as SVG that stretches with the container
- mown stripes, a floodlight falloff at the corners and a soft accent glow
- player tokens carrying a real photo, a jersey-tinted ring, a stat chip
  (match rating on a played game, starts on a probable XI) and a ★ on new
  signings
- rows come from the provider's `grid` ("2:4" = second row, fourth across), so
  players sit where they actually played; away sides are flipped

---

## Probable XI

Expand a club card in **Transfers** and it builds a likely XI on a pitch,
lazily (nobody wants 110 lineup requests on page load). The same XI appears
on a **match page** when teamsheets have not been published yet.

Four real signals, no guessing:

1. **Current squad** from `/players/squads` — the roster must be today's, not
   last season's appearance list
2. **Most-used formation** from `/teams/statistics`
3. **Grid slots** from the club's most recent XI in that shape, so players sit
   where they actually play
4. **Who is unavailable**, and who arrived this window

New signings are ranked on what they did at their **previous** club, so a
summer arrival can displace an incumbent. Anyone still unranked is listed
separately as an arrival with no minutes yet.

### Four bugs this took

- **Slot-by-slot filling scrambled the team.** The highest starter grabbed the
  first vacant slot, putting Shaw at right-back and dropping Bruno Fernandes.
  Now each position band is ranked first, then players are seated, preferring
  their own previous slot.
- **`/injuries?season=` returns the whole season's history**, so 19 Man United
  players were marked unavailable. Scoped to the latest fixture.
- **New signings were invisible.** The pool came from last season's stats *for
  this club*, so Tonali — a Newcastle player last season — did not exist at
  Spurs. Fixed by making the current squad the roster.
- **`Attacker` bucketed as a midfielder.** The lineups endpoint says `G/D/M/F`,
  the players endpoint says `Goalkeeper/Defender/Midfielder/Attacker`; taking
  the first letter sent every forward to midfield and left the striker slot to
  a youth player on zero starts.

Starts are only credited from competitions we cover, so a Championship keeper
on 41 games does not outrank a Premier League starter.

---

## Player career stats

The **By competition** tab groups a player's whole career by tournament, with
per-season rows underneath. Bruno Fernandes reads: Premier League 231 apps
71g/72a across 2019/20–2025/26, plus Primeira Liga, Champions League, Europa
League, Nations League and the cups.

Seasons come from `/players/seasons`, then one `/players?id=&season=` call per
season. That is capped at the **10 most recent** and cached for a week, so a
15-season career doesn't cost 15 calls on every page view.

### League rankings

Ranked against each competition's **published top-20 chart**
(`/players/topscorers` and `/players/topassists`), which are cached per
league-season and therefore shared across every player you look at.

A player outside the top 20 simply gets no rank — the app does not invent a
position it cannot verify. Bruno shows *#1 for assists, 21* in the Premier
League.

---

## Continental competitions

The Champions League is marked `continental: True` in `leagues.py`, which
changes two behaviours:

- **Club resolution is not league-scoped.** Domestic leagues reject a club
  from another league (that guard is what stopped Athletic Club MG becoming
  Athletic Bilbao). Continental entrants come from everywhere, so UCL uses an
  exact registry match across all leagues instead.
- **The simulated season skips it.** A cup has no fixed membership, so there
  is nothing to round-robin; `mock.py` returns an empty schedule rather than
  raising on an empty club list.

Its league-phase table is a single 36-team standing. Out of season the usual
fallback shows the last completed one.

---

## Podcast tab

Set `TF_YOUTUBE_CHANNEL` in `.env` to an `@handle`, a `UC...` channel id, or a
full channel URL. **No API key needed.** Currently pointed at
`@HighburyChronicle`.

Two sources, tried in order:

1. **Channel RSS** (`/feeds/videos.xml?channel_id=`) — real timestamps, view
   counts, no quota. But YouTube only serves 15 items, and **it does not serve
   a feed for every channel**: Highbury Chronicle's returns a hard 404 despite
   the channel having 60 public uploads.
2. **Channel page scrape** — reads `ytInitialData` off the `/videos`,
   `/streams`, `/podcasts` and `/shorts` tabs and parses the `lockupViewModel`
   grid items. Gets all 60 episodes with thumbnails and view counts; the page
   only exposes relative dates ("3 months ago"), which are parsed to order the
   merged tabs.

Optionally set `TF_YOUTUBE_API_KEY` (free tier, 10,000 units/day) for the
canonical back catalogue via `playlistItems` — 1 unit per 50 videos.

> Resolving a handle to a channel id has one trap: a bare `"channelId"` search
> of the page matches the **recommended** channels in the sidebar. The code
> reads `rssUrl`, then the canonical link, then `channelMetadataRenderer`.

---

## Adding a competition

Leagues are data, not code: add an entry to `server/data/leagues.py` (with its
API-Football `api_id`), add its clubs to `clubs.py`, rebuild `team_ids.json`,
then run both sync endpoints. Everything else — nav, filters, standings,
scorers, search, tickets — picks it up automatically.

That is how ISL was added. Two things bit on the way and are now guarded:

- The simulated-season name pools are keyed by league id, so a new league
  raised `KeyError` on the club page. Lookups now fall back to an
  international pool.
- API-Football calls East Bengal "East Bengal II", and the reserve-team guard
  (which stops `Arsenal U21` matching Arsenal) rejected it. An exact registry
  or alias hit now always wins over that guard.

---

## The club registry

`server/data/clubs.py` is the source of truth for the 96 big-five clubs. It has
to be re-based every summer as clubs go up and down — 14 clubs changed for
2026-27. When you do that, three things must move together:

1. the rows in `clubs.py` (including a ticket URL for each new club)
2. `server/data/team_ids.json` — rebuild from `/teams?league=&season=`
3. `.cache/squads.json` and `.cache/transfers.json` — prune relegated clubs,
   then re-run both sync endpoints

Aliases in `clubs.py` are filtered against the live registry on import, because
a dangling alias (`"hellas verona" -> "verona"` after Verona went down) raised
`KeyError` deep inside transfer parsing.

> Historical tables still name relegated clubs. Viewing the final 2025/26
> standings shows West Ham, Burnley and Wolves without crest colours, since
> they are no longer in the registry. Once the new season has fixtures played,
> standings switch to 2026/27 and everything resolves.

---

## Ticketing

`server/data/clubs.py` holds all 96 big-five clubs with their **official**
ticket URL. Resolution order:

1. Home club's own box office
2. League ticket portal
3. A scoped web search — so the link is never dead

Only big-five fixtures get a ticket link. Matches outside the registry return
`tickets: null` rather than a guess, because fuzzy club matching would
otherwise hand *Athletic Club MG U20* (Brazil) the Athletic Bilbao box office.
Club resolution rejects youth, reserve and women's sides for the same reason.

### Link verification

All 96 URLs were probed against the live web. Current state:

| Result | Count |
|---|---|
| `200` — real ticket page loads | 86 |
| `403` — bot protection, page exists and works in a browser | 8 |
| Timeout — slow or protected origin (Bayern, Sassuolo) | 2 |
| **Broken (404)** | **0** |

An initial pass had **32 clubs 404**, which is why they were probed rather
than trusted: 22 were corrected to their real paths (several clubs use
dedicated ticketing subdomains — `billetterie.om.fr`, `entradas.sevillafc.es`,
`tickets.fcaugsburg.de`), and 11 with no reachable deep link now point at the
club's official homepage, which always resolves.

Those 11 — Leeds, Man United, Lazio, Pisa, Leverkusen, Köln, St. Pauli, Union
Berlin, Frankfurt, Le Havre, Metz — land you on the official site one click
from the box office rather than on a dead URL. Clubs restructure their sites,
so if one drifts, fix the single line in `clubs.py`.

---

## Layout

```
server/
  main.py              FastAPI app + SPA fallback
  config.py            .env settings
  quota.py             daily budget guard, persisted, with refunds
  cache.py             disk-backed TTL cache, single-flight, stale fallback
  data/
    clubs.py           96 clubs: colours, stadiums, official ticket URLs
    leagues.py         big-five metadata
    tickets.py         fixture -> box office resolution
    team_ids.json      club -> API-Football id (built once, never re-fetched)
  providers/
    apifootball.py     live adapter, rate-paced and budgeted
    mock.py            simulated season engine
    composite.py       stitches real + simulated, labels every response
  routers/api.py       JSON API
web/
  index.html
  css/app.css          floodlit dark theme
  js/                  router, views, components — ES modules, no bundler
```

## API

```
GET  /api/meta                      leagues, clubs, capabilities, quota
GET  /api/matches?day=YYYY-MM-DD
GET  /api/live?scope=big5|all
GET  /api/match/{id}
GET  /api/league/{id}/standings
GET  /api/league/{id}/scorers
GET  /api/transfers?league=&limit=
POST /api/transfers/sync?limit=     pull next slice of clubs
GET  /api/team/{id}
GET  /api/search?q=
GET  /api/tickets[?league=]
GET  /api/health                    quota + cache stats
```

## Deploying (Railway)

1. Push to GitHub. `.env` and `.cache/` are gitignored — neither should ship.
2. New Railway project → deploy from the repo. The `Procfile` and
   `.python-version` are already here, so it needs no build config.
3. Set these variables in the Railway dashboard:

```
TF_API_FOOTBALL_KEY   your key
TF_PROVIDER           apifootball
TF_YOUTUBE_CHANNEL    @HighburyChronicle
TF_AUTH_USER          pick one
TF_AUTH_PASS          pick one
```

`PORT` is injected by Railway and picked up automatically.

**Set `TF_AUTH_USER` / `TF_AUTH_PASS` before the URL is public.** Without them
every route is open, and an unauthenticated visitor can spend your 7,500 daily
API-Football requests — `POST /api/transfers/sync` costs 110 calls per hit.
With them set, everything needs credentials except `/api/health`, which stays
open for platform health checks.

On first boot the warm-up pulls squads and transfers (~200 requests, a few
minutes under the rate limiter). Attach a volume at `/app/.cache` to skip that
on redeploys; without one it simply re-warms, which is fine.

---

## Notes

- `.env` holds your API key and is gitignored. It was pasted into a chat
  transcript during development — **rotate it** if that transcript is shared.
- Switch to `TF_PROVIDER=mock` for a zero-request offline demo.
- Late July is the off-season: expect no real big-five fixtures until August.
  The app falls back to the simulated slate and says so.
