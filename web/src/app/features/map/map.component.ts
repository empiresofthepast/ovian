import { AfterViewInit, Component, DestroyRef, ElementRef, computed, effect, inject, input, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Api } from '../../core/api.service';
import { EngineService } from '../../core/engine.service';
import { GameStore } from '../../core/game.store';
import { MapVillage, Tile } from '../../core/models';
import { SkinService } from '../../core/skin.service';
import { UI } from '../../shared/ui';
import { BadgesComponent } from '../../shared/badges';
import { Badge } from '../../core/hub';
import { colonyBlocker, migrationSeconds } from '../../core/ver-sacrum';

const TILE = 30;
const CHUNK = 32;
const DEFAULT_TERRAIN: Record<string, string> = {
  plain: '#c9d48f', forest: '#6f9a55', hills: '#b7a46a', mountain: '#8d8578', water: '#6fa3c7', beach: '#e6d7a3',
};

@Component({
  selector: 'ov-map',
  imports: [FormsModule, BadgesComponent, ...UI],
  template: `
    <div class="page-head">
      <h1 class="page-title">{{ 'nav.map' | label }}</h1>
      <form class="map-jump" (ngSubmit)="jump()">
        <input type="number" name="jx" [ngModel]="jx()" (ngModelChange)="jx.set($event)" aria-label="x" />
        <span>|</span>
        <input type="number" name="jy" [ngModel]="jy()" (ngModelChange)="jy.set($event)" aria-label="y" />
        <button class="btn btn--ghost btn--small">Go</button>
        <button class="btn btn--ghost btn--small" type="button" (click)="home()">⌂</button>
      </form>
    </div>
    <div class="map-layout">
      <div class="map-wrap panel" #wrap>
        <canvas #canvas class="map-canvas" tabindex="0" aria-label="World map. Drag to pan, arrow keys to move, click a tile for details."
                (pointerdown)="down($event)" (pointermove)="move($event)" (pointerup)="up($event)" (pointerleave)="dragging = null"
                (keydown)="key($event)"></canvas>
        <div class="map-coords muted small">{{ center().x }}|{{ center().y }}</div>
      </div>
      <aside class="panel map-info">
        @if (selected(); as t) {
          <h2 class="panel__title">({{ t.x }}|{{ t.y }})</h2>
          <p class="small">{{ 'terrain.' + t.terrain | label: t.terrain }}</p>
          @if (selectedVillage(); as v) {
            <h3 class="subtitle">{{ v.name }}</h3>
            @if (v.abandoned_by) {<p class="small muted">🏚 Ruins of a city abandoned by {{ v.abandoned_by }}; barbarians hold it now@if (v.camp_level) { (camp level {{ v.camp_level }})}.</p>}
            @if (v.treacherous) {<p class="small bad" title="This ruler attacked a pact partner: their word is worth little">⚠ {{ 'map.treacherous' | label: 'Oath-breaker: broke a pact recently' }}</p>}
            <p class="small">{{ v.player_name }}@if (v.bot) { <span title="AI ruler">🤖</span>}@if (owner(); as o) {@if (o.id === v.player_id && o.badges.length) { <ov-badges [badges]="o.badges" [founderNo]="o.founder_no" />}} · {{ v.tribe | name: 'tribe' }} · <ov-icon key="stat.population" /> {{ v.population }}</p>
            @if (v.overlord_id) {<p class="small">⛓ Vassal of {{ v.overlord_name }} ({{ v.overlord_player_name }})</p>}
            @if (v.vassals) {<p class="small">Overlord of {{ v.vassals }} {{ v.vassals === 1 ? 'city' : 'cities' }}</p>}
            @if (distance() !== null) {<p class="small muted">{{ distance()!.toFixed(1) }} tiles away</p>}
            @if (v.player_id !== game.me()?.id) {
              @if (v.protected) {
                <p class="small muted">🛡 {{ 'map.protected' | label: 'Under beginner protection: it cannot be attacked or raided' }}@if (v.protected_until) { ({{ v.protected_until - game.now() | duration }} left)}.</p>
              }
              <div class="btn-row">
                @if (!v.protected) {
                  <button class="btn btn--primary btn--small" (click)="send('attack')">{{ 'kind.attack' | label }}</button>
                  <button class="btn btn--small" (click)="send('raid')">{{ 'kind.raid' | label }}</button>
                  <button class="btn btn--small" (click)="send('scout')">{{ 'kind.scout' | label }}</button>
                }
                <button class="btn btn--ghost btn--small" (click)="send('reinforce')">{{ 'kind.reinforce' | label }}</button>
              </div>
              @if (!v.npc && !game.village()?.submission) {
                @if (game.village()?.fealty_offer?.village?.id === v.id) {
                  <p class="small muted">{{ game.village()!.name }} has offered fealty to {{ v.name }}.</p>
                } @else {
                  <button class="btn btn--ghost btn--small" (click)="fealty(v.id, v.name)" [title]="'Offer ' + game.village()?.name + ' as a vassal of ' + v.name + ': a lighter tribute for its protection; you may renounce it later'">⚑ Swear fealty</button>
                }
              }
              @if (!v.npc && v.player_name) {
                <button class="btn btn--ghost btn--small" (click)="pact(v.player_name)" title="A promise of peace, with an optional tribute">🤝 {{ 'treaty.propose' | label: 'Propose a pact' }}</button>
              }
            } @else if (v.id !== game.village()?.id) {
              <div class="btn-row">
                <button class="btn btn--small" (click)="send('reinforce')">{{ 'kind.reinforce' | label }}</button>
                <button class="btn btn--ghost btn--small" (click)="open(v.id)">Open</button>
              </div>
            }
          } @else {
            <p class="small muted">{{ t.settleable ? ('map.free' | label: 'Free land') : ('map.wild' | label: 'Wilderness') }}</p>
            @if (game.village()?.ver_sacrum; as vs) {
              @if (t.settleable) {
                <h3 class="subtitle">{{ 'ver_sacrum' | label: 'Ver sacrum' }}</h3>
                @if (colonyError(); as err) {
                  <p class="small muted">{{ 'error.' + err | label }}</p>
                } @else {
                  <p class="small">Send the young of {{ game.village()!.name }} to found a colony here. You manage it; it pays {{ game.village()!.name }} tribute.</p>
                  <p class="small"><ov-cost [cost]="vs.cost" /></p>
                  <p class="small muted">{{ distance()!.toFixed(1) }} of {{ vs.range }} tiles · arrives in {{ colonyEta() * 1000 | duration }}</p>
                  <form class="btn-row" (ngSubmit)="foundColony()">
                    <input name="colony" [(ngModel)]="colonyName" maxlength="40" placeholder="Colony name" aria-label="Colony name" />
                    <button class="btn btn--primary btn--small">Found colony</button>
                  </form>
                }
              }
            }
          }
        } @else {
          <p class="muted small">Click a tile to inspect it.</p>
        }
        <div class="legend small">
          <span><i class="sw sw--own"></i> {{ 'map.own' | label: 'Your villages' }}</span>
          <span><i class="sw sw--other"></i> {{ 'map.other' | label: 'Other villages' }}</span>
          <span><span class="bad">●</span> {{ 'map.oath_breaker' | label: 'Oath-breaker' }}</span>
        </div>
      </aside>
    </div>
  `,
})
export class MapComponent implements AfterViewInit {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly skin = inject(SkinService);
  private readonly router = inject(Router);
  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly wrap = viewChild.required<ElementRef<HTMLDivElement>>('wrap');

  protected readonly center = signal({ x: 0, y: 0 });
  protected readonly selected = signal<Tile | null>(null);
  private readonly villages = signal(new Map<string, MapVillage>());
  private readonly tiles = new Map<string, Tile>();
  private readonly loaded = new Set<string>();
  private size = { w: 0, h: 0 };
  protected dragging: { x: number; y: number; cx: number; cy: number; moved: boolean } | null = null;
  // Query params (?x=&y=): centre on and select that tile, e.g. from the chronicle.
  readonly x = input<string>();
  readonly y = input<string>();
  private pendingSelect: string | null = null;
  protected readonly jx = signal(0);
  protected readonly jy = signal(0);

  protected readonly selectedVillage = computed(() => {
    const t = this.selected();
    return t ? this.villages().get(`${t.x},${t.y}`) : undefined;
  });
  /** The selected city's ruler: badges (founder, patron, awards), fetched once per player. */
  protected readonly owner = signal<{ id: number; badges: Badge[]; founder_no: number | null } | null>(null);
  private readonly owners = new Map<number, Promise<{ id: number; badges: Badge[]; founder_no: number | null }>>();
  protected readonly distance = computed(() => {
    const t = this.selected();
    const v = this.game.village();
    return t && v ? Math.hypot(t.x - v.x, t.y - v.y) : null;
  });

  constructor() {
    const v = this.game.village();
    if (v) this.center.set({ x: v.x, y: v.y });
    queueMicrotask(() => {
      const qx = Number(this.x()), qy = Number(this.y());
      if (this.x() === undefined || this.y() === undefined || !isFinite(qx) || !isFinite(qy)) return;
      this.center.set({ x: qx, y: qy });
      this.selected.set(this.tiles.get(`${qx},${qy}`) ?? { x: qx, y: qy, terrain: 'plain', settleable: false });
      this.pendingSelect = `${qx},${qy}`;
    });
    effect(() => {
      const id = this.selectedVillage()?.player_id;
      if (!id) return;
      let p = this.owners.get(id);
      if (!p) {
        p = this.api.player(id).then(
          (r) => ({ id, badges: (r?.badges ?? []) as Badge[], founder_no: r?.founder_no ?? null }),
          () => ({ id, badges: [], founder_no: null }),
        );
        this.owners.set(id, p);
      }
      void p.then((o) => {
        if (this.selectedVillage()?.player_id === id) this.owner.set(o);
      });
    });
    effect(() => {
      const c = this.center();
      this.jx.set(c.x);
      this.jy.set(c.y);
    });
    effect(() => {
      this.center();
      this.villages();
      this.selected();
      this.skin.skin();
      this.draw();
      void this.ensureLoaded();
    });
    const sub = this.game.mapEvents.subscribe((e) => {
      if (e.type.startsWith('map.village')) {
        for (const key of [...this.loaded]) if (this.chunkContains(key, e.data.x, e.data.y)) this.loaded.delete(key);
        void this.ensureLoaded();
      }
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
  }

  private resize(): void {
    const el = this.canvas().nativeElement;
    const rect = this.wrap().nativeElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(200, Math.floor(rect.width));
    const h = Math.max(240, Math.min(720, window.innerHeight - 220));
    if (w === this.size.w && h === this.size.h && el.width) return;
    this.size = { w, h };
    el.width = w * dpr;
    el.height = h * dpr;
    el.style.width = '100%';
    el.style.height = `${h}px`;
    el.getContext('2d')!.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
    void this.ensureLoaded();
  }

  private view() {
    const cols = Math.ceil(this.size.w / TILE) + 1;
    const rows = Math.ceil(this.size.h / TILE) + 1;
    const c = this.center();
    return { x0: c.x - Math.floor(cols / 2), y0: c.y - Math.floor(rows / 2), cols, rows };
  }

  private chunkContains(key: string, x: number, y: number): boolean {
    const [cx, cy] = key.split(',').map(Number);
    return x >= cx && x < cx + CHUNK && y >= cy && y < cy + CHUNK;
  }

  private async ensureLoaded(): Promise<void> {
    const { x0, y0, cols, rows } = this.view();
    const fx = Math.floor(x0 / CHUNK) * CHUNK;
    const fy = Math.floor(y0 / CHUNK) * CHUNK;
    for (let cy = fy; cy < y0 + rows; cy += CHUNK) {
      for (let cx = fx; cx < x0 + cols; cx += CHUNK) {
        const key = `${cx},${cy}`;
        if (this.loaded.has(key)) continue;
        this.loaded.add(key);
        // Terrain is procedural: compute it locally when WASM is loaded, otherwise the API returns it.
        const local = this.engine.tiles(cx, cy, CHUNK, CHUNK);
        try {
          const area = await this.api.map(cx, cy, CHUNK, CHUNK);
          for (const t of local ?? area.tiles) this.tiles.set(`${t.x},${t.y}`, t);
          if (this.pendingSelect && this.tiles.has(this.pendingSelect)) {
            this.selected.set(this.tiles.get(this.pendingSelect)!);
            this.pendingSelect = null;
          }
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

  private draw(): void {
    const el = this.canvas()?.nativeElement;
    if (!el) return;
    const ctx = el.getContext('2d')!;
    const colors = { ...DEFAULT_TERRAIN, ...(this.skin.skin()?.map?.terrain ?? {}) };
    const m = this.skin.skin()?.map ?? {};
    const css = getComputedStyle(document.documentElement);
    const { x0, y0, cols, rows } = this.view();
    const offX = (this.size.w - cols * TILE) / 2 + TILE / 2;
    const offY = (this.size.h - rows * TILE) / 2 + TILE / 2;
    ctx.fillStyle = colors['water'];
    ctx.fillRect(0, 0, this.size.w, this.size.h);
    const myId = this.game.me()?.id;
    const sel = this.selected();
    ctx.font = `600 10px ${css.getPropertyValue('--font-body') || 'sans-serif'}`;
    ctx.textAlign = 'center';
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const x = x0 + i;
        const y = y0 + j;
        const px = offX + i * TILE - TILE / 2;
        const py = offY + j * TILE - TILE / 2;
        const t = this.tiles.get(`${x},${y}`);
        ctx.fillStyle = t ? (colors[t.terrain] ?? '#999') : '#00000022';
        ctx.fillRect(px, py, TILE, TILE);
        ctx.strokeStyle = m.grid ?? 'rgba(0,0,0,0.08)';
        ctx.strokeRect(px + 0.5, py + 0.5, TILE - 1, TILE - 1);
        const v = this.villages().get(`${x},${y}`);
        if (v) {
          ctx.fillStyle = v.player_id === myId ? (m.own ?? '#1f5fa8') : (m.other ?? '#9b3b1b');
          const r = 6 + Math.min(6, Math.sqrt(v.population) / 2);
          ctx.beginPath();
          ctx.roundRect(px + TILE / 2 - r, py + TILE / 2 - r, r * 2, r * 2, 3);
          ctx.fill();
          if (v.treacherous) {
            // an oath-breaker: a small red mark in the corner
            ctx.fillStyle = css.getPropertyValue('--bad').trim() || '#c0392b';
            ctx.beginPath();
            ctx.arc(px + TILE - 6, py + 6, 4, 0, Math.PI * 2);
            ctx.fill();
          }
          if (v.overlord_id) {
            // a vassal: dashed outline in its overlord's colour
            ctx.strokeStyle = v.overlord_player_id === myId ? (m.own ?? '#1f5fa8') : (m.other ?? '#9b3b1b');
            ctx.setLineDash([3, 2]);
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.roundRect(px + TILE / 2 - r - 3, py + TILE / 2 - r - 3, r * 2 + 6, r * 2 + 6, 4);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.lineWidth = 1;
          }
        }
        if (sel && sel.x === x && sel.y === y) {
          ctx.strokeStyle = m.selected ?? '#fff';
          ctx.lineWidth = 2;
          ctx.strokeRect(px + 1, py + 1, TILE - 2, TILE - 2);
          ctx.lineWidth = 1;
        }
      }
    }
    // ver sacrum: how far a colony may go
    const here = this.game.village();
    if (here?.ver_sacrum?.available) {
      ctx.strokeStyle = m.own ?? '#1f5fa8';
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(offX + (here.x - x0) * TILE, offY + (here.y - y0) * TILE, here.ver_sacrum.range * TILE, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.lineWidth = 1;
    }
    ctx.fillStyle = m.label ?? 'rgba(0,0,0,0.55)';
    for (let i = 0; i < cols; i += 5) ctx.fillText(String(x0 + i), offX + i * TILE, 12);
  }

  private tileAt(ev: PointerEvent): { x: number; y: number } {
    const rect = this.canvas().nativeElement.getBoundingClientRect();
    const { x0, y0, cols, rows } = this.view();
    const offX = (this.size.w - cols * TILE) / 2;
    const offY = (this.size.h - rows * TILE) / 2;
    return { x: x0 + Math.floor((ev.clientX - rect.left - offX) / TILE), y: y0 + Math.floor((ev.clientY - rect.top - offY) / TILE) };
  }

  protected down(ev: PointerEvent): void {
    const c = this.center();
    this.dragging = { x: ev.clientX, y: ev.clientY, cx: c.x, cy: c.y, moved: false };
    this.canvas().nativeElement.setPointerCapture(ev.pointerId);
  }

  protected move(ev: PointerEvent): void {
    const d = this.dragging;
    if (!d) return;
    const dx = Math.round((d.x - ev.clientX) / TILE);
    const dy = Math.round((d.y - ev.clientY) / TILE);
    if (dx || dy) d.moved = true;
    if (d.moved) this.center.set({ x: d.cx + dx, y: d.cy + dy });
  }

  protected up(ev: PointerEvent): void {
    const d = this.dragging;
    this.dragging = null;
    if (d && !d.moved) {
      const p = this.tileAt(ev);
      this.selected.set(this.tiles.get(`${p.x},${p.y}`) ?? { ...p, terrain: 'water', settleable: false });
    }
  }

  protected key(ev: KeyboardEvent): void {
    const step: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const s = step[ev.key];
    if (!s) return;
    ev.preventDefault();
    this.center.update((c) => ({ x: c.x + s[0] * 3, y: c.y + s[1] * 3 }));
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

  protected pact(player: string): void {
    void this.router.navigate(['/realm'], { queryParams: { pact: player }, fragment: 'pacts' });
  }

    protected send(kind: string): void {
    const t = this.selected();
    if (t) void this.router.navigate(['/rally'], { queryParams: { x: t.x, y: t.y, kind } });
  }

  protected colonyName = '';
  protected readonly colonyError = computed(() => colonyBlocker(this.game.village(), this.selected(), this.selectedVillage()));
  protected readonly colonyEta = computed(() => {
    const v = this.game.village();
    const t = this.selected();
    return v?.ver_sacrum && t ? migrationSeconds(v, t, this.engine.pack()?.world.speed ?? 1) : 0;
  });

  protected async foundColony(): Promise<void> {
    const v = this.game.village();
    const t = this.selected();
    if (v && t && (await this.game.act(() => this.api.verSacrum(v.id, t.x, t.y, this.colonyName), 'The migrants set out'))) this.colonyName = '';
  }

  protected async open(id: number): Promise<void> {
    await this.game.selectVillage(id);
    await this.router.navigateByUrl('/village');
  }
}
