import { Component, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { HallOfFame, Medal, MedalsView, Victory } from '../../core/models';
import { UI } from '../../shared/ui';
import { BadgesComponent } from '../../shared/badges';

type Tab = 'players' | 'victory' | 'medals' | 'fame';

@Component({
  selector: 'ov-rankings',
  imports: [DatePipe, DecimalPipe, NgTemplateOutlet, BadgesComponent, ...UI],
  template: `
    <div class="page-head"><h1 class="page-title">{{ 'nav.rankings' | label }}</h1></div>
    <div class="tabs" role="tablist">
      @for (t of tabs; track t.id) {
        <button class="tabs__tab" role="tab" [attr.aria-selected]="tab() === t.id" [class.tabs__tab--active]="tab() === t.id" (click)="open(t.id)">{{ 'rank.tab.' + t.id | label: t.label }}</button>
      }
    </div>

    @switch (tab()) {
      @case ('players') {
        <section class="panel">
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>#</th><th>{{ 'rank.player' | label: 'Player' }}</th><th>{{ 'login.tribe' | label: 'Tribe' }}</th>
                <th class="num">{{ 'rank.villages' | label: 'Villages' }}</th><th class="num">{{ 'rank.population' | label: 'Population' }}</th><th class="num">{{ 'rank.vassals' | label: 'Vassals' }}</th></tr></thead>
              <tbody>
                @for (r of rows(); track r.id) {
                  <tr [class.me]="r.id === game.me()?.id">
                    <td>{{ r.rank }}</td><td>{{ r.username }}@if (r.bot) { <span title="AI ruler">🤖</span>}@if (r.badges?.length) { <ov-badges [badges]="r.badges" [founderNo]="r.founder_no" />}</td><td>{{ r.tribe | name: 'tribe' }}</td>
                    <td class="num">{{ r.villages }}</td><td class="num">{{ r.population }}</td><td class="num">{{ r.vassals ?? 0 }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }
      @case ('medals') {
        @if (medals(); as m) {
          <div class="realm">
            <section class="panel">
              <h2 class="panel__title">{{ 'medals.week' | label: 'This week' }}
                @if (m.next_award_at) {<span class="muted small">{{ 'medals.next' | label: 'awarded in' }} {{ m.next_award_at - game.now() | duration }}</span>}</h2>
              @for (c of m.categories; track c.id) {
                <div class="row small"><span class="grow">{{ c.name }}</span><span class="muted">{{ 'medals.you' | label: 'you' }}:</span>
                  <strong class="num">{{ c.progress | number: '1.0-0' }}</strong><span class="muted">{{ c.unit }}</span></div>
              }
              <h2 class="panel__title">{{ 'medals.mine' | label: 'My medals' }}</h2>
              @for (x of m.mine; track $index) {
                <div class="row small"><span>{{ icon(x.rank) }}</span><span class="grow">{{ x.name }}</span><span class="muted">{{ x.at | date: 'mediumDate' }}</span></div>
              } @empty {<p class="muted small">{{ 'medals.none_yet' | label: 'None yet.' }}</p>}
            </section>
            <section class="panel">
              <h2 class="panel__title">{{ 'medals.latest' | label: 'Latest awards' }}@if (m.latest.length) {<span class="muted small">{{ m.latest[0].at | date: 'mediumDate' }}</span>}</h2>
              @for (g of latest(); track g.name) {
                <h3 class="subtitle">{{ g.name }}</h3>
                @for (x of g.medals; track x.rank) {
                  <div class="row small"><span>{{ icon(x.rank) }}</span><span class="grow">{{ x.player.name }}</span><span class="num">{{ x.value | number: '1.0-0' }}</span></div>
                }
              } @empty {<p class="muted small">{{ 'medals.not_yet' | label: 'No medals have been awarded yet.' }}</p>}
            </section>
          </div>
          <section class="panel">
            <h2 class="panel__title">{{ 'medals.table' | label: 'Medal table' }} <span class="muted small">{{ 'round' | label: 'round' }} {{ m.round }}</span></h2>
            <ng-container *ngTemplateOutlet="table; context: { rows: m.table }" />
          </section>
        } @else {<p class="muted">Loading…</p>}
      }
      @case ('victory') {
        @if (victory(); as v) {
          @if (v.winner; as w) {<section class="panel"><p>🏆 <strong>{{ w.text ?? (w.player.name + ' built the wonder') }}</strong> {{ 'victory.won' | label: 'and won this world.' }}</p></section>}
          <p class="muted small">{{ 'victory.intro' | label: 'The first player to reach any of these wins the world; the round then goes to the hall of fame.' }}</p>
          <div class="realm">
            @for (c of v.conditions ?? []; track c.id) {
              <section class="panel">
                <h2 class="panel__title">{{ c.name }} @if (c.target) {<span class="muted small">{{ 'victory.first_to' | label: 'first to' }} {{ c.target | number }} {{ unit(c.id) }}</span>} @else {<span class="muted small">{{ 'victory.wonder_level' | label: 'first to finish level' }} {{ v.max_level }}</span>}</h2>
                @if (c.id === 'wonder') {
                  @for (r of v.race.slice(0, 5); track r.id) {<div class="row small"><span class="grow">{{ r.username }} <span class="muted">· {{ r.name }}</span></span><span class="num">{{ r.level }} / {{ v.max_level }}</span></div>}
                  @empty {<p class="muted small">{{ 'victory.no_wonder' | label: 'No one has begun a wonder yet.' }}</p>}
                } @else {
                  @for (l of c.leaders ?? []; track l.player.id) {<div class="row small"><span class="grow">{{ l.player.name }}</span><span class="num">{{ l.value | number: '1.0-0' }} / {{ c.target | number }}</span></div>}
                  @empty {<p class="muted small">{{ 'victory.nobody' | label: 'Nobody yet.' }}</p>}
                }
              </section>
            }
          </div>
          <section class="panel">
            <h2 class="panel__title">{{ 'victory.titles' | label: 'Titles' }} <span class="muted small">{{ 'victory.titles_now' | label: 'who would hold them if the round ended now; the race that wins the world gives none' }}</span></h2>
            @for (t of v.titles ?? []; track t.id) {<div class="row small"><span>{{ titleIcon(t.id) }}</span><span class="grow"><strong>{{ t.player.name }}</strong> · {{ t.name }}</span><span class="muted num">{{ t.value | number: '1.0-1' }} {{ t.unit }}</span></div>}
            @if (!v.titles?.length) {<p class="muted small">{{ 'victory.no_titles' | label: 'No titles yet: they need players with three cities, battles won or culture.' }}</p>}
          </section>
        } @else {<p class="muted">Loading…</p>}
      }
      @case ('fame') {
        @if (fame(); as f) {
          @for (r of f.rounds; track r.round) {
            <section class="panel">
              <h2 class="panel__title">{{ 'round' | label: 'Round' }} {{ r.round }} <span class="muted small">{{ r.data.started_at ? (r.data.started_at | date: 'mediumDate') + ' – ' : '' }}{{ r.ended_at | date: 'mediumDate' }} · ×{{ r.data.speed }}</span></h2>
              @if (r.data.winner; as w) {<p>🏆 <strong>{{ w.text ?? (w.player.name + ' built the wonder of ' + (w.village?.name ?? '')) }}</strong>@if (w.condition) { <span class="muted small">· {{ w.condition.name }}</span>}</p>}
              @else {<p class="muted small">{{ 'fame.no_winner' | label: 'Nobody won the world.' }}</p>}
              @if (r.atlas) {<p class="small"><a [href]="atlasUrl(r.round)" target="_blank" rel="noopener" title="Terrain, cities, roads and events of the round, for OpenFantasyMap">🗺 {{ 'fame.atlas' | label: 'World map as the round ended (GeoJSON)' }}</a></p>}
              @if (r.data.titles?.length) {<div class="fame-titles">@for (t of r.data.titles!; track t.id) {<div class="row small"><span>{{ titleIcon(t.id) }}</span><span class="grow"><strong>{{ t.player.name }}</strong> · {{ t.name }}</span><span class="muted num">{{ t.value | number: '1.0-1' }} {{ t.unit }}</span></div>}</div>}
              <div class="realm">
                <div>
                  <h3 class="subtitle">{{ 'fame.players' | label: 'Top players' }}</h3>
                  <div class="table-wrap"><table class="table small">
                    <thead><tr><th>#</th><th>{{ 'rank.player' | label: 'Player' }}</th><th class="num">{{ 'rank.villages' | label: 'Cities' }}</th><th class="num">{{ 'rank.population' | label: 'Population' }}</th></tr></thead>
                    <tbody>@for (p of r.data.players.slice(0, 10); track p.id; let i = $index) {
                      <tr><td>{{ i + 1 }}</td><td>{{ p.username }}</td><td class="num">{{ p.cities }}</td><td class="num">{{ p.population }}</td></tr>
                    }</tbody></table></div>
                </div>
                <div>
                  <h3 class="subtitle">{{ 'fame.alliances' | label: 'Top alliances' }}</h3>
                  <div class="table-wrap"><table class="table small">
                    <thead><tr><th>#</th><th>{{ 'fame.alliance' | label: 'Alliance' }}</th><th class="num">{{ 'fame.members' | label: 'Members' }}</th><th class="num">{{ 'rank.population' | label: 'Population' }}</th></tr></thead>
                    <tbody>@for (a of r.data.alliances.slice(0, 10); track a.id; let i = $index) {
                      <tr><td>{{ i + 1 }}</td><td>[{{ a.tag }}] {{ a.name }}</td><td class="num">{{ a.members }}</td><td class="num">{{ a.population }}</td></tr>
                    } @empty {<tr><td colspan="4" class="muted">—</td></tr>}</tbody></table></div>
                </div>
              </div>
            </section>
          } @empty {
            <section class="panel"><p class="muted small">{{ 'fame.first_round' | label: 'This is the first round: no past rounds yet.' }} ({{ 'round' | label: 'round' }} {{ f.current_round }})</p></section>
          }
          <section class="panel">
            <h2 class="panel__title">{{ 'fame.all_time' | label: 'All-time medal table' }}</h2>
            <ng-container *ngTemplateOutlet="table; context: { rows: f.all_time }" />
          </section>
        } @else {<p class="muted">Loading…</p>}
      }
    }

    <ng-template #table let-rows="rows">
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>#</th><th>{{ 'rank.player' | label: 'Player' }}</th><th class="num">🥇</th><th class="num">🥈</th><th class="num">🥉</th></tr></thead>
          <tbody>
            @for (r of rows; track r.player_id; let i = $index) {
              <tr [class.me]="r.player_id === game.me()?.id"><td>{{ i + 1 }}</td><td>{{ r.username }}</td>
                <td class="num">{{ r.gold }}</td><td class="num">{{ r.silver }}</td><td class="num">{{ r.bronze }}</td></tr>
            } @empty {<tr><td colspan="5" class="muted small">{{ 'medals.empty' | label: 'No medals yet.' }}</td></tr>}
          </tbody>
        </table>
      </div>
    </ng-template>
  `,
})
export class RankingsComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  protected readonly tabs: { id: Tab; label: string }[] = [
    { id: 'players', label: 'Players' }, { id: 'victory', label: 'Ways to win' }, { id: 'medals', label: 'Medals' }, { id: 'fame', label: 'Hall of fame' },
  ];
  protected readonly tab = signal<Tab>('players');
  protected readonly rows = signal<any[]>([]);
  protected readonly medals = signal<MedalsView | null>(null);
  protected readonly fame = signal<HallOfFame | null>(null);
  protected readonly victory = signal<Victory | null>(null);
  protected readonly latest = signal<{ name: string; medals: Medal[] }[]>([]);

  constructor() {
    this.api.rankings().then((r) => this.rows.set(r)).catch(() => undefined);
  }

  protected open(t: Tab): void {
    this.tab.set(t);
    if (t === 'medals' && !this.medals()) {
      this.api.medals().then((m) => {
        this.medals.set(m);
        const groups = new Map<string, Medal[]>();
        for (const x of m.latest) groups.set(x.name, [...(groups.get(x.name) ?? []), x].sort((a, b) => a.rank - b.rank));
        this.latest.set([...groups].map(([name, medals]) => ({ name, medals })));
      }).catch((e) => this.game.toast(this.game.errorText(e), 'bad'));
    }
    if (t === 'victory' && !this.victory()) {
      this.api.victory().then((v) => this.victory.set(v)).catch((e) => this.game.toast(this.game.errorText(e), 'bad'));
    }
    if (t === 'fame' && !this.fame()) {
      this.api.hallOfFame().then((f) => this.fame.set(f)).catch((e) => this.game.toast(this.game.errorText(e), 'bad'));
    }
  }

  protected atlasUrl(round: number): string {
    return this.api.atlasGeojsonUrl(round);
  }

  protected unit(id: string): string {
    return { conquest: 'cities', battles: 'battles won', culture: 'culture' }[id] ?? '';
  }

  protected titleIcon(id: string): string {
    return { sprawling: '🗺', compact: '🏘', conquest: '👑', culture: '🎭', battles: '⚔' }[id] ?? '🏅';
  }

  protected icon(rank: number): string {
    return ['🥇', '🥈', '🥉'][rank - 1] ?? `#${rank}`;
  }
}
