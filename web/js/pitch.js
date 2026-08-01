// Shared pitch renderer. Used by match lineups and the probable XI.
//
// Deliberately not a plain list of dots: proper markings, mown stripes, a
// floodlit vignette and player tokens that carry a photo, a shirt number and
// a stat chip. Everything is CSS/SVG - no images, no libraries.
import { esc } from './util.js';

const MARKINGS = `
<svg class="pitch-lines" viewBox="0 0 100 140" preserveAspectRatio="none" aria-hidden="true">
  <rect x="2" y="2" width="96" height="136" rx="1"/>
  <line x1="2" y1="70" x2="98" y2="70"/>
  <circle cx="50" cy="70" r="13"/>
  <circle class="spot" cx="50" cy="70" r="0.9"/>
  <rect x="26" y="2"  width="48" height="20"/>
  <rect x="38" y="2"  width="24" height="8"/>
  <rect x="26" y="118" width="48" height="20"/>
  <rect x="38" y="130" width="24" height="8"/>
  <circle class="spot" cx="50" cy="15" r="0.9"/>
  <circle class="spot" cx="50" cy="125" r="0.9"/>
  <path d="M 37 22 A 13 13 0 0 0 63 22"/>
  <path d="M 37 118 A 13 13 0 0 1 63 118"/>
  <path d="M 2 6 A 4 4 0 0 0 6 2"/>
  <path d="M 98 6 A 4 4 0 0 1 94 2"/>
  <path d="M 2 134 A 4 4 0 0 1 6 138"/>
  <path d="M 98 134 A 4 4 0 0 0 94 138"/>
</svg>`;

/** Group players into rows using the provider's grid ("row:col"), falling back
 *  to the formation string when no grid is published. */
export function toLines(players, formation) {
  const hasGrid = players.some(p => p.grid);
  const rows = new Map();

  if (hasGrid) {
    for (const p of players) {
      const [r, c] = String(p.grid || '1:1').split(':').map(Number);
      if (!rows.has(r)) rows.set(r, []);
      rows.get(r).push({ ...p, _col: c || 0 });
    }
    return [...rows.entries()].sort((a, b) => a[0] - b[0])
      .map(([, line]) => line.sort((a, b) => a._col - b._col));
  }

  const shape = String(formation || '4-3-3').split('-').map(Number).filter(Boolean);
  const out = [[players[0]].filter(Boolean)];
  let i = 1;
  for (const n of shape) { out.push(players.slice(i, i + n)); i += n; }
  return out.filter(l => l.length);
}

function token(p, opts) {
  const { colour, stat, statLabel } = opts;
  const value = typeof stat === 'function' ? stat(p) : null;
  const name = lastName(p.name);
  const num = p.number ?? p.starts ?? '';
  return `
    <${p.id ? 'a' : 'div'} class="pt ${p.new_signing ? 'is-new' : ''}"
        ${p.id ? `href="#/player/${esc(p.id)}"` : ''}
        title="${esc(p.name || '')}${p.replaces ? ` — in for ${esc(p.replaces)}` : ''}">
      <span class="pt-badge" style="--jersey:${esc(colour || '#39443e')}">
        ${p.photo
          ? `<img src="${esc(p.photo)}" alt="" loading="lazy">`
          : `<em>${esc(String(num))}</em>`}
        ${value != null ? `<b class="pt-stat">${esc(String(value))}</b>` : ''}
        ${p.new_signing ? '<i class="pt-new">★</i>' : ''}
      </span>
      <span class="pt-name">${esc(name)}</span>
      ${p.replaces ? `<span class="pt-sub">for ${esc(lastName(p.replaces))}</span>` : ''}
    </${p.id ? 'a' : 'div'}>`;
}

function lastName(name = '') {
  const parts = String(name).trim().split(' ');
  return parts.length > 1 ? parts[parts.length - 1] : (name || '');
}

/**
 * @param players  array with {name, number|starts, photo, grid, new_signing}
 * @param opts     {colour, formation, title, subtitle, stat, statLabel, flip}
 */
export function pitch(players, opts = {}) {
  if (!players?.length) return '';
  const lines = toLines(players, opts.formation);
  const body = lines.map(line =>
    `<div class="pt-line">${line.map(p => token(p, opts)).join('')}</div>`).join('');

  return `
    <div class="pitch2 ${opts.flip ? 'flip' : ''}">
      ${MARKINGS}
      <div class="pitch2-glow"></div>
      ${opts.title ? `<div class="pitch2-head">
          <span class="p2-team">${esc(opts.title)}</span>
          ${opts.formation ? `<span class="p2-form">${esc(opts.formation)}</span>` : ''}
          ${opts.subtitle ? `<span class="p2-sub">${esc(opts.subtitle)}</span>` : ''}
        </div>` : ''}
      <div class="pitch2-rows">${body}</div>
      ${opts.statLabel ? `<div class="pitch2-foot">${esc(opts.statLabel)}</div>` : ''}
    </div>`;
}
