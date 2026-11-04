import { Injectable, signal } from '@angular/core';
import {
  BuildPlan, BuildingDef, ResearchPlan, TechDef, Economy, Pack, Plan, ResourceMap, Tile, TrainPlan, UnitDef, Units, VillageState, BattleResult } from './models';

/** The subset of the WebAssembly engine API the client uses (see engine/crates/ovian-wasm). */
interface WasmEngine {
  economy(village: VillageState, extraUpkeep: number): Economy;
  accrue(village: VillageState, now: number, extraUpkeep: number): VillageState;
  planBuild(village: VillageState, queue: unknown[], slot: number, building?: string): Plan<BuildPlan>;
  planTraining(village: VillageState, tribe: string, unit: string, count: number): Plan<TrainPlan>;
  planResearch(village: VillageState, queued: string[], tech: string): Plan<ResearchPlan>;
  buildCost(building: string, level: number): ResourceMap;
  travelSeconds(units: Units, fx: number, fy: number, tx: number, ty: number): number | undefined;
  carryCapacity(units: Units): number;
  resolveBattle(battle: unknown): unknown;
  tiles(x: number, y: number, w: number, h: number): Tile[];
}

/**
 * Runs the same Rust rules as the server, compiled to WebAssembly, for live
 * resource counters, cost previews and travel times. The server stays the
 * authority: if WASM is unavailable the client falls back to simple maths and
 * lets the server validate orders.
 */
@Injectable({ providedIn: 'root' })
export class EngineService {
  readonly pack = signal<Pack | null>(null);
  readonly wasm = signal(false);
  private engine: WasmEngine | null = null;
  private buildings = new Map<string, BuildingDef>();
  private units = new Map<string, UnitDef>();
  private techs = new Map<string, TechDef>();

  async init(pack: Pack): Promise<void> {
    this.pack.set(pack);
    this.buildings = new Map(pack.buildings.map((b) => [b.id, b]));
    this.units = new Map(pack.units.map((u) => [u.id, u]));
    this.techs = new Map((pack.techs ?? []).map((t) => [t.id, t]));
    try {
      const glue = new URL('engine/ovian_engine.js', document.baseURI).href;
      const mod = await import(/* @vite-ignore */ glue);
      await mod.default({ module_or_path: new URL('engine/ovian_engine_bg.wasm', document.baseURI).href });
      this.engine = new mod.Engine(pack) as WasmEngine;
      this.wasm.set(true);
    } catch (e) {
      console.warn('WebAssembly engine unavailable, using fallbacks', e);
      this.engine = null;
      this.wasm.set(false);
    }
  }

  building(id: string | null | undefined): BuildingDef | undefined {
    return id ? this.buildings.get(id) : undefined;
  }
  unit(id: string): UnitDef | undefined {
    return this.units.get(id);
  }
  tech(id: string): TechDef | undefined {
    return this.techs.get(id);
  }
  /** Techs researched in a given building. */
  techsIn(building: string): TechDef[] {
    return [...this.techs.values()].filter((t) => t.building === building);
  }

  resourceIds(): string[] {
    return this.pack()?.resources.map((r) => r.id) ?? [];
  }

  /** Resources at `now`, given the last server snapshot and its economy. */
  accrue(state: VillageState, economy: Economy, now: number, extraUpkeep: number): ResourceMap {
    if (this.engine) return this.engine.accrue(state, now, extraUpkeep).resources;
    const hours = Math.max(0, now - state.resources_at) / 3_600_000;
    const out: ResourceMap = {};
    for (const [r, v] of Object.entries(state.resources)) {
      const cap = economy.capacity[r] ?? Infinity;
      const next = v + (economy.production[r] ?? 0) * hours;
      out[r] = Math.max(0, v > cap ? Math.min(v, next) : Math.min(cap, next));
    }
    return out;
  }

  economy(state: VillageState, extraUpkeep: number): Economy | null {
    return this.engine ? this.engine.economy(state, extraUpkeep) : null;
  }

  planBuild(state: VillageState, queue: { slot: number; building: string; level: number }[], slot: number, building?: string): Plan<BuildPlan> | null {
    return this.engine ? this.engine.planBuild(state, queue, slot, building) : null;
  }

  planTraining(state: VillageState, tribe: string, unit: string, count: number): Plan<TrainPlan> | null {
    return this.engine ? this.engine.planTraining(state, tribe, unit, count) : null;
  }

  planResearch(state: VillageState, queued: string[], tech: string): Plan<ResearchPlan> | null {
    return this.engine ? this.engine.planResearch(state, queued, tech) : null;
  }

  buildCost(building: string, level: number): ResourceMap {
    if (this.engine) return this.engine.buildCost(building, level);
    const b = this.building(building)!;
    const k = Math.pow(b.cost.factor, level - 1);
    return Object.fromEntries(Object.entries(b.cost.base).map(([r, v]) => [r, Math.round(v * k)]));
  }

  travelSeconds(units: Units, from: { x: number; y: number }, to: { x: number; y: number }): number | null {
    const active = Object.fromEntries(Object.entries(units).filter(([, n]) => n > 0));
    if (this.engine) return this.engine.travelSeconds(active, from.x, from.y, to.x, to.y) ?? null;
    const speeds = Object.keys(active).map((u) => this.unit(u)?.speed ?? Infinity);
    if (!speeds.length) return null;
    const dist = Math.hypot(from.x - to.x, from.y - to.y);
    return Math.max(1, Math.round((dist / (Math.min(...speeds) * (this.pack()?.world.speed ?? 1))) * 3600));
  }

  carry(units: Units): number {
    if (this.engine) return this.engine.carryCapacity(units);
    return Object.entries(units).reduce((s, [u, n]) => s + (this.unit(u)?.carry ?? 0) * n, 0);
  }

  /** Run the battle engine locally (the same code the server uses). */
  simulate(battle: { kind: 'attack' | 'raid'; attackers: Units; defenders: Units[]; defense_bonus?: number; attack_multiplier?: number }): BattleResult | null {
    if (!this.engine) return null;
    return this.engine.resolveBattle({ defense_bonus: 0, attack_multiplier: 1, ...battle }) as BattleResult;
  }

  tiles(x: number, y: number, w: number, h: number): Tile[] | null {
    return this.engine ? this.engine.tiles(x, y, w, h) : null;
  }
}

export function curveAt(curve: BuildingDef['effects']['build_speed'], level: number): number {
  if (!curve || level <= 0) return 0;
  if (Array.isArray(curve)) return curve[Math.min(level, curve.length) - 1];
  const v = curve.base * Math.pow(curve.factor, level - 1);
  return curve.round ? Math.round(v / curve.round) * curve.round : v;
}
