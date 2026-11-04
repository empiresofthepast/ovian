import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { Calendar, FestivalContest, ResourceMap, Season } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

const SEASON_ICON: Record<string, string> = { spring: '🌱', summer: '☀', autumn: '🍂', winter: '❄' };

/** The year: seasons and their effects, and the festival with its contests. */
@Component({
  selector: 'dio-festival',
  imports: [FormsModule, ...UI],
  template: `
    <section class="hud-panel dialog festival" role="dialog" aria-label="Calendar and games">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      @if (cal(); as c) {
        @if (c.season; as s) {
          <h2 class="selection__title">{{ icon(s.id) }} {{ s.name }} <span class="muted small">· year {{ s.year }} · {{ s.ends_at - game.now() | dur: 'ms' }} left</span></h2>
          <div class="seasons">
            @for (x of c.seasons; track x.id; let i = $index) {
              <div class="season" [class.season--on]="i === s.index">
                <strong>{{ icon(x.id) }} {{ x.name }}</strong>
                <div class="small">@for (e of effects(x); track e.text) {<div [class.good]="e.good" [class.bad]="!e.good">{{ e.text }}</div>} @empty {<span class="muted">An ordinary season.</span>}</div>
              </div>
            }
          </div>
          @if (c.season_ms) {<p class="small muted">Each season lasts {{ c.season_ms | dur: 'ms' }}; a year, {{ c.season_ms * c.seasons.length | dur: 'ms' }}.</p>}
        } @else {<h2 class="selection__title">Calendar</h2><p class="muted">This world has no seasons.</p>}

        @if (c.festival; as f) {
          <h3 class="subhead">🏛 {{ f.name }}
            @if (f.active) {<span class="good small">· open, closes in {{ f.closes_at! - game.now() | dur: 'ms' }}</span>}
            @else if (f.opens_at) {<span class="muted small">· opens in {{ f.opens_at - game.now() | dur: 'ms' }}</span>}
          </h3>
          <p class="small muted">{{ f.text }}</p>
          <div class="prizes small">
            @for (p of f.prizes; track $index) {
              <div>{{ medal($index + 1) }}&nbsp;@if (p.resources) {<dio-cost [cost]="prize(p.resources)" />}@if (p.favor) {<span>&nbsp;+{{ p.favor }} favor</span>}@if (p.contentment) {<span>, +{{ p.contentment }} contentment in all your cities</span>}</div>
            }
          </div>
          <div class="contests">
            @for (e of contests(); track e.id) {
              <div class="contest">
                <strong>{{ e.c.name }}</strong>
                <div class="small muted">{{ e.c.text }}</div>
                <ol class="standings small">
                  @for (s of e.c.standings; track s.player_id) {<li [class.me]="s.player_id === game.me()?.id">{{ s.username }} <span class="muted">{{ s.score | n }}</span></li>}
                  @empty {<li class="muted">No entries yet.</li>}
                </ol>
                @if (e.c.mine !== null) {<div class="small good">Your entry: {{ e.c.mine | n }}</div>}
                @if (f.active) {
                  @if (e.c.kind === 'resources') {
                    <div class="res-inputs">
                      @for (r of offerable(e.c); track r.id) {
                        <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="e.id + r.id" [(ngModel)]="offer[e.id + ':' + r.id]" [attr.aria-label]="r.name" /></label>
                      }
                    </div>
                    <button class="btn btn--gold btn--small" (click)="enter(e.id, e.c)">Offer{{ e.c.mine !== null ? ' more' : '' }} from {{ game.village()?.name }}</button>
                  } @else if (e.c.kind === 'army') {
                    <button class="btn btn--gold btn--small" (click)="enter(e.id, e.c)">Send the troops of {{ game.village()?.name }}</button>
                  } @else {
                    <button class="btn btn--gold btn--small" (click)="enter(e.id, e.c)">Enter your poets</button>
                  }
                }
              </div>
            }
          </div>
          @if (f.last; as l) {
            <h3 class="subhead">Last games · year {{ l.number }}</h3>
            @for (x of lastContests(); track x.id) {
              <div class="small"><strong>{{ x.name }}</strong>: @for (w of x.winners; track w.rank) {<span>{{ medal(w.rank) }} {{ w.player.name }}&nbsp;</span>} @empty {<span class="muted">no one entered</span>}</div>
            }
          }
        }
      } @else {<p class="muted">Loading…</p>}
    </section>
  `,
})
export class FestivalComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  protected readonly cal = signal<Calendar | null>(null);
  protected offer: Record<string, number> = {};
  protected readonly contests = computed(() => Object.entries(this.cal()?.festival?.contests ?? {}).map(([id, c]) => ({ id, c })));
  protected readonly lastContests = computed(() => Object.entries(this.cal()?.festival?.last?.contests ?? {}).map(([id, c]) => ({ id, ...c })));

  constructor() {
    void this.load();
    const sub = this.game.serverEvents.subscribe((e) => {
      if (e.type.startsWith('season.') || e.type.startsWith('festival.')) void this.load();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  private async load(): Promise<void> {
    this.cal.set(await this.api.calendar());
  }

  protected icon(id: string): string {
    return SEASON_ICON[id] ?? '◷';
  }

  protected medal(rank: number): string {
    return ['🥇', '🥈', '🥉'][rank - 1] ?? `#${rank}`;
  }

  /** Prize resources, with "all" spread over every resource. */
  protected prize(m: ResourceMap): ResourceMap {
    const ids = (this.engine.pack()?.resources ?? []).map((r) => r.id);
    const out: ResourceMap = {};
    for (const [k, n] of Object.entries(m)) for (const r of k === 'all' ? ids : [k]) out[r] = (out[r] ?? 0) + n;
    return out;
  }

  protected effects(s: Season): { text: string; good: boolean }[] {
    const out: { text: string; good: boolean }[] = [];
    for (const [r, n] of Object.entries(s.production ?? {})) {
      const name = r === 'all' ? 'production' : this.engine.pack()?.resources.find((x) => x.id === r)?.name.toLowerCase() ?? r;
      out.push({ text: `${n > 0 ? '+' : ''}${Math.round(n * 100)}% ${name}`, good: n > 0 });
    }
    if (s.travel && s.travel !== 1) out.push({ text: s.travel > 1 ? `marches ${Math.round((s.travel - 1) * 100)}% slower` : `marches ${Math.round((1 - s.travel) * 100)}% faster`, good: s.travel < 1 });
    if (s.contentment) out.push({ text: `${s.contentment > 0 ? '+' : ''}${s.contentment} contentment`, good: s.contentment > 0 });
    return out;
  }

  protected offerable(c: FestivalContest) {
    const ids = c.resources?.length ? c.resources : (this.engine.pack()?.resources ?? []).map((r) => r.id);
    return ids.map((id) => ({ id, name: this.engine.pack()?.resources.find((r) => r.id === id)?.name ?? id, icon: this.art.resourceIcon(id) }));
  }

  protected async enter(id: string, c: FestivalContest): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    const res: ResourceMap = {};
    if (c.kind === 'resources') {
      for (const r of this.offerable(c)) {
        const n = Math.floor(Number(this.offer[id + ':' + r.id]) || 0);
        if (n > 0) res[r.id] = n;
      }
    }
    try {
      this.cal.set(await this.api.enterFestival(id, v.id, res));
      for (const k of Object.keys(this.offer)) if (k.startsWith(id + ':')) delete this.offer[k];
      this.game.toast(`Entered in the ${c.name}`, 'good');
      if (c.kind === 'resources') await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
