import { Component, Pipe, PipeTransform, computed, inject, input } from '@angular/core';
import { EngineService } from '@core/engine.service';
import { ResourceMap } from '@core/models';
import { ArtService } from './art/art.service';

/** Seconds (or milliseconds with unit 'ms') as h:mm:ss. */
@Pipe({ name: 'dur' })
export class DurationPipe implements PipeTransform {
  transform(value: number | null | undefined, unit: 's' | 'ms' = 's'): string {
    if (value === null || value === undefined) return '';
    let s = Math.max(0, Math.round(unit === 'ms' ? value / 1000 : value));
    const h = Math.floor(s / 3600);
    s -= h * 3600;
    const m = Math.floor(s / 60);
    s -= m * 60;
    const two = (n: number) => String(n).padStart(2, '0');
    return h ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
  }
}

/** Compact numbers: 1 234, 12.3k. */
@Pipe({ name: 'n' })
export class NumberPipe implements PipeTransform {
  transform(v: number | null | undefined): string {
    if (v === null || v === undefined || !isFinite(v)) return '';
    const r = Math.floor(v);
    if (Math.abs(r) >= 100_000) return `${(r / 1000).toFixed(0)}k`;
    if (Math.abs(r) >= 10_000) return `${(r / 1000).toFixed(1)}k`;
    return r.toLocaleString('en-US').replace(/,/g, ' ');
  }
}

@Component({
  selector: 'dio-cost',
  imports: [NumberPipe],
  template: `
    @for (r of rows(); track r.id) {
      <span class="cost" [class.cost--short]="r.short" [title]="r.name">
        @if (r.icon) {<img [src]="r.icon" alt="" />} {{ r.amount | n }}
      </span>
    }
  `,
  host: { class: 'costs' },
})
export class CostComponent {
  readonly cost = input.required<ResourceMap>();
  readonly have = input<ResourceMap>({});
  private readonly art = inject(ArtService);
  private readonly engine = inject(EngineService);
  protected readonly rows = computed(() => {
    const have = this.have();
    const names = new Map(this.engine.pack()?.resources.map((r) => [r.id, r.name]) ?? []);
    return Object.entries(this.cost())
      .filter(([, v]) => v > 0)
      .map(([id, amount]) => ({ id, amount, name: names.get(id) ?? id, icon: this.art.resourceIcon(id), short: (have[id] ?? Infinity) < amount }));
  });
}

/** A 0 A.D.-style portrait frame. */
@Component({
  selector: 'dio-portrait',
  template: `@if (src()) {<img [src]="src()" [alt]="alt()" />} @else {<span>{{ alt().slice(0, 1) }}</span>}`,
  host: { class: 'portrait', '[class.portrait--small]': 'small()', '[class.portrait--locked]': 'locked()' },
})
export class PortraitComponent {
  readonly src = input<string | null>(null);
  readonly alt = input('');
  readonly small = input(false);
  readonly locked = input(false);
}

/** Troops as portraits with counts. */
@Component({
  selector: 'dio-units',
  imports: [PortraitComponent],
  template: `
    @for (u of list(); track u.id) {
      <span class="troop" [title]="u.name"><dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" /><span>{{ u.count }}</span></span>
    } @empty {<span class="muted small">—</span>}
  `,
  host: { class: 'troop-row' },
})
export class UnitsComponent {
  readonly units = input<Record<string, number> | undefined>({});
  private readonly art = inject(ArtService);
  private readonly engine = inject(EngineService);
  protected readonly list = computed(() =>
    Object.entries(this.units() ?? {})
      .filter(([, n]) => n > 0)
      .map(([id, count]) => ({ id, count, name: this.engine.unit(id)?.name ?? id, icon: this.art.unitIcon(id) })),
  );
}

/** Wall-clock time of a server timestamp, e.g. 14:05:09. */
@Pipe({ name: 'clock' })
export class ClockPipe implements PipeTransform {
  transform(ms: number | null | undefined): string {
    return ms ? new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  }
}

export const UI = [DurationPipe, NumberPipe, ClockPipe, CostComponent, PortraitComponent, UnitsComponent];
