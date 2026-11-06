import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { maxLevel } from '@core/levels';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService, curveAt } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { Labels } from '@core/labels';
import { BuildingDef, CultureView, Plan, ResourceMap, UnitDef, VillageState } from '@core/models';
import { demolishInfo } from '@core/demolish';
import { foreignRole } from '@core/embassy';
import { cultureName, isSettler, scaleCost } from '@core/wiki';
import { missingTechs, techOptions } from '@core/research';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

interface Option {
  def: BuildingDef;
  icon: string | null;
  plan: Plan<{ cost: ResourceMap; seconds: number }> | null;
  cost: ResourceMap;
}

/** The 0 A.D.-style bottom panel: portrait, details and the command grid for one site. */
@Component({
  selector: 'dio-selection',
  imports: [FormsModule, ...UI],
  template: `
    <section class="hud-panel selection" aria-label="Selection">
      <button class="close" (click)="close.emit()" aria-label="Close" title="Close (Esc)">✕</button>
      <div class="selection__who">
        <dio-portrait [src]="portrait()" [alt]="title()" />
        <div>
          <h2 class="selection__title">{{ title() }}</h2>
          @if (specific()) {<div class="selection__specific">{{ specific() }}</div>}
          @if (def()) {<div class="selection__level">Level {{ level() }}@if (pending() > level()) { → {{ pending() }}}</div>}
        </div>
      </div>

      <div class="selection__body">
        @if (def(); as b) {
          @if (b.description) {<p class="muted">{{ b.description }}</p>}
          <p class="small"><ov-wiki kind="building" [id]="b.id" [tribe]="artTribe()" [label]="true" /></p>
          @if (b.unique === false && copies() > 1) {<p class="small muted">One of {{ copies() }} in this city: storage adds up and training runs in parallel.</p>}
          <dl class="effects">
            @for (e of effects(); track e.label) {
              <dt>{{ e.label }}</dt><dd>{{ e.now }}@if (e.next !== null) {<span class="next"> → {{ e.next }}</span>}</dd>
            }
          </dl>
          @if (gods(); as g) {
            <div class="culture">
              <div class="subhead">Favor · {{ favor() | n }} / {{ g.max | n }} <span class="muted small">+{{ g.rate | n }} per hour</span></div>
              @if (g.blessing) {<div class="small good">Blessing: +{{ (g.blessing.boost * 100).toFixed(0) }}% production for {{ g.blessing.until - game.now() | dur: 'ms' }}</div>}
              @if (g.shield) {<div class="small good">Divine shield: +{{ (g.shield.defense * 100).toFixed(0) }}% defense for {{ g.shield.until - game.now() | dur: 'ms' }}</div>}
              @if (g.fury) {<div class="small good">Battle fury awaits your next army: +{{ (g.fury * 100).toFixed(0) }}% attack</div>}
              <div class="powers">
                @for (p of powers(); track p.id) {
                  <div class="power">
                    <div class="grow"><strong>{{ p.name }}</strong> <span class="muted small">{{ p.cost }} favor</span><div class="small muted">{{ p.description }}</div>
                      @if (p.target) {
                        <div class="rally__target small"><label>x <input type="number" [(ngModel)]="wrathX" name="wx" /></label><label>y <input type="number" [(ngModel)]="wrathY" name="wy" /></label></div>
                      }
                    </div>
                    <button class="btn btn--small" [class.btn--gold]="favor() >= p.cost" [disabled]="favor() < p.cost || busy()" (click)="cast(p.id, p.target)">Call</button>
                  </div>
                }
              </div>
            </div>
          }
          @if (great(); as gb) {
            <div class="culture">
              @if (gb.building_until) {
                <div class="small muted">Level {{ gb.building_level }} is under construction, done at {{ when(gb.building_until) }}.</div>
              }
              @if (gb.complete) {
                <div class="subhead">Great building · complete</div>
              } @else {
                <div class="subhead">Great building · level {{ gb.next_level }} {{ gb.points | n }} / {{ gb.cost | n }}</div>
                <div class="bar"><div class="bar__fill" [style.width.%]="((gb.points ?? 0) / (gb.cost ?? 1)) * 100"></div></div>
                <p class="small muted">Anyone can contribute resources from the map; when the level's cost is met, its construction begins. Contributors from other cities get half back.</p>
                @for (c of gb.contributors ?? []; track c.player_id) {<div class="small">{{ c.name }}: {{ c.points | n }}</div>}
                <div class="res-inputs">
                  @for (r of resourceList(); track r.id) {
                    <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="'gb-' + r.id" [(ngModel)]="gift[r.id]" [attr.aria-label]="r.name" /></label>
                  }
                </div>
                <button class="btn btn--small" [disabled]="busy()" (click)="contribute(gb.building)">Contribute</button>
              }
            </div>
          }
          @if (def()?.id === 'market') {
            <button class="btn btn--gold btn--small" (click)="openMarket()">Open the market</button>
          }
          @if (verSacrum(); as vs) {
            <div class="culture">
              <div class="subhead">Ver sacrum · {{ vs.available }}/{{ vs.earned }} <span class="muted small">one every {{ vs.every }} levels</span></div>
              @if (vs.available) {
                <p class="small">The young of this city can leave to found a colony up to {{ vs.range }} tiles away. You will manage it, and it pays this city tribute.</p>
                <dio-cost [cost]="vs.cost" [have]="game.resources()" />
                <button class="btn btn--gold btn--small" (click)="chooseColonySite()">Choose a site on the map</button>
              } @else {
                <p class="small muted">The next ver sacrum comes with level {{ vs.next_at_level }}.</p>
              }
              @for (m of vs.migrations; track m.id) {
                <div class="small">Migrants to {{ m.name }} ({{ m.x }}|{{ m.y }}) · {{ m.arrives_at - game.now() | dur: 'ms' }}</div>
              }
              @for (c of vs.colonies; track c.id) {
                <div class="small">Colony <button type="button" class="linkbtn" (click)="goTo(c.id)" [title]="'Go to ' + c.name">{{ c.name }}</button> <span class="muted">({{ c.x }}|{{ c.y }})</span></div>
              }
            </div>
          }
          @if (culture(); as c) {
            <div class="culture">
              <div class="subhead">Culture · {{ c.culture | n }} <span class="muted small">reaching {{ c.radius }} tiles</span></div>
              @for (nb of c.neighbours.slice(0, 5); track nb.village.id) {
                <div class="culture__row small">
                  @if (emblem(nb.tribe)) {<img [src]="emblem(nb.tribe)" alt="" />}
                  <span class="grow">{{ nb.village.name }} <span class="muted">{{ nb.distance.toFixed(1) }}</span></span>
                  <span [class.good]="nb.attack_bonus > 0" title="Your prestige when you attack them">⚔ +{{ pct(nb.attack_bonus) }}</span>
                  <span [class.good]="nb.defense_bonus > 0" title="Your prestige when they attack you">⛨ +{{ pct(nb.defense_bonus) }}</span>
                </div>
              } @empty {<p class="small muted">No foreign city within reach of your culture.</p>}
            </div>
          }
        } @else if (chosen(); as o) {
          <h3 class="subhead">{{ nameOf(o.def.id) }}@if (nameOf(o.def.id) !== o.def.name) {<span class="muted small"> · {{ o.def.name }}</span>} <ov-wiki kind="building" [id]="o.def.id" [tribe]="artTribe()" /></h3>
          <p class="muted">{{ o.def.description }}</p>
          <p class="small muted">{{ o.def.unique === false ? (copiesOf(o.def.id) ? 'You can build several: you have ' + copiesOf(o.def.id) + ' already.' : 'You can build several of these.') : 'Only one per city.' }}</p>
          <dio-cost [cost]="o.cost" [have]="game.resources()" />
          @if (seconds(o); as secs) {<div class="small muted">⌛ {{ secs | dur }}</div>}
          @if (o.plan && !o.plan.ok) {<p class="bad small">{{ errorText(o.plan.error, o.def.requires) }}</p>}
          <button class="btn btn--gold" [disabled]="(o.plan && !o.plan.ok) || busy()" (click)="build(o.def.id)">Build {{ nameOf(o.def.id) }}</button>
        } @else {
          <p class="muted">Choose a building for this site.</p>
        }
      </div>

      <div class="selection__commands">
        @if (def(); as b) {
          @if (role() === 'embassy') {
            <p class="muted small">Your overlord's envoys live here. Only the overlord raises the embassy, and pays for it. If the city breaks free, it is left in ruins.</p>
          } @else if (role() === 'ruin') {
            <p class="muted small">The ruin of a former overlord's embassy. Pull it down to free the site.</p>
          @if (dig(); as g) {
            <div class="dig">
              <div class="subhead">Below this site</div>
              @for (l of g.layers; track $index) {
                <div class="dig__layer small" [class.muted]="l.dug">
                  <span class="grow"><strong>{{ l.name }}</strong>@if (l.style) {<span class="muted">, {{ l.style }}</span>} · level {{ l.level }} · {{ l.end }}</span>
                  <span class="tag" [class.tag--dim]="!l.dug">{{ l.dug ? 'dug' : 'not dug' }}</span>
                </div>
              } @empty {<p class="small muted">Nothing known. Older remains may lie deeper.</p>}
              @if (g.dig; as d) {
                <div class="tax-line small">
                  <span class="grow">⛏ Diggers at work</span>
                  <span class="job__time">{{ d.due_at - game.now() | dur: 'ms' }}</span>
                  <button class="btn btn--ghost btn--small" [disabled]="busy() || game.inspecting()" (click)="stopDig()">Call off</button>
                </div>
              } @else if (g.bare) {
                <p class="small muted">Dug down to the bare rock.</p>
              } @else {
                <dio-cost [cost]="g.cost" [have]="game.resources()" />
                <div class="small muted">⌛ {{ g.seconds | dur }}@if (g.ruin) { · clears the ruin}</div>
                <button class="btn btn--small" [disabled]="busy() || game.inspecting()" (click)="excavate()">Excavate</button>
              }
            </div>
          }
          } @else if (pending() < maxLv()) {
            <div class="upgrade">
              <div class="subhead">Upgrade to level {{ pending() + 1 }}</div>
              <dio-cost [cost]="upgrade().cost" [have]="game.resources()" />
              @if (upgrade().seconds) {<div class="small muted">⌛ {{ upgrade().seconds | dur }}</div>}
              @if (upgrade().error) {<p class="bad small">{{ errorText(upgrade().error, b.requires) }}</p>}
              <button class="btn btn--gold" [disabled]="!!upgrade().error || busy()" (click)="build()">Upgrade</button>
            </div>
          } @else {
            <p class="muted">Fully upgraded.</p>
          }
          @if (research().length && level() > 0) {
            <div class="subhead">Research</div>
            <div class="grid" role="list" aria-label="Research">
              @for (t of research(); track t.def.id) {
                <button class="cmd" role="listitem" [class.cmd--on]="tech() === t.def.id" [class.cmd--done]="t.status === 'done'"
                        (click)="tech.set(t.def.id); unit.set(null)" [title]="t.def.name + ' — ' + statusText(t.status)">
                  <dio-portrait [src]="art.techIcon(t.def.id)" [alt]="t.def.name" [small]="true" [locked]="t.status === 'locked'" />
                  @if (t.status === 'done') {<span class="cmd__mark">✓</span>} @else if (t.status === 'queued') {<span class="cmd__mark">⌛</span>}
                </button>
              }
            </div>
            @if (techInfo(); as t) {
              <div class="train">
                <div><strong>{{ t.def.name }}</strong> <span class="muted small">{{ statusText(t.status) }}</span></div>
                <p class="small muted">{{ t.def.description }}</p>
                @if (t.unlocks.length) {<p class="small">Unlocks: {{ t.unlocks.join(', ') }}</p>}
                @if (t.status === 'ready' || t.status === 'locked') {
                  <dio-cost [cost]="t.cost" [have]="game.resources()" />
                  @if (t.seconds) {<div class="small muted">⌛ {{ t.seconds | dur }}</div>}
                  @if (t.needs.length) {<p class="bad small">Needs {{ t.needs.join(', ') }}.</p>}
                  @else if (t.error) {<p class="bad small">{{ errorText(t.error, {}) }}</p>}
                  <button class="btn btn--gold btn--small" [disabled]="!!t.error || t.needs.length > 0 || busy()" (click)="doResearch(t.def.id)">Research</button>
                }
              </div>
            }
          }
          @if (trainable().length) {
            <div class="grid" role="list" aria-label="Train">
              @for (u of trainable(); track u.def.id) {
                <button class="cmd" role="listitem" [class.cmd--on]="unit() === u.def.id" [class.cmd--locked]="u.locked"
                        (click)="unit.set(u.def.id); tech.set(null)" [title]="u.def.name + (u.locked ? ' (locked)' : '')">
                  <dio-portrait [src]="u.icon" [alt]="u.def.name" [small]="true" [locked]="u.locked" />
                </button>
              }
            </div>
            @if (!techInfo() && unitInfo(); as u) {
              <div class="train">
                <div><strong>{{ u.def.name }}</strong> <span class="muted small">{{ u.def.class }}</span> <ov-wiki kind="unit" [id]="u.def.id" /></div>
                <div class="stats small">
                  <span title="Attack">⚔ {{ u.def.attack }}</span>
                  <span title="Defense against infantry / cavalry">⛨ {{ u.def.defense.infantry }} / {{ u.def.defense.cavalry }}</span>
                  <span title="Speed, tiles per hour">➶ {{ u.def.speed }}</span>
                  <span title="Loot carried">⚖ {{ u.def.carry }}</span>
                </div>
                @if (u.def.description) {<p class="small muted">{{ u.def.description }}</p>}
                <dio-cost [cost]="u.cost" [have]="game.resources()" />
                @if (u.factor > 1) {<p class="small muted">Settlers cost more for every city you hold and every settler you have: × {{ u.factor.toFixed(1) }}.</p>}
                @if (u.locked) {
                  <p class="bad small">Needs {{ u.needs }}.</p>
                } @else {
                  <form class="train__form" (ngSubmit)="train(u.def.id)">
                    <input type="number" min="1" [max]="u.max" name="count" [ngModel]="count()" (ngModelChange)="count.set(+$event)" aria-label="How many" />
                    <button type="button" class="btn btn--small" (click)="count.set(u.max)">max {{ u.max }}</button>
                    <button class="btn btn--gold btn--small" [disabled]="u.max < 1 || busy()">Train</button>
                  </form>
                }
              </div>
            }
          }
          @if (demolition(); as d) {
            <div class="demolish">
              @if (!confirming()) {
                <button class="btn btn--ghost btn--small" [disabled]="busy() || game.inspecting()" (click)="confirming.set(true)"
                        [title]="'Pull it down and get back ' + pct(d.share) + ' of what it cost'">Demolish…</button>
              } @else {
                <div class="subhead">Pull down {{ title() }} (level {{ level() }})?</div>
                <div class="small">You get back <dio-cost [cost]="d.refund" /> <span class="muted">({{ pct(d.share) }} of what it cost; what does not fit in your storage is lost).</span></div>
                @if (d.blocked) {<p class="bad small">{{ d.blocked }}</p>}
                <div class="btn-row">
                  <button class="btn btn--danger btn--small" [disabled]="!!d.blocked || busy()" (click)="demolish()">Demolish</button>
                  <button class="btn btn--ghost btn--small" (click)="confirming.set(false)">Keep it</button>
                </div>
              }
            </div>
          }
        } @else {
          <div class="grid" role="list" aria-label="Buildings">
            @for (o of options(); track o.def.id) {
              <button class="cmd" role="listitem" [class.cmd--on]="choice() === o.def.id" [class.cmd--locked]="o.plan && !o.plan.ok"
                      (click)="choice.set(o.def.id)" [title]="nameOf(o.def.id)">
                <dio-portrait [src]="o.icon" [alt]="nameOf(o.def.id)" [small]="true" [locked]="!!o.plan && !o.plan.ok" />
              </button>
            } @empty {<p class="muted">Every building already stands in this village.</p>}
          </div>
          @if (dig(); as g) {
            <div class="dig">
              <div class="subhead">Below this site</div>
              @for (l of g.layers; track $index) {
                <div class="dig__layer small" [class.muted]="l.dug">
                  <span class="grow"><strong>{{ l.name }}</strong>@if (l.style) {<span class="muted">, {{ l.style }}</span>} · level {{ l.level }} · {{ l.end }}</span>
                  <span class="tag" [class.tag--dim]="!l.dug">{{ l.dug ? 'dug' : 'not dug' }}</span>
                </div>
              } @empty {<p class="small muted">Nothing known. Older remains may lie deeper.</p>}
              @if (g.dig; as d) {
                <div class="tax-line small">
                  <span class="grow">⛏ Diggers at work</span>
                  <span class="job__time">{{ d.due_at - game.now() | dur: 'ms' }}</span>
                  <button class="btn btn--ghost btn--small" [disabled]="busy() || game.inspecting()" (click)="stopDig()">Call off</button>
                </div>
              } @else if (g.bare) {
                <p class="small muted">Dug down to the bare rock.</p>
              } @else {
                <dio-cost [cost]="g.cost" [have]="game.resources()" />
                <div class="small muted">⌛ {{ g.seconds | dur }}@if (g.ruin) { · clears the ruin}</div>
                <button class="btn btn--small" [disabled]="busy() || game.inspecting()" (click)="excavate()">Excavate</button>
              }
            </div>
          }
        }
      </div>
    </section>
  `,
})
export class SelectionComponent {
  readonly site = input.required<number>();
  readonly close = output();
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  protected readonly art = inject(ArtService);
  private readonly labels = inject(Labels);
  protected readonly busy = signal(false);
  protected readonly choice = signal<string | null>(null);
  protected readonly unit = signal<string | null>(null);
  protected readonly count = signal(1);

  constructor() {
    effect(() => {
      this.site();
      this.choice.set(null);
      this.unit.set(null);
      this.tech.set(null);
      this.confirming.set(false);
    });
  }

  protected readonly confirming = signal(false);

  /** Archaeology on an empty town site, a foreign site or a ruin: the known layers and the dig. */
  protected readonly dig = computed(() => {
    const v = this.game.village();
    const a = v?.archaeology;
    const pack = this.engine.pack();
    const i = this.site();
    if (!v || !a || !pack) return null;
    const ruin = this.role() === 'ruin';
    const slot = v.state.slots[i];
    const fields = pack.village.field_slots.length;
    const town = !!slot?.foreign || (i >= fields && i < fields + pack.village.center_slots);
    if (!town || (this.def() && !ruin)) return null;
    const known = a.sites[String(i)];
    const layers = [...(known?.layers ?? [])].reverse().map((l) => ({
      name: this.engine.building(l.building)?.name ?? l.building,
      style: l.style ? (pack.tribes.find((t) => t.id === l.style)?.name ?? this.art.civ(l.style)?.name ?? l.style) : '',
      level: l.level,
      end: l.end === 'ruined' ? 'fell to ruin' : 'pulled down',
      dug: l.dug,
    }));
    return {
      layers, ruin,
      bare: !!known?.probed && layers.every((l) => l.dug),
      dig: a.digs.find((d) => d.slot === i) ?? null,
      cost: a.cost,
      seconds: (a.hours * 3600) / (pack.world.speed || 1),
    };
  });

  async excavate(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.excavate(v.id, this.site()), 'The diggers are at work');
    this.busy.set(false);
  }

  async stopDig(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.stopDigging(v.id, this.site()), 'Dig called off');
    this.busy.set(false);
  }
  protected readonly demolition = computed(() => demolishInfo(this.engine, this.game.village(), this.site()));

  async demolish(): Promise<void> {
    const v = this.game.village();
    const name = this.title();
    if (!v) return;
    this.busy.set(true);
    if (await this.game.act(() => this.api.demolish(v.id, this.site()), `${name} pulled down`)) this.close.emit();
    this.busy.set(false);
  }

  private readonly tribe = computed(() => this.game.village()?.owner?.tribe ?? this.game.me()?.tribe ?? null);
  private readonly router = inject(Router);
  /** Shown on the growth building (civic centre / town hall). */
  protected readonly verSacrum = computed(() => {
    const growth = this.engine.pack()?.village.growth?.building ?? this.engine.pack()?.village.start?.buildings[0]?.building;
    return this.def()?.id === growth ? (this.game.village()?.ver_sacrum ?? null) : null;
  });

  protected wrathX = 0;
  protected wrathY = 0;
  protected gift: ResourceMap = {};
  protected readonly gods = computed(() => {
    const b = this.def()?.id;
    return b && b === ((this.engine.pack() as any)?.extensions?.gods?.building ?? 'temple') ? (this.game.village()?.gods ?? null) : null;
  });
  protected readonly favor = computed(() => {
    const g = this.gods();
    return g ? Math.min(g.max, g.favor + (g.rate * Math.max(0, this.game.now() - g.favor_at)) / 3_600_000) : 0;
  });
  protected readonly powers = computed(() => Object.entries(this.gods()?.powers ?? {}).map(([id, p]) => ({ id, ...p })));
  protected readonly great = computed(() => {
    const site = this.site();
    return this.game.village()?.great?.find((g) => g.slot === site) ?? null;
  });
  protected readonly resourceList = computed(() =>
    (this.engine.pack()?.resources ?? []).map((r) => ({ id: r.id, name: r.name, icon: this.art.resourceIcon(r.id) })),
  );

  protected async cast(power: string, target?: boolean): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.cast(v.id, power, target ? this.wrathX : undefined, target ? this.wrathY : undefined), 'The gods have answered');
    this.busy.set(false);
  }

  protected when(ms: number): string {
    return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  protected async contribute(building: string): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    const res = Object.fromEntries(Object.entries(this.gift).filter(([, n]) => Number(n) > 0).map(([k, n]) => [k, Math.floor(Number(n))]));
    this.busy.set(true);
    if (await this.game.act(() => this.api.contribute(v.id, building, v.id, res), 'Contribution made')) this.gift = {};
    this.busy.set(false);
  }

  protected openMarket(): void {
    void this.router.navigate(['/market']);
  }

  /** Opens the colony itself. */
  protected goTo(id: number): void {
    void this.router.navigateByUrl('/');
    void this.game.selectVillage(id);
  }

  protected chooseColonySite(): void {
    void this.router.navigate(['/map'], { queryParams: { colony: 1 } });
  }
  /** Each building keeps the style it was founded in; a new one in a vassal city follows the overlord. */
  protected readonly artTribe = computed(() => {
    const c = this.current();
    if (c?.style) return c.style;
    if (c?.building && c.level > 0) return this.tribe();
    const s = this.game.village()?.submission; // new buildings in a vassal city follow its overlord
    return s && !s.colony ? s.tribe : this.tribe();
  });
  private readonly live = computed<VillageState | null>(() => {
    const v = this.game.village();
    return v ? { ...v.state, resources: this.game.resources(), resources_at: this.game.now() } : null;
  });
  private readonly queue = computed(() => this.game.village()?.build_queue.map(({ slot, building, level }) => ({ slot, building, level })) ?? []);
  private readonly current = computed(() => this.game.village()?.state.slots[this.site()]);
  protected readonly def = computed(() => {
    const queued = this.game.village()?.build_queue.find((q) => q.slot === this.site());
    return this.engine.building(this.current()?.building ?? queued?.building);
  });
  protected readonly level = computed(() => this.current()?.level ?? 0);
  protected readonly maxLv = computed(() => { const b = this.def(); return b ? maxLevel(this.engine.pack(), this.game.village()?.state, b) : 0; });
  protected readonly foreignSite = computed(() => !!this.current()?.foreign);
  protected readonly role = computed(() => foreignRole(this.engine.pack(), this.def()?.id));
  protected readonly pending = computed(() =>
    Math.max(this.level(), ...(this.game.village()?.build_queue.filter((q) => q.slot === this.site()).map((q) => q.level) ?? [])),
  );
  protected readonly copies = computed(() => this.copiesOf(this.def()?.id ?? ''));
  protected copiesOf(id: string): number {
    const v = this.game.village();
    return v ? v.state.slots.filter((s) => s.building === id).length + v.build_queue.filter((q) => q.building === id && !v.state.slots[q.slot]?.building).length : 0;
  }
  /** What the building's own culture calls it (extensions.cultures), else the pack's name. */
  protected nameOf(building: string | null | undefined): string {
    return cultureName(this.engine.pack(), this.artTribe(), building) ?? this.engine.building(building)?.name ?? building ?? '';
  }
  protected readonly title = computed(() => (this.def() ? this.nameOf(this.def()!.id) : 'Building site'));
  /** The subtitle: the pack's generic name under a cultural one, else 0 A.D.'s own name for the structure. */
  protected readonly specific = computed(() => {
    const b = this.def();
    if (!b) return '';
    if (cultureName(this.engine.pack(), this.artTribe(), b.id)) return this.title() !== b.name ? b.name : '';
    const s = this.art.structure(this.artTribe(), b.id);
    return s?.specific && s.specific !== b.name ? s.specific : '';
  });
  protected readonly portrait = computed(() => {
    const b = this.def();
    return b ? this.art.buildingIcon(this.artTribe(), b.id) : this.art.url(this.art.civ(this.tribe())?.emblem);
  });

  protected readonly upgrade = computed(() => {
    const b = this.def();
    const live = this.live();
    if (!b || !live) return { cost: {} as ResourceMap, seconds: null as number | null, error: '' };
    const plan = this.engine.planBuild(live, this.queue(), this.site());
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
    const fmt = (n: number) => Math.round(n).toLocaleString('en-US');
    const pct = (n: number) => `${Math.round(n * 100)}%`;
    const rows: { label: string; now: string; next: string | null }[] = [];
    const e = b.effects;
    const row = (label: string, f: (l: number) => string) => rows.push({ label, now: f(lv), next: next === null ? null : f(next) });
    if (e.production) {
      const name = this.engine.pack()?.resources.find((r) => r.id === e.production!.resource)?.name ?? e.production.resource;
      row(`${name} per hour`, (l) => fmt(curveAt(e.production!.curve, l) * speed));
    }
    if (e.storage) row('Capacity', (l) => fmt(curveAt(e.storage!.curve, l)));
    if (e.defense) row('Defense bonus', (l) => pct(curveAt(e.defense, l)));
    if (e.culture) row('Culture', (l) => fmt(curveAt(e.culture, l)));
    if (e.contentment) row('Contentment', (l) => '+' + fmt(curveAt(e.contentment, l)));
    if (e.hide) row('Hidden from raiders', (l) => fmt(curveAt(e.hide, l)));
    if (e.build_speed) row('Construction time', (l) => pct(l > 0 ? curveAt(e.build_speed, l) : 1));
    if (e.train_speed) row('Training time', (l) => pct(l > 0 ? curveAt(e.train_speed, l) : 1));
    const growth = this.engine.pack()?.village.growth;
    if (growth?.building === b.id) {
      const phaseAt = (l: number) => [...growth.phases].reverse().find((p) => p.level <= l) ?? growth.phases[0];
      row('Phase', (l) => `${phaseAt(l).name} · ${phaseAt(l).center_slots} sites · ${phaseAt(l).build_queue ?? this.engine.pack()!.village.build_queue} builders`);
    }
    return rows;
  });

  protected readonly options = computed<Option[]>(() => {
    const live = this.live();
    const pack = this.engine.pack();
    if (!live || !pack || this.def()) return [];
    const taken = new Set([...live.slots.map((s) => s.building), ...this.queue().map((q) => q.building)]);
    return pack.buildings
      .filter((b) => b.slot === 'center' && !!b.foreign === this.foreignSite() && b.id !== 'ruin' && (b.unique === false || !taken.has(b.id)))
      .map((def) => ({
        def,
        icon: this.art.buildingIcon(this.artTribe(), def.id),
        plan: this.engine.planBuild(live, this.queue(), this.site(), def.id),
        cost: this.engine.buildCost(def.id, 1),
      }))
      .sort((a, b) => Number(!!a.plan && !a.plan.ok) - Number(!!b.plan && !b.plan.ok));
  });
  protected readonly chosen = computed(() => this.options().find((o) => o.def.id === this.choice()) ?? null);

  protected readonly trainable = computed(() => {
    const b = this.def();
    const live = this.live();
    const tribe = this.tribe();
    if (!b || !live || this.level() < 1) return [];
    const levels = new Map<string, number>();
    for (const s of live.slots) if (s.building) levels.set(s.building, Math.max(levels.get(s.building) ?? 0, s.level));
    return (this.engine.pack()?.units ?? [])
      .filter((u) => u.building === b.id && u.tribe === tribe)
      .map((def) => {
        const techs = missingTechs(this.engine, live, def.id);
        const locked = Object.entries(def.requires).some(([k, l]) => (levels.get(k) ?? 0) < l) || techs.length > 0;
        const needs = [this.requiresText(def.requires), ...techs].filter(Boolean).join(', ');
        const factor = isSettler(this.engine.pack(), def.id) ? (this.game.village()?.settler_price ?? 1) : 1;
        const cost = scaleCost(def.cost, factor);
        const max = Math.max(0, Math.floor(Math.min(...Object.entries(cost).filter(([, v]) => v > 0).map(([r, v]) => (live.resources[r] ?? 0) / v))));
        return { def, cost, factor, locked, needs, max: isFinite(max) ? (factor > 1 ? Math.min(max, 1) : max) : 0, icon: this.art.unitIcon(def.id) };
      });
  });
  protected readonly unitInfo = computed(() => {
    const list = this.trainable();
    return list.find((u) => u.def.id === this.unit()) ?? list.find((u) => !u.locked) ?? list[0] ?? null;
  });

  seconds(o: Option): number | null {
    return o.plan?.ok ? o.plan.plan.seconds : null;
  }

  protected readonly tech = signal<string | null>(null);
  protected readonly research = computed(() => {
    const b = this.def();
    const v = this.game.village();
    const live = this.live();
    return b && v && live ? techOptions(this.engine, v, live, b.id, this.tribe()) : [];
  });
  protected readonly techInfo = computed(() => this.research().find((t) => t.def.id === this.tech()) ?? null);

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

  statusText(s: string): string {
    return { done: 'researched', queued: 'in progress', ready: 'available', locked: 'locked' }[s] ?? s;
  }

  pct(x: number): string {
    return `${Math.round(x * 100)}%`;
  }

  emblem(tribe: string): string | null {
    return this.art.url(this.art.civ(tribe)?.emblem);
  }

  async doResearch(tech: string): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    await this.game.act(() => this.api.research(v.id, tech), `${this.engine.tech(tech)?.name ?? tech}: research started`);
    this.busy.set(false);
  }

  requiresText(req: Record<string, number>): string {
    const have = new Map<string, number>();
    for (const sl of this.game.village()?.state.slots ?? []) if (sl.building) have.set(sl.building, Math.max(have.get(sl.building) ?? 0, sl.level));
    return Object.entries(req)
      .filter(([b, l]) => (have.get(b) ?? 0) < l)
      .map(([b, l]) => `${this.engine.building(b)?.name ?? b} ${l}`)
      .join(', ');
  }

  errorText(code: string, req: Record<string, number>): string {
    const text = this.labels.label(`error.${code}`, code);
    return code === 'requirements' ? `${text} Needs ${this.requiresText(req)}.` : text;
  }

  async build(building?: string): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    const name = this.engine.building(building ?? this.def()?.id)?.name ?? '';
    await this.game.act(() => this.api.build(v.id, this.site(), building), building ? `${name}: construction started` : `${name}: upgrade started`);
    this.busy.set(false);
  }

  async train(unit: string): Promise<void> {
    const v = this.game.village();
    const n = Math.floor(this.count());
    if (!v || n < 1) return;
    this.busy.set(true);
    const def: UnitDef | undefined = this.engine.unit(unit);
    await this.game.act(() => this.api.train(v.id, unit, n), `Training ${n} × ${def?.name ?? unit}`);
    this.busy.set(false);
  }
}
