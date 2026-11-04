import { EngineService } from './engine.service';
import { ResourceMap, TechDef, VillageState, VillageView } from './models';

export type TechStatus = 'done' | 'queued' | 'ready' | 'locked';

export interface TechOption {
  def: TechDef;
  status: TechStatus;
  cost: ResourceMap;
  seconds: number | null;
  /** Why it cannot be researched now (error code), if so. */
  error: string;
  /** Human-readable missing prerequisites. */
  needs: string[];
  /** Units this tech unlocks for the given tribe. */
  unlocks: string[];
}

/** Techs researched in `building`, with their status for the given village. */
export function techOptions(engine: EngineService, view: VillageView, live: VillageState, building: string, tribe: string | null): TechOption[] {
  const done = new Set(live.techs ?? []);
  const queued = (view.research ?? []).map((r) => r.tech);
  const levels = new Map<string, number>();
  for (const s of live.slots) if (s.building) levels.set(s.building, Math.max(levels.get(s.building) ?? 0, s.level));
  return engine.techsIn(building).map((def) => {
    const unlocks = (engine.pack()?.units ?? []).filter((u) => (!tribe || u.tribe === tribe) && u.techs?.includes(def.id)).map((u) => u.name);
    const needs = [
      ...((levels.get(def.building) ?? 0) < def.level ? [`${engine.building(def.building)?.name ?? def.building} ${def.level}`] : []),
      ...Object.entries(def.requires ?? {}).filter(([b, l]) => (levels.get(b) ?? 0) < l).map(([b, l]) => `${engine.building(b)?.name ?? b} ${l}`),
      ...(def.after ?? []).filter((a) => !done.has(a)).map((a) => engine.tech(a)?.name ?? a),
    ];
    if (done.has(def.id)) return { def, status: 'done', cost: def.cost, seconds: null, error: '', needs: [], unlocks };
    if (queued.includes(def.id)) return { def, status: 'queued', cost: def.cost, seconds: null, error: '', needs: [], unlocks };
    const plan = engine.planResearch(live, queued, def.id);
    if (plan?.ok) return { def, status: 'ready', cost: plan.plan.cost, seconds: plan.plan.seconds, error: '', needs, unlocks };
    const error = plan && !plan.ok ? plan.error : needs.length ? 'requirements' : '';
    const status: TechStatus = needs.length ? 'locked' : 'ready';
    return { def, status, cost: def.cost, seconds: Math.round(def.time / (engine.pack()?.world.speed ?? 1)), error, needs, unlocks };
  });
}

/** Names of the techs a unit still needs in this village. */
export function missingTechs(engine: EngineService, live: VillageState, unit: string): string[] {
  const done = new Set(live.techs ?? []);
  return (engine.unit(unit)?.techs ?? []).filter((t) => !done.has(t)).map((t) => engine.tech(t)?.name ?? t);
}
