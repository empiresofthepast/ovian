import { Injectable } from '@angular/core';

/**
 * UI text lookup used by the shared core. Each front end provides its own
 * implementation (the ledger client maps it to the active skin).
 */
@Injectable({ providedIn: 'root', useFactory: () => new PlainLabels() })
export abstract class Labels {
  /** Text for `key`, or `fallback` (default: the key itself) when there is none. */
  abstract label(key: string, fallback?: string): string;
}

export class PlainLabels extends Labels {
  constructor(private readonly table: Record<string, string> = {}) {
    super();
  }
  label(key: string, fallback?: string): string {
    return this.table[key] ?? fallback ?? key;
  }
}
