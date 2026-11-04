import { Component, computed, inject } from '@angular/core';
import { Api } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { OmenChoice } from '@core/models';
import { UI } from '../ui';

/** Something happened in the city: the ruler chooses. Unanswered, the default happens. */
@Component({
  selector: 'dio-omen',
  imports: [...UI],
  template: `
    @if (omen(); as o) {
      <section class="hud-panel omen" role="alertdialog" [attr.aria-label]="o.title">
        <h3 class="subhead">✶ {{ o.title }} <span class="muted small">· {{ o.expires_at - game.now() | dur: 'ms' }}</span></h3>
        <p class="omen__text small">{{ o.text }}</p>
        @for (c of o.choices; track c.id) {
          <button class="btn btn--small omen__choice" [class.btn--gold]="c.id === o.default" [disabled]="!c.available || game.inspecting()" (click)="choose(c.id)"
                  [title]="c.id === o.default ? 'Happens by itself if you do not choose' : ''">
            <span>{{ c.label }}@if (c.id === o.default) { <span class="muted small">(default)</span>}</span>
            @if (outcome(c); as t) {<span class="small">{{ t }}</span>}
            @if (hasCost(c)) {<span class="small">Costs <dio-cost [cost]="c.cost" [have]="game.resources()" /></span>}
            @if (hasGain(c)) {<span class="small">Gives <dio-cost [cost]="c.gain" /></span>}
          </button>
        }
      </section>
    }
  `,
})
export class OmenComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  protected readonly omen = computed(() => this.game.village()?.omen ?? null);

  protected hasCost(c: OmenChoice): boolean {
    return Object.values(c.cost).some((n) => n > 0);
  }

  protected hasGain(c: OmenChoice): boolean {
    return Object.values(c.gain).some((n) => n > 0);
  }

  protected outcome(c: OmenChoice): string {
    const parts: string[] = [];
    if (c.favor_cost) parts.push(`−${c.favor_cost} favor`);
    if (c.favor) parts.push(`+${c.favor} favor`);
    if (c.contentment) parts.push(`${c.contentment > 0 ? '+' : ''}${c.contentment} contentment`);
    if (c.boost) parts.push(`${c.boost > 0 ? '+' : ''}${Math.round(c.boost * 100)}% production`);
    if ((c.contentment || c.boost) && c.hours) parts.push(`for ${c.hours} h`);
    const loss = Object.entries(c.gain).filter(([, n]) => n < 0);
    if (loss.length) parts.push('lose some ' + loss.map(([k]) => k).join(', '));
    return parts.join(', ');
  }

  protected async choose(id: string): Promise<void> {
    const v = this.game.village();
    if (v) await this.game.act(() => this.api.answerOmen(v.id, id), 'So be it');
  }
}
