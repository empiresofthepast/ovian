import { Injectable, computed, inject, signal } from '@angular/core';
import { EngineService } from '@core/engine.service';

/** One appearance of a 0 A.D. actor, as baked by tools/zeroad/bake.py. */
export interface Look {
  mesh?: string;
  tex?: string;
  props?: [string, string][];
  decal?: { width?: number; depth?: number; angle?: number; offsetx?: number; offsetz?: number };
  color?: number[];
}

export type MaterialKind = 'player' | 'alphatest' | 'blend' | 'opaque' | 'objectcolor';

export interface ActorDef {
  looks: Look[];
  mat: MaterialKind;
  shadow: boolean;
}

export interface StructureArt {
  actor: string;
  foundation: string | null;
  footprint: [number, number] | null;
  name: string;
  specific: string;
  icon: string | null;
}

export interface CivArt {
  name: string;
  emblem: string | null;
  structures: Record<string, StructureArt>;
  flag: string | null;
  /** 0 A.D. hero portraits by hero template id. */
  heroes?: Record<string, string>;
}

export interface PackArt {
  tribes: Record<string, string>;
  buildings: Record<string, string>;
  fields: Record<string, 'wood' | 'stone' | 'metal' | 'food'>;
  resources: Record<string, string>;
  units: Record<string, { icon: string | null }>;
  /** Per tribe: building -> 0 A.D. structure role, when it differs by civ (e.g. a university). */
  tribe_buildings?: Record<string, Record<string, string>>;
  techs?: Record<string, string | null>;
}

export interface Manifest {
  version: number;
  source: { repo: string; commit: string };
  packs: Record<string, PackArt>;
  civs: Record<string, CivArt>;
  gaia: Record<string, string[]>;
  plot: string | null;
  terrain: { grass: string[]; dirt: string; paving: string; forest: string; farmland?: string };
  icons: Record<string, string>;
  actors: Record<string, ActorDef>;
}

export const ART_BASE = 'art/';

/** 0 A.D. art: which civ dresses a tribe, which structure stands for a building, icons. */
@Injectable({ providedIn: 'root' })
export class ArtService {
  private readonly engine = inject(EngineService);
  readonly manifest = signal<Manifest | null>(null);

  /** Mapping for the pack this world runs, falling back to the first civ for unknown packs. */
  readonly pack = computed<PackArt | null>(() => {
    const m = this.manifest();
    const p = this.engine.pack();
    if (!m || !p) return null;
    return m.packs[p.id] ?? { tribes: {}, buildings: {}, fields: {}, resources: {}, units: {}, techs: {} };
  });

  async init(): Promise<void> {
    try {
      const r = await fetch(ART_BASE + 'manifest.json');
      if (r.ok) this.manifest.set(await r.json());
    } catch (e) {
      console.warn('0 A.D. art manifest unavailable', e);
    }
  }

  url(path: string | null | undefined): string | null {
    return path ? ART_BASE + path : null;
  }

  civOf(tribe: string | null | undefined): string {
    const m = this.manifest();
    const mapped = tribe ? this.pack()?.tribes[tribe] : undefined;
    return mapped ?? (tribe && m?.civs[tribe] ? tribe : Object.keys(m?.civs ?? { athen: 1 })[0]);
  }

  civ(tribe: string | null | undefined): CivArt | null {
    return this.manifest()?.civs[this.civOf(tribe)] ?? null;
  }

  /** The 0 A.D. structure that represents an Ovian building for this tribe. */
  structure(tribe: string | null | undefined, building: string | null | undefined): StructureArt | null {
    if (!building) return null;
    const p = this.pack();
    const role = (tribe ? p?.tribe_buildings?.[tribe]?.[building] : undefined) ?? p?.buildings[building];
    return role ? (this.civ(tribe)?.structures[role] ?? null) : null;
  }

  /** wood | stone | metal | food for field buildings, by what they produce. */
  fieldKind(building: string | null | undefined): string | null {
    if (!building) return null;
    const known = this.pack()?.fields[building];
    if (known) return known;
    const prod = this.engine.building(building)?.effects.production?.resource;
    return prod ? (this.pack()?.resources[prod] ?? 'food') : null;
  }

  resourceIcon(resource: string): string | null {
    const kind = this.pack()?.resources[resource] ?? resource;
    return this.url(this.manifest()?.icons[kind]);
  }

  buildingIcon(tribe: string | null | undefined, building: string): string | null {
    const s = this.structure(tribe, building);
    if (s?.icon) return this.url(s.icon);
    const kind = this.fieldKind(building);
    return kind ? this.resourceIcon(kind) : this.url(this.civ(tribe)?.emblem);
  }

  techIcon(tech: string): string | null {
    return this.url(this.pack()?.techs?.[tech]);
  }

  unitIcon(unit: string): string | null {
    return this.url(this.pack()?.units[unit]?.icon);
  }
}
