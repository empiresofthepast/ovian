import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { UI } from '../../shared/ui';

@Component({
  selector: 'ov-login',
  imports: [FormsModule, ...UI],
  template: `
    <div class="login">
      <section class="login__card panel">
        <h1 class="login__title"><ov-icon key="app.logo" />{{ 'app.title' | label }}</h1>
        @if (pack(); as p) {
          <p class="muted">{{ p.name }}: {{ p.description }}</p>
        } @else {
          <p class="bad">The game server cannot be reached. Try again in a moment.</p>
        }

        <div class="tabs" role="tablist">
          <button role="tab" class="tabs__tab" [class.tabs__tab--active]="mode() === 'login'" (click)="mode.set('login')">
            {{ 'login.signin' | label: 'Sign in' }}
          </button>
          <button role="tab" class="tabs__tab" [class.tabs__tab--active]="mode() === 'register'" (click)="mode.set('register')">
            {{ 'login.register' | label: 'Found a village' }}
          </button>
        </div>

        <form class="form" (ngSubmit)="submit()">
          <label class="field">
            <span>{{ 'login.username' | label: 'Name' }}</span>
            <input name="username" [(ngModel)]="username" autocomplete="username" required minlength="3" maxlength="24" />
          </label>
          <label class="field">
            <span>{{ 'login.password' | label: 'Password' }}</span>
            <input name="password" type="password" [(ngModel)]="password" required minlength="8"
                   [attr.autocomplete]="mode() === 'login' ? 'current-password' : 'new-password'" />
          </label>

          @if (mode() === 'register') {
            <fieldset class="tribes">
              <legend>{{ 'login.tribe' | label: 'Tribe' }}</legend>
              @for (t of pack()?.tribes ?? []; track t.id) {
                <label class="tribe" [class.tribe--active]="tribe === t.id">
                  <input type="radio" name="tribe" [value]="t.id" [(ngModel)]="tribe" />
                  <ov-icon [key]="'tribe.' + t.id" />
                  <strong>{{ t.id | name: 'tribe' }}</strong>
                  <small class="muted">{{ t.description }}</small>
                </label>
              }
            </fieldset>
          }

          @if (error()) {<p class="bad" role="alert">{{ error() }}</p>}
          <button class="btn btn--primary" type="submit" [disabled]="busy()">
            {{ mode() === 'login' ? ('login.signin' | label: 'Sign in') : ('login.register' | label: 'Found a village') }}
          </button>
        </form>
      </section>
    </div>
  `,
})
export class LoginComponent {
  private readonly game = inject(GameStore);
  private readonly router = inject(Router);
  protected readonly pack = inject(EngineService).pack;
  protected readonly mode = signal<'login' | 'register'>('login');
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected username = '';
  protected password = '';
  protected tribe = '';
  private readonly firstTribe = computed(() => this.pack()?.tribes[0]?.id ?? '');

  protected async submit(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      if (this.mode() === 'login') await this.game.login(this.username, this.password);
      else await this.game.register(this.username, this.password, this.tribe || this.firstTribe());
      await this.router.navigateByUrl('/village');
    } catch (e) {
      this.error.set(this.game.errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
