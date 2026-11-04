import { ResourceMap, VillageView } from './models';

/** One line about where a city stands: vassal of, overlord of, or being beaten into submission. */
export interface SubmissionInfo {
  /** Percent of production paid to the overlord, 0 when free. */
  tributePct: number;
  overlord: string | null;
  vassals: number;
  /** The most wins any player has in a row against this city, and how many are needed. */
  threat: { player: string; wins: number; needed: number } | null;
}

export function submissionInfo(v: VillageView | null): SubmissionInfo {
  const s = v?.submission;
  const t = v?.dominance?.threats?.[0];
  return {
    tributePct: s ? Math.round(s.tribute * 100) : 0,
    overlord: s ? `${s.village.name} (${s.player_name})` : null,
    vassals: v?.vassals?.length ?? 0,
    threat: t ? { player: t.player_name, wins: t.wins, needed: v!.dominance!.needed } : null,
  };
}

/** Sum of a resource map, for "+N/h" summaries. */
export function total(m: ResourceMap | undefined): number {
  return Object.values(m ?? {}).reduce((a, b) => a + b, 0);
}
