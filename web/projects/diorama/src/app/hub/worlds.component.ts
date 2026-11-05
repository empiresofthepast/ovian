import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiError } from '@core/api.service';
import { CONFIG, selectedWorld } from '@core/config';
import { GameStore } from '@core/game.store';
import { EnterOptions, Hub, HubMe, HubWorld } from '@core/hub';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';
import { HubSigninComponent } from './hub-signin.component';

const BLOCKED: Record<string, string> = {
  world_upcoming: 'Not open yet',
  world_closed: 'Closed to newcomers',
  world_ended: 'This world has ended',
  early_access_only: 'Early access for founders and patrons only',
};

const STATUS: Record<string, string> = { upcoming: 'Soon', open: 'Open', closed: 'Closed', ended: 'Ended' };

type Step = 'tribe' | 'name' | 'link';

/** The hub's landing: sign in, then pick the world to play. Entering one reloads the page on it. */
@Component({
  selector: 'dio-worlds',
  imports: [DatePipe, FormsModule, RouterLink, HubSigninComponent, ...UI],
  template: `
    <main class="welcome">
      <header class="welcome__head">
        <h1 class="welcome__title">Ovian</h1>
        <p class="welcome__sub">@if (hub.token()) {Choose a world. Each one is its own age: its own map, its own peoples, its own ending.} @else {One account for every world.}</p>
      </header>

      @if (!hub.token()) {
        <section class="hud-panel welcome__panel hub-signin">
          <dio-hub-signin (signedIn)="load()" />
        </section>
      } @else {
        <section class="worlds">
          <div class="worlds__bar">
            @if (me(); as m) {
              <span class="worlds__who"><strong>{{ m.username }}</strong>
                @if (m.founder) {<span class="tag">Founder #{{ m.founder_no }}</span>}
                <dio-badges [badges]="m.badges" [founderNo]="m.founder_no" /></span>
            }
            <span class="grow"></span>
            @if (game.loggedIn() && current()) {<a class="btn btn--small" routerLink="/">Back to {{ current()!.name }}</a>}
            <button class="btn btn--small" type="button" (click)="load()" title="Refresh">↻</button>
            <button class="btn btn--small" type="button" (click)="logout()">Sign out</button>
          </div>
          @if (error()) {<p class="bad">{{ error() }}</p>}
          @if (worlds() === null) {<p class="muted">Loading the worlds…</p>}
          <div class="worlds__grid">
            @for (w of cards(); track w.id) {
              <article class="world hud-panel" [class.world--off]="!w.can_enter" [class.world--here]="w.here" [attr.data-status]="w.status">
                <div class="world__head">
                  <h2 class="world__name">{{ w.name }}</h2>
                  <span class="world__status">{{ w.statusLabel }}</span>
                </div>
                @if (w.description) {<p class="world__desc small">{{ w.description }}</p>}
                <div class="world__facts small">
                  <span title="World speed">⚡ ×{{ w.speed }}</span>
                  <span title="Players">♟ {{ w.players }} {{ w.players === 1 ? 'player' : 'players' }}</span>
                  @if (w.starts_at) {<span title="Opens">☀ {{ w.starts_at | date: 'd MMM y' }}</span>}
                  @if (w.ends_at) {<span title="Ends">☾ {{ w.ends_at | date: 'd MMM y' }}</span>}
                </div>
                <div class="world__tags">
                  @if (w.here) {<span class="tag">You are here</span>}
                  @else if (w.joined) {<span class="tag">Your city is here</span>}
                  @if (w.founders_only) {<span class="tag tag--early" title="Open to founders before everyone else">✦ Founders' early access</span>}
                  @else if (w.patrons_early) {<span class="tag tag--early" title="Founders and patrons may enter before everyone else">✦ Early access</span>}
                </div>
                <div class="world__foot">
                  @if (w.can_enter) {
                    <button class="btn" [class.btn--gold]="!w.here" type="button" [disabled]="busy()" (click)="choose(w)">{{ w.here ? 'Play' : w.joined ? 'Enter' : 'Join this world' }}</button>
                  } @else {
                    <span class="small muted">{{ w.reason }}</span>
                  }
                </div>
              </article>
            } @empty {
              @if (worlds() !== null) {<p class="muted">No world is open at the moment.</p>}
            }
          </div>
        </section>
      }

      @if (entering(); as w) {
        <div class="enter-backdrop" (click)="cancel()"></div>
        <section class="hud-panel enter" role="dialog" [attr.aria-label]="'Enter ' + w.name">
          <button class="close" type="button" (click)="cancel()" aria-label="Close">✕</button>
          <h2 class="selection__title">{{ w.name }}</h2>
          @if (step() === 'tribe') {
            <p class="small muted">Your first city in this world. Choose the people who found it.</p>
            <fieldset class="civs">
              <legend>Civilization</legend>
              <div class="civs__grid">
                @for (t of tribes(); track t.id) {
                  <button type="button" class="civ" [class.civ--on]="tribe() === t.id" (click)="tribe.set(t.id)" [attr.aria-pressed]="tribe() === t.id" [title]="t.name">
                    @if (t.emblem) {<img [src]="t.emblem" alt="" />}
                    <span>{{ t.name }}</span>
                  </button>
                } @empty {<p class="muted small">Loading the peoples…</p>}
              </div>
              @if (chosenTribe(); as c) {
                <div class="civ-info"><h3 class="subhead">{{ c.name }}</h3>@if (c.description) {<p class="small">{{ c.description }}</p>}</div>
              }
            </fieldset>
            <button class="btn btn--gold btn--wide" type="button" [disabled]="busy() || !tribe()" (click)="go({ tribe: tribe()! })">Found the city</button>
          } @else if (step() === 'name') {
            <p class="small">The name <strong>{{ opts().username || me()?.username }}</strong> is taken in this world. Choose the name you will carry here.</p>
            <form class="welcome__form" (ngSubmit)="go({ username: newName.trim() })">
              <label>Name in {{ w.name }} <input name="wn" [(ngModel)]="newName" required minlength="3" maxlength="24" autocomplete="off" /></label>
              <button class="btn btn--gold btn--wide" [disabled]="busy() || newName.trim().length < 3">Continue</button>
            </form>
          } @else if (step() === 'link') {
            <p class="small">A player called <strong>{{ me()?.username }}</strong> already lives in this world. Is it you?</p>
            <form class="welcome__form" (ngSubmit)="go({ password: linkPassword })">
              <label>Yes: that player's password <input name="lp" type="password" [(ngModel)]="linkPassword" required autocomplete="current-password" /></label>
              <button class="btn btn--gold btn--wide" [disabled]="busy() || !linkPassword">It's me: link my account</button>
            </form>
            <p class="small muted enter__or">or</p>
            <button class="btn btn--wide" type="button" (click)="step.set('name')">No, I'll take another name</button>
          } @else {
            <p class="muted">Opening the gates…</p>
          }
          @if (stepError()) {<p class="bad">{{ stepError() }}</p>}
        </section>
      }

      <footer class="welcome__foot small muted">
        Art from <a href="https://play0ad.com" target="_blank" rel="noopener">0 A.D.</a> by Wildfire Games, CC BY-SA 3.0.
        @if (ledgerUrl) { · <a [href]="ledgerUrl">Ledger view</a>}
      </footer>
    </main>
  `,
})
export class WorldsComponent implements OnInit {
  protected readonly hub = inject(Hub);
  protected readonly game = inject(GameStore);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  protected readonly ledgerUrl = inject(CONFIG).ledgerUrl ?? '';
  protected readonly me = signal<HubMe | null>(null);
  protected readonly worlds = signal<HubWorld[] | null>(null);
  protected readonly error = signal('');
  protected readonly busy = signal(false);
  protected readonly current = signal(selectedWorld());

  protected readonly entering = signal<HubWorld | null>(null);
  protected readonly step = signal<Step | null>(null);
  protected readonly stepError = signal('');
  protected readonly opts = signal<EnterOptions>({});
  protected readonly tribes = signal<{ id: string; name: string; description?: string; emblem: string | null }[]>([]);
  protected readonly tribe = signal<string | null>(null);
  protected readonly chosenTribe = computed(() => this.tribes().find((t) => t.id === this.tribe()) ?? null);
  protected newName = '';
  protected linkPassword = '';

  protected readonly cards = computed(() =>
    (this.worlds() ?? []).map((w) => ({
      ...w,
      here: this.game.loggedIn() && w.id === this.hub.worldId,
      statusLabel: STATUS[w.status] ?? w.status,
      reason: (w.blocked && BLOCKED[w.blocked]) || 'Closed',
    })),
  );

  ngOnInit(): void {
    if (this.hub.token()) void this.load();
  }

  protected async load(): Promise<void> {
    this.error.set('');
    try {
      const [me, worlds] = await Promise.all([this.hub.me(), this.hub.myWorlds()]);
      this.me.set(me);
      this.worlds.set(worlds);
    } catch (e) {
      this.error.set(this.game.errorText(e));
    }
  }

  protected logout(): void {
    this.hub.logout();
    this.game.logout();
    this.me.set(null);
    this.worlds.set(null);
    this.current.set(null);
  }

  protected choose(w: HubWorld): void {
    if (this.game.loggedIn() && w.id === this.hub.worldId) {
      void this.router.navigateByUrl('/');
      return;
    }
    this.entering.set(w);
    this.step.set(null);
    this.stepError.set('');
    this.opts.set({});
    this.tribe.set(null);
    this.newName = this.linkPassword = '';
    void this.go({});
  }

  protected cancel(): void {
    if (this.busy()) return;
    this.entering.set(null);
    this.step.set(null);
  }

  /** Try to enter with what we know so far; the world tells us what is missing. */
  protected async go(more: EnterOptions): Promise<void> {
    const w = this.entering();
    if (!w) return;
    const opts = { ...this.opts(), ...more };
    this.opts.set(opts);
    this.busy.set(true);
    this.stepError.set('');
    try {
      await this.hub.enter(w, opts);
      location.assign(document.baseURI);
      return;
    } catch (e) {
      const code = e instanceof ApiError ? e.code : '';
      if (code === 'tribe_required') {
        this.step.set('tribe');
        void this.loadTribes(w);
      } else if (code === 'username_taken') {
        this.opts.set({ ...opts, password: undefined });
        if (this.step() === 'name') this.stepError.set(this.game.errorText(e));
        this.step.set('name');
      } else if (code === 'link_required') {
        this.step.set('link');
      } else {
        // a wrong link password: ask again, without it
        if (opts.password) this.opts.set({ ...opts, password: undefined });
        if (!this.step()) {
          this.entering.set(null);
          this.game.toast(this.game.errorText(e), 'bad');
        } else this.stepError.set(this.game.errorText(e));
      }
    } finally {
      this.busy.set(false);
    }
  }

  private async loadTribes(w: HubWorld): Promise<void> {
    if (this.tribes().length && this.tribesOf === w.id) return;
    this.tribes.set([]);
    try {
      const list = await this.hub.tribes(w);
      this.tribesOf = w.id;
      this.tribes.set(list.map((t) => ({ ...t, emblem: this.art.url(this.art.civ(t.id)?.emblem) })));
      this.tribe.set(this.tribe() ?? list[0]?.id ?? null);
    } catch (e) {
      this.stepError.set(this.game.errorText(e));
    }
  }
  private tribesOf = '';
}
