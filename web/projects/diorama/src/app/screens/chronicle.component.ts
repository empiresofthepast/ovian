import { DatePipe } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { ChronicleEntry } from '@core/models';
import { UI } from '../ui';

const KIND: Record<string, { icon: string; label: string }> = {
  founded: { icon: '⌂', label: 'Foundings' }, colony: { icon: '⛵', label: 'Colonies' }, submission: { icon: '⛓', label: 'Submissions' },
  rebellion: { icon: '🔥', label: 'Rebellions' }, battle: { icon: '⚔', label: 'Battles' }, war: { icon: '⚑', label: 'Wars' },
  pact: { icon: '🤝', label: 'Pacts' }, alliance: { icon: '⚭', label: 'Alliances' }, phase: { icon: '▲', label: 'Growth' },
  wonder: { icon: '🏛', label: 'Wonders' }, great: { icon: '🏟', label: 'Great buildings' }, festival: { icon: '🏅', label: 'Games' },
  government: { icon: '⚜', label: 'Governments' }, round: { icon: '⌛', label: 'Rounds' }, renamed: { icon: '✎', label: 'New names' },
  horde: { icon: '☠', label: 'Hordes' }, abandoned: { icon: '🏚', label: 'Abandoned cities' }, treaty: { icon: '✍', label: 'Treaties' },
  treachery: { icon: '⚠', label: 'Treachery' },
};

/** The public history of the world, with a GeoJSON export. */
@Component({
  selector: 'dio-chronicle',
  imports: [DatePipe, ...UI],
  template: `
    <section class="hud-panel dialog chronicle" role="dialog" aria-label="Chronicle">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Chronicle <span class="muted small">· round {{ round() }}</span></h2>
      <div class="chips">
        <button type="button" class="chip" [class.chip--on]="!kind()" (click)="filter(null)">All</button>
        @for (k of kinds(); track k) {<button type="button" class="chip" [class.chip--on]="kind() === k" (click)="filter(k)">{{ meta(k).icon }} {{ meta(k).label }}</button>}
      </div>
      <ol class="timeline">
        @for (e of entries(); track e.id) {
          <li class="timeline__item">
            <span class="timeline__icon" aria-hidden="true">{{ meta(e.kind).icon }}</span>
            <div class="grow">
              <div>{{ e.title }}</div>
              <div class="small muted">{{ e.at | date: 'd MMM, HH:mm' }}@if (e.x !== null) { · <button type="button" class="linkbtn" (click)="show(e)">({{ e.x }}|{{ e.y }})</button>}</div>
            </div>
          </li>
        } @empty {<li class="muted">Nothing has happened yet. History is waiting.</li>}
      </ol>
      @if (more()) {<button class="btn btn--small" (click)="older()">Older entries</button>}
      <p class="small muted">
        <a [href]="geojson" target="_blank" rel="noopener">Download as GeoJSON</a>, one point per event with a <code>start_date</code>, for a timeline map.
        The map grid is projected onto made-up coordinates, so do not upload it to OpenHistoricalMap as real history.
      </p>
    </section>
  `,
})
export class ChronicleComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly entries = signal<ChronicleEntry[]>([]);
  protected readonly kinds = signal<string[]>([]);
  protected readonly kind = signal<string | null>(null);
  protected readonly round = signal(1);
  protected readonly more = signal(false);
  protected readonly geojson = this.api.chronicleGeojsonUrl();
  private readonly page = 60;

  constructor() {
    void this.load();
    const sub = this.game.serverEvents.subscribe((e) => {
      if (e.type === 'chronicle.entry' && !this.kind()) void this.load();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  protected meta(kind: string) {
    return KIND[kind] ?? { icon: '•', label: kind };
  }

  private async load(): Promise<void> {
    const r = await this.api.chronicle({ kind: this.kind() ?? undefined, limit: this.page });
    this.round.set(r.round);
    this.kinds.set(r.kinds);
    this.entries.set(r.entries);
    this.more.set(r.entries.length === this.page);
  }

  protected filter(k: string | null): void {
    this.kind.set(k);
    void this.load();
  }

  protected async older(): Promise<void> {
    const last = this.entries().at(-1);
    if (!last) return;
    const r = await this.api.chronicle({ kind: this.kind() ?? undefined, before: last.at, limit: this.page });
    this.entries.update((e) => [...e, ...r.entries]);
    this.more.set(r.entries.length === this.page);
  }

  protected show(e: ChronicleEntry): void {
    void this.router.navigate(['/map'], { queryParams: { x: e.x, y: e.y } });
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
