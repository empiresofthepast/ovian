import * as THREE from 'three';
import { ColladaLoader } from 'three/examples/jsm/loaders/ColladaLoader.js';
import { clone as cloneSkinned } from 'three/examples/jsm/utils/SkeletonUtils.js';
import { ART_BASE, ActorDef, Look, Manifest } from '../art/art.service';

interface MeshAsset {
  /** Mesh content in the file's own Z-up frame (the loader's axis fix removed). */
  root: THREE.Object3D;
  clips: THREE.AnimationClip[];
}

export interface ActorOptions {
  /** Picks among an actor's alternative looks (trees, rocks); stable per placement. */
  seed?: number;
  /** Player colour for "player_trans" materials. */
  player?: THREE.Color;
  /** Multiplies the colour of every material: ghosts for planned buildings. */
  tint?: THREE.Color;
  opacity?: number;
}

/**
 * Builds three.js objects from 0 A.D. actors: COLLADA meshes, a material per
 * texture and material kind, and props attached at their prop points,
 * recursively. Meshes, textures and materials are cached and shared.
 */
export class ActorFactory {
  private readonly loader = new ColladaLoader();
  private readonly textures = new THREE.TextureLoader();
  private readonly meshes = new Map<string, Promise<MeshAsset | null>>();
  private readonly texCache = new Map<string, THREE.Texture>();
  private readonly matCache = new Map<string, THREE.Material>();
  readonly mixers: THREE.AnimationMixer[] = [];

  constructor(
    private readonly manifest: Manifest,
    private readonly anisotropy = 4,
  ) {}

  has(id: string | null | undefined): boolean {
    return !!id && !!this.manifest.actors[id];
  }

  /** A Y-up object for the actor; empty group when the actor is unknown. */
  async create(id: string | null | undefined, opts: ActorOptions = {}): Promise<THREE.Group> {
    const outer = new THREE.Group();
    if (!id) return outer;
    const inner = await this.build(id, opts, 0);
    inner.rotation.x = -Math.PI / 2; // 0 A.D. meshes are Z-up
    outer.add(inner);
    outer.userData['actor'] = id;
    return outer;
  }

  private async build(id: string, opts: ActorOptions, depth: number): Promise<THREE.Object3D> {
    const group = new THREE.Group();
    const def = this.manifest.actors[id];
    if (!def || depth > 8 || !def.looks.length) return group;
    const look = def.looks[Math.abs(opts.seed ?? 0) % def.looks.length];
    let mesh: THREE.Object3D | null = null;
    if (look.mesh) {
      const asset = await this.mesh(look.mesh);
      if (asset) {
        mesh = cloneSkinned(asset.root);
        const material = this.material(look, def, opts);
        mesh.traverse((o) => {
          const m = o as THREE.Mesh;
          if (m.isMesh) {
            m.material = material;
            m.castShadow = def.shadow && def.mat !== 'blend';
            m.receiveShadow = def.mat !== 'blend';
          }
        });
        if (asset.clips.length) {
          const mixer = new THREE.AnimationMixer(mesh);
          for (const clip of asset.clips) mixer.clipAction(clip).play();
          mixer.update(Math.random() * 2);
          this.mixers.push(mixer);
        }
        group.add(mesh);
      }
    }
    if (look.decal) group.add(this.decal(look, def, opts));
    if (look.props?.length) {
      const points = mesh ? propPoints(mesh) : new Map<string, THREE.Object3D>();
      const children = await Promise.all(
        look.props.map(([, child], i) => this.build(child, { ...opts, seed: (opts.seed ?? 0) * 7 + i + 1 }, depth + 1)),
      );
      look.props.forEach(([point], i) => {
        const at = point === 'root' ? group : (points.get(normalise(point)) ?? group);
        at.add(children[i]);
      });
    }
    return group;
  }

  private mesh(path: string): Promise<MeshAsset | null> {
    let p = this.meshes.get(path);
    if (!p) {
      p = this.loader
        .loadAsync(ART_BASE + 'm/' + path)
        .then((c) => {
          const root = c.scene;
          // a few 0 A.D. files keep the artist's lamp and camera: they must not light the city
          const strays: THREE.Object3D[] = [];
          root.traverse((o) => {
            if ((o as THREE.Light).isLight || (o as THREE.Camera).isCamera) strays.push(o);
          });
          for (const o of strays) o.removeFromParent();
          root.rotation.set(0, 0, 0);
          root.scale.set(1, 1, 1);
          root.updateMatrixWorld(true);
          return { root, clips: (root as any).animations ?? [] };
        })
        .catch((e) => {
          console.warn('mesh failed', path, e);
          return null;
        });
      this.meshes.set(path, p);
    }
    return p;
  }

  texture(path: string, repeat = false): THREE.Texture {
    let t = this.texCache.get(path);
    if (!t) {
      t = this.textures.load(ART_BASE + path);
      t.colorSpace = THREE.SRGBColorSpace;
      t.anisotropy = this.anisotropy;
      if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping;
      this.texCache.set(path, t);
    }
    return t;
  }

  private material(look: Look, def: ActorDef, opts: ActorOptions): THREE.Material {
    const player = opts.player ?? DEFAULT_PLAYER;
    const key = [look.tex, def.mat, player.getHexString(), look.color?.join(','), opts.tint?.getHexString(), opts.opacity].join('|');
    let m = this.matCache.get(key);
    if (m) return m;
    const mat = new THREE.MeshStandardMaterial({ roughness: 0.88, metalness: 0.02 });
    if (look.tex) {
      mat.map = this.texture(`t/${look.tex}.webp`);
      mat.map.wrapS = mat.map.wrapT = THREE.RepeatWrapping;
    }
    switch (def.mat) {
      case 'player':
        withPlayerColour(mat, player);
        break;
      case 'alphatest':
        mat.alphaTest = 0.45;
        mat.side = THREE.DoubleSide;
        break;
      case 'blend':
        mat.transparent = true;
        mat.depthWrite = false;
        break;
      case 'objectcolor':
        if (look.color) mat.color.setRGB(look.color[0], look.color[1], look.color[2], THREE.SRGBColorSpace);
        break;
    }
    if (opts.tint) mat.color.multiply(opts.tint);
    if (opts.opacity !== undefined && opts.opacity < 1) {
      mat.transparent = true;
      mat.opacity = opts.opacity;
      mat.depthWrite = false;
    }
    this.matCache.set(key, mat);
    return mat;
  }

  private decal(look: Look, def: ActorDef, opts: ActorOptions): THREE.Mesh {
    const d = look.decal!;
    const geo = new THREE.PlaneGeometry(d.width ?? 4, d.depth ?? 4);
    const mat = new THREE.MeshStandardMaterial({
      map: look.tex ? this.texture(`t/${look.tex}.webp`) : null,
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -4,
      roughness: 1,
    });
    if (opts.opacity !== undefined) mat.opacity = opts.opacity;
    const plane = new THREE.Mesh(geo, mat);
    // the plane lies in the Z-up frame's XY ground plane
    plane.position.set(d.offsetx ?? 0, -(d.offsetz ?? 0), 0.06);
    plane.rotation.z = -(d.angle ?? 0);
    plane.receiveShadow = true;
    plane.renderOrder = 1;
    void def;
    return plane;
  }

  update(dt: number): void {
    for (const m of this.mixers) m.update(dt);
  }
}

const DEFAULT_PLAYER = new THREE.Color(0x2e2ec8);

/** 0 A.D. player_trans: the texture's alpha marks where the player colour shows. */
function withPlayerColour(mat: THREE.MeshStandardMaterial, colour: THREE.Color): void {
  mat.onBeforeCompile = (shader) => {
    shader.uniforms['playerColour'] = { value: colour };
    shader.fragmentShader = 'uniform vec3 playerColour;\n' + shader.fragmentShader.replace(
      '#include <map_fragment>',
      `#ifdef USE_MAP
        vec4 texel = texture2D( map, vMapUv );
        diffuseColor.rgb *= texel.rgb * mix( playerColour, vec3( 1.0 ), texel.a );
      #endif`,
    );
  };
  mat.customProgramCacheKey = () => 'ovian-player';
}

function normalise(name: string): string {
  return name.toLowerCase().replace(/^prop[-_]/, '');
}

function propPoints(root: THREE.Object3D): Map<string, THREE.Object3D> {
  const out = new Map<string, THREE.Object3D>();
  root.traverse((o) => {
    if (o.name && /^prop[-_]/i.test(o.name)) out.set(normalise(o.name), o);
  });
  return out;
}
