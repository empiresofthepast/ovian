import { DatePipe } from '@angular/common';
import { Component, DestroyRef, OnInit, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { ResourceMap, Treaty, TreatiesView } from '@core/models';
import { RealtimeService } from '@core/realtime.service';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

/** Pacts of peace between players, with an optional tribute. Shown in the Realm screen. */
@Component({
  selector: 'dio-treaties',
  imports: [FormsModule, DatePipe, ...UI],
  template: `
    @if (view(); as tv) {
      @if (tv.treacherous_until && tv.treacherous_until > game.now()) {
        <p class="small bad">⚠ You broke a pact: the map marks you as an oath-breaker for another {{ tv.treacherous_until - game.now() | dur: 'ms' }}, and your cities are unhappy about it.</p>
      }
      @for (t of tv.treaties; track t.id) {
        <div class="row-item">
          <span class="grow">
            🤝 <strong>{{ t.with.name }}</strong>
            @if (t.status === 'proposed') {<span class="tag tag--dim">{{ t.proposed_by_me ? 'proposed, awaiting them' : 'offered to you' }}</span>}
            @else if (t.ends_at) {<span class="tag tag--bad">notice given</span>} @else {<span class="tag">in force</span>}
            <div class="small">
              @if (t.tribute; as tr) {
                {{ tr.i_pay ? 'You pay ' + t.with.name : t.with.name + ' pays you' }} <dio-cost [cost]="tr.resources" /> every {{ tr.every_hours }} h
                @if (t.last_paid_at) {<span class="muted"> · last paid {{ t.last_paid_at | date: 'd MMM, HH:mm' }}</span>}
              } @else {<span class="muted">No tribute.</span>}
            </div>
            <div class="small muted">
              @if (t.since) {In force since {{ t.since | date: 'd MMM, HH:mm' }}} @else {Proposed {{ t.created_at | date: 'd MMM, HH:mm' }}}
              @if (t.ends_at) {<span class="bad"> · ends in {{ t.ends_at - game.now() | dur: 'ms' }}</span>}
            </div>
          </span>
          @if (t.status === 'proposed') {
            @if (!t.proposed_by_me) {<button class="btn btn--gold btn--small" (click)="accept(t)">Accept</button>}
            <button class="btn btn--ghost btn--small" (click)="end(t)">{{ t.proposed_by_me ? 'Withdraw' : 'Decline' }}</button>
          } @else if (!t.ends_at) {
            <button class="btn btn--ghost btn--small" (click)="end(t)" [title]="'The pact holds ' + tv.rules.notice_hours + ' h more, then ends'">Give notice</button>
          }
        </div>
      } @empty {<p class="small muted">No pacts. Propose one to a neighbour below.</p>}

      <h3 class="subhead">Propose a pact</h3>
      <form class="route-form" (ngSubmit)="propose()">
        <div class="rally__target">
          <input name="to" [(ngModel)]="to" placeholder="Player name" aria-label="Player" style="width: 160px" />
          <label class="small"><input type="checkbox" name="withTribute" [(ngModel)]="withTribute" style="width: auto" /> with tribute</label>
        </div>
        @if (withTribute) {
          <div class="rally__target">
            <select name="payer" [(ngModel)]="payer" aria-label="Who pays">
              <option value="me">I pay them</option>
              <option value="them">They pay me</option>
            </select>
            <label>every <input type="number" name="every" [min]="tv.rules.min_tribute_hours" [(ngModel)]="every" /> h</label>
          </div>
          <div class="res-inputs">
            @for (r of resources(); track r.id) {
              <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="'t-' + r.id" [(ngModel)]="goods[r.id]" [attr.aria-label]="r.name" /></label>
            }
          </div>
        }
        <button class="btn btn--gold btn--small" [disabled]="!to.trim()">Propose</button>
      </form>
      <p class="small muted">
        A pact is a promise of peace. Attacking or raiding a pact partner is still possible, but it breaks the pact: the breaker is marked as an oath-breaker on the map for {{ tv.rules.treachery_hours }} h
        and their cities lose {{ 0 - tv.rules.treachery_mood }} contentment. Either side may give notice; the pact then holds {{ tv.rules.notice_hours }} h more.
        A tribute goes from the payer's first city to the other's first city every few hours (at least {{ tv.rules.min_tribute_hours }} h); if it cannot be paid, the pact lapses.
      </p>
    } @else if (missing()) {<p class="muted">This world has no pacts between players.</p>} @else {<p class="muted">Loading…</p>}
  `,
})
export class TreatiesComponent implements OnInit {
  /** Pre-fill the proposal (from a player on the map). */
  readonly prefill = input<string | null>(null);
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  protected readonly view = signal<TreatiesView | null>(null);
  /** The world has no pacts (or they could not be loaded). */
  protected readonly missing = signal(false);
  protected to = '';
  protected withTribute = false;
  protected payer: 'me' | 'them' = 'them';
  protected every = 24;
  protected goods: ResourceMap = {};
  protected readonly resources = computed(() =>
    (this.engine.pack()?.resources ?? []).map((r) => ({ id: r.id, name: r.name, icon: this.art.resourceIcon(r.id) })),
  );

  constructor() {
    void this.load();
    const sub = inject(RealtimeService).messages.subscribe((m) => {
      if (m.path.startsWith('player/') && m.event.type.startsWith('treaty.')) void this.load();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  ngOnInit(): void {
    const name = this.prefill();
    if (name) this.to = name;
  }

  private async load(): Promise<void> {
    try {
      const v = await this.api.treaties();
      this.view.set(v);
      if (this.every < v.rules.min_tribute_hours) this.every = v.rules.min_tribute_hours;
    } catch {
      this.missing.set(true);
    }
  }

  private async run(order: () => Promise<unknown>, success: string): Promise<boolean> {
    try {
      await order();
      this.game.toast(success, 'good');
      return true;
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      return false;
    }
  }

  protected async propose(): Promise<void> {
    const resources = Object.fromEntries(Object.entries(this.goods).filter(([, n]) => Number(n) > 0).map(([k, n]) => [k, Math.floor(Number(n))]));
    const tribute = this.withTribute && Object.keys(resources).length ? { payer: this.payer, resources, every_hours: Number(this.every) } : undefined;
    const name = this.to.trim();
    if (await this.run(() => this.api.proposeTreaty(name, tribute), `Pact proposed to ${name}`)) {
      this.to = '';
      this.goods = {};
      this.withTribute = false;
      await this.load();
    }
  }

  protected async accept(t: Treaty): Promise<void> {
    if (await this.run(() => this.api.acceptTreaty(t.id), `Pact with ${t.with.name} in force`)) await this.load();
  }

  protected async end(t: Treaty): Promise<void> {
    const msg = t.status === 'proposed' ? (t.proposed_by_me ? 'Proposal withdrawn' : 'Proposal declined') : `Notice given to ${t.with.name}`;
    if (await this.run(() => this.api.endTreaty(t.id), msg)) await this.load();
  }
}
