import { Component, computed, inject, input, signal } from '@angular/core';
import { Api } from '../../core/api.service';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { embassyRules } from '../../core/embassy';
import { Layer } from '../../core/models';
import { UI } from '../../shared/ui';

/** "pulled down" / "fell to ruin" for a layer's `end`. */
export function layerEnd(end: string | null | undefined): string {
  return end === 'ruined' ? 'fell to ruin' : end === 'demolished' ? 'pulled down' : (end ?? '');
}

/**
 * Archaeology under one town or foreign site: the known layers, a dig under way,
 * or the order to dig. Shown only for empty sites and ruins in worlds with archaeology.
 */
@Component({
  selector: 'ov-dig-site',
  imports: [...UI],
  template: `
    @if (info(); as a) {
      <div class="dig">
        <h3 class="subtitle">{{ 'archaeology' | label: 'Below this site' }}</h3>
        @if (a.layers.length) {
          <p class="small muted">From the top down:</p>
          @for (l of a.layers; track $index) {
            <div class="row small">
              <ov-icon [key]="'building.' + l.building" />
              <span class="grow">{{ l.building | name: 'building' }}
                <span class="muted">@if (l.style) {<span>{{ l.style | name: 'tribe' }} style, </span>}level {{ l.level }}, {{ end(l.end) }}</span></span>
              @if (l.dug) {<span class="muted">dug</span>} @else {<span class="good">not dug</span>}
            </div>
          }
        } @else if (!a.probed) {
          <p class="small muted">Nothing is known of what lies below.</p>
        }

        @if (a.dig; as d) {
          <div class="meter"><i [style.width.%]="progress(d.started_at, d.due_at)"></i></div>
          <div class="row small">
            <span class="grow">Diggers at work</span>
            <span class="timer">{{ d.due_at - game.now() | duration }}</span>
            <button class="btn btn--ghost btn--small" [disabled]="busy() || game.inspecting()" (click)="stop()">Call off</button>
          </div>
        } @else if (a.probed && !a.undug) {
          <p class="small muted">Dug down to the bare rock.</p>
        } @else {
          <div class="row row--wrap small">
            <span class="grow"><ov-cost [cost]="a.cost" [have]="game.resources()" />
              <span class="muted"> <ov-icon key="stat.time" /> {{ a.seconds | duration: 's' }}</span></span>
            <button class="btn btn--small" [disabled]="busy() || game.inspecting() || !a.affordable" (click)="dig()">Excavate</button>
          </div>
          @if (a.ruin) {<p class="small muted">Digging clears the ruin.</p>}
        }
      </div>
    }
  `,
  styles: `.dig { margin-top: 0.8rem; }`,
})
export class DigSiteComponent {
  readonly slot = input.required<number>();
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  protected readonly busy = signal(false);
  protected readonly end = layerEnd;

  protected readonly info = computed(() => {
    const v = this.game.village();
    const arch = v?.archaeology;
    const pack = this.engine.pack();
    if (!v || !arch || !pack) return null;
    const i = this.slot();
    const s = v.state.slots[i];
    const fields = pack.village.field_slots.length;
    if (!s || i < fields || !(i < fields + pack.village.center_slots || s.foreign)) return null;
    const ruinId = embassyRules(pack)?.ruin ?? 'ruin';
    const ruin = s.building === ruinId;
    if (s.building && !ruin) return null;
    if (v.build_queue.some((q) => q.slot === i)) return null;
    const site = arch.sites[String(i)] ?? { layers: [] as Layer[], probed: false };
    const have = this.game.resources();
    return {
      layers: [...site.layers].reverse(),
      probed: site.probed,
      undug: site.layers.some((l) => !l.dug),
      dig: arch.digs.find((d) => d.slot === i) ?? null,
      cost: arch.cost,
      seconds: (arch.hours * 3600) / (pack.world.speed || 1),
      affordable: Object.entries(arch.cost).every(([r, n]) => (have[r] ?? 0) + 1e-6 >= n),
      ruin,
    };
  });

  protected progress(start: number, due: number): number {
    const span = due - start;
    return span > 0 ? Math.min(100, Math.max(0, ((this.game.now() - start) / span) * 100)) : 0;
  }

  protected async dig(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.excavate(v.id, this.slot()), 'The diggers set to work');
    this.busy.set(false);
  }

  protected async stop(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.stopDigging(v.id, this.slot()), 'The diggers are called off');
    this.busy.set(false);
  }
}
