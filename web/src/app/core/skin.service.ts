import { Injectable, inject, signal } from '@angular/core';
import { CONFIG } from './config';
import { DEFAULT_ICONS, DEFAULT_LABELS } from './defaults';

/**
 * A skin is a folder under /skins/<id>/ with:
 * - skin.json: name, author, icons, labels, map colours, layout options
 * - a stylesheet (default theme.css) that sets the CSS variables in styles.css
 *
 * Skins never change rules. They only change how things look and are named.
 */
export interface SkinManifest {
  id: string;
  /** Parent skin id: icons, labels and map colours not set here are inherited. */
  extends?: string;
  name: string;
  author?: string;
  description?: string;
  stylesheet?: string;
  /** Extra stylesheets, e.g. Google Fonts. */
  fonts?: string[];
  /** Preview swatches for the settings page. */
  swatches?: string[];
  layout?: { nav?: 'top' | 'side'; hide?: string[] };
  /** Glyph or image path (relative to the skin folder) per key: resource.wood, building.farm, unit.lancer, nav.map, terrain.forest... */
  icons?: Record<string, string>;
  /** Text overrides per key: app.title, nav.map, building.farm, error.queue_full... */
  labels?: Record<string, string>;
  map?: {
    terrain?: Record<string, string>;
    own?: string;
    other?: string;
    selected?: string;
    grid?: string;
    label?: string;
  };
}

const SKIN_KEY = 'ovian.skin';

@Injectable({ providedIn: 'root' })
export class SkinService {
  private readonly cfg = inject(CONFIG);
  readonly skin = signal<SkinManifest | null>(null);
  readonly available = signal<SkinManifest[]>([]);

  async init(): Promise<void> {
    let wanted = this.cfg.skin;
    try {
      wanted = localStorage.getItem(SKIN_KEY) ?? wanted;
    } catch {
      // ignore
    }
    if (!this.cfg.skins.includes(wanted)) wanted = this.cfg.skin;
    await this.use(wanted).catch(() => this.use(this.cfg.skin));
    const all = await Promise.all(this.cfg.skins.map((id) => this.fetchManifest(id).catch(() => null)));
    this.available.set(all.filter((s): s is SkinManifest => s !== null));
  }

  async use(id: string): Promise<void> {
    const manifest = await this.fetchManifest(id);
    const base = `skins/${id}/`;
    setLink('ovian-skin', base + (manifest.stylesheet ?? 'theme.css'));
    document.querySelectorAll('link[data-ovian-font]').forEach((l) => l.remove());
    for (const href of manifest.fonts ?? []) {
      const l = document.createElement('link');
      l.rel = 'stylesheet';
      l.href = href;
      l.dataset['ovianFont'] = '1';
      document.head.appendChild(l);
    }
    document.documentElement.dataset['skin'] = id;
    this.skin.set(manifest);
    try {
      localStorage.setItem(SKIN_KEY, id);
    } catch {
      // ignore
    }
  }

  /** Load a manifest; with "extends", missing icons, labels and map colours come from the parent skin. */
  private async fetchManifest(id: string, depth = 0): Promise<SkinManifest> {
    const r = await fetch(`skins/${id}/skin.json`);
    if (!r.ok) throw new Error(`skin ${id} not found`);
    const own = (await r.json()) as SkinManifest & { extends?: string };
    if (!own.extends || depth > 3) return { ...own, id };
    const parent = await this.fetchManifest(own.extends, depth + 1);
    const prefix = (icons: Record<string, string> = {}, from: string) =>
      Object.fromEntries(Object.entries(icons).map(([k, v]) => [k, isImage(v) ? `../${from}/${v}` : v]));
    return {
      ...own,
      id,
      icons: { ...prefix(parent.icons, parent.id), ...own.icons },
      labels: { ...parent.labels, ...own.labels },
      map: { ...parent.map, ...own.map, terrain: { ...parent.map?.terrain, ...own.map?.terrain } },
    };
  }

  /** Text for a key: skin override, then the fallback (usually the content pack name), then built-in English. */
  label(key: string, fallback?: string): string {
    return this.skin()?.labels?.[key] ?? fallback ?? DEFAULT_LABELS[key] ?? key;
  }

  /** Glyph or image URL for a key. Falls back from "building.farm" to "building" to a dot. */
  icon(key: string): string {
    const icons = this.skin()?.icons ?? {};
    const v = icons[key] ?? DEFAULT_ICONS[key] ?? icons[key.split('.')[0]] ?? DEFAULT_ICONS[key.split('.')[0]] ?? '•';
    return isImage(v) ? `skins/${this.skin()?.id}/${v}` : v;
  }

  hidden(feature: string): boolean {
    return this.skin()?.layout?.hide?.includes(feature) ?? false;
  }
}

export function isImage(v: string): boolean {
  return /\.(svg|png|webp|gif|jpe?g)$/i.test(v);
}

function setLink(id: string, href: string): void {
  let link = document.getElementById(id) as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    document.head.appendChild(link);
  }
  link.href = href;
}
