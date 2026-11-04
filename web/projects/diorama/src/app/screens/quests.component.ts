import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { Achievement, Quest } from '@core/models';
import { UI } from '../ui';

@Component({
  selector: 'dio-quests',
  imports: [...UI],
  template: `
    <section class="hud-panel dialog quests" role="dialog" aria-label="Quests">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Quests <span class="muted small">· {{ done() }} of {{ total() }} done</span></h2>
      @for (q of quests(); track q.id) {
        <div class="quest" [class.quest--done]="q.complete">
          <div class="grow">
            <strong>{{ q.title }}</strong>&nbsp;·&nbsp;<span class="muted small">{{ q.text }}</span>
            <div class="bar"><div class="bar__fill" [style.width.%]="(q.have / q.need) * 100"></div></div>
            <div class="small muted">{{ q.have | n }} / {{ q.need | n }} · reward <dio-cost [cost]="q.reward" /></div>
          </div>
          <button class="btn btn--small" [class.btn--gold]="q.complete" [disabled]="!q.complete" (click)="claim(q.id)">Claim</button>
        </div>
      } @empty {<p class="muted">Every quest is done. Well played.</p>}
      <p class="small muted">Rewards arrive in the city you are looking at, and may go beyond its storage.</p>

      <h3 class="subhead">Achievements</h3>
      <div class="achievements">
        @for (a of achievements(); track a.id) {
          <div class="achievement" [class.achievement--on]="a.unlocked_at" [title]="a.description">
            <span class="achievement__icon">{{ a.unlocked_at ? '🏆' : '·' }}</span>
            <div><strong>{{ a.name }}</strong><div class="small muted">{{ a.description }}</div>
              @if (!a.unlocked_at && a.value > 1) {<div class="small muted">{{ a.progress | n }} / {{ a.value | n }}</div>}
            </div>
          </div>
        }
      </div>
    </section>
  `,
})
export class QuestsComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly quests = signal<Quest[]>([]);
  protected readonly done = signal(0);
  protected readonly total = signal(0);
  protected readonly achievements = signal<Achievement[]>([]);

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    const [q, a] = await Promise.all([this.api.quests(), this.api.achievements()]);
    this.quests.set(q.quests);
    this.done.set(q.done);
    this.total.set(q.total);
    this.achievements.set(a);
  }

  protected async claim(id: string): Promise<void> {
    const v = this.game.village();
    if (v && (await this.game.act(() => this.api.claimQuest(id, v.id), 'Reward collected'))) await this.load();
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
