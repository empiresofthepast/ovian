import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { DecimalPipe, KeyValuePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { Calendar, FestivalContest, ResourceMap, Season } from '../../core/models';
import { ResPipe, resourceNamer, seasonEffects, signed } from '../../shared/effects';
import { UI } from '../../shared/ui';

/** The calendar of seasons and the festival with its contests. */
@Component({
  selector: 'ov-festival',
  imports: [FormsModule, DecimalPipe, KeyValuePipe, ResPipe, ...UI],
  template: `
    <div class="page-head"><h1 class="page-title">{{ 'nav.festival' | label }}</h1>
      <button class="btn btn--ghost btn--small" (click)="load()">↻</button></div>
    @if (error()) {<p class="bad">{{ error() }}</p>}
    @if (cal(); as c) {
      <section class="panel">
        <h2 class="panel__title">{{ 'festival.calendar' | label: 'Calendar' }}
          @if (c.season; as s) {<span class="muted small">{{ s.name }}, {{ 'year' | label: 'year' }} {{ s.year }} · {{ 'festival.ends_in' | label: 'ends in' }} {{ s.ends_at - game.now() | duration }}</span>}</h2>
        <div class="cards">
          @for (s of c.seasons; track s.id) {
            <div class="card" [class.card--active]="s.id === c.season?.id">
              <strong>{{ s.name }}@if (s.id === c.season?.id) {<span class="muted small"> · {{ 'festival.now' | label: 'now' }}</span>}
                @if (c.festival?.season === s.id) {<span class="small"> 🏛</span>}</strong>
              @if (effects(s); as fx) {
                @if (fx.length) {<ul class="small">@for (e of fx; track e) {<li>{{ e }}</li>}</ul>}
                @else {<p class="small muted">{{ 'festival.mild' | label: 'An ordinary season.' }}</p>}
              }
            </div>
          }
        </div>
        @if (c.season_ms) {<p class="small muted">{{ 'festival.season_length' | label: 'Each season lasts' }} {{ c.season_ms | duration }}.</p>}
      </section>

      @if (c.festival; as f) {
        <section class="panel">
          <h2 class="panel__title">🏛 {{ f.name }}
            @if (f.active) {<span class="chip chip--accent">{{ 'festival.open' | label: 'open' }}</span>}</h2>
          <p class="small">{{ f.text }}</p>
          @if (f.active && f.closes_at) {
            <p class="small"><strong>{{ 'festival.closes_in' | label: 'The games close in' }} <span class="timer">{{ f.closes_at - game.now() | duration }}</span>.</strong></p>
          } @else if (f.opens_at) {
            <p class="small muted">{{ 'festival.opens_in' | label: 'The games open in' }} <span class="timer">{{ f.opens_at - game.now() | duration }}</span>, {{ 'festival.with' | label: 'with' }} {{ seasonName(f.season) }}.</p>
          }
          @if (f.prizes.length) {
            <h3 class="subtitle">{{ 'festival.prizes' | label: 'Prizes for each contest' }}</h3>
            @for (p of f.prizes; track $index) {
              <div class="row small"><span>{{ medal($index) }}</span>
                <span class="grow">@if (p.resources) {<span>{{ p.resources | res }}</span>}@if (p.favor) {, {{ p.favor }} favor}@if (p.contentment) {, {{ signed(p.contentment) }} contentment}</span></div>
            }
          }
        </section>

        <div class="realm">
          @for (e of f.contests | keyvalue; track e.key) {
            <section class="panel">
              <h2 class="panel__title">{{ e.value.name }} <span class="tag">{{ kindLabel(e.value) }}</span></h2>
              @if (e.value.text) {<p class="small muted">{{ e.value.text }}</p>}
              @if (e.value.mine !== null) {<p class="small"><strong>{{ 'festival.my_score' | label: 'Your entry' }}: {{ e.value.mine | number }}</strong></p>}
              @if (f.active && game.village(); as v) {
                <form class="form" (ngSubmit)="enter(e.key, e.value)">
                  @if (e.value.kind === 'resources') {
                    <div class="form__row">
                      @for (id of e.value.resources ?? []; track id) {
                        <label class="field field--short"><span><ov-icon [key]="'resource.' + id" /> {{ name(id) }}</span>
                          <input type="number" min="0" [name]="e.key + '-' + id" [ngModel]="offer(e.key)[id] ?? 0" (ngModelChange)="setOffer(e.key, id, $event)" /></label>
                      }
                    </div>
                  } @else {
                    <p class="small muted">{{ e.value.kind === 'army' ? 'Your troops at home in ' + v.name + ' compete.' : 'The culture of all your cities competes.' }}</p>
                  }
                  <div><button class="btn btn--primary btn--small" [disabled]="busy() || game.inspecting() || (e.value.kind === 'resources' && !hasOffer(e.key))">
                    {{ e.value.mine !== null && e.value.kind !== 'resources' ? ('festival.update' | label: 'Enter again') : ('festival.enter' | label: 'Enter from') + ' ' + v.name }}</button></div>
                </form>
              }
              <div class="table-wrap">
                <table class="table">
                  <thead><tr><th>#</th><th>{{ 'rank.player' | label: 'Player' }}</th><th class="num">{{ 'festival.score' | label: 'Score' }}</th></tr></thead>
                  <tbody>
                    @for (s of e.value.standings; track s.player_id; let i = $index) {
                      <tr [class.me]="s.player_id === game.me()?.id"><td>{{ medal(i) || i + 1 }}</td><td>{{ s.username }}</td><td class="num">{{ s.score | number: '1.0-0' }}</td></tr>
                    } @empty {<tr><td colspan="3" class="muted small">{{ 'festival.no_entries' | label: 'No entries yet.' }}</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
          }
        </div>

        @if (f.last; as last) {
          <section class="panel">
            <h2 class="panel__title">{{ 'festival.last' | label: 'Last games' }} <span class="muted small">{{ last.name }}</span></h2>
            @for (e of last.contests | keyvalue; track e.key) {
              <h3 class="subtitle">{{ e.value.name }}</h3>
              @for (w of e.value.winners; track w.rank) {
                <div class="row small"><span>{{ medal(w.rank - 1) || w.rank }}</span><span class="grow">{{ w.player.name }}</span><span class="num">{{ w.score | number: '1.0-0' }}</span></div>
              } @empty {<p class="muted small">{{ 'festival.no_winner' | label: 'Nobody entered.' }}</p>}
            }
          </section>
        }
      } @else {
        <section class="panel"><p class="muted small">{{ 'festival.none' | label: 'This world holds no festival.' }}</p></section>
      }
    } @else if (!error()) {
      <p class="muted">Loading…</p>
    }
  `,
})
export class FestivalComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  protected readonly name = resourceNamer();
  protected readonly signed = signed;
  protected readonly cal = signal<Calendar | null>(null);
  protected readonly error = signal('');
  protected readonly busy = signal(false);
  private readonly offers = signal<Record<string, ResourceMap>>({});

  constructor() {
    void this.load();
    const sub = this.game.serverEvents.subscribe((e) => {
      if (e.type.startsWith('festival.') || e.type === 'season.changed') void this.load();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  protected async load(): Promise<void> {
    try {
      this.cal.set(await this.api.calendar());
      this.error.set('');
    } catch (e) {
      this.error.set(this.game.errorText(e));
    }
  }

  protected effects(s: Season): string[] {
    return seasonEffects(s, this.name);
  }

  protected seasonName(id: string): string {
    return this.cal()?.seasons.find((s) => s.id === id)?.name ?? id;
  }

  protected medal(i: number): string {
    return ['🥇', '🥈', '🥉'][i] ?? '';
  }

  protected kindLabel(c: FestivalContest): string {
    return c.kind === 'resources' ? 'offerings' : c.kind;
  }

  protected offer(key: string): ResourceMap {
    return this.offers()[key] ?? {};
  }

  protected hasOffer(key: string): boolean {
    return Object.values(this.offer(key)).some((n) => n > 0);
  }

  protected setOffer(key: string, id: string, n: number): void {
    this.offers.update((o) => ({ ...o, [key]: { ...o[key], [id]: Math.max(0, Math.floor(Number(n) || 0)) } }));
  }

  protected async enter(key: string, c: FestivalContest): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    this.busy.set(true);
    try {
      const resources = c.kind === 'resources' ? Object.fromEntries(Object.entries(this.offer(key)).filter(([, n]) => n > 0)) : {};
      this.cal.set(await this.api.enterFestival(key, v.id, resources));
      this.offers.update((o) => ({ ...o, [key]: {} }));
      this.game.toast(`${c.name}: ${'your entry is in'}`, 'good');
      if (c.kind === 'resources') await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
    this.busy.set(false);
  }
}
