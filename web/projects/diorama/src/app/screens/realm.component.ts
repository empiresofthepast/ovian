import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api, ApiError } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { ContentmentView, Government, GovernmentView, ResourceMap } from '@core/models';
import { politicsText } from '@core/politics';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

/** Government, the people's mood, roads and trade routes. */
@Component({
  selector: 'dio-realm',
  imports: [FormsModule, ...UI],
  template: `
    <section class="hud-panel dialog realm" role="dialog" aria-label="Realm">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Realm</h2>
      <div class="seg" role="tablist" aria-label="Realm">
        @for (t of tabs; track t.id) {<button type="button" role="tab" class="seg__opt" [class.seg__opt--on]="tab() === t.id" (click)="tab.set(t.id)">{{ t.label }}</button>}
      </div>

      @if (tab() === 'people') {
        @if (game.village()?.contentment; as c) {
          @if (c.score !== undefined) {
            <div class="mood" [class.good]="c.score! >= 10" [class.bad]="c.score! < 0">
              <span class="mood__face" aria-hidden="true">{{ face(c.score!) }}</span>
              <div>
                <div><strong>{{ c.score }}</strong> contentment in {{ game.village()?.name }}</div>
                <div class="small">{{ (c.production ?? 0) >= 0 ? '+' : '' }}{{ ((c.production ?? 0) * 100).toFixed(1) }}% production</div>
              </div>
            </div>
            <table class="table factors">
              <tbody>
                @for (f of c.factors; track f.label) {<tr><td>{{ f.label }}</td><td class="num" [class.good]="f.value > 0" [class.bad]="f.value < 0">{{ f.value > 0 ? '+' : '' }}{{ f.value }}</td></tr>}
              </tbody>
            </table>
            @if (c.can_rebel) {
              <h3 class="subhead">Unrest</h3>
              <div class="bar" [title]="c.unrest + ' / ' + c.rebel_at"><div class="bar__fill bar__fill--bad" [style.width.%]="(c.unrest! / c.rebel_at!) * 100"></div></div>
              <p class="small muted">Below {{ c.rebel_below }} contentment a vassal grows restless; at {{ c.rebel_at }} unrest it rises up and stops paying tribute. Now {{ c.unrest | n }}.</p>
            }
          }
          @if (politics(c).length) {
            <h3 class="subhead">Politics</h3>
            @for (t of politics(c); track t) {<div class="small good">{{ t }}</div>}
          }
          @if (c.effects.length) {
            <h3 class="subhead">For a while</h3>
            @for (e of c.effects; track $index) {
              <div class="small">{{ e.label }}: <span [class.good]="e.value > 0" [class.bad]="e.value < 0">{{ e.kind === 'boost' ? ((e.value > 0 ? '+' : '') + (e.value * 100).toFixed(0) + '% production') : ((e.value > 0 ? '+' : '') + e.value + ' contentment') }}</span>
                <span class="muted">{{ e.until - game.now() | dur: 'ms' }}</span></div>
            }
          }
          <p class="small muted">Culture, food to spare and good omens please the people; hunger, tribute, lost battles, crowding and winter anger them. Happy cities produce up to 10% more, angry ones up to 40% less.</p>
        } @else {<p class="muted">This world has no rules about contentment.</p>}
      }

      @if (tab() === 'government') {
        @if (gov(); as g) {
          <p>Your realm is a <strong>{{ g.label }}</strong>.
            @if (g.anarchy_until > game.now()) {<span class="bad"> Anarchy for another {{ g.anarchy_until - game.now() | dur: 'ms' }}.</span>}
          </p>
          <div class="gov-grid">
            @for (o of g.options; track o.id) {
              <div class="gov" [class.gov--on]="o.id === g.current">
                <strong>{{ o.name }}</strong>
                @if (o.text) {<div class="small muted">{{ o.text }}</div>}
                <ul class="small effects">@for (e of effects(o); track e.text) {<li [class.good]="e.good" [class.bad]="!e.good">{{ e.text }}</li>} @empty {<li class="muted">No strengths, no weaknesses.</li>}</ul>
                @if (o.id === g.current) {<span class="tag">current</span>} @else {
                  <button class="btn btn--small" [disabled]="g.can_change_at > game.now()" (click)="choose(o)">Proclaim</button>
                }
              </div>
            }
          </div>
          <p class="small muted">Changing brings {{ g.anarchy_hours * 3600 | dur }} of anarchy (−10% production, unhappy people).
            @if (g.can_change_at > game.now()) {Your people need {{ g.can_change_at - game.now() | dur: 'ms' }} before another change.}</p>
        } @else {<p class="muted">Loading…</p>}
      }

      @if (tab() === 'roads') {
        @if (game.village(); as v) {
          @if (v.roads; as r) {
            <p class="small muted">Armies, scouts and merchants travel {{ r.speed }}× faster along a road. This city may have {{ r.max }} road{{ r.max === 1 ? '' : 's' }} ({{ r.list.length }} built), one more every {{ r.per_levels ?? 10 }} levels of its civic centre. A road is at most {{ r.max_length }} tiles long; each tile costs <dio-cost [cost]="r.cost_per_tile" /> and {{ r.seconds_per_tile | dur }} of work.</p>
            @for (x of r.list; track x.id) {
              <div class="row-item">
                <span class="grow">⟷ {{ x.to.name }} <span class="muted">({{ x.to.x }}|{{ x.to.y }})</span>
                  @if (x.ready_at > game.now()) {<span class="muted small"> · ready in {{ x.ready_at - game.now() | dur: 'ms' }}</span>}</span>
                <button class="btn btn--ghost btn--small" (click)="abandon(x.id)">Abandon</button>
              </div>
            } @empty {<p class="small muted">No roads from {{ v.name }} yet.</p>}
            @if (roadTargets().length) {
              <div class="row-form">
                <select [ngModel]="roadTo" (ngModelChange)="setRoadTo($event)" aria-label="Road to">
                  @for (c of roadTargets(); track c.id) {<option [ngValue]="c.id">{{ c.name }} · {{ c.tiles }} tiles</option>}
                </select>
                <button class="btn btn--gold btn--small" [disabled]="!roadTo" (click)="buildRoad()">Build road</button>
              </div>
              @if (roadCost(); as rc) {<div class="small">Costs <dio-cost [cost]="rc.cost" [have]="game.resources()" />, {{ rc.seconds | dur }}</div>}
            } @else {<p class="small muted">Roads join your own cities and your vassals.</p>}
          } @else {<p class="muted">This world has no roads.</p>}

          <h3 class="subhead">Trade routes</h3>
          <p class="small muted">The market's merchants carry the same goods every few hours, as long as there are goods and free merchants.</p>
          @for (t of v.routes ?? []; track t.id) {
            <div class="row-item">
              <span class="grow">→ {{ t.to.name }} <dio-cost [cost]="t.resources" /> <span class="muted small">every {{ t.every_ms | dur: 'ms' }} · next {{ t.next_at - game.now() | dur: 'ms' }}</span>
                @if (t.last_error) {<span class="bad small"> · last run skipped: {{ errorLabel(t.last_error) }}</span>}</span>
              <button class="btn btn--ghost btn--small" (click)="dropRoute(t.id)">Stop</button>
            </div>
          } @empty {<p class="small muted">No trade routes from {{ v.name }}.</p>}
          <form class="route-form" (ngSubmit)="addRoute()">
            <div class="rally__target">
              <label>to x <input type="number" name="rx" [(ngModel)]="rx" /></label>
              <label>y <input type="number" name="ry" [(ngModel)]="ry" /></label>
              <label>every <input type="number" name="rh" min="1" [(ngModel)]="rh" /> h</label>
            </div>
            @if (others().length) {<div class="small muted">Your cities: @for (c of others(); track c.id) {<button type="button" class="linkbtn" (click)="rx = c.x; ry = c.y">{{ c.name }}</button> }</div>}
            <div class="res-inputs">
              @for (r of resources(); track r.id) {
                <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="'r-' + r.id" [(ngModel)]="goods[r.id]" [attr.aria-label]="r.name" /></label>
              }
            </div>
            <button class="btn btn--small">Add route</button>
          </form>
        }
      }
    </section>
  `,
})
export class RealmComponent {
  protected readonly game = inject(GameStore);
  protected readonly politics = (c: ContentmentView) => politicsText(c);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  protected readonly tabs = [{ id: 'people', label: 'People' }, { id: 'government', label: 'Government' }, { id: 'roads', label: 'Roads & routes' }];
  protected readonly tab = signal('people');
  protected readonly gov = signal<GovernmentView | null>(null);
  protected roadTo: number | null = null;
  protected rx = 0;
  protected ry = 0;
  protected rh = 4;
  protected goods: ResourceMap = {};
  protected readonly resources = computed(() =>
    (this.engine.pack()?.resources ?? []).map((r) => ({ id: r.id, name: r.name, icon: this.art.resourceIcon(r.id) })),
  );
  protected readonly others = computed(() => (this.game.me()?.villages ?? []).filter((c) => c.id !== this.game.village()?.id));
  protected readonly roadTargets = computed(() => {
    const v = this.game.village();
    if (!v?.roads) return [];
    const linked = new Set(v.roads.list.map((r) => r.to.id));
    const vassals = (v.vassals ?? []).map((x) => x.village);
    const all = [...this.others(), ...vassals.filter((x) => !this.others().some((o) => o.id === x.id))];
    return all
      .filter((c) => !linked.has(c.id))
      .map((c) => ({ id: c.id, name: c.name, tiles: Math.round(Math.hypot(c.x - v.x, c.y - v.y) * 10) / 10 }))
      .filter((c) => c.tiles <= v.roads!.max_length);
  });
  protected readonly roadCost = computed(() => {
    const v = this.game.village();
    const t = this.roadTargets().find((c) => c.id === this.roadToSig());
    if (!v?.roads || !t) return null;
    const cost = Object.fromEntries(Object.entries(v.roads.cost_per_tile).map(([k, n]) => [k, Math.ceil(n * t.tiles)]));
    return { cost, seconds: t.tiles * v.roads.seconds_per_tile };
  });
  private readonly roadToSig = signal<number | null>(null);

  constructor() {
    void this.load();
    const first = this.roadTargets()[0];
    if (first) this.setRoadTo(first.id);
  }

  private async load(): Promise<void> {
    try {
      this.gov.set(await this.api.government());
    } catch {
      /* the world may have no governments */
    }
  }

  protected setRoadTo(id: number | null): void {
    this.roadTo = id;
    this.roadToSig.set(id);
  }

  protected errorLabel(code: string): string {
    return this.game.errorText(new ApiError(409, code, code.replace(/_/g, ' ')));
  }

  protected face(score: number): string {
    return score >= 20 ? '😄' : score >= 5 ? '🙂' : score >= -5 ? '😐' : score >= -20 ? '😠' : '🔥';
  }

  protected effects(g: Government): { text: string; good: boolean }[] {
    const pct = (x: number) => `${x > 0 ? '+' : ''}${Math.round(x * 100)}%`;
    const out: { text: string; good: boolean }[] = [];
    for (const [r, n] of Object.entries(g.production ?? {})) {
      const name = r === 'all' ? 'production' : `${this.engine.pack()?.resources.find((x) => x.id === r)?.name ?? r}`;
      out.push({ text: `${pct(n)} ${name.toLowerCase()}`, good: n > 0 });
    }
    if (g.attack) out.push({ text: `${pct(g.attack)} attack`, good: g.attack > 0 });
    if (g.defense) out.push({ text: `${pct(g.defense)} defense`, good: g.defense > 0 });
    if (g.contentment) out.push({ text: `${g.contentment > 0 ? '+' : ''}${g.contentment} contentment`, good: g.contentment > 0 });
    if (g.favor) out.push({ text: `${pct(g.favor)} favor`, good: g.favor > 0 });
    if (g.trade_speed) out.push({ text: `${pct(g.trade_speed)} merchant speed`, good: g.trade_speed > 0 });
    if (g.march_speed) out.push({ text: `${pct(g.march_speed)} marching speed`, good: g.march_speed > 0 });
    return out;
  }

  protected async choose(g: Government): Promise<void> {
    try {
      this.gov.set(await this.api.setGovernment(g.id));
      this.game.toast(`${g.name} proclaimed. Anarchy first, then the new order.`, 'good');
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected async buildRoad(): Promise<void> {
    const v = this.game.village();
    if (v && this.roadTo && (await this.game.act(() => this.api.buildRoad(v.id, this.roadTo!), 'The road builders set to work'))) {
      this.setRoadTo(this.roadTargets()[0]?.id ?? null);
    }
  }

  protected async abandon(id: number): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    try {
      await this.api.abandonRoad(id);
      this.game.toast('Road abandoned', 'good');
      await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected async addRoute(): Promise<void> {
    const v = this.game.village();
    const goods = Object.fromEntries(Object.entries(this.goods).filter(([, n]) => Number(n) > 0).map(([k, n]) => [k, Math.floor(Number(n))]));
    if (v && (await this.game.act(() => this.api.addRoute(v.id, this.rx, this.ry, goods, this.rh), 'Trade route set up'))) this.goods = {};
  }

  protected async dropRoute(id: number): Promise<void> {
    await this.game.act(() => this.api.dropRoute(id), 'Trade route stopped');
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
