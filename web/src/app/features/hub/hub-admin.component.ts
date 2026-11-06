import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminAccount, SpawnedWorld, SpawnerSchema, Badge, BadgeDef, BadgeForm, HubProfile, HubWorld, WorldForm, WorldStatus } from '../../core/hub';
import { GameStore } from '../../core/game.store';
import { BadgesComponent } from '../../shared/badges';
import { UI } from '../../shared/ui';
import { HubSession } from './hub-session';

type Tab = 'accounts' | 'badges' | 'worlds';
type AdminWorld = HubWorld & { internal_url: string };

interface BadgeEdit extends Required<Omit<BadgeForm, 'patreon_tier'>> {
  id: string;
  patreon_tier: string;
  isNew: boolean;
}

interface SpawnForm {
  id: string; name: string; description: string; pack: string; speed: number; mode: string; status: 'upcoming' | 'open';
  founders_only: boolean; patrons_early: boolean; local_registration: boolean;
  /** JSON text */
  overrides: string;
}

interface WorldEdit extends Required<Omit<WorldForm, 'starts_at' | 'ends_at'>> {
  id: string;
  starts_at: number | null;
  ends_at: number | null;
  isNew: boolean;
}

/** Hub administration: accounts (founders, badges), the badge catalogue and the list of worlds. */
@Component({
  selector: 'ov-hub-admin',
  imports: [DatePipe, FormsModule, BadgesComponent, ...UI],
  template: `
    <div class="page-head">
      <h1 class="page-title">{{ 'nav.hub-admin' | label: 'Hub admin' }}</h1>
      <button class="btn btn--ghost btn--small" (click)="load()">↻ Refresh</button>
    </div>
    @if (!session.me()?.is_admin) {
      <p class="muted">{{ session.me() ? ('error.admin_only' | label: 'Only administrators can open this.') : 'Loading…' }}</p>
    } @else {
      <div class="tabs" role="tablist">
        @for (t of tabs; track t.id) {
          <button class="tabs__tab" role="tab" [attr.aria-selected]="tab() === t.id" [class.tabs__tab--active]="tab() === t.id" (click)="tab.set(t.id)">{{ 'hub.admin.' + t.id | label: t.label }}</button>
        }
      </div>
      @if (error()) {<p class="bad" role="alert">{{ error() }}</p>}

      @switch (tab()) {
        @case ('accounts') {
          <section class="panel">
            <form class="row-form" (ngSubmit)="search()">
              <input name="q" [(ngModel)]="query" placeholder="Search name or email" aria-label="Search accounts" />
              <button class="btn">Search</button>
            </form>
            <div class="table-wrap">
              <table class="table small">
                <thead><tr><th>Account</th><th>Email</th><th>Founder</th><th>Patreon</th><th>Badges</th><th>Last login</th><th></th></tr></thead>
                <tbody>
                  @for (a of accounts(); track a.id) {
                    <tr>
                      <td><strong>{{ a.username }}</strong>@if (a.is_admin) { <span title="Administrator">⚿</span>}</td>
                      <td>{{ a.email || '—' }}</td>
                      <td>{{ a.founder ? '#' + (a.founder_no ?? '?') : '—' }}</td>
                      <td>{{ a.patron_status ? a.patron_status + (a.cents ? ' (' + (a.cents / 100) + ')' : '') : '—' }}</td>
                      <td><ov-badges [badges]="badgesOf(a)" [founderNo]="a.founder_no" /></td>
                      <td>{{ a.last_login_at ? (a.last_login_at | date: 'short') : '—' }}</td>
                      <td><button class="btn btn--small" (click)="manage(a)">{{ managing()?.id === a.id ? 'Close' : 'Manage' }}</button></td>
                    </tr>
                    @if (managing()?.id === a.id) {
                      <tr><td colspan="7">
                        <div class="hub-manage">
                          <fieldset class="hub-fieldset">
                            <legend>Founder</legend>
                            <div class="form__row">
                              <label class="field"><span>Founder</span>
                                <select [(ngModel)]="founder.on" name="fon"><option [ngValue]="true">yes</option><option [ngValue]="false">no</option></select></label>
                              @if (founder.on) {
                                <label class="field field--short"><span>Number (empty: next)</span><input type="number" min="1" name="fno" [(ngModel)]="founder.number" /></label>
                              }
                            </div>
                            @if (founder.on) {
                              <div class="hub-checks">
                                <span class="small muted">Founder badges:</span>
                                @for (b of founderBadges(); track b.id) {
                                  <label class="small"><input type="checkbox" [checked]="founder.badges.includes(b.id)" (change)="toggleFounderBadge(b.id)" /> {{ b.icon }} {{ b.name }}</label>
                                } @empty {<span class="small muted">none in the catalogue</span>}
                              </div>
                            }
                            <button class="btn btn--small btn--primary" [disabled]="busy()" (click)="saveFounder(a)">{{ founder.on ? 'Save founder' : 'Remove founder status' }}</button>
                          </fieldset>
                          <fieldset class="hub-fieldset">
                            <legend>Badges</legend>
                            @for (id of a.badges; track id) {
                              <div class="row small"><span class="grow">{{ badgeName(id) }}</span>
                                <button class="btn btn--small btn--ghost" [disabled]="busy()" (click)="revoke(a, id)">Revoke</button></div>
                            } @empty {<p class="small muted">No badges.</p>}
                            <div class="form__row">
                              <label class="field"><span>Grant</span>
                                <select name="gb" [(ngModel)]="grant.badge">
                                  <option value="">—</option>
                                  @for (b of catalogue(); track b.id) {@if (!a.badges.includes(b.id)) {<option [value]="b.id">{{ b.icon }} {{ b.name }} ({{ b.kind }})</option>}}
                                </select></label>
                              <label class="field grow"><span>Note</span><input name="gn" [(ngModel)]="grant.note" maxlength="200" /></label>
                              <button class="btn btn--small" [disabled]="busy() || !grant.badge" (click)="grantBadge(a)">Grant</button>
                            </div>
                          </fieldset>
                        </div>
                      </td></tr>
                    }
                  } @empty {<tr><td colspan="7" class="muted">No accounts.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        }

        @case ('badges') {
          <section class="panel">
            <div class="table-wrap">
              <table class="table small">
                <thead><tr><th></th><th>Id</th><th>Name</th><th>Kind</th><th>Patreon tier</th><th class="num">Sort</th><th class="num">Holders</th><th></th></tr></thead>
                <tbody>
                  @for (b of catalogue(); track b.id) {
                    <tr>
                      <td><ov-badges [badges]="[b]" /></td><td><code>{{ b.id }}</code></td><td>{{ b.name }}</td><td>{{ b.kind }}</td>
                      <td>{{ b.patreon_tier ?? '—' }}</td><td class="num">{{ b.sort }}</td><td class="num">{{ b.holders }}</td>
                      <td class="nowrap">
                        <button class="btn btn--small" (click)="editBadge(b)">Edit</button>
                        @if (armed() === 'badge:' + b.id) {
                          <button class="btn btn--small btn--danger" [disabled]="busy()" (click)="removeBadge(b.id)">Really delete</button>
                        } @else {<button class="btn btn--small btn--ghost" (click)="armed.set('badge:' + b.id)">Delete</button>}
                      </td>
                    </tr>
                  } @empty {<tr><td colspan="8" class="muted">No badges yet.</td></tr>}
                </tbody>
              </table>
            </div>
            <button class="btn btn--small" (click)="editBadge(null)">+ New badge</button>
          </section>
          @if (badge(); as b) {
            <section class="panel">
              <h2 class="panel__title">{{ b.isNew ? 'New badge' : 'Edit ' + b.id }}</h2>
              <form class="form" (ngSubmit)="saveBadge()">
                <div class="form__row">
                  <label class="field"><span>Id</span><input name="bid" [(ngModel)]="b.id" [disabled]="!b.isNew" placeholder="founder-gold" required /></label>
                  <label class="field"><span>Name</span><input name="bname" [(ngModel)]="b.name" maxlength="40" required /></label>
                  <label class="field field--short"><span>Icon</span><input name="bicon" [(ngModel)]="b.icon" maxlength="8" placeholder="✦" /></label>
                  <label class="field"><span>Color</span><input name="bcolor" type="color" [(ngModel)]="b.color" /></label>
                  <label class="field"><span>Kind</span>
                    <select name="bkind" [(ngModel)]="b.kind"><option value="founder">founder</option><option value="patron">patron</option><option value="award">award</option></select></label>
                  @if (b.kind === 'patron') {
                    <label class="field"><span>Patreon tier (* = any pledge)</span><input name="btier" [(ngModel)]="b.patreon_tier" maxlength="40" /></label>
                  }
                  <label class="field field--short"><span>Sort</span><input name="bsort" type="number" [(ngModel)]="b.sort" /></label>
                </div>
                <label class="field"><span>Description</span><input name="bdesc" [(ngModel)]="b.description" maxlength="300" /></label>
                <p class="small muted">Preview: <ov-badges [badges]="[preview(b)]" /> {{ b.name }}</p>
                <div class="btn-row">
                  <button class="btn btn--primary" [disabled]="busy() || !b.id || !b.name">Save</button>
                  <button class="btn btn--ghost" type="button" (click)="badge.set(null)">Cancel</button>
                </div>
              </form>
            </section>
          }
        }

        @case ('worlds') {
          <section class="panel">
            <div class="table-wrap">
              <table class="table small">
                <thead><tr><th>Id</th><th>Name</th><th>Status</th><th>Speed</th><th>API</th><th>Early access</th><th class="num">Players</th><th class="num">Sort</th><th></th></tr></thead>
                <tbody>
                  @for (w of worlds(); track w.id) {
                    <tr>
                      <td><code>{{ w.id }}</code></td><td>{{ w.name }}</td><td>{{ w.status }}</td><td>×{{ w.speed }}</td>
                      <td><code>{{ w.api_url }}</code>@if (w.internal_url) {<br /><span class="muted">{{ w.internal_url }}</span>}</td>
                      <td>{{ w.founders_only ? (w.patrons_early ? 'founders + patrons' : 'founders') : '—' }}</td>
                      <td class="num">{{ w.players }}</td><td class="num">{{ w.sort }}</td>
                      <td class="nowrap">
                        <button class="btn btn--small" (click)="editWorld(w)">Edit</button>
                        @if (armed() === 'world:' + w.id) {
                          <button class="btn btn--small btn--danger" [disabled]="busy()" (click)="removeWorld(w.id)">Really remove</button>
                        } @else {<button class="btn btn--small btn--ghost" (click)="armed.set('world:' + w.id)">Remove</button>}
                      </td>
                    </tr>
                  } @empty {<tr><td colspan="9" class="muted">No worlds yet.</td></tr>}
                </tbody>
              </table>
            </div>
            <p class="small muted">Removing a world only takes it off the hub's list; its server and database are untouched.</p>
            <button class="btn btn--small" (click)="editWorld(null)">+ New world</button>
            <button class="btn btn--small btn--primary" (click)="openSpawn()">⚙ Spawn a world here</button>
          </section>
          <section class="panel">
            <h2 class="panel__title">Worlds on this machine <span class="muted small">run by the spawner</span></h2>
            @if (schema()?.enabled === false) {<p class="muted small">This hub has no spawner (OVIAN_HUB_SPAWNER_URL).</p>}
            <div class="table-wrap">
              <table class="table small">
                <thead><tr><th>Id</th><th>Pack</th><th>Speed</th><th>State</th><th>Containers</th><th></th></tr></thead>
                <tbody>
                  @for (sw of spawned(); track sw.id) {
                    <tr>
                      <td><code>{{ sw.id }}</code></td><td>{{ sw.pack }}</td><td>×{{ sw.speed }}</td>
                      <td [class.good]="sw.state === 'running'" [class.bad]="sw.state !== 'running'">{{ sw.state }}</td>
                      <td class="small muted">@for (c of sw.containers; track c.service) {<div>{{ c.service }}: {{ c.status }}</div>}</td>
                      <td class="nowrap">
                        @if (sw.state === 'running') {<button class="btn btn--small" [disabled]="busy()" (click)="stopSpawned(sw.id)">Stop</button>}
                        @else {<button class="btn btn--small" [disabled]="busy()" (click)="startSpawned(sw.id)">Start</button>}
                      </td>
                    </tr>
                  } @empty {<tr><td colspan="6" class="muted">No spawned worlds.</td></tr>}
                </tbody>
              </table>
            </div>
            <p class="small muted">Stop keeps the database and marks the world closed on the list. Removing containers and databases is done by hand.</p>
          </section>
          @if (spawn(); as sp) {
            <section class="panel">
              <h2 class="panel__title">Spawn a world here</h2>
              <form class="form" (ngSubmit)="doSpawn()">
                <div class="form__row">
                  <label class="field"><span>Id</span><input name="sid" [(ngModel)]="sp.id" placeholder="w3" required pattern="[a-z][a-z0-9_-]{0,30}" /></label>
                  <label class="field grow"><span>Name</span><input name="sname" [(ngModel)]="sp.name" maxlength="60" required /></label>
                  <label class="field"><span>Pack</span><input name="spack" [(ngModel)]="sp.pack" placeholder="antiquity" /></label>
                  <label class="field field--short"><span>Speed</span><input name="sspeed" type="number" min="0.1" step="0.1" [(ngModel)]="sp.speed" /></label>
                </div>
                <label class="field"><span>Description</span><textarea name="sdesc" rows="2" [(ngModel)]="sp.description" maxlength="1000"></textarea></label>
                <div class="form__row">
                  <label class="field"><span>Mode</span>
                    <select name="smode" [(ngModel)]="sp.mode" (ngModelChange)="modeChanged($event)">
                      @for (m of modeList(); track m.id) {<option [value]="m.id">{{ m.name }}</option>}
                    </select></label>
                  <label class="field"><span>Status on the list</span>
                    <select name="sstatus" [(ngModel)]="sp.status"><option value="upcoming">upcoming</option><option value="open">open</option></select></label>
                  <label class="small"><input type="checkbox" name="sfo" [(ngModel)]="sp.founders_only" /> Founders only</label>
                  <label class="small"><input type="checkbox" name="spe" [(ngModel)]="sp.patrons_early" [disabled]="!sp.founders_only" /> Patrons too</label>
                  <label class="small"><input type="checkbox" name="slr" [(ngModel)]="sp.local_registration" /> Its own sign-up page too</label>
                </div>
                @if (modeDoc(); as d) {<p class="small muted">{{ d }}</p>}
                <label class="field"><span>Overrides, as JSON with "world" and "extensions" (the mode's preset is filled in; null removes a group and switches that feature off)</span>
                  <textarea name="sover" rows="10" style="font-family: monospace" [(ngModel)]="sp.overrides"></textarea></label>
                <details class="small">
                  <summary>Every setting with its default ({{ schema()?.groups?.length ?? 0 }} groups) — ⏻ marks groups that switch off when removed</summary>
                  @if (schema(); as sc) {
                    <p class="muted"><strong>world</strong> · {{ sc.world.doc }} <code>{{ json(sc.world.defaults) }}</code></p>
                    @for (g of sc.groups; track g.key) {<p class="muted"><strong>{{ g.key }}</strong>@if (g.off_when_absent) { ⏻} · {{ g.doc }} <code>{{ json(g.defaults) }}</code></p>}
                  }
                </details>
                <div class="btn-row">
                  <button class="btn btn--primary" [disabled]="busy() || !sp.id || !sp.name">Create and start</button>
                  <button class="btn btn--ghost" type="button" (click)="spawn.set(null)">Cancel</button>
                </div>
              </form>
            </section>
          }
          @if (world(); as w) {
            <section class="panel">
              <h2 class="panel__title">{{ w.isNew ? 'New world' : 'Edit ' + w.id }}</h2>
              <form class="form" (ngSubmit)="saveWorld()">
                <div class="form__row">
                  <label class="field"><span>Id</span><input name="wid" [(ngModel)]="w.id" [disabled]="!w.isNew" placeholder="w3" required /></label>
                  <label class="field grow"><span>Name</span><input name="wname" [(ngModel)]="w.name" maxlength="60" required /></label>
                  <label class="field"><span>Pack</span><input name="wpack" [(ngModel)]="w.pack" placeholder="antiquity" /></label>
                  <label class="field field--short"><span>Speed</span><input name="wspeed" type="number" min="0.1" step="0.1" [(ngModel)]="w.speed" /></label>
                  <label class="field field--short"><span>Sort</span><input name="wsort" type="number" [(ngModel)]="w.sort" /></label>
                </div>
                <label class="field"><span>Description</span><textarea name="wdesc" rows="2" [(ngModel)]="w.description" maxlength="1000"></textarea></label>
                <div class="form__row">
                  <label class="field grow"><span>API URL ("/" = this site, "/w/w3", or a full origin)</span><input name="wapi" [(ngModel)]="w.api_url" required /></label>
                  <label class="field grow"><span>Internal URL (hub to world, optional)</span><input name="wint" [(ngModel)]="w.internal_url" placeholder="http://world-w3:8000" /></label>
                </div>
                <div class="form__row">
                  <label class="field"><span>Status</span>
                    <select name="wstatus" [(ngModel)]="w.status">
                      @for (s of statuses; track s) {<option [value]="s">{{ s }}</option>}
                    </select></label>
                  <label class="small"><input type="checkbox" name="wfo" [(ngModel)]="w.founders_only" /> Founders only (early access)</label>
                  <label class="small"><input type="checkbox" name="wpe" [(ngModel)]="w.patrons_early" [disabled]="!w.founders_only" /> Patrons too</label>
                </div>
                <div class="btn-row">
                  <button class="btn btn--primary" [disabled]="busy() || !w.id || !w.name || !w.api_url">Save</button>
                  <button class="btn btn--ghost" type="button" (click)="world.set(null)">Cancel</button>
                </div>
              </form>
            </section>
          }
        }
      }
    }
  `,
})
export class HubAdminComponent implements OnInit {
  protected readonly session = inject(HubSession);
  private readonly game = inject(GameStore);
  private readonly hub = this.session.hub;
  protected readonly tabs: { id: Tab; label: string }[] = [
    { id: 'accounts', label: 'Accounts' },
    { id: 'badges', label: 'Badges' },
    { id: 'worlds', label: 'Worlds' },
  ];
  protected readonly statuses: WorldStatus[] = ['upcoming', 'open', 'closed', 'ended'];
  protected readonly tab = signal<Tab>('accounts');
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly armed = signal('');
  protected readonly accounts = signal<AdminAccount[]>([]);
  protected readonly catalogue = signal<BadgeDef[]>([]);
  protected readonly worlds = signal<AdminWorld[]>([]);
  protected readonly managing = signal<AdminAccount | null>(null);
  protected readonly badge = signal<BadgeEdit | null>(null);
  protected readonly world = signal<WorldEdit | null>(null);
  // the spawner
  protected readonly spawned = signal<SpawnedWorld[]>([]);
  protected readonly schema = signal<SpawnerSchema | null>(null);
  protected readonly spawn = signal<SpawnForm | null>(null);
  protected readonly modeList = computed(() => Object.entries(this.schema()?.modes ?? {}).map(([id, m]) => ({ id, name: m.name, doc: m.doc })));
  protected readonly modeDoc = computed(() => this.schema()?.modes?.[this.spawn()?.mode ?? '']?.doc ?? '');
  protected readonly founderBadges = computed(() => this.catalogue().filter((b) => b.kind === 'founder'));
  protected query = '';
  protected founder: { on: boolean; number: number | null; badges: string[] } = { on: false, number: null, badges: [] };
  protected grant = { badge: '', note: '' };

  async ngOnInit(): Promise<void> {
    const me = await this.session.load();
    if (me?.is_admin) await this.load();
  }

  protected async load(): Promise<void> {
    await this.run(async () => {
      const [accounts, badges, worlds] = await Promise.all([this.hub.adminAccounts(this.query.trim()), this.hub.badges(), this.hub.adminWorlds()]);
      this.accounts.set(accounts);
      this.catalogue.set(badges);
      this.worlds.set(worlds);
      void this.loadSpawner();
    });
  }

  private async run(fn: () => Promise<void>, done?: string): Promise<boolean> {
    this.busy.set(true);
    this.error.set('');
    try {
      await fn();
      if (done) this.game.toast(done, 'good');
      return true;
    } catch (e) {
      this.error.set(this.game.errorText(e));
      return false;
    } finally {
      this.busy.set(false);
      this.armed.set('');
    }
  }

  // ---- accounts
  protected search(): void {
    void this.run(async () => this.accounts.set(await this.hub.adminAccounts(this.query.trim())));
  }

  protected badgesOf(a: AdminAccount): Badge[] {
    const all = this.catalogue();
    return a.badges.map((id) => all.find((b) => b.id === id)).filter((b): b is BadgeDef => !!b);
  }

  protected badgeName(id: string): string {
    const b = this.catalogue().find((x) => x.id === id);
    return b ? `${b.icon} ${b.name}` : id;
  }

  protected manage(a: AdminAccount): void {
    if (this.managing()?.id === a.id) {
      this.managing.set(null);
      return;
    }
    const founderIds = this.founderBadges().map((b) => b.id);
    const held = a.badges.filter((id) => founderIds.includes(id));
    this.founder = { on: a.founder, number: a.founder_no, badges: a.founder && held.length ? held : founderIds };
    this.grant = { badge: '', note: '' };
    this.managing.set(a);
  }

  protected toggleFounderBadge(id: string): void {
    const l = this.founder.badges;
    this.founder.badges = l.includes(id) ? l.filter((x) => x !== id) : [...l, id];
  }

  private applyProfile(id: number, p: HubProfile): void {
    this.accounts.update((l) => l.map((a) => (a.id === id ? { ...a, founder: p.founder, founder_no: p.founder_no, badges: p.badges.map((b) => b.id) } : a)));
    this.managing.set(this.accounts().find((a) => a.id === id) ?? null);
    if (id === this.session.me()?.account_id) void this.session.load(true);
  }

  protected saveFounder(a: AdminAccount): void {
    const f = this.founder;
    void this.run(async () => {
      const p = await this.hub.setFounder(a.id, f.on, f.on ? f.number || null : null, f.on ? f.badges : undefined);
      this.applyProfile(a.id, p);
      this.catalogue.set(await this.hub.badges());
    }, f.on ? `${a.username} is a founder.` : `${a.username} is no longer a founder.`);
  }

  protected grantBadge(a: AdminAccount): void {
    const { badge, note } = this.grant;
    void this.run(async () => {
      this.applyProfile(a.id, await this.hub.grantBadge(a.id, badge, note.trim()));
      this.grant = { badge: '', note: '' };
    }, `${this.badgeName(badge)} → ${a.username}`);
  }

  protected revoke(a: AdminAccount, badge: string): void {
    void this.run(async () => this.applyProfile(a.id, await this.hub.revokeBadge(a.id, badge)), `${this.badgeName(badge)} revoked.`);
  }

  // ---- badges
  protected editBadge(b: BadgeDef | null): void {
    this.badge.set(
      b
        ? { id: b.id, name: b.name, description: b.description ?? '', icon: b.icon, color: b.color, kind: b.kind, patreon_tier: b.patreon_tier ?? '', sort: b.sort, isNew: false }
        : { id: '', name: '', description: '', icon: '✦', color: '#b8892c', kind: 'award', patreon_tier: '', sort: 0, isNew: true },
    );
  }

  protected preview(b: BadgeEdit): Badge {
    return { id: b.id || 'preview', name: b.name, icon: b.icon, color: b.color, kind: b.kind };
  }

  protected saveBadge(): void {
    const b = this.badge();
    if (!b) return;
    const form: BadgeForm = {
      name: b.name.trim(), description: b.description.trim(), icon: b.icon.trim(), color: b.color, kind: b.kind,
      patreon_tier: b.kind === 'patron' ? b.patreon_tier.trim() || null : null, sort: Number(b.sort) || 0,
    };
    void this.run(async () => {
      await this.hub.putBadge(b.id.trim(), form);
      this.badge.set(null);
      this.catalogue.set(await this.hub.badges());
    }, 'Badge saved.');
  }

  protected removeBadge(id: string): void {
    void this.run(async () => {
      await this.hub.deleteBadge(id);
      this.catalogue.update((l) => l.filter((b) => b.id !== id));
      this.accounts.update((l) => l.map((a) => ({ ...a, badges: a.badges.filter((x) => x !== id) })));
    }, 'Badge deleted.');
  }

  // ---- the spawner
  private async loadSpawner(): Promise<void> {
    try {
      const sc = await this.hub.spawnerSchema();
      this.schema.set(sc);
      if (sc.enabled) this.spawned.set(await this.hub.spawnedWorlds());
    } catch {
      this.schema.set({ enabled: false, world: { doc: '', defaults: {} }, groups: [], modes: {} });
    }
  }

  protected openSpawn(): void {
    const preset = this.schema()?.modes?.['hybrid']?.overrides ?? {};
    this.spawn.set({ id: '', name: '', description: '', pack: 'antiquity', speed: 1, mode: 'hybrid', status: 'upcoming', founders_only: false,
                     patrons_early: false, local_registration: false, overrides: JSON.stringify(preset, null, 2) });
  }

  protected modeChanged(mode: string): void {
    const sp = this.spawn();
    if (!sp) return;
    this.spawn.set({ ...sp, mode, overrides: JSON.stringify(this.schema()?.modes?.[mode]?.overrides ?? {}, null, 2) });
  }

  protected async doSpawn(): Promise<void> {
    const sp = this.spawn();
    if (!sp) return;
    let overrides: Record<string, unknown> = {};
    try {
      overrides = sp.overrides.trim() ? JSON.parse(sp.overrides) : {};
    } catch {
      this.game.toast('The overrides are not valid JSON.', 'bad');
      return;
    }
    await this.run(async () => {
      await this.hub.spawnWorld({ id: sp.id.trim(), name: sp.name.trim(), description: sp.description.trim(), pack: sp.pack.trim() || 'antiquity',
                                  speed: +sp.speed || 1, mode: sp.mode, overrides, status: sp.status, founders_only: sp.founders_only,
                                  patrons_early: sp.patrons_early, local_registration: sp.local_registration });
      this.worlds.set(await this.hub.adminWorlds());
      this.spawned.set(await this.hub.spawnedWorlds());
      this.spawn.set(null);
    }, `World ${sp.id} is up at /w/${sp.id}/.`);
  }

  protected async stopSpawned(id: string): Promise<void> {
    await this.run(async () => {
      await this.hub.stopSpawned(id);
      this.spawned.set(await this.hub.spawnedWorlds());
      this.worlds.set(await this.hub.adminWorlds());
    }, `World ${id} stopped.`);
  }

  protected async startSpawned(id: string): Promise<void> {
    await this.run(async () => {
      await this.hub.startSpawned(id);
      this.spawned.set(await this.hub.spawnedWorlds());
    }, `World ${id} started.`);
  }

  protected json(v: unknown): string {
    return JSON.stringify(v);
  }

  // ---- worlds
  protected editWorld(w: AdminWorld | null): void {
    this.world.set(
      w
        ? { id: w.id, name: w.name, description: w.description, pack: w.pack, speed: w.speed, api_url: w.api_url, internal_url: w.internal_url ?? '',
            status: w.status, founders_only: w.founders_only, patrons_early: w.patrons_early, starts_at: w.starts_at, ends_at: w.ends_at, sort: w.sort, isNew: false }
        : { id: '', name: '', description: '', pack: '', speed: 1, api_url: '/', internal_url: '', status: 'upcoming', founders_only: false,
            patrons_early: false, starts_at: null, ends_at: null, sort: this.worlds().length, isNew: true },
    );
  }

  protected saveWorld(): void {
    const w = this.world();
    if (!w) return;
    const form: WorldForm = {
      name: w.name.trim(), description: w.description.trim(), pack: w.pack.trim(), speed: Number(w.speed) || 1,
      api_url: w.api_url.trim(), internal_url: w.internal_url.trim(), status: w.status,
      founders_only: w.founders_only, patrons_early: w.founders_only && w.patrons_early,
      starts_at: w.starts_at, ends_at: w.ends_at, sort: Number(w.sort) || 0,
    };
    void this.run(async () => {
      await this.hub.putWorld(w.id.trim(), form);
      this.world.set(null);
      this.worlds.set(await this.hub.adminWorlds());
    }, 'World saved.');
  }

  protected removeWorld(id: string): void {
    void this.run(async () => {
      await this.hub.deleteWorld(id);
      this.worlds.update((l) => l.filter((w) => w.id !== id));
    }, 'World removed.');
  }
}
