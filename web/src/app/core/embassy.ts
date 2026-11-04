import { Pack } from './models';

export interface EmbassyRules {
  building: string;
  ruin: string;
  exchange: string;
  exchange_slots: number;
  exchange_relief: number;
  /** Buildings only an overlord raises on its overlord sites (cultural exchange, garrison). */
  overlord: string[];
}

/** The pack's embassy rules (extensions.embassies), or null when the world has none. */
export function embassyRules(pack: Pack | null | undefined): EmbassyRules | null {
  const c = (pack?.extensions as Record<string, any> | undefined)?.['embassies'];
  return c ? { building: 'embassy', ruin: 'ruin', exchange: 'exchange', exchange_slots: 1, exchange_relief: 0.03, overlord: [], ...c } : null;
}

/** 'embassy' when only the overlord may raise this building, 'ruin' for a ruined embassy, else null. */
export function foreignRole(pack: Pack | null | undefined, building: string | null | undefined): 'embassy' | 'ruin' | null {
  const r = embassyRules(pack);
  if (!r || !building) return null;
  return building === r.building || r.overlord.includes(building) ? 'embassy' : building === r.ruin ? 'ruin' : null;
}
