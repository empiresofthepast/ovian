import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { ART_BASE, CivArt, Manifest, StructureArt } from '../art/art.service';
import { ActorFactory } from './actors';
import type { ScenePrefs } from '../prefs.service';

/** What the scene needs to know about one building site. */
export interface SiteView {
  index: number;
  area: 'center' | 'field';
  building: string | null;
  level: number;
  /** A level 0 building is under construction. */
  founding: boolean;
  /** A ruined building (a lost overlord's embassy): drawn low, on its foundation. */
  ruin?: boolean;
  /** A site reserved for a building nobody has started (an embassy awaiting its overlord). */
  idle?: boolean;
  upgrading: boolean;
  /** For fields: wood | stone | metal | food. */
  fieldKind: string | null;
  structure: StructureArt | null;
  role: 'civic' | 'rally' | 'wall' | 'other';
  /** Not yet open in the current growth phase: nothing is drawn. */
  locked: boolean;
  /** A foreign-quarter site: it lies outside the town, on ground of its own. */
  foreign?: boolean;
  /** Diggers are at work on this site (archaeology). */
  digging?: boolean;
}

export interface VillageSceneView {
  id: number;
  civ: string;
  sites: SiteView[];
  wallLevel: number;
}

interface Placement {
  x: number;
  z: number;
  /** Ring radius, 0 for the civic centre and for fields. */
  ring: number;
  /** Radius available to whatever stands here. */
  r: number;
  angle: number;
}

interface SiteObject {
  key: string;
  group: THREE.Group;
  hit: THREE.Mesh;
  badge: CSS2DObject;
  height: number;
  version: number;
}

const OWN_COLOUR = new THREE.Color(0x2e64d8);
const GOLD = new THREE.Color(0xf0c75e);

/**
 * A three.js diorama of one village. Angular owns the data; this class only
 * renders it and reports clicks. Call `setVillage` whenever the view changes.
 */
export class VillageScene {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly labels = new CSS2DRenderer();
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(32, 1, 4, 3000);
  private readonly controls: OrbitControls;
  private readonly factory: ActorFactory;
  private readonly clock = new THREE.Clock();
  private readonly ray = new THREE.Raycaster();
  private readonly sites = new Map<number, SiteObject>();
  private readonly world = new THREE.Group();
  private decor = new THREE.Group();
  private walls = new THREE.Group();
  private wallKey = '';
  private layout: { center: Placement[]; fields: Placement[]; townRadius: number; fieldRadius: number } | null = null;
  private layoutKey = '';
  /** Placement of each open field by site index, and the index of the first center site. */
  private fieldAt = new Map<number, Placement>();
  private centerAt = new Map<number, Placement>();
  private hoverRing: THREE.Mesh;
  private selectRing: THREE.Mesh;
  private selected: number | null = null;
  private hovered: number | null = null;
  private frame = 0;
  private resizeObs: ResizeObserver;
  private down: { x: number; y: number } | null = null;
  private disposed = false;
  private paused = false;
  private prefs: ScenePrefs | null = null;
  private civ: CivArt | null = null;

  constructor(
    private readonly host: HTMLElement,
    private readonly manifest: Manifest,
    private readonly events: { select(index: number | null): void; hover(index: number | null): void },
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.domElement.className = 'scene-canvas';
    host.appendChild(this.renderer.domElement);
    this.labels.domElement.className = 'scene-labels';
    host.appendChild(this.labels.domElement);

    this.factory = new ActorFactory(manifest, this.renderer.capabilities.getMaxAnisotropy());

    const sky = new THREE.Color(0xb7cfe3);
    this.scene.background = sky;
    this.scene.fog = new THREE.Fog(sky, 520, 1250);
    this.scene.add(new THREE.HemisphereLight(0xe3ecff, 0x6b5a3a, 1.25));
    const sun = new THREE.DirectionalLight(0xfff0d2, 2.6);
    sun.position.set(-210, 300, 170);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.bias = -0.0003;
    sun.shadow.normalBias = 0.5;
    this.scene.add(sun, sun.target);
    this.sun = sun;
    this.scene.add(this.world);
    this.world.add(this.decor, this.walls);

    this.hoverRing = ring(0xf0c75e, 0.35);
    this.selectRing = ring(0xffe08a, 0.9);
    this.scene.add(this.hoverRing, this.selectRing);

    this.camera.position.set(0, 210, 250);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.screenSpacePanning = false;
    this.controls.minDistance = 55;
    this.controls.maxDistance = 520;
    this.controls.minPolarAngle = 0.35;
    this.controls.maxPolarAngle = 1.22;
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
    this.controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
    this.controls.zoomToCursor = true;

    const el = this.renderer.domElement;
    el.addEventListener('pointerdown', this.onDown);
    el.addEventListener('pointerup', this.onUp);
    el.addEventListener('pointermove', this.onMove);
    el.addEventListener('contextmenu', (e) => e.preventDefault());
    addEventListener('keydown', this.onKey);

    (globalThis as any).ovianScene = this; // for debugging from the console
    this.resizeObs = new ResizeObserver(() => requestAnimationFrame(() => this.resize()));
    this.resizeObs.observe(host);
    this.resize();
    this.loop();
  }

  private readonly sun: THREE.DirectionalLight;

  // ------------------------------------------------------------------ data
  setVillage(v: VillageSceneView): void {
    this.civ = this.manifest.civs[v.civ] ?? null;
    const centers = v.sites.filter((s) => s.area === 'center').length;
    // open fields (extra ones too) on one ring, each next to fields of its kind
    const order: string[] = [];
    for (const s of v.sites) if (s.area === 'field' && !order.includes(s.fieldKind ?? 'food')) order.push(s.fieldKind ?? 'food');
    const fieldSites = v.sites
      .filter((s) => s.area === 'field' && !s.locked)
      .sort((a, b) => order.indexOf(a.fieldKind ?? 'food') - order.indexOf(b.fieldKind ?? 'food') || a.index - b.index);
    const fieldKinds = fieldSites.map((s) => s.fieldKind ?? 'food');
    const key = `${v.id}:${centers}:${fieldSites.map((s) => s.index).join(',')}`;
    if (key !== this.layoutKey) {
      this.layoutKey = key;
      this.clearSites();
      this.layout = computeLayout(centers, fieldKinds);
      this.fieldAt = new Map(fieldSites.map((s, i) => [s.index, this.layout!.fields[i]]));
      // center sites in order, the foreign quarter last: it lies at the edge of the town
      this.centerAt = new Map(v.sites.filter((s) => s.area === 'center').map((s, i) => [s.index, this.layout!.center[i]]));
      this.groundKey = '';
      void this.buildDecor(v.id, fieldKinds);
      this.framed = false;
    }
    // the town spreads to the outermost ring with an open (or built) site
    // (the foreign quarter lies outside it, on patches of its own)
    const open = v.sites.filter((s) => s.area === 'center' && !s.locked && !s.foreign).map((s) => this.centerAt.get(s.index)?.ring ?? 0);
    const reach = Math.max(0, ...open) + 26;
    const groundKey = `${v.id}:${reach}`;
    if (groundKey !== this.groundKey) {
      this.groundKey = groundKey;
      this.townReach = reach;
      this.buildGround(v.id);
      this.wallKey = '';
    }
    if (!this.framed) {
      this.framed = true;
      this.frameCamera();
    }
    for (const s of v.sites) {
      if (s.locked) this.removeSite(s.index);
      else void this.updateSite(v, s);
    }
    void this.updateWalls(v);
  }

  select(index: number | null): void {
    this.selected = index;
    this.placeRing(this.selectRing, index);
  }

  /** Display preferences: shadows, resolution, badges, forest. */
  applyPrefs(p: ScenePrefs): void {
    this.prefs = p;
    this.sun.castShadow = p.shadows;
    const ratio = p.quality === 'low' ? 1 : p.quality === 'medium' ? Math.min(devicePixelRatio, 1.5) : Math.min(devicePixelRatio, 2);
    if (this.renderer.getPixelRatio() !== ratio) {
      this.renderer.setPixelRatio(ratio);
      this.renderer.setSize(this.host.clientWidth || 1, this.host.clientHeight || 1, false);
    }
    this.labels.domElement.hidden = !p.badges;
    this.decor.visible = p.decor;
  }

  /** Stop drawing while a full-screen view covers the scene. */
  setPaused(paused: boolean): void {
    this.paused = paused;
    if (!paused) this.clock.getDelta();
  }

  /** Debug summary of one site: what was built and how big it is. */
  inspect(index: number): unknown {
    const s = this.sites.get(index);
    if (!s) return null;
    const box = new THREE.Box3().setFromObject(s.group);
    let meshes = 0, visible = 0;
    s.group.traverse((o) => { if ((o as THREE.Mesh).isMesh) { meshes++; if (o.visible) visible++; } });
    return { key: s.key, pos: s.group.position.toArray(), min: box.min.toArray(), max: box.max.toArray(), meshes, visible,
      scale: s.group.children[0]?.scale.toArray() };
  }

  /** Fly the camera to a site. */
  focus(index: number): void {
    const p = this.placementOf(index);
    if (!p) return;
    const offset = this.camera.position.clone().sub(this.controls.target);
    this.controls.target.set(p.x, 0, p.z);
    this.camera.position.copy(this.controls.target).add(offset);
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.resizeObs.disconnect();
    removeEventListener('keydown', this.onKey);
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.domElement.remove();
  }

  // ------------------------------------------------------------------ sites
  private placementOf(index: number): Placement | null {
    const l = this.layout;
    if (!l) return null;
    return this.fieldAt.get(index) ?? this.centerAt.get(index) ?? null;
  }

  private async updateSite(v: VillageSceneView, s: SiteView): Promise<void> {
    const p = this.placementOf(s.index);
    if (!p) return;
    const key = [s.building, s.level, s.founding, s.upgrading, s.ruin, s.idle, s.digging, s.structure?.actor, v.civ].join(':');
    let obj = this.sites.get(s.index);
    if (obj && obj.key === key) return;
    if (!obj) {
      const hit = new THREE.Mesh(new THREE.CylinderGeometry(p.r, p.r, 6, 24), new THREE.MeshBasicMaterial({ visible: false }));
      hit.position.set(p.x, 3, p.z);
      hit.userData['site'] = s.index;
      const badgeEl = document.createElement('div');
      badgeEl.className = 'site-badge';
      const badge = new CSS2DObject(badgeEl);
      badge.center.set(0.5, 1);
      this.world.add(hit, badge);
      obj = { key: '', group: new THREE.Group(), hit, badge, height: 10, version: 0 };
      this.world.add(obj.group);
      this.sites.set(s.index, obj);
    }
    obj.key = key;
    const version = ++obj.version;
    const group = await this.buildSite(s, p, v.id);
    if (this.disposed || version !== obj.version) return;
    this.world.remove(obj.group);
    obj.group = group;
    this.world.add(group);
    const box = new THREE.Box3().setFromObject(group);
    // skinned meshes report loose bounds; keep badges near the roofs
    obj.height = box.isEmpty() ? 4 : Math.min(s.role === 'civic' ? 34 : 24, Math.max(4, box.max.y));
    obj.badge.position.set(p.x, obj.height + 3, p.z + p.r * 0.35);
    const el = obj.badge.element as HTMLElement;
    el.textContent = s.digging ? '⛏' : s.ruin ? '' : s.building && (s.level > 0 || s.founding) ? (s.founding ? '⚒' : String(s.level)) : '';
    el.classList.toggle('site-badge--busy', s.upgrading || s.founding || !!s.digging);
    el.hidden = !el.textContent;
    if (this.selected === s.index) this.placeRing(this.selectRing, s.index);
  }

  private async buildSite(s: SiteView, p: Placement, seed: number): Promise<THREE.Group> {
    const g = new THREE.Group();
    g.position.set(p.x, 0.12, p.z); // above the ground patches
    const rnd = rng(seed * 131 + s.index * 977);
    if (s.area === 'field') {
      await this.buildField(g, s, p, rnd);
      return g;
    }
    const facing = Math.atan2(-p.x, -p.z) || 0; // doors toward the civic centre
    if (s.foreign) g.add(this.square(this.manifest.terrain.dirt, p.r * 2.3));
    if (s.digging) await this.digPit(g, p, rnd);
    if (!s.building || s.idle) {
      if (!s.digging) g.add(siteMarker(p.r));
      return g;
    }
    if (s.role === 'rally') {
      const flag = await this.factory.create(this.civ?.flag, { player: OWN_COLOUR });
      flag.scale.setScalar(1.6);
      g.add(flag);
      return g;
    }
    const art = s.structure;
    if (s.ruin) {
      // a broken stump of the old building on its bare foundation
      if (art?.foundation) {
        const base = await this.factory.create(art.foundation, {});
        fit(base, p.r * 2 * 0.95);
        base.rotation.y = facing;
        g.add(base);
      }
      const stump = await this.factory.create(art?.actor, { opacity: 0.85, seed: s.index });
      stump.rotation.y = facing + 0.15;
      fit(stump, p.r * 2 * 0.9);
      stump.scale.y *= 0.28;
      g.add(stump);
      return g;
    }
    const id = s.founding && s.level === 0 ? (art?.foundation ?? art?.actor) : art?.actor;
    const building = await this.factory.create(id, { player: OWN_COLOUR, seed: s.index });
    building.rotation.y = s.role === 'civic' ? 0 : facing;
    fit(building, p.r * 2 * 0.95);
    g.add(building);
    if (s.upgrading && art?.foundation && s.level > 0) {
      // scaffolding peeks out under the building while it is being upgraded
      const scaffold = await this.factory.create(art.foundation, { opacity: 0.9 });
      fit(scaffold, p.r * 2 * 1.02);
      scaffold.rotation.y = building.rotation.y;
      scaffold.scale.y *= 0.35;
      g.add(scaffold);
    }
    return g;
  }

  private async buildField(g: THREE.Group, s: SiteView, p: Placement, rnd: () => number): Promise<void> {
    const kind = s.fieldKind ?? 'food';
    const lv = s.level;
    const gaia = this.manifest.gaia;
    const ground = { wood: this.manifest.terrain.forest, stone: this.manifest.terrain.dirt, metal: this.manifest.terrain.dirt, food: null }[kind as 'wood'] ?? null;
    if (ground) g.add(this.patch(ground, p.r * 1.05));
    if (kind === 'wood') {
      const n = Math.min(14, 3 + lv);
      for (let i = 0; i < n; i++) {
        const a = rnd() * Math.PI * 2;
        const d = Math.sqrt(rnd()) * p.r * 0.85;
        const t = await this.factory.create(pick(gaia['wood'], i + Math.floor(rnd() * 5)), { seed: Math.floor(rnd() * 100) });
        t.position.set(Math.cos(a) * d, 0, Math.sin(a) * d);
        t.rotation.y = rnd() * Math.PI * 2;
        t.scale.setScalar((lv === 0 ? 0.55 : 0.75) + rnd() * 0.35);
        g.add(t);
      }
      return;
    }
    if (kind === 'stone' || kind === 'metal') {
      const set = gaia[kind];
      const main = await this.factory.create(lv === 0 ? pick(set, 2) : set[0], { seed: s.index });
      fit(main, p.r * (lv === 0 ? 0.9 : 1.1 + lv * 0.07));
      main.rotation.y = rnd() * Math.PI * 2;
      g.add(main);
      for (let i = 0; i < Math.floor(lv / 2); i++) {
        const r = await this.factory.create(pick(set, 1 + (i % 2)), { seed: i });
        const a = rnd() * Math.PI * 2;
        r.position.set(Math.cos(a) * p.r * 0.75, 0, Math.sin(a) * p.r * 0.75);
        fit(r, p.r * 0.45);
        r.rotation.y = rnd() * 6;
        g.add(r);
      }
      return;
    }
    // grain: a square of farmland planted in rows; more rows ripen with every level
    const side = p.r * 1.55;
    const soil = this.square(this.manifest.terrain.farmland ?? this.manifest.terrain.dirt, side);
    soil.rotation.y = Math.atan2(-p.x, -p.z);
    g.add(soil);
    const crops = gaia['food'] ?? [];
    if (!crops.length || lv === 0) return;
    const rows = Math.min(8, 2 + Math.ceil(lv * 0.6));
    const per = 7;
    const rowGroup = new THREE.Group();
    rowGroup.rotation.y = soil.rotation.y;
    const jobs: Promise<void>[] = [];
    for (let row = 0; row < rows; row++) {
      for (let k = 0; k < per; k++) {
        const x = (-0.5 + (k + 0.5) / per) * side * 0.88 + (rnd() - 0.5) * 0.8;
        const z = (-0.5 + (row + 0.5) / 8) * side * 0.88;
        jobs.push(
          this.factory.create(pick(crops, row + k), { seed: row * per + k }).then((c) => {
            c.position.set(x, 0, z);
            c.rotation.y = rnd() * 6.28;
            c.scale.setScalar(0.75 + rnd() * 0.25);
            rowGroup.add(c);
          }),
        );
      }
    }
    await Promise.all(jobs);
    g.add(rowGroup);
  }

  /** An excavation: a dark pit of turned earth with a few tools and finds-baskets around it. */
  private async digPit(g: THREE.Group, p: Placement, rnd: () => number): Promise<void> {
    const dirt = this.manifest.terrain.dirt;
    const turn = Math.atan2(-p.x, -p.z);
    const outer = this.square(dirt, p.r * 1.45);
    tint(outer, 0x8a7258);
    const pit = this.square(dirt, p.r * 0.95);
    tint(pit, 0x3b2c1e);
    pit.position.y = 0.02;
    outer.rotation.y = pit.rotation.y = turn;
    g.add(outer, pit);
    const props = ['props/special/eyecandy/plank_pile_big_01', 'props/special/eyecandy/sack_1', 'props/special/eyecandy/crate_a', 'props/special/eyecandy/vase']
      .filter((id) => this.factory.has(id));
    const jobs = props.map(async (id, i) => {
      const o = await this.factory.create(id, { seed: i });
      const a = turn + Math.PI / 4 + (i * Math.PI) / 2 + (rnd() - 0.5) * 0.3;
      o.position.set(Math.cos(a) * p.r * 0.72, 0, Math.sin(a) * p.r * 0.72);
      o.rotation.y = rnd() * Math.PI * 2;
      fit(o, p.r * (i === 0 ? 0.55 : 0.28));
      g.add(o);
    });
    await Promise.all(jobs);
  }

  /** A square of ground texture with soft edges. */
  private square(texture: string, side: number): THREE.Object3D {
    const tex = this.factory.texture(texture, true).clone();
    tex.needsUpdate = true;
    tex.repeat.set(side / 12, side / 12);
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(side, side),
      new THREE.MeshStandardMaterial({ map: tex, alphaMap: squareAlpha(), transparent: true, depthWrite: false, roughness: 1, polygonOffset: true, polygonOffsetFactor: -3 }),
    );
    m.geometry.rotateX(-Math.PI / 2);
    m.position.y = 0.03;
    m.receiveShadow = true;
    m.renderOrder = 1;
    const holder = new THREE.Group();
    holder.add(m);
    return holder;
  }

  private async updateWalls(v: VillageSceneView): Promise<void> {
    const l = this.layout;
    if (!l) return;
    const tower = this.civ?.structures['wall_tower'];
    const count = v.wallLevel > 0 ? Math.min(18, 6 + v.wallLevel) : 0;
    const key = `${tower?.actor}:${count}`;
    if (key === this.wallKey) return;
    this.wallKey = key;
    const g = new THREE.Group();
    const r = this.townReach + 4;
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2 + 0.2;
      const t = await this.factory.create(tower?.actor, { player: OWN_COLOUR });
      fit(t, 11);
      t.position.set(Math.cos(a) * r, 0, Math.sin(a) * r);
      t.rotation.y = -a;
      g.add(t);
    }
    if (key !== this.wallKey) return;
    this.world.remove(this.walls);
    this.walls = g;
    this.world.add(g);
  }

  private removeSite(index: number): void {
    const s = this.sites.get(index);
    if (!s) return;
    this.world.remove(s.group, s.hit, s.badge);
    s.badge.element.remove();
    s.version++;
    this.sites.delete(index);
  }

  private clearSites(): void {
    for (const s of this.sites.values()) {
      this.world.remove(s.group, s.hit, s.badge);
      s.badge.element.remove();
    }
    this.sites.clear();
    this.wallKey = '';
  }

  // ------------------------------------------------------------------ ground and decor
  private ground: THREE.Object3D[] = [];
  private groundKey = '';
  private framed = false;
  private townReach = 82;

  private buildGround(seed: number): void {
    for (const o of this.ground) this.world.remove(o);
    const l = this.layout!;
    const t = this.manifest.terrain;
    const grassTex = this.factory.texture(t.grass[seed % t.grass.length] ?? t.grass[0], true);
    grassTex.repeat.set(70, 70);
    const grass = new THREE.Mesh(new THREE.PlaneGeometry(2400, 2400), new THREE.MeshStandardMaterial({ map: grassTex, roughness: 1 }));
    grass.rotation.x = -Math.PI / 2;
    grass.receiveShadow = true;
    const town = this.patch(t.dirt, this.townReach + 14, 10);
    const square = this.patch(t.paving, 30, 4);
    square.position.y = 0.08;
    this.ground = [grass, town, square];
    this.world.add(...this.ground);
    const shadowR = l.fieldRadius + 40;
    const cam = this.sun.shadow.camera;
    cam.left = cam.bottom = -shadowR;
    cam.right = cam.top = shadowR;
    cam.near = 50;
    cam.far = 900;
    cam.updateProjectionMatrix();
  }

  /** A soft-edged disc of ground texture. */
  private patch(texture: string, radius: number, tile = 8): THREE.Mesh {
    const tex = this.factory.texture(texture, true).clone();
    tex.needsUpdate = true;
    tex.repeat.set((radius * 2) / tile / 3, (radius * 2) / tile / 3);
    const mat = new THREE.MeshStandardMaterial({ map: tex, alphaMap: radialAlpha(), transparent: true, depthWrite: false, roughness: 1, polygonOffset: true, polygonOffsetFactor: -2 });
    const m = new THREE.Mesh(new THREE.CircleGeometry(radius, 48), mat);
    m.rotation.x = -Math.PI / 2;
    m.position.y = 0.04;
    m.receiveShadow = true;
    m.renderOrder = 1;
    return m;
  }

  private async buildDecor(seed: number, fieldKinds: string[]): Promise<void> {
    const l = this.layout!;
    const g = new THREE.Group();
    const rnd = rng(seed * 7919 + 17);
    const woodAngles = l.fields.filter((_, i) => fieldKinds[i] === 'wood').map((f) => f.angle);
    const trees = this.manifest.gaia['decor'] ?? [];
    const jobs: Promise<void>[] = [];
    for (let i = 0; i < 170; i++) {
      const a = rnd() * Math.PI * 2;
      const nearWood = woodAngles.some((w) => Math.abs(angleDiff(a, w)) < 0.45);
      const inner = l.fieldRadius + (nearWood ? 20 : 42);
      const d = inner + Math.pow(rnd(), 0.7) * 230;
      if (!nearWood && rnd() < 0.35) continue;
      jobs.push(
        this.factory.create(pick(trees, i), { seed: i }).then((t) => {
          t.position.set(Math.cos(a) * d, 0, Math.sin(a) * d);
          t.rotation.y = rnd() * 6.28;
          t.scale.setScalar(0.8 + rnd() * 0.5);
          g.add(t);
        }),
      );
    }
    await Promise.all(jobs);
    if (this.disposed) return;
    this.world.remove(this.decor);
    this.decor = g;
    g.visible = this.prefs?.decor ?? true;
    this.world.add(g);
  }

  private frameCamera(): void {
    const d = Math.max(170, this.townReach * 2.5);
    this.controls.maxDistance = Math.max(520, d * 1.4); // big cities may be seen whole
    this.controls.target.set(0, 0, 12);
    this.camera.position.set(0, d * 0.62, 12 + d * 0.86);
    this.controls.update();
  }

  // ------------------------------------------------------------------ input and loop
  private readonly onDown = (e: PointerEvent) => {
    this.down = { x: e.clientX, y: e.clientY };
  };

  private readonly onUp = (e: PointerEvent) => {
    const d = this.down;
    this.down = null;
    if (!d || e.button !== 0 || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6) return;
    const hit = this.pick(e);
    this.events.select(hit);
  };

  private readonly onMove = (e: PointerEvent) => {
    if (e.buttons) return;
    const hit = this.pick(e);
    if (hit !== this.hovered) {
      this.hovered = hit;
      this.placeRing(this.hoverRing, hit === this.selected ? null : hit);
      this.renderer.domElement.style.cursor = hit === null ? '' : 'pointer';
      this.events.hover(hit);
    }
  };

  private readonly onKey = (e: KeyboardEvent) => {
    if ((e.target as HTMLElement)?.closest?.('input,textarea')) return;
    const step = 0.06;
    if (e.key === 'q' || e.key === 'Q') this.orbit(step);
    if (e.key === 'e' || e.key === 'E') this.orbit(-step);
    if (e.key === 'Escape') this.events.select(null);
  };

  private orbit(a: number): void {
    const t = this.controls.target;
    const off = this.camera.position.clone().sub(t).applyAxisAngle(new THREE.Vector3(0, 1, 0), a);
    this.camera.position.copy(t).add(off);
  }

  private pick(e: PointerEvent): number | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.ray.setFromCamera(ndc, this.camera);
    const hits = this.ray.intersectObjects([...this.sites.values()].map((s) => s.hit), false);
    return hits.length ? (hits[0].object.userData['site'] as number) : null;
  }

  private placeRing(r: THREE.Mesh, index: number | null): void {
    const p = index === null ? null : this.placementOf(index);
    r.visible = !!p;
    if (!p) return;
    r.position.set(p.x, 0.3, p.z);
    r.scale.setScalar(p.r);
  }

  private resize(): void {
    const w = this.host.clientWidth || 1;
    const h = this.host.clientHeight || 1;
    const size = this.renderer.getSize(new THREE.Vector2());
    if (size.x === w && size.y === h) return;
    this.renderer.setSize(w, h, false);
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private loop = () => {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.loop);
    if (this.paused) return;
    const dt = Math.min(0.1, this.clock.getDelta());
    this.controls.update();
    const t = this.controls.target;
    const lim = (this.layout?.fieldRadius ?? 200) + 60;
    const len = Math.hypot(t.x, t.z);
    if (len > lim) {
      const k = lim / len;
      const dx = t.x * (1 - k), dz = t.z * (1 - k);
      t.x -= dx;
      t.z -= dz;
      this.camera.position.x -= dx;
      this.camera.position.z -= dz;
    }
    // the haze starts beyond what the camera looks at, however far out it is zoomed
    const fog = this.scene.fog as THREE.Fog;
    const dist = this.camera.position.distanceTo(t);
    fog.near = Math.max(520, dist + 260);
    fog.far = Math.max(1250, dist * 2 + 900);
    this.sun.target.position.set(t.x, 0, t.z);
    this.sun.position.set(t.x - 210, 300, t.z + 170);
    this.factory.update(dt);
    const pulse = 0.65 + 0.35 * Math.sin(performance.now() / 260);
    (this.selectRing.material as THREE.MeshBasicMaterial).opacity = 0.55 + 0.4 * pulse;
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  };
}

// ------------------------------------------------------------------ helpers

/** Center sites on rings around the civic centre; fields on an outer ring, grouped by kind. */
export function computeLayout(centers: number, fieldKinds: string[]) {
  const center: Placement[] = [{ x: 0, z: 0, r: 26, angle: 0, ring: 0 }];
  let r = 56;
  let left = centers - 1;
  while (left > 0) {
    const cap = Math.max(4, Math.floor((2 * Math.PI * r) / 46));
    const n = Math.min(cap, left);
    const off = r % 2 ? 0.3 : 0.05;
    for (let i = 0; i < n; i++) {
      const a = off + (i / n) * Math.PI * 2 + Math.PI / 2;
      center.push({ x: Math.cos(a) * r, z: Math.sin(a) * r, r: 18, angle: a, ring: r });
    }
    left -= n;
    r += 40;
  }
  const townRadius = r - 40 + 26;
  const count = fieldKinds.length;
  const fieldRadius = Math.max(townRadius + 46, (count * 52) / (2 * Math.PI));
  // rotate so the food fields face the camera (+z)
  const food = fieldKinds.map((k, i) => (k === 'food' ? i : -1)).filter((i) => i >= 0);
  const mid = food.length ? (food[0] + food[food.length - 1]) / 2 : 0;
  const base = Math.PI / 2 - (mid / Math.max(1, count)) * Math.PI * 2;
  const fields: Placement[] = fieldKinds.map((_, i) => {
    const a = base + (i / Math.max(1, count)) * Math.PI * 2;
    return { ring: 0, x: Math.cos(a) * fieldRadius, z: Math.sin(a) * fieldRadius, r: Math.min(21, (Math.PI * fieldRadius) / Math.max(1, count) * 0.8), angle: a };
  });
  return { center, fields, townRadius, fieldRadius };
}

/** Scale an object down (never up beyond 1.15) so its footprint fits `size`. */
function fit(o: THREE.Object3D, size: number): void {
  o.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(o);
  if (box.isEmpty()) return;
  const w = Math.max(box.max.x - box.min.x, box.max.z - box.min.z);
  if (w > 0) o.scale.multiplyScalar(Math.min(1.15, size / w));
}

function ring(color: number, opacity: number): THREE.Mesh {
  const m = new THREE.Mesh(
    new THREE.RingGeometry(0.92, 1, 64),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide }),
  );
  m.rotation.x = -Math.PI / 2;
  m.visible = false;
  m.renderOrder = 5;
  return m;
}

let markerTex: THREE.Texture | null = null;
/** An empty building site: trodden earth inside a pegged, roped-off square. */
function siteMarker(r: number): THREE.Object3D {
  if (!markerTex) {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d')!;
    g.fillStyle = 'rgba(70, 52, 30, 0.28)';
    g.fillRect(14, 14, 100, 100);
    g.strokeStyle = 'rgba(245, 228, 190, 0.75)';
    g.lineWidth = 3;
    g.setLineDash([10, 7]);
    g.strokeRect(14, 14, 100, 100);
    g.setLineDash([]);
    g.fillStyle = 'rgba(70, 45, 20, 0.95)';
    for (const [x, y] of [[14, 14], [114, 14], [14, 114], [114, 114]]) g.fillRect(x - 5, y - 5, 10, 10);
    markerTex = new THREE.CanvasTexture(c);
    markerTex.colorSpace = THREE.SRGBColorSpace;
  }
  const m = new THREE.Mesh(
    new THREE.PlaneGeometry(r * 1.6, r * 1.6),
    new THREE.MeshStandardMaterial({ map: markerTex, transparent: true, depthWrite: false, roughness: 1, polygonOffset: true, polygonOffsetFactor: -6 }),
  );
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.05;
  m.receiveShadow = true;
  m.renderOrder = 2;
  return m;
}

let squareTex: THREE.Texture | null = null;
/** Darkens a ground square (from `square()`) to the given colour. */
function tint(holder: THREE.Object3D, color: number): void {
  holder.traverse((o) => {
    const m = (o as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined;
    if (m?.color) m.color.setHex(color);
  });
}

function squareAlpha(): THREE.Texture {
  if (squareTex) return squareTex;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d')!;
  g.fillStyle = '#000';
  g.fillRect(0, 0, 64, 64);
  g.filter = 'blur(3px)';
  g.fillStyle = '#fff';
  g.fillRect(5, 5, 54, 54);
  squareTex = new THREE.CanvasTexture(c);
  return squareTex;
}

let alphaTex: THREE.Texture | null = null;
function radialAlpha(): THREE.Texture {
  if (alphaTex) return alphaTex;
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d')!;
  const grad = g.createRadialGradient(64, 64, 20, 64, 64, 64);
  grad.addColorStop(0, '#fff');
  grad.addColorStop(0.7, '#ddd');
  grad.addColorStop(1, '#000');
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  alphaTex = new THREE.CanvasTexture(c);
  return alphaTex;
}

function rng(seed: number): () => number {
  let a = seed >>> 0 || 1;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(list: T[] | undefined, i: number): T | null {
  return list && list.length ? list[Math.abs(i) % list.length] : null;
}

function angleDiff(a: number, b: number): number {
  return Math.atan2(Math.sin(a - b), Math.cos(a - b));
}

export { ART_BASE, GOLD };
