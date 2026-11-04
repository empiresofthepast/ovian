import { AdminPlayer } from './models';

export type AdminFilter = 'all' | 'online' | 'connected' | 'own_city' | 'never';

export const ADMIN_FILTERS: { id: AdminFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'online', label: 'Online now' },
  { id: 'connected', label: 'Have logged in' },
  { id: 'own_city', label: 'With their own city' },
  { id: 'never', label: 'Never logged in' },
];

export function filterPlayers(players: AdminPlayer[], filter: AdminFilter, query: string): AdminPlayer[] {
  const q = query.trim().toLowerCase();
  return players.filter((p) => {
    if (q && !p.username.toLowerCase().includes(q) && !p.cities.some((c) => c.name.toLowerCase().includes(q))) return false;
    switch (filter) {
      case 'online': return p.online;
      case 'connected': return p.connected;
      case 'own_city': return p.own_cities > 0;
      case 'never': return !p.connected;
      default: return true;
    }
  });
}

/** "just now", "5 min ago", "3 h ago", "2 days ago", or "never". */
export function ago(at: number | null, now: number): string {
  if (!at) return 'never';
  const s = Math.max(0, Math.round((now - at) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86_400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86_400)} days ago`;
}
