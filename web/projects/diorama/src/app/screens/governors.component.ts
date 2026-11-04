import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { Governor, GovernorsView } from '@core/models';
import { UI } from '../ui';

/** Governors: those in your service, where they rule, and the people on offer to hire. */
@Component({
  selector: 'dio-governors',
  imports: [FormsModule, ...UI],
  template: `
    <section class="hud-panel dialog governors" role="dialog" aria-label="Governors">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      @if (data(); as d) {
        <h2 class="selection__title">Governors <span class="muted small">· {{ d.count }} of {{ d.max }}</span></h2>
        <p class="small muted">One governor for each city you hold or rule. Sent to a vassal, a governor rules as your prefect, and the people resent it.</p>

        <h3 class="subhead">In your service</h3>
        @for (g of d.governors; track g.id) {
          <div class="row-item gov-row">
            <div class="grow">
              <strong>{{ g.name }}</strong>
              <div class="chips chips--tight">@for (t of g.traits; track t.id) {<span class="chip chip--static" [title]="t.text ?? ''">{{ t.name ?? t.id }}</span>}</div>
              <div class="small">
                @if (g.moving_to; as m) {
                  On the way to <strong>{{ m.name }}</strong>, arrives in <span class="job__time">{{ (g.arrives_at ?? 0) - game.now() | dur: 'ms' }}</span> <span class="muted">({{ g.arrives_at | clock }})</span>
                } @else if (g.village; as v) {
                  Rules <strong>{{ v.name }}</strong>@if (isVassal(v.id)) {&nbsp;<span class="tag">prefect</span>}
                } @else {<span class="muted">At court, waiting for a city.</span>}
              </div>
            </div>
            @if (!game.inspecting()) {
              <div class="gov-row__acts">
                <div class="row-form">
                  <select [(ngModel)]="appointTo[g.id]" [name]="'ap' + g.id" aria-label="City to rule">
                    @for (c of targets(); track c.id) {<option [ngValue]="c.id" [disabled]="c.id === g.village?.id || c.id === g.moving_to?.id">{{ c.name }}{{ c.vassal ? ' (vassal)' : '' }}</option>}
                  </select>
                  <button class="btn btn--small btn--gold" [disabled]="!appointTo[g.id] || busy()" (click)="appoint(g)">Send</button>
                </div>
                <div class="btn-row">
                  @if (g.village || g.moving_to) {<button class="btn btn--ghost btn--small" [disabled]="busy()" (click)="recall(g)" title="Back to court">Recall</button>}
                  <button class="btn btn--small" [class.btn--danger]="dismissing() === g.id" [class.btn--ghost]="dismissing() !== g.id" [disabled]="busy()" (click)="dismiss(g)">{{ dismissing() === g.id ? 'Really dismiss' : 'Dismiss' }}</button>
                  @if (dismissing() === g.id) {<button type="button" class="linkbtn small" (click)="dismissing.set(null)">Keep</button>}
                </div>
              </div>
            }
          </div>
        } @empty {<p class="small muted">Nobody yet. Hire one below.</p>}

        <h3 class="subhead">On offer <span class="muted small">· new faces in {{ d.offer_until - game.now() | dur: 'ms' }}</span></h3>
        <div class="gov-grid">
          @for (c of d.candidates; track c.index) {
            <div class="gov">
              <strong>{{ c.name }}</strong>
              <div class="chips chips--tight">@for (t of c.traits; track t.id) {<span class="chip chip--static" [title]="t.text ?? ''">{{ t.name ?? t.id }}</span>}</div>
              @for (t of c.traits; track t.id) {@if (t.text) {<div class="small muted">{{ t.text }}</div>}}
              <dio-cost [cost]="d.cost" [have]="game.resources()" />
              @if (!game.inspecting()) {
                <button class="btn btn--small" [disabled]="busy() || d.count >= d.max" (click)="hire(c.index, c.name)"
                        [title]="'Paid by ' + (game.village()?.name ?? '')">Hire</button>
              }
            </div>
          } @empty {<p class="small muted">Nobody on offer now.</p>}
        </div>
        <p class="small muted">Paid by {{ game.village()?.name }}. Each governor in service makes the next one dearer. They travel {{ d.speed }} tiles an hour.</p>
      } @else if (failed()) {
        <h2 class="selection__title">Governors</h2>
        <p class="muted">{{ failed() }}</p>
      } @else {<p class="muted">Loading…</p>}
    </section>
  `,
})
export class GovernorsComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly data = signal<GovernorsView | null>(null);
  protected readonly failed = signal('');
  protected readonly busy = signal(false);
  protected readonly dismissing = signal<number | null>(null);
  protected appointTo: Record<number, number | undefined> = {};

  /** Own cities, then the vassals of the open city (colonies are own cities already). */
  protected readonly targets = computed(() => {
    const own = (this.game.me()?.villages ?? []).map((c) => ({ id: c.id, name: c.name, vassal: false }));
    const ids = new Set(own.map((c) => c.id));
    const vassals = (this.game.village()?.vassals ?? [])
      .filter((x) => !ids.has(x.village.id))
      .map((x) => ({ id: x.village.id, name: x.village.name, vassal: true }));
    return [...own, ...vassals];
  });

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    try {
      this.data.set(await this.api.governors());
    } catch (e) {
      this.failed.set(this.game.errorText(e));
    }
  }

  protected isVassal(id: number): boolean {
    return !(this.game.me()?.villages ?? []).some((c) => c.id === id);
  }

  private async run(fn: () => Promise<GovernorsView>, ok: string): Promise<void> {
    if (this.game.inspecting()) return;
    this.busy.set(true);
    try {
      this.data.set(await fn());
      this.game.toast(ok, 'good');
      const v = this.game.village();
      if (v) await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
    this.busy.set(false);
  }

  protected hire(index: number, name: string): void {
    const v = this.game.village();
    if (v) void this.run(() => this.api.hireGovernor(index, v.id), `${name} enters your service`);
  }

  protected appoint(g: Governor): void {
    const to = this.appointTo[g.id];
    const name = this.targets().find((c) => c.id === to)?.name ?? '';
    if (to) void this.run(() => this.api.appointGovernor(g.id, to), `${g.name} sets out for ${name}`);
  }

  protected recall(g: Governor): void {
    void this.run(() => this.api.recallGovernor(g.id), `${g.name} returns to court`);
  }

  /** Two steps: the first press arms the button. */
  protected dismiss(g: Governor): void {
    if (this.dismissing() !== g.id) {
      this.dismissing.set(g.id);
      return;
    }
    this.dismissing.set(null);
    void this.run(() => this.api.dismissGovernor(g.id), `${g.name} is dismissed`);
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
