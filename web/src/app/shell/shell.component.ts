import { Component, computed, inject, signal } from '@angular/core';
import { CONFIG } from '../core/config';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { GameStore } from '../core/game.store';
import { RealtimeService } from '../core/realtime.service';
import { SkinService } from '../core/skin.service';
import { FEATURES } from '../features';
import { ChatComponent } from '../features/chat/chat.component';
import { UI } from '../shared/ui';
import { EngineService } from '../core/engine.service';

@Component({
  selector: 'ov-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, ChatComponent, ...UI],
  template: `
    <div class="shell" [class.shell--side]="sideNav()" [class.shell--chat]="chatOpen()">
      <header class="topbar">
        <a class="brand" routerLink="/village"><ov-icon key="app.logo" />{{ 'app.title' | label }}</a>

        @if (game.me(); as me) {
          <label class="village-picker">
            <span class="sr-only">Village</span>
            <select [value]="game.village()?.id" (change)="pick($any($event.target).value)">
              @for (v of me.villages; track v.id) {
                <option [value]="v.id">{{ v.name }} ({{ v.x }}|{{ v.y }})</option>
              }
            </select>
          </label>
        }

        <div class="resbar" role="status" aria-label="Resources">
          @for (r of resources(); track r.id) {
            <div class="resbar__item" [class.resbar__item--full]="r.full" [title]="r.name + ': ' + r.rate + '/h'">
              <ov-icon [key]="'resource.' + r.id" [alt]="r.name" />
              <span class="resbar__amount">{{ r.amount }}</span>
              <span class="resbar__cap">/{{ r.cap }}</span>
              <span class="resbar__rate" [class.neg]="r.negative">{{ r.rate }}/h</span>
            </div>
          }
        </div>

        <div class="topbar__end">
          <span class="dot" [class]="'dot--' + realtime.status()" [title]="'Realtime: ' + realtime.status()"></span>
          <button class="btn btn--ghost" (click)="chatOpen.set(!chatOpen())" [attr.aria-pressed]="chatOpen()">
            <ov-icon key="nav.chat" /> {{ 'nav.chat' | label: 'Chat' }}
          </button>
          @if (dioramaUrl) {<a class="btn btn--ghost" [href]="dioramaUrl" title="Your city in 3D">{{ 'nav.diorama' | label: '3D view' }}</a>}
          <button class="btn btn--ghost" (click)="logout()">{{ 'nav.logout' | label: 'Log out' }}</button>
        </div>
      </header>

      <nav class="nav" aria-label="Main">
        @for (f of nav(); track f.id) {
          <a class="nav__link" [routerLink]="'/' + f.path" routerLinkActive="nav__link--active">
            <ov-icon [key]="'nav.' + f.id" />
            <span>{{ 'nav.' + f.id | label }}</span>
            @if (f.id === 'reports' && (game.me()?.unread_reports ?? 0) > 0) {
              <span class="badge">{{ game.me()!.unread_reports }}</span>
            }
          </a>
        }
      </nav>

      @if (game.inspecting()) {
        <div class="inspect-banner" role="status">👁 {{ game.village()?.owner?.name }}'s city {{ game.village()?.name }}, read-only.
          <button class="btn btn--small" (click)="game.home()">Back to my city</button></div>
      }
      <main class="main"><router-outlet /></main>

      @if (chatOpen()) {
        <aside class="chat-dock"><ov-chat /></aside>
      }

      <div class="toasts" aria-live="polite">
        @for (t of game.toasts(); track t.id) {
          <div class="toast" [class]="'toast toast--' + t.tone">{{ t.text }}</div>
        }
      </div>
    </div>
  `,
})
export class ShellComponent {
  protected readonly game = inject(GameStore);
  protected readonly realtime = inject(RealtimeService);
  private readonly skin = inject(SkinService);
  private readonly engine = inject(EngineService);
  private readonly router = inject(Router);
  protected readonly dioramaUrl = inject(CONFIG).dioramaUrl ?? '';
  protected readonly chatOpen = signal(false);
  protected readonly sideNav = computed(() => this.skin.skin()?.layout?.nav === 'side');
  protected readonly nav = computed(() => FEATURES.filter((f) => f.nav && !this.skin.hidden(f.id) && (!f.admin || !!this.game.me()?.is_admin)));

  protected readonly resources = computed(() => {
    const v = this.game.village();
    const now = this.game.resources();
    if (!v) return [];
    return (this.engine.pack()?.resources ?? []).map((r) => {
      const cap = v.economy.capacity[r.id] ?? 0;
      const rate = v.economy.production[r.id] ?? 0;
      const amount = now[r.id] ?? 0;
      return {
        id: r.id,
        name: this.skin.label(`resource.${r.id}`, r.name),
        amount: Math.floor(amount).toLocaleString(),
        cap: Math.round(cap).toLocaleString(),
        rate: Math.round(rate).toLocaleString(),
        negative: rate < 0,
        full: amount >= cap - 0.5,
      };
    });
  });

  protected pick(id: string): void {
    void this.game.selectVillage(Number(id));
  }

  protected logout(): void {
    this.game.logout();
    void this.router.navigateByUrl('/login');
  }
}
