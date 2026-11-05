import { Injectable, inject, signal } from '@angular/core';
import { selectedWorld } from '../../core/config';
import { Hub, HubMe } from '../../core/hub';

/** Patreon sends the browser back with ?patreon=linked|cancelled|error|patreon_taken: read it once, then strip it. */
function takePatreonReturn(): string | null {
  try {
    const url = new URL(location.href);
    const code = url.searchParams.get('patreon');
    if (code) {
      url.searchParams.delete('patreon');
      history.replaceState(history.state, '', url.pathname + url.search + url.hash);
    }
    return code;
  } catch {
    return null;
  }
}

const PATREON_RETURN = takePatreonReturn();

/** The ledger's view of the hub account: its profile (cached) and the world being played. */
@Injectable({ providedIn: 'root' })
export class HubSession {
  readonly hub = inject(Hub);
  readonly me = signal<HubMe | null>(null);
  /** The world this page plays, as chosen through the hub. */
  readonly world = this.hub.enabled ? selectedWorld() : null;
  private patreon = PATREON_RETURN;
  private loading: Promise<HubMe | null> | null = null;

  /** Load (or reload with `force`) the hub profile; null when not signed in to the hub. */
  load(force = false): Promise<HubMe | null> {
    if (!this.hub.enabled || !this.hub.token()) {
      this.me.set(null);
      return Promise.resolve(null);
    }
    if (!this.loading || force) {
      this.loading = this.hub.me().then(
        (me) => {
          this.me.set(me);
          return me;
        },
        () => {
          this.me.set(null);
          return null;
        },
      );
    }
    return this.loading;
  }

  /** The Patreon return code, once. */
  patreonReturn(): string | null {
    const code = this.patreon;
    this.patreon = null;
    return code;
  }

  /** Log out of the hub and the world, back to the hub login (full reload: the API must forget the world). */
  logout(): void {
    this.hub.logout();
    this.me.set(null);
    location.assign(document.baseURI);
  }

  /** Start playing the world just entered: reload so the API, the broker and the engine point at it. */
  play(): void {
    location.assign(document.baseURI);
  }
}

/** Text and tone for a Patreon return code. */
export function patreonNotice(code: string): { text: string; tone: 'good' | 'bad' | 'info'; key: string } {
  switch (code) {
    case 'linked':
      return { key: 'hub.patreon_linked', text: 'Your Patreon account is linked. Thank you for supporting Ovian!', tone: 'good' };
    case 'cancelled':
      return { key: 'hub.patreon_cancelled', text: 'Patreon linking was cancelled.', tone: 'info' };
    case 'patreon_taken':
      return { key: 'error.patreon_taken', text: 'This Patreon account is linked to another player.', tone: 'bad' };
    default:
      return { key: 'hub.patreon_error', text: 'Patreon could not be linked. Try again later.', tone: 'bad' };
  }
}
