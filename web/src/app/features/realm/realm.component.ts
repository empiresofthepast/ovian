import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { Government, GovernmentView, ResourceMap, VillageRef } from '../../core/models';
import { governmentEffects, resourceNamer } from '../../shared/effects';
import { UI } from '../../shared/ui';

/** The realm: government, the roads of the current city and its trade routes. */
@Component({
  selector: 'ov-realm',
  imports: [FormsModule, ...UI],
  template: `
    <div class="page-head"><h1 class="page-title">{{ 'nav.realm' | label }}</h1></div>

    <section class="panel">
      <h2 class="panel__title">{{ 'realm.government' | label: 'Government' }}</h2>
      @if (gov(); as g) {
        <p class="small">
          {{ 'realm.ruled_by' | label: 'Your cities are ruled by' }}: <strong>{{ g.label }}</strong>.
          @if (g.anarchy_until > game.now()) {
            <span class="bad">{{ 'realm.anarchy' | label: 'Anarchy' }}: {{ g.anarchy_until - game.now() | duration }} {{ 'realm.left' | label: 'left' }}.</span>
          }
          @if (g.can_change_at > game.now()) {
            <span class="muted">{{ 'realm.next_change' | label: 'Next change possible in' }} {{ g.can_change_at - game.now() | duration }}.</span>
          } @else {
            <span class="muted">{{ 'realm.change_note' | label: 'A change brings anarchy for' }} {{ g.anarchy_hours }}h.</span>
          }
        </p>
        <div class="cards">
          @for (o of g.options; track o.id) {
            <div class="card" [class.card--active]="o.id === g.current">
              <strong>{{ o.name }}@if (o.id === g.current) {<span class="muted small"> · {{ 'realm.current' | label: 'current' }}</span>}</strong>
              @if (o.text) {<p class="small muted">{{ o.text }}</p>}
              @if (effects(o); as fx) {
                @if (fx.length) {<ul class="small">@for (e of fx; track e) {<li>{{ e }}</li>}</ul>}
                @else if (!o.text) {<p class="small muted">{{ 'realm.no_effects' | label: 'No strengths, no weaknesses.' }}</p>}
              }
              @if (o.id !== g.current) {
                @if (confirmGov() === o.id) {
                  <div class="btn-row">
                    <button class="btn btn--primary btn--small" [disabled]="busy()" (click)="adopt(o)">{{ 'realm.confirm_adopt' | label: 'Yes, adopt it' }}</button>
                    <button class="btn btn--ghost btn--small" (click)="confirmGov.set(null)">{{ 'cancel' | label: 'Cancel' }}</button>
                  </div>
                } @else {
                  <button class="btn btn--small" [disabled]="g.can_change_at > game.now() || game.inspecting()" (click)="confirmGov.set(o.id)">{{ 'realm.adopt' | label: 'Adopt' }}</button>
                }
              }
            </div>
          }
        </div>
      } @else if (govError()) {
        <p class="muted small">{{ govError() }}</p>
      } @else {
        <p class="muted small">Loading…</p>
      }
    </section>

    @if (game.village(); as v) {
      <div class="realm">
        <section class="panel">
          <h2 class="panel__title">{{ 'realm.roads' | label: 'Roads' }} <span class="muted small">{{ v.name }}</span></h2>
          @if (v.roads; as r) {
            <p class="small muted">Armies, scouts and merchants go {{ r.speed }}× faster along a road. This city may have {{ r.max }} road{{ r.max === 1 ? '' : 's' }} ({{ r.list.length }} built), one more every {{ r.per_levels ?? 10 }} levels of its civic centre; {{ r.max_length }} tiles long at most.</p>
            @for (road of r.list; track road.id) {
              <div class="row small">
                <span class="grow">⟷ {{ road.to.name }} <span class="muted">({{ road.to.x }}|{{ road.to.y }})</span></span>
                @if (road.ready_at > game.now()) {<span class="muted">{{ 'realm.building' | label: 'building' }}</span><span class="timer">{{ road.ready_at - game.now() | duration }}</span>}
                @else {<span class="good">✓</span>}
                @if (confirmRoad() === road.id) {
                  <button class="btn btn--small" (click)="abandon(road.id)">{{ 'realm.confirm_abandon' | label: 'Abandon?' }}</button>
                  <button class="btn btn--ghost btn--small" (click)="confirmRoad.set(null)" aria-label="Cancel">✕</button>
                } @else {
                  <button class="btn btn--ghost btn--small" (click)="confirmRoad.set(road.id)" title="Abandon this road">✕</button>
                }
              </div>
            } @empty {<p class="muted small">{{ 'realm.no_roads' | label: 'No roads lead from this city.' }}</p>}

            @if (r.list.length < r.max) {
              <h3 class="subtitle">{{ 'realm.build_road' | label: 'Build a road' }}</h3>
              @if (roadTargets().length) {
                <form class="form" (ngSubmit)="buildRoad()">
                  <label class="field"><span>{{ 'realm.to' | label: 'To' }}</span>
                    <select name="roadTo" [ngModel]="roadTo()" (ngModelChange)="roadTo.set(+$event)">
                      @for (t of roadTargets(); track t.id) {<option [value]="t.id">{{ t.name }} ({{ t.x }}|{{ t.y }}) · {{ t.dist.toFixed(1) }} tiles</option>}
                    </select>
                  </label>
                  @if (roadPlan(); as p) {
                    <div class="small">
                      <ov-cost [cost]="p.cost" [have]="game.resources()" />
                      <span class="muted"> · <ov-icon key="stat.time" /> {{ p.seconds | duration: 's' }}</span>
                      @if (p.tooLong) {<p class="bad">{{ 'error.road_too_long' | label }}</p>}
                    </div>
                  }
                  <div><button class="btn btn--primary btn--small" [disabled]="!roadPlan() || roadPlan()!.tooLong || game.inspecting()">{{ 'realm.build' | label: 'Build road' }}</button></div>
                </form>
              } @else {
                <p class="muted small">{{ 'realm.no_road_targets' | label: 'Roads join this city to your other cities and to its vassals. There is none to join yet.' }}</p>
              }
            }
          } @else {
            <p class="muted small">{{ 'error.no_roads' | label }}</p>
          }
        </section>

        <section class="panel">
          <h2 class="panel__title">{{ 'realm.routes' | label: 'Trade routes' }} <span class="muted small">{{ v.name }}</span></h2>
          <p class="small muted">The market's merchants carry the same goods from this city, again and again. A run is skipped when goods or merchants are missing.</p>
          @for (t of v.routes ?? []; track t.id) {
            <div class="row small">
              <div class="grow">
                <div>→ {{ t.to.name }} <span class="muted">({{ t.to.x }}|{{ t.to.y }})</span></div>
                <div><ov-cost [cost]="t.resources" /> <span class="muted">{{ 'realm.every' | label: 'every' }} {{ t.every_ms | duration }}</span></div>
                @if (t.last_error) {<div class="bad">{{ 'error.' + t.last_error | label: t.last_error }}</div>}
              </div>
              <span class="timer" title="Next run">{{ t.next_at - game.now() | duration }}</span>
              <button class="btn btn--ghost btn--small" (click)="dropRoute(t.id)" title="Delete this route">✕</button>
            </div>
          } @empty {<p class="muted small">{{ 'realm.no_routes' | label: 'No trade routes from this city.' }}</p>}

          <h3 class="subtitle">{{ 'realm.add_route' | label: 'New route' }}</h3>
          <form class="form" (ngSubmit)="addRoute()">
            <div class="form__row">
              @if (myCities().length) {
                <label class="field"><span>{{ 'realm.my_city' | label: 'My city' }}</span>
                  <select name="routeCity" [ngModel]="''" (ngModelChange)="pickCity($event)">
                    <option value="">—</option>
                    @for (c of myCities(); track c.id) {<option [value]="c.x + ',' + c.y">{{ c.name }} ({{ c.x }}|{{ c.y }})</option>}
                  </select>
                </label>
              }
              <label class="field field--short"><span>x</span><input type="number" name="rx" [(ngModel)]="rx" /></label>
              <label class="field field--short"><span>y</span><input type="number" name="ry" [(ngModel)]="ry" /></label>
              <label class="field field--short"><span>{{ 'realm.every_hours' | label: 'Every (hours)' }}</span><input type="number" name="every" min="1" step="0.5" [(ngModel)]="every" /></label>
            </div>
            <div class="form__row">
              @for (id of resourceIds(); track id) {
                <label class="field field--short"><span><ov-icon [key]="'resource.' + id" /> {{ name(id) }}</span>
                  <input type="number" min="0" [name]="'r-' + id" [ngModel]="goods()[id] ?? 0" (ngModelChange)="setGood(id, $event)" /></label>
              }
            </div>
            <div><button class="btn btn--primary btn--small" [disabled]="!anyGoods() || game.inspecting()">{{ 'realm.add' | label: 'Add route' }}</button></div>
          </form>
        </section>
      </div>
    }
  `,
})
export class RealmComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  protected readonly name = resourceNamer();

  protected readonly gov = signal<GovernmentView | null>(null);
  protected readonly govError = signal('');
  protected readonly confirmGov = signal<string | null>(null);
  protected readonly confirmRoad = signal<number | null>(null);
  protected readonly busy = signal(false);

  protected readonly roadTo = signal<number | null>(null);
  protected rx = 0;
  protected ry = 0;
  protected every = 2;
  protected readonly goods = signal<ResourceMap>({});
  protected readonly anyGoods = computed(() => Object.values(this.goods()).some((n) => n > 0));
  protected readonly resourceIds = computed(() => this.engine.resourceIds());

  /** My other cities. */
  protected readonly myCities = computed(() => {
    const v = this.game.village();
    return (this.game.me()?.villages ?? []).filter((c) => c.id !== v?.id);
  });

  /** Cities a road may lead to: my other cities and this city's vassals, without a road yet. */
  protected readonly roadTargets = computed(() => {
    const v = this.game.village();
    if (!v) return [];
    const linked = new Set((v.roads?.list ?? []).map((r) => r.to.id));
    const seen = new Set<number>();
    const out: (Pick<VillageRef, 'id' | 'name' | 'x' | 'y'> & { dist: number })[] = [];
    for (const c of [...this.myCities(), ...(v.vassals ?? []).map((x) => x.village)]) {
      if (linked.has(c.id) || seen.has(c.id) || c.id === v.id) continue;
      seen.add(c.id);
      out.push({ id: c.id, name: c.name, x: c.x, y: c.y, dist: Math.hypot(c.x - v.x, c.y - v.y) });
    }
    return out.sort((a, b) => a.dist - b.dist);
  });

  protected readonly roadPlan = computed(() => {
    const v = this.game.village();
    const r = v?.roads;
    const id = this.roadTo() ?? this.roadTargets()[0]?.id;
    const t = this.roadTargets().find((x) => x.id === id);
    if (!r || !t) return null;
    const cost = Object.fromEntries(Object.entries(r.cost_per_tile).map(([k, n]) => [k, Math.ceil(n * t.dist)]));
    return { id: t.id, cost, seconds: r.seconds_per_tile * t.dist, tooLong: t.dist > r.max_length };
  });

  constructor() {
    void this.loadGov();
  }

  protected effects(g: Government): string[] {
    return governmentEffects(g, this.name);
  }

  private async loadGov(): Promise<void> {
    try {
      this.gov.set(await this.api.government());
    } catch (e) {
      this.govError.set(this.game.errorText(e));
    }
  }

  protected async adopt(g: Government): Promise<void> {
    this.busy.set(true);
    try {
      this.gov.set(await this.api.setGovernment(g.id));
      this.game.toast(`${g.name}: ${'the old order falls; anarchy until the new one settles'}`, 'good');
      const v = this.game.village();
      if (v) await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
    this.confirmGov.set(null);
    this.busy.set(false);
  }

  protected buildRoad(): void {
    const v = this.game.village();
    const p = this.roadPlan();
    if (v && p) void this.game.act(() => this.api.buildRoad(v.id, p.id), 'Road builders set to work');
  }

  protected async abandon(id: number): Promise<void> {
    const v = this.game.village();
    this.confirmRoad.set(null);
    if (!v) return;
    await this.game.act(async () => {
      await this.api.abandonRoad(id);
      return this.api.village(v.id);
    }, 'Road abandoned');
  }

  protected pickCity(value: string): void {
    if (!value) return;
    const [x, y] = value.split(',').map(Number);
    this.rx = x;
    this.ry = y;
  }

  protected setGood(id: string, n: number): void {
    this.goods.update((g) => ({ ...g, [id]: Math.max(0, Math.floor(Number(n) || 0)) }));
  }

  protected async addRoute(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    const resources = Object.fromEntries(Object.entries(this.goods()).filter(([, n]) => n > 0));
    if (await this.game.act(() => this.api.addRoute(v.id, Number(this.rx), Number(this.ry), resources, Number(this.every)), 'Trade route added')) {
      this.goods.set({});
    }
  }

  protected dropRoute(id: number): void {
    void this.game.act(() => this.api.dropRoute(id), 'Trade route removed');
  }
}
