// Podcast tab: episodes from the configured YouTube channel.
import { api } from '../api.js';
import { $, emptyState, esc, notice, relTime, skeleton } from '../util.js';

let state = { q: '', playing: null, showAll: false };

export async function renderVideos(ctx) {
  const root = $('#view');
  root.innerHTML = skeleton(4);

  let d;
  try {
    d = await api.videos(state.showAll);
  } catch (err) {
    root.innerHTML = emptyState('⚠', 'Could not load episodes', err.message);
    return;
  }

  if (!d.configured) {
    root.innerHTML = setupCard(d);
    return;
  }

  ctx.setPill({ text: 'YouTube', cls: 'real' });
  const ch = d.channel || {};
  const title = ch.title || 'Podcast';

  root.innerHTML = `
    <div class="page-head">
      <h1>${esc(title)}</h1>
      <span class="sub">${d.count} episode${d.count === 1 ? '' : 's'}</span>
      ${ch.url ? `<a class="btn ghost" style="margin-left:auto"
          href="${esc(ch.url)}" target="_blank" rel="noopener noreferrer">
          Open on YouTube ↗</a>` : ''}
    </div>

    <div id="player-slot"></div>

    <div class="tr-toolbar">
      <input id="vid-search" type="search" placeholder="Search episodes…"
             autocomplete="off" value="${esc(state.q)}">
      ${d.has_api_key ? `
        <div class="seg" id="vid-scope">
          <button class="seg-btn ${!state.showAll ? 'active' : ''}" data-all="">Latest</button>
          <button class="seg-btn ${state.showAll ? 'active' : ''}" data-all="1">All episodes</button>
        </div>` : ''}
    </div>

    ${d.source === 'rss' && !d.has_api_key && d.count >= 15 ? notice(
      'Showing the latest 15 episodes from the channel feed. Add '
      + '<b>TF_YOUTUBE_API_KEY</b> to <b>.env</b> for the full back catalogue.', 'info') : ''}

    <div id="vid-grid"></div>`;

  const grid = $('#vid-grid');
  const paint = () => {
    const q = state.q.toLowerCase();
    const rows = q
      ? d.videos.filter(v => (v.title || '').toLowerCase().includes(q)
                          || (v.description || '').toLowerCase().includes(q))
      : d.videos;
    grid.innerHTML = rows.length
      ? `<div class="vid-grid">${rows.map(card).join('')}</div>`
      : emptyState('🔍', 'No episodes match that search');
  };
  paint();

  let t;
  $('#vid-search').addEventListener('input', e => {
    clearTimeout(t);
    state.q = e.target.value.trim();
    t = setTimeout(paint, 180);
  });

  $('#vid-scope')?.addEventListener('click', e => {
    const b = e.target.closest('[data-all]'); if (!b) return;
    state.showAll = !!b.dataset.all;
    renderVideos(ctx);
  });

  grid.addEventListener('click', e => {
    const c = e.target.closest('[data-video]');
    if (!c) return;
    play(c.dataset.video, c.dataset.title);
  });
}

function play(id, title) {
  state.playing = id;
  const slot = $('#player-slot');
  if (!slot) return;
  slot.innerHTML = `
    <div class="player-wrap">
      <div class="player-frame">
        <iframe src="https://www.youtube-nocookie.com/embed/${esc(id)}?autoplay=1&rel=0"
                title="${esc(title || 'Episode')}" allowfullscreen
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture"
                referrerpolicy="strict-origin-when-cross-origin" frameborder="0"></iframe>
      </div>
      <div class="player-bar">
        <b>${esc(title || '')}</b>
        <button class="btn ghost" id="close-player">Close</button>
      </div>
    </div>`;
  $('#close-player').addEventListener('click', () => {
    slot.innerHTML = '';
    state.playing = null;
  });
  slot.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function card(v) {
  const when = v.published ? relTime(v.published) : (v.published_text || '');
  const views = v.views != null ? fmtViews(v.views) : null;
  return `
    <article class="vid-card" data-video="${esc(v.id)}" data-title="${esc(v.title || '')}">
      <div class="vid-thumb">
        <img src="${esc(v.thumbnail)}" alt="" loading="lazy">
        <span class="vid-play">▶</span>
      </div>
      <div class="vid-body">
        <h3 class="vid-title">${esc(v.title || 'Untitled')}</h3>
        <div class="vid-meta">
          ${views ? `<span>${esc(views)} views</span>` : ''}
          ${when ? `<span>${esc(when)}</span>` : ''}
        </div>
      </div>
    </article>`;
}

function fmtViews(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

function setupCard(d) {
  return `
    <div class="page-head"><h1>Podcast</h1></div>
    ${notice(esc(d.note || 'Not configured yet.'), 'info')}
    <div class="card">
      <h3>Connect your channel</h3>
      <p style="font-size:13.5px;color:var(--text-2);line-height:1.6">
        Open <b>.env</b>, set <b>TF_YOUTUBE_CHANNEL</b> to your channel, and restart
        the server. Any of these work:
      </p>
      <div class="kv"><span>Handle</span><b>@YourChannel</b></div>
      <div class="kv"><span>Channel URL</span><b>youtube.com/@YourChannel</b></div>
      <div class="kv"><span>Channel id</span><b>UCxxxxxxxxxxxxxxxxxxxxxx</b></div>
      <p style="font-size:13px;color:var(--muted);margin-top:14px">
        No API key needed — the latest 15 episodes come from the channel's public
        RSS feed. Add <b>TF_YOUTUBE_API_KEY</b> only if you want the full back
        catalogue.
      </p>
    </div>`;
}
