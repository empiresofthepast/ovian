import { Pipe, PipeTransform, inject } from '@angular/core';
import { EngineService } from '../core/engine.service';
import { Government, ResourceMap, Season } from '../core/models';
import { SkinService } from '../core/skin.service';

/** Signed percentage of a fraction: 0.15 → "+15%". */
export function pct(f: number): string {
  const n = Math.round(f * 1000) / 10;
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n)}%`;
}

/** Signed number: 5 → "+5". */
export function signed(n: number): string {
  const r = Math.round(n * 10) / 10;
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r)}`;
}

type Namer = (id: string) => string;

function production(map: ResourceMap | undefined, name: Namer): string[] {
  return Object.entries(map ?? {}).filter(([, v]) => v).map(([k, v]) => `${pct(v)} ${name(k)}`);
}

/** What a government changes, as short phrases. */
export function governmentEffects(g: Government, name: Namer): string[] {
  const out = production(g.production, name);
  if (g.attack) out.push(`${pct(g.attack)} attack`);
  if (g.defense) out.push(`${pct(g.defense)} defense`);
  if (g.contentment) out.push(`${signed(g.contentment)} contentment`);
  if (g.favor) out.push(`${pct(g.favor)} favor`);
  if (g.trade_speed) out.push(`${pct(g.trade_speed)} merchant speed`);
  if (g.march_speed) out.push(`${pct(g.march_speed)} march speed`);
  return out;
}

/** What a season changes, as short phrases. */
export function seasonEffects(s: Season, name: Namer): string[] {
  const out = production(s.production, name);
  if (s.travel && s.travel !== 1) out.push(`travel time ×${s.travel}`);
  if (s.contentment) out.push(`${signed(s.contentment)} contentment`);
  return out;
}

/** Resource map as text, with "all" and "upkeep" spelled out: `{all: 6000} | res`. */
@Pipe({ name: 'res', pure: false })
export class ResPipe implements PipeTransform {
  private readonly namer = resourceNamer();
  transform(map: ResourceMap | null | undefined): string {
    return Object.entries(map ?? {})
      .filter(([, v]) => v)
      .map(([k, v]) => `${Math.round(v).toLocaleString()} ${this.namer(k)}`)
      .join(', ');
  }
}

/** Resource id → display name; call in an injection context. */
export function resourceNamer(): Namer {
  const skin = inject(SkinService);
  const engine = inject(EngineService);
  const named = (id: string): string => {
    if (id === 'all') return skin.label('res.all', 'of each resource');
    if (id === 'upkeep') {
      const food = engine.pack()?.resources.find((r) => r.upkeep)?.id;
      return food ? named(food) : 'food';
    }
    return skin.label(`resource.${id}`, engine.pack()?.resources.find((r) => r.id === id)?.name ?? id);
  };
  return named;
}
