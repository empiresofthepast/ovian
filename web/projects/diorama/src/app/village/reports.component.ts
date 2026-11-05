import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { Report, ReportSummary } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

/** Battle and reinforcement reports, with unit portraits. */
@Component({
  selector: 'dio-reports',
  imports: [...UI],
  template: `
    <section class="hud-panel reports" role="dialog" aria-label="Reports">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Reports</h2>
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
            <h3 class="subhead">{{ r.title }}</h3>
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

  constructor() {
    void this.api.reports().then((l) => this.list.set(l));
  }

  async show(id: number): Promise<void> {
    this.open.set(await this.api.report(id));
    this.list.update((l) => l.map((r) => (r.id === id ? { ...r, read: true } : r)));
    void this.game.refreshMe();
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
