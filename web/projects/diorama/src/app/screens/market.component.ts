import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { ResourceMap, TradeOffer } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

@Component({
  selector: 'dio-market',
  imports: [FormsModule, RouterLink, ...UI],
  template: `
    <section class="hud-panel dialog market" role="dialog" aria-label="Market">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Market</h2>
      @if (game.village()?.market; as mk) {
        @if (!mk.merchants) {
          <p class="muted">Build a market in this city to hire merchants. Each level adds one.</p>
        } @else {
          <p class="small">Merchants: <strong>{{ mk.merchants - mk.busy }}</strong> of {{ mk.merchants }} free, each carrying {{ mk.carry | n }}, at {{ mk.speed }} tiles per hour.</p>
          <div class="market__cols">
            <form (ngSubmit)="send()">
              <h3 class="subhead">Send resources</h3>
              <div class="rally__target">
                <label>x <input type="number" name="sx" [(ngModel)]="sx" /></label>
                <label>y <input type="number" name="sy" [(ngModel)]="sy" /></label>
                <a class="btn btn--small" routerLink="/map">⌖ Map</a>
              </div>
              @if (cities().length) {
                <div class="small muted">Your cities: @for (c of cities(); track c.id) {<button type="button" class="linkbtn" (click)="sx = c.x; sy = c.y">{{ c.name }}</button> }</div>
              }
              <div class="res-inputs">
                @for (r of resources(); track r.id) {
                  <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="'s-' + r.id" [(ngModel)]="ship[r.id]" [attr.aria-label]="r.name" /></label>
                }
              </div>
              <div class="small muted">{{ need(ship) }} merchants</div>
              <button class="btn btn--gold btn--small">Send merchants</button>
            </form>
            <form (ngSubmit)="offer()">
              <h3 class="subhead">Make an offer</h3>
              <div class="small muted">Give</div>
              <div class="res-inputs">
                @for (r of resources(); track r.id) {
                  <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="'g-' + r.id" [(ngModel)]="give[r.id]" [attr.aria-label]="'Give ' + r.name" /></label>
                }
              </div>
              <div class="small muted">For</div>
              <div class="res-inputs">
                @for (r of resources(); track r.id) {
                  <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="'w-' + r.id" [(ngModel)]="want[r.id]" [attr.aria-label]="'Want ' + r.name" /></label>
                }
              </div>
              <button class="btn btn--small">Put on the market</button>
            </form>
          </div>
          @if (mk.shipments.length) {
            <h3 class="subhead">On the road</h3>
            @for (s of mk.shipments; track $index) {
              <div class="small">{{ s.outgoing ? '→ ' + s.to.name : '← ' + s.from.name }} <dio-cost [cost]="s.resources" /> <span class="muted">{{ s.arrives_at - game.now() | dur: 'ms' }}</span></div>
            }
          }
        }
        <h3 class="subhead">Offers</h3>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>From</th><th>Gives</th><th>Wants</th><th class="num">Tiles</th><th></th></tr></thead>
          <tbody>
            @for (o of offers(); track o.id) {
              <tr>
                <td>{{ o.village.name }} <span class="muted small">{{ o.player_name }}</span></td>
                <td><dio-cost [cost]="o.give" /></td>
                <td><dio-cost [cost]="o.want" /></td>
                <td class="num">{{ o.distance ?? '' }}</td>
                <td>@if (o.mine) {<button class="btn btn--small" (click)="cancel(o.id)">Withdraw</button>} @else {<button class="btn btn--gold btn--small" (click)="accept(o.id)">Accept</button>}</td>
              </tr>
            } @empty {<tr><td colspan="5" class="muted">No offers on the market.</td></tr>}
          </tbody>
        </table></div>
      }
    </section>
  `,
})
export class MarketComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  readonly x = input<string>();
  readonly y = input<string>();
  protected sx = 0;
  protected sy = 0;
  protected ship: ResourceMap = {};
  protected give: ResourceMap = {};
  protected want: ResourceMap = {};
  protected readonly offers = signal<TradeOffer[]>([]);
  protected readonly resources = computed(() =>
    (this.engine.pack()?.resources ?? []).map((r) => ({ id: r.id, name: r.name, icon: this.art.resourceIcon(r.id) })),
  );
  protected readonly cities = computed(() => (this.game.me()?.villages ?? []).filter((c) => c.id !== this.game.village()?.id));

  constructor() {
    queueMicrotask(() => {
      if (this.x() !== undefined) this.sx = Number(this.x());
      if (this.y() !== undefined) this.sy = Number(this.y());
    });
    void this.load();
  }

  private async load(): Promise<void> {
    const v = this.game.village();
    if (v) this.offers.set(await this.api.offers(v.id));
  }

  protected need(m: ResourceMap): number {
    const carry = this.game.village()?.market?.carry ?? 1000;
    return Math.ceil(Object.values(m).reduce((a, b) => a + (Number(b) || 0), 0) / carry);
  }

  private clean(m: ResourceMap): ResourceMap {
    return Object.fromEntries(Object.entries(m).filter(([, n]) => Number(n) > 0).map(([k, n]) => [k, Math.floor(Number(n))]));
  }

  protected async send(): Promise<void> {
    const v = this.game.village();
    if (v && (await this.game.act(() => this.api.ship(v.id, this.sx, this.sy, this.clean(this.ship)), 'The merchants set out'))) this.ship = {};
  }

  protected async offer(): Promise<void> {
    const v = this.game.village();
    if (v && (await this.game.act(() => this.api.offer(v.id, this.clean(this.give), this.clean(this.want)), 'Offer placed'))) {
      this.give = {};
      this.want = {};
      await this.load();
    }
  }

  protected async accept(id: number): Promise<void> {
    const v = this.game.village();
    if (v && (await this.game.act(() => this.api.acceptOffer(id, v.id), 'Deal! Both caravans set out'))) await this.load();
  }

  protected async cancel(id: number): Promise<void> {
    if (await this.game.act(() => this.api.cancelOffer(id), 'Offer withdrawn')) await this.load();
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
