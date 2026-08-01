// League page: standings table, scorers chart, and the club ticket directory.
import { api } from '../api.js';
import { formStrip, leagueBlocks, matchRow, sourcePill } from '../components.js';
import { $, crest, emptyState, esc, notice, skeleton } from '../util.js';

const QUALIFY = {
  epl:        { ucl: 4, uel: 6, rel: 18 },
  laliga:     { ucl: 4, uel: 6, rel: 18 },
  seriea:     { ucl: 4, uel: 6, rel: 18 },
  bundesliga: { ucl: 4, uel: 6, rel: 16 },
  ligue1:     { ucl: 3, uel: 5, rel: 16 },
};

export async function renderLeague(ctx, params) {
  const lid = params.id;
  const meta = ctx.leagueMeta[lid];
  const root = $('#view');

  root.innerHTML = `
    <div class="page-head">
      <h1>${esc(meta?.name || lid)}</h1>
      <span class="sub">${esc(meta?.country || '')}</span>
    </div>
    <div class="tabs" id="lg-tabs">
      <div class="tab active" data-tab="table">Table</div>
      <div class="tab" data-tab="fixtures">Fixtures</div>
      <div class="tab" data-tab="scorers">Top scorers</div>
      <div class="tab" data-tab="honours">Roll of honour</div>
      <div class="tab" data-tab="tickets">Ticket directory</div>
    </div>
    <div id="lg-body">${skeleton(8)}</div>`;

  const body = $('#lg-body');
  const panels = {
    table: () => tablePanel(ctx, lid),
    fixtures: () => fixturesPanel(ctx, lid),
    scorers: () => scorersPanel(ctx, lid),
    honours: () => honoursPanel(ctx, lid),
    tickets: () => ticketsPanel(ctx, lid),
  };
  panels.table();

  $('#lg-tabs').addEventListener('click', e => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    $('#lg-tabs').querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    tab.classList.add('active');
    body.innerHTML = skeleton(6);
    panels[tab.dataset.tab]();
  });
}

async function tablePanel(ctx, lid) {
  const body = $('#lg-body');
  try {
    const data = await api.standings(lid);
    ctx.setPill(sourcePill(data));
    const q = QUALIFY[lid] || {};
    const total = data.table.length;
    // Prefer the provider's own qualification wording when it ships one.
    const bandOf = r => {
      const d = (r.description || '').toLowerCase();
      if (d) {
        if (d.includes('champions league')) return 'ucl';
        if (d.includes('europa league')) return 'uel';
        if (d.includes('conference')) return 'uecl';
        if (d.includes('relegation')) return 'rel';
        return '';
      }
      return r.rank <= (q.ucl || 0) ? 'ucl'
           : r.rank <= (q.uel || 0) ? 'uel'
           : r.rank > (q.rel || total) ? 'rel' : '';
    };

    body.innerHTML = notice(data.note) +
      (data.season ? `<div class="season-tag">Season ${esc(data.season)}</div>` : '') + `
      <div class="card"><div class="table-wrap">
      <table class="tbl">
        <thead><tr>
          <th>#</th><th>Club</th>
          <th class="num">P</th>
          <th class="num col-opt">W</th><th class="num col-opt">D</th><th class="num col-opt">L</th>
          <th class="num col-opt">GF</th><th class="num col-opt">GA</th>
          <th class="num">GD</th><th class="num">Pts</th><th class="col-opt">Form</th>
        </tr></thead>
        <tbody>
          ${data.table.map(r => {
            const cls = bandOf(r);
            return `<tr class="${cls}" data-team="${esc(r.team.id)}"
                        title="${esc(r.description || '')}">
              <td class="rank">${r.rank}</td>
              <td><div class="team-cell">${crest(r.team)}<span>${esc(r.team.short)}</span></div></td>
              <td class="num">${r.played}</td>
              <td class="num col-opt">${r.win}</td><td class="num col-opt">${r.draw}</td>
              <td class="num col-opt">${r.loss}</td>
              <td class="num col-opt">${r.gf}</td><td class="num col-opt">${r.ga}</td>
              <td class="num">${r.gd > 0 ? '+' : ''}${r.gd}</td>
              <td class="num"><b>${r.points}</b></td>
              <td class="col-opt">${formStrip(r.form)}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table></div>
      <div class="legend">
        <span><i style="background:var(--accent)"></i>Champions League</span>
        <span><i style="background:#4d9fff"></i>Europa League</span>
        <span><i style="background:#35d07f"></i>Conference League</span>
        <span><i style="background:var(--live)"></i>Relegation</span>
      </div>
      </div>`;

    body.querySelectorAll('tbody tr').forEach(tr =>
      tr.addEventListener('click', () => { location.hash = `#/team/${tr.dataset.team}`; }));
  } catch (err) {
    body.innerHTML = emptyState('⚠', 'Could not load the table', err.message);
  }
}

async function fixturesPanel(ctx, lid) {
  const body = $('#lg-body');
  body.innerHTML = `
    <div class="tr-toolbar">
      <div class="seg" id="fx-when">
        <button class="seg-btn active" data-when="next">Upcoming</button>
        <button class="seg-btn" data-when="last">Results</button>
      </div>
    </div>
    <div id="fx-rows">${skeleton(6)}</div>`;

  const load = async when => {
    const rows = $('#fx-rows');
    rows.innerHTML = skeleton(6);
    try {
      const data = await api.leagueFixtures(lid, when);
      ctx.setPill(sourcePill(data));
      rows.innerHTML = data.matches?.length
        ? notice(data.note)
          + (data.season ? `<div class="season-tag">Season ${esc(data.season)}</div>` : '')
          + data.matches.map(matchRow).join('')
        : emptyState('🗓', when === 'next' ? 'No upcoming fixtures' : 'No results yet');
    } catch (err) {
      rows.innerHTML = emptyState('⚠', 'Could not load fixtures', err.message);
    }
  };
  load('next');

  $('#fx-when').addEventListener('click', e => {
    const b = e.target.closest('[data-when]'); if (!b) return;
    $('#fx-when').querySelectorAll('.seg-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    load(b.dataset.when);
  });
}

async function scorersPanel(ctx, lid) {
  const body = $('#lg-body');
  try {
    const data = await api.scorers(lid);
    ctx.setPill(sourcePill(data));
    const rows = data.scorers || [];
    if (!rows.length) { body.innerHTML = emptyState('👟', 'No scorers yet'); return; }
    const max = rows[0].goals || 1;

    body.innerHTML = notice(data.note) +
      (data.season ? `<div class="season-tag">Season ${esc(data.season)}</div>` : '') + `
      <div class="card"><div class="table-wrap">
      <table class="tbl">
        <thead><tr><th>#</th><th>Player</th><th>Club</th>
          <th class="num">Goals</th><th class="num col-opt">Assists</th>
          <th class="num col-opt">Apps</th><th class="col-opt" style="width:28%"></th></tr></thead>
        <tbody>${rows.map((r, i) => `
          <tr data-team="${esc(r.team_id || '')}">
            <td class="rank">${r.rank ?? i + 1}</td>
            <td><div class="team-cell">
              ${r.photo ? `<img class="sq-photo sm" src="${esc(r.photo)}" alt="" loading="lazy">` : ''}
              <b>${r.player_id
                ? `<a href="#/player/${esc(r.player_id)}">${esc(r.player)}</a>`
                : esc(r.player)}</b></div></td>
            <td><div class="team-cell">
              ${r.logo ? `<img class="crest" src="${esc(r.logo)}" alt="" loading="lazy">`
                       : `<span class="crest-fb" style="background:${esc(r.colour || '#39443e')}">${
                            esc((r.team || '?').slice(0, 3).toUpperCase())}</span>`}
              <span>${esc(r.team)}</span></div></td>
            <td class="num"><b>${r.goals}</b></td>
            <td class="num col-opt">${r.assists}</td>
            <td class="num col-opt">${r.appearances ?? '–'}</td>
            <td class="col-opt"><div class="stat-bar"><i class="h" style="width:${(r.goals / max) * 100}%"></i></div></td>
          </tr>`).join('')}
        </tbody></table></div></div>`;

    body.querySelectorAll('tbody tr').forEach(tr =>
      tr.dataset.team && tr.addEventListener('click', e => {
        if (e.target.closest('a')) return;   // let the player link win
        location.hash = `#/team/${tr.dataset.team}`;
      }));
  } catch (err) {
    body.innerHTML = emptyState('⚠', 'Could not load scorers', err.message);
  }
}

async function honoursPanel(ctx, lid) {
  const body = $('#lg-body');
  try {
    const data = await api.honours(lid);
    ctx.setPill({ text: 'Live data', cls: 'real' });
    const rows = data.honours || [];
    if (!rows.length) {
      body.innerHTML = emptyState('🏆', 'No finals on record',
        'League competitions are decided on the table, not a final.');
      return;
    }
    const champ = rows[0];
    body.innerHTML = `
      <div class="champ-card">
        <div class="champ-eyebrow">Reigning champions · ${esc(champ.season_label)}</div>
        <div class="champ-main">
          ${crest(champ.winner, 'champ-crest')}
          <div>
            <h2>${esc(champ.winner.name)}</h2>
            <div class="champ-sub">beat ${esc(champ.runner_up.name)} ${esc(champ.score)}</div>
            ${champ.venue ? `<div class="champ-venue">${esc(champ.venue)}${
              champ.date ? ' · ' + esc(champ.date) : ''}</div>` : ''}
          </div>
        </div>
      </div>
      <div class="card"><h3>Previous finals</h3>
        ${rows.slice(1).map(r => `
          <div class="honour-row">
            <span class="honour-season">${esc(r.season_label)}</span>
            <span class="honour-win">${crest(r.winner, 'honour-crest')}
              <b>${esc(r.winner.short)}</b></span>
            <span class="honour-score">${esc(r.score)}</span>
            <span class="honour-lose">${esc(r.runner_up.short)}</span>
          </div>`).join('')}
      </div>`;
  } catch (err) {
    body.innerHTML = emptyState('⚠', 'Could not load honours', err.message);
  }
}

async function ticketsPanel(ctx, lid) {
  const body = $('#lg-body');
  try {
    const data = await api.tickets(lid);
    ctx.setPill({ text: 'Official links', cls: 'real' });
    body.innerHTML = notice(
      'Every link goes straight to the club’s own box office — no resale sites.', 'info') +
      `<div class="tix-grid">${data.clubs.map(c => `
        <a class="tix-card" style="--edge:${esc(c.colour)}"
           href="${esc(c.ticket_url)}" target="_blank" rel="noopener noreferrer">
          ${crest(c, 'tix-crest')}
          <span class="info"><b>${esc(c.name)}</b><small>${esc(c.stadium)}</small></span>
          <span style="color:var(--accent);font-size:15px">🎟</span>
        </a>`).join('')}</div>`;
  } catch (err) {
    body.innerHTML = emptyState('⚠', 'Could not load ticket links', err.message);
  }
}
