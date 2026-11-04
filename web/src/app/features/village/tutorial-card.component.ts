import { Component, computed, effect, inject, output, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { Quest } from '../../core/models';
import { FEATURES } from '../../features';
import { UI } from '../../shared/ui';

/** The guided tutorial: the first open quest, with a hint and a pointer. */
@Component({
  selector: 'ov-tutorial-card',
  imports: [RouterLink, ...UI],
  template: `
    @if (quest(); as q) {
      <section class="panel tutorial" aria-label="Tutorial">
        <div class="tutorial__head">
          <span class="tag">{{ 'tutorial' | label: 'Tutorial' }} {{ done() + 1 }}/{{ total() }}</span>
          <strong class="grow">{{ q.title }}</strong>
          <button class="btn btn--ghost btn--small" (click)="hide()">{{ 'tutorial.hide' | label: 'Hide tutorial' }}</button>
        </div>
        <p class="small">{{ q.text }}</p>
        @if (q.hint) {<p class="small muted">💡 {{ q.hint }}</p>}
        <div class="meter" [title]="q.have + ' / ' + q.need"><i [style.width.%]="progress(q)"></i></div>
        <div class="btn-row">
          <span class="small muted grow">{{ q.have }} / {{ q.need }} · <ov-cost [cost]="q.reward" /></span>
          @if (q.complete) {
            <button class="btn btn--primary btn--small" [disabled]="busy()" (click)="claim(q)">{{ 'quest.claim' | label: 'Claim reward' }}</button>
          } @else if (q.focus?.building) {
            <button class="btn btn--small" (click)="show.emit(q)">{{ 'tutorial.show' | label: 'Show me' }}</button>
          } @else if (screen(q); as path) {
            <a class="btn btn--small" [routerLink]="'/' + path">{{ 'tutorial.go' | label: 'Go there' }}</a>
          }
        </div>
      </section>
    }
  `,
})
export class TutorialCardComponent {
  private readonly api = inject(Api);
  private readonly game = inject(GameStore);
  /** The quest being shown changed (null when none): the village highlights its focus. */
  readonly questChange = output<Quest | null>();
  /** "Show me": point at the quest's building. */
  readonly show = output<Quest>();

  private readonly data = signal<{ quests: Quest[]; done: number; total: number; tutorial: boolean } | null>(null);
  protected readonly busy = signal(false);
  protected readonly quest = computed(() => {
    const d = this.data();
    return d && d.tutorial && this.game.me()?.tutorial && !this.game.inspecting() ? (d.quests[0] ?? null) : null;
  });
  protected readonly done = computed(() => this.data()?.done ?? 0);
  protected readonly total = computed(() => this.data()?.total ?? 0);
  private last = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Reload when the city changes (a building finished, a quest may be done), at most every few seconds.
    effect(() => {
      this.game.village();
      if (!this.game.me()?.tutorial) return;
      untracked(() => this.schedule());
    });
    effect(() => this.questChange.emit(this.quest()));
  }

  private schedule(): void {
    if (this.timer) return;
    const wait = Math.max(0, this.last + 3000 - Date.now());
    this.timer = setTimeout(() => {
      this.timer = null;
      this.last = Date.now();
      this.api.quests().then((d) => this.data.set(d)).catch(() => undefined);
    }, wait);
  }

  protected progress(q: Quest): number {
    return q.need ? Math.min(100, (q.have / q.need) * 100) : 0;
  }

  protected screen(q: Quest): string | null {
    const s = q.focus?.screen;
    return s && FEATURES.some((f) => f.path === s) ? s : null;
  }

  protected async claim(q: Quest): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    if (await this.game.act(() => this.api.claimQuest(q.id, v.id), `${q.title} ✓`)) {
      this.last = 0;
      this.schedule();
    }
    this.busy.set(false);
  }

  protected async hide(): Promise<void> {
    try {
      await this.api.tutorial(false);
      await this.game.refreshMe();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }
}
