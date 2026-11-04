//! Procedural map. Terrain is a pure function of (seed, x, y), so the server
//! only stores what players change (villages) and the client can render any
//! area without asking for terrain.

use crate::pack::{GeneratorKind, World};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Terrain {
    Plain,
    Forest,
    Hills,
    Mountain,
    Water,
    Beach,
}

impl Terrain {
    pub fn settleable(self) -> bool {
        matches!(self, Terrain::Plain | Terrain::Hills | Terrain::Beach)
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq)]
pub struct Tile {
    pub x: i32,
    pub y: i32,
    pub terrain: Terrain,
    pub settleable: bool,
}

/// Integer hash of (seed, x, y) mapped to [0, 1).
pub fn hash01(seed: u32, x: i32, y: i32) -> f64 {
    let mut h = seed ^ 0x9e37_79b9;
    h = (h ^ (x as u32).wrapping_mul(374_761_393)).wrapping_mul(0x85eb_ca6b);
    h = (h ^ (y as u32).wrapping_mul(668_265_263)).wrapping_mul(0xc2b2_ae35);
    h ^= h >> 15;
    h = h.wrapping_mul(0x27d4_eb2d);
    h ^= h >> 13;
    h as f64 / 4_294_967_296.0
}

/// Smooth value noise in [0, 1).
pub fn value_noise(seed: u32, x: i32, y: i32, cell: i32) -> f64 {
    let gx = x.div_euclid(cell);
    let gy = y.div_euclid(cell);
    let fx = x.rem_euclid(cell) as f64 / cell as f64;
    let fy = y.rem_euclid(cell) as f64 / cell as f64;
    let sx = fx * fx * (3.0 - 2.0 * fx);
    let sy = fy * fy * (3.0 - 2.0 * fy);
    let a = hash01(seed, gx, gy);
    let b = hash01(seed, gx + 1, gy);
    let c = hash01(seed, gx, gy + 1);
    let d = hash01(seed, gx + 1, gy + 1);
    a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy
}

fn grid(seed: u32, x: i32, y: i32) -> Terrain {
    let n = value_noise(seed, x, y, 6);
    let r = hash01(seed.wrapping_add(7), x, y);
    if n > 0.82 && r < 0.5 {
        Terrain::Mountain
    } else if n > 0.7 {
        if r < 0.4 { Terrain::Hills } else { Terrain::Plain }
    } else if n < 0.18 && r < 0.6 {
        Terrain::Forest
    } else {
        Terrain::Plain
    }
}

fn islands(seed: u32, x: i32, y: i32) -> Terrain {
    let n = 0.65 * value_noise(seed, x, y, 7) + 0.35 * value_noise(seed.wrapping_add(3), x, y, 3);
    if n < 0.52 {
        Terrain::Water
    } else if n < 0.56 {
        Terrain::Beach
    } else if n > 0.8 {
        Terrain::Mountain
    } else if hash01(seed.wrapping_add(11), x, y) < 0.25 {
        Terrain::Forest
    } else {
        Terrain::Plain
    }
}

pub fn tile_at(world: &World, x: i32, y: i32) -> Tile {
    let inside = x >= 0 && y >= 0 && x < world.width && y < world.height;
    let terrain = if !inside {
        Terrain::Water
    } else {
        match world.generator {
            GeneratorKind::Grid => grid(world.seed, x, y),
            GeneratorKind::Islands => islands(world.seed, x, y),
        }
    };
    Tile { x, y, terrain, settleable: inside && terrain.settleable() }
}

/// All tiles of a rectangle, row by row. Size is capped to keep responses small.
pub fn tiles(world: &World, x0: i32, y0: i32, w: i32, h: i32) -> Vec<Tile> {
    let (w, h) = (w.clamp(0, 64), h.clamp(0, 64));
    (y0..y0 + h).flat_map(|y| (x0..x0 + w).map(move |x| tile_at(world, x, y))).collect()
}

/// Settleable spawn candidates spiralling out from the centre with jitter.
/// Deterministic for a given `rng_seed`; the caller filters occupied tiles.
pub fn spawn_candidates(world: &World, rng_seed: u64, count: usize) -> Vec<(i32, i32)> {
    let mut state = rng_seed | 1;
    let mut next = move || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state >> 11) as f64 / (1u64 << 53) as f64
    };
    let (cx, cy) = (world.width as f64 / 2.0, world.height as f64 / 2.0);
    let max_r = world.width.max(world.height) as f64;
    let mut out = Vec::with_capacity(count);
    let mut r = 2.0;
    while r < max_r && out.len() < count {
        for _ in 0..12 {
            let angle = next() * std::f64::consts::TAU;
            let rr = r + next() * 3.0;
            let x = (cx + angle.cos() * rr).round() as i32;
            let y = (cy + angle.sin() * rr).round() as i32;
            if tile_at(world, x, y).settleable && !out.contains(&(x, y)) {
                out.push((x, y));
            }
        }
        r += 1.0;
    }
    out.truncate(count);
    out
}
