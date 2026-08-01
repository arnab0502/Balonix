// Router + app shell.
import { api } from './api.js';
import { $, $$, esc, installCrestFallback } from './util.js';
import { renderMatches, renderLive, stopPolling } from './views/matches.js';
import { renderMatch } from './views/match.js';
import { renderLeague } from './views/league.js';
import { renderTransfers } from './views/transfers.js';
import { renderTeam } from './views/team.js';
import { renderPlayer } from './views/player.js';
import { renderTickets } from './views/tickets.js';
import { renderVideos } from './views/videos.js';

const NAV = [
  { id: 'matches',   href: '#/matches',   icon: '⚽', label: 'Matches' },
  { id: 'live',      href: '#/live',      icon: '🔴', label: 'Live' },
  { id: 'transfers', href: '#/transfers', icon: '🔄', label: 'Transfers' },
  { id: 'tickets',   href: '#/tickets',   icon: '🎟', label: 'Tickets' },
  { id: 'podcast',   href: '#/podcast',   icon: '🎙', label: 'Podcast' },
];

const ctx = {
  leagues: [],
  leagueMeta: {},
  meta: null,
  setPill(pill) {
    const el = $('#src-pill');
    if (!el) return;
    if (!pill?.text) { el.hidden = true; return; }
    el.hidden = false;
    el.textContent = pill.text;
    el.className = `src-pill ${pill.cls || ''}`;
  },
};

// --------------------------------------------------------------------------
// Routing
// --------------------------------------------------------------------------
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '') || 'matches';
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(qs || ''));
  return { route: parts[0] || 'matches', id: parts[1], params };
}

const ROUTES = {
  matches:   (c, p) => renderMatches(c, p),
  live:      (c) => renderLive(c),
  match:     (c, p) => renderMatch(c, p),
  league:    (c, p) => renderLeague(c, p),
  transfers: (c, p) => renderTransfers(c, p),
  team:      (c, p) => renderTeam(c, p),
  player:    (c, p) => renderPlayer(c, p),
  tickets:   (c) => renderTickets(c),
  podcast:   (c) => renderVideos(c),
};

async function route() {
  stopPolling();
  const { route: name, id, params } = parseHash();
  const handler = ROUTES[name] || ROUTES.matches;
  markActive(name, id);
  closeRail();
  window.scrollTo(0, 0);
  ctx.setPill(null);
  try {
    await handler(ctx, { ...params, id });
  } catch (err) {
    $('#view').innerHTML = `<div class="empty"><div class="big">⚠</div>
      <div>Something broke rendering this page.</div>
      <div style="font-size:13px;margin-top:6px">${esc(err.message)}</div></div>`;
    console.error(err);
  }
}

function markActive(name, id) {
  $$('.rail-link').forEach(a =>
    a.classList.toggle('active', a.dataset.nav === name));
  $$('.tabbar a').forEach(a =>
    a.classList.toggle('active', a.dataset.nav === name));
  $$('.lg-link').forEach(a =>
    a.classList.toggle('active', name === 'league' && a.dataset.lg === id));
}

// --------------------------------------------------------------------------
// Shell chrome
// --------------------------------------------------------------------------
function buildNav() {
  $('#rail-nav').innerHTML = NAV.map(n => `
    <a class="rail-link" data-nav="${n.id}" href="${n.href}">
      <span class="rail-ico">${n.icon}</span>${n.label}
      ${n.id === 'live' ? '<span class="count" id="live-count" hidden></span>' : ''}
    </a>`).join('');

  $('#tabbar').innerHTML = NAV.map(n => `
    <a data-nav="${n.id}" href="${n.href}">
      <span class="ti">${n.icon}</span>${n.label}
    </a>`).join('');

  $('#rail-leagues').innerHTML = ctx.leagues.map(l => `
    <a class="lg-link" data-lg="${esc(l.id)}" href="#/league/${esc(l.id)}">
      <span class="lg-dot" style="background:${esc(l.accent)}"></span>${esc(l.short)}
    </a>`).join('');
}

function renderQuota(q) {
  const el = $('#quota-widget');
  if (!el || !ctx.meta?.live) { if (el) el.innerHTML = ''; return; }
  const used = q.total_spent;
  const pct = Math.min(100, Math.round((used / q.plan_limit) * 100));
  const cls = pct > 85 ? 'danger' : pct > 60 ? 'warn' : '';
  el.innerHTML = `
    <div class="quota-head"><b>API budget</b><span>${used}/${q.plan_limit}</span></div>
    <div class="qbar ${cls}"><i style="width:${pct}%"></i></div>
    ${Object.entries(q.buckets).map(([name, b]) => `
      <div class="quota-row"><span>${name}</span><b>${b.spent}/${b.limit}</b></div>`).join('')}
    <div class="quota-row" style="margin-top:6px">
      <span>poll</span><b>${q.poll_seconds ? q.poll_seconds + 's' : 'paused'}</b></div>`;
}

async function refreshQuota() {
  try {
    const h = await api.health();
    renderQuota(h.quota);
  } catch { /* non-fatal */ }
}

// --------------------------------------------------------------------------
// Search
// --------------------------------------------------------------------------
function wireSearch() {
  const input = $('#search');
  const box = $('#search-results');
  let timer;

  const close = () => { box.hidden = true; };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    timer = setTimeout(async () => {
      try {
        const r = await api.search(q);
        const bits = [];
        if (r.leagues?.length) {
          bits.push('<div class="sr-group">Competitions</div>');
          bits.push(...r.leagues.map(l =>
            `<div class="sr-item" data-go="#/league/${esc(l.id)}">
               <span class="lg-dot" style="background:${esc(l.accent)}"></span>${esc(l.name)}</div>`));
        }
        if (r.teams?.length) {
          bits.push('<div class="sr-group">Clubs</div>');
          bits.push(...r.teams.map(t =>
            `<div class="sr-item" data-go="#/team/${esc(t.id)}">
               <span class="crest-fb" style="background:${esc(t.colour)}">${esc(t.tla)}</span>
               ${esc(t.name)}<small>${esc(t.stadium)}</small></div>`));
        }
        if (r.players?.length) {
          bits.push('<div class="sr-group">Players</div>');
          bits.push(...r.players.map(p =>
            `<div class="sr-item" data-go="#/player/${esc(p.id)}">
               ${p.photo
                 ? `<img class="sr-photo" src="${esc(p.photo)}" alt="" loading="lazy">`
                 : `<span class="crest-fb" style="background:${esc(p.club_colour || '#39443e')}">${
                      esc((p.position || '?').slice(0, 2))}</span>`}
               <span>${esc(p.name)}<br>
                 <small style="color:var(--muted)">${esc(p.position || '')}${
                   p.number != null ? ` · #${p.number}` : ''}</small></span>
               <small>${esc(p.club_name || '')}</small></div>`));
        }
        box.innerHTML = bits.length ? bits.join('')
          : '<div class="sr-item" style="color:var(--muted)">No matches</div>';
        box.hidden = false;
      } catch { close(); }
    }, 220);
  });

  box.addEventListener('click', e => {
    const item = e.target.closest('[data-go]');
    if (!item) return;
    location.hash = item.dataset.go;
    input.value = '';
    close();
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('.search-wrap')) close();
  });
  input.addEventListener('keydown', e => { if (e.key === 'Escape') { input.blur(); close(); } });
}

// --------------------------------------------------------------------------
// Mobile rail
// --------------------------------------------------------------------------
function closeRail() {
  $('#rail')?.classList.remove('open');
  const s = $('#scrim'); if (s) s.hidden = true;
  document.body.style.overflow = '';
}

function wireRail() {
  $('#mobile-menu').addEventListener('click', () => {
    $('#rail').classList.add('open');
    $('#scrim').hidden = false;
    document.body.style.overflow = 'hidden';   // stop the page scrolling behind
  });
  $('#scrim').addEventListener('click', closeRail);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeRail(); });

  // Swipe the drawer closed.
  let x0 = null;
  const rail = $('#rail');
  rail.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; }, { passive: true });
  rail.addEventListener('touchend', e => {
    if (x0 !== null && e.changedTouches[0].clientX - x0 < -55) closeRail();
    x0 = null;
  }, { passive: true });
}

// --------------------------------------------------------------------------
// Global click delegation: match rows open detail, ticket links do not.
// --------------------------------------------------------------------------
document.addEventListener('click', e => {
  const row = e.target.closest('.match');
  if (!row) return;
  if (e.target.closest('[data-stop]') || e.target.closest('a')) return;
  location.hash = `#/match/${row.dataset.match}`;
});

// --------------------------------------------------------------------------
// Boot
// --------------------------------------------------------------------------
(async function boot() {
  try {
    ctx.meta = await api.meta();
    ctx.leagues = ctx.meta.leagues || [];
    ctx.leagueMeta = Object.fromEntries(ctx.leagues.map(l => [l.id, l]));
    renderQuota(ctx.meta.quota);
  } catch (err) {
    console.error('meta failed', err);
  }
  installCrestFallback();
  buildNav();
  wireSearch();
  wireRail();
  window.addEventListener('hashchange', route);
  if (!location.hash) location.hash = '#/matches';
  route();
  setInterval(refreshQuota, 30000);
})();
