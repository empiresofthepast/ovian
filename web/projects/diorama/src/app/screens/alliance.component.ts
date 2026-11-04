import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { GameStore } from '@core/game.store';
import { ChatMessage, MyAlliance } from '@core/models';
import { UI } from '../ui';

const KIND: Record<string, string> = { ally: 'Allied', nap: 'Non-aggression pact', war: 'At war' };

@Component({
  selector: 'dio-alliance',
  imports: [FormsModule, ...UI],
  template: `
    <section class="hud-panel dialog alliance" role="dialog" aria-label="Alliance">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      @if (mine(); as m) {
        @if (m.alliance; as a) {
          <h2 class="selection__title">[{{ a.tag }}] {{ a.name }} <span class="muted small">· {{ a.members.length }} members · population {{ a.population | n }}</span></h2>
          @if (a.description) {<p class="muted">{{ a.description }}</p>}
          <div class="alliance__cols">
            <div>
              <h3 class="subhead">Members</h3>
              <div class="table-wrap"><table class="table">
                <thead><tr><th>Player</th><th>Role</th><th class="num">Cities</th><th class="num">Population</th><th></th></tr></thead>
                <tbody>
                  @for (p of a.members; track p.id) {
                    <tr [class.me]="p.id === game.me()?.id">
                      <td><strong>{{ p.username }}</strong></td>
                      <td>{{ p.role }}</td>
                      <td class="num">{{ p.villages }}</td>
                      <td class="num">{{ p.population | n }}</td>
                      <td class="actions">
                        @if (m.role === 'leader' && p.id !== game.me()?.id) {
                          @if (p.role === 'member') {<button class="btn btn--small" (click)="role(p.id, 'officer')" title="Make officer">▲</button>}
                          @if (p.role === 'officer') {<button class="btn btn--small" (click)="role(p.id, 'member')" title="Make member">▼</button>}
                          <button class="btn btn--small" (click)="role(p.id, 'leader')" title="Hand over the leadership">♛</button>
                        }
                        @if (rank(m.role) > rank(p.role) && p.id !== game.me()?.id && m.role !== 'member') {
                          <button class="btn btn--small" (click)="kick(p.id)" title="Remove from the alliance">✕</button>
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table></div>
              @if (m.role !== 'member') {
                <form class="row-form" (ngSubmit)="invite()">
                  <input name="invitee" [(ngModel)]="invitee" placeholder="Player name" aria-label="Player to invite" />
                  <button class="btn btn--gold btn--small">Invite</button>
                </form>
                @for (s of m.sent_invites ?? []; track s.id) {
                  <div class="small muted">Invited {{ s.username }} <button class="btn btn--small" (click)="withdraw(s.id)">withdraw</button></div>
                }
              }

              <h3 class="subhead">Diplomacy</h3>
              @for (d of a.diplomacy; track d.other_id) {
                <div class="small dip" [class.bad]="d.kind === 'war'">[{{ d.tag }}] {{ d.name }}: {{ kindText(d.kind) }}@if (d.status === 'proposed') { <span class="muted">(proposed, awaiting them)</span>}</div>
              } @empty {<p class="small muted">No pacts and no wars.</p>}
              @for (p of a.proposals; track p.other_id) {
                <div class="small dip">[{{ p.tag }}] {{ p.name }} proposes: {{ kindText(p.kind) }}
                  @if (m.role !== 'member') {<button class="btn btn--small btn--gold" (click)="stance(p.tag, p.kind)">Accept</button>}
                </div>
              }
              @if (m.role !== 'member') {
                <form class="row-form" (ngSubmit)="stance(dipTag, dipKind)">
                  <input name="tag" [(ngModel)]="dipTag" placeholder="Alliance tag" aria-label="Alliance tag" />
                  <select name="kind" [(ngModel)]="dipKind" aria-label="Relation">
                    <option value="ally">Propose alliance</option>
                    <option value="nap">Propose non-aggression</option>
                    <option value="war">Declare war</option>
                    <option value="none">End relations</option>
                  </select>
                  <button class="btn btn--small">Send</button>
                </form>
              }
              <p class="small muted">Members, allies and pact partners cannot attack, raid or scout one another.</p>
              <button class="btn btn--small" (click)="leave()">Leave the alliance</button>
            </div>
            <div class="alliance__chat">
              <h3 class="subhead">Alliance chat</h3>
              <div class="chatlog">
                @for (c of chat(); track c.id) {
                  <div class="small"><strong>{{ c.from.name }}</strong> <span class="muted">{{ c.at | clock }}</span> {{ c.text }}</div>
                } @empty {<p class="small muted">No messages yet.</p>}
              </div>
              <form class="row-form" (ngSubmit)="say()">
                <input name="say" [(ngModel)]="text" maxlength="500" placeholder="Write to your alliance" aria-label="Message" />
                <button class="btn btn--small">Send</button>
              </form>
              <h3 class="subhead">Members' battles</h3>
              @for (r of reports(); track r.id) {
                <div class="small"><span class="muted">{{ r.created_at | clock }}</span> {{ r.username }}: {{ r.title }}</div>
              } @empty {<p class="small muted">No battles yet.</p>}
            </div>
          </div>
        } @else {
          <h2 class="selection__title">Alliance</h2>
          <p class="muted">You are not in an alliance. Members cannot attack each other, share a chat and see each other's battles; alliances make pacts and wars.</p>
          @for (i of m.invites; track i.id) {
            <div class="dip">Invitation from <strong>[{{ i.tag }}] {{ i.name }}</strong>@if (i.invited_by) { (by {{ i.invited_by }})}
              <button class="btn btn--gold btn--small" (click)="join(i.id)">Join</button>
              <button class="btn btn--small" (click)="decline(i.id)">Decline</button>
            </div>
          }
          <h3 class="subhead">Found an alliance</h3>
          <form class="found" (ngSubmit)="found()">
            <input name="name" [(ngModel)]="name" placeholder="Name" maxlength="40" aria-label="Alliance name" />
            <input name="tag" [(ngModel)]="tag" placeholder="Tag (2-8)" maxlength="8" aria-label="Tag" />
            <input name="desc" [(ngModel)]="description" placeholder="What you stand for" aria-label="Description" />
            <button class="btn btn--gold btn--small">Found</button>
          </form>
        }
      }
      <h3 class="subhead">All alliances</h3>
      <div class="table-wrap"><table class="table">
        <thead><tr><th class="num">#</th><th>Alliance</th><th class="num">Members</th><th class="num">Population</th><th class="num">Culture</th></tr></thead>
        <tbody>
          @for (a of all(); track a.id) {
            <tr><td class="num">{{ a.rank }}</td><td>[{{ a.tag }}] {{ a.name }}</td><td class="num">{{ a.members }}</td><td class="num">{{ a.population | n }}</td><td class="num">{{ a.culture | n }}</td></tr>
          } @empty {<tr><td colspan="5" class="muted">No alliances yet.</td></tr>}
        </tbody>
      </table></div>
    </section>
  `,
})
export class AllianceComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly mine = signal<MyAlliance | null>(null);
  protected readonly all = signal<any[]>([]);
  protected readonly chat = signal<ChatMessage[]>([]);
  protected readonly reports = signal<any[]>([]);
  protected name = '';
  protected tag = '';
  protected description = '';
  protected invitee = '';
  protected dipTag = '';
  protected dipKind = 'nap';
  protected text = '';
  protected readonly inAlliance = computed(() => !!this.mine()?.alliance);

  constructor() {
    void this.load();
    const sub = this.game.allianceEvents.subscribe((e) => {
      if (e.type === 'alliance.message') this.chat.update((c) => [...c, e.data].slice(-200));
      else void this.load();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  private async load(): Promise<void> {
    const [m, all] = await Promise.all([this.api.myAlliance(), this.api.alliances()]);
    this.mine.set(m);
    this.all.set(all);
    if (m.alliance) {
      this.chat.set(await this.api.allianceMessages());
      this.reports.set(await this.api.allianceReports());
    }
  }

  private async run(fn: () => Promise<unknown>, ok?: string): Promise<boolean> {
    try {
      await fn();
      if (ok) this.game.toast(ok, 'good');
      await this.load();
      return true;
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
      return false;
    }
  }

  protected rank(role: string | null): number {
    return { leader: 3, officer: 2, member: 1 }[role ?? 'member'] ?? 0;
  }

  protected kindText(k: string): string {
    return KIND[k] ?? k;
  }

  protected async found(): Promise<void> {
    await this.run(() => this.api.foundAlliance(this.name, this.tag, this.description), 'Alliance founded');
  }
  protected join(id: number): void { void this.run(() => this.api.joinAlliance(id), 'Welcome to the alliance'); }
  protected decline(id: number): void { void this.run(() => this.api.declineInvite(id)); }
  protected leave(): void { void this.run(() => this.api.leaveAlliance(), 'You left the alliance'); }
  protected kick(id: number): void { void this.run(() => this.api.kick(id)); }
  protected role(id: number, role: string): void { void this.run(() => this.api.setRole(id, role)); }
  protected withdraw(id: number): void { void this.run(() => this.api.withdrawInvite(id)); }

  protected async invite(): Promise<void> {
    if (await this.run(() => this.api.inviteToAlliance(this.invitee), `${this.invitee} invited`)) this.invitee = '';
  }

  protected async stance(tag: string, kind: string): Promise<void> {
    if (await this.run(() => this.api.diplomacy(tag, kind), 'Done')) this.dipTag = '';
  }

  protected async say(): Promise<void> {
    const t = this.text.trim();
    if (!t) return;
    try {
      await this.api.allianceSay(t);
      this.text = '';
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
