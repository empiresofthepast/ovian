import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { ResourceMap, Vassal } from '../../core/models';
import { UI } from '../../shared/ui';

/** The overlord's levy of a vassal's own troops into the garrison there, paid by the current city. */
@Component({
  selector: 'ov-auxiliaries',
  imports: [FormsModule, ...UI],
  template: `
    @if (vassal().garrison; as g) {
      @if (g.auxiliaries; as a) {
        <div class="aux small">
          <div class="row row--wrap">
            <span class="grow">Auxiliaries: levied <strong>{{ a.levied }}</strong>, in training {{ a.queued }}
              <span class="muted">(room {{ g.capacity }})</span></span>
          </div>
          @if (a.options.length && !game.inspecting()) {
            <form class="row row--wrap" (ngSubmit)="levy()">
              <select name="unit" [ngModel]="option()?.unit" (ngModelChange)="unit.set($event)" aria-label="Unit">
                @for (o of a.options; track o.unit) {<option [ngValue]="o.unit">{{ o.name }}</option>}
              </select>
              <input type="number" name="count" min="1" [max]="room()" [(ngModel)]="count" aria-label="Count" class="aux__count" />
              @if (option(); as o) {<ov-cost [cost]="total(o.cost_each)" [have]="game.resources()" />}
              <button class="btn btn--small" [disabled]="busy() || count < 1 || count > room()"
                      [title]="'Paid by ' + (game.village()?.name ?? '')">Levy</button>
            </form>
          }
          @for (t of a.training; track t.id) {
            <div class="row">
              <ov-icon [key]="'unit.' + t.unit" />
              <span class="grow">{{ t.remaining }} × {{ t.unit | name: 'unit' }}</span>
              <span class="timer" title="Next one">{{ t.next_at - game.now() | duration }}</span>
              <span class="muted timer" title="All done">{{ t.finishes_at - game.now() | duration }}</span>
              <button class="btn btn--ghost btn--small" [disabled]="busy()" (click)="cancel(t.id)" title="Cancel">✕</button>
            </div>
          }
          <p class="muted aux__note">They anger the city; if it breaks free they join it.</p>
        </div>
      }
    }
  `,
  styles: `
    .aux { padding: 0.2rem 0 0.4rem 1.2rem; }
    .aux__count { width: 4.5rem; }
    .aux__note { margin: 0.2rem 0 0; }
  `,
})
export class AuxiliariesComponent {
  readonly vassal = input.required<Vassal>();
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  protected readonly busy = signal(false);
  protected readonly unit = signal('');
  protected count = 1;

  protected readonly room = computed(() => {
    const g = this.vassal().garrison;
    const a = g?.auxiliaries;
    return g && a ? Math.max(0, g.capacity - a.levied - a.queued) : 0;
  });

  /** The chosen unit, or the first one on offer. */
  protected readonly option = computed(() => {
    const opts = this.vassal().garrison?.auxiliaries?.options ?? [];
    return opts.find((o) => o.unit === this.unit()) ?? opts[0] ?? null;
  });

  protected total(each: ResourceMap): ResourceMap {
    const n = Math.max(1, Math.floor(Number(this.count) || 1));
    return Object.fromEntries(Object.entries(each).map(([r, c]) => [r, c * n]));
  }

  protected async levy(): Promise<void> {
    const v = this.game.village();
    const o = this.option();
    if (!v || !o) return;
    this.busy.set(true);
    const n = Math.floor(Number(this.count) || 0);
    await this.game.act(() => this.api.levy(this.vassal().village.id, v.id, o.unit, n), `${n} × ${o.name} levied`);
    this.busy.set(false);
  }

  protected async cancel(jobId: number): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.cancelLevy(this.vassal().village.id, jobId), 'Levy called off');
    this.busy.set(false);
  }
}
