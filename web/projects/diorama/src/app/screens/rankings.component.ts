import { Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { HallOfFame, MedalsView, Victory } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

interface Row { rank: number; id: number; username: string; tribe: string; bot?: boolean; villages: number; population: number; culture: number; vassals?: number; alliance_tag?: string | null }

@Component({
  selector: 'dio-rankings',
  imports: [...UI],
  template: `
    <section class="hud-panel dialog rankings" role="dialog" aria-label="Rankings">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Rankings</h2>
      <div class="seg" role="tablist" aria-label="Ranking">
        @for (t of tabs; track t.id) {<button type="button" role="tab" class="seg__opt" [class.seg__opt--on]="tab() === t.id" (click)="tab.set(t.id)">{{ t.label }}</button>}
      </div>
      @if (tab() === 'alliances') {
        <div class="table-wrap"><table class="table">
          <thead><tr><th class="num">#</th><th>Alliance</th><th class="num">Members</th><th class="num">Population</th><th class="num">Culture</th></tr></thead>
          <tbody>
            @for (a of alliances(); track a.id) {<tr><td class="num">{{ a.rank }}</td><td>[{{ a.tag }}] {{ a.name }}</td><td class="num">{{ a.members }}</td><td class="num">{{ a.population | n }}</td><td class="num">{{ a.culture | n }}</td></tr>}
            @empty {<tr><td colspan="5" class="muted">No alliances yet.</td></tr>}
          </tbody>
        </table></div>
      } @else if (tab() === 'medals') {
        @if (medals(); as m) {
          <p class="small muted">Every week the three players who gained most in each category win gold, silver and bronze.@if (m.next_award_at) { Next awards in {{ m.next_award_at - game.now() | dur: 'ms' }}.}</p>
          <div class="medal-cats">
            @for (c of m.categories; track c.id) {
              <div class="medal-cat">
                <strong>{{ c.name }}</strong>
                @for (x of latestOf(m, c.id); track x.rank) {<div class="small">{{ medalIcon(x.rank) }} {{ x.player.name }} <span class="muted">{{ x.value | n }}</span></div>}
                @empty {<div class="small muted">Not awarded yet.</div>}
                <div class="small muted">You this week: {{ c.progress | n }} {{ c.unit }}</div>
              </div>
            }
          </div>
          <h3 class="subhead">Medal table · round {{ m.round }}</h3>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Player</th><th class="num">🥇</th><th class="num">🥈</th><th class="num">🥉</th></tr></thead>
            <tbody>
              @for (r of m.table; track r.player_id) {<tr [class.me]="r.player_id === game.me()?.id"><td>{{ r.username }}</td><td class="num">{{ r.gold }}</td><td class="num">{{ r.silver }}</td><td class="num">{{ r.bronze }}</td></tr>}
              @empty {<tr><td colspan="4" class="muted">No medals yet.</td></tr>}
            </tbody>
          </table></div>
          @if (m.mine.length) {
            <h3 class="subhead">Your medals</h3>
            <div class="small">@for (x of m.mine; track $index) {<span class="tag" [title]="'Round ' + x.round + ', ' + (x.value | n)">{{ medalIcon(x.rank) }} {{ x.name }}</span> }</div>
          }
        }
      } @else if (tab() === 'fame') {
        @if (fame(); as f) {
          <p class="small muted">Round {{ f.current_round }} is under way. Finished rounds are kept here for good.</p>
          @for (r of f.rounds; track r.round) {
            <div class="fame">
              <h3 class="subhead">Round {{ r.round }} <span class="muted small">· ended {{ r.ended_at | clock }}@if (r.data.speed) { · speed {{ r.data.speed }}}</span></h3>
              @if (r.data.winner; as w) {<p class="good small">🏛 {{ w.player.name }} built the wonder in {{ w.village.name }}.</p>}
              <div class="small">@for (p of r.data.players.slice(0, 5); track p.id; let i = $index) {<span>{{ i + 1 }}. <strong>{{ p.username }}</strong> <span class="muted">{{ p.population | n }}</span>&nbsp;&nbsp;</span>}</div>
              @if (r.data.alliances.length) {<div class="small muted">Alliances: @for (a of r.data.alliances; track a.id) {[{{ a.tag }}] {{ a.name }}&nbsp;&nbsp;}</div>}
            </div>
          } @empty {<p class="muted">No round has ended yet.</p>}
          <h3 class="subhead">All-time medals</h3>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Player</th><th class="num">🥇</th><th class="num">🥈</th><th class="num">🥉</th></tr></thead>
            <tbody>
              @for (r of f.all_time; track r.player_id) {<tr><td>{{ r.username }}</td><td class="num">{{ r.gold }}</td><td class="num">{{ r.silver }}</td><td class="num">{{ r.bronze }}</td></tr>}
              @empty {<tr><td colspan="4" class="muted">No medals yet.</td></tr>}
            </tbody>
          </table></div>
        }
      } @else if (tab() === 'wonder') {
        @if (victory(); as w) {
          @if (w.winner) {<p class="good">🏛 {{ w.winner.player.name }} finished the wonder in {{ w.winner.village.name }} and won this world.</p>}
          <p class="small muted">The first to finish level {{ w.max_level }} of the wonder wins the world.</p>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>City</th><th>Player</th><th class="num">Wonder level</th></tr></thead>
            <tbody>
              @for (r of w.race; track r.id) {<tr><td>{{ r.name }} <span class="muted">({{ r.x }}|{{ r.y }})</span></td><td>{{ r.username }}</td><td class="num">{{ r.level }} / {{ w.max_level }}</td></tr>}
              @empty {<tr><td colspan="3" class="muted">No one has begun a wonder yet.</td></tr>}
            </tbody>
          </table></div>
        }
      } @else {
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th class="num">#</th><th>Player</th><th>Civilization</th><th class="num">Cities</th><th class="num">Population</th><th class="num">Culture</th><th class="num">Vassals</th></tr></thead>
          <tbody>
            @for (r of view(); track r.id) {
              <tr [class.me]="r.id === game.me()?.id">
                <td class="num">{{ r.rank }}</td>
                <td>@if (r.alliance_tag) {<span class="muted">[{{ r.alliance_tag }}]</span> }<strong>{{ r.username }}</strong>@if (r.bot) {&nbsp;<span title="An AI ruler">🤖</span>}</td>
                <td class="civcell">@if (r.emblem) {<img [src]="r.emblem" alt="" />}{{ r.civ }}</td>
                <td class="num">{{ r.villages }}</td>
                <td class="num">{{ r.population | n }}</td>
                <td class="num">{{ r.culture | n }}</td>
                <td class="num">{{ r.vassals ?? 0 }}</td>
              </tr>
            } @empty {<tr><td colspan="7" class="muted">No one has founded a city yet.</td></tr>}
          </tbody>
        </table>
      </div>
      }
    </section>
  `,
})
export class RankingsComponent {
  protected readonly game = inject(GameStore);
  private readonly art = inject(ArtService);
  private readonly engine = inject(EngineService);
  private readonly router = inject(Router);
  private readonly rows = signal<Row[]>([]);
  protected readonly tabs = [
    { id: 'players', label: 'Players' }, { id: 'alliances', label: 'Alliances' }, { id: 'medals', label: 'Medals' },
    { id: 'wonder', label: 'Wonder race' }, { id: 'fame', label: 'Hall of fame' },
  ];
  protected readonly medals = signal<MedalsView | null>(null);
  protected readonly fame = signal<HallOfFame | null>(null);
  protected readonly tab = signal('players');
  protected readonly alliances = signal<any[]>([]);
  protected readonly victory = signal<Victory | null>(null);
  protected readonly view = computed(() =>
    this.rows().map((r) => ({
      ...r,
      civ: this.engine.pack()?.tribes.find((t) => t.id === r.tribe)?.name ?? r.tribe,
      emblem: this.art.url(this.art.civ(r.tribe)?.emblem),
    })),
  );

  constructor() {
    const api = inject(Api);
    api.rankings().then((r) => this.rows.set(r)).catch(() => undefined);
    api.alliances().then((r) => this.alliances.set(r)).catch(() => undefined);
    api.victory().then((r) => this.victory.set(r)).catch(() => undefined);
    api.medals().then((r) => this.medals.set(r)).catch(() => undefined);
    api.hallOfFame().then((r) => this.fame.set(r)).catch(() => undefined);
  }

  protected latestOf(m: MedalsView, category: string) {
    return m.latest.filter((x) => x.category === category);
  }

  protected medalIcon(rank: number): string {
    return ['🥇', '🥈', '🥉'][rank - 1] ?? '🏅';
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
