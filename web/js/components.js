// Shared render pieces used by more than one view.
import { crest, esc, kickoffTime } from './util.js';

const TODAY = new Date().toDateString();

/** Kickoff cell for a fixture that has not started.
 *  Lists spanning several dates (a competition's fixture list, a club's next
 *  games) need the date, not just a bare time. */
function scheduledCell(kickoff) {
  const d = kickoff ? new Date(kickoff) : null;
  const sameDay = d && d.toDateString() === TODAY;
  const date = d && !sameDay
    ? `<div class="m-date">${esc(d.toLocaleDateString([], { day: 'numeric', month: 'short' }))}</div>`
    : '';
  return `${date}<div class="clock">${kickoffTime(kickoff)}</div>` +
         `<div class="state">${sameDay ? 'KO' : esc(d ? d.toLocaleDateString([], { weekday: 'short' }) : '')}</div>`;
}

/** Kickoff cell for a finished match. A results list also spans dates. */
function finishedCell(kickoff) {
  const d = kickoff ? new Date(kickoff) : null;
  const sameDay = d && d.toDateString() === TODAY;
  return (d && !sameDay
      ? `<div class="m-date muted">${esc(d.toLocaleDateString([], { day: 'numeric', month: 'short' }))}</div>`
      : '')
    + `<div class="clock">FT</div>`
    + `<div class="state">${sameDay ? 'Full time' : ''}</div>`;
}

/** One match row. Clicking it routes to the detail view; the ticket link does not. */
export function matchRow(m) {
  const st = m.status || {};
  const live = st.type === 'live';
  const done = st.type === 'finished';
  const off = st.type === 'postponed';
  const showScore = live || done;

  const hs = m.home?.score ?? 0;
  const as = m.away?.score ?? 0;
  const homeLost = done && hs < as;
  const awayLost = done && as < hs;

  const timeCell = off
    ? `<div class="clock" style="font-size:11px">—</div>
       <div class="state" style="color:var(--warn)">${esc(st.label || 'OFF')}</div>`
    : live
      ? `<div class="clock">${esc(st.label)}</div>
         <div class="state"><span class="live-dot"></span>Live</div>`
      : done
        ? finishedCell(m.kickoff)
        : scheduledCell(m.kickoff);

  const side = (s, lost) => `
    <div class="m-team ${lost ? 'dim' : ''}">
      ${crest(s)}
      <span class="nm">${esc(s?.name || s?.short || 'TBD')}</span>
      <span class="sc">${showScore ? (s?.score ?? 0) : ''}</span>
    </div>`;

  const t = m.tickets;
  const tix = t
    ? `<a class="tix" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer"
          title="${esc(t.label)} — official box office" data-stop>
         🎟 <span>Tickets</span></a>`
    : '';

  return `
  <div class="match" style="--edge:${esc(m.league_accent || '#39443e')}"
       data-match="${esc(m.id)}">
    <div class="m-time ${live ? 'live' : ''}">${timeCell}</div>
    <div class="m-teams">
      ${side(m.home, homeLost)}
      ${side(m.away, awayLost)}
    </div>
    <div class="m-right">${tix}</div>
  </div>`;
}

/** Group an array of matches into per-competition blocks. */
export function leagueBlocks(matches, leagueMeta = {}) {
  const groups = new Map();
  for (const m of matches) {
    if (!groups.has(m.league)) groups.set(m.league, []);
    groups.get(m.league).push(m);
  }
  return [...groups.entries()].map(([lid, rows]) => {
    const meta = leagueMeta[lid];
    const first = rows[0];
    const name = meta?.name || first.league_name || lid;
    const country = meta?.country || first.league_country || '';
    const accent = meta?.accent || first.league_accent || '#39443e';
    const tableLink = meta
      ? `<a class="to-table" href="#/league/${esc(lid)}">Table →</a>` : '';
    return `
      <section class="lg-block">
        <div class="lg-head">
          <span class="bar" style="background:${esc(accent)}"></span>
          <h3>${esc(name)}</h3>
          ${country ? `<span class="country">${esc(country)}</span>` : ''}
          ${tableLink}
        </div>
        ${rows.map(matchRow).join('')}
      </section>`;
  }).join('');
}

export function sourcePill(payload) {
  if (!payload) return { text: '', cls: '' };
  if (payload.simulated) return { text: 'Simulated', cls: 'sim' };
  if ((payload.source || '').includes('cached')) return { text: 'Cached', cls: 'real' };
  return { text: 'Live data', cls: 'real' };
}

export function formStrip(form = '') {
  if (!form) return '<span style="color:var(--muted)">—</span>';
  return `<span class="form">${[...form].map(c => `<i class="${c}">${c}</i>`).join('')}</span>`;
}
