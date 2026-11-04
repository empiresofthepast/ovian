import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Api } from '@core/api.service';
import { hostileAllowed, watchTarget } from '@core/target';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { Units } from '@core/models';
import { garrisonOrigins } from '@core/garrison';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';

type Kind = 'attack' | 'raid' | 'reinforce' | 'scout';

const KIND_TEXT: Record<string, string> = { attack: 'Attack', raid: 'Raid', reinforce: 'Reinforce', scout: 'Scout', return: 'Returning' };

@Component({
  selector: 'dio-rally',
  imports: [FormsModule, RouterLink, ...UI],
  template: `
    <section class="hud-panel dialog rally" role="dialog" aria-label="Rally point">
      <button class="close" (click)="close()" aria-label="Close" title="Close (Esc)">✕</button>
      <h2 class="selection__title">Rally point</h2>
      @if (game.village(); as v) {
        <div class="rally__cols">
          <form class="rally__send" (ngSubmit)="send()">
            <h3 class="subhead">Send troops</h3>
            <div class="rally__target">
              <label>x <input type="number" name="tx" [ngModel]="tx()" (ngModelChange)="tx.set(+$event)" /></label>
              <label>y <input type="number" name="ty" [ngModel]="ty()" (ngModelChange)="ty.set(+$event)" /></label>
              <a class="btn btn--small" routerLink="/map" title="Pick a target on the map">⌖ Map</a>
            </div>
            @if (origins().length) {
              <label class="small">Set out from
                <select name="origin" [ngModel]="origin()" (ngModelChange)="origin.set($event === 'null' || $event === null ? null : +$event); picked.set({})">
                  <option [ngValue]="null">{{ v.name }}</option>
                  @for (o of origins(); track o.id) {<option [ngValue]="o.id">garrison in {{ o.name }} ({{ o.room }} of {{ o.capacity }} may set out)</option>}
                </select>
              </label>
            }
            <div class="seg" role="radiogroup" aria-label="Mission">
              @for (k of kinds; track k) {
                <button type="button" role="radio" class="seg__opt" [class.seg__opt--on]="mission() === k" [attr.aria-checked]="mission() === k" [disabled]="blocked(k)"
                        [title]="blocked(k) ? 'Beginner protection: only reinforcements' : ''" (click)="mission.set(k)">{{ text(k) }}</button>
              }
            </div>
            @if (target()?.protected) {
              <p class="small muted">🛡 {{ target()!.name }} is under beginner protection: you can only reinforce it.</p>
            }
            <div class="pick">
              @for (u of home(); track u.id) {
                <div class="pick__unit" [class.pick__unit--on]="(picked()[u.id] ?? 0) > 0">
                  <button type="button" class="cmd" (click)="pick(u.id, (picked()[u.id] ?? 0) ? 0 : u.have)" [title]="u.name + ': click for all or none'">
                    <dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" />
                  </button>
                  <div class="pick__body">
                    <div class="small">{{ u.name }}</div>
                    <div class="pick__row">
                      <input type="number" min="0" [max]="u.have" [name]="'u-' + u.id" [ngModel]="picked()[u.id] ?? 0" (ngModelChange)="pick(u.id, $event)" [attr.aria-label]="u.name" />
                      <span class="muted small">/ {{ u.have }}</span>
                    </div>
                  </div>
                </div>
              } @empty {<p class="muted">@if (origin() !== null) {None of your troops are stationed there. Reinforce that city first.} @else {No troops at home. Train some at the barracks or stable.}</p>}
            </div>
            <div class="rally__summary small">
              <span title="Travel time">⌛ {{ travel() | dur }}</span>
              @if (travel()) {<span class="muted">arrives {{ game.now() + travel()! * 1000 | clock }}</span>}
              @if (mission() === 'attack' || mission() === 'raid') {<span title="Loot capacity">⚖ {{ carry() | n }}</span>}
            </div>
            @if (mission() === 'scout') {
              <div class="seg seg--small" role="radiogroup" aria-label="Scouts' task">
                @for (o of spyTasks; track o.id) {
                  <button type="button" role="radio" class="seg__opt" [class.seg__opt--on]="spy() === o.id" [attr.aria-checked]="spy() === o.id" (click)="spy.set(o.id)" [title]="o.text">{{ o.label }}</button>
                }
              </div>
              <p class="small muted">{{ spyText() }}</p>
            }
            @if ((mission() === 'attack' || mission() === 'raid') && v.hero?.here && origin() === null) {
              <label class="small"><input type="checkbox" name="hero" [ngModel]="withHero()" (ngModelChange)="withHero.set($event)" /> {{ v.hero!.name }} leads the army</label>
            }
            <button class="btn btn--gold" [disabled]="!travel() || busy() || blocked(mission())">{{ text(mission()) }}</button>

            <details class="sim" (toggle)="simOpen.set($any($event.target).open)">
              <summary class="subhead">Battle simulator</summary>
              <p class="small muted">Your selected troops against an army you describe. Same engine as the server; walls as a defense bonus.</p>
              <div class="row-form">
                <select name="simTribe" [ngModel]="simTribe()" (ngModelChange)="simTribe.set($event); simDef.set({})" aria-label="Defenders' people">
                  @for (t of tribes(); track t.id) {<option [value]="t.id">{{ t.name }}</option>}
                </select>
                <label class="small">wall + <input type="number" min="0" max="200" name="simWall" [ngModel]="simWall()" (ngModelChange)="simWall.set(+$event)" style="width: 60px" />%</label>
                <select name="simKind" [ngModel]="simKind()" (ngModelChange)="simKind.set($event)" aria-label="Kind">
                  <option value="attack">attack</option><option value="raid">raid</option>
                </select>
              </div>
              <div class="pick">
                @for (u of simUnits(); track u.id) {
                  <div class="pick__unit">
                    <dio-portrait [src]="u.icon" [alt]="u.name" [small]="true" />
                    <div class="pick__body"><div class="small">{{ u.name }}</div>
                      <input type="number" min="0" [name]="'sim-' + u.id" [ngModel]="simDef()[u.id] ?? 0" (ngModelChange)="setSim(u.id, $event)" [attr.aria-label]="u.name" />
                    </div>
                  </div>
                }
              </div>
              @if (sim(); as r) {
                <p class="small"><strong [class.good]="r.attacker_won" [class.bad]="!r.attacker_won">{{ r.attacker_won ? 'You win' : 'You lose' }}</strong>
                  · attack {{ r.attack_power | n }} against defense {{ r.defense_power | n }}</p>
                <div class="small">Your losses: {{ lossText(r.attacker_losses) }}</div>
                <div class="small">Their losses: {{ lossText(r.defender_losses[0]) }}</div>
              }
            </details>
          </form>

          <div class="rally__lists">
            <h3 class="subhead">Incoming</h3>
            @for (m of v.movements.incoming; track m.id) {
              <div class="move" [class.move--bad]="m.kind === 'attack' || m.kind === 'raid'">
                <span class="tag">{{ text(m.kind) }}</span>
                <span class="grow">{{ m.from.name }} <span class="muted">({{ m.from.x }}|{{ m.from.y }})</span></span>
                @if (m.units) {<dio-units [units]="m.units" />}
                <span class="job__time">{{ m.arrives_at - game.now() | dur: 'ms' }}</span>
              </div>
            } @empty {<p class="muted small">Nothing on the way.</p>}

            <h3 class="subhead">On the move</h3>
            @for (m of v.movements.outgoing; track m.id) {
              <div class="move">
                <span class="tag">{{ text(m.kind) }}</span>
                <span class="grow">{{ m.kind === 'return' ? 'from ' + m.from.name : m.to.name }}</span>
                <dio-units [units]="m.units" />
                @if (m.loot && hasLoot(m.loot)) {<dio-cost [cost]="m.loot" />}
                <span class="job__time">{{ m.arrives_at - game.now() | dur: 'ms' }}</span>
              </div>
            } @empty {<p class="muted small">All troops are at home.</p>}

            <h3 class="subhead">Allies stationed here</h3>
            @for (r of v.reinforcements.here; track r.id) {
              <div class="move">
                <span class="grow">{{ r.home.name }}</span>
                <dio-units [units]="r.units" />
                <button class="btn btn--small" (click)="dismiss(r.id)">Send back</button>
              </div>
            } @empty {<p class="muted small">None.</p>}

            <h3 class="subhead">Your troops abroad</h3>
            @for (r of v.reinforcements.abroad; track r.id) {
              <div class="move">
                <span class="grow">{{ r.host.name }}</span>
                <dio-units [units]="r.units" />
                <button class="btn btn--small" (click)="recall(r.id)">Recall</button>
              </div>
            } @empty {<p class="muted small">None.</p>}
          </div>
        </div>
      }
    </section>
  `,
})
export class RallyComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  // query parameters from the map
  readonly x = input<string>();
  readonly y = input<string>();
  readonly kind = input<string>();

  protected readonly kinds: Kind[] = ['attack', 'raid', 'scout', 'reinforce'];
  protected readonly tx = signal(0);
  protected readonly ty = signal(0);
  protected readonly mission = signal<Kind>('raid');
  protected readonly picked = signal<Units>({});
  protected readonly busy = signal(false);
  protected readonly withHero = signal(false);
  protected readonly simOpen = signal(false);
  protected readonly simTribe = signal<string>('');
  protected readonly simWall = signal(0);
  protected readonly simKind = signal<'attack' | 'raid'>('attack');
  protected readonly simDef = signal<Units>({});
  protected readonly tribes = computed(() => this.engine.pack()?.tribes ?? []);
  protected readonly simUnits = computed(() => {
    const t = this.simTribe() || this.tribes()[0]?.id;
    return (this.engine.pack()?.units ?? []).filter((u) => u.tribe === t).map((u) => ({ id: u.id, name: u.name, icon: this.art.unitIcon(u.id) }));
  });
  protected readonly sim = computed(() => {
    if (!this.simOpen()) return null;
    const att = Object.fromEntries(Object.entries(this.picked()).filter(([, n]) => n > 0));
    if (!Object.keys(att).length) return null;
    const def = Object.fromEntries(Object.entries(this.simDef()).filter(([, n]) => n > 0));
    return this.engine.simulate({ kind: this.simKind(), attackers: att, defenders: [def], defense_bonus: this.simWall() / 100 });
  });

  protected setSim(unit: string, n: number): void {
    this.simDef.update((d) => ({ ...d, [unit]: Math.max(0, Math.floor(Number(n) || 0)) }));
  }

  protected lossText(l: Units): string {
    const parts = Object.entries(l).filter(([, n]) => n > 0).map(([u, n]) => `${n} ${this.engine.unit(u)?.name ?? u}`);
    return parts.length ? parts.join(', ') : 'none';
  }
  protected readonly target = watchTarget(this.tx, this.ty);

  protected blocked(kind: Kind): boolean {
    return kind !== 'reinforce' && !hostileAllowed(this.target());
  }

  constructor() {
    queueMicrotask(() => {
      const v = this.game.village();
      this.tx.set(this.x() !== undefined ? Number(this.x()) : (v?.x ?? 0));
      this.ty.set(this.y() !== undefined ? Number(this.y()) : (v?.y ?? 0));
      if (this.kinds.includes(this.kind() as Kind)) this.mission.set(this.kind() as Kind);
    });
  }

  protected readonly origin = signal<number | null>(null);
  protected readonly origins = computed(() => garrisonOrigins(this.game.village()));
  private readonly from = computed(() => this.origins().find((o) => o.id === this.origin()) ?? null);
  protected readonly home = computed(() =>
    Object.entries(this.from()?.units ?? this.game.village()?.state.units ?? {})
      .filter(([, n]) => n > 0)
      .map(([id, have]) => ({ id, have, name: this.engine.unit(id)?.name ?? id, icon: this.art.unitIcon(id) })),
  );
  protected readonly travel = computed(() => {
    const v = this.from() ?? this.game.village();
    if (!v || (v.x === this.tx() && v.y === this.ty())) return null;
    return this.engine.travelSeconds(this.picked(), v, { x: this.tx(), y: this.ty() });
  });
  protected readonly carry = computed(() => Math.max(0, this.engine.carry(this.picked())));

  protected text(kind: string): string {
    return KIND_TEXT[kind] ?? kind;
  }

  protected pick(unit: string, n: number): void {
    const have = (this.from()?.units ?? this.game.village()?.state.units ?? {})[unit] ?? 0;
    this.picked.update((p) => ({ ...p, [unit]: Math.max(0, Math.min(have, Math.floor(Number(n) || 0))) }));
  }

  protected hasLoot(l: Record<string, number>): boolean {
    return Object.values(l).some((n) => n > 0);
  }

  protected readonly spy = signal<'look' | 'sabotage' | 'steal' | 'incite'>('look');
  protected readonly spyTasks = [
    { id: 'look' as const, label: 'Look', text: 'Count their stores, troops and buildings, and come home.', need: 1 },
    { id: 'sabotage' as const, label: 'Sabotage', text: 'Set fire to a building: it loses a level. Not the city centre or a wonder.', need: 2 },
    { id: 'steal' as const, label: 'Steal secrets', text: 'Learn a technology they know and this city does not.', need: 3 },
    { id: 'incite' as const, label: 'Incite revolt', text: 'Stir up a vassal city against its overlord: its unrest grows, and it may rise up.', need: 2 },
  ];
  protected readonly spyText = computed(() => {
    const t = this.spyTasks.find((x) => x.id === this.spy())!;
    const m = (this.engine.pack() as any)?.extensions?.scouting?.missions?.[t.id];
    const need = m?.difficulty ?? t.need;
    const req = Object.entries<number>(m?.requires ?? {}).map(([b, n]) => `${this.engine.building(b)?.name ?? b} ${n}`).join(', ');
    return `${t.text} They get through when they number at least ${need === 1 ? 'a tenth' : `${need} tenths`} of the defenders; otherwise they are caught.${req ? ` Needs ${req} here.` : ''}`;
  });

  protected async send(): Promise<void> {
    const v = this.game.village();
    if (!v) return;
    const units = Object.fromEntries(Object.entries(this.picked()).filter(([, n]) => n > 0));
    this.busy.set(true);
    if (await this.game.act(() => this.api.send(v.id, this.mission(), this.tx(), this.ty(), units, this.withHero() && this.origin() === null && (this.mission() === 'attack' || this.mission() === 'raid'), this.mission() === 'scout' ? this.spy() : undefined, this.origin()), this.mission() === 'scout' && this.spy() !== 'look' ? 'Your agents slip away.' : 'Your troops are marching.')) {
      this.picked.set({});
    }
    this.busy.set(false);
  }

  protected recall(id: number): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.recall(v.id, id), 'Troops recalled.');
  }

  protected dismiss(id: number): void {
    const v = this.game.village();
    if (v) void this.game.act(() => this.api.dismiss(v.id, id), 'Allies sent home.');
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
