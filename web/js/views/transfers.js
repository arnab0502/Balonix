// Transfer feed - grouped by club by default, with search.
import { api, bustCache } from '../api.js';
import { sourcePill } from '../components.js';
import { pitch } from '../pitch.js';
import { $, crest, emptyState, esc, money, notice, relTime, shortDate, skeleton } from '../util.js';

const state = { league: '', kind: '', group: 'club', q: '', window: 'season' };
let searchTimer = null;

export async function renderTransfers(ctx, params) {
  state.league = params.league || '';
  const root = $('#view');

  root.innerHTML = `
    <div class="page-head">
      <h1>Transfers</h1>
      <span class="sub">Ins and outs across every competition</span>
    </div>
    <div id="cov-slot"></div>

    <div class="tr-toolbar">
      <input id="tr-search" type="search" placeholder="Search player or club…"
             autocomplete="off" spellcheck="false" value="${esc(state.q)}">
      <div class="seg" id="tr-group">
        <button class="seg-btn ${state.group === 'club' ? 'active' : ''}" data-g="club">By club</button>
        <button class="seg-btn ${state.group === 'flat' ? 'active' : ''}" data-g="flat">Latest</button>
      </div>
    </div>

    <div class="filters" id="lg-filters">
      <button class="chip ${!state.league ? 'active' : ''}" data-lg="">All leagues</button>
      ${ctx.leagues.filter(l => !l.continental).map(l => `
        <button class="chip ${state.league === l.id ? 'active' : ''}" data-lg="${esc(l.id)}">
          <span class="dot" style="background:${esc(l.accent)}"></span>${esc(l.short)}
        </button>`).join('')}
    </div>
    <div class="filters" id="kind-filters">
      ${[['', 'All types'], ['transfer', 'Permanent'], ['loan', 'Loans']]
        .map(([k, label]) => `
          <button class="chip ${state.kind === k ? 'active' : ''}" data-kind="${k}">${label}</button>`).join('')}
    </div>
    <div class="filters" id="win-filters">
      ${[['season', 'This season'], ['year', 'Last 12 months'], ['all', 'All stored']]
        .map(([w, label]) => `
          <button class="chip ${state.window === w ? 'active' : ''}" data-win="${w}">${label}</button>`).join('')}
    </div>
    <div id="tr-body">${skeleton(10)}</div>`;

  const pick = (sel, attr, key) => $(sel).addEventListener('click', e => {
    const b = e.target.closest('[data-' + attr + ']'); if (!b) return;
    state[key] = b.dataset[attr];
    $(sel).querySelectorAll('.chip, .seg-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    load(ctx);
  });
  pick('#lg-filters', 'lg', 'league');
  pick('#kind-filters', 'kind', 'kind');
  pick('#tr-group', 'g', 'group');
  pick('#win-filters', 'win', 'window');

  $('#tr-search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    state.q = e.target.value.trim();
    searchTimer = setTimeout(() => load(ctx), 250);
  });

  load(ctx);
}

async function load(ctx) {
  const body = $('#tr-body');
  if (!body) return;
  body.innerHTML = skeleton(6);
  try {
    const data = await api.transfers({
      league: state.league || null, q: state.q, group: state.group,
      window: state.window, limit: 600,
    });
    ctx.setPill(sourcePill(data));
    renderCoverage(ctx, data);

    // Free transfers count as permanent moves, not their own category - a
    // free is still a permanent departure/arrival, just with no fee attached.
    const filterKind = rows => {
      if (!state.kind) return rows;
      if (state.kind === 'transfer') {
        return rows.filter(t => t.fee.kind === 'transfer' || t.fee.kind === 'free');
      }
      return rows.filter(t => t.fee.kind === state.kind);
    };

    if (state.group === 'club' && data.clubs?.length) {
      const clubs = data.clubs
        .map(c => ({ ...c, in: filterKind(c.in), out: filterKind(c.out) }))
        .filter(c => c.in.length || c.out.length);
      if (!clubs.length) { body.innerHTML = noResults(data); return; }
      body.innerHTML = notice(data.note) +
        `<div class="tr-count">${data.total_matching} moves · ${
          esc(data.window_label || '')}</div>` +
        clubs.map(clubCard).join('');
      wireAccordions(body);
      return;
    }

    const rows = filterKind(data.transfers || []);
    if (!rows.length) { body.innerHTML = noResults(data); return; }
    body.innerHTML = notice(data.note) +
      `<div class="tr-count">${rows.length} of ${data.total_matching} moves · ${
        esc(data.window_label || '')}</div>` +
      rows.map(row).join('');
  } catch (err) {
    body.innerHTML = emptyState('⚠', 'Could not load transfers', err.message);
  }
}

function noResults(data) {
  return emptyState('🔄', 'Nothing matches these filters',
    data.coverage?.clubs === 0 ? 'Run a sync to pull real data.' : 'Try widening the filters.');
}

/* ---------------------------------------------------------------- by club */
function clubCard(c) {
  // Fees are almost never published for recent windows (see README), so the
  // headline is deal mix, not spend. Money is shown only when it exists.
  const all = [...c.in, ...c.out];
  // Free transfers are permanent moves with no fee, not a category of their
  // own - counted alongside paid permanent deals.
  const perm = all.filter(t => t.fee.kind === 'transfer' || t.fee.kind === 'free').length;
  const loan = all.filter(t => t.fee.kind === 'loan').length;
  const net = c.net;
  const hasMoney = c.spent || c.received;

  return `
    <section class="club-card" data-club="${esc(c.club.id)}">
      <div class="club-head" style="--edge:${esc(c.club.colour)}" role="button" tabindex="0">
        ${crest(c.club)}
        <span class="ch-name">
          <b>${esc(c.club.name)}</b>
          <small>${c.in.length} in · ${c.out.length} out</small>
        </span>
        <span class="ch-mix">
          ${perm ? `<i class="mx transfer">${perm} perm</i>` : ''}
          ${loan ? `<i class="mx loan">${loan} loan</i>` : ''}
        </span>
        ${hasMoney ? `<span class="ch-net ${net > 0 ? 'pos' : 'neg'}">
          ${net > 0 ? '+' : '−'}${money(Math.abs(net))}<small>net</small></span>` : ''}
        <button class="xi-btn" type="button" data-xi-btn="${esc(c.club.id)}">⚽ Probable XI</button>
        <span class="ch-caret">▾</span>
      </div>
      <div class="club-body" hidden>
        ${column('In', c.in, 'in')}
        ${column('Out', c.out, 'out')}
      </div>
      <div class="club-xi" hidden data-xi="${esc(c.club.id)}"></div>
    </section>`;
}

function column(title, rows, dir) {
  if (!rows.length) return '';
  return `<div class="tr-col">
    <h4 class="tr-col-head ${dir}">${title} <span>${rows.length}</span></h4>
    ${rows.map(t => compactRow(t, dir)).join('')}
  </div>`;
}

function compactRow(t, dir) {
  const other = dir === 'in' ? t.from : t.to;
  const fee = money(t.fee.amount);
  const link = other.id
    ? `<a href="#/team/${esc(other.id)}">${esc(other.name || '?')}</a>`
    : esc(other.name || '?');
  return `<div class="tr-mini">
    <span class="tm-date">${esc(shortDate(t.date))}</span>
    <span class="tm-player">${t.player.id
      ? `<a href="#/player/${esc(t.player.id)}">${esc(t.player.name || '?')}</a>`
      : esc(t.player.name || '?')}</span>
    <span class="tm-club">${dir === 'in' ? 'from' : 'to'} ${link}</span>
    <span class="tr-kind ${esc(t.fee.kind)}">${fee || kindLabel(t.fee.kind)}</span>
  </div>`;
}

function wireAccordions(root) {
  // The header only ever toggles the In/Out list now - the probable XI has
  // its own button and opens independently, instead of being forced open or
  // closed alongside the transfer list every time.
  root.querySelectorAll('.club-head').forEach(h => {
    const toggleBody = () => {
      const body = h.nextElementSibling;
      const opening = body.hidden;
      body.hidden = !opening;
      h.classList.toggle('open', opening);
    };
    h.addEventListener('click', e => {
      if (e.target.closest('[data-xi-btn]')) return;
      toggleBody();
    });
    h.addEventListener('keydown', e => {
      if (e.target.closest('[data-xi-btn]')) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleBody(); }
    });
  });

  root.querySelectorAll('[data-xi-btn]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const xi = btn.closest('.club-card')?.querySelector('.club-xi');
      if (!xi) return;
      const opening = xi.hidden;
      xi.hidden = !opening;
      btn.classList.toggle('active', opening);
      // Fetch the XI only the first time it is actually shown - nobody wants
      // 110 lineup requests fired on page load.
      if (opening && !xi.dataset.loaded) loadXI(xi);
    });
  });
}

async function loadXI(slot) {
  slot.dataset.loaded = '1';
  slot.innerHTML = `<div class="xi-loading">Working out the probable XI…</div>`;
  try {
    const d = await api.lineup(slot.dataset.xi);
    slot.innerHTML = d.available ? pitchBlock(d)
      : `<div class="xi-loading">${esc(d.reason || 'No lineup data')}</div>`;
  } catch (err) {
    slot.innerHTML = `<div class="xi-loading">Could not build a lineup — ${esc(err.message)}</div>`;
  }
}

/* ------------------------------------------------------ probable XI */
function pitchBlock(d) {
  return `
    <div class="xi-head">
      <b>Probable XI</b>
      <span class="xi-note">${esc(d.season)} data · ${esc(d.basis)}</span>
    </div>
    ${pitch(d.xi, {
      colour: d.club.colour,
      formation: d.formation,
      title: d.club.short,
      subtitle: `${d.new_signings} signings this window`,
      stat: p => p.starts || null,
      statLabel: 'number shown is starts last season',
    })}

    ${d.arrivals?.length ? `<div class="xi-sub">
      <h4>Arrivals this window</h4>
      <div class="bench-list">${d.arrivals.map(p => `
        <a class="bench-chip is-new" href="#/player/${esc(p.id)}">★ ${esc(p.name)}${
          p.from_club ? ` · ${esc(p.from_club)}` : ''}</a>`).join('')}</div>
    </div>` : ''}

    ${d.bench?.length ? `<div class="xi-sub">
      <h4>Bench and squad</h4>
      <div class="bench-list">${d.bench.map(p => `
        <a class="bench-chip ${p.new_signing ? 'is-new' : ''}" href="#/player/${esc(p.id)}">
          <b>${p.starts ?? 0}</b>${esc(p.name)}</a>`).join('')}</div>
    </div>` : ''}

    ${d.unavailable?.length ? `<div class="xi-sub">
      <h4>Unavailable${d.unavailable[0].as_of ? ` (as of ${esc(d.unavailable[0].as_of)})` : ''}</h4>
      <div class="bench-list">${d.unavailable.map(p => `
        <span class="bench-chip out">${esc(p.name)}${p.reason ? ` · ${esc(p.reason)}` : ''}</span>`).join('')}</div>
    </div>` : ''}

    <p class="xi-caveat">Derived from the club's most-used shape, its most recent
      XI and who actually starts — not an official teamsheet.</p>`;
}


/* ----------------------------------------------------------------- latest */
function kindLabel(k) {
  return { transfer: 'Transfer', loan: 'Loan', free: 'Free',
           end_of_loan: 'Loan ended' }[k] || k;
}

function row(t) {
  const fee = money(t.fee.amount);
  const d = new Date((t.date || '') + 'T00:00:00');
  const clubLink = c => c.id
    ? `<a class="club" href="#/team/${esc(c.id)}" style="font-weight:600">${esc(c.name || '?')}</a>`
    : `<span class="club">${esc(c.name || 'Unknown')}</span>`;

  return `
    <div class="tr-row">
      <div class="tr-date">
        <b>${isNaN(d) ? '–' : d.getDate()}</b>
        ${isNaN(d) ? '' : d.toLocaleDateString([], { month: 'short' })}
      </div>
      <div class="tr-main">
        <div class="tr-player">${t.player.id
          ? `<a href="#/player/${esc(t.player.id)}">${esc(t.player.name || 'Unknown player')}</a>`
          : esc(t.player.name || 'Unknown player')}</div>
        <div class="tr-move">
          ${clubLink(t.from)}<span class="arrow">→</span>${clubLink(t.to)}
        </div>
      </div>
      <div class="tr-fee">
        <div class="amount">${fee || (t.fee.kind === 'free' ? 'Free' : '—')}</div>
        <span class="tr-kind ${esc(t.fee.kind)}">${esc(kindLabel(t.fee.kind))}</span>
      </div>
    </div>`;
}

/* --------------------------------------------------------------- coverage */
function renderCoverage(ctx, data) {
  const slot = $('#cov-slot');
  if (!slot) return;
  const cov = data.coverage;
  if (!cov) { slot.innerHTML = ''; return; }
  const pct = cov.total ? Math.round((cov.clubs / cov.total) * 100) : 0;
  if (pct >= 100) {
    slot.innerHTML = `<div class="coverage">
      <div class="grow"><b>All ${cov.total} clubs</b> swept
        <span style="color:var(--muted)">· updated ${esc(relTime(cov.updated))}</span></div>
      <button class="btn ghost" id="sync-btn">Refresh</button></div>`;
  } else {
    slot.innerHTML = `<div class="coverage">
        <div class="grow">
          <div><b>${cov.clubs}</b> of <b>${cov.total}</b> clubs swept
            <span style="color:var(--muted)">· ${esc(relTime(cov.updated))}</span></div>
          <div class="cov-bar"><i style="width:${pct}%"></i></div>
        </div>
        <button class="btn" id="sync-btn">Sync remaining</button>
      </div>`;
  }

  $('#sync-btn')?.addEventListener('click', async e => {
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = 'Syncing…';
    try {
      const res = await api.syncTransfers(200);
      bustCache('/transfers');
      btn.textContent = `+${res.swept}`;
      setTimeout(() => load(ctx), 400);
    } catch (err) {
      btn.textContent = 'Failed'; btn.title = err.message;
    } finally {
      setTimeout(() => { btn.disabled = false; btn.textContent = 'Refresh'; }, 2500);
    }
  });
}
