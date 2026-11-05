import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { GameStore } from '@core/game.store';
import { AdminAccount, BadgeDef, Hub, HubWorld, WorldStatus } from '@core/hub';
import { UI } from '../ui';

type Tab = 'accounts' | 'badges' | 'worlds';
type AdminWorld = HubWorld & { internal_url: string };

interface BadgeEdit { id: string; name: string; description: string; icon: string; color: string; kind: 'founder' | 'patron' | 'award'; patreon_tier: string; sort: number; isNew: boolean }
interface WorldEdit {
  id: string; name: string; description: string; pack: string; speed: number; api_url: string; internal_url: string; status: WorldStatus;
  founders_only: boolean; patrons_early: boolean; starts: string; ends: string; sort: number; isNew: boolean;
}

/** ms -> the value of a datetime-local input, and back. */
function toLocal(ms: number | null | undefined): string {
  if (!ms) return '';
  const d = new Date(ms);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}
function fromLocal(v: string): number | null {
  const t = v ? new Date(v).getTime() : NaN;
  return isFinite(t) ? t : null;
}

/** The hub's administration: accounts (founders, badges), the badge catalogue and the list of worlds. */
@Component({
  selector: 'dio-hub-admin',
  imports: [DatePipe, FormsModule, ...UI],
  template: `
    <section class="hud-panel dialog admin hub-admin" role="dialog" aria-label="Hub administration">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Hub administration <span class="muted small">· accounts, badges and worlds for every world</span></h2>
      <div class="seg" role="tablist" aria-label="Section">
        @for (t of tabs; track t.id) {<button type="button" role="tab" class="seg__opt" [class.seg__opt--on]="tab() === t.id" [attr.aria-selected]="tab() === t.id" (click)="tab.set(t.id)">{{ t.label }}</button>}
      </div>
      @if (error()) {<p class="bad">{{ error() }}</p>}

      @if (tab() === 'accounts') {
        <form class="admin__tools" (submit)="$event.preventDefault(); loadAccounts()">
          <input name="q" [(ngModel)]="query" placeholder="Search name or email" aria-label="Search accounts" />
          <button class="btn btn--small">Search</button>
        </form>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Account</th><th>Joined</th><th>Last login</th><th>Patreon</th><th>Badges</th><th></th></tr></thead>
            <tbody>
              @for (a of accounts(); track a.id) {
                <tr>
                  <td><strong>{{ a.username }}</strong>@if (a.is_admin) {<span class="tag">admin</span>}@if (a.founder) {<span class="tag">Founder #{{ a.founder_no }}</span>}
                    @if (a.email) {<div class="small muted">{{ a.email }}</div>}</td>
                  <td class="small">{{ a.created_at | date: 'd MMM y' }}</td>
                  <td class="small">{{ a.last_login_at ? (a.last_login_at | date: 'd MMM y, HH:mm') : 'never' }}</td>
                  <td class="small">@if (a.patron_status) {{{ a.patron_status === 'active_patron' ? 'active' : a.patron_status }}@if (a.cents) { · {{ a.cents / 100 }}/mo}} @else {<span class="muted">—</span>}</td>
                  <td>
                    <div class="hub-admin__chips">
                      @for (b of badgesOf(a); track b.id) {
                        <span class="hub-admin__held"><dio-badges [badges]="[b]" [founderNo]="a.founder_no" />
                          <button type="button" class="linkbtn small" (click)="revoke(a, b.id)" [title]="'Revoke ' + b.name" [attr.aria-label]="'Revoke ' + b.name">✕</button></span>
                      } @empty {<span class="muted small">—</span>}
                    </div>
                  </td>
                  <td class="actions">
                    <button type="button" class="btn btn--small" (click)="openFounder(a)">Founder…</button>
                    <button type="button" class="btn btn--small" (click)="openGrant(a)">Grant…</button>
                  </td>
                </tr>
                @if (editing()?.id === a.id) {
                  <tr class="hub-admin__edit"><td colspan="6">
                    @if (editing()!.kind === 'founder') {
                      <div class="row-form">
                        <label class="small">Founder number <input type="number" min="1" [(ngModel)]="founderNo" placeholder="next free" style="width: 7em" /></label>
                        @for (b of founderBadges(); track b.id) {
                          <label class="small"><input type="checkbox" [checked]="founderPick.has(b.id)" (change)="togglePick(b.id)" style="width: auto" /> <dio-badges [badges]="[b]" /> {{ b.name }}</label>
                        } @empty {<span class="small muted">No founder badges in the catalogue.</span>}
                      </div>
                      <div class="btn-row">
                        <button type="button" class="btn btn--small btn--gold" [disabled]="busy()" (click)="setFounder(a, true)">{{ a.founder ? 'Update founder' : 'Make founder' }}</button>
                        @if (a.founder) {<button type="button" class="btn btn--small btn--danger" [disabled]="busy()" (click)="setFounder(a, false)">Remove founder</button>}
                        <button type="button" class="btn btn--small" (click)="editing.set(null)">Cancel</button>
                      </div>
                    } @else {
                      <div class="row-form">
                        <select [(ngModel)]="grantId" aria-label="Badge">
                          @for (b of catalogue(); track b.id) {<option [value]="b.id">{{ b.icon }} {{ b.name }} ({{ b.kind }})</option>}
                        </select>
                        <input [(ngModel)]="grantNote" placeholder="Note (why)" aria-label="Note" maxlength="200" />
                        <button type="button" class="btn btn--small btn--gold" [disabled]="busy() || !grantId" (click)="grant(a)">Grant</button>
                        <button type="button" class="btn btn--small" (click)="editing.set(null)">Cancel</button>
                      </div>
                      <p class="small muted">Patron badges follow Patreon by themselves; grant them by hand only as an exception.</p>
                    }
                  </td></tr>
                }
              } @empty {<tr><td colspan="6" class="muted">No accounts match.</td></tr>}
            </tbody>
          </table>
        </div>
      } @else if (tab() === 'badges') {
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th></th><th>Id</th><th>Name</th><th>Kind</th><th>Patreon tier</th><th class="num">Sort</th><th class="num">Holders</th><th></th></tr></thead>
            <tbody>
              @for (b of catalogue(); track b.id) {
                <tr>
                  <td><dio-badges [badges]="[b]" /></td>
                  <td><code>{{ b.id }}</code></td>
                  <td>{{ b.name }}@if (b.description) {<div class="small muted">{{ b.description }}</div>}</td>
                  <td>{{ b.kind }}</td>
                  <td class="small">{{ b.patreon_tier ?? '' }}</td>
                  <td class="num">{{ b.sort }}</td>
                  <td class="num">{{ b.holders }}</td>
                  <td class="actions">
                    <button type="button" class="btn btn--small" (click)="editBadge(b)">Edit</button>
                    <button type="button" class="btn btn--small btn--danger" [disabled]="busy()" (click)="deleteBadge(b.id)">{{ armed() === 'b:' + b.id ? 'Really delete' : 'Delete' }}</button>
                  </td>
                </tr>
              } @empty {<tr><td colspan="8" class="muted">No badges yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <div class="btn-row"><button type="button" class="btn btn--small" (click)="editBadge(null)">+ New badge</button></div>
        @if (badge(); as f) {
          <form class="hub-form" (submit)="$event.preventDefault(); saveBadge()">
            <h3 class="subhead">{{ f.isNew ? 'New badge' : 'Badge ' + f.id }}</h3>
            <label>Id <input name="bid" [(ngModel)]="f.id" [readonly]="!f.isNew" required pattern="[a-z0-9_\\-]{2,32}" placeholder="founder-gold" /></label>
            <label>Name <input name="bname" [(ngModel)]="f.name" required maxlength="40" /></label>
            <label class="hub-form__wide">Description <input name="bdesc" [(ngModel)]="f.description" maxlength="300" /></label>
            <label>Icon (emoji) <input name="bicon" [(ngModel)]="f.icon" maxlength="8" placeholder="★" /></label>
            <label>Colour <span class="hub-form__color"><input name="bcolor" type="color" [(ngModel)]="f.color" /><input name="bcolor2" [(ngModel)]="f.color" pattern="#[0-9a-fA-F]{6}" /></span></label>
            <label>Kind
              <select name="bkind" [(ngModel)]="f.kind"><option value="award">award</option><option value="founder">founder</option><option value="patron">patron</option></select></label>
            @if (f.kind === 'patron') {<label>Patreon tier <input name="btier" [(ngModel)]="f.patreon_tier" placeholder="tier id, or * for any pledge" required /></label>}
            <label>Sort <input name="bsort" type="number" [(ngModel)]="f.sort" /></label>
            <div class="hub-form__preview hub-form__wide small">Preview: <dio-badges [badges]="[previewBadge(f)]" [founderNo]="1" [named]="true" /></div>
            <div class="btn-row hub-form__wide">
              <button class="btn btn--small btn--gold" [disabled]="busy()">Save</button>
              <button type="button" class="btn btn--small" (click)="badge.set(null)">Cancel</button>
            </div>
          </form>
        }
      } @else {
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>World</th><th>Status</th><th class="num">Speed</th><th>API</th><th>Early access</th><th class="num">Players</th><th class="num">Sort</th><th></th></tr></thead>
            <tbody>
              @for (w of adminWorlds(); track w.id) {
                <tr>
                  <td><strong>{{ w.name }}</strong> <code>{{ w.id }}</code>@if (w.pack) {<div class="small muted">{{ w.pack }}</div>}</td>
                  <td>{{ w.status }}</td>
                  <td class="num">×{{ w.speed }}</td>
                  <td class="small"><code>{{ w.api_url }}</code>@if (w.internal_url) {<div class="muted">{{ w.internal_url }}</div>}</td>
                  <td class="small">{{ w.founders_only ? 'founders' : w.patrons_early ? 'founders & patrons' : '—' }}</td>
                  <td class="num">{{ w.players }}</td>
                  <td class="num">{{ w.sort }}</td>
                  <td class="actions">
                    <button type="button" class="btn btn--small" (click)="editWorld(w)">Edit</button>
                    <button type="button" class="btn btn--small btn--danger" [disabled]="busy()" (click)="deleteWorld(w.id)">{{ armed() === 'w:' + w.id ? 'Really remove' : 'Remove' }}</button>
                  </td>
                </tr>
              } @empty {<tr><td colspan="8" class="muted">No worlds yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <div class="btn-row"><button type="button" class="btn btn--small" (click)="editWorld(null)">+ New world</button></div>
        <p class="small muted">Removing a world only takes it off the list: its server and database are untouched.</p>
        @if (world(); as f) {
          <form class="hub-form" (submit)="$event.preventDefault(); saveWorld()">
            <h3 class="subhead">{{ f.isNew ? 'New world' : 'World ' + f.id }}</h3>
            <label>Id <input name="wid" [(ngModel)]="f.id" [readonly]="!f.isNew" required pattern="[a-z0-9_\\-]{1,32}" placeholder="w3" /></label>
            <label>Name <input name="wname" [(ngModel)]="f.name" required maxlength="60" /></label>
            <label class="hub-form__wide">Description <textarea name="wdesc" [(ngModel)]="f.description" rows="3" maxlength="1000"></textarea></label>
            <label>Content pack <input name="wpack" [(ngModel)]="f.pack" placeholder="antiquity" /></label>
            <label>Speed <input name="wspeed" type="number" min="0.1" step="0.1" [(ngModel)]="f.speed" /></label>
            <label>API URL <input name="wapi" [(ngModel)]="f.api_url" required placeholder="/ , /w/w3 or https://…" /></label>
            <label>Internal URL <input name="wint" [(ngModel)]="f.internal_url" placeholder="http://world-w3:8000" /></label>
            <label>Status
              <select name="wstatus" [(ngModel)]="f.status"><option value="upcoming">upcoming</option><option value="open">open</option><option value="closed">closed</option><option value="ended">ended</option></select></label>
            <label>Sort <input name="wsort" type="number" [(ngModel)]="f.sort" /></label>
            <label>Opens <input name="wstarts" type="datetime-local" [(ngModel)]="f.starts" /></label>
            <label>Ends <input name="wends" type="datetime-local" [(ngModel)]="f.ends" /></label>
            <label class="hub-form__check"><input name="wfo" type="checkbox" [(ngModel)]="f.founders_only" /> Founders only (early access)</label>
            <label class="hub-form__check"><input name="wpe" type="checkbox" [(ngModel)]="f.patrons_early" /> Patrons early (founders and patrons may enter before it opens)</label>
            <p class="small muted hub-form__wide">API URL: "/" is this site, "/w/w3" a path on it, or a full origin. The internal URL is how the hub reaches the world's server.</p>
            <div class="btn-row hub-form__wide">
              <button class="btn btn--small btn--gold" [disabled]="busy()">Save</button>
              <button type="button" class="btn btn--small" (click)="world.set(null)">Cancel</button>
            </div>
          </form>
        }
      }
    </section>
  `,
})
export class HubAdminComponent implements OnInit {
  private readonly hub = inject(Hub);
  private readonly game = inject(GameStore);
  private readonly router = inject(Router);
  protected readonly tabs: { id: Tab; label: string }[] = [
    { id: 'accounts', label: 'Accounts' }, { id: 'badges', label: 'Badges' }, { id: 'worlds', label: 'Worlds' },
  ];
  protected readonly tab = signal<Tab>('accounts');
  protected readonly error = signal('');
  protected readonly busy = signal(false);
  protected readonly armed = signal<string | null>(null);

  protected readonly accounts = signal<AdminAccount[]>([]);
  protected readonly catalogue = signal<BadgeDef[]>([]);
  protected readonly adminWorlds = signal<AdminWorld[]>([]);
  private readonly byId = computed(() => new Map(this.catalogue().map((b) => [b.id, b])));
  protected readonly founderBadges = computed(() => this.catalogue().filter((b) => b.kind === 'founder'));
  protected query = '';

  protected readonly editing = signal<{ id: number; kind: 'founder' | 'grant' } | null>(null);
  protected founderNo: number | null = null;
  protected founderPick = new Set<string>();
  protected grantId = '';
  protected grantNote = '';

  protected readonly badge = signal<BadgeEdit | null>(null);
  protected readonly world = signal<WorldEdit | null>(null);

  ngOnInit(): void {
    void this.run(async () => {
      const [badges, worlds, accounts] = await Promise.all([this.hub.badges(), this.hub.adminWorlds(), this.hub.adminAccounts('')]);
      this.catalogue.set(badges);
      this.adminWorlds.set(worlds);
      this.accounts.set(accounts);
    });
  }

  /** Run an admin call: busy while it runs, errors shown. */
  private async run(fn: () => Promise<unknown>, done?: string): Promise<boolean> {
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
    }
  }

  // ---- accounts
  protected loadAccounts(): Promise<boolean> {
    return this.run(async () => this.accounts.set(await this.hub.adminAccounts(this.query.trim())));
  }

  protected badgesOf(a: AdminAccount): BadgeDef[] {
    return a.badges.map((id) => this.byId().get(id)).filter((b): b is BadgeDef => !!b);
  }

  protected openFounder(a: AdminAccount): void {
    this.founderNo = a.founder_no;
    const held = a.badges.filter((id) => this.byId().get(id)?.kind === 'founder');
    this.founderPick = new Set(a.founder && held.length ? held : this.founderBadges().map((b) => b.id));
    this.editing.set({ id: a.id, kind: 'founder' });
  }

  protected togglePick(id: string): void {
    if (this.founderPick.has(id)) this.founderPick.delete(id);
    else this.founderPick.add(id);
  }

  protected openGrant(a: AdminAccount): void {
    this.grantId = this.catalogue().find((b) => b.kind !== 'patron' && !a.badges.includes(b.id))?.id ?? this.catalogue()[0]?.id ?? '';
    this.grantNote = '';
    this.editing.set({ id: a.id, kind: 'grant' });
  }

  protected async setFounder(a: AdminAccount, on: boolean): Promise<void> {
    const ok = await this.run(
      () => this.hub.setFounder(a.id, on, on ? this.founderNo || null : null, on ? [...this.founderPick] : undefined),
      on ? `${a.username} is a founder` : `${a.username} is no longer a founder`,
    );
    if (ok) {
      this.editing.set(null);
      await this.refresh();
    }
  }

  protected async grant(a: AdminAccount): Promise<void> {
    const ok = await this.run(() => this.hub.grantBadge(a.id, this.grantId, this.grantNote.trim()), `Badge granted to ${a.username}`);
    if (ok) {
      this.editing.set(null);
      await this.refresh();
    }
  }

  protected async revoke(a: AdminAccount, badge: string): Promise<void> {
    if (await this.run(() => this.hub.revokeBadge(a.id, badge), `Badge revoked from ${a.username}`)) await this.refresh();
  }

  /** Accounts and holder counts after a change. */
  private async refresh(): Promise<void> {
    await this.loadAccounts();
    this.hub.badges().then((b) => this.catalogue.set(b)).catch(() => undefined);
  }

  // ---- badges
  protected editBadge(b: BadgeDef | null): void {
    this.badge.set(b
      ? { id: b.id, name: b.name, description: b.description ?? '', icon: b.icon, color: b.color, kind: b.kind, patreon_tier: b.patreon_tier ?? '', sort: b.sort, isNew: false }
      : { id: '', name: '', description: '', icon: '★', color: '#b8892c', kind: 'award', patreon_tier: '', sort: (this.catalogue().at(-1)?.sort ?? 0) + 10, isNew: true });
  }

  protected previewBadge(f: BadgeEdit) {
    return { id: f.id || 'new', name: f.name || 'Badge', icon: f.icon, color: f.color, kind: f.kind, description: f.description };
  }

  protected async saveBadge(): Promise<void> {
    const f = this.badge();
    if (!f) return;
    const ok = await this.run(async () => {
      await this.hub.putBadge(f.id.trim(), {
        name: f.name.trim(), description: f.description.trim(), icon: f.icon.trim(), color: f.color, kind: f.kind,
        patreon_tier: f.kind === 'patron' ? f.patreon_tier.trim() || null : null, sort: +f.sort || 0,
      });
      this.catalogue.set(await this.hub.badges());
    }, `Badge ${f.id} saved`);
    if (ok) this.badge.set(null);
  }

  protected async deleteBadge(id: string): Promise<void> {
    if (this.armed() !== 'b:' + id) {
      this.armed.set('b:' + id);
      return;
    }
    this.armed.set(null);
    if (await this.run(() => this.hub.deleteBadge(id), `Badge ${id} deleted`)) {
      this.catalogue.update((l) => l.filter((b) => b.id !== id));
      if (this.badge()?.id === id) this.badge.set(null);
    }
  }

  // ---- worlds
  protected editWorld(w: AdminWorld | null): void {
    this.world.set(w
      ? { id: w.id, name: w.name, description: w.description, pack: w.pack, speed: w.speed, api_url: w.api_url, internal_url: w.internal_url ?? '', status: w.status,
          founders_only: w.founders_only, patrons_early: w.patrons_early, starts: toLocal(w.starts_at), ends: toLocal(w.ends_at), sort: w.sort, isNew: false }
      : { id: '', name: '', description: '', pack: '', speed: 1, api_url: '', internal_url: '', status: 'upcoming', founders_only: false, patrons_early: false,
          starts: '', ends: '', sort: (this.adminWorlds().at(-1)?.sort ?? 0) + 10, isNew: true });
  }

  protected async saveWorld(): Promise<void> {
    const f = this.world();
    if (!f) return;
    const ok = await this.run(async () => {
      await this.hub.putWorld(f.id.trim(), {
        name: f.name.trim(), description: f.description.trim(), pack: f.pack.trim(), speed: +f.speed || 1, api_url: f.api_url.trim(),
        internal_url: f.internal_url.trim(), status: f.status, founders_only: f.founders_only, patrons_early: f.patrons_early,
        starts_at: fromLocal(f.starts), ends_at: fromLocal(f.ends), sort: +f.sort || 0,
      });
      this.adminWorlds.set(await this.hub.adminWorlds());
    }, `World ${f.id} saved`);
    if (ok) this.world.set(null);
  }

  protected async deleteWorld(id: string): Promise<void> {
    if (this.armed() !== 'w:' + id) {
      this.armed.set('w:' + id);
      return;
    }
    this.armed.set(null);
    if (await this.run(() => this.hub.deleteWorld(id), `World ${id} removed from the list`)) {
      this.adminWorlds.update((l) => l.filter((w) => w.id !== id));
      if (this.world()?.id === id) this.world.set(null);
    }
  }

  protected close(): void {
    void this.router.navigateByUrl('/settings');
  }
}
