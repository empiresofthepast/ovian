import { Units, VillageView } from './models';

/** A garrison of this city's overlord in one of its vassals: where troops may also set out from. */
export interface GarrisonOrigin {
  id: number;
  name: string;
  x: number;
  y: number;
  /** This city's troops stationed there. */
  units: Units;
  /** How many more may set out at once. */
  room: number;
  capacity: number;
}

export function garrisonOrigins(v: VillageView | null | undefined): GarrisonOrigin[] {
  return (v?.vassals ?? [])
    .filter((x) => x.garrison && x.garrison.capacity > 0)
    .map((x) => ({
      id: x.village.id, name: x.village.name, x: x.village.x, y: x.village.y,
      units: Object.fromEntries(Object.entries(x.garrison!.here ?? {}).filter(([, n]) => n > 0)),
      capacity: x.garrison!.capacity,
      room: Math.max(0, x.garrison!.capacity - x.garrison!.out),
    }));
}
