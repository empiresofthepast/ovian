import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { hostileAllowed, watchTarget } from '../../core/target';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { Units } from '../../core/models';
import { garrisonOrigins } from '../../core/garrison';
import { UI } from '../../shared/ui';

type Kind = 'attack' | 'raid' | 'reinforce' | 'scout';
type Mission = 'look' | 'sabotage' | 'steal' | 'incite';

@Component({
  selector: 'ov-rally',
  imports: [FormsModule, ...UI],
  template: `
    <div class="page-head"><h1 class="page-title">{{ 'nav.rally' | label }}</h1></div>
    @if (game.village(); as v) {
      <div class="rally">
        <section class="panel">
          <h2 class="panel__title">{{ 'rally.send' | label: 'Send troops' }}</h2>
          <form class="form" (ngSubmit)="send()">
            <div class="form__row">
              <label class="field field--short"><span>x</span><input type="number" name="tx" [ngModel]="tx()" (ngModelChange)="tx.set($event)" /></label>
              <label class="field field--short"><span>y</span><input type="number" name="ty" [ngModel]="ty()" (ngModelChange)="ty.set($event)" /></label>
              <div class="seg" role="radiogroup" aria-label="Mission">
                @for (k of kinds; track k) {
                  <label class="seg__opt" [class.seg__opt--active]="mission() === k" [class.seg__opt--off]="blocked(k)">
                    <input type="radio" name="kind" [value]="k" [ngModel]="mission()" (ngModelChange)="mission.set($event)" [disabled]="blocked(k)" />{{ 'kind.' + k | label }}
                  </label>
                }
              </div>
            </div>
            @if (origins().length) {
              <div class="form__row">
                <label class="field"><span>Set out from</span>
                  <select name="origin" [ngModel]="origin()" (ngModelChange)="origin.set($event); picked.set({})">
                    <option [ngValue]="null">{{ v.name }}</option>
                    @for (o of origins(); track o.id) {<option [ngValue]="o.id">garrison in {{ o.name }} ({{ o.room }} of {{ o.capacity }} may set out)</option>}
                  </select>
                </label>
              </div>
            }
            @if (mission() === 'scout') {
              <div class="form__row">
                <div class="seg" role="radiogroup" aria-label="Scouts' mission">
                  @for (m of missions; track m.id) {
                    <label class="seg__opt" [class.seg__opt--active]="scoutMission() === m.id" [title]="m.text">
                      <input type="radio" name="scoutMission" [value]="m.id" [ngModel]="scoutMission()" (ngModelChange)="scoutMission.set($event)" />{{ 'mission.' + m.id | label: m.label }}
                    </label>
                  }
                </div>
              </div>
              <p class="small muted">{{ missionText() }}</p>
            }
            @if (target()?.protected) {
              <p class="small muted">🛡 {{ target()!.name }} {{ 'rally.protected' | label: 'is under beginner protection: you can only reinforce it.' }}</p>
            }

            <div class="troop-grid">
              @for (u of home(); track u.id) {
                <label class="troop">
                  <ov-icon [key]="'unit.' + u.id" />
                  <span class="troop__name">{{ u.id | name: 'unit' }}</span>
                  <input type="number" min="0" [max]="u.have" [name]="'u-' + u.id" [ngModel]="picked()[u.id] ?? 0" (ngModelChange)="pick(u.id, $event)" />
                  <button type="button" class="btn btn--ghost btn--small" (click)="pick(u.id, u.have)">{{ u.have }}</button>
                </label>
              } @empty {<p class="muted">No troops at home. Train some in the barracks.</p>}
            </div>

            <div class="row small">
              <span><ov-icon key="stat.time" /> {{ travel() | duration: 's' }}</span>
              @if (travel()) {<span class="muted">arrives {{ game.now() + travel()! * 1000 | clock }}</span>}
              @if (mission() === 'attack' || mission() === 'raid') {<span><ov-icon key="stat.carry" /> {{ carry() }}</span>}
            </div>
            <button class="btn btn--primary" [disabled]="!travel() || busy() || blocked(mission())">{{ 'kind.' + mission() | label }}</button>
          </form>
        </section>

        <section class="panel">
          <h2 class="panel__title">{{ 'rally.incoming' | label: 'Incoming' }}</h2>
          @for (m of v.movements.incoming; track m.id) {
            <div class="row" [class.row--danger]="m.kind === 'attack' || m.kind === 'raid'">
              <span class="tag" [class]="'tag tag--' + m.kind">{{ 'kind.' + m.kind | label }}</span>
              <span class="grow">{{ m.from.name }} ({{ m.from.x }}|{{ m.from.y }})</span>
              @if (m.units) {<ov-units [units]="m.units" />}
              <span class="timer">{{ m.arrives_at - game.now() | duration }}</span>
            </div>
          } @empty {<p class="muted">Nothing on the way.</p>}

          <h2 class="panel__title">{{ 'rally.outgoing' | label: 'Your troops on the move' }}</h2>
          @for (m of v.movements.outgoing; track m.id) {
            <div class="row">
              <span class="tag" [class]="'tag tag--' + m.kind">{{ 'kind.' + m.kind | label }}</span>
              @if (m.mission) {<span class="tag" [title]="'Mission'">{{ missionLabel(m.mission) }}</span>}
              <span class="grow">{{ m.kind === 'return' ? m.from.name : m.to.name }} ({{ m.kind === 'return' ? m.from.x : m.to.x }}|{{ m.kind === 'return' ? m.from.y : m.to.y }})</span>
              <ov-units [units]="m.units" />
              @if (m.loot && hasLoot(m.loot)) {<ov-cost [cost]="m.loot" />}
              <span class="timer">{{ m.arrives_at - game.now() | duration }}</span>
            </div>
          } @empty {<p class="muted">All troops are at home.</p>}
        </section>

        <section class="panel">
          <h2 class="panel__title">{{ 'rally.here' | label: 'Reinforcements here' }}</h2>
          @for (r of v.reinforcements.here; track r.id) {
            <div class="row">
              <span class="grow">{{ r.home.name }} ({{ r.home.x }}|{{ r.home.y }})</span>
              <ov-units [units]="r.units" />
              <button class="btn btn--ghost btn--small" (click)="dismiss(r.id)">{{ 'rally.dismiss' | label: 'Send back' }}</button>
            </div>
          } @empty {<p class="muted">None.</p>}
          <h2 class="panel__title">{{ 'rally.abroad' | label: 'Your troops abroad' }}</h2>
          @for (r of v.reinforcements.abroad; track r.id) {
            <div class="row">
              <span class="grow">{{ r.host.name }} ({{ r.host.x }}|{{ r.host.y }})</span>
              <ov-units [units]="r.units" />
              <button class="btn btn--ghost btn--small" (click)="recall(r.id)">{{ 'rally.recall' | label: 'Recall' }}</button>
            </div>
          } @empty {<p class="muted">None.</p>}
        </section>
      </div>
    }
  `,
})
export class RallyComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  // Query params from the map (component input binding).
  readonly x = input<string>();
  readonly y = input<string>();
  readonly kind = input<string>();

  protected readonly kinds: Kind[] = ['attack', 'raid', 'reinforce', 'scout'];
  protected readonly missions: { id: Mission; label: string; text: string }[] = [
    { id: 'look', label: 'Look', text: 'Count the stores, troops and buildings of the target, and come home.' },
    { id: 'sabotage', label: 'Sabotage', text: 'Sneak in and damage a building: it loses a level. Harder to get past the guards.' },
    { id: 'steal', label: 'Steal secrets', text: 'Learn a technology the target knows and your city does not. The hardest mission.' },
    { id: 'incite', label: 'Incite revolt', text: 'Stir up a vassal city against its overlord, adding unrest: it may rise up.' },
  ];
  protected readonly scoutMission = signal<Mission>('look');
  protected readonly missionText = computed(() => this.missions.find((m) => m.id === this.scoutMission())?.text ?? '');
  protected readonly tx = signal(0);
  protected readonly ty = signal(0);
  protected readonly mission = signal<Kind>('raid');
  protected readonly picked = signal<Units>({});
  protected readonly busy = signal(false);
  protected readonly target = watchTarget(this.tx, this.ty);

  protected blocked(kind: Kind): boolean {
    return kind !== 'reinforce' && !hostileAllowed(this.target());
  }

  constructor() {
    queueMicrotask(() => {
      if (this.x() !== undefined) this.tx.set(Number(this.x()));
      if (this.y() !== undefined) this.ty.set(Number(this.y()));
      if (this.kinds.includes(this.kind() as Kind)) this.mission.set(this.kind() as Kind);
    });
  }

  protected readonly origin = signal<number | null>(null);
  protected readonly origins = computed(() => garrisonOrigins(this.game.village()));
  private readonly from = computed(() => this.origins().find((o) => o.id === this.origin()) ?? null);
  protected readonly home = computed(() =>
    Object.entries(this.from()?.units ?? this.game.village()?.state.units ?? {}).filter(([, n]) => n > 0).map(([id, have]) => ({ id, have })),
  );
  protected readonly travel = computed(() => {
    const v = this.from() ?? this.game.village();
    return v ? this.engine.travelSeconds(this.picked(), v, { x: this.tx(), y: this.ty() }) : null;
  });
  protected readonly carry = computed(() => Math.round(this.engine.carry(this.picked())).toLocaleString());

  protected pick(unit: string, n: number): void {
    const have = (this.from()?.units ?? this.game.village()?.state.units ?? {})[unit] ?? 0;
    this.picked.update((p) => ({ ...p, [unit]: Math.max(0, Math.min(have, Math.floor(Number(n) || 0))) }));
  }

  protected missionLabel(id: string): string {
    const m = this.missions.find((x) => x.id === id);
    return m ? m.label : id;
  }

  protected hasLoot(l: Record<string, number>): boolean {
    return Object.values(l).some((n) => n > 0);
  }

  protected async send(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    const units = Object.fromEntries(Object.entries(this.picked()).filter(([, n]) => n > 0));
    this.busy.set(true);
    const kind = this.mission();
    const mission = kind === 'scout' ? this.scoutMission() : undefined;
    if (await this.game.act(() => this.api.send(v.id, kind, this.tx(), this.ty(), units, false, mission, this.origin()), 'Troops are on their way.')) {
      this.picked.set({});
    }
    this.busy.set(false);
  }

  protected recall(id: number): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.recall(v.id, id));
  }

  protected dismiss(id: number): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.dismiss(v.id, id));
  }
}
