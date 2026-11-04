import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { GovernorsView } from '../../core/models';
import { UI } from '../../shared/ui';
import { TraitsComponent } from './traits.component';

interface Place { id: number; name: string; x: number; y: number; vassal: boolean }

/** Governors: the people in service, where they rule, and the candidates on offer. */
@Component({
  selector: 'ov-governors',
  imports: [FormsModule, TraitsComponent, ...UI],
  template: `
    <div class="page-head"><h1 class="page-title">{{ 'nav.governors' | label: 'Governors' }}</h1>
      <button class="btn btn--ghost btn--small" (click)="load()" title="Refresh">↻</button></div>
    @if (error()) {<p class="bad">{{ error() }}</p>}
    @if (view(); as g) {
      <div class="realm">
        <section class="panel">
          <h2 class="panel__title">{{ 'governors.service' | label: 'In service' }} <span class="muted">{{ g.count }}/{{ g.max }}</span></h2>
          <p class="small muted">One governor for each city you hold or rule. In a vassal city yours rules as a prefect, and the people resent it.</p>
          @for (x of g.governors; track x.id) {
            <div class="gov">
              <div class="row row--wrap">
                <strong class="grow">{{ x.name }} <span class="muted small">{{ x.tribe | name: 'tribe' }}</span></strong>
                <ov-traits [traits]="x.traits" [summary]="true" />
              </div>
              <p class="small gov__where">
                @if (x.moving_to; as to) {
                  On the way to <strong>{{ to.name }}</strong> <span class="muted">({{ to.x }}|{{ to.y }})</span>,
                  arrives in <span class="timer">{{ (x.arrives_at ?? 0) - game.now() | duration }}</span>
                } @else if (x.village; as at) {
                  Rules <strong>{{ at.name }}</strong> <span class="muted">({{ at.x }}|{{ at.y }})</span>@if (at.player_id !== game.me()?.id) {<span class="muted">, as prefect</span>}
                } @else {
                  <span class="muted">At court, waiting for a city.</span>
                }
              </p>
              @if (!game.inspecting()) {
                <div class="row row--wrap small">
                  <select class="grow" [ngModel]="target()[x.id] ?? null" (ngModelChange)="setTarget(x.id, $event)" [attr.aria-label]="'Send ' + x.name + ' to'">
                    <option [ngValue]="null" disabled>Send to…</option>
                    @for (p of places(); track p.id) {
                      <option [ngValue]="p.id">{{ p.name }} ({{ p.x }}|{{ p.y }}){{ p.vassal ? ', vassal' : '' }}</option>
                    }
                  </select>
                  <button class="btn btn--small btn--primary" [disabled]="busy() || !target()[x.id]" (click)="appoint(x.id)">Appoint</button>
                  @if (x.village || x.moving_to) {
                    <button class="btn btn--ghost btn--small" [disabled]="busy()" (click)="recall(x.id)" title="Back to court">Recall</button>
                  }
                  @if (confirming() === x.id) {
                    <button class="btn btn--danger btn--small" [disabled]="busy()" (click)="dismiss(x.id)">Dismiss {{ x.name }}</button>
                    <button class="btn btn--ghost btn--small" (click)="confirming.set(null)">Keep</button>
                  } @else {
                    <button class="btn btn--ghost btn--small" (click)="confirming.set(x.id)">Dismiss…</button>
                  }
                </div>
              }
            </div>
          } @empty {<p class="small muted">No governors yet. Hire one below.</p>}
        </section>

        <section class="panel">
          <h2 class="panel__title">{{ 'governors.candidates' | label: 'On offer' }}
            <span class="muted small">new faces in {{ g.offer_until - game.now() | duration }}</span></h2>
          @if (!game.inspecting()) {
            <div class="row row--wrap small">
              <span class="grow">Hiring costs <ov-cost [cost]="g.cost" /></span>
              <label class="muted">paid by
                <select [ngModel]="payer()" (ngModelChange)="from.set($event)" aria-label="Paid by">
                  @for (c of game.me()?.villages ?? []; track c.id) {<option [ngValue]="c.id">{{ c.name }}</option>}
                </select></label>
            </div>
          }
          @for (c of g.candidates; track c.index) {
            <div class="row row--wrap">
              <strong class="grow">{{ c.name }}</strong>
              <ov-traits [traits]="c.traits" [summary]="true" />
              @if (!game.inspecting()) {
                <button class="btn btn--small btn--primary" [disabled]="busy() || g.count >= g.max" (click)="hire(c.index, c.name)"
                        [title]="g.count >= g.max ? ('error.too_many_governors' | label: 'One governor for each city you hold or rule.') : ''">Hire</button>
              }
            </div>
          } @empty {<p class="small muted">Nobody is on offer now.</p>}
          @if (g.count >= g.max) {<p class="small muted">You have as many governors as you hold or rule cities.</p>}
        </section>
      </div>
    } @else if (!error()) {
      <p class="muted">Loading…</p>
    }
  `,
  styles: `
    .gov { padding: 0.35rem 0 0.5rem; border-bottom: 1px dashed color-mix(in srgb, var(--border) 60%, transparent); }
    .gov:last-child { border-bottom: 0; }
    .gov .row { border-bottom: 0; }
    .gov__where { margin: 0.1rem 0 0.2rem; }
  `,
})
export class GovernorsComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  protected readonly view = signal<GovernorsView | null>(null);
  protected readonly error = signal('');
  protected readonly busy = signal(false);
  protected readonly confirming = signal<number | null>(null);
  protected readonly target = signal<Record<number, number | null>>({});
  protected readonly from = signal<number | null>(null);

  /** The city that pays for hiring: the chosen one, else the current city. */
  protected readonly payer = computed(() => {
    const own = this.game.me()?.villages ?? [];
    const id = this.from() ?? this.game.village()?.id;
    return own.find((c) => c.id === id)?.id ?? own[0]?.id ?? null;
  });

  /** Where a governor may go: your own cities and the vassals of the city you are in. */
  protected readonly places = computed<Place[]>(() => {
    const me = this.game.me();
    const own: Place[] = (me?.villages ?? []).map((c) => ({ id: c.id, name: c.name, x: c.x, y: c.y, vassal: false }));
    const vassals: Place[] = (this.game.village()?.vassals ?? [])
      .filter((x) => !own.some((o) => o.id === x.village.id))
      .map((x) => ({ id: x.village.id, name: x.village.name, x: x.village.x, y: x.village.y, vassal: true }));
    return [...own, ...vassals];
  });

  constructor() {
    void this.load();
  }

  protected async load(): Promise<void> {
    try {
      this.view.set(await this.api.governors());
      this.error.set('');
    } catch (e) {
      this.error.set(this.game.errorText(e));
    }
  }

  protected setTarget(id: number, village: number | null): void {
    this.target.update((t) => ({ ...t, [id]: village }));
  }

  /** Run an order that hands back the governors; refresh the city, whose governor may have changed. */
  private async run(order: () => Promise<GovernorsView>, success: string): Promise<boolean> {
    this.busy.set(true);
    try {
      this.view.set(await order());
      this.game.toast(success, 'good');
      const v = this.game.village();
      if (v) await this.game.selectVillage(v.id);
      return true;
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      return false;
    } finally {
      this.busy.set(false);
    }
  }

  protected hire(index: number, name: string): void {
    const from = this.payer();
    if (from !== null) void this.run(() => this.api.hireGovernor(index, from), `${name} enters your service`);
  }

  protected async appoint(id: number): Promise<void> {
    const to = this.target()[id];
    if (!to) return;
    const place = this.places().find((p) => p.id === to);
    if (await this.run(() => this.api.appointGovernor(id, to), `On the way to ${place?.name ?? 'the city'}`)) this.setTarget(id, null);
  }

  protected recall(id: number): void {
    void this.run(() => this.api.recallGovernor(id), 'Called back to court');
  }

  protected async dismiss(id: number): Promise<void> {
    if (await this.run(() => this.api.dismissGovernor(id), 'Dismissed')) this.confirming.set(null);
  }
}
