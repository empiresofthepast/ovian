import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { GameStore } from '../../core/game.store';
import { SkinService } from '../../core/skin.service';
import { BadgesComponent } from '../../shared/badges';
import { UI } from '../../shared/ui';
import { HubSession } from './hub-session';

/** The hub account: one name for every world, founder status, badges, Patreon and the password. */
@Component({
  selector: 'ov-account',
  imports: [DatePipe, FormsModule, RouterLink, BadgesComponent, ...UI],
  template: `
    <div class="page-head">
      <h1 class="page-title">{{ 'nav.account' | label: 'Account' }}</h1>
      <a class="btn btn--ghost btn--small" routerLink="/worlds">🌍 {{ 'hub.worlds' | label: 'Worlds' }}</a>
    </div>
    @if (!session.hub.token()) {
      <section class="panel">
        <p>{{ 'hub.signed_out' | label: 'You are not signed in to your account.' }}</p>
        <a class="btn btn--primary" routerLink="/worlds">{{ 'login.signin' | label: 'Sign in' }}</a>
      </section>
    } @else if (session.me(); as me) {
      <section class="panel">
        <h2 class="panel__title">{{ me.username }} <ov-badges [badges]="me.badges" [founderNo]="me.founder_no" /></h2>
        <table class="table small">
          @if (me.email) {<tr><th>{{ 'hub.email_short' | label: 'Email' }}</th><td>{{ me.email }}</td></tr>}
          <tr><th>{{ 'hub.member_since' | label: 'Member since' }}</th><td>{{ me.created_at | date: 'mediumDate' }}</td></tr>
          <tr><th>{{ 'hub.founder' | label: 'Founder' }}</th>
            <td>@if (me.founder) {✦ {{ 'hub.founder' | label: 'Founder' }}@if (me.founder_no) { #{{ me.founder_no }}}@if (me.founder_since) {, {{ 'hub.since' | label: 'since' }} {{ me.founder_since | date: 'mediumDate' }}}}
              @else {<span class="muted">—</span>}</td></tr>
          <tr><th>{{ 'hub.worlds' | label: 'Worlds' }}</th><td>{{ me.worlds.length }}</td></tr>
        </table>
        @if (!me.badges.length) {<p class="small muted">{{ 'hub.no_badges' | label: 'No badges yet.' }}</p>}
      </section>

      <section class="panel">
        <h2 class="panel__title">Patreon</h2>
        <p class="small muted">{{ 'hub.patreon_about' | label: 'Supporting Ovian on Patreon earns a badge next to your name, and sometimes early access to new worlds. It gives no advantage in play.' }}</p>
        @if (me.patreon; as p) {
          <p class="small">
            {{ 'hub.patreon_linked_since' | label: 'Linked since' }} {{ p.linked_at | date: 'mediumDate' }} ·
            @if (p.patron_status === 'active_patron') {<span class="good">{{ 'hub.patron_active' | label: 'active patron' }}</span>}
            @else {<span class="muted">{{ p.patron_status ? ('hub.patron.' + p.patron_status | label: p.patron_status) : ('hub.patron_none' | label: 'no pledge') }}</span>}
          </p>
          @if (unlinkArmed()) {
            <div class="btn-row">
              <button class="btn btn--danger btn--small" [disabled]="busy()" (click)="unlink()">{{ 'hub.unlink_confirm' | label: 'Yes, unlink Patreon' }}</button>
              <button class="btn btn--ghost btn--small" (click)="unlinkArmed.set(false)">{{ 'hub.cancel' | label: 'Cancel' }}</button>
            </div>
          } @else {
            <button class="btn btn--small" (click)="unlinkArmed.set(true)">{{ 'hub.unlink' | label: 'Unlink Patreon' }}</button>
          }
        } @else if (me.patreon_enabled) {
          <button class="btn btn--primary" [disabled]="busy()" (click)="connect()">{{ 'hub.patreon_connect' | label: 'Link your Patreon account' }}</button>
        } @else {
          <p class="small muted">{{ 'error.patreon_disabled' | label: 'Patreon is not set up on this site.' }}</p>
        }
      </section>

      <section class="panel">
        <h2 class="panel__title">{{ 'hub.password' | label: 'Change your password' }}</h2>
        <form class="row-form" (ngSubmit)="changePassword()">
          <input name="oldpw" type="password" [(ngModel)]="oldPassword" [placeholder]="'hub.current_password' | label: 'Current password'" aria-label="Current password" autocomplete="current-password" />
          <input name="newpw" type="password" [(ngModel)]="newPassword" [placeholder]="'hub.new_password' | label: 'New password (8 or more)'" aria-label="New password" autocomplete="new-password" minlength="8" />
          <button class="btn" [disabled]="busy() || !oldPassword || newPassword.length < 8">{{ 'hub.change' | label: 'Change' }}</button>
        </form>
        <p class="small muted">{{ 'hub.password_note' | label: 'One password for every world you play through this account.' }}</p>
      </section>
    } @else {
      <p class="muted">Loading…</p>
    }
  `,
})
export class AccountComponent implements OnInit {
  protected readonly session = inject(HubSession);
  private readonly game = inject(GameStore);
  private readonly skin = inject(SkinService);
  protected readonly busy = signal(false);
  protected readonly unlinkArmed = signal(false);
  protected oldPassword = '';
  protected newPassword = '';

  ngOnInit(): void {
    void this.session.load(true);
  }

  protected async connect(): Promise<void> {
    this.busy.set(true);
    try {
      const { url } = await this.session.hub.patreonConnect();
      location.href = url;
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      this.busy.set(false);
    }
  }

  protected async unlink(): Promise<void> {
    this.busy.set(true);
    try {
      await this.session.hub.patreonUnlink();
      this.game.toast(this.skin.label('hub.patreon_unlinked', 'Patreon unlinked.'), 'info');
      await this.session.load(true);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    } finally {
      this.unlinkArmed.set(false);
      this.busy.set(false);
    }
  }

  protected async changePassword(): Promise<void> {
    this.busy.set(true);
    try {
      await this.session.hub.changePassword(this.oldPassword, this.newPassword);
      this.game.toast(this.skin.label('hub.password_changed', 'Your password has been changed.'), 'good');
      this.oldPassword = this.newPassword = '';
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    } finally {
      this.busy.set(false);
    }
  }
}
