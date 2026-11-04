import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { HeroView } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

@Component({
  selector: 'dio-hero',
  imports: [FormsModule, ...UI],
  template: `
    <section class="hud-panel dialog hero" role="dialog" aria-label="Hero">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      @if (data(); as d) {
        @if (d.hero; as h) {
          <div class="hero__sheet">
            <dio-portrait [src]="portrait(h.template)" [alt]="h.name" />
            <div class="grow">
              <h2 class="selection__title">{{ h.name }} <span class="muted small">· level {{ h.level }}</span></h2>
              <div class="small">
                @switch (h.status) {
                  @case ('home') { At home in {{ cityName(h.village_id) }}. }
                  @case ('away') { On campaign or on the road. }
                  @case ('dead') { <span class="bad">Fallen. Returns in {{ h.revive_at - game.now() | dur: 'ms' }}.</span> }
                }
              </div>
              <div class="bar" title="Experience"><div class="bar__fill" [style.width.%]="xpPct()"></div></div>
              <div class="small muted">{{ h.xp | n }} / {{ h.next_xp | n }} experience to level {{ h.level + 1 }}</div>
            </div>
          </div>
          <h3 class="subhead">Skills @if (h.unspent) {<span class="good small">· {{ h.unspent }} point{{ h.unspent > 1 ? 's' : '' }} to spend</span>}</h3>
          <div class="hero__skills">
            @for (s of skills; track s.id) {
              <div class="hero__skill">
                <div><strong>{{ s.name }}</strong> <span class="muted small">{{ h.points[s.id] }} points</span></div>
                <div class="small">+{{ (h.bonus[s.id] * 100).toFixed(0) }}% {{ s.text }}</div>
                <button class="btn btn--small" [disabled]="!h.unspent" (click)="spend(s.id)">+1</button>
              </div>
            }
          </div>
          <h3 class="subhead">Home</h3>
          <div class="row-form">
            <select [(ngModel)]="moveTo" aria-label="City">
              @for (c of game.me()?.villages ?? []; track c.id) {<option [ngValue]="c.id">{{ c.name }}</option>}
            </select>
            <button class="btn btn--small" [disabled]="h.status !== 'home' || moveTo === h.village_id" (click)="move()">Move there</button>
          </div>
          <p class="small muted">Send your hero with an attack or raid from the rally point. Battles give experience, double against barbarian camps. If the whole army falls, so does the hero, for a while.</p>
        } @else {
          <h2 class="selection__title">Choose your hero</h2>
          <p class="muted">A hero leads your armies, guards a city and makes it prosper. Choose one of your people's great figures.</p>
          <div class="hero__choices">
            @for (c of d.candidates; track c.id) {
              <button class="hero__choice" [class.hero__choice--on]="picked() === c.id" (click)="picked.set(c.id)">
                <dio-portrait [src]="portrait(c.id)" [alt]="c.name" />
                <strong>{{ c.title }}</strong>
                <span class="muted small">{{ c.name }}</span>
              </button>
            }
          </div>
          @if (pickedHero(); as c) {<p class="small">{{ c.history }}</p>}
          <button class="btn btn--gold" [disabled]="!picked()" (click)="choose()">Call this hero to {{ game.village()?.name }}</button>
        }
      } @else {<p class="muted">Loading…</p>}
    </section>
  `,
})
export class HeroComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  protected readonly data = signal<HeroView | null>(null);
  protected readonly picked = signal<string | null>(null);
  protected moveTo: number | null = null;
  protected readonly skills = [
    { id: 'attack' as const, name: 'Command', text: 'attack for armies they lead' },
    { id: 'defense' as const, name: 'Guard', text: 'defense in their home city' },
    { id: 'production' as const, name: 'Stewardship', text: 'production in their home city' },
  ];
  protected readonly pickedHero = computed(() => this.data()?.candidates.find((c) => c.id === this.picked()));
  protected readonly xpPct = computed(() => {
    const h = this.data()?.hero;
    return h ? Math.min(100, ((h.xp - h.level_xp) / Math.max(1, h.next_xp - h.level_xp)) * 100) : 0;
  });

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    const d = await this.api.hero();
    this.data.set(d);
    this.moveTo = d.hero?.village_id ?? null;
  }

  protected portrait(id: string): string | null {
    return this.art.url(this.art.civ(this.game.me()?.tribe)?.heroes?.[id]);
  }

  protected cityName(id: number | null): string {
    return this.game.me()?.villages.find((v) => v.id === id)?.name ?? '';
  }

  private async run(fn: () => Promise<unknown>, ok?: string): Promise<void> {
    try {
      await fn();
      if (ok) this.game.toast(ok, 'good');
      await this.load();
      const v = this.game.village();
      if (v) await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected choose(): void {
    const v = this.game.village();
    if (v && this.picked()) void this.run(() => this.api.chooseHero(this.picked()!, v.id, ''), 'Your hero has arrived');
  }

  protected spend(skill: 'attack' | 'defense' | 'production'): void {
    void this.run(() => this.api.heroPoints({ [skill]: 1 }));
  }

  protected move(): void {
    if (this.moveTo) void this.run(() => this.api.moveHero(this.moveTo!), 'Your hero is on the way');
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
