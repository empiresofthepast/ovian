import { Injectable, effect, signal } from '@angular/core';

export interface ScenePrefs {
  /** Sun shadows. The most expensive effect; turn off on weak GPUs. */
  shadows: boolean;
  /** Render resolution: 'low' (1×), 'medium' (1.5×), 'high' (device, up to 2×). */
  quality: 'low' | 'medium' | 'high';
  /** Level badges above buildings and fields. */
  badges: boolean;
  /** Forest around the town. */
  decor: boolean;
}

const KEY = 'ovian.diorama.prefs';
const DEFAULTS: ScenePrefs = { shadows: true, quality: 'high', badges: true, decor: true };

/** Display preferences of this browser (not part of the game state). */
@Injectable({ providedIn: 'root' })
export class PrefsService {
  readonly scene = signal<ScenePrefs>(load());

  constructor() {
    effect(() => {
      try {
        localStorage.setItem(KEY, JSON.stringify(this.scene()));
      } catch {
        // storage unavailable: preferences last for this visit only
      }
    });
  }

  set<K extends keyof ScenePrefs>(key: K, value: ScenePrefs[K]): void {
    this.scene.update((p) => ({ ...p, [key]: value }));
  }
}

function load(): ScenePrefs {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') };
  } catch {
    return { ...DEFAULTS };
  }
}
