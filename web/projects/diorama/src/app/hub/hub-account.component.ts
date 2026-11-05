import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiError } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { Hub, HubMe } from '@core/hub';
import { UI } from '../ui';

/** Settings: the hub account behind this player (founder, badges, Patreon, password). */
@Component({
  selector: 'dio-hub-account',
  imports: [DatePipe, DecimalPipe, RouterLink, ...UI],
  template: `
    <h3 class="subhead">Your Ovian account</h3>
    @if (expired()) {
      <p class="small muted">Your account session has ended. <a routerLink="/worlds">Sign in again</a> to see it, or to change world.</p>
    } @else if (me(); as m) {
      <div class="hub-card">
        <div class="hub-card__who">
          <strong>{{ m.username }}</strong>
          @if (m.founder) {<span class="tag" [title]="m.founder_since ? 'Since ' + (m.founder_since | date: 'd MMM y') : 'Founder'">Founder #{{ m.founder_no }}</span>}
          @if (m.patron) {<span class="tag">Patron</span>}
        </div>
        @if (m.badges.length) {<dio-badges [badges]="m.badges" [founderNo]="m.founder_no" [named]="true" />}
        @else {<p class="small muted">No badges yet.</p>}
        <p class="small muted">Badges are honours only: they show beside your name in every world and never change the game.</p>
      </div>

      @if (m.patreon_enabled || m.patreon) {
        <h3 class="subhead">Patreon</h3>
        @if (m.patreon; as p) {
          <p class="small">Linked since {{ p.linked_at | date: 'd MMM y' }}.
            @if (p.patron_status === 'active_patron') {<span class="good">Supporting Ovian@if (p.cents) {, {{ p.cents / 100 | number: '1.2-2' }} a month}. Thank you!</span>}
            @else {<span class="muted">No active pledge.</span>}
          </p>
          <button class="btn btn--small" type="button" [disabled]="busy()" (click)="unlink()">Unlink Patreon</button>
        } @else {
          <p class="small muted">Supporters get patron badges and, for some new worlds, the chance to enter a little before everyone else. Nothing that helps in play.</p>
          <button class="btn btn--small" type="button" [disabled]="busy()" (click)="connect()">Link your Patreon</button>
        }
      }

      <h3 class="subhead">Account password</h3>
      <form class="row-form" (submit)="$event.preventDefault(); changePassword()">
        <input name="hubpw" type="password" [value]="oldPw" (input)="oldPw = $any($event.target).value" placeholder="Current password" aria-label="Current password" autocomplete="current-password" />
        <input name="hubnew" type="password" [value]="newPw" (input)="newPw = $any($event.target).value" placeholder="New password (8+)" aria-label="New password" autocomplete="new-password" />
        <button class="btn btn--small" [disabled]="busy() || !oldPw || newPw.length < 8">Change</button>
      </form>
      @if (m.is_admin) {
        <div class="btn-row"><a class="btn btn--small" routerLink="/hub-admin">⚿ Hub administration</a></div>
      }
    } @else if (error()) {
      <p class="small bad">{{ error() }}</p>
    } @else {
      <p class="small muted">Loading…</p>
    }
  `,
})
export class HubAccountComponent implements OnInit {
  private readonly hub = inject(Hub);
  private readonly game = inject(GameStore);
  protected readonly me = signal<HubMe | null>(null);
  protected readonly error = signal('');
  protected readonly expired = signal(!this.hub.token());
  protected readonly busy = signal(false);
  protected oldPw = '';
  protected newPw = '';

  ngOnInit(): void {
    if (this.hub.token()) void this.load();
  }

  private async load(): Promise<void> {
    try {
      this.me.set(await this.hub.me());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) this.expired.set(true);
      else this.error.set(this.game.errorText(e));
    }
  }

  protected async connect(): Promise<void> {
    this.busy.set(true);
    try {
      const { url } = await this.hub.patreonConnect();
      location.href = url;
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      this.busy.set(false);
    }
  }

  protected async unlink(): Promise<void> {
    this.busy.set(true);
    try {
      await this.hub.patreonUnlink();
      this.game.toast('Patreon unlinked', 'info');
      await this.load();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    } finally {
      this.busy.set(false);
    }
  }

  protected async changePassword(): Promise<void> {
    this.busy.set(true);
    try {
      await this.hub.changePassword(this.oldPw, this.newPw);
      this.game.toast('Password changed', 'good');
      this.oldPw = this.newPw = '';
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    } finally {
      this.busy.set(false);
    }
  }
}
