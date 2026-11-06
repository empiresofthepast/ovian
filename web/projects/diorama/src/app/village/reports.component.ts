import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { Report, ReportSummary } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

/** Battle, reinforcement, trade and pact reports, with unit portraits. */
@Component({
  selector: 'dio-reports',
  imports: [DatePipe, RouterLink, ...UI],
  template: `
    <section class="hud-panel reports" role="dialog" aria-label="Reports">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Reports</h2>
      @if (hasUnread()) {<button class="btn btn--small reports__all" (click)="markAllRead()">Mark all as read</button>}
      <div class="reports__cols">
        <ul class="reports__list">
          @for (r of list(); track r.id) {
            <li><button class="reports__item" [class.reports__item--unread]="!r.read" [class.reports__item--on]="open()?.id === r.id" (click)="show(r.id)">
              <span>{{ r.title }}</span><time class="muted small">{{ when(r.created_at) }}</time>
            </button></li>
          } @empty {<li class="muted">Nothing has happened yet.</li>}
        </ul>
        <div class="reports__detail">
          @if (open(); as r) {
            <h3 class="subhead">{{ r.title }}@if (r.data?.horde) { <span class="tag tag--bad" title="The barbarians gathered against the strongest">Barbarian horde</span>}</h3>
            @if (r.data?.attacker) {
              @for (side of sides(r); track side.label) {
                <div class="side-report">
                  <div class="side-report__who">{{ side.label }}: <strong>{{ side.name }}</strong> <span class="muted">{{ side.village }}</span></div>
                  <div class="troop-row">
                    @for (u of side.units; track u.id) {
                      <div class="troop" [title]="u.name">
                        <dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" />
                        <span>{{ u.count }}</span>@if (u.lost) {<span class="bad small">−{{ u.lost }}</span>}
                      </div>
                    } @empty {<span class="muted small">no troops</span>}
                  </div>
                </div>
              }
              @if (r.data.loot) {<div class="small">Loot: <dio-cost [cost]="r.data.loot" /></div>}
              @if (r.data.settled; as st) {
                <div class="small good">Settlers stayed behind: the camp is now <strong>{{ st.village.name }}</strong>, your colony, with all its stores: <dio-cost [cost]="st.stores" /></div>
              }
              @if (r.data.camp?.find; as f) {
                <div class="small good">Among the spoils: <strong>{{ f.name }}</strong> ({{ f.grade }}), now kept in {{ f.kept_in?.name }}. Show it in a temple for +{{ f.culture }} culture.</div>
              }
              @if (r.data.culture?.attacker_bonus || r.data.culture?.defender_bonus) {
                <div class="small">Cultural prestige:
                  @if (r.data.culture.attacker_bonus) {attacker +{{ (r.data.culture.attacker_bonus * 100).toFixed(0) }}% attack}
                  @if (r.data.culture.defender_bonus) {defender +{{ (r.data.culture.defender_bonus * 100).toFixed(0) }}% defense}
                </div>
              }
              @if (r.data.submission; as s) {
                <div class="small">Submission:
                  @if (s.submitted) {<strong>{{ r.data.defender.village.name }} submits to {{ r.data.attacker.village.name }}</strong>, paying {{ (s.tribute * 100).toFixed(0) }}% tribute}
                  @else if (s.reset) {the defence resets the count of wins in a row}
                  @else if (s.vassal) {already a vassal of the attacker}
                  @else {{{ s.wins }} of {{ s.needed }} wins in a row}
                  @if (s.freed) {. {{ r.data.attacker.village.name }} breaks free of its overlord}
                </div>
              }
            } @else if (r.kind === 'starvation') {
              <p class="small">Out of {{ r.data.resource }}, {{ r.data.village.name }} could not feed its army. These troops died:</p>
              <div class="troop-row">
                @for (u of units(r.data.units, {}); track u.id) {
                  <div class="troop"><dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" /><span>{{ u.count }}</span></div>
                }
              </div>
            } @else if (r.kind === 'ver_sacrum') {
              @if (r.data.founded) {
                <p class="small">The migrants of {{ r.data.from.name }} founded <strong>{{ r.data.colony.name }}</strong> at ({{ r.data.x }}|{{ r.data.y }}). It is yours to manage and pays tribute to {{ r.data.from.name }}.</p>
              } @else {
                <p class="small">Someone settled ({{ r.data.x }}|{{ r.data.y }}) first. The migrants came home; the resources and the ver sacrum are back in {{ r.data.from.name }}.</p>
              }
            } @else if (r.kind === 'trade' && r.data?.robbed) {
              <p class="small">On the way from {{ r.data.from?.name }} to {{ r.data.to?.name }}, bandits took <dio-cost [cost]="r.data.robbed" />.</p>
              <p class="small">The rest was delivered: <dio-cost [cost]="r.data.delivered" /></p>
              <p class="small muted">Roads keep caravans safe; long journeys off the roads tempt bandits.</p>
            } @else if (r.kind === 'treaty' && r.data) {
              @if (r.data.breaker; as b) {
                <p class="small bad">{{ b.name }} broke your pact and marches on {{ r.data.target?.name }}.</p>
                <p class="small muted">The map marks {{ b.name }} as an oath-breaker until {{ r.data.until | date: 'd MMM, HH:mm' }}, and their cities are unhappy.</p>
              } @else if (r.data.status) {
                <p class="small">Pact with <strong>{{ r.data.with?.name }}</strong>: {{ r.data.status === 'active' ? 'in force' : 'proposed' }}@if (r.data.ends_at) {<span class="bad">, ends {{ r.data.ends_at | date: 'd MMM, HH:mm' }}</span>}.</p>
                @if (r.data.tribute; as tr) {
                  <p class="small">{{ tr.i_pay ? 'You pay ' + r.data.with?.name : r.data.with?.name + ' pays you' }} <dio-cost [cost]="tr.resources" /> every {{ tr.every_hours }} h.</p>
                } @else {<p class="small muted">No tribute.</p>}
              } @else if (r.data.tribute) {
                <p class="small">The pact with {{ r.data.with }} lapsed: the tribute of <dio-cost [cost]="r.data.tribute" /> could not be paid.</p>
              }
              <p class="small"><a routerLink="/realm" [queryParams]="{ tab: 'pacts' }">Your pacts</a></p>
            } @else if (r.data?.units) {
              <div class="troop-row">
                @for (u of units(r.data.units, {}); track u.id) {
                  <div class="troop"><dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" /><span>{{ u.count }}</span></div>
                }
              </div>
            }
          } @else {<p class="muted">Choose a report.</p>}
        </div>
      </div>
    </section>
  `,
})
export class ReportsComponent {
  private readonly router = inject(Router);
  close(): void {
    void this.router.navigateByUrl('/');
  }
  private readonly api = inject(Api);
  private readonly game = inject(GameStore);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  protected readonly list = signal<ReportSummary[]>([]);
  protected readonly open = signal<Report | null>(null);
  protected readonly hasUnread = computed(() => (this.game.me()?.unread_reports ?? 0) > 0 || this.list().some((r) => !r.read));

  constructor() {
    void this.api.reports().then((l) => this.list.set(l));
  }

  async show(id: number): Promise<void> {
    this.open.set(await this.api.report(id));
    this.list.update((l) => l.map((r) => (r.id === id ? { ...r, read: true } : r)));
    void this.game.refreshMe();
  }

  async markAllRead(): Promise<void> {
    await this.api.markAllReportsRead();
    this.list.update((l) => l.map((r) => ({ ...r, read: true })));
    this.game.me.update((m) => m && { ...m, unread_reports: 0 });
  }

  when(ms: number): string {
    return new Date(ms).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
  }

  units(units: Record<string, number>, losses: Record<string, number>) {
    return Object.entries(units ?? {})
      .filter(([, n]) => n > 0)
      .map(([id, count]) => ({ id, count, lost: losses?.[id] ?? 0, name: this.engine.unit(id)?.name ?? id, icon: this.art.unitIcon(id) }));
  }

  sides(r: Report) {
    const d = r.data;
    return [
      { label: 'Attacker', name: d.attacker.player.name, village: d.attacker.village?.name ?? '', units: this.units(d.attacker.units, d.attacker.losses) },
      { label: 'Defender', name: d.defender.player.name, village: d.defender.village?.name ?? '', units: this.units(d.defender.units, d.defender.losses) },
      ...(d.defender.militia ? [{ label: 'Citizens under arms', name: d.defender.player.name, village: d.defender.village?.name ?? '', units: this.units(d.defender.militia.units, d.defender.militia.losses) }] : []),
    ];
  }
}
