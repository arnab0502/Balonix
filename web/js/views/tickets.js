// Full official ticketing directory across the big five.
import { api } from '../api.js';
import { $, emptyState, esc, notice, skeleton } from '../util.js';

export async function renderTickets(ctx) {
  const root = $('#view');
  root.innerHTML = `
    <div class="page-head">
      <h1>Tickets</h1>
      <span class="sub">Official box office for every club we cover</span>
    </div>
    ${notice('These are the clubs’ own ticketing pages. No resale, no affiliate links. '
           + 'Availability and membership requirements are set by each club.', 'info')}
    <div id="tix-body">${skeleton(6)}</div>`;

  try {
    const data = await api.tickets(null);
    ctx.setPill({ text: 'Official links', cls: 'real' });
    const byLeague = new Map();
    for (const c of data.clubs) {
      if (!byLeague.has(c.league)) byLeague.set(c.league, []);
      byLeague.get(c.league).push(c);
    }
    $('#tix-body').innerHTML = [...byLeague.entries()].map(([lid, clubs]) => {
      const meta = ctx.leagueMeta[lid];
      return `<section class="lg-block">
        <div class="lg-head">
          <span class="bar" style="background:${esc(meta?.accent || '#39443e')}"></span>
          <h3>${esc(meta?.name || lid)}</h3>
          <span class="country">${clubs.length} clubs</span>
        </div>
        <div class="tix-grid">${clubs.map(c => `
          <a class="tix-card" style="--edge:${esc(c.colour)}"
             href="${esc(c.ticket_url)}" target="_blank" rel="noopener noreferrer">
            <span class="crest-fb" style="background:${esc(c.colour)};width:34px;height:34px;font-size:11px;border-radius:9px">
              ${esc(c.short.slice(0, 3).toUpperCase())}</span>
            <span class="info"><b>${esc(c.name)}</b><small>${esc(c.stadium)}</small></span>
            <span style="color:var(--accent);font-size:15px">🎟</span>
          </a>`).join('')}</div>
      </section>`;
    }).join('');
  } catch (err) {
    $('#tix-body').innerHTML = emptyState('⚠', 'Could not load ticket links', err.message);
  }
}
