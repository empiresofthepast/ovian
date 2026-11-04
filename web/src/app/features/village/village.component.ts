import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { UI } from '../../shared/ui';
import { SlotPanelComponent } from './slot-panel.component';
import { TutorialCardComponent } from './tutorial-card.component';
import { OmenCardComponent } from './omen-card.component';
import { ContentmentPanelComponent } from './contentment-panel.component';
import { FindsPanelComponent } from './finds-panel.component';
import { AuxiliariesComponent } from './auxiliaries.component';
import { TraitsComponent } from '../governors/traits.component';
import { Quest, Submission, vassalBenefits, EmbassyInfo } from '../../core/models';
import { embassyRules } from '../../core/embassy';

@Component({
  selector: 'ov-village',
  imports: [FormsModule, RouterLink, SlotPanelComponent, TutorialCardComponent, OmenCardComponent, ContentmentPanelComponent, FindsPanelComponent, AuxiliariesComponent, TraitsComponent, ...UI],
  template: `
    @if (game.village(); as v) {
      <div class="page-head">
        @if (renaming()) {
          <form class="rename" (ngSubmit)="saveName()">
            <input name="name" [(ngModel)]="newName" maxlength="40" required aria-label="Village name" />
            <button class="btn btn--primary">Save</button>
            <button class="btn btn--ghost" type="button" (click)="renaming.set(false)">Cancel</button>
          </form>
        } @else {
          <h1 class="page-title">
            {{ v.name }} <span class="muted">({{ v.x }}|{{ v.y }})</span>
            <button class="btn btn--ghost btn--small" (click)="startRename(v.name)" title="Rename">✎</button>
          </h1>
        }
        <div class="stats">
          <span title="Population"><ov-icon key="stat.population" /> {{ v.economy.population }}</span>
          @if (v.economy.defense_bonus > 0) {
            <span title="Defense bonus"><ov-icon key="stat.defense" /> +{{ (v.economy.defense_bonus * 100).toFixed(0) }}%</span>
          }
          @if (v.season; as se) {
            <span class="chip" [title]="'Season ends in ' + (se.ends_at - game.now() | duration)">{{ seasonIcon(se.id) }} {{ se.name }}, {{ 'year' | label: 'year' }} {{ se.year }}
              <span class="muted">· {{ se.ends_at - game.now() | duration }}</span></span>
            @if (se.festival; as f) {
              @if (game.now() >= f.opens_at && game.now() < f.closes_at) {
                <a class="chip chip--accent" routerLink="/festival" [title]="'Closes in ' + (f.closes_at - game.now() | duration)">🏛 {{ f.name }}</a>
              }
            }
          }
          @if (v.government; as g) {
            <a class="chip" routerLink="/realm" [class.chip--bad]="g.anarchy_until > game.now()">♜ {{ g.label }}@if (g.anarchy_until > game.now()) { · {{ 'anarchy' | label: 'anarchy' }} {{ g.anarchy_until - game.now() | duration }}}</a>
          }
        </div>
      </div>

      @if (v.starvation; as st) {
        @if (st.starving) {
          <p class="starving bad"><strong>☠ Your troops are starving.</strong> The city is {{ st.deficit.toFixed(0) }}/h short of {{ st.resource }};
            the cheapest troops die first until it feeds itself. Raise farms, or send troops away.</p>
        } @else if (st.empty_at && st.troops) {
          <p class="starving">⚠ {{ st.resource }} runs out in {{ st.empty_at - game.now() | duration }}; then troops start to starve.</p>
        }
      }

      <ov-tutorial-card (questChange)="focus.set($event)" (show)="showFocus()" />

      <div class="village">
        <div class="village__grids">
          @for (section of sections(); track section.id) {
            <section class="panel">
              <h2 class="panel__title">{{ section.label | label }}@if (section.phase) {<span class="muted small"> · {{ section.phase }}</span>}</h2>
              <div class="slots" [class.slots--fields]="section.id === 'fields'">
                @for (s of section.slots; track s.index) {
                  <button class="slot" [attr.id]="'slot-' + s.index" [class.slot--focus]="focusSlots().has(s.index)" [class.slot--empty]="!s.building" [class.slot--selected]="selected() === s.index"
                          [class.slot--busy]="s.queued" [class.slot--locked]="s.locked" [disabled]="s.locked" (click)="selected.set(s.index)"
                          [title]="s.locked ? ('error.site_locked' | label) : ''"
                          [attr.aria-label]="(s.building ? (s.building | name: 'building') + ' level ' + s.level : ('empty_slot' | label))">
                    <ov-icon [key]="s.building ? 'building.' + s.building : 'slot.empty'" />
                    <span class="slot__name">{{ s.building ? (s.building | name: 'building') : s.locked ? ('locked_site' | label: 'Locked') : ('empty_slot' | label) }}</span>
                    @if (s.style) {<span class="slot__style muted small">{{ s.style }}</span>}
                    @if (s.building) {<span class="slot__level">{{ s.level }}@if (s.queued) {<span class="slot__next">→{{ s.queued }}</span>}</span>}
                  </button>
                }
              </div>
            </section>
          }
        </div>

        <div class="village__side">
          @if (selected() !== null) {
            <ov-slot-panel [slot]="selected()!" (close)="selected.set(null)" />
          }

          <ov-omen-card [omen]="v.omen" />

          <section class="panel">
            <h2 class="panel__title">{{ 'section.queue' | label }} <span class="muted">{{ v.build_queue.length }}/{{ queueSize() }}</span></h2>
            @for (j of v.build_queue; track j.id) {
              <div class="row">
                <ov-icon [key]="'building.' + j.building" />
                <span class="grow">{{ j.building | name: 'building' }} → {{ j.level }}</span>
                <span class="timer">{{ j.due_at - game.now() | duration }}</span>
                <button class="btn btn--ghost btn--small" (click)="cancel(j.id)" title="Cancel">✕</button>
              </div>
            } @empty {<p class="muted">Nothing under construction.</p>}
          </section>

          <ov-contentment [view]="v.contentment" />

          @if (v.governor || v.governor_coming) {
            <section class="panel">
              <h2 class="panel__title">{{ 'section.governor' | label: 'Governor' }}</h2>
              @if (v.governor; as g) {
                <div class="row row--wrap small">
                  <span class="grow"><strong>{{ g.name }}</strong>
                    @if (g.prefect) {<span class="bad"> · prefect of your overlord</span>}</span>
                  <ov-traits [traits]="g.traits" [summary]="true" />
                </div>
              }
              @if (v.governor_coming; as c) {
                <div class="row row--wrap small">
                  <span class="grow">{{ c.name }} on the way@if (c.prefect) {<span class="bad">, a prefect of your overlord</span>}</span>
                  <ov-traits [traits]="c.traits" />
                  <span class="timer" title="Arrives in">{{ c.arrives_at - game.now() | duration }}</span>
                </div>
              }
              <p class="small"><a routerLink="/governors">All governors</a></p>
            </section>
          }

          <ov-finds />

          @if (v.research?.length) {
            <section class="panel">
              <h2 class="panel__title">{{ 'section.research' | label: 'Research' }}</h2>
              @for (r of v.research; track r.id) {
                <div class="row">
                  <ov-icon key="stat.research" />
                  <span class="grow">{{ techName(r.tech) }}</span>
                  <span class="timer">{{ r.due_at - game.now() | duration }}</span>
                  <button class="btn btn--ghost btn--small" (click)="cancel(r.id)" title="Cancel">✕</button>
                </div>
              }
            </section>
          }

          @if (v.training.length) {
            <section class="panel">
              <h2 class="panel__title">{{ 'section.training' | label }}</h2>
              @for (t of v.training; track t.id) {
                <div class="row">
                  <ov-icon [key]="'unit.' + t.unit" />
                  <span class="grow">{{ t.remaining }} × {{ t.unit | name: 'unit' }}</span>
                  <span class="timer" title="Next unit">{{ t.next_at - game.now() | duration }}</span>
                  <span class="muted timer" title="All done">{{ t.finishes_at - game.now() | duration }}</span>
                  <button class="btn btn--ghost btn--small" (click)="cancel(t.id)" title="Cancel">✕</button>
                </div>
              }
            </section>
          }

          @if (v.submission || v.fealty_offer || v.fealty_offers?.length || v.vassals?.length || v.dominance?.threats?.length || v.dominance?.conquests?.length) {
            <section class="panel">
              <h2 class="panel__title">{{ 'section.dominion' | label: 'Dominion' }}</h2>
              @if (v.submission; as s) {
                @if (s.village.player_id === v.player_id) {
                  <p class="small"><strong>Colony</strong> of {{ s.village.name }} ({{ s.village.x }}|{{ s.village.y }}), founded by a ver sacrum.
                    Pays {{ (s.tribute * 100).toFixed(0) }}% of its production to its mother city, for good.</p>
                } @else {
                  <p class="small"><strong>Vassal</strong> of {{ s.village.name }} ({{ s.village.x }}|{{ s.village.y }}, {{ s.player_name }}).
                    Pays {{ (s.tribute * 100).toFixed(0) }}% of its production; its culture serves the overlord.
                    Win one battle against {{ s.village.name }} to break free.</p>
                  @if (benefits(s).length) {<p class="small good">Under its protection: {{ benefits(s).join(' · ') }}.</p>}
                  @if (s.voluntary) {<p class="small">Sworn of its own will. <button class="btn btn--ghost btn--small" (click)="renounce()">Renounce the oath</button></p>}
                }
                <div class="row small"><span class="grow muted">Tribute</span><ov-cost [cost]="s.flow" /><span class="muted">/h</span></div>
              }
              @if (v.fealty_offer; as f) {
                <p class="small">⚑ Offered fealty to {{ f.village.name }} ({{ f.player_name }}, {{ (f.tribute * 100).toFixed(0) }}% tribute).
                  <button class="btn btn--ghost btn--small" (click)="withdrawFealty()">Withdraw</button></p>
              }
              @for (f of v.fealty_offers ?? []; track f.village.id) {
                <div class="row small">
                  <span class="grow">⚑ {{ f.village.name }} <span class="muted">({{ f.player_name }})</span> offers fealty, {{ (f.tribute * 100).toFixed(0) }}% tribute</span>
                  <button class="btn btn--small btn--primary" (click)="answerFealty(f.village.id, 'accept')">Accept</button>
                  <button class="btn btn--ghost btn--small" (click)="answerFealty(f.village.id, 'decline')">Decline</button>
                </div>
              }
              @if (v.taxes && v.vassals?.length; as _) {
                <div class="row row--wrap small"><span class="grow">Taxes for all vassals <span class="muted">(usual {{ (v.taxes!.usual * 100).toFixed(0) }}%; heavier ones anger far-off cities most)</span></span>
                  <button class="btn btn--ghost btn--small" [disabled]="taxStep(v.taxes!.default ?? v.taxes!.usual, -1) === null" (click)="setRealmTax(taxStep(v.taxes!.default ?? v.taxes!.usual, -1))">−</button>
                  <strong>{{ ((v.taxes!.default ?? v.taxes!.usual) * 100).toFixed(0) }}%</strong>
                  <button class="btn btn--ghost btn--small" [disabled]="taxStep(v.taxes!.default ?? v.taxes!.usual, 1) === null" (click)="setRealmTax(taxStep(v.taxes!.default ?? v.taxes!.usual, 1))">+</button>
                  @if (v.taxes!.default !== null) {<button class="btn btn--ghost btn--small" (click)="setRealmTax(null)">usual</button>}
                </div>
              }
              @for (x of v.vassals ?? []; track x.village.id) {
                <div class="row row--wrap small">
                  <span class="grow">⛓ {{ x.village.name }} <span class="muted">({{ x.village.x }}|{{ x.village.y }}, {{ x.player_name }})</span></span>
                  <ov-cost [cost]="x.flow" /><span class="muted">/h</span>
                  @if (x.tax; as t) {
                    <button class="btn btn--ghost btn--small" [disabled]="taxStep(t.rate, -1) === null" (click)="setTax(x.village.id, taxStep(t.rate, -1))" title="Lower taxes">−</button>
                    <span [title]="t.source === 'city' ? 'Set for this city' : 'The realm rate'">{{ (t.rate * 100).toFixed(0) }}%</span>
                    <button class="btn btn--ghost btn--small" [disabled]="taxStep(t.rate, 1) === null" (click)="setTax(x.village.id, taxStep(t.rate, 1))" title="Raise taxes">+</button>
                    @if (t.source === 'city') {<button class="btn btn--ghost btn--small" (click)="setTax(x.village.id, null)" title="Follow the realm rate">realm</button>}
                    @if (t.mood) {<span class="small" [class.bad]="t.mood < 0" [class.good]="t.mood > 0" title="Contentment from taxes">{{ t.mood > 0 ? '+' : '' }}{{ t.mood }}</span>}
                  }
                  @if (x.colony) {<span class="muted small">colony</span>} @else {
                    @if (x.embassy; as e) {
                      @if (embassyNext(e); as n) {
                        <button class="btn btn--small" (click)="buildEmbassy(x.village.id)" [disabled]="!n.affordable"
                                [title]="'Paid by ' + v.name + ': ' + n.costText">🏛 Embassy {{ n.level - 1 }} → {{ n.level }}</button>
                      } @else {<span class="muted small">🏛 Embassy {{ e.level }}</span>}
                    }
                    <button class="btn btn--ghost btn--small" (click)="release(x.village.id)" title="Release this vassal">Release</button>
                  }
                </div>
                @if (!x.colony && x.sites?.length) {
                  <div class="row row--wrap small">
                    <span class="muted">Your sites in {{ x.village.name }}:</span>
                    @for (s of x.sites!; track s.slot) {
                      @if (s.building) {
                        @if (embassyNext(s); as n) {
                          <button class="btn btn--small" (click)="buildSite(x.village.id, s.slot)" [disabled]="!n.affordable" [title]="'Paid by ' + v.name + ': ' + n.costText">{{ s.building | name: 'building' }} {{ n.level - 1 }} → {{ n.level }}</button>
                        } @else {<span>{{ s.building | name: 'building' }} {{ s.level }}</span>}
                      } @else {
                        @for (c of (s.slot === firstFree(x.sites!) ? siteChoices(x.sites!) : []); track c) {
                          <button class="btn btn--ghost btn--small" (click)="buildSite(x.village.id, s.slot, c)" [title]="(c | name: 'building') + ', paid by ' + v.name">＋ {{ c | name: 'building' }}</button>
                        }
                      }
                    }
                    @if (x.garrison; as g) {<span class="muted">garrison: {{ g.out }}/{{ g.capacity }} out, {{ count(g.here) }} stationed</span>}
                  </div>
                }
                @if (!x.colony && x.garrison?.auxiliaries) {<ov-auxiliaries [vassal]="x" />}
              }
              @for (t of v.dominance?.threats ?? []; track t.player_id) {
                <p class="small bad">{{ t.player_name }} has won {{ t.wins }} of {{ v.dominance!.needed }} battles in a row here. Defend once to reset.</p>
              }
              @for (c of v.dominance?.conquests ?? []; track c.village.id) {
                <p class="small">{{ c.wins }}/{{ v.dominance!.needed }} wins against {{ c.village.name }} <span class="muted">({{ c.player_name }})</span></p>
              }
            </section>
          }

          @if (v.ver_sacrum; as vs) {
            <section class="panel">
              <h2 class="panel__title">{{ 'ver_sacrum' | label: 'Ver sacrum' }} <span class="muted">{{ vs.available }}/{{ vs.earned }}</span></h2>
              @if (vs.available) {
                <p class="small">{{ vs.available }} colony ready to set out, up to {{ vs.range }} tiles away. Pick a free tile on the <a routerLink="/map">map</a>.</p>
                <p class="small"><ov-cost [cost]="vs.cost" /></p>
              } @else {
                <p class="small muted">The next ver sacrum comes with level {{ vs.next_at_level }} of the city centre (now {{ vs.level }}).</p>
              }
              @for (m of vs.migrations; track m.id) {
                <div class="row small"><span class="grow">Migrants to {{ m.name }} ({{ m.x }}|{{ m.y }})</span><span class="timer">{{ m.arrives_at - game.now() | duration }}</span></div>
              }
              @for (c of vs.colonies; track c.id) {
                <div class="row small"><span class="grow">Colony {{ c.name }} <span class="muted">({{ c.x }}|{{ c.y }})</span></span>
                  <button class="btn btn--ghost btn--small" (click)="openCity(c.id)">Open</button></div>
              }
            </section>
          }

          <section class="panel">
            <h2 class="panel__title">{{ 'section.troops' | label }}</h2>
            <ov-units [units]="v.state.units" />
            @if (v.reinforcements.here.length) {
              <p class="muted small">+ reinforcements from {{ v.reinforcements.here.length }} village(s)</p>
            }
          </section>
        </div>
      </div>
    } @else {
      <p class="muted">Loading village…</p>
    }
  `,
})
export class VillageComponent {
  protected benefits(s: Submission): string[] {
    return vassalBenefits(s.benefits);
  }
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  protected readonly selected = signal<number | null>(null);
  protected readonly renaming = signal(false);
  protected newName = '';
  protected readonly queueSize = computed(() => this.game.village()?.economy.build_queue ?? this.engine.pack()?.village.build_queue ?? 1);

  protected readonly sections = computed(() => {
    const v = this.game.village();
    if (!v) return [];
    const pack = this.engine.pack();
    const fields = pack?.village.field_slots.length ?? 0;
    const base = fields + (pack?.village.center_slots ?? Infinity);
    const open = v.economy.center_sites ?? pack?.village.center_slots ?? Infinity;
    const extra = v.economy.extra_fields ?? 0;
    const slots = v.state.slots.map((s, index) => {
      const queued = v.build_queue.filter((q) => q.slot === index).reduce((m, q) => Math.max(m, q.level), 0);
      const building = s.building ?? v.build_queue.find((q) => q.slot === index)?.building ?? null;
      const tribe = v.owner?.tribe ?? this.game.me()?.tribe;
      const style = s.style && s.style !== tribe ? (pack?.tribes.find((t) => t.id === s.style)?.name ?? s.style) : '';
      return { index, building, level: s.level, queued, style, locked: index >= fields && !s.foreign && !building && index - fields >= open };
    });
    const foreign = slots.filter((s) => v.state.slots[s.index].foreign);
    const phase = pack?.village.growth?.phases.find((p) => p.id === v.economy.phase);
    return [
      { id: 'fields', label: 'section.fields', slots: [...slots.slice(0, fields), ...slots.slice(base, base + extra)], phase: this.moreFields(v.state.slots, extra) },
      { id: 'center', label: 'section.center', slots: slots.slice(fields, base), phase: phase ? `${phase.name}, ${open} of ${pack!.village.center_slots} sites open, ${v.economy.build_queue ?? pack!.village.build_queue} builders` : '' },
      ...(foreign.length ? [{ id: 'foreign', label: 'section.foreign', slots: foreign, phase: v.exchange_relief ? `tribute ${Math.round(v.exchange_relief * 100)}% lighter` : '' }] : []),
    ];
  });

  /** When the next extra fields open, e.g. "4 more fields at Civic Centre level 20". */
  private moreFields(slots: { building: string | null; level: number }[], open: number): string {
    const growth = this.engine.pack()?.village.growth;
    const x = growth?.extra_fields;
    if (!growth || !x?.every || !x.fields.length) return '';
    const level = Math.max(0, ...slots.filter((s) => s.building === growth.building).map((s) => s.level));
    const next = (Math.floor(level / x.every) + 1) * x.every;
    const max = this.engine.building(growth.building)?.max_level ?? 0;
    const name = this.engine.building(growth.building)?.name ?? growth.building;
    const now = open ? `${open} extra fields open; ` : '';
    return next > max ? `${now}all extra fields open` : `${now}${x.fields.length} more at ${name} level ${next}`;
  }

  /** The tutorial quest's target: slots to highlight, the first one is the one "Show me" opens. */
  protected readonly focus = signal<Quest | null>(null);
  private readonly focusList = computed(() => {
    const f = this.focus()?.focus;
    if (!f?.building) return [];
    const all = this.sections().flatMap((s) => s.slots);
    const fields = all.filter((s) => s.building === f.building).sort((a, b) => a.level - b.level);
    if (fields.length || !f.site) return fields.map((s) => s.index);
    const site = this.sections().find((s) => s.id === 'center')?.slots.find((s) => !s.building && !s.locked);
    return site ? [site.index] : [];
  });
  protected readonly focusSlots = computed(() => new Set(this.focusList()));

  protected showFocus(): void {
    const i = this.focusList()[0];
    if (i === undefined) return;
    this.selected.set(i);
    document.getElementById('slot-' + i)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  protected seasonIcon(id: string): string {
    return ({ spring: '🌱', summer: '☀', autumn: '🍂', winter: '❄' } as Record<string, string>)[id] ?? '◷';
  }

  protected techName(id: string): string {
    return this.engine.tech(id)?.name ?? id;
  }

  protected startRename(name: string): void {
    this.newName = name;
    this.renaming.set(true);
  }

  protected async saveName(): Promise<void> {
    const v = this.game.village();
    if (v && (await this.game.act(() => this.api.rename(v.id, this.newName)))) {
      this.renaming.set(false);
      void this.game.refreshMe();
    }
  }

  protected openCity(id: number): void {
    void this.game.selectVillage(id);
  }

  /** The next embassy level this city could pay for in a vassal, or null when it is complete. */
  protected embassyNext(e: EmbassyInfo): { level: number; affordable: boolean; costText: string } | null {
    const b = this.engine.building(e.building ?? 'embassy');
    const level = Math.max(e.level, ...e.queued.map((q) => q.level)) + 1;
    if (!b || !e.building || level > b.max_level) return null;
    const cost = this.engine.buildCost(b.id, level);
    const have = this.game.resources();
    return {
      level,
      affordable: Object.entries(cost).every(([r, n]) => (have[r] ?? 0) >= n),
      costText: Object.entries(cost).map(([r, n]) => `${Math.round(n)} ${r}`).join(', '),
    };
  }

  protected siteChoices(sites: EmbassyInfo[]): string[] {
    return (embassyRules(this.engine.pack())?.overlord ?? []).filter((b) => !sites.some((s) => s.building === b));
  }

  protected firstFree(sites: EmbassyInfo[]): number | undefined {
    return sites.find((s) => !s.building)?.slot;
  }

  protected count(u: Record<string, number>): number {
    return Object.values(u ?? {}).reduce((a, b) => a + b, 0);
  }

  protected buildSite(vassalId: number, slot: number, building?: string): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.buildOverlordSite(vassalId, slot, v.id, building), 'Construction ordered');
  }

  protected buildEmbassy(vassalId: number): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.buildEmbassy(vassalId, v.id), 'Embassy ordered');
  }


  /** A tax rate one step (1 point) up or down, within the overlord's range; null when it would leave it. */
  protected taxStep(rate: number, dir: 1 | -1): number | null {
    const t = this.game.village()?.taxes;
    const next = Math.round((rate + dir * 0.01) * 100) / 100;
    return t && next >= t.min - 1e-9 && next <= t.max + 1e-9 ? next : null;
  }

  protected setTax(vassalId: number, rate: number | null): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.taxVassal(v.id, vassalId, rate), rate === null ? 'Follows the realm rate' : `Tax set to ${Math.round(rate * 100)}%`);
  }

  protected async setRealmTax(rate: number | null): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    try {
      const r = await this.api.taxRealm(rate);
      this.game.toast(`Taxes for ${r.vassals} vassal(s): ${rate === null ? 'the usual tribute' : Math.round(rate * 100) + '%'}`, 'good');
      await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected renounce(): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.renounce(v.id), 'The oath is renounced');
  }

  protected withdrawFealty(): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.withdrawFealty(v.id), 'Offer withdrawn');
  }

  protected answerFealty(vassalId: number, answer: 'accept' | 'decline'): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.answerFealty(v.id, vassalId, answer), answer === 'accept' ? 'A new vassal' : 'Offer declined');
  }

  protected release(vassalId: number): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.release(v.id, vassalId), 'Vassal released');
  }

  protected cancel(jobId: number): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.cancel(v.id, jobId));
  }
}
