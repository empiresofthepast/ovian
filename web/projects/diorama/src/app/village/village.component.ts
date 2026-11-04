import { Auxiliaries, EmbassyInfo, ResourceMap, vassalBenefits } from '@core/models';
import { embassyRules, foreignRole } from '@core/embassy';
import { Component, ElementRef, HostListener, OnDestroy, afterNextRender, computed, effect, inject, signal, viewChild } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';
import { PrefsService } from '../prefs.service';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { ArtService } from '../art/art.service';
import type { SiteView, VillageScene, VillageSceneView } from '../scene/village-scene';
import { UI } from '../ui';
import { OmenComponent } from './omen.component';
import { SelectionComponent } from './selection.component';
import { TutorialComponent } from './tutorial.component';

interface LevyDraft { unit: string; count: number; from: number }

@Component({
  selector: 'dio-village',
  imports: [SelectionComponent, OmenComponent, TutorialComponent, RouterOutlet, RouterLink, RouterLinkActive, ...UI],
  template: `
    <div class="stage" #stage></div>
    @if (!art.manifest()) {
      <div class="stage-note">The 0 A.D. art is not installed. Run <code>tools/zeroad/bake.sh</code> and rebuild.</div>
    }

    <header class="topbar hud-panel">
      <div class="topbar__who">
        @if (emblem()) {<img class="emblem" [src]="emblem()" alt="" />}
        <div>
          @if ((game.me()?.villages?.length ?? 0) > 1 && !game.inspecting()) {
            <select class="topbar__village topbar__switch" [value]="village()?.id" (change)="switchCity($any($event.target).value)" aria-label="Your cities" title="Switch city">
              @for (c of game.me()!.villages; track c.id) {<option [value]="c.id" [selected]="c.id === village()?.id">{{ c.name }} ({{ c.x }}|{{ c.y }})</option>}
            </select>
          } @else {
            <div class="topbar__village">{{ village()?.name }}</div>
          }
          <div class="topbar__civ">{{ civName() }} · {{ phaseName() }}@if (village()?.submission; as s) { · <span [class.bad]="s.village.player_id !== village()!.player_id" title="Pays tribute; its culture follows the overlord">{{ s.village.player_id === village()!.player_id ? 'colony' : 'vassal' }} of @if (s.village.player_id === village()!.player_id && !game.inspecting()) {<button type="button" class="linkbtn" (click)="goTo(s.village.id)" [title]="'Go to ' + s.village.name">{{ s.village.name }}</button>} @else {{{ s.village.name }}}</span>}
            @if (village()?.season; as se) {&nbsp;· <a class="season-chip" routerLink="/year" [title]="se.name + ', year ' + se.year + (se.festival ? '. ' + se.festival.name + ' open!' : '')">{{ seasonIcon(se.id) }} {{ se.name }}@if (se.festival) { 🏛}</a>}
            @if (mood(); as m) {&nbsp;· <a class="mood-chip" routerLink="/realm" [class.bad]="m.score < 0" [class.good]="m.score >= 10" [title]="'Contentment ' + m.score + (m.unrest ? ', unrest ' + m.unrest : '')">{{ m.face }} {{ m.score }}</a>}</div>
        </div>
      </div>
      <div class="resources" role="list" aria-label="Resources">
        @for (r of resources(); track r.id) {
          <div class="res" role="listitem" [class.res--full]="r.full" [title]="r.name + ': ' + (r.rate >= 0 ? '+' : '') + r.rate + ' per hour, capacity ' + r.cap">
            @if (r.icon) {<img [src]="r.icon" alt="" />}
            <span class="res__amount">{{ r.amount | n }}</span>
            <span class="res__rate" [class.bad]="r.rate < 0">{{ r.rate >= 0 ? '+' : '' }}{{ r.rate | n }}</span>
          </div>
        }
        <div class="res" role="listitem" title="Population and upkeep per hour">
          @if (popIcon()) {<img [src]="popIcon()" alt="" />}
          <span class="res__amount">{{ village()?.economy?.population | n }}</span>
        </div>
      </div>
      <nav class="topbar__nav" aria-label="Main">
        @for (n of mainNav(); track n.path) {
          <a class="navbtn" [routerLink]="n.path" routerLinkActive="navbtn--on" [routerLinkActiveOptions]="{ exact: true }" [title]="n.label + ' (' + n.key + ')'">
            <span class="navbtn__icon" aria-hidden="true">{{ n.icon }}</span><span class="navbtn__label">{{ n.label }}</span>
            @if (n.path === '/reports' && game.me()?.unread_reports) {<span class="pill">{{ game.me()!.unread_reports }}</span>}
            @if (n.path === '/rally' && threats()) {<span class="pill">{{ threats() }}</span>}
          </a>
        }
        <div class="navmore">
          <button type="button" class="navbtn" [class.navbtn--on]="moreActive()" (click)="more.set(!more())" [attr.aria-expanded]="more()" aria-haspopup="menu" title="More screens">
            <span class="navbtn__icon" aria-hidden="true">☰</span><span class="navbtn__label">{{ moreActive()?.label ?? 'More' }}</span>
          </button>
          @if (more()) {
            <div class="navmore__backdrop" (click)="more.set(false)"></div>
            <div class="navmore__menu hud-panel" role="menu">
              @for (n of moreNav(); track n.path) {
                <a class="navmore__item" role="menuitem" [routerLink]="n.path" routerLinkActive="navmore__item--on" (click)="more.set(false)">
                  <span class="navbtn__icon" aria-hidden="true">{{ n.icon }}</span><span class="grow">{{ n.label }}</span><kbd>{{ n.key }}</kbd>
                </a>
              }
            </div>
          }
        </div>
      </nav>
    </header>

    @if (game.inspecting()) {
      <div class="inspect hud-panel" role="status">
        <span>👁 {{ village()?.owner?.name }}'s city, read-only</span>
        <button class="btn btn--small" (click)="game.inspecting() && refreshInspect()" title="Reload">↻</button>
        <button class="btn btn--gold btn--small" (click)="backHome()">Back to my city</button>
      </div>
    }
    @if (game.winner(); as w) {
      <div class="winner hud-panel" role="status">🏛 {{ w.player.name }} finished the wonder in {{ w.village.name }} and has won this world.</div>
    }
    <aside class="side side--left" [hidden]="!!overlay()">
      @if (!game.inspecting()) {
        <dio-omen />
        <dio-tutorial (focus)="focusSite($event)" />
      }
      @if (queue().length || training().length || researching().length) {
        <section class="hud-panel queue">
          <h3 class="subhead">Under way <span class="muted small">· builders {{ queue().length }}/{{ village()?.economy?.build_queue ?? 2 }}</span></h3>
          @for (q of queue(); track q.id) {
            <div class="job">
              <dio-portrait [src]="q.icon" [alt]="q.name" [small]="true" />
              <div class="job__body">
                <div class="job__name">{{ q.name }} <span class="muted">→ {{ q.level }}</span></div>
                <div class="bar"><div class="bar__fill" [style.width.%]="q.progress"></div></div>
              </div>
              <span class="job__time">{{ q.left | dur: 'ms' }}</span>
              <button class="close close--inline" (click)="cancel(q.id)" title="Cancel and refund">✕</button>
            </div>
          }
          @for (r of researching(); track r.id) {
            <div class="job">
              <dio-portrait [src]="r.icon" [alt]="r.name" [small]="true" />
              <div class="job__body">
                <div class="job__name">{{ r.name }} <span class="muted">research</span></div>
                <div class="bar"><div class="bar__fill bar__fill--research" [style.width.%]="r.progress"></div></div>
              </div>
              <span class="job__time">{{ r.left | dur: 'ms' }}</span>
              <button class="close close--inline" (click)="cancel(r.id)" title="Cancel and refund">✕</button>
            </div>
          }
          @for (t of training(); track t.id) {
            <div class="job">
              <dio-portrait [src]="t.icon" [alt]="t.name" [small]="true" />
              <div class="job__body">
                <div class="job__name">{{ t.remaining }} × {{ t.name }}</div>
                <div class="bar"><div class="bar__fill bar__fill--units" [style.width.%]="t.progress"></div></div>
              </div>
              <span class="job__time">{{ t.left | dur: 'ms' }}</span>
            </div>
          }
        </section>
      }
    </aside>

    @if (!overlay() && selected() === null) {
      <button class="sheet-toggle hud-panel" (click)="sheet.set(!sheet())" [attr.aria-expanded]="sheet()" aria-label="Garrison and dominion">
        {{ sheet() ? '✕' : '⚔' }}@if (!sheet() && threats()) {<span class="pill">{{ threats() }}</span>}
      </button>
    }
    <aside class="side side--right" [class.side--open]="sheet()" [hidden]="!!overlay()">
      <section class="hud-panel troops">
        <h3 class="subhead">Garrison</h3>
        @for (u of troops(); track u.id) {
          <div class="troop" [title]="u.name"><dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" /><span>{{ u.count }}</span></div>
        } @empty {<p class="muted small">No troops at home.</p>}
        @if (village()?.starvation; as st) {
          @if (st.starving) {
            <div class="alert alert--bad" title="The cheapest troops die first, until the city feeds itself">☠ Troops are starving: {{ st.deficit | n }}/h short</div>
          } @else if (st.empty_at && st.troops) {
            <div class="alert" title="Then troops start to starve">⚠ Food runs out in <span class="job__time">{{ st.empty_at - game.now() | dur: 'ms' }}</span></div>
          }
        }
        @for (m of incoming(); track m.id) {
          <div class="alert" [class.alert--bad]="m.hostile">
            {{ m.hostile ? '⚔' : '⛨' }} {{ m.label }} <span class="job__time">{{ m.left | dur: 'ms' }}</span>
          </div>
        }
      </section>
      @if (village()?.contentment; as c) {
        @if (c.score !== undefined) {
          <section class="hud-panel people">
            <h3 class="subhead">People <a class="small" routerLink="/realm">details</a></h3>
            <div class="small">{{ mood()?.face }} Contentment&nbsp;<strong [class.bad]="c.score! < 0" [class.good]="c.score! >= 10">{{ c.score }}</strong>,
              {{ (c.production ?? 0) >= 0 ? '+' : '' }}{{ ((c.production ?? 0) * 100).toFixed(1) }}% production</div>
            @if (c.can_rebel && (c.unrest ?? 0) > 0) {
              <div class="bar" title="Unrest"><div class="bar__fill bar__fill--bad" [style.width.%]="(c.unrest! / c.rebel_at!) * 100"></div></div>
              <div class="small bad">Unrest {{ c.unrest | n }} / {{ c.rebel_at }}: at the top it rises up.</div>
            }
          </section>
        }
      }
      @if (village()?.governor || village()?.governor_coming) {
        <section class="hud-panel governor">
          <h3 class="subhead">Governor <a class="small" routerLink="/governors">all</a></h3>
          @if (village()?.governor; as g) {
            <div class="small">{{ g.name }}@if (g.prefect) {&nbsp;<span class="tag tag--bad" title="Sent by the overlord: the people resent a foreign ruler">prefect</span>}</div>
            <div class="chips chips--tight">@for (t of g.traits; track t.id) {<span class="chip chip--static" [title]="t.text ?? ''">{{ t.name ?? t.id }}</span>}</div>
          }
          @if (village()?.governor_coming; as g) {
            <div class="small">{{ g.name }}@if (g.prefect) { (prefect)} arrives in <span class="job__time">{{ g.arrives_at - game.now() | dur: 'ms' }}</span></div>
          }
        </section>
      }
      @if (dominion(); as d) {
        <section class="hud-panel dominion">
          <h3 class="subhead">Dominion</h3>
          @if (d.overlord; as o) {
            <div class="dom dom--vassal">
              @if (o.emblem) {<img class="dom__emblem" [src]="o.emblem" alt="" />}
              <div>
                <div>{{ o.own ? 'Colony' : 'Vassal' }} of @if (o.own) {<button type="button" class="linkbtn" (click)="goTo(o.id)" [title]="'Go to ' + o.name"><strong>{{ o.name }}</strong></button>} @else {<strong>{{ o.name }}</strong>}&nbsp;<span class="muted">({{ o.player }})</span></div>
                <div class="small muted">Pays {{ o.pct }}% of production@if (o.taxed) { (taxed by its overlord)}, per hour:</div>
                <dio-cost [cost]="o.flow" />
                @if (o.own) {
                  <div class="small muted">Founded by a ver sacrum. You manage it, and it stays bound to {{ o.name }} for good.</div>
                } @else {
                  @if (o.voluntary) {
                    <div class="small muted">Sworn of its own will. New buildings follow the {{ o.civ }}.</div>
                  } @else {
                    <div class="small muted">New buildings follow the {{ o.civ }}. Beat {{ o.name }} once to break free.</div>
                  }
                  @if (o.benefits.length) {<div class="small good">Under its protection: {{ o.benefits.join(' · ') }}.</div>}
                  @if (o.voluntary && !game.inspecting()) {<button class="btn btn--ghost btn--small" (click)="renounce()">Renounce the oath</button>}
                }
              </div>
            </div>
          }
          @if (d.offer; as f) {
            <div class="small">⚑ Offered fealty to <strong>{{ f.village.name }}</strong> <span class="muted">({{ f.player_name }}, {{ (f.tribute * 100).toFixed(0) }}% tribute)</span>
              @if (!game.inspecting()) {<button class="btn btn--ghost btn--small" (click)="withdrawFealty()">Withdraw</button>}</div>
          }
          @for (f of d.offers; track f.village.id) {
            <div class="dom">
              <div class="grow small">⚑ <strong>{{ f.village.name }}</strong> <span class="muted">({{ f.player_name }})</span> offers fealty: {{ (f.tribute * 100).toFixed(0) }}% of its production for your protection.</div>
              @if (!game.inspecting()) {
                <button class="btn btn--gold btn--small" (click)="answerFealty(f.village.id, 'accept')">Accept</button>
                <button class="btn btn--ghost btn--small" (click)="answerFealty(f.village.id, 'decline')">Decline</button>
              }
            </div>
          }
          @if (d.taxes && hasTaxable(d.vassals) && !game.inspecting()) {
            <div class="tax-line" title="Above the usual tribute, taxes anger a city, and the farther it lies from you, the more">
              <span class="grow small">Taxes, all vassals <span class="muted">(usual {{ pct(d.taxes.usual) }})</span></span>
              <span class="stepper">
                <button type="button" [disabled]="taxStep(d.taxes.default ?? d.taxes.usual, -1) === null" (click)="setRealmTax(taxStep(d.taxes.default ?? d.taxes.usual, -1))" aria-label="Lower taxes">−</button>
                <strong>{{ pct(d.taxes.default ?? d.taxes.usual) }}</strong>
                <button type="button" [disabled]="taxStep(d.taxes.default ?? d.taxes.usual, 1) === null" (click)="setRealmTax(taxStep(d.taxes.default ?? d.taxes.usual, 1))" aria-label="Raise taxes">+</button>
              </span>
              @if (d.taxes.default !== null) {<button type="button" class="linkbtn small" (click)="setRealmTax(null)" title="Back to the usual tribute">reset</button>}
            </div>
          }
          @for (x of d.vassals; track x.id) {
            <div class="vassal">
              <div class="dom">
                @if (x.emblem) {<img class="dom__emblem" [src]="x.emblem" alt="" />}
                <div class="grow">⛓ @if (x.colony) {<button type="button" class="linkbtn" (click)="goTo(x.id)">{{ x.name }}</button>} @else {{{ x.name }}}&nbsp;<span class="muted">({{ x.player }})</span></div>
                @if (x.colony) {<button type="button" class="tag tag--link" (click)="goTo(x.id)" [title]="'Go to ' + x.name + ' (founded by a ver sacrum, bound to this city for good)'">colony ›</button>}
              </div>
              <dio-cost [cost]="x.flow" title="Tribute received per hour" />
              @if (!x.colony) {
                <div class="tax-line">
                  @if (x.tax; as t) {
                    <span class="small muted">Tax</span>
                    @if (game.inspecting()) {<strong class="small">{{ pct(t.rate) }}</strong>} @else {
                      <span class="stepper">
                        <button type="button" [disabled]="taxStep(t.rate, -1) === null" (click)="setTax(x.id, taxStep(t.rate, -1))" aria-label="Lower taxes">−</button>
                        <strong>{{ pct(t.rate) }}</strong>
                        <button type="button" [disabled]="taxStep(t.rate, 1) === null" (click)="setTax(x.id, taxStep(t.rate, 1))" aria-label="Raise taxes">+</button>
                      </span>
                      @if (t.source === 'city') {<button type="button" class="linkbtn small" (click)="setTax(x.id, null)" title="Follow the rate for all vassals">reset</button>}
                    }
                    @if (t.mood) {<span class="small" [class.bad]="t.mood < 0" [class.good]="t.mood > 0" title="Contentment from taxes in that city">{{ t.mood > 0 ? '+' : '' }}{{ t.mood }}☺</span>}
                  }
                  <span class="grow"></span>
                  @if (x.embassy; as e) {
                    @if (x.next; as n) {
                      <button class="btn btn--small" (click)="buildEmbassy(x.id)" [disabled]="!n.affordable || game.inspecting()"
                              [title]="'Raise your embassy in ' + x.name + ', paid by ' + village()!.name + ': ' + n.costText">🏛 {{ n.level - 1 }}→{{ n.level }}</button>
                    } @else {<span class="tag" title="Your embassy">🏛 {{ e.level }}</span>}
                  }
                  <button class="btn btn--ghost btn--small" (click)="release(x.id)" title="Free this city from tribute">Release</button>
                </div>
                @if (x.sites.length) {
                  <div class="tax-line small">
                    @for (s of x.sites; track s.slot) {
                      @if (s.building) {
                        @if (s.next; as n) {
                          <button class="btn btn--small" (click)="buildSite(x.id, s.slot)" [disabled]="!n.affordable || game.inspecting()"
                                  [title]="'Raise your ' + s.name + ' in ' + x.name + ', paid by ' + village()!.name + ': ' + n.costText">{{ s.name }} {{ n.level - 1 }}→{{ n.level }}</button>
                        } @else {<span class="tag">{{ s.name }} {{ s.level }}</span>}
                      } @else if (!game.inspecting()) {
                        @for (c of s.choices; track c.id) {
                          <button class="btn btn--ghost btn--small" (click)="buildSite(x.id, s.slot, c.id)" [disabled]="!c.affordable" [title]="c.text + ' Cost: ' + c.costText">＋ {{ c.name }}</button>
                        }
                      }
                    }
                    @if (x.garrison; as g) {<span class="muted" title="Your troops there may set out from it (rally point: set out from the garrison)">⚔ {{ g.out }}/{{ g.capacity }} out · {{ count(g.here) }} stationed</span>}
                  </div>
                }
                @if (x.garrison?.auxiliaries; as a) {
                  <div class="aux small">
                    <div class="tax-line">
                      <span class="grow">Auxiliaries <span class="muted" title="Levied or in training, out of the garrison's room">{{ a.levied + a.queued }}/{{ x.garrison!.capacity }}</span></span>
                    </div>
                    @for (t of a.training; track t.id) {
                      <div class="tax-line">
                        <span class="grow">{{ t.remaining }} × {{ unitName(t.unit, a) }}</span>
                        <span class="job__time">{{ t.finishes_at - game.now() | dur: 'ms' }}</span>
                        @if (!game.inspecting()) {<button class="close close--inline" (click)="cancelLevy(x.id, t.id)" title="Stop the levy; the rest is paid back">✕</button>}
                      </div>
                    }
                    @if (!game.inspecting() && a.options.length) {
                      @if (levyDraft(x.id, a); as f) {
                        <div class="tax-line">
                          <select [value]="f.unit" (change)="setLevy(x.id, { unit: $any($event.target).value })" aria-label="Troops to levy">
                            @for (o of a.options; track o.unit) {<option [value]="o.unit" [selected]="o.unit === f.unit">{{ o.name }} ({{ costText(o.cost_each) }})</option>}
                          </select>
                          <input class="aux__count" type="number" min="1" [max]="room(x.garrison!.capacity, a)" [value]="f.count" (input)="setLevy(x.id, { count: +$any($event.target).value })" aria-label="How many" />
                        </div>
                        <div class="tax-line">
                          <span class="muted">Paid by</span>
                          <select [value]="f.from" (change)="setLevy(x.id, { from: +$any($event.target).value })" aria-label="City that pays">
                            @for (c of game.me()?.villages ?? []; track c.id) {<option [value]="c.id" [selected]="c.id === f.from">{{ c.name }}</option>}
                          </select>
                          <span class="grow"></span>
                          <button class="btn btn--small" [disabled]="f.count < 1 || f.count > room(x.garrison!.capacity, a)" (click)="levy(x.id, f)">Levy</button>
                        </div>
                        @if (levyCost(f, a); as c) {<dio-cost [cost]="c" [have]="f.from === village()?.id ? game.resources() : {}" />}
                      }
                      <div class="muted">They anger the city; if it breaks free they join it.</div>
                    }
                  </div>
                }
              }
            </div>
          }
          @for (t of d.threats; track t.player) {
            <div class="alert alert--bad small" title="Win one defence to reset">{{ t.player }}: {{ t.wins }}/{{ d.needed }} wins in a row against you</div>
          }
          @for (c of d.conquests; track c.id) {
            <div class="dom small">
              <span class="grow">{{ c.name }}&nbsp;<span class="muted">({{ c.player }})</span></span>
              <span class="pips" [title]="c.wins + ' of ' + d.needed + ' wins in a row'">@for (p of c.pips; track $index) {<i [class.on]="p"></i>}</span>
            </div>
          }
        </section>
      }
    </aside>

    @if (!overlay()) {
      @if (selected() !== null) {
        <dio-selection [site]="selected()!" (close)="select(null)" />
      } @else {
        <div class="hint hud-panel">{{ touch ? 'Tap a building or an empty site. Drag to pan, two fingers to turn and zoom.' : 'Click a building or an empty site. Drag to pan, right-drag or Q/E to turn, wheel to zoom.' }}</div>
      }
    }

    <router-outlet />
  `,
  host: { class: 'village' },
})
export class VillageComponent implements OnDestroy {
  protected readonly game = inject(GameStore);
  protected readonly art = inject(ArtService);
  private readonly engine = inject(EngineService);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly stage = viewChild.required<ElementRef<HTMLElement>>('stage');
  private scene: VillageScene | null = null;

  protected readonly selected = signal<number | null>(null);
  /** On phones the garrison panel is a sheet opened from a button. */
  protected readonly sheet = signal(false);
  protected readonly touch = typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches;
  private readonly prefs = inject(PrefsService);
  /** The first five stay in the bar; the rest sit behind "More". */
  protected readonly nav = [
    { path: '/', label: 'City', icon: '⌂', key: 'C' },
    { path: '/map', label: 'Map', icon: '⌖', key: 'M' },
    { path: '/rally', label: 'Rally point', icon: '⚑', key: 'R' },
    { path: '/market', label: 'Market', icon: '⚖', key: 'T' },
    { path: '/reports', label: 'Reports', icon: '✉', key: 'P' },
    { path: '/hero', label: 'Hero', icon: '♞', key: 'H' },
    { path: '/alliance', label: 'Alliance', icon: '⚭', key: 'L' },
    { path: '/quests', label: 'Quests', icon: '✓', key: 'Q' },
    { path: '/realm', label: 'Realm', icon: '⚜', key: 'G' },
    { path: '/governors', label: 'Governors', icon: '♜', key: 'V' },
    { path: '/finds', label: 'Finds', icon: '⚱', key: 'F' },
    { path: '/year', label: 'Year & games', icon: '☀', key: 'Y' },
    { path: '/chronicle', label: 'Chronicle', icon: '📜', key: 'N' },
    { path: '/rankings', label: 'Rankings', icon: '♛', key: 'K' },
    { path: '/settings', label: 'Settings', icon: '⚙', key: 'O' },
  ];
  /** Superusers also get the Admin screen. */
  protected readonly navItems = computed(() =>
    this.game.me()?.is_admin ? [...this.nav, { path: '/admin', label: 'Admin', icon: '⚿', key: 'A' }] : this.nav,
  );
  protected readonly mainNav = computed(() => this.navItems().slice(0, 5));
  protected readonly moreNav = computed(() => this.navItems().slice(5));
  protected readonly more = signal(false);
  /** The open screen when it is one of those behind "More": the button then shows its name. */
  protected readonly moreActive = computed(() => this.moreNav().find((n) => n.path === '/' + this.overlay()) ?? null);
  /** The open child screen ('' for none). */
  protected readonly overlay = toSignal(
    this.router.events.pipe(
      filter((e) => e instanceof NavigationEnd),
      map(() => this.router.url.split(/[?#]/)[0].replace(/^\//, '')),
    ),
    { initialValue: this.router.url.split(/[?#]/)[0].replace(/^\//, '') },
  );
  protected readonly threats = computed(() => (this.village()?.movements.incoming ?? []).filter((m) => m.kind === 'attack' || m.kind === 'raid').length);
  protected readonly village = this.game.village;
  private readonly tribe = computed(() => this.village()?.owner?.tribe ?? this.game.me()?.tribe ?? null);
  /** Each building keeps the style it was founded in (its slot's `style`); older ones show the owner's. */
  private readonly artTribe = computed(() => this.tribe());

  protected readonly dominion = computed(() => {
    const v = this.village();
    if (!v) return null;
    const civ = (tribe: string) => this.engine.pack()?.tribes.find((t) => t.id === tribe)?.name ?? this.art.civ(tribe)?.name ?? tribe;
    const emblem = (tribe: string) => this.art.url(this.art.civ(tribe)?.emblem);
    const s = v.submission;
    const d = v.dominance;
    const needed = d?.needed ?? 5;
    const out = {
      needed,
      overlord: s ? { id: s.village.id, benefits: vassalBenefits(s.benefits), own: !!s.colony || s.village.player_id === v.player_id, name: s.village.name, player: s.player_name, pct: Math.round(s.tribute * 100), flow: s.flow, civ: civ(s.tribe), emblem: emblem(s.tribe), voluntary: !!s.voluntary, taxed: s.tax?.source === 'city' || s.tax?.source === 'realm' } : null,
      offer: v.fealty_offer ?? null,
      offers: v.fealty_offers ?? [],
      vassals: (v.vassals ?? []).map((x) => ({ colony: !!x.colony, id: x.village.id, name: x.village.name, player: x.player_name, flow: x.flow, emblem: emblem(x.tribe),
        embassy: x.embassy ?? null, next: x.embassy ? this.embassyNext(x.embassy) : null, tax: x.tax ?? null,
        sites: (x.sites ?? []).map((s) => ({ ...s, name: s.building ? (this.engine.building(s.building)?.name ?? s.building) : '', next: s.building ? this.embassyNext(s) : null,
          // offer what can still be raised once, on the first free site
          choices: s.slot === (x.sites ?? []).find((y) => !y.building)?.slot ? this.siteChoices(x.sites ?? []) : [] })),
        garrison: x.garrison ?? null })),
      taxes: v.taxes ?? null,
      threats: (d?.threats ?? []).map((t) => ({ player: t.player_name, wins: t.wins })),
      conquests: (d?.conquests ?? []).map((c) => ({ id: c.village.id, name: c.village.name, player: c.player_name, wins: c.wins,
        pips: Array.from({ length: needed }, (_, i) => i < c.wins) })),
    };
    return out.overlord || out.offer || out.offers.length || out.vassals.length || out.threats.length || out.conquests.length ? out : null;
  });

  protected readonly mood = computed(() => {
    const c = this.village()?.contentment;
    if (c?.score === undefined) return null;
    const s = c.score;
    return { score: s, unrest: c.can_rebel ? Math.round(c.unrest ?? 0) : 0, face: s >= 20 ? '😄' : s >= 5 ? '🙂' : s >= -5 ? '😐' : s >= -20 ? '😠' : '🔥' };
  });

  protected seasonIcon(id: string): string {
    return ({ spring: '🌱', summer: '☀', autumn: '🍂', winter: '❄' } as Record<string, string>)[id] ?? '◷';
  }

  /** The tutorial asks to point at a building, or at a free site to build on. */
  protected focusSite(f: { building?: string; site?: boolean }): void {
    const v = this.village();
    const pack = this.engine.pack();
    if (!v || !pack) return;
    const fields = pack.village.field_slots.length;
    const open = v.economy.center_sites ?? pack.village.center_slots;
    let index = -1;
    if (f.building) {
      let best = -1;
      v.state.slots.forEach((s, i) => {
        const shut = i >= fields + pack.village.center_slots && i - fields - pack.village.center_slots >= (v.economy.extra_fields ?? 0);
        if (s.building === f.building && !shut && (best < 0 || s.level < v.state.slots[best].level)) best = i;
      });
      index = best;
    }
    if (index < 0 && (f.site || f.building)) index = v.state.slots.findIndex((s, i) => i >= fields && i - fields < Math.min(open, pack.village.center_slots) && !s.building);
    if (index >= 0) this.select(index);
    else this.game.toast('No free building site: raise the city centre to open more.', 'info');
  }

  protected readonly emblem = computed(() => this.art.url(this.art.civ(this.tribe())?.emblem));
  protected readonly civName = computed(() => this.engine.pack()?.tribes.find((t) => t.id === this.tribe())?.name ?? this.art.civ(this.tribe())?.name ?? '');
  protected readonly popIcon = computed(() => this.art.url(this.art.manifest()?.icons['population']));
  protected readonly phaseName = computed(() => {
    const v = this.village();
    const growth = this.engine.pack()?.village.growth;
    return growth?.phases.find((p) => p.id === v?.economy.phase)?.name ?? '';
  });

  protected readonly resources = computed(() => {
    const v = this.village();
    const pack = this.engine.pack();
    if (!v || !pack) return [];
    const now = this.game.resources();
    return pack.resources.map((r) => {
      const cap = v.economy.capacity[r.id] ?? 0;
      const out = v.economy.tribute_out?.[r.id] ?? 0;
      const got = v.economy.tribute_in?.[r.id] ?? 0;
      return {
        id: r.id,
        name: r.name + (out ? `, tribute paid ${Math.round(out)}/h` : '') + (got ? `, tribute received ${Math.round(got)}/h` : ''),
        icon: this.art.resourceIcon(r.id),
        amount: now[r.id] ?? 0,
        cap,
        rate: Math.round(v.economy.production[r.id] ?? 0),
        full: (now[r.id] ?? 0) >= cap * 0.98,
      };
    });
  });

  protected readonly queue = computed(() => {
    const v = this.village();
    const now = this.game.now();
    return (v?.build_queue ?? []).map((q) => ({
      id: q.id,
      level: q.level,
      name: this.engine.building(q.building)?.name ?? q.building,
      icon: this.art.buildingIcon(this.artTribe(), q.building),
      left: Math.max(0, q.due_at - now),
      progress: Math.min(100, Math.max(0, ((now - q.started_at) / Math.max(1, q.due_at - q.started_at)) * 100)),
    }));
  });

  protected readonly researching = computed(() => {
    const now = this.game.now();
    return (this.village()?.research ?? []).map((r) => ({
      id: r.id,
      name: this.engine.tech(r.tech)?.name ?? r.tech,
      icon: this.art.techIcon(r.tech),
      left: Math.max(0, r.due_at - now),
      progress: Math.min(100, Math.max(0, ((now - r.started_at) / Math.max(1, r.due_at - r.started_at)) * 100)),
    }));
  });

  protected readonly training = computed(() => {
    const now = this.game.now();
    return (this.village()?.training ?? []).map((t) => ({
      id: t.id,
      remaining: t.remaining,
      name: this.engine.unit(t.unit)?.name ?? t.unit,
      icon: this.art.unitIcon(t.unit),
      left: Math.max(0, t.finishes_at - now),
      progress: Math.min(100, Math.max(0, 100 - ((t.next_at - now) / Math.max(1, t.each_ms)) * 100)),
    }));
  });

  protected readonly troops = computed(() =>
    Object.entries(this.village()?.state.units ?? {})
      .filter(([, n]) => n > 0)
      .map(([id, count]) => ({ id, count, name: this.engine.unit(id)?.name ?? id, icon: this.art.unitIcon(id) })),
  );

  protected readonly incoming = computed(() => {
    const now = this.game.now();
    return (this.village()?.movements.incoming ?? []).map((m) => ({
      id: m.id,
      hostile: m.kind === 'attack' || m.kind === 'raid',
      label: `${m.kind} from ${m.from.name}`,
      left: Math.max(0, m.arrives_at - now),
    }));
  });

  /** The scene's view of the village: one entry per site. */
  private readonly sceneView = computed<VillageSceneView | null>(() => {
    const v = this.village();
    const pack = this.engine.pack();
    if (!v || !pack || !this.art.manifest()) return null;
    const tribe = this.artTribe();
    const fields = pack.village.field_slots.length;
    const base = fields + pack.village.center_slots; // extra fields follow the center sites
    const extra = v.economy.extra_fields ?? 0;
    const growth = pack.village.growth;
    const open = v.economy.center_sites ?? pack.village.center_slots;
    let wallLevel = 0;
    const sites: SiteView[] = v.state.slots.map((s, i) => {
      const queued = v.build_queue.filter((q) => q.slot === i);
      const building = s.building ?? queued[0]?.building ?? null;
      const area = i < fields || (i >= base && !s.foreign) ? 'field' : 'center';
      const def = this.engine.building(building);
      const role = building && growth?.building === building ? 'civic' : building && i === fields && !growth ? 'civic' : def?.effects.defense ? 'wall' : building?.includes('rally') ? 'rally' : 'other';
      if (role === 'wall') wallLevel = Math.max(wallLevel, s.level);
      return {
        index: i,
        area,
        building,
        level: s.level,
        founding: s.level === 0 && queued.length > 0,
        upgrading: s.level > 0 && queued.length > 0,
        fieldKind: area === 'field' ? this.art.fieldKind(building) : null,
        structure: this.art.structure(s.style ?? tribe, building),
        role,
        ruin: !!building && foreignRole(pack, building) === 'ruin',
        idle: area === 'center' && !!building && s.level === 0 && queued.length === 0,
        foreign: !!s.foreign,
        digging: !!v.archaeology?.digs.some((d) => d.slot === i),
        locked: s.foreign ? false : i >= base ? i - base >= extra : area === 'center' && !building && i - fields >= open,
      };
    });
    return { id: v.id, civ: this.art.civOf(tribe), sites, wallLevel };
  });

  constructor() {
    afterNextRender(async () => {
      const manifest = this.art.manifest();
      if (!manifest) return;
      const { VillageScene } = await import('../scene/village-scene');
      this.scene = new VillageScene(this.stage().nativeElement, manifest, {
        select: (i) => this.select(i),
        hover: () => undefined,
      });
      this.scene.applyPrefs(this.prefs.scene());
      this.scene.setPaused(this.overlay() === 'map');
      const view = this.sceneView();
      if (view) this.scene.setVillage(view);
    });
    effect(() => {
      const p = this.prefs.scene();
      this.scene?.applyPrefs(p);
    });
    effect(() => {
      const o = this.overlay();
      this.scene?.setPaused(o === 'map');
      if (o) this.select(null);
    });
    effect(() => {
      const view = this.sceneView();
      if (view && this.scene) this.scene.setVillage(view);
    });
  }

  select(i: number | null): void {
    this.selected.set(i);
    this.scene?.select(i);
  }

  async refreshInspect(): Promise<void> {
    const v = this.village();
    if (v) await this.game.inspect(v.id);
  }

  async backHome(): Promise<void> {
    this.select(null);
    await this.game.home();
  }

  /** Opens one of your own cities (a colony, or the city that founded it). */
  protected goTo(id: number): void {
    if (this.game.inspecting()) return;
    void this.router.navigateByUrl('/');
    this.switchCity(String(id));
  }

  switchCity(id: string): void {
    this.select(null);
    void this.game.selectVillage(Number(id));
  }

  /** Overlord buildings not yet raised on any of this overlord's sites in a vassal. */
  private siteChoices(sites: EmbassyInfo[]): { id: string; name: string; text: string; affordable: boolean; costText: string }[] {
    const r = embassyRules(this.engine.pack());
    const have = this.game.resources();
    return (r?.overlord ?? [])
      .filter((b) => !sites.some((s) => s.building === b))
      .map((b) => {
        const def = this.engine.building(b);
        const cost = this.engine.buildCost(b, 1);
        return {
          id: b, name: def?.name ?? b, text: def?.description ?? '',
          affordable: Object.entries(cost).every(([k, n]) => (have[k] ?? 0) >= n),
          costText: Object.entries(cost).map(([k, n]) => `${Math.round(n)} ${k}`).join(', '),
        };
      });
  }

  protected count(u: Record<string, number>): number {
    return Object.values(u ?? {}).reduce((a, b) => a + b, 0);
  }

  async buildSite(vassalId: number, slot: number, building?: string): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.buildOverlordSite(vassalId, slot, v.id, building), 'Construction ordered');
  }

  /** The next embassy level this city could pay for in a vassal, or null when it is complete. */
  private embassyNext(e: EmbassyInfo): { level: number; affordable: boolean; costText: string } | null {
    const b = this.engine.building(e.building ?? 'embassy');
    const level = Math.max(e.level, ...e.queued.map((q) => q.level)) + 1;
    if (!b || !e.building || e.building !== b.id || level > b.max_level) return null;
    const cost = this.engine.buildCost(b.id, level);
    const have = this.game.resources();
    return {
      level,
      affordable: Object.entries(cost).every(([r, n]) => (have[r] ?? 0) >= n),
      costText: Object.entries(cost).map(([r, n]) => `${Math.round(n)} ${r}`).join(', '),
    };
  }

  async buildEmbassy(vassalId: number): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.buildEmbassy(vassalId, v.id), 'Embassy ordered');
  }


  /** A tax rate one step (1 point) up or down, within the overlord's range; null when it would leave it. */
  protected taxStep(rate: number, dir: 1 | -1): number | null {
    const t = this.game.village()?.taxes;
    const next = Math.round((rate + dir * 0.01) * 100) / 100;
    return t && next >= t.min - 1e-9 && next <= t.max + 1e-9 ? next : null;
  }

  protected pct(rate: number): string {
    return `${Math.round(rate * 100)}%`;
  }

  protected hasTaxable(vassals: { colony: boolean }[]): boolean {
    return vassals.some((x) => !x.colony);
  }

  async setTax(vassalId: number, rate: number | null): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.taxVassal(v.id, vassalId, rate), rate === null ? 'Follows the realm rate' : `Tax set to ${Math.round(rate * 100)}%`);
  }

  async setRealmTax(rate: number | null): Promise<void> {
    const v = this.village();
    if (!v) return;
    try {
      const r = await this.api.taxRealm(rate);
      this.game.toast(`Taxes for ${r.vassals} vassal${r.vassals === 1 ? '' : 's'}: ${rate === null ? 'the usual tribute' : Math.round(rate * 100) + '%'}`, 'good');
      await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  /** Levy forms, one per vassal: unit, count and the city that pays. */
  private readonly levies = signal<Record<number, LevyDraft>>({});

  protected levyDraft(vassalId: number, a: Auxiliaries): LevyDraft {
    const d = this.levies()[vassalId];
    const unit = d && a.options.some((o) => o.unit === d.unit) ? d.unit : a.options[0]?.unit ?? '';
    return { unit, count: d?.count ?? 1, from: d?.from ?? this.village()?.id ?? 0 };
  }

  protected setLevy(vassalId: number, change: Partial<LevyDraft>): void {
    const a = this.village()?.vassals?.find((x) => x.village.id === vassalId)?.garrison?.auxiliaries;
    if (!a) return;
    this.levies.update((all) => ({ ...all, [vassalId]: { ...this.levyDraft(vassalId, a), ...change } }));
  }

  protected room(capacity: number, a: Auxiliaries): number {
    return Math.max(0, capacity - a.levied - a.queued);
  }

  protected levyCost(f: LevyDraft, a: Auxiliaries): ResourceMap | null {
    const o = a.options.find((x) => x.unit === f.unit);
    return o && f.count > 0 ? Object.fromEntries(Object.entries(o.cost_each).map(([r, n]) => [r, n * f.count])) : null;
  }

  protected costText(cost: ResourceMap): string {
    return Object.entries(cost).filter(([, n]) => n > 0).map(([r, n]) => `${Math.round(n)} ${r}`).join(', ');
  }

  protected unitName(unit: string, a: Auxiliaries): string {
    return a.options.find((o) => o.unit === unit)?.name ?? this.engine.unit(unit)?.name ?? unit;
  }

  async levy(vassalId: number, f: LevyDraft): Promise<void> {
    const v = this.village();
    if (!v || f.count < 1) return;
    // the server answers with the overlord's city (this one), whoever paid
    await this.game.act(() => this.api.levy(vassalId, f.from, f.unit, Math.floor(f.count)), `Levying ${Math.floor(f.count)} auxiliaries`);
  }

  async cancelLevy(vassalId: number, jobId: number): Promise<void> {
    const v = this.village();
    if (!v || this.game.inspecting()) return;
    try {
      await this.api.cancelLevy(vassalId, jobId);
      this.game.toast('Levy stopped, the rest paid back', 'good');
      await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  async renounce(): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.renounce(v.id), 'The oath is renounced');
  }

  async withdrawFealty(): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.withdrawFealty(v.id), 'Offer withdrawn');
  }

  async answerFealty(vassalId: number, answer: 'accept' | 'decline'): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.answerFealty(v.id, vassalId, answer), answer === 'accept' ? 'A new vassal' : 'Offer declined');
  }

  async release(vassalId: number): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.release(v.id, vassalId), 'Vassal released');
  }

  async cancel(jobId: number): Promise<void> {
    const v = this.village();
    if (v) await this.game.act(() => this.api.cancel(v.id, jobId), 'Cancelled, resources refunded');
  }

  /** Keyboard shortcuts for the screens; Escape closes an open screen. */
  @HostListener('window:keydown', ['$event'])
  protected shortcut(e: KeyboardEvent): void {
    if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement)?.closest?.('input,textarea,select')) return;
    if (e.key === 'Escape' && this.more()) {
      this.more.set(false);
      return;
    }
    if (e.key === 'Escape' && this.overlay()) {
      void this.router.navigateByUrl('/');
      return;
    }
    const n = this.navItems().find((x) => x.key.toLowerCase() === e.key.toLowerCase());
    if (n) {
      this.more.set(false);
      void this.router.navigateByUrl(n.path);
    }
  }

  ngOnDestroy(): void {
    this.scene?.dispose();
  }
}
