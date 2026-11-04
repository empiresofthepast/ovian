import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { GameStore } from '@core/game.store';

@Component({
  selector: 'dio-root',
  imports: [RouterOutlet],
  template: `
    <router-outlet />
    <div class="toasts" aria-live="polite">
      @for (t of game.toasts(); track t.id) {
        <div class="toast" [class.toast--good]="t.tone === 'good'" [class.toast--bad]="t.tone === 'bad'">{{ t.text }}</div>
      }
    </div>
  `,
})
export class App {
  protected readonly game = inject(GameStore);
}
