// Landing page. Built to look alive even when nothing is kicking off:
// out of season there are no live games and often none today either, so the
// hero falls forward to the next real fixture and the page leans on transfers,
// the rumour mill and the podcast.
import { api } from '../api.js';
import { matchRow } from '../components.js';
import { $, crest, esc, emptyState, kickoffTime, money, relTime, shortDate, skeleton } from '../util.js';

export async function renderHome(ctx) {
  const root = $('#view');
  root.innerHTML = `<div class="home-skel">${skeleton(3)}</div>`;

  let d;
  try {
    d = await api.home();
  } catch (err) {
    root.innerHTML = emptyState('⚠', 'Could not load', err.message);
    return;
  }
  ctx.setPill({ text: d.live_count ? 'Live data' : 'Live data', cls: 'real' });

  root.innerHTML = `
    ${hero(d)}
    <div class="home-grid">
      <div class="home-col">
        ${rumourPanel(d)}
        ${transferPanel(d)}
      </div>
      <div class="home-col">
        ${fixturePanel(d)}
        ${leaderPanel(d)}
        ${podcastPanel(d)}
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ hero */
function hero(d) {
  const live = d.live || [];
  if (live.length) {
    return `
      <section class="hero hero-live">
        <div class="hero-glow"></div>
        <div class="hero-inner">
          <div class="hero-eyebrow"><span class="live-dot"></span>Live now · ${live.length} match${live.length === 1 ? '' : 'es'}</div>
          <div class="hero-live-grid">${live.map(liveTile).join('')}</div>
          <a class="btn" href="#/matches">All matches →</a>
        </div>
      </section>`;
  }

  const next = (d.upcoming || [])[0];
  if (next) {
    const when = new Date(next.kickoff);
    const days = Math.round((when - new Date()) / 86400000);
    return `
      <section class="hero" style="--accent-league:${esc(next.league_accent || '#c8ff2e')}">
        <div class="hero-glow"></div>
        <div class="hero-inner">
          <div class="hero-eyebrow">Next up · ${esc(next.league_name || '')}</div>
          <div class="hero-fixture">
            <div class="hf-side">${crest(next.home)}<span>${esc(next.home.short)}</span></div>
            <div class="hf-mid">
              <div class="hf-vs">vs</div>
              <div class="hf-date">${esc(when.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }))}</div>
              <div class="hf-time">${esc(kickoffTime(next.kickoff))}</div>
            </div>
            <div class="hf-side">${crest(next.away)}<span>${esc(next.away.short)}</span></div>
          </div>
          <div class="hero-actions">
            ${days > 0 ? `<span class="hero-count">${days} day${days === 1 ? '' : 's'} away</span>` : ''}
            ${next.tickets ? `<a class="btn" href="${esc(next.tickets.url)}" target="_blank"
                 rel="noopener noreferrer">🎟 Tickets</a>` : ''}
            <a class="btn ghost" href="#/matches?day=${esc((next.kickoff || '').slice(0, 10))}">See the card →</a>
          </div>
        </div>
      </section>`;
  }

  return `
    <section class="hero">
      <div class="hero-glow"></div>
      <div class="hero-inner">
        <div class="hero-eyebrow">Off season</div>
        <h1 class="hero-title">Everything football,<br><em>one place.</em></h1>
        <p class="hero-sub">Scores, tables, transfers and the rumour mill across
          six competitions — plus every episode we record.</p>
        <div class="hero-actions">
          <a class="btn" href="#/rumours">Football Hot →</a>
          <a class="btn ghost" href="#/transfers">Transfers</a>
        </div>
      </div>
    </section>`;
}

function liveTile(m) {
  return `
    <a class="lt" href="#/match/${esc(m.id)}" style="--edge:${esc(m.league_accent || '#c8ff2e')}">
      <span class="lt-min">${esc((m.status || {}).label || '')}</span>
      <span class="lt-row"><span>${esc(m.home.short)}</span><b>${m.home.score}</b></span>
      <span class="lt-row"><span>${esc(m.away.short)}</span><b>${m.away.score}</b></span>
    </a>`;
}

/* ----------------------------------------------------------------- panels */
function panel(title, href, linkText, body, extra = '') {
  return `
    <section class="hpanel">
      <div class="hpanel-head">
        <h2>${esc(title)}</h2>
        ${extra}
        ${href ? `<a class="hpanel-more" href="${href}">${esc(linkText)} →</a>` : ''}
      </div>
      ${body}
    </section>`;
}

function rumourPanel(d) {
  const rows = d.rumours || [];
  if (!rows.length) return '';
  return panel('Football Hot', '#/rumours?tab=transfers', 'See all',
    `<div class="hr-list">${rows.map(r => `
      <a class="hr-item" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">
        <span class="hr-dot" style="--c:${r.tier === 1 ? '#c8ff2e' : '#7a8699'}"></span>
        <span class="hr-main">
          <span class="hr-title">${esc(r.title)}</span>
          <span class="hr-meta">${esc(r.source)}${r.published ? ' · ' + esc(relTime(r.published)) : ''}</span>
        </span>
      </a>`).join('')}</div>`);
}

function transferPanel(d) {
  const rows = d.transfers || [];
  if (!rows.length) return '';
  return panel('Latest transfers', '#/transfers', 'All transfers',
    `<div class="ht-list">${rows.map(t => {
      const fee = money(t.fee.amount);
      const link = c => c.id
        ? `<a href="#/team/${esc(c.id)}">${esc(c.name || '?')}</a>` : esc(c.name || '?');
      return `<div class="ht-item">
        <span class="ht-date">${esc(shortDate(t.date))}</span>
        <span class="ht-main">
          <span class="ht-player">${t.player.id
            ? `<a href="#/player/${esc(t.player.id)}">${esc(t.player.name || '')}</a>`
            : esc(t.player.name || '')}</span>
          <span class="ht-move">${link(t.from)} <i>→</i> ${link(t.to)}</span>
        </span>
        <span class="tr-kind ${esc(t.fee.kind)}">${esc(fee || kindShort(t.fee.kind))}</span>
      </div>`;
    }).join('')}</div>`,
    `<span class="hpanel-tag">${esc(d.transfer_window || '')}</span>`);
}

function kindShort(k) {
  return { transfer: 'Transfer', loan: 'Loan', free: 'Free', end_of_loan: 'Loan end' }[k] || k;
}

function fixturePanel(d) {
  const rows = d.upcoming || [];
  if (!rows.length) return '';
  const day = d.upcoming_day ? shortDate(d.upcoming_day) : '';
  return panel('Next fixtures', `#/matches?day=${esc(d.upcoming_day || '')}`, 'Full calendar',
    `<div class="hf-list">${rows.map(matchRow).join('')}</div>`,
    day ? `<span class="hpanel-tag">${esc(day)}</span>` : '');
}

function leaderPanel(d) {
  const rows = d.leaders || [];
  if (!rows.length) return '';
  return panel('League leaders', null, '',
    `<div class="hl-grid">${rows.map(l => `
      <a class="hl-card" href="#/league/${esc(l.league.id)}" style="--c:${esc(l.league.accent)}">
        <div class="hl-head">${esc(l.league.short)}
          ${l.season ? `<span>${esc(l.season)}</span>` : ''}</div>
        ${l.top.map((r, i) => `
          <div class="hl-row">
            <span class="hl-rank">${i + 1}</span>
            ${crest(r.team)}
            <span class="hl-name">${esc(r.team.short)}</span>
            <b>${r.points}</b>
          </div>`).join('')}
      </a>`).join('')}</div>`);
}

function podcastPanel(d) {
  const rows = d.episodes || [];
  if (!rows.length) return '';
  return panel(d.channel?.title || 'Podcast', '#/podcast', 'All episodes',
    `<div class="hp-list">${rows.map(v => `
      <a class="hp-item" href="#/podcast">
        <span class="hp-thumb"><img src="${esc(v.thumbnail)}" alt="" loading="lazy"><i>▶</i></span>
        <span class="hp-main">
          <span class="hp-title">${esc(v.title)}</span>
          <span class="hp-meta">${v.views != null ? esc(fmtViews(v.views)) + ' views' : ''}${
            v.published_text ? ' · ' + esc(v.published_text) : ''}</span>
        </span>
      </a>`).join('')}</div>`);
}

function fmtViews(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}
