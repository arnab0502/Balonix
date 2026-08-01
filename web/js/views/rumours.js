// Rumour mill: transfer talk aggregated from football news desks.
import { api } from '../api.js';
import { $, emptyState, esc, notice, relTime, skeleton } from '../util.js';

const state = { source: '', club: '', q: '' };
let timer = null;

export async function renderRumours(ctx, params) {
  state.club = params.club || '';
  const root = $('#view');
  root.innerHTML = `
    <div class="page-head">
      <h1>Rumour mill</h1>
      <span class="sub">Transfer talk from the desks that break it</span>
    </div>
    <div class="tr-toolbar">
      <input id="rm-search" type="search" placeholder="Search rumours, clubs, players…"
             autocomplete="off" value="${esc(state.q)}">
    </div>
    <div class="filters" id="rm-sources"></div>
    <div id="rm-body">${skeleton(8)}</div>`;

  $('#rm-search').addEventListener('input', e => {
    clearTimeout(timer);
    state.q = e.target.value.trim().toLowerCase();
    timer = setTimeout(paint, 180);
  });

  let data;
  try {
    data = await api.rumours({ club: state.club });
  } catch (err) {
    $('#rm-body').innerHTML = emptyState('⚠', 'Could not load rumours', err.message);
    return;
  }
  ctx.setPill({ text: 'Live feeds', cls: 'real' });

  $('#rm-sources').innerHTML = `
    <button class="chip ${!state.source ? 'active' : ''}" data-src="">All sources</button>
    ${data.sources.map(s => `
      <button class="chip ${state.source === s.id ? 'active' : ''} ${s.live ? '' : 'dead'}"
              data-src="${esc(s.id)}" ${s.live ? '' : 'disabled'}>
        <span class="tier tier${s.tier}">T${s.tier}</span>${esc(s.name)}
      </button>`).join('')}`;

  $('#rm-sources').addEventListener('click', e => {
    const b = e.target.closest('[data-src]'); if (!b || b.disabled) return;
    state.source = b.dataset.src;
    $('#rm-sources').querySelectorAll('.chip').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    paint();
  });

  function paint() {
    let rows = data.rumours;
    if (state.source) rows = rows.filter(r => r.source_id === state.source);
    if (state.q) {
      rows = rows.filter(r => (r.title + ' ' + r.summary).toLowerCase().includes(state.q)
                           || r.clubs.some(c => c.short.toLowerCase().includes(state.q)));
    }
    $('#rm-body').innerHTML = rows.length
      ? `<div class="rm-count">${rows.length} stories</div>` + rows.map(card).join('')
      : emptyState('🔍', 'Nothing matches', 'Try another source or search term.');
  }
  paint();
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
