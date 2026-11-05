import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { CONFIG, selectedWorld } from '@core/config';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { Hub } from '@core/hub';
import { RealtimeService } from '@core/realtime.service';
import { ArtService } from '../art/art.service';
import { PrefsService, ScenePrefs } from '../prefs.service';
import { UI } from '../ui';
import { HubAccountComponent } from '../hub/hub-account.component';
import { AssistantsComponent } from './assistants.component';

@Component({
  selector: 'dio-settings',
  imports: [AssistantsComponent, HubAccountComponent, ...UI],
  template: `
    <section class="hud-panel dialog settings" role="dialog" aria-label="Settings">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Settings</h2>
      <div class="settings__cols">
        <div>
          <h3 class="subhead">Display</h3>
          <div class="opt">
            <span>Quality</span>
            <div class="seg" role="radiogroup" aria-label="Quality">
              @for (q of qualities; track q.id) {
                <button type="button" role="radio" class="seg__opt" [class.seg__opt--on]="prefs.scene().quality === q.id" [attr.aria-checked]="prefs.scene().quality === q.id" (click)="prefs.set('quality', q.id)">{{ q.label }}</button>
              }
            </div>
          </div>
          @for (t of toggles; track t.id) {
            <label class="opt">
              <span>{{ t.label }} <small class="muted">{{ t.hint }}</small></span>
              <input type="checkbox" class="switch" [checked]="prefs.scene()[t.id]" (change)="toggle(t.id, $event)" />
            </label>
          }
          <h3 class="subhead">Controls</h3>
          <dl class="effects small">
            <dt>Drag</dt><dd>pan</dd>
            <dt>Right-drag, Q / E</dt><dd>turn</dd>
            <dt>Wheel</dt><dd>zoom</dd>
            <dt>C M R T H L Q</dt><dd>city, map, rally point, market, hero, alliance, quests</dd>
            <dt>G Y N</dt><dd>realm, year &amp; games, chronicle</dd>
            <dt>P K O</dt><dd>reports, rankings, settings</dd>
            <dt>Esc</dt><dd>close a screen or the selection</dd>
          </dl>
        </div>
        <div>
          <h3 class="subhead">This world</h3>
          @if (hub.enabled) {
            <div class="world-switch">
              <span class="grow"><strong>{{ worldName }}</strong></span>
              <button class="btn btn--small" type="button" (click)="switchWorld()">⇄ Switch world</button>
            </div>
          }
          @if (game.world(); as w) {
            <dl class="effects small">
              <dt>World</dt><dd>{{ w.id }}</dd>
              <dt>Rules</dt><dd>{{ w.pack.name }} {{ w.pack.version }}</dd>
              <dt>Speed</dt><dd>×{{ w.speed }}</dd>
              <dt>Size</dt><dd>{{ w.width }} × {{ w.height }}</dd>
              <dt>Engine</dt><dd>{{ engine.wasm() ? 'WebAssembly, same rules as the server' : 'fallback, the server checks orders' }}</dd>
              <dt>Realtime</dt><dd>{{ realtime.status() }}</dd>
            </dl>
          }
          @if (game.me(); as me) {
            <h3 class="subhead">Vacation</h3>
            @if ((me.vacation_until ?? 0) > game.now()) {
              <p class="small">On vacation for another {{ me.vacation_until! - game.now() | dur: 'ms' }}. Nobody can attack you, and you cannot give orders.</p>
              <button class="btn btn--small" (click)="endVacation()">End the vacation</button>
            } @else {
              <p class="small muted">While away, nobody can attack, raid or scout your cities, and you cannot give orders. 12 hours to 14 days; production goes on.</p>
              <div class="row-form">
                <input type="number" min="12" max="336" [value]="vacationHours" (input)="vacationHours = +$any($event.target).value" aria-label="Hours" style="max-width: 90px" /> hours
                <button class="btn btn--small" (click)="startVacation()">Go on vacation</button>
              </div>
            }
            <h3 class="subhead">Tutorial</h3>
            <label class="small"><input type="checkbox" [checked]="me.tutorial !== false" (change)="setTutorial($any($event.target).checked)" /> Show the next step in the city</label>
            <h3 class="subhead">Your account</h3>
            <div class="account">
              @if (emblem()) {<img class="emblem" [src]="emblem()" alt="" />}
              <div class="small">
                <strong>{{ me.username }}</strong>, {{ civName() }}
                @if (me.badges?.length) {<br /><dio-badges [badges]="me.badges" [founderNo]="me.founder_no" [named]="true" />}
                @if (me.protected_until > game.now()) {<br /><span class="muted">Beginner protection for {{ me.protected_until - game.now() | dur: 'ms' }}</span>}
              </div>
            </div>
            <h3 class="subhead">Change your name</h3>
            @if (me.account_id) {
              <p class="small muted">Your name comes from your Ovian account, the same in every world.</p>
            } @else if ((me.rename_ready_at ?? 0) > game.now()) {
              <p class="small muted">You can change your name again in {{ me.rename_ready_at! - game.now() | dur: 'ms' }}.</p>
            } @else {
              <form class="row-form" (submit)="$event.preventDefault(); rename()">
                <input name="newname" [value]="newName" (input)="newName = $any($event.target).value" placeholder="New name" aria-label="New name" maxlength="24" autocomplete="username" />
                <input name="pw" type="password" [value]="password" (input)="password = $any($event.target).value" placeholder="Your password" aria-label="Your password" autocomplete="current-password" />
                <button class="btn btn--small" [disabled]="busy || newName.trim().length < 3 || !password">Change name</button>
              </form>
              <p class="small muted">3 to 24 letters, digits, _ or -. You log in with the new name; cities still called “{{ me.username }}'s village” follow it. Once every few days.</p>
            }
            @if (me.former_names?.length) {<p class="small muted">Formerly: {{ me.former_names!.join(', ') }}</p>}
            <details class="danger-zone">
              <summary>Delete your account</summary>
              <p class="small">@if (me.account_id) {This deletes your player in this world only; your Ovian account and your other worlds stay. }This cannot be undone. Your cities leave the map with everything in them, and your reports, messages and achievements are deleted.
                Cities you hold as vassals go free; troops of other players in your cities, or marching on them, go home; your alliance passes to the next member.</p>
              <form class="row-form" (submit)="$event.preventDefault(); deleteAccount()">
                <input name="delconfirm" [value]="delConfirm" (input)="delConfirm = $any($event.target).value" [placeholder]="'Type ' + me.username" aria-label="Type your username to confirm" autocomplete="off" />
                @if (!me.account_id) {<input name="delpw" type="password" [value]="delPassword" (input)="delPassword = $any($event.target).value" placeholder="Your password" aria-label="Your password" autocomplete="current-password" />}
                <button class="btn btn--small btn--danger" [disabled]="busy || (!delPassword && !me.account_id) || delConfirm.trim().toLowerCase() !== me.username.toLowerCase()">{{ delArmed ? 'Really delete, for good' : 'Delete account' }}</button>
              </form>
              @if (delArmed) {<p class="small bad">Press again to delete {{ me.username }} and all its cities. <button type="button" class="linkbtn" (click)="delArmed = false">Cancel</button></p>}
            </details>
          }
          @if (hub.enabled) {<dio-hub-account />}
          <dio-assistants />
          <div class="btn-row">
            @if (ledgerUrl) {<a class="btn btn--small" [href]="ledgerUrl">Open the ledger view</a>}
            <button class="btn btn--small" (click)="logout()">Leave the game</button>
          </div>
          <p class="small muted credits">3D art from <a href="https://play0ad.com" target="_blank" rel="noopener">0 A.D.</a> by Wildfire Games, CC BY-SA 3.0.</p>
        </div>
      </div>
    </section>
  `,
})
export class SettingsComponent {
  protected vacationHours = 24;
  protected newName = '';
  protected password = '';
  protected busy = false;

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
  private readonly api = inject(Api);

  protected async setTutorial(on: boolean): Promise<void> {
    await this.api.tutorial(on);
    this.game.me.update((m) => m && { ...m, tutorial: on });
  }

  protected async startVacation(): Promise<void> {
    try {
      await this.api.vacation(this.vacationHours);
      await this.game.refreshMe();
      this.game.toast('Enjoy your vacation', 'good');
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected async endVacation(): Promise<void> {
    try {
      await this.api.endVacation();
      await this.game.refreshMe();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected readonly prefs = inject(PrefsService);
  protected readonly game = inject(GameStore);
  protected readonly engine = inject(EngineService);
  protected readonly realtime = inject(RealtimeService);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  protected readonly ledgerUrl = inject(CONFIG).ledgerUrl ?? '';
  protected readonly hub = inject(Hub);
  protected readonly worldName = selectedWorld()?.name ?? this.hub.worldId ?? 'this world';
  protected readonly qualities: { id: ScenePrefs['quality']; label: string }[] = [
    { id: 'low', label: 'Low' }, { id: 'medium', label: 'Medium' }, { id: 'high', label: 'High' },
  ];
  protected readonly toggles: { id: 'shadows' | 'badges' | 'decor'; label: string; hint: string }[] = [
    { id: 'shadows', label: 'Shadows', hint: 'the heaviest effect' },
    { id: 'badges', label: 'Level badges', hint: 'numbers above buildings' },
    { id: 'decor', label: 'Forest', hint: 'trees around the city' },
  ];

  protected emblem(): string | null {
    return this.art.url(this.art.civ(this.game.me()?.tribe)?.emblem);
  }

  protected civName(): string {
    const t = this.game.me()?.tribe;
    return this.engine.pack()?.tribes.find((x) => x.id === t)?.name ?? t ?? '';
  }

  protected toggle(id: 'shadows' | 'badges' | 'decor', e: Event): void {
    this.prefs.set(id, (e.target as HTMLInputElement).checked);
  }

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
      void this.router.navigateByUrl('/welcome');
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      this.delArmed = false;
    } finally {
      this.busy = false;
      this.delPassword = '';
    }
  }

  protected logout(): void {
    if (this.hub.enabled) this.hub.logout();
    this.game.logout();
    void this.router.navigateByUrl('/welcome');
  }

  protected switchWorld(): void {
    void this.router.navigateByUrl('/worlds');
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
