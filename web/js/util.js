// Small shared helpers. No framework, no build step.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function monogram(side) {
  return (side?.tla || side?.short || side?.name || '?').slice(0, 3).toUpperCase();
}

/** Club crest: real logo when the provider gave us one, else a coloured monogram.
 *  Failures are handled by the delegated listener below, never by inline JS -
 *  a club named O'Higgins would otherwise break out of an onerror string. */
export function crest(side, cls = 'crest') {
  const colour = side?.colour || '#39443e';
  if (side?.logo) {
    return `<img class="${cls}" src="${esc(side.logo)}" alt="" loading="lazy"
             data-fb="${esc(monogram(side))}" data-fb-cls="${esc(cls)}"
             data-fb-colour="${esc(colour)}">`;
  }
  return `<span class="${cls}-fb" style="background:${esc(colour)}">${esc(monogram(side))}</span>`;
}

/** Swap broken crest images for their monogram. Capture phase: `error` on
 *  <img> does not bubble. */
export function installCrestFallback() {
  document.addEventListener('error', e => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || !img.dataset.fb) return;
    const span = document.createElement('span');
    span.className = `${img.dataset.fbCls || 'crest'}-fb`;
    span.textContent = img.dataset.fb;
    span.style.background = img.dataset.fbColour || '#39443e';
    img.replaceWith(span);
  }, true);
}

export function kickoffTime(iso) {
  if (!iso) return '--:--';
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function dayLabel(iso) {
  const d = new Date(iso + 'T00:00:00');
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((d - today) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
}

export function shortDate(iso) {
  if (!iso) return '';
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso);
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

export function isoDay(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

export function money(amount) {
  if (!amount) return null;
  if (amount >= 1_000_000) {
    const m = amount / 1_000_000;
    return `€${m % 1 === 0 ? m.toFixed(0) : m.toFixed(1)}m`;
  }
  return `€${Math.round(amount / 1000)}k`;
}

export function relTime(iso) {
  if (!iso) return 'never';
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 90) return 'just now';
  if (secs < 5400) return `${Math.round(secs / 60)}m ago`;
  if (secs < 172800) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

export const EVENT_ICON = {
  goal: '⚽',
  card: '▮',
  subst: '⇄',
  var: 'VAR',
  other: '•',
};

export function eventIcon(ev) {
  if (ev.type === 'goal') return '⚽';
  if (ev.type === 'card') {
    return (ev.detail || '').toLowerCase().includes('red')
      ? '<span style="color:#ff4747">▮</span>'
      : '<span style="color:#ffcc33">▮</span>';
  }
  if (ev.type === 'subst') return '<span style="color:#35d07f">⇄</span>';
  return '•';
}

export function skeleton(n = 5) {
  return Array.from({ length: n }, () => '<div class="skeleton"></div>').join('');
}

export function emptyState(icon, title, sub = '') {
  return `<div class="empty"><div class="big">${icon}</div>
    <div style="font-weight:700;color:var(--text-2);margin-bottom:4px">${esc(title)}</div>
    ${sub ? `<div style="font-size:13px">${esc(sub)}</div>` : ''}</div>`;
}

export function notice(text, kind = 'warn') {
  if (!text) return '';
  const icon = kind === 'info' ? 'ℹ' : '⚠';
  return `<div class="notice ${kind === 'info' ? 'info' : ''}">
    <span>${icon}</span><div>${text}</div></div>`;
}
