import { Component, input } from '@angular/core';
import { GovernorTrait } from '../../core/models';

const pct = (x: number) => `${Math.round(Math.abs(x) * 100)}%`;
const signed = (x: number) => `${x > 0 ? '+' : '−'}${pct(x)}`;

/** A trait's effects in a few words, e.g. "+2 contentment, unrest 20% slower". */
export function traitSummary(t: GovernorTrait): string {
  const out: string[] = [];
  const mult = (m: number | undefined, what: string, up: string, down: string) => {
    if (m !== undefined && m !== 1) out.push(`${what} ${pct(m - 1)} ${m > 1 ? up : down}`);
  };
  if (t.contentment) out.push(`${t.contentment > 0 ? '+' : ''}${t.contentment} contentment`);
  mult(t.unrest, 'unrest grows', 'faster', 'slower');
  mult(t.calm, 'calms', 'faster', 'slower');
  mult(t.size, 'crowding', 'worse', 'milder');
  mult(t.tribute, 'tribute anger', 'worse', 'milder');
  mult(t.agitators, 'agitators', 'stronger', 'weaker');
  if (t.production) out.push(`${signed(t.production)} production`);
  if (t.defense) out.push(`${signed(t.defense)} defense`);
  return out.join(', ');
}

/** A governor's traits as chips; the tooltip has the trait's text and what it does. */
@Component({
  selector: 'ov-traits',
  template: `
    <span class="traits">
      @for (t of traits(); track t.id) {
        <span class="chip" [title]="tip(t)">{{ t.name ?? t.id }}</span>
      }
      @if (summary()) {
        @for (t of traits(); track t.id) {<span class="small muted traits__fx">{{ fx(t) }}</span>}
      }
    </span>
  `,
  styles: `
    .traits { display: inline-flex; flex-wrap: wrap; gap: 0.3rem; align-items: center; }
    .traits__fx:empty { display: none; }
    .traits__fx + .traits__fx::before { content: '· '; }
  `,
})
export class TraitsComponent {
  readonly traits = input.required<GovernorTrait[]>();
  /** Also spell out the effects next to the chips. */
  readonly summary = input(false);
  protected readonly fx = traitSummary;

  protected tip(t: GovernorTrait): string {
    return [t.text, traitSummary(t)].filter(Boolean).join('\n');
  }
}
