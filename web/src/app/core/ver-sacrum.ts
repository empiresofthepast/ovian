import { MapVillage, Tile, VillageView } from './models';

/** Can the current city send a ver sacrum to this tile? Returns the reason it cannot, or '' if it can. */
export function colonyBlocker(v: VillageView | null, tile: Tile | null, village: MapVillage | undefined): string {
  const vs = v?.ver_sacrum;
  if (!v || !vs || !tile) return 'unknown';
  if (village) return 'tile_taken';
  if (!tile.settleable) return 'not_settleable';
  if (vs.migrations.some((m) => m.x === tile.x && m.y === tile.y)) return 'tile_taken';
  if (Math.hypot(tile.x - v.x, tile.y - v.y) > vs.range) return 'out_of_range';
  if (vs.available < 1) return 'no_ver_sacrum';
  return '';
}

/** Hours of travel for the migrants, at world speed. */
export function migrationSeconds(v: VillageView, tile: { x: number; y: number }, worldSpeed: number): number {
  const vs = v.ver_sacrum!;
  return (Math.hypot(tile.x - v.x, tile.y - v.y) / vs.speed) * 3600 / worldSpeed;
}
