// Thin API client with an in-tab cache, so switching views does not refetch.

const memo = new Map();

async function req(path, { fresh = false, ttl = 30000, method = 'GET' } = {}) {
  const key = method + path;
  if (!fresh && method === 'GET') {
    const hit = memo.get(key);
    if (hit && Date.now() - hit.at < ttl) return hit.value;
  }
  const res = await fetch('/api' + path, { method });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  const value = await res.json();
  if (method === 'GET') memo.set(key, { at: Date.now(), value });
  return value;
}

export const api = {
  meta:       () => req('/meta', { ttl: 300000 }),
  home:       () => req('/home', { ttl: 120000 }),
  rumours:    ({ source, club, limit = 120 } = {}) => {
                const p = new URLSearchParams({ limit });
                if (source) p.set('source', source);
                if (club) p.set('club', club);
                return req(`/rumours?${p}`, { ttl: 300000 });
              },
  matches:    day => req(`/matches?day=${day}`, { ttl: 60000 }),
  live:       (scope = 'big5', fresh = true) => req(`/live?scope=${scope}`, { fresh, ttl: 20000 }),
  match:      id => req(`/match/${encodeURIComponent(id)}`, { ttl: 25000 }),
  standings:  lg => req(`/league/${lg}/standings`, { ttl: 600000 }),
  scorers:    lg => req(`/league/${lg}/scorers`, { ttl: 600000 }),
  honours:    lg => req(`/league/${lg}/honours`, { ttl: 3600000 }),
  leagueFixtures: (lg, when = 'next') =>
                req(`/league/${lg}/fixtures?when=${when}&count=30`, { ttl: 300000 }),
  transfers:  ({ league, q = '', group = 'club', limit = 400, window = 'season' } = {}) => {
                const p = new URLSearchParams({ limit, group, window });
                if (league) p.set('league', league);
                if (q) p.set('q', q);
                return req(`/transfers?${p}`, { ttl: 120000 });
              },
  syncTransfers: limit =>
                req(`/transfers/sync${limit ? `?limit=${limit}` : ''}`, { method: 'POST' }),
  syncSquads: limit =>
                req(`/squads/sync${limit ? `?limit=${limit}` : ''}`, { method: 'POST' }),
  team:       id => req(`/team/${encodeURIComponent(id)}`, { ttl: 300000 }),
  player:     id => req(`/player/${encodeURIComponent(id)}`, { ttl: 300000 }),
  search:     q => req(`/search?q=${encodeURIComponent(q)}`, { ttl: 120000 }),
  tickets:    lg => req(`/tickets${lg ? `?league=${lg}` : ''}`, { ttl: 600000 }),
  videos:     (full = false) => req(`/videos${full ? '?full=1' : ''}`, { ttl: 300000 }),
  health:     () => req('/health', { fresh: true }),
};

export function bustCache(prefix = '') {
  for (const k of [...memo.keys()]) if (k.includes(prefix)) memo.delete(k);
}
