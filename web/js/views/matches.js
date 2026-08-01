// Matches feed: date strip + live block + per-competition fixture blocks.
import { api } from '../api.js';
import { leagueBlocks, matchRow, sourcePill } from '../components.js';
import { $, dayLabel, emptyState, esc, isoDay, notice, skeleton } from '../util.js';

let pollTimer = null;

export function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/** Days either side of the selected date that the strip shows. */
const STRIP_SPAN = 7;

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Date strip centred on the selected day, so you can walk the whole season
 *  rather than being stuck inside a fixed window. */
function dateStrip(active) {
  const today = isoDay(0);
  const chips = [];
  for (let i = -STRIP_SPAN; i <= STRIP_SPAN; i++) {
    const iso = addDays(active, i);
    const d = new Date(iso + 'T00:00:00');
    const dow = iso === today ? 'Today' : d.toLocaleDateString([], { weekday: 'short' });
    chips.push(`
      <button class="dchip ${iso === active ? 'active' : ''} ${iso === today ? 'is-today' : ''}"
              data-day="${iso}">
        <div class="dow">${esc(dow)}</div>
        <div class="dnum">${d.getDate()}</div>
        <div class="dmon">${esc(d.toLocaleDateString([], { month: 'short' }))}</div>
      </button>`);
  }
  return `
    <div class="datebar">
      <button class="daynav" data-jump="-7" title="Previous week">‹</button>
      <div class="datestrip" id="datestrip">${chips.join('')}</div>
      <button class="daynav" data-jump="7" title="Next week">›</button>
      <label class="daypick" title="Jump to a date">
        <span>📅</span>
        <input type="date" id="daypick" value="${esc(active)}">
      </label>
      ${active !== isoDay(0)
        ? '<button class="daynav today-btn" data-day-today="1">Today</button>' : ''}
    </div>`;
}

/** Land on today if it has anything on, otherwise the nearest day that does -
 *  no point opening on an empty "no matches" page when the season's quiet. */
async function defaultMatchDay() {
  const today = isoDay(0);
  try {
    const todayData = await api.matches(today);
    if ((todayData.matches || []).length) return today;
  } catch { /* fall through */ }
  try {
    const home = await api.home();
    if (home.upcoming_day) return home.upcoming_day;
    const resultDay = (home.results || [])[0]?.kickoff?.slice(0, 10);
    if (resultDay) return resultDay;
  } catch { /* fall through */ }
  return today;
}

export async function renderMatches(ctx, params) {
  const day = params.day || await defaultMatchDay();
  const root = $('#view');

  root.innerHTML = `
    <div class="page-head">
      <h1>${esc(dayLabel(day))}</h1>
      <span class="sub" id="match-count"></span>
    </div>
    ${dateStrip(day)}
    <div id="live-slot"></div>
    <div id="fix-slot">${skeleton(6)}</div>`;

  const goto = day => { location.hash = `#/matches?day=${day}`; };

  root.querySelectorAll('.dchip').forEach(b =>
    b.addEventListener('click', () => goto(b.dataset.day)));
  root.querySelectorAll('[data-jump]').forEach(b =>
    b.addEventListener('click', () => goto(addDays(day, Number(b.dataset.jump)))));
  root.querySelector('[data-day-today]')?.addEventListener('click', () => goto(isoDay(0)));
  root.querySelector('#daypick')?.addEventListener('change', e => {
    if (e.target.value) goto(e.target.value);
  });

  // Keep the selected chip in view on narrow screens.
  const strip = root.querySelector('#datestrip');
  const activeChip = strip?.querySelector('.dchip.active');
  if (strip && activeChip) {
    strip.scrollLeft = activeChip.offsetLeft - strip.clientWidth / 2 + activeChip.clientWidth / 2;
  }

  // ---- live block (its own refresh cadence) ----
  const paintLive = async () => {
    const slot = $('#live-slot');
    if (!slot) { stopPolling(); return; }
    try {
      const data = await api.live('big5');
      const rows = data.matches || [];
      if (rows.length) {
        slot.innerHTML = `
          <section class="lg-block">
            <div class="lg-head">
              <span class="bar" style="background:var(--live)"></span>
              <h3><span class="live-dot"></span>Live now</h3>
              <span class="country">${rows.length} in play</span>
            </div>
            ${rows.map(matchRow).join('')}
          </section>`;
      } else {
        slot.innerHTML = '';
      }
      ctx.setPill(sourcePill(data));
      // Respect the server's budget-aware cadence; 0 means stop.
      const secs = data.poll_seconds ?? 0;
      stopPolling();
      if (secs > 0) pollTimer = setInterval(paintLive, secs * 1000);
    } catch (err) {
      slot.innerHTML = '';
      stopPolling();
    }
  };
  paintLive();

  // ---- fixtures for the chosen day ----
  try {
    const data = await api.matches(day);
    const slot = $('#fix-slot');
    if (!slot) return;
    const rows = data.matches || [];
    const count = $('#match-count');
    if (count) count.textContent = rows.length ? `${rows.length} matches` : '';

    slot.innerHTML =
      notice(data.note, data.real_result_empty ? 'info' : 'warn') +
      (rows.length
        ? leagueBlocks(rows, ctx.leagueMeta)
        : emptyState('🗓', 'No matches on this date',
                     'Pick another day from the strip above.'));
    if (!$('#live-slot')?.innerHTML) ctx.setPill(sourcePill(data));
  } catch (err) {
    $('#fix-slot').innerHTML = emptyState('⚠', 'Could not load fixtures', err.message);
  }
}

/** Standalone "everything live worldwide" view. */
export async function renderLive(ctx) {
  const root = $('#view');
  root.innerHTML = `
    <div class="page-head"><h1>Live now</h1>
      <span class="sub">Every match in play across the competitions we cover</span></div>
    <div id="all-live">${skeleton(8)}</div>`;
  try {
    const data = await api.live('big5');
    const rows = data.matches || [];
    ctx.setPill(sourcePill(data));
    $('#all-live').innerHTML = rows.length
      ? leagueBlocks(rows, ctx.leagueMeta)
      : emptyState('😴', 'Nothing in play', 'No matches kicking off right now.');
  } catch (err) {
    $('#all-live').innerHTML = emptyState('⚠', 'Could not load live matches', err.message);
  }
}
