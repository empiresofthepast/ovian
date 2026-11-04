import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { CONFIG } from '@core/config';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

@Component({
  selector: 'dio-login',
  imports: [FormsModule, ...UI],
  template: `
    <main class="welcome">
      <header class="welcome__head">
        <h1 class="welcome__title">Ovian</h1>
        <p class="welcome__sub">{{ world() }}</p>
      </header>

      <section class="hud-panel welcome__panel">
        <div class="tabs" role="tablist">
          <button role="tab" [attr.aria-selected]="mode() === 'login'" (click)="mode.set('login')">Return</button>
          <button role="tab" [attr.aria-selected]="mode() === 'register'" (click)="mode.set('register')">Found a city</button>
        </div>

        <form (ngSubmit)="submit()" class="welcome__form">
          <label>Name <input name="u" [(ngModel)]="username" autocomplete="username" required minlength="3" /></label>
          <label>Password <input name="p" type="password" [(ngModel)]="password" [autocomplete]="mode() === 'login' ? 'current-password' : 'new-password'" required minlength="8" /></label>

          @if (mode() === 'register') {
            <fieldset class="civs">
              <legend>Civilization</legend>
              <div class="civs__grid">
                @for (t of tribes(); track t.id) {
                  <button type="button" class="civ" [class.civ--on]="tribe() === t.id" (click)="tribe.set(t.id)" [attr.aria-pressed]="tribe() === t.id" [title]="t.name">
                    @if (t.emblem) {<img [src]="t.emblem" alt="" />}
                    <span>{{ t.name }}</span>
                  </button>
                }
              </div>
              @if (chosen(); as c) {
                <div class="civ-info">
                  <h3 class="subhead">{{ c.name }}</h3>
                  <p class="small">{{ c.description }}</p>
                  <div class="roster">
                    @for (u of c.units; track u.id) {
                      <div class="roster__unit" [title]="u.name + ' — attack ' + u.attack + ', defense ' + u.defense">
                        <dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" />
                        <span class="small">{{ u.name }}</span>
                      </div>
                    }
                  </div>
                </div>
              }
            </fieldset>
          }

          @if (error()) {<p class="bad">{{ error() }}</p>}
          <button class="btn btn--gold btn--wide" [disabled]="busy()">{{ mode() === 'login' ? 'Enter' : 'Found the city' }}</button>
        </form>
      </section>

      <footer class="welcome__foot small muted">
        Art from <a href="https://play0ad.com" target="_blank" rel="noopener">0 A.D.</a> by Wildfire Games, CC BY-SA 3.0.
        @if (ledgerUrl) { · <a [href]="ledgerUrl">Ledger view</a>}
      </footer>
    </main>
  `,
})
export class LoginComponent {
  private readonly game = inject(GameStore);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  protected readonly ledgerUrl = inject(CONFIG).ledgerUrl ?? '';
  protected readonly mode = signal<'login' | 'register'>('register');
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly tribe = signal<string | null>(null);
  protected username = '';
  protected password = '';

  protected readonly world = computed(() => {
    const p = this.engine.pack();
    return p ? `${p.name} · ${p.description}` : 'The game server cannot be reached.';
  });

  protected readonly tribes = computed(() =>
    (this.engine.pack()?.tribes ?? []).map((t) => ({ ...t, emblem: this.art.url(this.art.civ(t.id)?.emblem) })),
  );

  protected readonly chosen = computed(() => {
    const id = this.tribe() ?? this.tribes()[0]?.id;
    const t = this.tribes().find((x) => x.id === id);
    if (!t) return null;
    const units = (this.engine.pack()?.units ?? [])
      .filter((u) => u.tribe === t.id)
      .map((u) => ({ id: u.id, name: u.name, attack: u.attack, defense: `${u.defense.infantry}/${u.defense.cavalry}`, icon: this.art.unitIcon(u.id) }));
    return { ...t, units };
  });

  async submit(): Promise<void> {
    this.error.set('');
    this.busy.set(true);
    try {
      if (this.mode() === 'login') await this.game.login(this.username, this.password);
      else await this.game.register(this.username, this.password, this.tribe() ?? this.tribes()[0]?.id ?? '');
      await this.router.navigateByUrl('/');
    } catch (e) {
      this.error.set(this.game.errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
