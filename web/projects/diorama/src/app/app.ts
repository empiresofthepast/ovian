import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { GameStore } from '@core/game.store';
import { RealtimeService } from '@core/realtime.service';

/** What Patreon's return (?patreon=…) means, as a toast. */
const PATREON: Record<string, [string, 'good' | 'bad' | 'info']> = {
  linked: ['Patreon linked. Thank you for supporting Ovian!', 'good'],
  cancelled: ['Patreon linking cancelled.', 'info'],
  error: ['Patreon could not be linked. Try again later.', 'bad'],
  patreon_taken: ['That Patreon account is already linked to another Ovian account.', 'bad'],
};

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

  constructor() {
    this.patreonReturn();
    // badges given or taken on the hub reach the player live
    inject(RealtimeService).messages.subscribe(({ event }) => {
      if (event.type !== 'player.badges') return;
      const d = event.data as { badges?: unknown[]; founder_no?: number | null };
      this.game.me.update((m) => m && { ...m, badges: (d.badges ?? []) as typeof m.badges, founder_no: d.founder_no ?? null });
    });
  }

  /** Patreon sends the browser back to the site root with ?patreon=linked|cancelled|error|patreon_taken. */
  private patreonReturn(): void {
    const params = new URLSearchParams(location.search);
    const result = params.get('patreon');
    if (!result) return;
    params.delete('patreon');
    const rest = params.toString();
    history.replaceState(history.state, '', location.pathname + (rest ? `?${rest}` : '') + location.hash);
    const [text, tone] = PATREON[result] ?? [`Patreon: ${result}`, 'info'];
    setTimeout(() => this.game.toast(text, tone));
  }
}
