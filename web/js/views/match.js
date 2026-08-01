// Match detail: hero score, tickets CTA, timeline, stats, lineups, h2h.
import { api } from '../api.js';
import { formStrip, pitchBlock, sourcePill } from '../components.js';
import { pitch } from '../pitch.js';
import { api as apiClient } from '../api.js';
import { $, crest, emptyState, esc, eventIcon, kickoffTime, notice, shortDate, skeleton } from '../util.js';

const STAT_LABELS = {
  possession: 'Possession %', shots: 'Total shots', shots_on_target: 'Shots on target',
  xg: 'Expected goals (xG)', corners: 'Corners', fouls: 'Fouls',
  offsides: 'Offsides', pass_accuracy: 'Pass accuracy %',
};

export async function renderMatch(ctx, params) {
  const root = $('#view');
  root.innerHTML = skeleton(6);
  let m;
  try {
    m = await api.match(params.id);
  } catch (err) {
    root.innerHTML = emptyState('⚠', 'Match not found', err.message);
    return;
  }
  ctx.setPill(sourcePill(m));

  const st = m.status || {};
  const live = st.type === 'live';
  const started = live || st.type === 'finished';
  const t = m.tickets;

  root.innerHTML = `
    <a class="btn ghost" href="#/matches" style="margin-bottom:14px;display:inline-block">← Matches</a>

    <div class="md-hero">
      <div class="md-meta">
        <span>${esc(m.league_name || '')}</span>
        ${m.round ? `<span>· ${esc(m.round)}</span>` : ''}
        ${m.venue ? `<span>· ${esc(m.venue)}</span>` : ''}
        ${m.referee ? `<span>· Ref ${esc(m.referee)}</span>` : ''}
      </div>

      <div class="md-score">
        <div class="md-side">${crest(m.home)}<div class="nm">${esc(m.home.name)}</div></div>
        <div>
          <div class="md-nums">${started ? `${m.home.score} – ${m.away.score}`
                                         : kickoffTime(m.kickoff)}</div>
          <div class="md-state ${live ? 'live' : ''}">
            ${live ? `<span class="live-dot"></span>${esc(st.label)}`
                   : esc(st.type === 'finished' ? 'Full time'
                        : st.type === 'postponed' ? st.label : 'Kick-off')}</div>
        </div>
        <div class="md-side">${crest(m.away)}<div class="nm">${esc(m.away.name)}</div></div>
      </div>

      <div class="md-actions">
        ${t ? `<a class="btn" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">
                 🎟 ${esc(t.label)}</a>` : ''}
        <a class="btn ghost" href="#/team/${esc(m.home.id)}">${esc(m.home.short)} squad</a>
        <a class="btn ghost" href="#/team/${esc(m.away.id)}">${esc(m.away.short)} squad</a>
      </div>
      ${t && t.confidence !== 'high'
        ? `<div style="text-align:center;margin-top:9px;font-size:11.5px;color:var(--muted)">
             No direct club box-office link for this fixture — using ${esc(t.source)} fallback.</div>`
        : ''}
    </div>

    ${m.simulated ? notice('This fixture is from the simulated season — '
        + 'the free API-Football plan only serves real fixture detail for today ±1 day.') : ''}

    <div class="tabs" id="md-tabs">
      <div class="tab active" data-tab="summary">Summary</div>
      <div class="tab" data-tab="stats">Stats</div>
      <div class="tab" data-tab="ratings">Ratings</div>
      <div class="tab" data-tab="lineups">Lineups</div>
      <div class="tab" data-tab="h2h">Head to head</div>
    </div>
    <div id="md-body"></div>`;

  const panels = {
    summary: () => summaryPanel(m, started),
    stats: () => statsPanel(m),
    ratings: () => ratingsPanel(m),
    lineups: () => lineupsPanel(m),
    h2h: () => h2hPanel(m),
  };
  const body = $('#md-body');
  body.innerHTML = panels.summary();

  $('#md-tabs').addEventListener('click', e => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    $('#md-tabs').querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    tab.classList.add('active');
    body.innerHTML = panels[tab.dataset.tab]();
    wireXIButton(m, body);
  });
  wireXIButton(m, body);
}

function wireXIButton(m, body) {
  const btn = body.querySelector('#xi-load');
  if (!btn) return;
  btn.addEventListener('click', () => loadMatchXI(m, body.querySelector('#xi-slot'), btn));
}

function summaryPanel(m, started) {
  const evs = (m.events || []).filter(e => ['goal', 'card', 'subst'].includes(e.type));
  if (!started) {
    return `<div class="card">
      <h3>Form guide</h3>
      ${formRow(m.home.short, m.form?.home)}
      ${formRow(m.away.short, m.form?.away)}
    </div>` + (m.form ? '' : emptyState('⏳', 'Not started yet', 'Come back at kick-off.'));
  }
  if (!evs.length) return emptyState('📋', 'No events recorded yet');

  return `<div class="card"><h3>Timeline</h3><div class="tl">
    ${evs.map(e => `
      <div class="tl-row">
        <div class="tl-ev ${e.side === 'away' ? 'hidden-side' : ''}"
             style="${e.side === 'away' ? 'visibility:hidden' : ''}">
          ${eventBody(e)}
        </div>
        <div class="tl-min">${e.minute}'</div>
        <div class="tl-ev away" style="${e.side === 'home' ? 'visibility:hidden' : ''}">
          ${eventBody(e)}
        </div>
      </div>`).join('')}
  </div></div>`;
}

function eventBody(e) {
  return `<span class="ico">${eventIcon(e)}</span>
    <span>${esc(e.player || '')}${e.assist
      ? `<br><small>${e.type === 'subst' ? 'for ' : 'assist '}${esc(e.assist)}</small>` : ''}</span>`;
}

function formRow(name, form) {
  return `<div class="kv"><span>${esc(name)}</span>${formStrip(form)}</div>`;
}

function statsPanel(m) {
  const s = m.stats;
  if (!s || !Object.keys(s).length) return emptyState('📊', 'No stats available');
  return `<div class="card"><h3>Match stats</h3>
    ${Object.entries(s).map(([key, [h, a]]) => {
      const total = (Number(h) || 0) + (Number(a) || 0) || 1;
      return `<div class="stat">
        <div class="stat-top"><b>${h}</b><span class="lbl">${esc(STAT_LABELS[key] || key)}</span><b>${a}</b></div>
        <div class="stat-bar">
          <i class="h" style="width:${(h / total) * 100}%"></i>
          <i class="a" style="width:${(a / total) * 100}%"></i>
        </div></div>`;
    }).join('')}
  </div>`;
}

function unavailablePanel(m) {
  const u = m.unavailable;
  if (!u || (!u.home?.length && !u.away?.length)) return '';
  const col = (side, name) => !u[side]?.length ? '' : `
    <div class="tr-col">
      <h4 class="tr-col-head out">${esc(name)} <span>${u[side].length}</span></h4>
      ${u[side].map(p => `<div class="tr-mini">
        <span class="tm-player" style="grid-column:1/3">${p.id
          ? `<a href="#/player/${esc(p.id)}">${esc(p.name || '')}</a>`
          : esc(p.name || '')}</span>
        <span class="tr-kind loan">${esc(p.reason || p.type || '')}</span>
      </div>`).join('')}
    </div>`;
  return `<div class="card">
    <h3>Unavailable</h3>
    <div class="club-body" style="padding:0">
      ${col('home', m.home.short)}${col('away', m.away.short)}
    </div>
  </div>`;
}

function lineupsPanel(m) {
  const l = m.lineups;
  const un = unavailablePanel(m);
  const hasReal = l && (l.home || l.away);

  if (!hasReal) {
    // Nothing published yet - offer the probable XI for both sides instead of
    // an empty tab. Loaded lazily, since it is several upstream calls.
    return un + `
      <div class="card">
        <h3>Lineups not published yet</h3>
        <p style="font-size:13px;color:var(--text-2);line-height:1.6;margin-bottom:12px">
          Clubs release teamsheets about an hour before kick-off. Until then,
          here is the probable XI for each side.
        </p>
        <button class="btn" id="xi-load">Show probable XI</button>
      </div>
      <div id="xi-slot"></div>`;
  }

  return un + ['home', 'away'].filter(k => l[k]).map(k => {
    const t = l[k];
    return `<div class="card">
      ${t.coach ? `<div style="font-size:12px;color:var(--muted);margin-bottom:10px">
                     Coach · ${esc(t.coach)}</div>` : ''}
      ${pitch(t.starters || [], {
        colour: t.colour,
        formation: t.formation,
        title: t.team,
        subtitle: k === 'home' ? 'Home' : 'Away',
        stat: p => p.rating ?? null,
        statLabel: t.starters?.some(p => p.rating) ? 'number shown is match rating' : '',
        flip: k === 'away',
      })}
      ${t.bench?.length ? `<h3 style="margin-top:15px">Bench</h3>
        <div class="bench-list">${t.bench.map(p =>
          `<span class="bench-chip"><b>${p.number ?? ''}</b>${esc(p.name || '')}</span>`).join('')}
        </div>` : ''}
    </div>`;
  }).join('');
}

/** Fetch and render both probable XIs on the match page. */
export async function loadMatchXI(m, slot, button) {
  button.disabled = true;
  button.textContent = 'Working it out…';
  const sides = [m.home, m.away].filter(s => s && !String(s.id).startsWith('api-'));
  if (!sides.length) {
    slot.innerHTML = `<div class="card"><p style="color:var(--muted);font-size:13px">
      No squad data for these clubs.</p></div>`;
    return;
  }
  try {
    const results = await Promise.all(sides.map(s => apiClient.lineup(s.id).catch(() => null)));
    const blocks = results.map((d, i) => {
      if (!d?.available) return '';
      return `<div class="card">${pitchBlock(d, { flip: i === 1 })}</div>`;
    }).filter(Boolean).join('');
    slot.innerHTML = blocks || `<div class="card"><p style="color:var(--muted);font-size:13px">
      Could not build a probable XI for this fixture.</p></div>`;
    button.closest('.card')?.remove();
  } catch (err) {
    button.disabled = false;
    button.textContent = 'Show probable XI';
    slot.innerHTML = `<div class="card"><p style="color:var(--muted);font-size:13px">${esc(err.message)}</p></div>`;
  }
}

function h2hPanel(m) {
  const rows = m.h2h || [];
  if (!rows.length) return emptyState('🔁', 'No previous meetings on record');
  const s = m.h2h_summary || {};
  const home = m.home, away = m.away;
  const played = s.played || 0;
  const pct = n => played ? (n / played) * 100 : 0;

  // Goals per meeting, so the two clubs can be compared at a glance.
  const gf = s.gf || 0, ga = s.ga || 0, goals = gf + ga || 1;

  return `
    <div class="card h2h-card">
      <div class="h2h-top">
        <div class="h2h-team">${crest(home)}<b>${esc(home.short)}</b></div>
        <div class="h2h-count">${played}<span>meetings</span></div>
        <div class="h2h-team away"><b>${esc(away.short)}</b>${crest(away)}</div>
      </div>

      <div class="h2h-split">
        <span class="h2h-n win">${s.won || 0}</span>
        <div class="h2h-bar">
          <i class="win"  style="width:${pct(s.won || 0)}%"></i>
          <i class="draw" style="width:${pct(s.drew || 0)}%"></i>
          <i class="loss" style="width:${pct(s.lost || 0)}%"></i>
        </div>
        <span class="h2h-n loss">${s.lost || 0}</span>
      </div>
      <div class="h2h-key">
        <span>${esc(home.short)} wins</span>
        <span>${s.drew || 0} drawn</span>
        <span>${esc(away.short)} wins</span>
      </div>

      <div class="h2h-metric">
        <div class="h2h-mrow">
          <b>${gf}</b><span class="lbl">Goals scored</span><b>${ga}</b>
        </div>
        <div class="stat-bar">
          <i class="h" style="width:${(gf / goals) * 100}%"></i>
          <i class="a" style="width:${(ga / goals) * 100}%"></i>
        </div>
        <div class="h2h-mrow sub">
          <b>${played ? (gf / played).toFixed(1) : '0.0'}</b>
          <span class="lbl">per meeting</span>
          <b>${played ? (ga / played).toFixed(1) : '0.0'}</b>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Every meeting</h3>
      <div class="h2h-list">
        ${rows.map(r => {
          const done = (r.status || {}).type === 'finished';
          const hs = r.home.score, as = r.away.score;
          // Orient the result to this fixture's home side.
          const isHome = r.home.id === home.id;
          const mine = isHome ? hs : as, theirs = isHome ? as : hs;
          const res = !done ? '' : mine > theirs ? 'W' : mine === theirs ? 'D' : 'L';
          return `<a class="h2h-row" href="#/match/${esc(r.id)}">
            <span class="h2h-res ${res}">${res || '–'}</span>
            <span class="h2h-when">${esc(shortDate(r.kickoff))}</span>
            <span class="h2h-fix">
              <span class="${isHome ? 'strong' : ''}">${esc(r.home.short)}</span>
              <b>${done ? `${hs}–${as}` : esc((r.status || {}).label || '')}</b>
              <span class="${isHome ? '' : 'strong'}">${esc(r.away.short)}</span>
            </span>
            <span class="h2h-comp">${esc(r.league_name || '')}</span>
          </a>`;
        }).join('')}
      </div>
    </div>`;
}

/* ---------------------------------------------------------------- ratings */
function ratingsPanel(m) {
  const ps = m.player_stats;
  if (!ps || (!ps.home?.length && !ps.away?.length)) {
    return emptyState('\u2b50', 'No player ratings for this match',
      'Ratings appear once a match kicks off.');
  }
  return ['home', 'away'].filter(k => ps[k]?.length).map(k => `
    <div class="card">
      <h3>${esc(m[k].name)}</h3>
      ${ps[k].map(playerRatingRow).join('')}
    </div>`).join('');
}

function ratingClass(r) {
  if (r == null) return '';
  if (r >= 8) return 'great';
  if (r >= 7) return 'good';
  if (r >= 6) return 'ok';
  return 'poor';
}

function playerRatingRow(p) {
  const bits = [];
  if (p.goals) bits.push(`${p.goals} goal${p.goals > 1 ? 's' : ''}`);
  if (p.assists) bits.push(`${p.assists} assist${p.assists > 1 ? 's' : ''}`);
  if (p.shots) bits.push(`${p.shots} shot${p.shots > 1 ? 's' : ''}`);
  if (p.key_passes) bits.push(`${p.key_passes} key pass`);
  if (p.duels_won) bits.push(`${p.duels_won} duels won`);
  if (p.tackles) bits.push(`${p.tackles} tackles`);
  if (p.saves) bits.push(`${p.saves} saves`);
  if (p.passes) bits.push(`${p.passes} passes${p.pass_accuracy ? ` (${p.pass_accuracy}%)` : ''}`);

  const cards = (p.red ? '<span style="color:var(--live)">\u25ae</span>' : '')
              + (p.yellow ? '<span style="color:#ffcc33">\u25ae</span>' : '');

  return `<div class="pr-row">
    ${p.photo
      ? `<img class="sq-photo sm" src="${esc(p.photo)}" alt="" loading="lazy">`
      : `<span class="sq-num">${p.number ?? '–'}</span>`}
    <span class="pr-main">
      <span class="pr-name">${p.id
        ? `<a href="#/player/${esc(p.id)}">${esc(p.name || '')}</a>`
        : esc(p.name || '')}${p.captain ? ' <b class="pr-c">C</b>' : ''} ${cards}</span>
      <span class="pr-meta">${esc(p.position || '')} · ${p.minutes}'${
        p.substitute ? ' · sub' : ''}${bits.length ? ' · ' + esc(bits.join(' · ')) : ''}</span>
    </span>
    ${p.rating != null
      ? `<span class="pr-rating ${ratingClass(p.rating)}">${p.rating.toFixed(1)}</span>`
      : '<span class="pr-rating none">–</span>'}
  </div>`;
}
