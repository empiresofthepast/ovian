import { AfterViewInit, Component, DestroyRef, ElementRef, computed, effect, inject, input, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '@core/api.service';
import { EngineService } from '@core/engine.service';
import { GameStore } from '@core/game.store';
import { GreatBuilding, MapVillage, Road, Tile } from '@core/models';
import { ArtService } from '../art/art.service';
import { UI } from '../ui';
import { Labels } from '@core/labels';
import { DEFAULT_LABELS } from '@core/defaults';
import { colonyBlocker, migrationSeconds } from '@core/ver-sacrum';

const CHUNK = 32;
/** Terrain as 0 A.D. ground textures where we have one, flat colour otherwise. */
const COLOURS: Record<string, string> = {
  plain: '#8a9a4a', forest: '#4d6a32', hills: '#9a8a58', mountain: '#7d7468', water: '#3f6f8f', beach: '#cdbb86',
};

/** World map: the terrain painted with 0 A.D. textures, villages as civilization emblems. */
const label = (v: MapVillage) => (v.alliance_tag ? `[${v.alliance_tag}] ` : '') + v.name + (v.bot ? ' 🤖' : '');

@Component({
  selector: 'dio-map',
  imports: [FormsModule, ...UI],
  template: `
    <section class="worldmap" aria-label="World map">
      <div class="worldmap__stage" #wrap>
        <canvas #canvas tabindex="0" aria-label="World map. Drag to pan, wheel to zoom, arrow keys to move, click a tile for details."
                (pointerdown)="down($event)" (pointermove)="move($event)" (pointerup)="up($event)" (pointercancel)="up($event)" (pointerleave)="drag = null"
                (wheel)="wheel($event)" (keydown)="key($event)"></canvas>
      </div>

      <div class="hud-panel worldmap__tools">
        <form class="worldmap__jump" (ngSubmit)="jump()">
          <input type="number" name="jx" [ngModel]="jx()" (ngModelChange)="jx.set($event)" aria-label="x" />
          <span>|</span>
          <input type="number" name="jy" [ngModel]="jy()" (ngModelChange)="jy.set($event)" aria-label="y" />
          <button class="btn btn--small">Go</button>
        </form>
        <button class="btn btn--small" (click)="home()" title="Back to your city">⌂</button>
        <button class="btn btn--small" (click)="zoom(1.25)" aria-label="Zoom in">+</button>
        <button class="btn btn--small" (click)="zoom(0.8)" aria-label="Zoom out">−</button>
        <span class="muted small">{{ center().x }}|{{ center().y }}</span>
      </div>

      <aside class="hud-panel worldmap__info">
        <button class="close" (click)="close()" aria-label="Close map" title="Close (Esc)">✕</button>
        @if (selected(); as t) {
          <h2 class="selection__title">({{ t.x }}|{{ t.y }})</h2>
          <p class="muted small terrain">{{ t.terrain }}</p>
          @if (selectedVillage(); as v) {
            <div class="worldmap__who">
              @if (emblem(v.tribe)) {<img class="emblem" [src]="emblem(v.tribe)" alt="" />}
              <div>
                <h3 class="subhead">@if (v.alliance_tag) {<span class="muted">[{{ v.alliance_tag }}]</span> }{{ v.name }}</h3>
                @if (v.npc) {
                  <div class="small">Barbarian camp, level {{ v.camp_level }}. Raid it for loot; heroes earn double experience here. It recovers an hour after each battle.</div>
                } @else {
                  <div class="small">{{ v.player_name }}@if (v.bot) { 🤖 <span class="muted">(an AI ruler)</span>} · {{ tribeName(v.tribe) }}</div>
                }
                <div class="small muted">Population {{ v.population }}@if (v.culture) { · culture {{ v.culture | n }}}@if (distance() !== null) { · {{ distance()!.toFixed(1) }} tiles}</div>
                @if (v.overlord_id) {<div class="small bad">⛓ Vassal of {{ v.overlord_name }} ({{ v.overlord_player_name }}), {{ tribeName(v.overlord_tribe!) }} in culture</div>}
                @if (v.vassals) {<div class="small">♛ Overlord of {{ v.vassals }} {{ v.vassals === 1 ? 'city' : 'cities' }}</div>}
              </div>
            </div>
            @if (roadable(v); as rd) {
              <button class="btn btn--small" (click)="buildRoad(v)" [title]="'Armies and merchants go faster between the two cities'">⟷ Build road from {{ game.village()?.name }}</button>
              <div class="small muted">{{ rd.tiles }} tiles · <dio-cost [cost]="rd.cost" [have]="game.resources()" /></div>
            }
            @if (game.me()?.is_admin && v.player_id !== game.me()?.id) {
              <button class="btn btn--small" (click)="inspect(v.id)" title="Superuser: look into this city">👁 Look inside</button>
            }
            @for (g of great(); track g.building) {
              <div class="colony">
                <h3 class="subhead">{{ buildingName(g.building) }} · level {{ g.level }}</h3>
                @if (g.complete) {<p class="small muted">Complete.</p>} @else {
                  <div class="bar"><div class="bar__fill" [style.width.%]="((g.points ?? 0) / (g.cost ?? 1)) * 100"></div></div>
                  <p class="small muted">{{ g.points | n }} / {{ g.cost | n }} towards level {{ g.next_level }}. Contribute from {{ game.village()?.name }}@if (v.player_id !== game.me()?.id) {; you get half back when the level is finished}.</p>
                  <div class="res-inputs">
                    @for (r of resourceList(); track r.id) {
                      <label>@if (r.icon) {<img [src]="r.icon" alt="" />}<input type="number" min="0" [name]="'gift-' + r.id" [(ngModel)]="gift[r.id]" [attr.aria-label]="r.name" /></label>
                    }
                  </div>
                  <button class="btn btn--small btn--gold" (click)="contribute(v.id, g.building)">Contribute</button>
                }
              </div>
            }
            @if (v.player_id !== game.me()?.id) {
              @if (v.protected) {
                <p class="small muted">🛡 Under beginner protection: it cannot be attacked or raided@if (v.protected_until) { for another {{ (v.protected_until - game.now()) | dur: 'ms' }}}.</p>
              }
              <div class="btn-row">
                @if (!v.protected) {
                  <button class="btn btn--gold btn--small" (click)="send('attack')">Attack</button>
                  <button class="btn btn--small" (click)="send('raid')">Raid</button>
                }
                <button class="btn btn--small" (click)="send('reinforce')">Reinforce</button>
              </div>

              @if (!v.npc && !game.village()?.submission) {
                @if (game.village()?.fealty_offer?.village?.id === v.id) {
                  <p class="small muted">{{ game.village()!.name }} has offered fealty to {{ v.name }}.</p>
                } @else {
                  <button class="btn btn--ghost btn--small" (click)="fealty(v.id, v.name)" [title]="'Offer ' + game.village()?.name + ' as a vassal of ' + v.name + ': a lighter tribute for its protection; you may renounce it later'">⚑ Swear fealty</button>
                }
              }
            } @else if (v.id !== game.village()?.id) {
              <div class="btn-row">
                <button class="btn btn--small" (click)="send('reinforce')">Reinforce</button>
                <button class="btn btn--gold btn--small" (click)="open(v.id)">Open city</button>
              </div>
            } @else {
              <p class="small muted">Your city.</p>
            }
          } @else {
            <p class="small muted">{{ t.settleable ? 'Free land.' : 'Wilderness.' }}</p>
            @if (t.settleable && game.village()?.ver_sacrum; as vs) {
              <div class="colony">
                <h3 class="subhead">Ver sacrum</h3>
                @if (colonyError(); as err) {
                  <p class="small muted">{{ colonyText(err) }}</p>
                } @else {
                  <p class="small">Send the young of {{ game.village()!.name }} to found a colony here. You manage it; it pays {{ game.village()!.name }} tribute.</p>
                  <dio-cost [cost]="vs.cost" [have]="game.resources()" />
                  <p class="small muted">{{ distance()!.toFixed(1) }} of {{ vs.range }} tiles · the migrants arrive in {{ colonyEta() | dur }}</p>
                  <form class="colony__form" (ngSubmit)="foundColony()">
                    <input name="colony" [(ngModel)]="colonyName" maxlength="40" placeholder="Name of the colony" aria-label="Name of the colony" />
                    <button class="btn btn--gold btn--small">Found colony</button>
                  </form>
                }
              </div>
            }
          }
        } @else if (choosingColony()) {
          <p class="small">Choose a free tile inside the dashed circle to found your colony.</p>
        } @else {
          <p class="muted small">{{ touch ? 'Tap a tile to inspect it. Drag to pan, pinch to zoom.' : 'Click a tile to inspect it. Drag to pan, wheel to zoom.' }}</p>
        }
        <div class="legend small">
          <span><i class="ring ring--own"></i> Your cities</span>
          <span><i class="ring ring--other"></i> Others</span>
          <span><i class="halo"></i> Culture</span>
        </div>
      </aside>
    </section>
  `,
})
export class MapComponent implements AfterViewInit {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly art = inject(ArtService);
  private readonly router = inject(Router);
  private readonly labels = inject(Labels);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly wrap = viewChild.required<ElementRef<HTMLDivElement>>('wrap');

  protected readonly center = signal({ x: 0, y: 0 });
  /** Roads by id (public; drawn under the cities). */
  private readonly roads = signal(new Map<number, Road>());
  /** Jump here when opened from the chronicle (?x=&y=). */
  readonly x = input<string>();
  readonly y = input<string>();
  protected readonly selected = signal<Tile | null>(null);
  protected readonly tile = signal(34);
  protected readonly jx = signal(0);
  protected readonly jy = signal(0);
  private readonly villages = signal(new Map<string, MapVillage>());
  private readonly tiles = new Map<string, Tile>();
  private readonly loaded = new Set<string>();
  private readonly images = new Map<string, HTMLImageElement>();
  private readonly patterns = new Map<string, CanvasPattern | null>();
  private readonly redraw = signal(0);
  private size = { w: 0, h: 0 };
  protected drag: { x: number; y: number; cx: number; cy: number; moved: boolean } | null = null;

  protected readonly touch = typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches;
  protected readonly choosingColony = signal(this.router.url.includes('colony='));
  protected colonyName = '';
  protected readonly colonyError = computed(() => colonyBlocker(this.game.village(), this.selected(), this.selectedVillage()));
  protected readonly colonyEta = computed(() => {
    const v = this.game.village();
    const t = this.selected();
    return v?.ver_sacrum && t ? migrationSeconds(v, t, this.engine.pack()?.world.speed ?? 1) : 0;
  });

  protected colonyText(code: string): string {
    return this.labels.label(`error.${code}`, DEFAULT_LABELS[`error.${code}`] ?? code);
  }

  protected async foundColony(): Promise<void> {
    const v = this.game.village();
    const t = this.selected();
    if (v && t && (await this.game.act(() => this.api.verSacrum(v.id, t.x, t.y, this.colonyName), 'The migrants set out'))) {
      this.colonyName = '';
      this.choosingColony.set(false);
    }
  }

  protected readonly great = signal<GreatBuilding[]>([]);
  protected gift: Record<string, number> = {};
  protected readonly resourceList = computed(() =>
    (this.engine.pack()?.resources ?? []).map((r) => ({ id: r.id, name: r.name, icon: this.art.resourceIcon(r.id) })),
  );

  protected async inspect(id: number): Promise<void> {
    try {
      await this.game.inspect(id);
      await this.router.navigateByUrl('/');
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected buildingName(id: string): string {
    return this.engine.building(id)?.name ?? id;
  }

  private async loadGreat(v: MapVillage | undefined): Promise<void> {
    this.great.set([]);
    if (!v || v.npc) return;
    try {
      this.great.set((await this.api.greatNear(v.x, v.y, 0)).filter((g) => g.village?.id === v.id));
    } catch {
      // ignore
    }
  }

  protected async contribute(villageId: number, building: string): Promise<void> {
    const here = this.game.village();
    if (!here) return;
    const res = Object.fromEntries(Object.entries(this.gift).filter(([, n]) => Number(n) > 0).map(([k, n]) => [k, Math.floor(Number(n))]));
    if (await this.game.act(() => this.api.contribute(villageId, building, here.id, res), 'Contribution made')) {
      this.gift = {};
      await this.loadGreat(this.selectedVillage());
    }
  }

  protected readonly selectedVillage = computed(() => {
    const t = this.selected();
    return t ? this.villages().get(`${t.x},${t.y}`) : undefined;
  });
  protected readonly distance = computed(() => {
    const t = this.selected();
    const v = this.game.village();
    return t && v ? Math.hypot(t.x - v.x, t.y - v.y) : null;
  });

  constructor() {
    effect(() => void this.loadGreat(this.selectedVillage()));
    const v = this.game.village();
    if (v) this.center.set({ x: v.x, y: v.y });
    effect(() => {
      const c = this.center();
      this.jx.set(c.x);
      this.jy.set(c.y);
    });
    effect(() => {
      this.center();
      this.tile();
      this.villages();
      this.roads();
      this.selected();
      this.redraw();
      this.draw();
      void this.ensureLoaded();
    });
    queueMicrotask(() => {
      if (this.x() !== undefined && this.y() !== undefined) {
        const t = { x: Number(this.x()), y: Number(this.y()) };
        this.center.set(t);
        this.selected.set(this.tiles.get(`${t.x},${t.y}`) ?? ({ ...t, terrain: '', settleable: false } as Tile));
      }
    });
    const sub = this.game.mapEvents.subscribe((e) => {
      if (e.type === 'map.road_built') {
        this.roads.update((m) => new Map(m).set(e.data.id, { id: e.data.id, player_id: e.data.a.player_id, ready: true, ready_at: e.at, a: e.data.a, b: e.data.b }));
        return;
      }
      if (e.type === 'map.road_removed') {
        this.roads.update((m) => { const next = new Map(m); next.delete(e.data.id); return next; });
        return;
      }
      if (!e.type.startsWith('map.village')) return;
      for (const key of [...this.loaded]) if (this.chunkContains(key, e.data.x, e.data.y)) this.loaded.delete(key);
      void this.ensureLoaded();
    });
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  ngAfterViewInit(): void {
    let frame = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => this.resize());
    });
    ro.observe(this.wrap().nativeElement);
    this.resize();
    this.canvas().nativeElement.focus();
  }

  /** A road can join the city you are in with this one: yours, or your vassal. */
  protected roadable(v: MapVillage): { tiles: number; cost: Record<string, number> } | null {
    const here = this.game.village();
    if (!here?.roads || v.id === here.id) return null;
    const mine = v.player_id === this.game.me()?.id || (v.overlord_player_id === this.game.me()?.id);
    if (!mine || here.roads.list.some((r) => r.to.id === v.id) || here.roads.list.length >= here.roads.max) return null;
    const tiles = Math.round(Math.hypot(v.x - here.x, v.y - here.y) * 10) / 10;
    if (tiles > here.roads.max_length) return null;
    return { tiles, cost: Object.fromEntries(Object.entries(here.roads.cost_per_tile).map(([k, n]) => [k, Math.ceil(n * tiles)])) };
  }

  protected async buildRoad(v: MapVillage): Promise<void> {
    const here = this.game.village();
    if (here && (await this.game.act(() => this.api.buildRoad(here.id, v.id), 'The road builders set to work'))) {
      this.loaded.clear();
      void this.ensureLoaded();
    }
  }

  protected emblem(tribe: string): string | null {
    return this.art.url(this.art.civ(tribe)?.emblem);
  }

  protected tribeName(tribe: string): string {
    return this.engine.pack()?.tribes.find((t) => t.id === tribe)?.name ?? tribe;
  }

  private resize(): void {
    const el = this.canvas().nativeElement;
    const rect = this.wrap().nativeElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(200, Math.floor(rect.width));
    const h = Math.max(200, Math.floor(rect.height));
    if (w === this.size.w && h === this.size.h && el.width) return;
    this.size = { w, h };
    el.width = w * dpr;
    el.height = h * dpr;
    el.getContext('2d')!.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.patterns.clear();
    this.draw();
    void this.ensureLoaded();
  }

  private view() {
    const T = this.tile();
    const cols = Math.ceil(this.size.w / T) + 2;
    const rows = Math.ceil(this.size.h / T) + 2;
    const c = this.center();
    return { T, x0: c.x - Math.floor(cols / 2), y0: c.y - Math.floor(rows / 2), cols, rows };
  }

  private chunkContains(key: string, x: number, y: number): boolean {
    const [cx, cy] = key.split(',').map(Number);
    return x >= cx && x < cx + CHUNK && y >= cy && y < cy + CHUNK;
  }

  private async ensureLoaded(): Promise<void> {
    if (!this.size.w) return;
    const { x0, y0, cols, rows } = this.view();
    const fx = Math.floor(x0 / CHUNK) * CHUNK;
    const fy = Math.floor(y0 / CHUNK) * CHUNK;
    for (let cy = fy; cy < y0 + rows; cy += CHUNK) {
      for (let cx = fx; cx < x0 + cols; cx += CHUNK) {
        const key = `${cx},${cy}`;
        if (this.loaded.has(key)) continue;
        this.loaded.add(key);
        const local = this.engine.tiles(cx, cy, CHUNK, CHUNK);
        try {
          const area = await this.api.map(cx, cy, CHUNK, CHUNK);
          this.api.roads(cx, cy, CHUNK, CHUNK).then((rs) => this.roads.update((m) => {
            const next = new Map(m);
            for (const r of rs) next.set(r.id, r);
            return next;
          })).catch(() => undefined);
          for (const t of local ?? area.tiles) this.tiles.set(`${t.x},${t.y}`, t);
          this.villages.update((m) => {
            const next = new Map(m);
            for (const [k] of next) if (this.chunkContains(key, ...(k.split(',').map(Number) as [number, number]))) next.delete(k);
            for (const v of area.villages) next.set(`${v.x},${v.y}`, v);
            return next;
          });
        } catch {
          this.loaded.delete(key);
        }
      }
    }
  }

  /** Image cache; a finished load triggers a redraw. */
  private image(url: string | null): HTMLImageElement | null {
    if (!url) return null;
    let img = this.images.get(url);
    if (!img) {
      img = new Image();
      img.onload = () => {
        this.patterns.clear();
        this.redraw.update((n) => n + 1);
      };
      img.src = url;
      this.images.set(url, img);
    }
    return img.complete && img.naturalWidth ? img : null;
  }

  private fill(ctx: CanvasRenderingContext2D, terrain: string): string | CanvasPattern {
    const t = this.art.manifest()?.terrain;
    const src = { plain: t?.grass[0], forest: t?.forest, hills: t?.grass[2] ?? t?.dirt, beach: t?.dirt }[terrain as 'plain'];
    if (!src) return COLOURS[terrain] ?? '#777';
    if (!this.patterns.has(terrain)) {
      const img = this.image(this.art.url(src));
      if (!img) return COLOURS[terrain] ?? '#777';
      const p = ctx.createPattern(img, 'repeat');
      p?.setTransform(new DOMMatrix().scale(0.35));
      this.patterns.set(terrain, p);
    }
    return this.patterns.get(terrain) ?? COLOURS[terrain] ?? '#777';
  }

  private draw(): void {
    const el = this.canvas()?.nativeElement;
    if (!el || !this.size.w) return;
    const ctx = el.getContext('2d')!;
    const { T, x0, y0, cols, rows } = this.view();
    const offX = Math.floor((this.size.w - cols * T) / 2);
    const offY = Math.floor((this.size.h - rows * T) / 2);
    ctx.fillStyle = '#2f5470';
    ctx.fillRect(0, 0, this.size.w, this.size.h);
    // ground
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const t = this.tiles.get(`${x0 + i},${y0 + j}`);
        const px = offX + i * T, py = offY + j * T;
        if (!t) {
          ctx.fillStyle = '#1b140d';
          ctx.fillRect(px, py, T, T);
          continue;
        }
        ctx.fillStyle = this.fill(ctx, t.terrain);
        ctx.fillRect(px, py, T + 0.5, T + 0.5);
        if (t.terrain === 'water') {
          ctx.fillStyle = 'rgba(160, 210, 240, 0.08)';
          ctx.fillRect(px, py + T * 0.55, T, 1);
        } else if (t.terrain === 'mountain') {
          ctx.fillStyle = 'rgba(255, 255, 255, 0.18)';
          ctx.beginPath();
          ctx.moveTo(px + T * 0.2, py + T * 0.78);
          ctx.lineTo(px + T * 0.5, py + T * 0.22);
          ctx.lineTo(px + T * 0.8, py + T * 0.78);
          ctx.fill();
        } else if (t.terrain === 'forest') {
          ctx.fillStyle = 'rgba(20, 40, 15, 0.35)';
          for (const [a, b] of [[0.3, 0.35], [0.7, 0.4], [0.5, 0.72]]) {
            ctx.beginPath();
            ctx.arc(px + T * a, py + T * b, T * 0.16, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
    }
    // faint grid
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= cols; i++) { ctx.moveTo(offX + i * T + 0.5, 0); ctx.lineTo(offX + i * T + 0.5, this.size.h); }
    for (let j = 0; j <= rows; j++) { ctx.moveTo(0, offY + j * T + 0.5); ctx.lineTo(this.size.w, offY + j * T + 0.5); }
    ctx.stroke();
    // cultural influence: a soft halo out to the culture radius
    const radius = this.engine.pack()?.culture?.radius ?? 12;
    const meId = this.game.me()?.id;
    for (const v of this.villages().values()) {
      if (!v.culture) continue;
      const cx = offX + (v.x - x0) * T + T / 2, cy = offY + (v.y - y0) * T + T / 2;
      const R = radius * T;
      if (cx < -R || cy < -R || cx > this.size.w + R || cy > this.size.h + R) continue;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
      // a vassal's culture radiates for its overlord
      const rgb = (v.overlord_player_id ?? v.player_id) === meId ? '233, 196, 106' : '200, 80, 60';
      const a = Math.min(0.32, 0.08 + v.culture / 600);
      g.addColorStop(0, `rgba(${rgb}, ${a})`);
      g.addColorStop(1, `rgba(${rgb}, 0)`);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fill();
    }
    // built roads: a paved band; being built: dashed
    for (const r of this.roads().values()) {
      const ax = offX + (r.a.x - x0) * T + T / 2, ay = offY + (r.a.y - y0) * T + T / 2;
      const bx = offX + (r.b.x - x0) * T + T / 2, by = offY + (r.b.y - y0) * T + T / 2;
      const done = r.ready || r.ready_at <= this.game.now();
      ctx.lineCap = 'round';
      ctx.strokeStyle = 'rgba(40, 28, 16, 0.55)';
      ctx.lineWidth = Math.max(4, T * 0.22);
      ctx.setLineDash(done ? [] : [T * 0.3, T * 0.25]);
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
      ctx.strokeStyle = done ? 'rgba(214, 190, 140, 0.9)' : 'rgba(214, 190, 140, 0.5)';
      ctx.lineWidth = Math.max(2, T * 0.12);
      ctx.stroke();
      ctx.lineCap = 'butt';
    }
    ctx.setLineDash([]);
    // tribute roads: vassal to overlord
    const byId = new Map([...this.villages().values()].map((v) => [v.id, v]));
    ctx.setLineDash([6, 5]);
    ctx.lineWidth = 2;
    for (const v of byId.values()) {
      const lord = v.overlord_id ? byId.get(v.overlord_id) : undefined;
      if (!lord) continue;
      ctx.strokeStyle = lord.player_id === meId ? 'rgba(233, 196, 106, 0.8)' : 'rgba(200, 80, 60, 0.8)';
      ctx.beginPath();
      ctx.moveTo(offX + (v.x - x0) * T + T / 2, offY + (v.y - y0) * T + T / 2);
      ctx.lineTo(offX + (lord.x - x0) * T + T / 2, offY + (lord.y - y0) * T + T / 2);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    // cities
    const me = this.game.me()?.id;
    const here = this.game.village()?.id;
    ctx.textAlign = 'center';
    ctx.font = `600 ${Math.max(10, Math.round(T * 0.32))}px "Alegreya Sans", sans-serif`;
    for (const v of this.villages().values()) {
      const i = v.x - x0, j = v.y - y0;
      if (i < -1 || j < -1 || i > cols || j > rows) continue;
      const cx = offX + i * T + T / 2, cy = offY + j * T + T / 2;
      const r = T * (0.34 + Math.min(0.14, Math.sqrt(v.population) / 120));
      ctx.fillStyle = 'rgba(0,0,0,0.45)';
      ctx.beginPath();
      ctx.arc(cx + 1.5, cy + 2, r + 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = v.npc ? '#5b4630' : v.player_id === me ? '#e9c46a' : '#a33a24';
      ctx.beginPath();
      ctx.arc(cx, cy, r + 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#120d08';
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
      // a vassal shows its overlord's civilization, ringed in the overlord's colour
      const img = v.npc ? null : this.image(this.emblem(v.overlord_tribe ?? v.tribe));
      if (img) ctx.drawImage(img, cx - r, cy - r, r * 2, r * 2);
      if (v.npc) {
        ctx.fillStyle = '#e0b878';
        ctx.font = `${Math.round(r * 1.2)}px serif`;
        ctx.fillText('⚔', cx, cy + r * 0.42);
        ctx.font = `600 ${Math.max(10, Math.round(T * 0.32))}px "Alegreya Sans", sans-serif`;
      }
      if (v.overlord_id) {
        ctx.strokeStyle = v.overlord_player_id === me ? '#e9c46a' : '#a33a24';
        ctx.lineWidth = 3;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.arc(cx, cy, r + 2, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (v.id === here) {
        ctx.strokeStyle = '#fff3c4';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, r + 5, 0, Math.PI * 2);
        ctx.stroke();
      }
      const sel = this.selected();
      if (T >= 46 || v.player_id === me || (sel && sel.x === v.x && sel.y === v.y)) {
        ctx.fillStyle = 'rgba(0,0,0,0.65)';
        ctx.fillText(label(v), cx + 1, cy + r + T * 0.32 + 1);
        ctx.fillStyle = v.player_id === me ? '#f3e7c9' : '#f6d2c4';
        ctx.fillText(label(v), cx, cy + r + T * 0.32);
      }
    }
    // ver sacrum: reach of the migrants, and where they are heading
    const home = this.game.village();
    const vs = home?.ver_sacrum;
    if (home && vs) {
      const hx = offX + (home.x - x0) * T + T / 2, hy = offY + (home.y - y0) * T + T / 2;
      if (vs.available) {
        ctx.strokeStyle = 'rgba(233, 196, 106, 0.85)';
        ctx.fillStyle = 'rgba(233, 196, 106, 0.06)';
        ctx.setLineDash([8, 6]);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(hx, hy, vs.range * T, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);
      }
      for (const m of vs.migrations) {
        const mx = offX + (m.x - x0) * T + T / 2, my = offY + (m.y - y0) * T + T / 2;
        ctx.strokeStyle = 'rgba(243, 231, 201, 0.8)';
        ctx.setLineDash([2, 5]);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(hx, hy);
        ctx.lineTo(mx, my);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#e9c46a';
        ctx.beginPath();
        ctx.moveTo(mx, my - T * 0.3);
        ctx.lineTo(mx + T * 0.22, my + T * 0.2);
        ctx.lineTo(mx - T * 0.22, my + T * 0.2);
        ctx.fill();
      }
    }
    // selection
    const sel = this.selected();
    if (sel) {
      ctx.strokeStyle = '#ffe08a';
      ctx.lineWidth = 2;
      ctx.strokeRect(offX + (sel.x - x0) * T + 1, offY + (sel.y - y0) * T + 1, T - 2, T - 2);
    }
    // coordinates along the top edge
    ctx.fillStyle = 'rgba(243, 231, 201, 0.75)';
    ctx.font = '600 11px "Alegreya Sans", sans-serif';
    for (let i = 0; i < cols; i++) if ((x0 + i) % 5 === 0) ctx.fillText(String(x0 + i), offX + i * T + T / 2, 14);
    ctx.textAlign = 'left';
    for (let j = 0; j < rows; j++) if ((y0 + j) % 5 === 0) ctx.fillText(String(y0 + j), 6, offY + j * T + T / 2 + 4);
  }

  private tileAt(ev: { clientX: number; clientY: number }): { x: number; y: number } {
    const rect = this.canvas().nativeElement.getBoundingClientRect();
    const { T, x0, y0, cols, rows } = this.view();
    const offX = Math.floor((this.size.w - cols * T) / 2);
    const offY = Math.floor((this.size.h - rows * T) / 2);
    return { x: x0 + Math.floor((ev.clientX - rect.left - offX) / T), y: y0 + Math.floor((ev.clientY - rect.top - offY) / T) };
  }

  /** Active touch points, for pinch zoom. */
  private readonly touches = new Map<number, { x: number; y: number }>();
  private pinch: { dist: number; tile: number } | null = null;

  private spread(): number {
    const [a, b] = [...this.touches.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  protected down(ev: PointerEvent): void {
    this.touches.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    this.canvas().nativeElement.setPointerCapture(ev.pointerId);
    if (this.touches.size === 2) {
      this.pinch = { dist: this.spread(), tile: this.tile() };
      this.drag = null;
      return;
    }
    const c = this.center();
    this.drag = { x: ev.clientX, y: ev.clientY, cx: c.x, cy: c.y, moved: false };
  }

  protected move(ev: PointerEvent): void {
    if (this.touches.has(ev.pointerId)) this.touches.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (this.pinch && this.touches.size === 2) {
      const t = Math.round(this.pinch.tile * (this.spread() / Math.max(1, this.pinch.dist)));
      this.tile.set(Math.max(14, Math.min(64, t)));
      return;
    }
    const d = this.drag;
    if (!d) return;
    const T = this.tile();
    const dx = Math.round((d.x - ev.clientX) / T);
    const dy = Math.round((d.y - ev.clientY) / T);
    if (dx || dy) d.moved = true;
    if (d.moved) this.center.set({ x: d.cx + dx, y: d.cy + dy });
  }

  protected up(ev: PointerEvent): void {
    this.touches.delete(ev.pointerId);
    if (this.pinch) {
      if (this.touches.size < 2) this.pinch = null;
      this.drag = null;
      return;
    }
    const d = this.drag;
    this.drag = null;
    if (d && !d.moved) {
      const p = this.tileAt(ev);
      this.selected.set(this.tiles.get(`${p.x},${p.y}`) ?? { ...p, terrain: 'water', settleable: false });
    }
  }

  protected wheel(ev: WheelEvent): void {
    ev.preventDefault();
    this.zoom(ev.deltaY < 0 ? 1.15 : 1 / 1.15);
  }

  protected zoom(f: number): void {
    this.tile.update((t) => Math.max(14, Math.min(64, Math.round(t * f))));
  }

  protected key(ev: KeyboardEvent): void {
    const step: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const s = step[ev.key];
    if (s) {
      ev.preventDefault();
      this.center.update((c) => ({ x: c.x + s[0] * 3, y: c.y + s[1] * 3 }));
    } else if (ev.key === '+' || ev.key === '=') this.zoom(1.25);
    else if (ev.key === '-') this.zoom(0.8);
  }

  protected jump(): void {
    this.center.set({ x: Math.round(Number(this.jx())), y: Math.round(Number(this.jy())) });
  }

  protected home(): void {
    const v = this.game.village();
    if (v) this.center.set({ x: v.x, y: v.y });
  }

  protected async fealty(to: number, name: string): Promise<void> {
    const v = this.game.village();
    if (v) await this.game.act(() => this.api.offerFealty(v.id, to), `${v.name} offered fealty to ${name}`);
  }

  protected send(kind: string): void {
    const t = this.selected();
    if (t) void this.router.navigate(['/rally'], { queryParams: { x: t.x, y: t.y, kind } });
  }

  protected async open(id: number): Promise<void> {
    await this.game.selectVillage(id);
    await this.router.navigateByUrl('/');
  }

  protected close(): void {
    void this.router.navigateByUrl('/');
  }
}
