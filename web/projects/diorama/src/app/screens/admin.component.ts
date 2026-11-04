import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ADMIN_FILTERS, AdminFilter, ago, filterPlayers } from '@core/admin';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { AdminView } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

@Component({
  selector: 'dio-admin',
  imports: [...UI],
  template: `
    <section class="hud-panel dialog admin" role="dialog" aria-label="Admin">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Admin <span class="muted small">· players and their cities@if (data()?.world; as w) { · round {{ w.round }}, speed {{ w.speed }}}</span></h2>
      @if (error()) {<p class="bad">{{ error() }}</p>}
      @if (data(); as d) {
        <div class="admin__totals">
          <div><strong>{{ d.totals.online }}</strong><span>online now</span></div>
          <div><strong>{{ d.totals.connected }}</strong><span>have logged in</span></div>
          <div><strong>{{ d.totals.with_own_city }}</strong><span>with their own city</span></div>
          <div><strong>{{ d.totals.players }}</strong><span>players</span></div>
          <div><strong>{{ d.totals.cities }}</strong><span>cities · {{ d.totals.vassal_cities }} vassals</span></div>
        </div>
        <div class="admin__tools">
          @for (f of filters; track f.id) {
            <button class="btn btn--small" [class.btn--gold]="filter() === f.id" (click)="filter.set(f.id)">{{ f.label }}</button>
          }
          <input [value]="query()" (input)="query.set($any($event.target).value)" placeholder="Search player or city" aria-label="Search" />
          <button class="btn btn--small" (click)="load()" title="Refresh">↻</button>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th></th><th>Player</th><th>Civilization</th><th>Last seen</th><th>Last login</th><th class="num">Logins</th><th>Cities</th><th class="num">Population</th></tr></thead>
            <tbody>
              @for (p of rows(); track p.id) {
                <tr [class.me]="p.id === game.me()?.id">
                  <td><span class="dot" [class.dot--on]="p.online" [title]="p.online ? 'Online' : 'Offline'"></span></td>
                  <td><strong>{{ p.username }}</strong>@if (p.is_admin) {<span class="tag">admin</span>}@if (p.protected) {<span class="tag">protected</span>}@if ($any(p).bot) {<span class="tag" title="AI ruler">🤖 bot</span>}
                    @if ($any(p).banned) {<span class="tag tag--bad" [title]="$any(p).ban_reason">banned</span>}
                    @if (p.id !== game.me()?.id) {
                      @if ($any(p).banned) {<button class="linkbtn small" (click)="unban(p.id)">unban</button>}
                      @else if (banning() === p.id) {
                        <span class="row-form small"><input type="number" min="1" [value]="banDays()" (input)="banDays.set(+$any($event.target).value)" aria-label="Days" style="width:4em" /> days
                          <input [value]="banReason()" (input)="banReason.set($any($event.target).value)" placeholder="Reason" aria-label="Reason" />
                          <button class="btn btn--small" (click)="ban(p.id)">Ban</button><button class="linkbtn" (click)="banning.set(null)">cancel</button></span>
                      } @else {<button class="linkbtn small" (click)="banning.set(p.id)">ban…</button>}
                    }
                  </td>
                  <td class="civcell">@if (emblem(p.tribe)) {<img [src]="emblem(p.tribe)" alt="" />}{{ civ(p.tribe) }}</td>
                  <td [class.good]="p.online">{{ ago(p.last_seen_at) }}</td>
                  <td>{{ ago(p.last_login_at) }}</td>
                  <td class="num">{{ p.logins }}</td>
                  <td>
                    @for (c of p.cities; track c.id) {
                      <div class="small"><button class="linkbtn" (click)="view(c.id)" title="Look into this city">{{ c.name }}</button> <span class="muted">({{ c.x }}|{{ c.y }})</span>
                        @if (c.overlord_id) {<span class="bad"> ⛓ vassal of {{ c.overlord_name }}</span>}
                        @if (c.vassals) {<span> ♛ {{ c.vassals }}</span>}
                      </div>
                    } @empty {<span class="muted small">no city</span>}
                  </td>
                  <td class="num">{{ p.population | n }}</td>
                </tr>
              } @empty {<tr><td colspan="8" class="muted">No players match.</td></tr>}
            </tbody>
          </table>
        </div>
        <h3 class="subhead">New round</h3>
        <p class="small muted">Ends this round: it goes into the hall of fame (winner, leaders, medals), then the world is cleared and every player who is not banned gets a fresh city under beginner protection. Accounts, alliances, achievements, medals, the chronicle and chat stay.</p>
        @if (confirmRound()) {
          <div class="row-form">
            <label class="small">World speed <input type="number" min="0.1" step="0.1" [value]="roundSpeed()" (input)="roundSpeed.set(+$any($event.target).value)" style="width:5em" /></label>
            <button class="btn btn--danger btn--small" (click)="newRound()" [disabled]="busy()">Yes, end round {{ d.world?.round }} and start a new one</button>
            <button class="btn btn--small" (click)="confirmRound.set(false)">Cancel</button>
          </div>
        } @else {<button class="btn btn--small" (click)="roundSpeed.set(d.world?.speed ?? 1); confirmRound.set(true)">Start a new round…</button>}
        <p class="muted small">Online means seen in the last {{ d.online_window_ms / 60000 }} minutes. Logins are counted since tracking began; earlier players show "never" until they log in again.</p>
      } @else if (!error()) {
        <p class="muted">Loading…</p>
      }
    </section>
  `,
})
export class AdminComponent implements OnDestroy {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly art = inject(ArtService);
  private readonly engine = inject(EngineService);
  private readonly router = inject(Router);
  protected readonly filters = ADMIN_FILTERS;
  protected readonly data = signal<AdminView | null>(null);
  protected readonly error = signal('');
  protected readonly filter = signal<AdminFilter>('all');
  protected readonly query = signal('');
  protected readonly rows = computed(() => filterPlayers(this.data()?.players ?? [], this.filter(), this.query()));
  private readonly timer = setInterval(() => this.load(), 30_000);
  protected readonly banning = signal<number | null>(null);
  protected readonly banDays = signal(7);
  protected readonly banReason = signal('');
  protected readonly confirmRound = signal(false);
  protected readonly roundSpeed = signal(1);
  protected readonly busy = signal(false);

  protected async ban(id: number): Promise<void> {
    try {
      await this.api.ban(id, this.banDays(), this.banReason());
      this.banning.set(null);
      this.banReason.set('');
      await this.load();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected async unban(id: number): Promise<void> {
    try {
      await this.api.unban(id);
      await this.load();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected async newRound(): Promise<void> {
    this.busy.set(true);
    try {
      const r = await this.api.newRound(this.roundSpeed() || undefined);
      this.game.toast(`Round ${r.round} begins: ${r.players} players, speed ${r.speed}`, 'good');
      setTimeout(() => location.reload(), 1500);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
    this.busy.set(false);
    this.confirmRound.set(false);
  }

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

  protected ago(at: number | null): string {
    return ago(at, this.data()?.server_time ?? Date.now());
  }

  protected civ(tribe: string): string {
    return this.engine.pack()?.tribes.find((t) => t.id === tribe)?.name ?? tribe;
  }

  protected emblem(tribe: string): string | null {
    return this.art.url(this.art.civ(tribe)?.emblem);
  }

  protected async view(id: number): Promise<void> {
    try {
      await this.game.inspect(id);
      await this.router.navigateByUrl('/');
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }
}
