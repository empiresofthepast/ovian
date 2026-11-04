import { EngineService } from './engine.service';
import { ResourceMap, VillageView } from './models';

/** What pulling down the building on a site would do, mirroring the server's rules. */
export interface DemolishInfo {
  /** Resources given back: `refund` of what all its levels cost. */
  refund: ResourceMap;
  share: number;
  /** Why it cannot be pulled down now; empty when it can. */
  blocked: string;
}

export function demolishInfo(engine: EngineService, v: VillageView | null, site: number): DemolishInfo | null {
  const pack = engine.pack();
  const slot = v?.state.slots[site];
  if (!pack || !v || !slot?.building || slot.level < 1 || site < pack.village.field_slots.length) return null;
  if (site >= pack.village.field_slots.length + pack.village.center_slots && !slot.foreign) return null;
  const ext = pack.extensions as Record<string, any>;
  const cfg = (ext['demolish'] ?? {}) as { refund?: number; keep?: string[] };
  const keep = new Set<string>([
    ...(cfg.keep ?? []),
    ...((ext['great_buildings']?.buildings as string[]) ?? []),
    ext['wonder']?.building ?? 'wonder',
  ]);
  if (pack.village.growth?.building) keep.add(pack.village.growth.building);
  if (ext['embassies']) keep.add(ext['embassies'].building ?? 'embassy'); // stands while its overlord rules
  if (keep.has(slot.building)) return null;
  const share = cfg.refund ?? 0.5;
  const total: ResourceMap = {};
  for (let l = 1; l <= slot.level; l++) {
    for (const [r, c] of Object.entries(engine.buildCost(slot.building, l))) total[r] = (total[r] ?? 0) + c;
  }
  const refund: ResourceMap = {};
  for (const [r, c] of Object.entries(total)) if (c * share >= 1) refund[r] = Math.floor(c * share);
  const b = slot.building;
  const others = v.state.slots.some((s, i) => i !== site && s.building === b && s.level > 0);
  let blocked = '';
  if (v.build_queue.some((q) => q.slot === site)) blocked = 'Cancel the construction on this site first.';
  else if (!others && (v.training ?? []).some((t) => t.building === b)) blocked = 'Troops are still training here.';
  else if (!others && (v.research ?? []).some((r) => engine.tech(r.tech)?.building === b)) blocked = 'Research is still running here.';
  return { refund, share, blocked };
}
