import { Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { GameStore } from '@core/game.store';
import { Hub } from '@core/hub';

/** Sign in to (or create) the hub account: one account for every world. */
@Component({
  selector: 'dio-hub-signin',
  imports: [FormsModule],
  template: `
    <div class="tabs" role="tablist">
      <button role="tab" type="button" [attr.aria-selected]="mode() === 'login'" (click)="mode.set('login')">Return</button>
      <button role="tab" type="button" [attr.aria-selected]="mode() === 'register'" (click)="mode.set('register')">Create an account</button>
    </div>
    <form (ngSubmit)="submit()" class="welcome__form">
      <label>Name <input name="u" [(ngModel)]="username" autocomplete="username" required minlength="3" maxlength="24" /></label>
      <label>Password <input name="p" type="password" [(ngModel)]="password" [autocomplete]="mode() === 'login' ? 'current-password' : 'new-password'" required minlength="8" /></label>
      @if (mode() === 'register') {
        <label>Email <span class="muted small hub-optional">optional, only to recover the account</span>
          <input name="e" type="email" [(ngModel)]="email" autocomplete="email" /></label>
        <p class="small muted hub-note">One account opens every world of Ovian. You found a city, and choose your people, the first time you enter a world.</p>
      }
      @if (error()) {<p class="bad">{{ error() }}</p>}
      <button class="btn btn--gold btn--wide" [disabled]="busy()">{{ mode() === 'login' ? 'Sign in' : 'Create the account' }}</button>
    </form>
  `,
})
export class HubSigninComponent {
  private readonly hub = inject(Hub);
  private readonly game = inject(GameStore);
  readonly signedIn = output<void>();
  protected readonly mode = signal<'login' | 'register'>('login');
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected username = '';
  protected password = '';
  protected email = '';

  protected async submit(): Promise<void> {
    this.error.set('');
    this.busy.set(true);
    try {
      if (this.mode() === 'login') await this.hub.login(this.username.trim(), this.password);
      else await this.hub.register(this.username.trim(), this.password, this.email.trim() || undefined);
      this.password = '';
      this.signedIn.emit();
    } catch (e) {
      this.error.set(this.game.errorText(e));
    } finally {
      this.busy.set(false);
    }
  }
}
