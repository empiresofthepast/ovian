import { InjectionToken } from '@angular/core';

/** Loaded from /config.json at startup so one build can serve any deployment. */
export interface RuntimeConfig {
  /** REST base URL, e.g. https://api.example.org. Empty means same origin. */
  apiUrl: string;
  /** MQTT over WebSocket URL. Empty means ws(s)://<this host>/mqtt. */
  mqttUrl: string;
  /** Default skin id. */
  skin: string;
  /** Skins offered in settings; each is a folder under /skins. */
  skins: string[];
  /** Optional links between front ends: where the other client of this world lives. */
  ledgerUrl?: string;
  dioramaUrl?: string;
  /** The MCP server for AI assistants. Empty means http(s)://<this host name>:47002/mcp. */
  mcpUrl?: string;
  /** The hub (one account for many worlds), e.g. "/hub". Empty: this site serves a single world, no hub. */
  hubUrl?: string;
  /** Set when a hub world is selected: which one (its id); apiUrl and mqttUrl then point at it. */
  worldId?: string;
}

/** The world picked through the hub, kept in localStorage; loadConfig points the API and broker at it. */
export interface SelectedWorld {
  id: string;
  name: string;
  /** API base: "" for this origin, "/w/w3", or a full origin. */
  apiUrl: string;
  mqttUrl: string;
}

export const WORLD_KEY = 'ovian.world';

export function selectedWorld(): SelectedWorld | null {
  try {
    const raw = localStorage.getItem(WORLD_KEY);
    return raw ? (JSON.parse(raw) as SelectedWorld) : null;
  } catch {
    return null;
  }
}

/** The API base for a world's api_url as the hub lists it ("/" means this origin). */
export function apiBase(apiUrl: string): string {
  return apiUrl === '/' ? '' : apiUrl.replace(/\/$/, '');
}

export const CONFIG = new InjectionToken<RuntimeConfig>('ovian.config');

const DEFAULTS: RuntimeConfig = { apiUrl: '', mqttUrl: '', skin: 'parchment', skins: ['parchment'] };

export async function loadConfig(): Promise<RuntimeConfig> {
  let file: Partial<RuntimeConfig> = {};
  try {
    const r = await fetch('config.json', { cache: 'no-store' });
    if (r.ok) file = await r.json();
  } catch {
    // fall back to defaults
  }
  const cfg: RuntimeConfig = { ...DEFAULTS, ...file };
  cfg.apiUrl = cfg.apiUrl.replace(/\/$/, '');
  cfg.hubUrl = (cfg.hubUrl ?? '').replace(/\/$/, '');
  const world = cfg.hubUrl ? selectedWorld() : null;
  if (world) {
    cfg.worldId = world.id;
    cfg.apiUrl = apiBase(world.apiUrl);
    if (world.mqttUrl) cfg.mqttUrl = world.mqttUrl;
  }
  if (!cfg.mqttUrl) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    cfg.mqttUrl = `${proto}://${location.host}/mqtt`;
  }
  if (!cfg.mcpUrl) cfg.mcpUrl = `${location.protocol}//${location.hostname}:47002/mcp`;
  return cfg;
}
