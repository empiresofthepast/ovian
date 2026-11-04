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
  const cfg = { ...DEFAULTS, ...file };
  cfg.apiUrl = cfg.apiUrl.replace(/\/$/, '');
  if (!cfg.mqttUrl) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    cfg.mqttUrl = `${proto}://${location.host}/mqtt`;
  }
  if (!cfg.mcpUrl) cfg.mcpUrl = `${location.protocol}//${location.hostname}:47002/mcp`;
  return cfg;
}
