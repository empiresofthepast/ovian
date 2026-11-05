import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, ApiError } from '../../core/api.service';
import { EnterOptions, HubWorld } from '../../core/hub';
import { GameStore } from '../../core/game.store';
import { SkinService } from '../../core/skin.service';
import { BadgesComponent } from '../../shared/badges';
import { UI } from '../../shared/ui';
import { HubSession, patreonNotice } from './hub-session';

type Step = 'tribe' | 'name' | 'link';

interface Entering {
  world: HubWorld;
  step: Step | null;
  opts: EnterOptions;
  tribes: { id: string; name: string; description?: string }[];
}

/**
 * The hub's front door: sign in or register one account for every world, then pick a world.
 * Entering a world for the first time may ask for a people, another name, or the password of a
 * player of the same name who already lives there; then the page reloads into that world.
 */
@Component({
  selector: 'ov-worlds',
  imports: [FormsModule, RouterLink, BadgesComponent, ...UI],
  template: `
    <div class="login">
      <section class="login__card login__card--wide panel">
        <h1 class="login__title"><ov-icon key="app.logo" />{{ 'app.title' | label }}</h1>
        @if (notice(); as n) {<p [class]="n.tone === 'bad' ? 'bad' : n.tone === 'good' ? 'good' : 'muted'" role="status">{{ n.text }}</p>}

        @if (!session.hub.token()) {
          <p class="muted">{{ 'hub.intro' | label: 'One account for every world of Ovian.' }}</p>
          <div class="tabs" role="tablist">
            <button role="tab" class="tabs__tab" [class.tabs__tab--active]="mode() === 'login'" (click)="mode.set('login')">
              {{ 'login.signin' | label: 'Sign in' }}
            </button>
            <button role="tab" class="tabs__tab" [class.tabs__tab--active]="mode() === 'register'" (click)="mode.set('register')">
              {{ 'hub.register' | label: 'Create an account' }}
            </button>
          </div>
          <form class="form" (ngSubmit)="signIn()">
            <label class="field">
              <span>{{ 'login.username' | label: 'Name' }}</span>
              <input name="username" [(ngModel)]="username" autocomplete="username" required minlength="3" maxlength="24" />
            </label>
            <label class="field">
              <span>{{ 'login.password' | label: 'Password' }}</span>
              <input name="password" type="password" [(ngModel)]="password" required minlength="8"
                     [attr.autocomplete]="mode() === 'login' ? 'current-password' : 'new-password'" />
            </label>
            @if (mode() === 'register') {
              <label class="field">
                <span>{{ 'hub.email' | label: 'Email (optional, to recover the account)' }}</span>
                <input name="email" type="email" [(ngModel)]="email" autocomplete="email" maxlength="200" />
              </label>
            }
            @if (error()) {<p class="bad" role="alert">{{ error() }}</p>}
            <button class="btn btn--primary" type="submit" [disabled]="busy()">
              {{ mode() === 'login' ? ('login.signin' | label: 'Sign in') : ('hub.register' | label: 'Create an account') }}
            </button>
          </form>
        } @else if (entering(); as e) {
          <h2 class="panel__title">{{ e.world.name }}</h2>
          @switch (e.step) {
            @case ('tribe') {
              <p class="muted small">{{ 'hub.first_visit' | label: 'Your first visit to this world: choose the people of your first city.' }}</p>
              <form class="form" (ngSubmit)="retry({ tribe: tribe })">
                <fieldset class="tribes">
                  <legend>{{ 'login.tribe' | label: 'Tribe' }}</legend>
                  @for (t of e.tribes; track t.id) {
                    <label class="tribe" [class.tribe--active]="tribe === t.id">
                      <input type="radio" name="tribe" [value]="t.id" [(ngModel)]="tribe" />
                      <ov-icon [key]="'tribe.' + t.id" />
                      <strong>{{ ('tribe.' + t.id) | label: t.name }}</strong>
                      <small class="muted">{{ t.description }}</small>
                    </label>
                  }
                </fieldset>
                @if (error()) {<p class="bad" role="alert">{{ error() }}</p>}
                <div class="btn-row">
                  <button class="btn btn--primary" type="submit" [disabled]="busy() || !tribe">{{ 'login.register' | label: 'Found a village' }}</button>
                  <button class="btn btn--ghost" type="button" (click)="cancel()">{{ 'hub.back' | label: 'Back to the worlds' }}</button>
                </div>
              </form>
            }
            @case ('name') {
              <p class="muted small">{{ 'hub.name_taken' | label: 'Your name is already taken in this world. Choose the name you will have there.' }}</p>
              <form class="form" (ngSubmit)="retry({ username: newName.trim(), password: undefined })">
                <label class="field">
                  <span>{{ 'hub.world_name' | label: 'Name in this world' }}</span>
                  <input name="newname" [(ngModel)]="newName" required minlength="3" maxlength="24" autocomplete="off" />
                </label>
                @if (error()) {<p class="bad" role="alert">{{ error() }}</p>}
                <div class="btn-row">
                  <button class="btn btn--primary" type="submit" [disabled]="busy() || newName.trim().length < 3">{{ 'hub.continue' | label: 'Continue' }}</button>
                  <button class="btn btn--ghost" type="button" (click)="cancel()">{{ 'hub.back' | label: 'Back to the worlds' }}</button>
                </div>
              </form>
            }
            @case ('link') {
              <p class="small">{{ 'hub.link_intro' | label: 'A player called' }} <strong>{{ e.opts.username || session.me()?.username }}</strong>
                {{ 'hub.link_intro2' | label: 'already lives in this world.' }}</p>
              <form class="form" (ngSubmit)="retry({ password: linkPassword })">
                <label class="field">
                  <span>{{ 'hub.link_its_me' | label: 'It is me: enter that player\\'s password to bring it into your account' }}</span>
                  <input name="linkpw" type="password" [(ngModel)]="linkPassword" autocomplete="current-password" />
                </label>
                @if (error()) {<p class="bad" role="alert">{{ error() }}</p>}
                <div class="btn-row">
                  <button class="btn btn--primary" type="submit" [disabled]="busy() || !linkPassword">{{ 'hub.link' | label: 'Link that player' }}</button>
                  <button class="btn" type="button" (click)="step('name')">{{ 'hub.other_name' | label: 'Use another name' }}</button>
                  <button class="btn btn--ghost" type="button" (click)="cancel()">{{ 'hub.back' | label: 'Back to the worlds' }}</button>
                </div>
              </form>
            }
            @default {
              <p class="muted">{{ 'hub.entering' | label: 'Entering the world…' }}</p>
              @if (error()) {
                <p class="bad" role="alert">{{ error() }}</p>
                <button class="btn btn--ghost" type="button" (click)="cancel()">{{ 'hub.back' | label: 'Back to the worlds' }}</button>
              }
            }
          }
        } @else {
          <div class="hub-who">
            @if (session.me(); as me) {
              <span>{{ 'hub.signed_in_as' | label: 'Signed in as' }} <strong>{{ me.username }}</strong></span>
              <ov-badges [badges]="me.badges" [founderNo]="me.founder_no" />
            }
            <span class="grow"></span>
            @if (playing()) {<a class="btn btn--small" routerLink="/village">{{ 'hub.back_to' | label: 'Back to' }} {{ session.world?.name }}</a>}
            <button class="btn btn--ghost btn--small" type="button" (click)="logout()">{{ 'nav.logout' | label: 'Log out' }}</button>
          </div>
          <h2 class="panel__title">{{ 'hub.worlds' | label: 'Worlds' }}</h2>
          @if (error()) {<p class="bad" role="alert">{{ error() }}</p>}
          <div class="worlds">
            @for (w of worlds(); track w.id) {
              <button type="button" class="world-card" [class.world-card--current]="w.id === session.world?.id" [disabled]="busy() || w.can_enter === false"
                      (click)="choose(w)" [attr.aria-describedby]="'world-' + w.id">
                <span class="world-card__head">
                  <strong class="grow">{{ w.name }}</strong>
                  <span class="tag" [class]="'tag world-status world-status--' + w.status">{{ 'hub.status.' + w.status | label: statusText[w.status] }}</span>
                </span>
                @if (w.description) {<span class="small muted" [id]="'world-' + w.id">{{ w.description }}</span>}
                <span class="world-card__meta small">
                  <span>×{{ w.speed }}</span>
                  <span>☺ {{ w.players }} {{ 'hub.players' | label: 'players' }}</span>
                  @if (w.joined) {<span class="chip">✓ {{ 'hub.joined' | label: 'joined' }}</span>}
                  @if (w.id === session.world?.id) {<span class="chip chip--accent">{{ 'hub.playing' | label: 'playing' }}</span>}
                  @if (w.founders_only) {
                    <span class="chip" [title]="'hub.early_access_hint' | label: 'Founders enter first; everyone else when the world opens to all.'">
                      ✦ {{ w.patrons_early ? ('hub.early_founders_patrons' | label: 'Early access: founders and patrons') : ('hub.early_founders' | label: 'Early access: founders') }}
                    </span>
                  }
                </span>
                @if (w.can_enter === false && w.blocked) {<span class="small bad">{{ blockedText(w.blocked) }}</span>}
              </button>
            } @empty {
              @if (loaded()) {<p class="muted">{{ 'hub.no_worlds' | label: 'No worlds are open yet.' }}</p>} @else {<p class="muted">Loading…</p>}
            }
          </div>
        }
      </section>
    </div>
  `,
})
export class WorldsComponent implements OnInit {
  protected readonly session = inject(HubSession);
  private readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly skin = inject(SkinService);
  protected readonly mode = signal<'login' | 'register'>('login');
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly worlds = signal<HubWorld[]>([]);
  protected readonly loaded = signal(false);
  protected readonly entering = signal<Entering | null>(null);
  protected readonly notice = signal<{ text: string; tone: string } | null>(null);
  protected readonly statusText: Record<string, string> = { upcoming: 'Upcoming', open: 'Open', closed: 'Closed to newcomers', ended: 'Ended' };
  protected username = '';
  protected password = '';
  protected email = '';
  protected tribe = '';
  protected newName = '';
  protected linkPassword = '';

  /** A world is being played already (its token is valid): offer the way back. */
  protected readonly playing = () => !!this.session.world && !!this.api.token() && this.game.loggedIn();

  ngOnInit(): void {
    const code = this.session.patreonReturn();
    if (code) {
      const n = patreonNotice(code);
      this.notice.set({ text: this.skin.label(n.key, n.text), tone: n.tone });
    }
    if (this.session.hub.token()) void this.refresh();
  }

  protected async signIn(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      if (this.mode() === 'login') await this.session.hub.login(this.username, this.password);
      else await this.session.hub.register(this.username, this.password, this.email.trim() || undefined);
      this.password = '';
      await this.refresh();
    } catch (e) {
      this.error.set(this.game.errorText(e));
    } finally {
      this.busy.set(false);
    }
  }

  private async refresh(): Promise<void> {
    this.error.set('');
    void this.session.load(true);
    try {
      this.worlds.set(await this.session.hub.myWorlds());
    } catch (e) {
      this.error.set(this.game.errorText(e));
    } finally {
      this.loaded.set(true);
    }
  }

  protected blockedText(code: string): string {
    const fallback: Record<string, string> = {
      world_upcoming: 'This world has not opened yet.',
      world_closed: 'This world is closed to newcomers.',
      world_ended: 'This world has ended.',
      early_access_only: 'Only founders (and patrons, when allowed) can enter this world for now.',
    };
    return this.skin.label(`error.${code}`, fallback[code] ?? code);
  }

  protected choose(world: HubWorld): void {
    this.tribe = '';
    this.newName = '';
    this.linkPassword = '';
    this.entering.set({ world, step: null, opts: {}, tribes: [] });
    void this.attempt();
  }

  /** Try again with more answers (a people, another name, a password). */
  protected retry(more: EnterOptions): void {
    const e = this.entering();
    if (!e) return;
    this.entering.set({ ...e, opts: { ...e.opts, ...more } });
    void this.attempt();
  }

  protected step(step: Step): void {
    const e = this.entering();
    if (e) this.entering.set({ ...e, step, opts: { ...e.opts, password: undefined } });
    this.error.set('');
  }

  protected cancel(): void {
    this.entering.set(null);
    this.error.set('');
  }

  private async attempt(): Promise<void> {
    const e = this.entering();
    if (!e) return;
    this.busy.set(true);
    this.error.set('');
    try {
      await this.session.hub.enter(e.world, e.opts);
      this.session.play();
    } catch (err) {
      const code = err instanceof ApiError ? err.code : '';
      if (code === 'tribe_required') {
        const tribes = e.tribes.length ? e.tribes : await this.session.hub.tribes(e.world).catch(() => []);
        this.tribe ||= tribes[0]?.id ?? '';
        this.entering.set({ ...e, step: 'tribe', tribes, opts: { ...e.opts, tribe: undefined } });
      } else if (code === 'username_taken') {
        if (e.step === 'name') this.error.set(this.game.errorText(err));
        this.entering.set({ ...e, step: 'name', opts: { ...e.opts, username: undefined } });
      } else if (code === 'link_required') {
        if (e.step === 'link') this.error.set(this.game.errorText(err));
        this.entering.set({ ...e, step: 'link', opts: { ...e.opts, password: undefined } });
      } else {
        this.error.set(this.game.errorText(err));
        if (e.step === 'link') this.entering.set({ ...e, opts: { ...e.opts, password: undefined } });
      }
    } finally {
      this.busy.set(false);
    }
  }

  protected logout(): void {
    this.game.logout();
    this.session.logout();
  }
}
