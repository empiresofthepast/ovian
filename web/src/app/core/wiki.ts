import { Component, computed, inject, input } from '@angular/core';
import { EngineService } from './engine.service';

interface WikiRefs {
  base?: string;
  buildings?: Record<string, string>;
  units?: Record<string, string>;
}

/** What one civilization calls a building, and the Wikipedia article about it in that culture. */
interface CultureEntry {
  name?: string;
  wikipedia?: string;
}
type Cultures = Record<string, { buildings?: Record<string, CultureEntry> }>;
type WithExtensions = { extensions?: { wikipedia?: WikiRefs; cultures?: Cultures } } | null | undefined;

function cultureEntry(pack: unknown, tribe: string | null | undefined, building: string): CultureEntry | undefined {
  return tribe ? (pack as WithExtensions)?.extensions?.cultures?.[tribe]?.buildings?.[building] : undefined;
}

/** The name a culture gives a building (extensions.cultures), or null when the pack has none for it. */
export function cultureName(pack: unknown, tribe: string | null | undefined, building: string | null | undefined): string | null {
  return building ? (cultureEntry(pack, tribe, building)?.name ?? null) : null;
}

/**
 * The Wikipedia article the pack gives for a building or a unit, or null: the culture's own article
 * (extensions.cultures) when a tribe is given and has one, else the general one (extensions.wikipedia).
 */
export function wikiRef(pack: unknown, kind: 'building' | 'unit', id: string, tribe?: string | null): { title: string; url: string } | null {
  const w = (pack as WithExtensions)?.extensions?.wikipedia;
  const own = kind === 'building' ? cultureEntry(pack, tribe, id)?.wikipedia : undefined;
  const title = own ?? (kind === 'building' ? w?.buildings : w?.units)?.[id];
  if (!title) return null;
  return { title, url: (w?.base ?? 'https://en.wikipedia.org/wiki/') + encodeURIComponent(title.replace(/ /g, '_')) };
}

/** A small link to the Wikipedia article about a building or a unit; nothing when the pack has none. */
@Component({
  selector: 'ov-wiki',
  template: `@if (ref(); as r) {<a class="wiki" [href]="r.url" target="_blank" rel="noopener noreferrer" [title]="'On Wikipedia: ' + r.title"
    (click)="$event.stopPropagation()">{{ label() ? 'Wikipedia: ' + r.title + ' ↗' : 'W↗' }}</a>}`,
})
export class WikiLinkComponent {
  private readonly engine = inject(EngineService);
  readonly kind = input.required<'building' | 'unit'>();
  readonly id = input.required<string>();
  /** the culture whose article to prefer (buildings only) */
  readonly tribe = input<string | null | undefined>(null);
  /** show the article's title, not just "W↗" */
  readonly label = input(false);
  protected readonly ref = computed(() => wikiRef(this.engine.pack(), this.kind(), this.id(), this.tribe()));
}

/** Whether a unit is a settler (``extensions.settlers.unit``: the unit, or ``<tribe>_<unit>``). */
export function isSettler(pack: { extensions?: Record<string, unknown> } | null | undefined, unit: string): boolean {
  const suffix = (pack?.extensions?.['settlers'] as { unit?: string } | undefined)?.unit;
  return !!suffix && (unit === suffix || unit.endsWith('_' + suffix));
}

/** A cost multiplied by ``factor``, rounded up. */
export function scaleCost(cost: Record<string, number>, factor: number): Record<string, number> {
  if (factor === 1) return cost;
  return Object.fromEntries(Object.entries(cost).map(([r, c]) => [r, Math.ceil(c * factor)]));
}

/** A short label for the land around a city ("⛰ +20% stone · 🌲 +15% wood") and its explanation, or null when it gives nothing. */
export function landChip(t: { radius: number; around: Record<string, number>; bonus: Record<string, number> } | undefined | null): { text: string; title: string } | null {
  const b = Object.entries(t?.bonus ?? {}).filter(([, v]) => v > 0);
  if (!t || !b.length) return null;
  const icon: Record<string, string> = { stone: '⛰', wood: '🌲' };
  const text = b.map(([r, v]) => `${icon[r] ?? '✦'} +${Math.round(v * 100)}% ${r}`).join(' · ');
  const around = Object.entries(t.around).map(([k, n]) => `${n} ${k}`).join(', ');
  return { text, title: `Within ${t.radius} tiles: ${around}. Quarries by the mountains, sawmills by the forests.` };
}
