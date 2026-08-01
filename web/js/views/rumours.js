// Football Hot: news desk, transfer exclusives, and social feeds.
import { api, bustCache } from '../api.js';
import { $, emptyState, esc, notice, relTime, skeleton } from '../util.js';

const TABS = [
  { id: 'news',      label: 'News desk',   sub: 'Football news, no transfer talk' },
  { id: 'transfers', label: 'Transfers',   sub: 'Exclusives and window business' },
  { id: 'socials',   label: 'Socials',     sub: 'Top football accounts' },
];

const state = { tab: 'news', source: '', q: '' };
let searchTimer = null;
let refreshTimer = null;

/** Poll our own API while the tab is open. This never reaches the publishers -
 *  the server's cache is the only thing that talks to them. */
const REFRESH_MS = 120000;

export function stopRumourRefresh() {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
}

export async function renderRumours(ctx, params) {
  if (params.tab && TABS.some(t => t.id === params.tab)) state.tab = params.tab;
  const root = $('#view');

  root.innerHTML = `
    <div class="page-head">
      <h1>Football Hot</h1>
      <span class="sub">${esc(TABS.find(t => t.id === state.tab).sub)}</span>
    </div>
    <div class="tabs" id="fh-tabs">
      ${TABS.map(t => `
        <div class="tab ${state.tab === t.id ? 'active' : ''}" data-tab="${t.id}">${esc(t.label)}</div>`).join('')}
    </div>
    <div class="tr-toolbar">
      <input id="fh-search" type="search" placeholder="Search…"
             autocomplete="off" value="${esc(state.q)}">
    </div>
    <div class="filters" id="fh-sources"></div>
    <div id="fh-body">${skeleton(8)}</div>`;

  $('#fh-tabs').addEventListener('click', e => {
    const t = e.target.closest('.tab'); if (!t) return;
    state.tab = t.dataset.tab;
    state.source = '';
    location.hash = `#/rumours?tab=${state.tab}`;
  });

  $('#fh-search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    state.q = e.target.value.trim().toLowerCase();
    searchTimer = setTimeout(paint, 180);
  });

  let data = null;
  const load = async () => {
    try {
      data = state.tab === 'socials'
        ? await api.socials({})
        : await api.rumours({ kind: state.tab });
    } catch (err) {
      $('#fh-body').innerHTML = emptyState('⚠', 'Could not load', err.message);
      return false;
    }
    ctx.setPill({ text: state.tab === 'socials' ? 'Live socials' : 'Live feeds', cls: 'real' });
    renderSources();
    paint();
    return true;
  };

  function renderSources() {
    const box = $('#fh-sources');
    if (!box || !data) return;
    const list = state.tab === 'socials'
      ? (data.accounts || []).map(a => ({ id: a.handle, name: a.name, tier: a.tier, live: a.live }))
      : (data.sources || []).map(s => ({ id: s.id, name: s.name, tier: s.tier, live: s.live }));
    box.innerHTML = `
      <button class="chip ${!state.source ? 'active' : ''}" data-src="">All</button>
      ${list.map(s => `
        <button class="chip ${state.source === s.id ? 'active' : ''} ${s.live ? '' : 'dead'}"
                data-src="${esc(s.id)}" ${s.live ? '' : 'disabled'}>
          <span class="tier tier${s.tier}">T${s.tier}</span>${esc(s.name)}
        </button>`).join('')}`;
    box.onclick = e => {
      const b = e.target.closest('[data-src]'); if (!b || b.disabled) return;
      state.source = b.dataset.src;
      box.querySelectorAll('.chip').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      paint();
    };
  }

  function paint() {
    const body = $('#fh-body');
    if (!body || !data) return;

    if (state.tab === 'socials') {
      let rows = data.posts || [];
      if (state.source) rows = rows.filter(p => p.handle === state.source);
      if (state.q) rows = rows.filter(p => p.text.toLowerCase().includes(state.q)
                                        || p.author.toLowerCase().includes(state.q));
      body.innerHTML = rows.length
        ? `<div class="rm-count">${rows.length} posts</div>` + rows.map(postCard).join('')
        : emptyState('🔍', 'Nothing matches', 'Try another account or search term.');
      return;
    }

    let rows = data.rumours || [];
    if (state.source) rows = rows.filter(r => r.source_id === state.source);
    if (state.q) {
      rows = rows.filter(r => (r.title + ' ' + r.summary).toLowerCase().includes(state.q)
                           || r.clubs.some(c => c.short.toLowerCase().includes(state.q)));
    }
    body.innerHTML = rows.length
      ? `<div class="rm-count">${rows.length} stories</div>` + rows.map(card).join('')
      : emptyState('🔍', 'Nothing matches', 'Try another source or search term.');
  }

  if (!await load()) return;

  stopRumourRefresh();
  refreshTimer = setInterval(async () => {
    if (!document.querySelector('#fh-body')) { stopRumourRefresh(); return; }
    bustCache(state.tab === 'socials' ? '/socials' : '/rumours');
    await load();
  }, REFRESH_MS);
}

function card(r) {
  const when = r.published ? relTime(r.published) : '';
  return `
    <a class="rm-card" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">
      ${r.image ? `<img class="rm-img" src="${esc(r.image)}" alt="" loading="lazy">` : ''}
      <div class="rm-body">
        <div class="rm-top">
          <span class="rm-src"><span class="tier tier${r.tier}">T${r.tier}</span>${esc(r.source)}</span>
          ${when ? `<span class="rm-when">${esc(when)}</span>` : ''}
        </div>
        <h3 class="rm-title">${esc(r.title)}</h3>
        ${r.summary ? `<p class="rm-sum">${esc(r.summary.slice(0, 190))}${r.summary.length > 190 ? '…' : ''}</p>` : ''}
        ${r.clubs.length ? `<div class="rm-clubs">${r.clubs.map(c => `
          <span class="rm-club" style="--c:${esc(c.colour)}">${esc(c.short)}</span>`).join('')}</div>` : ''}
      </div>
      <span class="rm-go">↗</span>
    </a>`;
}

function postCard(p) {
  const when = p.published ? relTime(p.published) : '';
  const initials = (p.author || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
  return `
    <a class="sp-card" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">
      <span class="sp-avatar">${esc(initials)}</span>
      <div class="sp-body">
        <div class="sp-top">
          <b>${esc(p.author)}</b>
          <span class="sp-handle">@${esc(p.handle)}</span>
          <span class="tier tier${p.tier}">T${p.tier}</span>
          ${p.retweet ? '<span class="sp-rt">reposted</span>' : ''}
          ${when ? `<span class="sp-when">${esc(when)}</span>` : ''}
        </div>
        <p class="sp-text">${esc(p.text)}</p>
        ${p.clubs.length ? `<div class="rm-clubs">${p.clubs.map(c => `
          <span class="rm-club" style="--c:${esc(c.colour)}">${esc(c.short)}</span>`).join('')}</div>` : ''}
      </div>
      <span class="rm-go">↗</span>
    </a>`;
}
