import { DecimalPipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { Report, ReportSummary } from '../../core/models';
import { UI } from '../../shared/ui';

@Component({
  selector: 'ov-reports',
  imports: [RouterLink, DecimalPipe, ...UI],
  template: `
    <div class="page-head"><h1 class="page-title">{{ 'nav.reports' | label }}</h1></div>
    <div class="reports">
      <section class="panel reports__list">
        @for (r of list(); track r.id) {
          <a class="report-link" [class.report-link--unread]="!r.read" [class.report-link--active]="report()?.id === r.id" [routerLink]="['/reports', r.id]">
            <span class="grow">{{ r.title }}</span>
            <span class="muted small">{{ r.created_at | clock }}</span>
          </a>
        } @empty {<p class="muted">No reports yet.</p>}
        @if (more()) {<button class="btn btn--ghost btn--small" (click)="loadMore()">Older</button>}
      </section>

      @if (report(); as r) {
        <section class="panel reports__detail">
          <div class="row">
            <h2 class="panel__title grow">{{ r.title }}</h2>
            <button class="btn btn--ghost btn--small" (click)="remove(r.id)">Delete</button>
          </div>
          @if (r.kind === 'battle') {
            @let d = r.data;
            <p class="small muted">{{ 'kind.' + d.kind | label }} · {{ d.at | clock }} ·
              {{ d.winner === 'attacker' ? ('report.attacker_won' | label: 'The attacker won') : ('report.defender_won' | label: 'The defender held') }}</p>
            @for (side of [d.attacker, d.defender]; track $index) {
              <h3 class="subtitle">{{ $index === 0 ? ('report.attacker' | label: 'Attacker') : ('report.defender' | label: 'Defender') }}:
                {{ side.player.name }} · {{ side.village.name }} ({{ side.village.x }}|{{ side.village.y }})</h3>
              <table class="table small">
                <tr><th>Troops</th><td><ov-units [units]="side.units" /></td></tr>
                <tr><th>Losses</th><td><ov-units [units]="side.losses" /></td></tr>
              </table>
            }
            @for (g of d.defender.reinforcements; track $index) {
              <h3 class="subtitle">Reinforcement: {{ g.village.name }}</h3>
              <table class="table small">
                <tr><th>Troops</th><td><ov-units [units]="g.units" /></td></tr>
                <tr><th>Losses</th><td><ov-units [units]="g.losses" /></td></tr>
              </table>
            }
            <p class="small">{{ 'report.loot' | label: 'Loot' }}: <ov-cost [cost]="d.loot" /></p>
            @if (d.culture?.attacker_bonus || d.culture?.defender_bonus) {
              <p class="small">{{ 'report.prestige' | label: 'Cultural prestige' }}:
                @if (d.culture.attacker_bonus) {attacker +{{ (d.culture.attacker_bonus * 100).toFixed(0) }}%}
                @if (d.culture.defender_bonus) {defender +{{ (d.culture.defender_bonus * 100).toFixed(0) }}%}
              </p>
            }
            @if (d.submission; as s) {
              <p class="small">{{ 'report.submission' | label: 'Submission' }}:
                @if (s.submitted) {<strong>{{ d.defender.village.name }} submits to {{ d.attacker.village.name }}</strong> and pays {{ (s.tribute * 100).toFixed(0) }}% tribute.}
                @else if (s.reset) {the defence resets the count of wins in a row.}
                @else if (s.vassal) {already a vassal of the attacker.}
                @else {{{ s.wins }} of {{ s.needed }} wins in a row.}
                @if (s.freed) { {{ d.attacker.village.name }} breaks free of its overlord.}
              </p>
            }
            <p class="small muted">Attack {{ d.attack_power | number: '1.0-0' }} vs defense {{ d.defense_power | number: '1.0-0' }}
              @if (d.defense_bonus) {(wall +{{ d.defense_bonus * 100 | number: '1.0-0' }}%)}</p>
          } @else if (r.kind === 'starvation') {
            <p class="small">Out of {{ r.data.resource }}, {{ r.data.village.name }} could not feed its army. These troops died:</p>
            <ov-units [units]="r.data.units" />
          } @else if (r.kind === 'ver_sacrum') {
            @if (r.data.founded) {
              <p class="small">The migrants of {{ r.data.from.name }} founded <strong>{{ r.data.colony.name }}</strong> at ({{ r.data.x }}|{{ r.data.y }}). It is yours to manage and pays tribute to {{ r.data.from.name }}.</p>
            } @else {
              <p class="small">Someone settled ({{ r.data.x }}|{{ r.data.y }}) first. The migrants came home; the resources and the ver sacrum are back in {{ r.data.from.name }}.</p>
            }
          } @else {
            <p class="small">{{ r.data.from?.name }} → {{ r.data.to?.name }}</p>
            <ov-units [units]="r.data.units" />
          }
        </section>
      }
    </div>
  `,
})
export class ReportsComponent {
  private readonly api = inject(Api);
  private readonly game = inject(GameStore);
  private readonly router = inject(Router);
  readonly id = input<string>();
  protected readonly list = signal<ReportSummary[]>([]);
  protected readonly report = signal<Report | null>(null);
  protected readonly more = signal(false);

  constructor() {
    void this.load();
    effect(() => {
      const id = Number(this.id());
      if (id) void this.open(id);
      else this.report.set(null);
    });
  }

  private async load(): Promise<void> {
    const page = await this.api.reports();
    this.list.set(page);
    this.more.set(page.length >= 30);
  }

  protected async loadMore(): Promise<void> {
    const last = this.list().at(-1);
    const page = await this.api.reports(last?.id);
    this.list.update((l) => [...l, ...page]);
    this.more.set(page.length >= 30);
  }

  private async open(id: number): Promise<void> {
    try {
      const r = await this.api.report(id);
      this.report.set(r);
      this.list.update((l) => l.map((x) => (x.id === id ? { ...x, read: true } : x)));
      void this.game.refreshMe();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected async remove(id: number): Promise<void> {
    await this.api.deleteReport(id);
    this.list.update((l) => l.filter((x) => x.id !== id));
    void this.router.navigateByUrl('/reports');
  }
}
