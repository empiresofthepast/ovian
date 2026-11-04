import { Component, DestroyRef, inject, output, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { Quest } from '@core/models';
import { UI } from '../ui';

/** The guided first steps: the next open quest, with a hint and a "show me". */
@Component({
  selector: 'dio-tutorial',
  imports: [...UI],
  template: `
    @if (quest(); as q) {
      <section class="hud-panel tutorial" aria-label="Next step">
        <h3 class="subhead">Next step · {{ q.title }}
          <button class="close close--inline" (click)="folded.set(!folded())" [attr.aria-label]="folded() ? 'Show' : 'Fold'">{{ folded() ? '▾' : '▴' }}</button></h3>
        @if (!folded()) {
          <div class="small">{{ q.text }}</div>
          @if (q.hint) {<p class="tutorial__hint small muted">{{ q.hint }}</p>}
          <div class="bar"><div class="bar__fill" [style.width.%]="(q.have / q.need) * 100"></div></div>
          <div class="small muted">{{ q.have | n }} / {{ q.need | n }} · reward <dio-cost [cost]="q.reward" /></div>
          <div class="btn-row">
            @if (q.complete) {<button class="btn btn--gold btn--small" (click)="claim(q)">Claim reward</button>}
            @else if (q.focus) {<button class="btn btn--small" (click)="show(q)">Show me</button>}
            <button class="btn btn--ghost btn--small" (click)="off()" title="You can turn it back on in Settings">Hide tutorial</button>
          </div>
        }
      </section>
    }
  `,
})
export class TutorialComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  /** Asks the city to select a site (a building, or a free site when -1). */
  readonly focus = output<{ building?: string; site?: boolean }>();
  protected readonly quest = signal<Quest | null>(null);
  protected readonly folded = signal(false);
  private last = 0;

  constructor() {
    void this.load();
    // progress changes as the city does; refresh at most every few seconds
    const timer = setInterval(() => void this.load(), 15_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  async load(): Promise<void> {
    if (Date.now() - this.last < 3000 || !this.game.me()?.tutorial || this.game.inspecting()) {
      if (!this.game.me()?.tutorial) this.quest.set(null);
      return;
    }
    this.last = Date.now();
    try {
      const q = await this.api.quests();
      this.quest.set(q.tutorial ? (q.quests[0] ?? null) : null);
    } catch {
      this.quest.set(null);
    }
  }

  protected show(q: Quest): void {
    const f = q.focus!;
    if (f.screen) void this.router.navigateByUrl('/' + f.screen);
    else this.focus.emit({ building: f.building, site: f.site });
  }

  protected async claim(q: Quest): Promise<void> {
    const v = this.game.village();
    if (v && (await this.game.act(() => this.api.claimQuest(q.id, v.id), 'Reward collected'))) {
      this.last = 0;
      await this.load();
    }
  }

  protected async off(): Promise<void> {
    await this.api.tutorial(false);
    this.game.me.update((m) => m && { ...m, tutorial: false });
    this.quest.set(null);
    this.game.toast('Tutorial hidden. Turn it on again in Settings.', 'info');
  }
}
