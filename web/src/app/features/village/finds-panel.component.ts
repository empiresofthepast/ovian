import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { Find } from '../../core/models';
import { UI } from '../../shared/ui';
import { layerEnd } from './dig-site.component';

/** Where a find came from, in one line. */
export function findContext(f: Find): string {
  const l = f.context?.layer ?? {};
  const found = `found by ${f.found_by} on ${new Date(f.found_at).toLocaleDateString()}`;
  if (l.camp) return `spoils of a level ${l.camp} barbarian camp${f.context?.site?.village ? ' (' + f.context.site.village + ')' : ''}; taken by ${f.found_by} on ${new Date(f.found_at).toLocaleDateString()}`;
  if (l.ancient) return [l.people, l.age].filter(Boolean).join(', ') + `; ${found}`;
  const what = [l.style_name, l.building_name ?? l.building].filter(Boolean).join(' ');
  const article = /^[aeiou]/i.test(what) ? 'an' : 'a';
  const parts = [what ? `from ${article} ${what}` : 'from a site', l.level ? `level ${l.level}` : '', layerEnd(l.end)].filter(Boolean);
  return `${parts.join(', ')}; ${found}`;
}

/** The finds kept in this city, which of them the temples show, and moving them to other cities. */
@Component({
  selector: 'ov-finds',
  imports: [FormsModule, DecimalPipe, ...UI],
  template: `
    @if (game.village()?.archaeology; as a) {
      @if (a.finds.length || a.digs.length) {
        <section class="panel">
          <h2 class="panel__title">{{ 'section.finds' | label: 'Finds' }} <span class="muted">{{ a.finds.length }}</span></h2>
          <p class="small">Shown in {{ a.display.building | name: 'building' }}s: <strong>{{ a.display.shown.length }}</strong> of {{ a.display.room }} room,
            <span class="good">+{{ a.display.culture | number: '1.0-1' }} culture</span></p>
          @for (d of a.digs; track d.id) {
            <div class="row small"><span class="grow">⛏ A dig under way</span><span class="timer">{{ d.due_at - game.now() | duration }}</span></div>
          }
          @for (f of a.finds; track f.id) {
            <div class="find">
              <div class="row row--wrap small">
                <strong class="grow">{{ f.name }}
                  <span [class]="'grade grade--' + f.grade">{{ f.grade }}</span></strong>
                <span title="Culture when shown">+{{ f.culture | number: '1.0-1' }} culture</span>
                @if (a.display.shown.includes(f.id)) {<span class="good" title="Shown in a temple">shown</span>}
                @else {<span class="muted" title="No room in the temples">stored</span>}
              </div>
              <p class="small muted find__ctx">{{ context(f) }}</p>
              @if (moving() === f.id) {
                <div class="row small">
                  <select class="grow" [(ngModel)]="dest" aria-label="Move to">
                    @for (c of others(); track c.id) {<option [ngValue]="c.id">{{ c.name }} ({{ c.x }}|{{ c.y }})</option>}
                  </select>
                  <button class="btn btn--small btn--primary" [disabled]="busy() || !dest" (click)="move(f.id)">Move</button>
                  <button class="btn btn--ghost btn--small" (click)="moving.set(null)">Cancel</button>
                </div>
              } @else if (others().length && !game.inspecting()) {
                <button class="btn btn--ghost btn--small" (click)="startMove(f.id)">Move to another city…</button>
              }
            </div>
          } @empty {<p class="small muted">No finds kept here yet.</p>}
        </section>
      }
    }
  `,
  styles: `
    .find { padding: 0.3rem 0; border-bottom: 1px dashed color-mix(in srgb, var(--border) 60%, transparent); }
    .find:last-child { border-bottom: 0; }
    .find .row { border-bottom: 0; padding-bottom: 0; }
    .find__ctx { margin: 0.1rem 0 0.3rem; }
    .grade { margin-left: 0.3rem; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
             padding: 0.02rem 0.4rem; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); color: var(--muted); }
    .grade--fine { color: var(--focus); border-color: var(--focus); }
    .grade--exceptional { color: #fff; background: var(--gold, #b8901c); border-color: var(--gold, #b8901c); }
  `,
})
export class FindsPanelComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  protected readonly busy = signal(false);
  protected readonly moving = signal<number | null>(null);
  protected dest: number | null = null;
  protected readonly context = findContext;

  protected readonly others = computed(() => {
    const id = this.game.village()?.id;
    return (this.game.me()?.villages ?? []).filter((c) => c.id !== id);
  });

  protected startMove(id: number): void {
    this.dest = this.others()[0]?.id ?? null;
    this.moving.set(id);
  }

  protected async move(findId: number): Promise<void> {
    const v = this.game.village();
    if (!v || !this.dest) return;
    this.busy.set(true);
    try {
      const f = await this.api.moveFind(findId, this.dest);
      this.game.toast(`${f.name} moved to ${f.kept_in?.name ?? 'another city'}`, 'good');
      this.moving.set(null);
      await this.game.selectVillage(v.id);
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
    this.busy.set(false);
  }
}
