import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { maxLevel } from '../../core/levels';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { EngineService, curveAt } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { BuildingDef, Plan, ResourceMap, UnitDef, VillageState } from '../../core/models';
import { SkinService } from '../../core/skin.service';
import { UI } from '../../shared/ui';
import { missingTechs, techOptions } from '../../core/research';
import { demolishInfo } from '../../core/demolish';
import { foreignRole } from '../../core/embassy';
import { isSettler, scaleCost } from '../../core/wiki';
import { CultureView } from '../../core/models';
import { DigSiteComponent } from './dig-site.component';

interface Option {
  def: BuildingDef;
  plan: Plan<{ cost: ResourceMap; seconds: number }> | null;
  cost: ResourceMap;
}

@Component({
  selector: 'ov-slot-panel',
  imports: [FormsModule, DecimalPipe, DigSiteComponent, ...UI],
  template: `
    <section class="panel slot-panel">
      <button class="btn btn--ghost btn--small slot-panel__close" (click)="close.emit()" aria-label="Close">✕</button>
      @if (def(); as b) {
        <h2 class="panel__title"><ov-icon [key]="'building.' + b.id" /> {{ b.id | name: 'building' : tribe() }}
          <span class="muted">{{ 'level' | label: 'level' }} {{ level() }}</span></h2>
        @if ((b.id | name: 'building' : tribe()) !== b.name) {<p class="muted small"><em>{{ b.name }}</em></p>}
        @if (b.description) {<p class="muted">{{ b.description }}</p>}
        <p class="small"><ov-wiki kind="building" [id]="b.id" [tribe]="tribe()" [label]="true" /></p>
        @for (e of effects(); track e.label) {
          <div class="row small"><span class="grow">{{ e.label }}</span><span>{{ e.now }}</span>
            @if (e.next !== null) {<span class="muted">→ {{ e.next }}</span>}</div>
        }

        <div class="upgrade">
          @if (role() === 'embassy') {
            <p class="muted small">{{ 'embassy.vassal' | label: "Your overlord's envoys live here. Only the overlord raises the embassy, and pays for it. If the village breaks free, it is left in ruins." }}</p>
          } @else if (role() === 'ruin') {
            <p class="muted small">{{ 'embassy.ruin' | label: "The ruin of a former overlord's embassy. Pull it down to free the site." }}</p>
            <ov-dig-site [slot]="slot()" />
          } @else if (pending() >= maxLv()) {
            <p class="muted">{{ 'max_level' | label: 'Fully upgraded.' }}</p>
          } @else {
            <h3 class="subtitle">{{ 'upgrade_to' | label: 'Upgrade to level' }} {{ pending() + 1 }}</h3>
            <ov-cost [cost]="upgrade().cost" [have]="game.resources()" />
            @if (upgrade().seconds) {<div class="small muted"><ov-icon key="stat.time" /> {{ upgrade().seconds! | duration: 's' }}</div>}
            @if (upgrade().error) {<p class="bad small">{{ 'error.' + upgrade().error | label }}</p>}
            <button class="btn btn--primary" [disabled]="!!upgrade().error || busy()" (click)="build()">
              {{ 'upgrade' | label: 'Upgrade' }}
            </button>
          }
        </div>

        @if (demolition(); as d) {
          <div class="demolish">
            @if (!confirming()) {
              <button class="btn btn--ghost btn--small" [disabled]="busy() || game.inspecting()" (click)="confirming.set(true)">Demolish…</button>
            } @else {
              <h3 class="subtitle">Pull down {{ b.id | name: 'building' : tribe() }} (level {{ level() }})?</h3>
              <div class="small">You get back <ov-cost [cost]="d.refund" /></div>
              <p class="small muted">{{ d.share * 100 | number: '1.0-0' }}% of what it cost. Whatever does not fit in your storage is lost.</p>
              @if (d.blocked) {<p class="bad small">{{ d.blocked }}</p>}
              <div class="btn-row">
                <button class="btn btn--danger btn--small" [disabled]="!!d.blocked || busy()" (click)="demolish()">Demolish</button>
                <button class="btn btn--ghost btn--small" (click)="confirming.set(false)">Keep it</button>
              </div>
            }
          </div>
        }

        @if (b.effects.culture && level() > 0) {
          <h3 class="subtitle">{{ 'culture' | label: 'Culture' }}</h3>
          @if (culture(); as c) {
            <p class="small">This village: <strong>{{ c.culture | number: '1.0-0' }}</strong> culture, reaching {{ c.radius }} tiles.</p>
            @for (n of c.neighbours; track n.village.id) {
              <div class="row small">
                <span class="grow">{{ n.village.name }} <span class="muted">({{ n.player_name }}, {{ n.distance | number: '1.0-1' }} tiles)</span></span>
                <span [class.good]="n.attack_bonus > 0" title="Prestige when you attack them">⚔ +{{ n.attack_bonus * 100 | number: '1.0-0' }}%</span>
                <span [class.good]="n.defense_bonus > 0" title="Prestige when they attack you">⛨ +{{ n.defense_bonus * 100 | number: '1.0-0' }}%</span>
              </div>
            } @empty {<p class="small muted">No foreign village within reach.</p>}
          }
        }

        @if (research().length && level() > 0) {
          <h3 class="subtitle">{{ 'research' | label: 'Research' }}</h3>
          @for (t of research(); track t.def.id) {
            <div class="option" [class.option--locked]="t.status === 'locked'">
              <div class="row">
                <strong class="grow">{{ t.def.name }}</strong>
                @if (t.status === 'done') {<span class="good small">✓ researched</span>}
                @else if (t.status === 'queued') {<span class="small muted">in progress</span>}
                @else {<button class="btn btn--primary btn--small" [disabled]="!!t.error || busy()" (click)="researchTech(t.def.id)">{{ 'research' | label: 'Research' }}</button>}
              </div>
              <p class="small muted">{{ t.def.description }}@if (t.unlocks.length) { Unlocks {{ t.unlocks.join(', ') }}.}</p>
              @if (t.status === 'ready' || t.status === 'locked') {
                <ov-cost [cost]="t.cost" [have]="game.resources()" />
                @if (t.seconds) {<span class="small muted"><ov-icon key="stat.time" /> {{ t.seconds | duration: 's' }}</span>}
                @if (t.needs.length) {<p class="small bad">Needs {{ t.needs.join(', ') }}.</p>}
                @else if (t.error) {<p class="small bad">{{ 'error.' + t.error | label }}</p>}
              }
            </div>
          }
        }

        @if (trainable().length && level() > 0) {
          <h3 class="subtitle">{{ 'train' | label: 'Train' }}</h3>
          @for (u of trainable(); track u.def.id) {
            <div class="train">
              <div class="train__head">
                <ov-icon [key]="'unit.' + u.def.id" />
                <strong class="grow">{{ u.def.id | name: 'unit' }} <ov-wiki kind="unit" [id]="u.def.id" /></strong>
                <span class="small muted" title="attack / defense vs infantry / vs cavalry">
                  <ov-icon key="stat.attack" />{{ u.def.attack }} <ov-icon key="stat.defense" />{{ u.def.defense.infantry }}/{{ u.def.defense.cavalry }}
                  <ov-icon key="stat.speed" />{{ u.def.speed }} <ov-icon key="stat.carry" />{{ u.def.carry }}
                </span>
              </div>
              <ov-cost [cost]="u.cost" [have]="game.resources()" />
              @if (u.dearer) {<p class="small muted">Settlers cost more for every city you hold and every settler you have: × {{ u.factor | number: '1.0-1' }}.</p>}
              @if (u.locked) {
                <p class="small bad">{{ 'error.requirements' | label }} {{ u.requires }}</p>
              } @else {
                <form class="train__form" (ngSubmit)="train(u.def.id)">
                  <input type="number" min="1" [max]="u.max" [name]="'n-' + u.def.id" [ngModel]="counts()[u.def.id] ?? 1"
                         (ngModelChange)="setCount(u.def.id, $event)" aria-label="Count" />
                  <button type="button" class="btn btn--ghost btn--small" (click)="setCount(u.def.id, u.max)">max {{ u.max }}</button>
                  <button class="btn btn--primary btn--small" [disabled]="u.max < 1 || busy()">{{ 'train' | label: 'Train' }}</button>
                </form>
              }
            </div>
          }
        }
      } @else {
        <h2 class="panel__title">{{ 'empty_slot' | label }}</h2>
        <p class="muted small">{{ 'construct_hint' | label: 'Choose a building to construct here.' }}</p>
        @for (o of options(); track o.def.id) {
          <div class="option" [class.option--locked]="o.plan && !o.plan.ok">
            <div class="row">
              <ov-icon [key]="'building.' + o.def.id" />
              <strong class="grow">{{ o.def.id | name: 'building' : tribe() }}@if ((o.def.id | name: 'building' : tribe()) !== o.def.name) {<span class="muted"> · {{ o.def.name }}</span>} <ov-wiki kind="building" [id]="o.def.id" [tribe]="tribe()" /></strong>
              <button class="btn btn--primary btn--small" [disabled]="(o.plan && !o.plan.ok) || busy()" (click)="build(o.def.id)">
                {{ 'construct' | label: 'Build' }}
              </button>
            </div>
            <p class="small muted">{{ o.def.description }}@if (o.def.unique === false) {<em> Several allowed.</em>}</p>
            <ov-cost [cost]="o.cost" [have]="game.resources()" />
            @if (o.plan && !o.plan.ok) {
              <p class="small bad">{{ 'error.' + o.plan.error | label }}{{ o.plan.error === 'requirements' ? ' ' + requiresText(o.def.requires) : '' }}</p>
            }
          </div>
        } @empty {<p class="muted">Every building already stands in this village.</p>}
        <ov-dig-site [slot]="slot()" />
      }
    </section>
  `,
})
export class SlotPanelComponent {
  readonly slot = input.required<number>();
  readonly close = output();
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly skin = inject(SkinService);
  protected readonly busy = signal(false);
  protected readonly counts = signal<Record<string, number>>({});

  /** The village with resources at "now", so engine checks match what the player sees. */
  private readonly live = computed<VillageState | null>(() => {
    const v = this.game.village();
    return v ? { ...v.state, resources: this.game.resources(), resources_at: this.game.now() } : null;
  });
  private readonly queue = computed(() => this.game.village()?.build_queue.map(({ slot, building, level }) => ({ slot, building, level })) ?? []);

  private readonly current = computed(() => this.game.village()?.state.slots[this.slot()]);
  /** The culture whose name a building bears: the style it was founded in, else the owner's; a new one in a vassal city follows the overlord. */
  protected readonly tribe = computed(() => {
    const c = this.current();
    if (c?.style) return c.style;
    const v = this.game.village();
    const owner = v?.owner?.tribe ?? this.game.me()?.tribe ?? null;
    if (c?.building && c.level > 0) return owner;
    const s = v?.submission;
    return s && !s.colony ? s.tribe : owner;
  });
  protected readonly def = computed(() => {
    const queued = this.game.village()?.build_queue.find((q) => q.slot === this.slot());
    return this.engine.building(this.current()?.building ?? queued?.building);
  });
  protected readonly level = computed(() => this.current()?.level ?? 0);
  protected readonly maxLv = computed(() => { const b = this.def(); return b ? maxLevel(this.engine.pack(), this.game.village()?.state, b) : 0; });
  protected readonly foreignSite = computed(() => !!this.current()?.foreign);
  protected readonly role = computed(() => foreignRole(this.engine.pack(), this.def()?.id));
  protected readonly pending = computed(() =>
    Math.max(this.level(), ...(this.game.village()?.build_queue.filter((q) => q.slot === this.slot()).map((q) => q.level) ?? [])),
  );

  protected readonly upgrade = computed(() => {
    const b = this.def();
    const live = this.live();
    if (!b || !live) return { cost: {}, seconds: null as number | null, error: '' };
    const plan = this.engine.planBuild(live, this.queue(), this.slot());
    if (!plan) return { cost: this.engine.buildCost(b.id, this.pending() + 1), seconds: null, error: '' };
    return plan.ok
      ? { cost: plan.plan.cost, seconds: plan.plan.seconds, error: '' }
      : { cost: this.engine.buildCost(b.id, Math.min(this.pending() + 1, this.maxLv())), seconds: null, error: plan.error };
  });

  protected readonly effects = computed(() => {
    const b = this.def();
    if (!b) return [];
    const lv = this.level();
    const next = lv < this.maxLv() ? lv + 1 : null;
    const speed = this.engine.pack()?.world.speed ?? 1;
    const fmt = (n: number) => Math.round(n).toLocaleString();
    const pct = (n: number) => `${Math.round(n * 100)}%`;
    const rows: { label: string; now: string; next: string | null }[] = [];
    const e = b.effects;
    if (e.production) {
      const name = this.skin.label(`resource.${e.production.resource}`, e.production.resource);
      rows.push({ label: `${name} / h`, now: fmt(curveAt(e.production.curve, lv) * speed), next: next === null ? null : fmt(curveAt(e.production.curve, next) * speed) });
    }
    if (e.storage) rows.push({ label: this.skin.label('effect.storage', 'Capacity'), now: fmt(curveAt(e.storage.curve, lv)), next: next === null ? null : fmt(curveAt(e.storage.curve, next)) });
    if (e.defense) rows.push({ label: this.skin.label('effect.defense', 'Defense bonus'), now: pct(curveAt(e.defense, lv)), next: next === null ? null : pct(curveAt(e.defense, next)) });
    if (e.culture) rows.push({ label: this.skin.label('effect.culture', 'Culture'), now: fmt(curveAt(e.culture, lv)), next: next === null ? null : fmt(curveAt(e.culture, next)) });
    if (e.contentment) rows.push({ label: this.skin.label('effect.contentment', 'Contentment'), now: fmt(curveAt(e.contentment, lv)), next: next === null ? null : fmt(curveAt(e.contentment, next)) });
    if (e.hide) rows.push({ label: this.skin.label('effect.hide', 'Hidden per resource'), now: fmt(curveAt(e.hide, lv)), next: next === null ? null : fmt(curveAt(e.hide, next)) });
    const time = (c: typeof e.build_speed, l: number) => pct(l > 0 && c ? curveAt(c, l) : 1);
    if (e.build_speed) rows.push({ label: this.skin.label('effect.build_speed', 'Construction time'), now: time(e.build_speed, lv), next: next === null ? null : time(e.build_speed, next) });
    if (e.train_speed) rows.push({ label: this.skin.label('effect.train_speed', 'Training time'), now: time(e.train_speed, lv), next: next === null ? null : time(e.train_speed, next) });
    return rows;
  });

  protected readonly trainable = computed(() => {
    const b = this.def();
    const tribe = this.game.me()?.tribe;
    const live = this.live();
    if (!b || !live) return [];
    const have = this.game.resources();
    return (this.engine.pack()?.units ?? [])
      .filter((u) => u.building === b.id && u.tribe === tribe)
      .map((def: UnitDef) => {
        const factor = isSettler(this.engine.pack(), def.id) ? (this.game.village()?.settler_price ?? 1) : 1;
        const cost = scaleCost(def.cost, factor);
        const max = Math.min(...Object.entries(cost).filter(([, c]) => c > 0).map(([r, c]) => Math.floor((have[r] ?? 0) / c)));
        const plan = this.engine.planTraining(live, tribe!, def.id, 1);
        const techs = missingTechs(this.engine, live, def.id);
        const locked = (plan ? !plan.ok && (plan.error === 'requirements' || plan.error === 'tech_missing') : false) || techs.length > 0;
        return { def, cost, factor, dearer: factor > 1, max: isFinite(max) ? (factor > 1 ? Math.min(max, 1) : max) : 0, locked, requires: [this.requiresText(def.requires), ...techs].filter(Boolean).join(', ') };
      });
  });

  protected readonly options = computed<Option[]>(() => {
    const live = this.live();
    const v = this.game.village();
    if (!live || !v) return [];
    const taken = new Set([...v.state.slots.map((s) => s.building), ...v.build_queue.map((q) => q.building)]);
    return (this.engine.pack()?.buildings ?? [])
      .filter((b) => b.slot === 'center' && !!b.foreign === this.foreignSite() && b.id !== 'ruin' && (b.unique === false || !taken.has(b.id)))
      .map((def) => ({ def, plan: this.engine.planBuild(live, this.queue(), this.slot(), def.id), cost: this.engine.buildCost(def.id, 1) }))
      .sort((a, b) => Number(a.plan?.ok === false) - Number(b.plan?.ok === false));
  });

  protected readonly research = computed(() => {
    const b = this.def();
    const v = this.game.village();
    const live = this.live();
    return b && v && live ? techOptions(this.engine, v, live, b.id, this.game.me()?.tribe ?? null) : [];
  });

  protected readonly culture = signal<CultureView | null>(null);
  private readonly loadCulture = effect(() => {
    const b = this.def();
    const v = this.game.village();
    if (b?.effects.culture && v && this.level() > 0) {
      void this.api.culture(v.id).then((c) => this.culture.set(c)).catch(() => this.culture.set(null));
    } else {
      this.culture.set(null);
    }
  });

  protected async researchTech(tech: string): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.research(v.id, tech), `${this.engine.tech(tech)?.name ?? tech}: research started`);
    this.busy.set(false);
  }

  protected requiresText(req: Record<string, number>): string {
    const have: Record<string, number> = {};
    for (const s of this.game.village()?.state.slots ?? []) if (s.building) have[s.building] = Math.max(have[s.building] ?? 0, s.level);
    return Object.entries(req)
      .filter(([b, l]) => (have[b] ?? 0) < l)
      .map(([b, l]) => `${this.skin.label(`building.${b}`, this.engine.building(b)?.name)} ${l}`)
      .join(', ');
  }

  protected setCount(unit: string, n: number): void {
    this.counts.update((c) => ({ ...c, [unit]: Math.max(1, Math.floor(Number(n) || 1)) }));
  }

  protected readonly confirming = signal(false);
  protected readonly demolition = computed(() => demolishInfo(this.engine, this.game.village(), this.slot()));
  private readonly resetConfirm = effect(() => {
    this.slot();
    this.confirming.set(false);
  });

  protected async demolish(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    if (await this.game.act(() => this.api.demolish(v.id, this.slot()))) this.close.emit();
    this.busy.set(false);
  }

  protected async build(building?: string): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.build(v.id, this.slot(), building));
    this.busy.set(false);
  }

  protected async train(unit: string): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.train(v.id, unit, this.counts()[unit] ?? 1));
    this.busy.set(false);
  }
}
