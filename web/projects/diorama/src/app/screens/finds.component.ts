import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { Find } from '@core/models';
import { UI } from '../ui';

/** Archaeological finds: those kept in this city (the best shown in its temples), and elsewhere. */
@Component({
  selector: 'dio-finds',
  imports: [FormsModule, ...UI],
  template: `
    <section class="hud-panel dialog finds" role="dialog" aria-label="Finds">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Finds</h2>
      @if (arch(); as a) {
        <p class="small">Shown in {{ templeName() }}s: <strong>{{ a.display.shown.length }}</strong> of {{ a.display.room }} room,
          <span class="good">+{{ a.display.culture | n }} culture</span>.
          <span class="muted">Each {{ templeName() }} level shows one more; the best are shown first.</span></p>
        <h3 class="subhead">In {{ game.village()?.name }}</h3>
        @for (f of here(); track f.id) {
          <div class="row-item find">
            <div class="grow">
              <div><strong [class]="'grade grade--' + f.grade">{{ f.name }}</strong>
                <span class="tag" [class]="'grade grade--' + f.grade">{{ f.grade }}</span>
                <span class="small good">+{{ f.culture }} culture</span>
                @if (shown().has(f.id)) {<span class="tag" title="On show in a temple of this city">on show</span>}
              </div>
              <div class="small muted">{{ context(f) }}</div>
            </div>
            @if (!game.inspecting() && others(f).length) {
              <select [(ngModel)]="moveTo[f.id]" [name]="'mv' + f.id" aria-label="Move to">
                @for (c of others(f); track c.id) {<option [ngValue]="c.id">{{ c.name }}</option>}
              </select>
              <button class="btn btn--small" [disabled]="!moveTo[f.id] || busy()" (click)="move(f)">Move</button>
            }
          </div>
        } @empty {<p class="small muted">Nothing found here yet. Dig an empty site or a ruin: click it in the city.</p>}

        @if (elsewhere().length) {
          <h3 class="subhead">In your other cities</h3>
          @for (f of elsewhere(); track f.id) {
            <div class="row-item find small">
              <span class="grow"><strong [class]="'grade grade--' + f.grade">{{ f.name }}</strong> <span class="muted">· {{ f.grade }} · {{ context(f) }}</span></span>
              <span class="muted">{{ f.kept_in?.name ?? 'nowhere' }}</span>
            </div>
          }
        }
      } @else {<p class="muted">This world has no archaeology.</p>}
    </section>
  `,
})
export class FindsComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly engine = inject(EngineService);
  protected readonly busy = signal(false);
  protected readonly all = signal<Find[]>([]);
  protected moveTo: Record<number, number | undefined> = {};

  protected readonly arch = computed(() => this.game.village()?.archaeology ?? null);
  protected readonly here = computed(() => this.arch()?.finds ?? []);
  protected readonly shown = computed(() => new Set(this.arch()?.display.shown ?? []));
  protected readonly elsewhere = computed(() => {
    const id = this.game.village()?.id;
    return this.all().filter((f) => f.kept_in?.id !== id);
  });
  protected readonly templeName = computed(() => {
    const b = this.arch()?.display.building ?? 'temple';
    return (this.engine.building(b)?.name ?? b.replace(/_/g, ' ')).toLowerCase();
  });

  constructor() {
    void this.load();
  }

  private async load(): Promise<void> {
    if (this.game.inspecting()) return;
    try {
      this.all.set(await this.api.myFinds());
    } catch {
      this.all.set([]);
    }
  }

  /** "From a Roman embassy, level 2, fell to ruin; found by X", or the ancient people and their age. */
  protected context(f: Find): string {
    const l = f.context?.layer ?? {};
    let what: string;
    if (l.camp) {
      return `Spoils of a level ${l.camp} barbarian camp; taken by ${f.found_by}`;
    }
    if (l.ancient) {
      what = [l.people ?? l.ancient, l.age].filter(Boolean).join(', ');
    } else {
      const name = [l.style_name, l.building_name ?? l.building].filter(Boolean).join(' ');
      const end = l.end === 'ruined' ? 'fell to ruin' : l.end === 'demolished' ? 'pulled down' : '';
      what = ['from ' + (/^[aeiou]/i.test(name) ? 'an ' : 'a ') + name, l.level ? `level ${l.level}` : '', end].filter(Boolean).join(', ');
    }
    const where = f.context?.site?.village && f.context.site.village !== f.kept_in?.name ? ` in ${f.context.site.village}` : '';
    return `${what.charAt(0).toUpperCase()}${what.slice(1)}${where}; found by ${f.found_by}`;
  }

  protected others(f: Find): { id: number; name: string }[] {
    return (this.game.me()?.villages ?? []).filter((c) => c.id !== (f.kept_in?.id ?? this.game.village()?.id));
  }

  protected async move(f: Find): Promise<void> {
    const to = this.moveTo[f.id];
    const v = this.game.village();
    if (!to || !v) return;
    this.busy.set(true);
    try {
      const r = await this.api.moveFind(f.id, to);
      this.game.toast(`${f.name} moved to ${r.kept_in?.name ?? 'another city'}`, 'good');
      await Promise.all([this.load(), this.game.selectVillage(v.id)]);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
    this.busy.set(false);
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
