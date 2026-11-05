import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { ResourceMap, Treaty, TreatiesView } from '../../core/models';
import { resourceNamer } from '../../shared/effects';
import { UI } from '../../shared/ui';

/** Pacts of peace between players, with an optional tribute. */
@Component({
  selector: 'ov-treaties',
  imports: [FormsModule, DatePipe, ...UI],
  template: `
    <section class="panel" id="pacts">
      <h2 class="panel__title">{{ 'treaty.title' | label: 'Pacts' }}</h2>
      @if (view(); as tv) {
        @if (tv.treacherous_until && tv.treacherous_until > game.now()) {
          <p class="callout callout--bad small">{{ 'treaty.treacherous' | label: 'You broke a pact. The map marks you as an oath-breaker and your cities are restless' }}
            ({{ tv.rules.treachery_mood }} {{ 'treaty.contentment' | label: 'contentment' }}) {{ 'treaty.for' | label: 'for' }} {{ tv.treacherous_until - game.now() | duration }}.</p>
        }
        <p class="small muted">A pact is a promise of peace. Attacking or raiding a partner is still possible, but it breaks the pact:
          the breaker is marked as an oath-breaker on the map for {{ tv.rules.treachery_hours }}h and their cities lose {{ -tv.rules.treachery_mood }} contentment.
          Either side may give notice; the pact then holds {{ tv.rules.notice_hours }}h more. A tribute goes from the payer's first city to the other's first city
          at the agreed interval; if it cannot be paid, the pact lapses.</p>

        @for (t of tv.treaties; track t.id) {
          <div class="row small">
            <div class="grow">
              <div><strong>{{ t.with.name }}</strong> <span class="tag" [class.tag--reinforce]="t.status === 'active' && !t.ends_at" [class.tag--raid]="t.status === 'proposed' || t.ends_at">{{ status(t) }}</span></div>
              <div>
                @if (t.tribute; as tr) {
                  @if (tr.i_pay) {You pay {{ t.with.name }}} @else {{{ t.with.name }} pays you}
                  <ov-cost [cost]="tr.resources" /> <span class="muted">{{ 'realm.every' | label: 'every' }} {{ tr.every_hours }}h</span>
                } @else {<span class="muted">{{ 'treaty.no_tribute' | label: 'No tribute' }}</span>}
              </div>
              <div class="muted">
                @if (t.since) {{{ 'treaty.since' | label: 'Sworn' }} {{ t.since | date: 'short' }}} @else {{{ 'treaty.proposed_at' | label: 'Proposed' }} {{ t.created_at | date: 'short' }}}
                @if (t.tribute && t.since) { · {{ 'treaty.last_paid' | label: 'last paid' }} {{ t.last_paid_at ? (t.last_paid_at | date: 'short') : '—' }}}
                @if (t.ends_at) { · <span class="bad">{{ 'treaty.ends_in' | label: 'ends in' }} {{ t.ends_at - game.now() | duration }}</span>}
              </div>
            </div>
            @if (t.status === 'proposed') {
              @if (t.proposed_by_me) {
                <button class="btn btn--ghost btn--small" [disabled]="busy() || game.inspecting()" (click)="end(t, 'Proposal withdrawn')">{{ 'treaty.withdraw' | label: 'Withdraw' }}</button>
              } @else {
                <button class="btn btn--primary btn--small" [disabled]="busy() || game.inspecting()" (click)="accept(t)">{{ 'treaty.accept' | label: 'Accept' }}</button>
                <button class="btn btn--ghost btn--small" [disabled]="busy() || game.inspecting()" (click)="end(t, 'Proposal declined')">{{ 'treaty.decline' | label: 'Decline' }}</button>
              }
            } @else if (!t.ends_at) {
              @if (confirm() === t.id) {
                <button class="btn btn--small" [disabled]="busy()" (click)="end(t, 'Notice given')">{{ 'treaty.confirm_notice' | label: 'End it?' }}</button>
                <button class="btn btn--ghost btn--small" (click)="confirm.set(null)" aria-label="Cancel">✕</button>
              } @else {
                <button class="btn btn--ghost btn--small" [disabled]="game.inspecting()" (click)="confirm.set(t.id)" [title]="'The pact holds ' + tv.rules.notice_hours + 'h more'">{{ 'treaty.notice' | label: 'Give notice' }}</button>
              }
            }
          </div>
        } @empty {<p class="muted small">{{ 'treaty.none' | label: 'No pacts, no proposals.' }}</p>}

        <h3 class="subtitle">{{ 'treaty.propose' | label: 'Propose a pact' }}</h3>
        <form class="form" (ngSubmit)="propose()">
          <div class="form__row">
            <label class="field"><span>{{ 'treaty.player' | label: 'Player' }}</span>
              <input name="to" [ngModel]="to()" (ngModelChange)="to.set($event)" required maxlength="40" /></label>
            <label class="field"><span>{{ 'treaty.tribute' | label: 'Tribute' }}</span>
              <select name="payer" [ngModel]="payer()" (ngModelChange)="payer.set($event)">
                <option value="">{{ 'treaty.no_tribute' | label: 'No tribute' }}</option>
                <option value="me">{{ 'treaty.i_pay' | label: 'I pay them' }}</option>
                <option value="them">{{ 'treaty.they_pay' | label: 'They pay me' }}</option>
              </select>
            </label>
            @if (payer()) {
              <label class="field field--short"><span>{{ 'realm.every_hours' | label: 'Every (hours)' }}</span>
                <input type="number" name="tevery" [min]="tv.rules.min_tribute_hours" step="1" [(ngModel)]="every" /></label>
            }
          </div>
          @if (payer()) {
            <div class="form__row">
              @for (id of resourceIds(); track id) {
                <label class="field field--short"><span><ov-icon [key]="'resource.' + id" /> {{ name(id) }}</span>
                  <input type="number" min="0" [name]="'t-' + id" [ngModel]="goods()[id] ?? 0" (ngModelChange)="setGood(id, $event)" /></label>
              }
            </div>
          }
          <div><button class="btn btn--primary btn--small" [disabled]="busy() || !to().trim() || (!!payer() && !anyGoods()) || game.inspecting()">{{ 'treaty.send' | label: 'Propose' }}</button></div>
        </form>
      } @else if (error()) {
        <p class="muted small">{{ error() }}</p>
      } @else {
        <p class="muted small">Loading…</p>
      }
    </section>
  `,
})
export class TreatiesComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  protected readonly name = resourceNamer();
  /** Prefill the proposal with this player (e.g. from the map). */
  readonly invite = input<string | undefined>();

  protected readonly view = signal<TreatiesView | null>(null);
  protected readonly error = signal('');
  protected readonly busy = signal(false);
  protected readonly confirm = signal<number | null>(null);
  protected readonly to = signal('');
  protected readonly payer = signal<'' | 'me' | 'them'>('');
  protected every = 24;
  protected readonly goods = signal<ResourceMap>({});
  protected readonly anyGoods = computed(() => Object.values(this.goods()).some((n) => n > 0));
  protected readonly resourceIds = computed(() => this.engine.resourceIds());

  constructor() {
    void this.load();
    effect(() => {
      const w = this.invite();
      if (w) this.to.set(w);
    });
    const sub = this.game.playerEvents.subscribe((e) => {
      if (e.type.startsWith('treaty.')) void this.load();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  protected status(t: Treaty): string {
    if (t.status === 'proposed') return t.proposed_by_me ? 'awaiting reply' : 'offered to you';
    return t.ends_at ? 'ending' : 'active';
  }

  private async load(): Promise<void> {
    try {
      const v = await this.api.treaties();
      this.view.set(v);
      this.every = Math.max(this.every, v.rules.min_tribute_hours);
      this.error.set('');
    } catch (e) {
      this.error.set(this.game.errorText(e));
    }
  }

  private async run(order: () => Promise<unknown>, success: string): Promise<boolean> {
    this.busy.set(true);
    try {
      await order();
      this.game.toast(success, 'good');
      await this.load();
      return true;
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      return false;
    } finally {
      this.busy.set(false);
      this.confirm.set(null);
    }
  }

  protected accept(t: Treaty): void {
    void this.run(() => this.api.acceptTreaty(t.id), `A pact with ${t.with.name}`);
  }

  protected end(t: Treaty, success: string): void {
    void this.run(() => this.api.endTreaty(t.id), success);
  }

  protected setGood(id: string, n: number): void {
    this.goods.update((g) => ({ ...g, [id]: Math.max(0, Math.floor(Number(n) || 0)) }));
  }

  protected async propose(): Promise<void> {
    const to = this.to().trim();
    const payer = this.payer();
    const resources = Object.fromEntries(Object.entries(this.goods()).filter(([, n]) => n > 0));
    const tribute = payer ? { payer, resources, every_hours: Number(this.every) } : undefined;
    if (to && (await this.run(() => this.api.proposeTreaty(to, tribute), `Pact proposed to ${to}`))) {
      this.to.set('');
      this.payer.set('');
      this.goods.set({});
    }
  }
}
