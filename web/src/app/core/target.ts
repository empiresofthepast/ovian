import { Signal, effect, inject, signal } from '@angular/core';
import { Api } from './api.service';
import { MapVillage } from './models';

/**
 * The city at the rally point's target coordinates, looked up as they change
 * (null while unknown, undefined for an empty tile). Call in an injection context.
 */
export function watchTarget(x: Signal<number>, y: Signal<number>): Signal<MapVillage | undefined | null> {
  const api = inject(Api);
  const target = signal<MapVillage | undefined | null>(null);
  let seq = 0;
  effect((onCleanup) => {
    const tx = Number(x()), ty = Number(y());
    const mine = ++seq;
    target.set(null);
    const timer = setTimeout(() => {
      api.cityAt(tx, ty).then((v) => mine === seq && target.set(v)).catch(() => undefined);
    }, 250);
    onCleanup(() => clearTimeout(timer));
  });
  return target;
}

/** Attack and raid are not allowed against cities under beginner protection. */
export function hostileAllowed(target: MapVillage | undefined | null): boolean {
  return !target?.protected;
}
