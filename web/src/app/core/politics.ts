import { ContentmentView } from './models';

/** Plain-language lines for what a city's political techs do to unrest. */
export function politicsText(c: ContentmentView | undefined | null): string[] {
  const p = c?.politics;
  if (!p) return [];
  const out: string[] = [];
  const pct = (m: number) => `${Math.round(Math.abs(1 - m) * 100)}%`;
  if (p.unrest !== undefined) out.push(`Unrest grows ${pct(p.unrest)} ${p.unrest < 1 ? 'slower' : 'faster'}`);
  if (p.calm !== undefined) out.push(`Unrest calms ${pct(p.calm)} ${p.calm > 1 ? 'faster' : 'slower'}`);
  if (p.rebel_below) out.push(`Restless only below ${c?.rebel_below} contentment`);
  if (p.size !== undefined) out.push(`Crowding angers ${pct(p.size)} ${p.size < 1 ? 'less' : 'more'}`);
  if (p.tribute !== undefined) out.push(`Tribute angers ${pct(p.tribute)} ${p.tribute < 1 ? 'less' : 'more'}`);
  if (p.agitators !== undefined) out.push(`Agitators stir ${pct(p.agitators)} ${p.agitators < 1 ? 'less' : 'more'} unrest`);
  return out;
}
