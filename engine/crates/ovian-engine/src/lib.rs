//! # ovian-engine
//!
//! The pure rules of Ovian. Everything here is deterministic and free of I/O:
//! the server (Python, via PyO3) persists state and schedules events, and the
//! web client (via WebAssembly) uses the same code for previews and countdowns.
//!
//! All times are epoch milliseconds or whole seconds; all state is plain
//! serde data so bindings can pass it as dicts / JS objects.

pub mod combat;
pub mod map;
pub mod movement;
pub mod pack;
pub mod resources;
pub mod village;

pub use combat::{compute_loot, AttackKind, BattleInput, BattleResult};
pub use map::{spawn_candidates, tile_at, tiles, Terrain, Tile};
pub use movement::{distance, Point};
pub use pack::{Content, CultureRules, Curve, Pack, Phase, ResourceMap, Tech, Units};
pub use village::{BuildPlan, Economy, PlanError, QueuedBuild, ResearchPlan, Slot, TrainPlan, Village};
