import { Component, computed, inject, input } from '@angular/core';
import { GameStore } from '../../core/game.store';
import { ContentmentView, TimedEffect } from '../../core/models';
import { politicsText } from '../../core/politics';
import { pct, signed } from '../../shared/effects';
import { UI } from '../../shared/ui';

/** The people's mood: score and its causes, its effect on production, unrest and timed effects. */
@Component({
  selector: 'ov-contentment',
  imports: [...UI],
  template: `
    @if (view(); as c) {
      <section class="panel">
        <h2 class="panel__title">{{ 'section.contentment' | label: 'Contentment' }}
          @if (c.score !== undefined) {<span class="mood" [class]="'mood mood--' + tone()">{{ signed(c.score) }}</span>}</h2>
        @for (f of c.factors ?? []; track f.label) {
          <div class="row small"><span class="grow">{{ f.label }}</span><span [class.good]="f.value > 0" [class.bad]="f.value < 0">{{ signed(f.value) }}</span></div>
        }
        @if (c.production) {
          <div class="row small"><span class="grow">{{ 'contentment.production' | label: 'Production' }}</span>
            <strong [class.good]="c.production > 0" [class.bad]="c.production < 0">{{ pct(c.production) }}</strong></div>
        }
        @if (c.defense) {
          <div class="row small" [title]="'Above ' + c.defense_from + ' contentment the citizens take up arms when the city is attacked'"><span class="grow">{{ 'contentment.defense' | label: 'Defense' }}</span>
            <strong class="good">{{ pct(c.defense) }}</strong></div>
        } @else if (c.defense_from !== undefined && c.score !== undefined) {
          <div class="row small muted"><span class="grow">Above {{ c.defense_from }} contentment, citizens help defend the city</span></div>
        }
        @if (c.can_rebel || (c.unrest ?? 0) > 0) {
          <div class="row small"><span class="grow">{{ 'contentment.unrest' | label: 'Unrest' }}</span>
            <span [class.bad]="(c.unrest ?? 0) > 0">{{ (c.unrest ?? 0).toFixed(0) }} / {{ c.rebel_at }}</span></div>
          <div class="meter meter--bad" [title]="'Rises up at ' + c.rebel_at"><i [style.width.%]="unrestPct()"></i></div>
          @if (c.can_rebel) {<p class="small muted">{{ 'contentment.rebel' | label: 'A vassal city rises against its overlord when unrest is full.' }}</p>}
        }
        @if (politics().length) {
          <div class="small muted">{{ 'contentment.politics' | label: 'Politics' }}: {{ politics().join(' · ') }}</div>
        }
        @for (e of c.effects; track $index) {
          <div class="row small">
            <span class="grow">{{ e.label }}</span>
            <span [class.good]="e.value > 0" [class.bad]="e.value < 0">{{ effectText(e) }}</span>
            <span class="timer">{{ e.until - game.now() | duration }}</span>
          </div>
        }
      </section>
    }
  `,
})
export class ContentmentPanelComponent {
  protected readonly game = inject(GameStore);
  readonly view = input<ContentmentView | undefined>();
  protected readonly signed = signed;
  protected readonly pct = pct;

  protected readonly tone = computed(() => {
    const c = this.view();
    const s = c?.score ?? 0;
    return s < (c?.rebel_below ?? -10) ? 'bad' : s < 0 ? 'warn' : s > 0 ? 'good' : 'neutral';
  });
  protected readonly politics = computed(() => politicsText(this.view()));
  protected readonly unrestPct = computed(() => {
    const c = this.view();
    return c?.rebel_at ? Math.min(100, ((c.unrest ?? 0) / c.rebel_at) * 100) : 0;
  });

  protected effectText(e: TimedEffect): string {
    return e.kind === 'boost' ? `${pct(e.value)} production` : `${signed(e.value)} contentment`;
  }
}
