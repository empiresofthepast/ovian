import { Component, DestroyRef, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { ChronicleEntry } from '../../core/models';
import { UI } from '../../shared/ui';

const PAGE = 50;

/** The public history of the world, newest first. */
@Component({
  selector: 'ov-chronicle',
  imports: [DatePipe, RouterLink, ...UI],
  template: `
    <div class="page-head">
      <h1 class="page-title">{{ 'nav.chronicle' | label }}</h1>
      <a class="btn btn--small" [href]="geojson" target="_blank" rel="noopener">⬇ {{ 'chronicle.geojson' | label: 'Download GeoJSON' }}</a>
    </div>
    <section class="panel">
      <p class="small muted">{{ 'chronicle.about' | label: 'Foundings, conquests, wars, festivals and wonders, as the world remembers them. The GeoJSON places events on the game grid: fictional geography, not real places.' }}</p>
      <div class="chips" role="group" aria-label="Filter">
        <button class="chip" [class.chip--on]="!kind()" (click)="filter('')">{{ 'chronicle.all' | label: 'All' }}</button>
        @for (k of kinds(); track k) {
          <button class="chip" [class.chip--on]="kind() === k" (click)="filter(k)">{{ 'chronicle.' + k | label: k }}</button>
        }
      </div>
      <div class="timeline">
        @for (e of entries(); track e.id) {
          <div class="timeline__item">
            <span class="tag">{{ 'chronicle.' + e.kind | label: e.kind }}</span>
            <span>{{ e.title }}</span>
            <span class="timeline__meta small muted">{{ e.at | date: 'medium' }}
              @if (e.x !== null && e.y !== null) { · <a [routerLink]="'/map'" [queryParams]="{ x: e.x, y: e.y }">({{ e.x }}|{{ e.y }})</a>}</span>
          </div>
        } @empty {
          @if (!loading()) {<p class="muted small">{{ 'chronicle.empty' | label: 'Nothing has been written yet.' }}</p>}
        }
      </div>
      @if (error()) {<p class="bad small">{{ error() }}</p>}
      @if (more()) {
        <div class="btn-row"><button class="btn btn--small" [disabled]="loading()" (click)="older()">{{ 'chronicle.older' | label: 'Load older' }}</button></div>
      }
    </section>
  `,
})
export class ChronicleComponent {
  private readonly api = inject(Api);
  private readonly game = inject(GameStore);
  protected readonly geojson = this.api.chronicleGeojsonUrl();
  protected readonly entries = signal<ChronicleEntry[]>([]);
  protected readonly kinds = signal<string[]>([]);
  protected readonly kind = signal('');
  protected readonly loading = signal(false);
  protected readonly more = signal(false);
  protected readonly error = signal('');
  private seq = 0;

  constructor() {
    void this.load();
    const sub = this.game.serverEvents.subscribe((e) => {
      if (e.type.startsWith('chronicle')) void this.load();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  protected filter(kind: string): void {
    this.kind.set(kind);
    void this.load();
  }

  protected older(): void {
    const last = this.entries().at(-1);
    if (last) void this.load(last.at);
  }

  private async load(before?: number): Promise<void> {
    const mine = ++this.seq;
    this.loading.set(true);
    try {
      const r = await this.api.chronicle({ kind: this.kind() || undefined, before, limit: PAGE });
      if (mine !== this.seq) return;
      this.kinds.set(r.kinds);
      this.entries.update((l) => (before ? [...l, ...r.entries.filter((e) => !l.some((x) => x.id === e.id))] : r.entries));
      this.more.set(r.entries.length >= PAGE);
      this.error.set('');
    } catch (e) {
      if (mine === this.seq) this.error.set(this.game.errorText(e));
    } finally {
      if (mine === this.seq) this.loading.set(false);
    }
  }
}
