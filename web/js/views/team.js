// Club page: identity, league position, fixtures, squad, transfers, tickets.
import { api } from '../api.js';
import { formStrip, matchRow } from '../components.js';
import { $, crest, emptyState, esc, money, notice, shortDate, skeleton } from '../util.js';

export async function renderTeam(ctx, params) {
  const root = $('#view');
  root.innerHTML = skeleton(6);
  let d;
  try {
    d = await api.team(params.id);
  } catch (err) {
    root.innerHTML = emptyState('⚠', 'Club not found', err.message);
    return;
  }
  ctx.setPill({ text: 'Mixed sources', cls: 'sim' });

  const c = d.club;
  const s = d.standing;
  const t = d.tickets;

  root.innerHTML = `
    <div class="team-hero" style="--tint:${esc(c.colour)}22">
      ${crest({ ...c, tla: c.tla, logo: c.logo })}
      <div>
        <h1>${esc(c.name)}</h1>
        <div class="meta">${esc(d.league?.name || '')} · ${esc(c.stadium)}</div>
      </div>
      <div class="spacer"></div>
      ${t ? `<a class="btn" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">
               🎟 Buy tickets</a>` : ''}
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Season</h3>
        ${s ? `
          <div class="kv"><span>Position</span><b>${s.rank}</b></div>
          <div class="kv"><span>Played</span><b>${s.played}</b></div>
          <div class="kv"><span>W / D / L</span><b>${s.win} / ${s.draw} / ${s.loss}</b></div>
          <div class="kv"><span>Goals</span><b>${s.gf} : ${s.ga}</b></div>
          <div class="kv"><span>Points</span><b>${s.points}</b></div>
          <div class="kv"><span>Form</span>${formStrip(d.form)}</div>`
        : '<div style="color:var(--muted)">No table data.</div>'}
      </div>

      <div class="card">
        <h3>Next fixtures</h3>
        ${d.upcoming?.length
          ? d.upcoming.slice(0, 5).map(m => `
              <div class="kv">
                <span>${esc(shortDate(m.kickoff))} · ${esc(m.home.short)} v ${esc(m.away.short)}
                  <br><small style="color:var(--muted)">${esc(m.league_name || '')}</small></span>
                ${m.tickets
                  ? `<a class="tix sm" href="${esc(m.tickets.url)}" target="_blank"
                       rel="noopener noreferrer" title="${esc(m.tickets.label)}">🎟</a>`
                  : ''}
              </div>`).join('')
          : '<div style="color:var(--muted)">Nothing scheduled.</div>'}
      </div>
    </div>

    <div class="tabs" id="tm-tabs">
      <div class="tab active" data-tab="results">Results</div>
      <div class="tab" data-tab="squad">Squad</div>
      <div class="tab" data-tab="transfers">Transfers</div>
    </div>
    <div id="tm-body"></div>`;

  const panels = {
    results: () => d.recent?.length
      ? d.recent.map(matchRow).join('')
      : emptyState('📋', 'No results yet'),
    squad: () => squadPanel(d),
    transfers: () => transfersPanel(d),
  };
  const body = $('#tm-body');
  body.innerHTML = panels.results();

  $('#tm-tabs').addEventListener('click', e => {
    const tab = e.target.closest('.tab'); if (!tab) return;
    $('#tm-tabs').querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    tab.classList.add('active');
    body.innerHTML = panels[tab.dataset.tab]();
  });

  body.addEventListener('click', e => {
    const row = e.target.closest('.match');
    if (row && !e.target.closest('[data-stop]')) location.hash = `#/match/${row.dataset.match}`;
  });
}

function squadPanel(d) {
  const sq = d.squad || [];
  if (!sq.length) return emptyState('👥', 'No squad data');
  const real = d.squad_source === 'apifootball';
  const byPos = { GK: [], DF: [], MF: [], FW: [] };
  for (const p of sq) (byPos[p.position] || byPos.MF).push(p);
  const label = { GK: 'Goalkeepers', DF: 'Defenders', MF: 'Midfielders', FW: 'Forwards' };

  const meta = p => real
    ? [p.position_long, p.age ? `age ${p.age}` : ''].filter(Boolean).join(' · ')
    : [p.nationality, p.age, p.market_value ? money(p.market_value) : '']
        .filter(Boolean).join(' · ');

  return (real ? '' : notice('Squad list is from the simulated season.')) +
    Object.entries(byPos).filter(([, v]) => v.length).map(([pos, list]) => `
    <div class="card">
      <h3>${label[pos]} <span style="color:var(--muted);font-weight:600">${list.length}</span></h3>
      <div class="squad-grid">${list.map(p => `
        ${p.id ? `<a class="sq-card" href="#/player/${esc(p.id)}">` : '<div class="sq-card">'}
          ${p.photo
            ? `<img class="sq-photo" src="${esc(p.photo)}" alt="" loading="lazy">`
            : `<span class="sq-num">${p.number ?? '–'}</span>`}
          <span class="sq-info">
            <span class="n">${esc(p.name)}</span>
            <span class="p">${p.number != null ? `#${p.number} · ` : ''}${esc(meta(p))}</span>
          </span>
        ${p.id ? '</a>' : '</div>'}`).join('')}</div>
    </div>`).join('');
}

function transfersPanel(d) {
  const rows = d.transfers || [];
  if (!rows.length) return emptyState('🔄', 'No transfers recorded',
    'This club has not been swept yet — open the Transfers page and hit Sync.');
  return `<div class="card">
    <h3>Recent business ${d.transfers_source === 'apifootball' ? '· live data' : '· simulated'}</h3>
    ${rows.map(t => `
      <div class="kv">
        <span><b style="color:var(--text)">${t.player.id
          ? `<a href="#/player/${esc(t.player.id)}">${esc(t.player.name)}</a>`
          : esc(t.player.name)}</b><br>
          <small style="color:var(--muted)">${esc(t.from.name || '?')} → ${esc(t.to.name || '?')}</small></span>
        <b>${esc(money(t.fee.amount) || t.fee.label)}</b>
      </div>`).join('')}
  </div>`;
}
