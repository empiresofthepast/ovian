import { Component, computed, inject, input } from '@angular/core';
import { EngineService } from './engine.service';

interface WikiRefs {
  base?: string;
  buildings?: Record<string, string>;
  units?: Record<string, string>;
}

/** The Wikipedia article the pack gives for a building or a unit (extensions.wikipedia), or null. */
export function wikiRef(pack: unknown, kind: 'building' | 'unit', id: string): { title: string; url: string } | null {
  const w = (pack as { extensions?: { wikipedia?: WikiRefs } } | null)?.extensions?.wikipedia;
  const title = (kind === 'building' ? w?.buildings : w?.units)?.[id];
  if (!w || !title) return null;
  return { title, url: (w.base ?? 'https://en.wikipedia.org/wiki/') + encodeURIComponent(title.replace(/ /g, '_')) };
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
  /** show the article's title, not just "W↗" */
  readonly label = input(false);
  protected readonly ref = computed(() => wikiRef(this.engine.pack(), this.kind(), this.id()));
}
