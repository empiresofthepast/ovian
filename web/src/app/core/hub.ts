import { Injectable, inject, signal } from '@angular/core';
import { ApiError } from './api.service';
import { CONFIG, SelectedWorld, WORLD_KEY, apiBase } from './config';

/** A badge as the hub and the worlds show it. */
export interface Badge {
  id: string;
  name: string;
  icon: string;
  color: string;
  kind: 'founder' | 'patron' | 'award';
  description?: string;
}

export interface BadgeDef extends Badge {
  description: string;
  patreon_tier: string | null;
  sort: number;
  holders: number;
}

export interface HubProfile {
  account_id: number;
  username: string;
  founder: boolean;
  founder_no: number | null;
  patron: boolean;
  badges: Badge[];
}

export interface HubMe extends HubProfile {
  email: string | null;
  is_admin: boolean;
  created_at: number;
  founder_since: number | null;
  patreon: { patron_status: string | null; tier_ids: string[]; cents: number; linked_at: number } | null;
  patreon_enabled: boolean;
  worlds: { world_id: string; player_id: number; joined_at: number }[];
}

export type WorldStatus = 'upcoming' | 'open' | 'closed' | 'ended';

export interface HubWorld {
  id: string;
  name: string;
  description: string;
  pack: string;
  speed: number;
  api_url: string;
  status: WorldStatus;
  founders_only: boolean;
  patrons_early: boolean;
  starts_at: number | null;
  ends_at: number | null;
  sort: number;
  players: number;
  /** /me/worlds only */
  player_id?: number | null;
  joined?: boolean;
  can_enter?: boolean;
  /** why not: world_upcoming, world_closed, world_ended, early_access_only */
  blocked?: string | null;
}

/** A world the spawner runs on this machine (server + broker containers, its own database). */
export interface SpawnedWorld {
  id: string;
  pack: string;
  speed: number;
  database: string;
  api_url: string;
  internal_url: string;
  mqtt_url: string;
  /** running | stopped | partial | absent */
  state: string;
  containers: { service: string; state: string; status: string; image: string }[];
  overrides: Record<string, unknown>;
}

/** One tunable group of a content pack: its code defaults and whether leaving it out switches the feature off. */
export interface SettingsGroup { key: string; doc: string; off_when_absent: boolean; defaults: unknown; current?: unknown; present?: boolean }

export interface SpawnerSchema {
  /** False: this hub has no spawner configured. */
  enabled: boolean;
  world: { doc: string; defaults: Record<string, unknown> };
  groups: SettingsGroup[];
  modes: Record<string, { name: string; doc: string; overrides: Record<string, unknown> }>;
}

export interface SpawnRequest {
  id: string;
  name: string;
  description?: string;
  pack?: string;
  speed?: number;
  mode?: string;
  /** {world: {...}, extensions: {...}}, merged after the mode's preset; null removes a group. */
  overrides?: Record<string, unknown>;
  status?: 'upcoming' | 'open' | 'closed';
  founders_only?: boolean;
  patrons_early?: boolean;
  starts_at?: number | null;
  ends_at?: number | null;
  local_registration?: boolean;
}

export interface AdminAccount {
  id: number;
  username: string;
  email: string | null;
  created_at: number;
  last_login_at: number | null;
  is_admin: boolean;
  founder: boolean;
  founder_no: number | null;
  patron_status: string | null;
  cents: number | null;
  badges: string[];
}

export interface WorldForm {
  name: string;
  description?: string;
  pack?: string;
  speed?: number;
  api_url: string;
  internal_url?: string;
  status?: WorldStatus;
  founders_only?: boolean;
  patrons_early?: boolean;
  starts_at?: number | null;
  ends_at?: number | null;
  sort?: number;
}

export interface BadgeForm {
  name: string;
  description?: string;
  icon?: string;
  color?: string;
  kind?: 'founder' | 'patron' | 'award';
  patreon_tier?: string | null;
  sort?: number;
}

/** What entering a world needs from the player the first time. */
export interface EnterOptions {
  /** first visit: the people to found a city with (error tribe_required without it) */
  tribe?: string;
  /** when the account's name is taken in that world (username_taken / link_required) */
  username?: string;
  /** link_required: the password of the player who already lives there under this name */
  password?: string;
}

const HUB_TOKEN_KEY = 'ovian.hub.token';
const TOKEN_KEY = 'ovian.token';

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // storage unavailable: the session lasts until the page closes
  }
}

/**
 * The hub: one account for every world, founders, badges, Patreon and the list of worlds.
 * Only present when config.json has a hubUrl. After {@link enter} the page must be reloaded
 * (``location.assign``) so the API, the broker and the engine point at the chosen world.
 */
@Injectable({ providedIn: 'root' })
export class Hub {
  private readonly cfg = inject(CONFIG);
  readonly enabled = !!this.cfg.hubUrl;
  private readonly base = (this.cfg.hubUrl ?? '') + '/api/v1';
  readonly token = signal<string | null>(read(HUB_TOKEN_KEY));
  /** the world this page plays, if chosen through the hub */
  readonly worldId = this.cfg.worldId ?? null;

  setToken(token: string | null): void {
    this.token.set(token);
    write(HUB_TOKEN_KEY, token);
  }

  /** Forget the hub login and the chosen world (logging out of everything). */
  logout(): void {
    this.setToken(null);
    write(WORLD_KEY, null);
    write(TOKEN_KEY, null);
  }

  private async call<T>(method: string, path: string, body?: unknown, base = this.base, token = this.token()): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers['Authorization'] = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new ApiError(0, 'network', 'The server cannot be reached.');
    }
    const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401 && base === this.base && token) this.setToken(null);
      const detail = Array.isArray(data.detail) ? data.detail.map((d: any) => d.msg).join(', ') : undefined;
      throw new ApiError(res.status, data.error ?? 'error', data.message ?? detail ?? res.statusText);
    }
    return data as T;
  }

  // ---- account
  async register(username: string, password: string, email?: string): Promise<HubProfile> {
    const r = await this.call<{ token: string; account: HubProfile }>('POST', '/auth/register', { username, password, email: email || null });
    this.setToken(r.token);
    return r.account;
  }
  async login(username: string, password: string): Promise<HubProfile> {
    const r = await this.call<{ token: string; account: HubProfile }>('POST', '/auth/login', { username, password });
    this.setToken(r.token);
    return r.account;
  }
  me() { return this.call<HubMe>('GET', '/me'); }
  changePassword(password: string, new_password: string) { return this.call<{ ok: boolean }>('POST', '/me/password', { password, new_password }); }
  profile(username: string) { return this.call<HubProfile>('GET', `/accounts/${encodeURIComponent(username)}`); }
  founders() { return this.call<{ username: string; founder_no: number | null; founder_since: number | null }[]>('GET', '/founders'); }
  badges() { return this.call<BadgeDef[]>('GET', '/badges'); }

  // ---- Patreon: send the browser to the returned url; it comes back to /?patreon=linked|cancelled|error|patreon_taken
  patreonConnect() { return this.call<{ url: string }>('GET', '/patreon/connect'); }
  patreonUnlink() { return this.call<{ ok: boolean }>('DELETE', '/me/patreon'); }

  // ---- worlds
  worlds() { return this.call<HubWorld[]>('GET', '/worlds'); }
  myWorlds() { return this.call<HubWorld[]>('GET', '/me/worlds'); }

  /**
   * Log into a world with the hub account, founding a player there on the first visit.
   * Throws ApiError tribe_required (ask for a people), username_taken (ask for another name),
   * link_required (a player of this name lives there: ask for its password, or another name).
   * On success the world and its token are stored; reload the page to play it.
   */
  async enter(world: HubWorld, opts: EnterOptions = {}): Promise<{ joined: boolean; village_id: number | null }> {
    const { ticket } = await this.call<{ ticket: string }>('POST', `/worlds/${encodeURIComponent(world.id)}/ticket`);
    const api = apiBase(world.api_url) + '/api/v1';
    const r = opts.password
      ? await this.call<any>('POST', '/auth/hub/link', { ticket, password: opts.password, username: opts.username || null }, api, null)
      : await this.call<any>('POST', '/auth/hub', { ticket, tribe: opts.tribe || null, username: opts.username || null }, api, null);
    const info = await this.call<{ mqtt_url: string }>('GET', '/world', undefined, api, null);
    const chosen: SelectedWorld = { id: world.id, name: world.name, apiUrl: world.api_url, mqttUrl: info.mqtt_url };
    write(WORLD_KEY, JSON.stringify(chosen));
    write(TOKEN_KEY, r.token);
    return { joined: !!r.joined, village_id: r.village_id ?? null };
  }

  /** The tribes a world offers, for the first visit (its content pack). */
  async tribes(world: HubWorld): Promise<{ id: string; name: string; description?: string }[]> {
    const pack = await this.call<any>('GET', '/content', undefined, apiBase(world.api_url) + '/api/v1', null);
    return pack.tribes ?? [];
  }

  // ---- administration (is_admin)
  adminAccounts(q = '') { return this.call<AdminAccount[]>('GET', `/admin/accounts?q=${encodeURIComponent(q)}`); }
  setFounder(accountId: number, founder: boolean, number?: number | null, badges?: string[]) {
    return this.call<HubProfile>('POST', `/admin/accounts/${accountId}/founder`, { founder, number: number ?? null, badges: badges ?? null });
  }
  grantBadge(accountId: number, badge: string, note = '') { return this.call<HubProfile>('POST', `/admin/accounts/${accountId}/badges/${badge}`, { note }); }
  revokeBadge(accountId: number, badge: string) { return this.call<HubProfile>('DELETE', `/admin/accounts/${accountId}/badges/${badge}`); }
  putBadge(id: string, b: BadgeForm) { return this.call<BadgeDef>('PUT', `/admin/badges/${id}`, b); }
  deleteBadge(id: string) { return this.call<{ deleted: boolean }>('DELETE', `/admin/badges/${id}`); }
  adminWorlds() { return this.call<(HubWorld & { internal_url: string })[]>('GET', '/admin/worlds'); }
  putWorld(id: string, w: WorldForm) { return this.call<HubWorld>('PUT', `/admin/worlds/${id}`, w); }
  deleteWorld(id: string) { return this.call<{ deleted: boolean }>('DELETE', `/admin/worlds/${id}`); }
  // the world spawner (docs/worlds.md)
  spawnerSchema() { return this.call<SpawnerSchema>('GET', '/admin/spawner/schema'); }
  spawnedWorlds() { return this.call<SpawnedWorld[]>('GET', '/admin/spawner/worlds'); }
  spawnWorld(body: SpawnRequest) { return this.call<{ world: HubWorld; spawned: SpawnedWorld; mode: string; overrides: Record<string, unknown> }>('POST', '/admin/spawner/worlds', body); }
  stopSpawned(id: string) { return this.call<SpawnedWorld>('POST', `/admin/spawner/worlds/${id}/stop`); }
  startSpawned(id: string) { return this.call<SpawnedWorld>('POST', `/admin/spawner/worlds/${id}/start`); }
}
