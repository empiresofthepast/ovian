import { Component, Pipe, PipeTransform, computed, inject, input } from '@angular/core';
import { EngineService } from '../core/engine.service';
import { ResourceMap, Units } from '../core/models';
import { SkinService, isImage } from '../core/skin.service';

/** Skin-provided glyph or image for a key such as "resource.wood". */
@Component({
  selector: 'ov-icon',
  template: `@if (image()) {<img class="ov-icon" [src]="value()" [alt]="alt()" />} @else {<span class="ov-icon" aria-hidden="true">{{ value() }}</span>}`,
})
export class IconComponent {
  private readonly skin = inject(SkinService);
  readonly key = input.required<string>();
  readonly alt = input('');
  readonly value = computed(() => this.skin.icon(this.key()));
  readonly image = computed(() => isImage(this.value()));
}

/** Resource amounts with icons; amounts the player lacks are flagged. */
@Component({
  selector: 'ov-cost',
  imports: [IconComponent],
  template: `
    <span class="cost">
      @for (r of entries(); track r.id) {
        <span class="cost__item" [class.cost__item--short]="r.short" [title]="r.name">
          <ov-icon [key]="'resource.' + r.id" [alt]="r.name" />{{ r.amount }}
        </span>
      }
    </span>
  `,
})
export class CostComponent {
  private readonly engine = inject(EngineService);
  private readonly skin = inject(SkinService);
  readonly cost = input.required<ResourceMap>();
  readonly have = input<ResourceMap | null>(null);
  readonly entries = computed(() => {
    const have = this.have();
    return this.engine
      .resourceIds()
      .filter((id) => (this.cost()[id] ?? 0) > 0)
      .map((id) => ({
        id,
        name: this.skin.label(`resource.${id}`, this.engine.pack()?.resources.find((r) => r.id === id)?.name),
        amount: Math.round(this.cost()[id]).toLocaleString(),
        short: have ? (have[id] ?? 0) + 1e-6 < this.cost()[id] : false,
      }));
  });
}

/** A troop list: icon, name and count per unit. */
@Component({
  selector: 'ov-units',
  imports: [IconComponent],
  template: `
    <span class="units">
      @for (u of list(); track u.id) {
        <span class="units__item" [title]="u.name"><ov-icon [key]="'unit.' + u.id" [alt]="u.name" />{{ u.count }}</span>
      } @empty {<span class="muted">—</span>}
    </span>
  `,
})
export class UnitsComponent {
  private readonly engine = inject(EngineService);
  private readonly skin = inject(SkinService);
  readonly units = input.required<Units | undefined>();
  readonly list = computed(() =>
    Object.entries(this.units() ?? {})
      .filter(([, n]) => n > 0)
      .map(([id, count]) => ({ id, count, name: this.skin.label(`unit.${id}`, this.engine.unit(id)?.name) })),
  );
}

/** Milliseconds (or seconds with `'s'`) as h:mm:ss. */
@Pipe({ name: 'duration' })
export class DurationPipe implements PipeTransform {
  transform(value: number | null | undefined, unit: 'ms' | 's' = 'ms'): string {
    if (value === null || value === undefined || !isFinite(value)) return '—';
    let s = Math.max(0, Math.ceil(unit === 'ms' ? value / 1000 : value));
    const d = Math.floor(s / 86400);
    s -= d * 86400;
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const hms = `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    return d ? `${d}d ${hms}` : hms;
  }
}

/** Epoch ms as local clock time. */
@Pipe({ name: 'clock' })
export class ClockPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (!value) return '—';
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
}

/** Named label lookup: `'building' | name: id`. */
@Pipe({ name: 'name', pure: false })
export class NamePipe implements PipeTransform {
  private readonly engine = inject(EngineService);
  private readonly skin = inject(SkinService);
  transform(id: string | null | undefined, kind: 'building' | 'unit' | 'resource' | 'tribe'): string {
    if (!id) return '';
    const pack = this.engine.pack();
    const fallback =
      kind === 'building' ? this.engine.building(id)?.name
      : kind === 'unit' ? this.engine.unit(id)?.name
      : kind === 'resource' ? pack?.resources.find((r) => r.id === id)?.name
      : pack?.tribes.find((t) => t.id === id)?.name;
    return this.skin.label(`${kind}.${id}`, fallback ?? id);
  }
}

/** Skin label lookup: `'nav.map' | label`. */
@Pipe({ name: 'label', pure: false })
export class LabelPipe implements PipeTransform {
  private readonly skin = inject(SkinService);
  transform(key: string, fallback?: string): string {
    return this.skin.label(key, fallback);
  }
}

export const UI = [IconComponent, CostComponent, UnitsComponent, DurationPipe, ClockPipe, NamePipe, LabelPipe] as const;
