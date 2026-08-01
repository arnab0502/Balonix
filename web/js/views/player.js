// Player page: profile, season stats per competition, career, transfer history.
import { api } from '../api.js';
import { $, emptyState, esc, money, shortDate, skeleton } from '../util.js';

export async function renderPlayer(ctx, params) {
  const root = $('#view');
  root.innerHTML = skeleton(6);

  let d;
  try {
    d = await api.player(params.id);
  } catch (err) {
    root.innerHTML = emptyState('⚠', 'Player not found', err.message);
    return;
  }
  ctx.setPill({ text: 'Live data', cls: 'real' });

  const p = d.profile;
  const c = d.current_club || {};
  const t = d.totals || {};
  const accent = c.club_colour || '#39443e';

  const bio = [
    p.position_long,
    p.age != null ? `${p.age} years` : '',
    p.nationality,
    p.height ? `${p.height} cm` : '',
    p.weight ? `${p.weight} kg` : '',
  ].filter(Boolean).join(' · ');

  root.innerHTML = `
    <div class="team-hero player-hero" style="--tint:${esc(accent)}22">
      ${p.photo
        ? `<img class="pl-photo" src="${esc(p.photo)}" alt="" loading="lazy">`
        : `<span class="crest-fb" style="background:${esc(accent)};width:62px;height:62px">${
             esc((p.name || '?').slice(0, 2).toUpperCase())}</span>`}
      <div>
        <h1>${esc(p.firstname && p.lastname ? `${p.firstname} ${p.lastname}` : p.name)}</h1>
        <div class="meta">${esc(bio)}</div>
        ${c.club_name ? `<div class="meta" style="margin-top:5px">
          ${c.club
            ? `<a href="#/team/${esc(c.club)}" style="color:var(--accent);font-weight:700">${esc(c.club_name)}</a>`
            : `<b style="color:var(--text-2)">${esc(c.club_name)}</b>`}
          ${p.number != null ? ` · #${p.number}` : ''}</div>` : ''}
      </div>
      <div class="spacer"></div>
      ${statTiles(t)}
    </div>

    <div class="tabs" id="pl-tabs">
      <div class="tab active" data-tab="stats">Season ${esc(d.season || '')}</div>
      <div class="tab" data-tab="competitions">By competition</div>
      <div class="tab" data-tab="career">Clubs</div>
      <div class="tab" data-tab="transfers">Transfers</div>
    </div>
    <div id="pl-body"></div>`;

  const panels = {
    stats: () => statsPanel(d),
    competitions: () => competitionsPanel(d),
    career: () => careerPanel(d),
    transfers: () => transfersPanel(d),
  };
  const body = $('#pl-body');
  body.innerHTML = panels.stats();

  $('#pl-tabs').addEventListener('click', e => {
    const tab = e.target.closest('.tab'); if (!tab) return;
    $('#pl-tabs').querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    tab.classList.add('active');
    body.innerHTML = panels[tab.dataset.tab]();
  });
}

function statTiles(t) {
  const tiles = [
    ['Apps', t.apps], ['Goals', t.goals], ['Assists', t.assists],
    ['Rating', t.rating ?? '–'],
  ];
  return `<div class="pl-tiles">${tiles.map(([k, v]) => `
    <div class="pl-tile"><b>${esc(String(v ?? 0))}</b><span>${k}</span></div>`).join('')}</div>`;
}

function statsPanel(d) {
  const rows = d.stats || [];
  if (!rows.length) return emptyState('📊', 'No appearances recorded this season');
  return `<div class="card"><div class="table-wrap">
    <table class="tbl">
      <thead><tr><th>Competition</th><th>Club</th>
        <th class="num">Apps</th><th class="num">Goals</th><th class="num">Ast</th>
        <th class="num col-opt">Mins</th><th class="num col-opt">Rating</th>
        <th class="num col-opt">Cards</th></tr></thead>
      <tbody>${rows.map(s => `
        <tr>
          <td><div class="team-cell">
            ${s.league_logo ? `<img class="crest" src="${esc(s.league_logo)}" alt="" loading="lazy">` : ''}
            <span>${esc(s.league || '')}</span></div></td>
          <td><div class="team-cell">
            ${s.team_logo ? `<img class="crest" src="${esc(s.team_logo)}" alt="" loading="lazy">` : ''}
            <span>${esc(s.team || '')}</span></div></td>
          <td class="num">${s.apps}</td>
          <td class="num"><b>${s.goals}</b></td>
          <td class="num">${s.assists}</td>
          <td class="num col-opt">${s.minutes}</td>
          <td class="num col-opt">${s.rating ?? '–'}</td>
          <td class="num col-opt">${s.yellow}${s.red ? ` / ${s.red}` : ''}</td>
        </tr>`).join('')}
      </tbody></table></div></div>`;
}

function competitionsPanel(d) {
  const comps = d.competitions || [];
  if (!comps.length) return emptyState('📊', 'No career data');
  const seasons = d.seasons_covered || [];
  const span = seasons.length
    ? `${seasons[seasons.length - 1]}–${seasons[0]}` : '';

  return rankingsBlock(d) + `
    <div class="season-tag">Data available ${esc(span)}</div>
    ${comps.map(c => `
      <div class="card comp-card">
        <div class="comp-head">
          ${c.logo ? `<img class="comp-logo" src="${esc(c.logo)}" alt="" loading="lazy">` : ''}
          <div class="comp-id">
            <b>${esc(c.competition)}</b>
            <small>${esc(c.span)}${c.country ? ' · ' + esc(c.country) : ''}</small>
          </div>
          <div class="comp-totals">
            <span><b>${c.apps}</b>apps</span>
            <span><b>${c.goals}</b>goals</span>
            <span><b>${c.assists}</b>assists</span>
            ${c.rating ? `<span><b>${c.rating}</b>rating</span>` : ''}
          </div>
        </div>
        <div class="table-wrap"><table class="tbl comp-tbl">
          <thead><tr><th>Season</th><th>Club</th>
            <th class="num">Apps</th><th class="num">G</th><th class="num">A</th>
            <th class="num col-opt">Mins</th><th class="num col-opt">Rating</th></tr></thead>
          <tbody>${c.seasons.map(r => `
            <tr>
              <td>${esc(r.season_label)}</td>
              <td><div class="team-cell">
                ${r.team_logo ? `<img class="crest" src="${esc(r.team_logo)}" alt="" loading="lazy">` : ''}
                <span>${esc(r.team || '')}</span></div></td>
              <td class="num">${r.apps}</td>
              <td class="num"><b>${r.goals}</b></td>
              <td class="num">${r.assists}</td>
              <td class="num col-opt">${r.minutes}</td>
              <td class="num col-opt">${r.rating ?? '–'}</td>
            </tr>`).join('')}
          </tbody></table></div>
      </div>`).join('')}`;
}

function rankingsBlock(d) {
  const rows = d.rankings || [];
  if (!rows.length) return '';
  return `<div class="card"><h3>League rankings</h3>
    <div class="rank-grid">${rows.map(r => `
      <div class="rank-card" style="--c:${esc(r.accent)}">
        <div class="rank-lg">${esc(r.league)} <span>${esc(r.season)}</span></div>
        ${r.goals_rank ? `<div class="rank-line"><b>#${r.goals_rank}</b>
          <span>for goals · ${r.goals}</span></div>` : ''}
        ${r.assists_rank ? `<div class="rank-line"><b>#${r.assists_rank}</b>
          <span>for assists · ${r.assists}</span></div>` : ''}
      </div>`).join('')}</div>
    <p class="rank-note">Ranked against each competition's published top-20 chart.
      No rank shown means outside the top 20.</p>
  </div>`;
}

function careerPanel(d) {
  const rows = d.career || [];
  if (!rows.length) return emptyState('🗂', 'No career data');
  return `<div class="card"><h3>Clubs and national teams</h3>
    ${rows.map(r => {
      const seasons = (r.seasons || []).slice().sort((a, b) => b - a);
      const span = seasons.length
        ? (seasons.length > 1 ? `${seasons[seasons.length - 1]}–${seasons[0]}` : `${seasons[0]}`)
        : '—';
      return `<div class="kv">
        <span>${r.club
          ? `<a href="#/team/${esc(r.club)}" style="font-weight:600">${esc(r.name)}</a>`
          : esc(r.name || '')}</span>
        <b>${esc(span)}</b></div>`;
    }).join('')}
  </div>`;
}

function transfersPanel(d) {
  const rows = d.transfers || [];
  if (!rows.length) return emptyState('🔄', 'No transfer history');
  return `<div class="card"><h3>Transfer history</h3>
    ${rows.map(t => {
      const fee = money(t.fee.amount);
      const link = club => club.id
        ? `<a href="#/team/${esc(club.id)}" style="font-weight:600">${esc(club.name || '?')}</a>`
        : esc(club.name || '?');
      return `<div class="kv">
        <span>${esc(shortDate(t.date))} · ${link(t.from)} <span style="color:var(--accent)">→</span> ${link(t.to)}</span>
        <b>${esc(fee || t.fee.label || '—')}</b>
      </div>`;
    }).join('')}
  </div>`;
}
