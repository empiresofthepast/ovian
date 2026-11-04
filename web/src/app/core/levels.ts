import { BuildingDef, Pack, VillageState } from './models';

/** Highest level of a building in this village: production sites gain `field_levels` from researched techs. */
export function maxLevel(pack: Pack | null | undefined, v: VillageState | null | undefined, b: BuildingDef): number {
  if (b.slot !== 'field' || !pack || !v) return b.max_level;
  const techs = new Set(v.techs ?? []);
  return b.max_level + (pack.techs ?? []).filter((t) => techs.has(t.id)).reduce((n, t) => n + (t.field_levels ?? 0), 0);
}
