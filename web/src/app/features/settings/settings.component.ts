import { Router } from '@angular/router';
import { Component, inject } from '@angular/core';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { RealtimeService } from '../../core/realtime.service';
import { SkinService } from '../../core/skin.service';
import { UI } from '../../shared/ui';
import { AssistantsComponent } from './assistants.component';
import { RouterLink } from '@angular/router';
import { Hub } from '../../core/hub';
import { BadgesComponent } from '../../shared/badges';

@Component({
  selector: 'ov-settings',
  imports: [AssistantsComponent, RouterLink, BadgesComponent, ...UI],
  template: `
    <div class="page-head"><h1 class="page-title">{{ 'nav.settings' | label }}</h1></div>
    <section class="panel">
      <h2 class="panel__title">{{ 'settings.skin' | label: 'Skin' }}</h2>
      <div class="skins">
        @for (s of skin.available(); track s.id) {
          <button class="skin-card" [class.skin-card--active]="skin.skin()?.id === s.id" (click)="skin.use(s.id)" [attr.aria-pressed]="skin.skin()?.id === s.id">
            <span class="skin-card__swatches">
              @for (c of s.swatches ?? []; track $index) {<i [style.background]="c"></i>}
            </span>
            <strong>{{ s.name }}</strong>
            <small class="muted">{{ s.description }}</small>
            @if (s.author) {<small class="muted">by {{ s.author }}</small>}
          </button>
        }
      </div>
    </section>
    <section class="panel">
      <h2 class="panel__title">{{ 'settings.about' | label: 'About this world' }}</h2>
      @if (game.world(); as w) {
        <table class="table small">
          <tr><th>World</th><td>{{ w.id }}</td></tr>
          <tr><th>Rules</th><td>{{ w.pack.name }} {{ w.pack.version }}</td></tr>
          <tr><th>Speed</th><td>×{{ w.speed }}</td></tr>
          <tr><th>Size</th><td>{{ w.width }} × {{ w.height }}</td></tr>
          <tr><th>Engine</th><td>{{ engine.wasm() ? 'WebAssembly (same rules as the server)' : 'fallback (server validates)' }}</td></tr>
          <tr><th>Realtime</th><td>{{ realtime.status() }}</td></tr>
        </table>
      }
      @if (game.me(); as me) {
        <p class="small muted">Signed in as {{ me.username }} <ov-badges [badges]="me.badges" [founderNo]="me.founder_no" /> ({{ me.tribe | name: 'tribe' }}).
          @if (me.protected_until > game.now()) { Beginner protection for {{ me.protected_until - game.now() | duration }}. }
        </p>
      }
    </section>
    @if (game.me(); as me) {
      <section class="panel">
        <h2 class="panel__title">{{ 'settings.rename' | label: 'Change your name' }}</h2>
        @if (me.account_id) {
          <p class="small muted">{{ 'error.rename_on_hub' | label: 'Your name comes from your account on the hub: change it there.' }}
            @if (hubEnabled) {<a routerLink="/account">{{ 'nav.account' | label: 'Account' }}</a>}</p>
        } @else if ((me.rename_ready_at ?? 0) > game.now()) {
          <p class="small muted">You can change your name again in {{ me.rename_ready_at! - game.now() | duration }}.</p>
        } @else {
          <form class="row-form" (submit)="$event.preventDefault(); rename()">
            <input name="newname" [value]="newName" (input)="newName = $any($event.target).value" placeholder="New name" aria-label="New name" maxlength="24" autocomplete="username" />
            <input name="pw" type="password" [value]="password" (input)="password = $any($event.target).value" placeholder="Your password" aria-label="Your password" autocomplete="current-password" />
            <button class="btn" [disabled]="busy || newName.trim().length < 3 || !password">Change name</button>
          </form>
          <p class="small muted">3 to 24 letters, digits, _ or -. You log in with the new name; cities still called “{{ me.username }}'s village” follow it. Once every few days.</p>
        }
        @if (me.former_names?.length) {<p class="small muted">Formerly: {{ me.former_names!.join(', ') }}</p>}
      </section>
      <section class="panel">
      <details class="danger-zone">
        <summary>{{ me.account_id ? 'Leave this world' : 'Delete your account' }}</summary>
        @if (me.account_id) {<p class="small muted">Only your player in this world is deleted; your hub account and your other worlds stay.</p>}
        <p class="small">This cannot be undone. Your cities leave the map with everything in them, and your reports, messages and achievements are deleted.
          Cities you hold as vassals go free; troops of other players in your cities, or marching on them, go home; your alliance passes to the next member.</p>
        <form class="row-form" (submit)="$event.preventDefault(); deleteAccount()">
          <input name="delconfirm" [value]="delConfirm" (input)="delConfirm = $any($event.target).value" [placeholder]="'Type ' + me.username" aria-label="Type your username to confirm" autocomplete="off" />
          @if (!me.account_id) {
            <input name="delpw" type="password" [value]="delPassword" (input)="delPassword = $any($event.target).value" placeholder="Your password" aria-label="Your password" autocomplete="current-password" />
          }
          <button class="btn  btn--danger" [disabled]="busy || (!delPassword && !me.account_id) || delConfirm.trim().toLowerCase() !== me.username.toLowerCase()">{{ delArmed ? 'Really delete, for good' : 'Delete account' }}</button>
        </form>
        @if (delArmed) {<p class="small bad">Press again to delete {{ me.username }} and all its cities. <button type="button" class="linkbtn" (click)="delArmed = false">Cancel</button></p>}
      </details>
      </section>
      <ov-assistants />
    }
  `,
})
export class SettingsComponent {
  protected readonly skin = inject(SkinService);
  private readonly router = inject(Router);
  protected readonly game = inject(GameStore);
  protected readonly engine = inject(EngineService);
  protected readonly realtime = inject(RealtimeService);
  protected readonly hubEnabled = inject(Hub).enabled;
  protected newName = '';
  protected password = '';
  protected busy = false;

  protected delPassword = '';
  protected delConfirm = '';
  protected delArmed = false;

  protected async deleteAccount(): Promise<void> {
    if (!this.delArmed) {
      this.delArmed = true;
      return;
    }
    this.busy = true;
    try {
      await this.game.deleteAccount(this.delPassword, this.delConfirm.trim());
      this.game.toast('Your account has been deleted. Farewell.', 'info');
      void this.router.navigateByUrl('/');
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      this.delArmed = false;
    } finally {
      this.busy = false;
      this.delPassword = '';
    }
  }

  protected async rename(): Promise<void> {
    this.busy = true;
    try {
      await this.game.changeUsername(this.newName.trim(), this.password);
      this.game.toast(`You are now ${this.game.me()?.username}`, 'good');
      this.newName = this.password = '';
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    } finally {
      this.busy = false;
    }
  }
}
