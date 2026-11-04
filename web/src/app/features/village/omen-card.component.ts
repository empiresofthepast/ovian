import { Component, inject, input, signal } from '@angular/core';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { Omen, OmenChoice, ResourceMap } from '../../core/models';
import { pct, ResPipe, signed } from '../../shared/effects';
import { UI } from '../../shared/ui';

/** An omen waiting for the ruler's choice. */
@Component({
  selector: 'ov-omen-card',
  imports: [...UI],
  template: `
    @if (omen(); as o) {
      <section class="panel omen" aria-label="Omen">
        <h2 class="panel__title">✶ {{ o.title }}</h2>
        <p class="small">{{ o.text }}</p>
        <p class="small muted">{{ 'omen.expires' | label: 'If you do not choose, in' }} <span class="timer">{{ o.expires_at - game.now() | duration }}</span>:
          <em>{{ defaultLabel(o) }}</em></p>
        <div class="omen__choices">
          @for (c of o.choices; track c.id) {
            <button class="btn omen__choice" [class.omen__choice--default]="c.id === o.default" [disabled]="!c.available || busy()" (click)="answer(c)">
              <strong>{{ c.label }}@if (c.id === o.default) {<span class="muted small"> · {{ 'omen.default' | label: 'default' }}</span>}</strong>
              @if (hasAny(c.cost)) {<span class="small">{{ 'omen.cost' | label: 'Costs' }} <ov-cost [cost]="c.cost" [have]="game.resources()" /></span>}
              @for (e of effects(c); track e) {<span class="small">{{ e }}</span>}
              @if (!c.available) {<span class="small bad">{{ 'omen.unavailable' | label: 'Not possible here' }}</span>}
            </button>
          }
        </div>
      </section>
    }
  `,
})
export class OmenCardComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly res = new ResPipe();
  readonly omen = input<Omen | null | undefined>(null);
  protected readonly busy = signal(false);

  protected defaultLabel(o: Omen): string {
    return o.choices.find((c) => c.id === o.default)?.label ?? o.default;
  }

  protected hasAny(m: ResourceMap | undefined): boolean {
    return Object.values(m ?? {}).some((n) => n > 0);
  }

  protected effects(c: OmenChoice): string[] {
    const out: string[] = [];
    const gain = Object.entries(c.gain ?? {});
    const plus = Object.fromEntries(gain.filter(([, n]) => n > 0));
    const minus = Object.fromEntries(gain.filter(([, n]) => n < 0).map(([k, n]) => [k, -n]));
    if (Object.keys(plus).length) out.push(`Gain ${this.res.transform(plus)}`);
    if (Object.keys(minus).length) out.push(`Lose ${this.res.transform(minus)}`);
    if (c.favor_cost) out.push(`−${c.favor_cost} favor`);
    if (c.favor) out.push(`${signed(c.favor)} favor`);
    const time = c.hours ? ` for ${Math.round(c.hours * 10) / 10}h` : '';
    if (c.contentment) out.push(`${signed(c.contentment)} contentment${time}`);
    if (c.boost) out.push(`${pct(c.boost)} production${time}`);
    if (c.unrest) out.push(`${signed(c.unrest)} unrest`);
    return out;
  }

  protected async answer(c: OmenChoice): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.answerOmen(v.id, c.id), c.label);
    this.busy.set(false);
  }
}
