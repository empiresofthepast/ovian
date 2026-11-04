import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe } from '@angular/common';
import { Router } from '@angular/router';
import { ADMIN_FILTERS, AdminFilter, ago, filterPlayers } from '../../core/admin';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { AdminPlayer, AdminView } from '../../core/models';

/** Fields the server sends that the shared model may not list yet. */
type Player = AdminPlayer & { bot?: boolean; banned?: boolean; banned_until?: number; ban_reason?: string };
import { UI } from '../../shared/ui';

@Component({
  selector: 'ov-admin',
  imports: [FormsModule, DatePipe, ...UI],
  template: `
    <div class="page-head">
      <h1 class="page-title">{{ 'nav.admin' | label }}</h1>
      <button class="btn btn--ghost btn--small" (click)="load()">↻ Refresh</button>
    </div>
    @if (error()) {<p class="bad">{{ error() }}</p>}
    @if (data(); as d) {
      <div class="admin-totals">
        <div class="panel"><strong>{{ d.totals.online }}</strong><span class="muted">online now</span></div>
        <div class="panel"><strong>{{ d.totals.connected }}</strong><span class="muted">have logged in</span></div>
        <div class="panel"><strong>{{ d.totals.with_own_city }}</strong><span class="muted">with their own city</span></div>
        <div class="panel"><strong>{{ d.totals.players }}</strong><span class="muted">players</span></div>
        <div class="panel"><strong>{{ d.totals.cities }}</strong><span class="muted">cities, {{ d.totals.vassal_cities }} vassals</span></div>
      </div>
      @if (d.world; as w) {
        <section class="panel">
          <h2 class="panel__title">World <span class="muted small">round {{ w.round }} · speed ×{{ w.speed }}</span></h2>
          @if (w.winner; as win) {<p class="small">🏆 {{ win.player.name }} won with {{ win.village.name }}.</p>}
          @if (roundStep() === 0) {
            <button class="btn btn--small" (click)="roundStep.set(1)">New round…</button>
          } @else {
            <div class="confirm">
              <p class="small"><strong>Start round {{ w.round + 1 }}?</strong> The current round goes to the hall of fame and the world is reset:
                every city, army and alliance is gone; players keep their accounts and start again.</p>
              <div class="form__row">
                <label class="field field--short"><span>Speed (optional)</span><input type="number" min="0.1" step="0.1" [(ngModel)]="newSpeed" [placeholder]="w.speed" /></label>
                @if (roundStep() === 1) {
                  <button class="btn btn--small" (click)="roundStep.set(2)">Continue</button>
                } @else {
                  <button class="btn btn--primary btn--small" [disabled]="busy()" (click)="newRound()">Yes, end round {{ w.round }} and reset the world</button>
                }
                <button class="btn btn--ghost btn--small" (click)="roundStep.set(0)">Cancel</button>
              </div>
            </div>
          }
        </section>
      }
      <section class="panel">
        <div class="admin-tools">
          @for (f of filters; track f.id) {
            <button class="btn btn--small" [class.btn--primary]="filter() === f.id" (click)="filter.set(f.id)">{{ f.label }}</button>
          }
          <input class="grow" [ngModel]="query()" (ngModelChange)="query.set($event)" placeholder="Search player or city" aria-label="Search" />
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th></th><th>Player</th><th>Tribe</th><th>Last seen</th><th>Last login</th><th class="num">Logins</th><th>Cities</th><th class="num">Population</th></tr></thead>
            <tbody>
              @for (p of rows(); track p.id) {
                <tr [class.me]="p.id === game.me()?.id">
                  <td><span class="dot" [class.dot--on]="p.online" [title]="p.online ? 'Online' : 'Offline'"></span></td>
                  <td><strong>{{ p.username }}</strong>@if (p.is_admin) {<span class="flag">admin</span>}@if (p.protected) {<span class="flag">protected</span>}@if (p.bot) {<span class="flag" title="AI ruler">🤖 bot</span>}
                    @if (isBanned(p)) {<span class="flag bad" [title]="p.ban_reason || ''">banned@if (p.banned_until) { until {{ p.banned_until | date: 'short' }}}</span>}
                    @if (p.id !== game.me()?.id) {
                      <div class="small">
                        @if (isBanned(p)) {
                          <button class="btn btn--ghost btn--small" (click)="unban(p)">Unban</button>
                        } @else if (banning() === p.id) {
                          <form class="ban-form" (ngSubmit)="ban(p)">
                            <input type="number" name="days" min="0.1" step="0.5" [(ngModel)]="banDays" aria-label="Days" title="Days" />
                            <input name="reason" [(ngModel)]="banReason" maxlength="500" placeholder="Reason" aria-label="Reason" />
                            <button class="btn btn--small" [disabled]="busy()">Ban</button>
                            <button class="btn btn--ghost btn--small" type="button" (click)="banning.set(null)">✕</button>
                          </form>
                        } @else {
                          <button class="btn btn--ghost btn--small" (click)="banning.set(p.id)">Ban…</button>
                        }
                      </div>
                    }
                  </td>
                  <td>{{ p.tribe | name: 'tribe' }}</td>
                  <td>{{ ago(p.last_seen_at) }}</td>
                  <td>{{ ago(p.last_login_at) }}</td>
                  <td class="num">{{ p.logins }}</td>
                  <td>
                    @for (c of p.cities; track c.id) {
                      <div class="small"><a href="" (click)="$event.preventDefault(); view(c.id)" title="Look into this city">{{ c.name }}</a> <span class="muted">({{ c.x }}|{{ c.y }})</span>
                        @if (c.overlord_id) {<span class="bad flag">vassal of {{ c.overlord_name }}</span>}
                        @if (c.vassals) {<span class="flag">{{ c.vassals }} vassal(s)</span>}
                      </div>
                    } @empty {<span class="muted small">no city</span>}
                  </td>
                  <td class="num">{{ p.population }}</td>
                </tr>
              } @empty {<tr><td colspan="8" class="muted">No players match.</td></tr>}
            </tbody>
          </table>
        </div>
        <p class="muted small">Online means seen in the last {{ d.online_window_ms / 60000 }} minutes. Logins are counted since tracking began; earlier players show "never" until they log in again.</p>
      </section>
    } @else if (!error()) {
      <p class="muted">Loading…</p>
    }
  `,
  styles: `
    .admin-totals { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 12px; }
    .admin-totals .panel { display: flex; flex-direction: column; padding: 10px 14px; }
    .admin-totals strong { font-size: 1.6em; }
    .admin-tools { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; align-items: center; }
    .admin-tools input { min-width: 160px; flex: 1; }
    .flag { margin-left: 6px; font-size: 0.85em; opacity: 0.75; }
    .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #9995; }
    .ban-form { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
    .ban-form input[type=number] { width: 4.5rem; }
    .ban-form input:not([type]) { width: 9rem; }
    .dot--on { background: #2e9d4a; box-shadow: 0 0 6px #2e9d4a; }
  `,
})
export class AdminComponent implements OnDestroy {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly filters = ADMIN_FILTERS;
  protected readonly data = signal<AdminView | null>(null);
  protected readonly error = signal('');
  protected readonly filter = signal<AdminFilter>('all');
  protected readonly query = signal('');
  protected readonly rows = computed(() => filterPlayers(this.data()?.players ?? [], this.filter(), this.query()) as Player[]);
  protected readonly roundStep = signal(0);
  protected readonly busy = signal(false);
  protected readonly banning = signal<number | null>(null);
  protected newSpeed: number | null = null;
  protected banDays = 7;
  protected banReason = '';
  private readonly timer = setInterval(() => this.load(), 30_000);

  constructor() {
    void this.load();
  }

  protected async load(): Promise<void> {
    try {
      this.data.set(await this.api.adminPlayers());
      this.error.set('');
    } catch (e) {
      this.error.set(this.game.errorText(e));
    }
  }

  protected async view(id: number): Promise<void> {
    try {
      await this.game.inspect(id);
      await this.router.navigateByUrl('/village');
    } catch (e) {
      this.error.set(this.game.errorText(e));
    }
  }

  protected isBanned(p: Player): boolean {
    return !!p.banned || (p.banned_until ?? 0) > (this.data()?.server_time ?? Date.now());
  }

  private async run(what: () => Promise<unknown>, done: string): Promise<void> {
    this.busy.set(true);
    try {
      await what();
      this.game.toast(done, 'good');
      await this.load();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
    this.busy.set(false);
  }

  protected async ban(p: Player): Promise<void> {
    await this.run(() => this.api.ban(p.id, Number(this.banDays), this.banReason), `${p.username} is banned`);
    this.banning.set(null);
    this.banReason = '';
  }

  protected unban(p: Player): Promise<void> {
    return this.run(() => this.api.unban(p.id), `${p.username} may play again`);
  }

  protected async newRound(): Promise<void> {
    const speed = this.newSpeed ? Number(this.newSpeed) : undefined;
    await this.run(() => this.api.newRound(speed), 'A new round begins');
    this.roundStep.set(0);
  }

  protected ago(at: number | null): string {
    return ago(at, this.data()?.server_time ?? Date.now());
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }
}
