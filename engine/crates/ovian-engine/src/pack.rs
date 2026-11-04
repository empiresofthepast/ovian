//! Content packs: pure data describing resources, buildings, units, tribes and
//! world rules. Swapping packs turns a Travian-like game into an Ikariam-like
//! one without code changes. Unknown keys are ignored, so packs can carry
//! extra data (e.g. `extensions`) for server-side Python mods.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};

pub type ResourceMap = BTreeMap<String, f64>;
pub type Units = BTreeMap<String, u64>;

/// A value depending on a 1-based building level.
/// Either an explicit table `[v1, v2, ...]` or `base * factor^(level-1)`,
/// optionally rounded to a multiple of `round`.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(untagged)]
pub enum Curve {
    Table(Vec<f64>),
    Formula {
        base: f64,
        factor: f64,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        round: Option<f64>,
    },
}

impl Curve {
    /// Value at `level`; level 0 (not built) is always 0.
    pub fn at(&self, level: u32) -> f64 {
        if level == 0 {
            return 0.0;
        }
        match self {
            Curve::Table(t) => t[(level as usize).min(t.len()) - 1],
            Curve::Formula { base, factor, round } => {
                let v = base * factor.powi(level as i32 - 1);
                match round {
                    Some(r) if *r > 0.0 => (v / r).round() * r,
                    _ => v,
                }
            }
        }
    }

    /// Multiplier semantics: 1.0 when the building is absent.
    pub fn multiplier(curve: Option<&Curve>, level: u32) -> f64 {
        match curve {
            Some(c) if level > 0 => c.at(level),
            _ => 1.0,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Resource {
    pub id: String,
    pub name: String,
    /// Units consume this resource as upkeep. At most one per pack.
    #[serde(default)]
    pub upkeep: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Production {
    pub resource: String,
    pub curve: Curve,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Storage {
    pub resources: Vec<String>,
    pub curve: Curve,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Effects {
    /// Adds hourly production of a resource.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub production: Option<Production>,
    /// Storage capacity for the listed resources (largest building wins).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub storage: Option<Storage>,
    /// Multiplier on construction times in the village.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub build_speed: Option<Curve>,
    /// Multiplier on training times of units trained in this building.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub train_speed: Option<Curve>,
    /// Fractional defense bonus (0.2 = +20%).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub defense: Option<Curve>,
    /// Amount of each resource hidden from raiders.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hide: Option<Curve>,
    /// Culture points: they radiate to nearby cities (see `CultureRules`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub culture: Option<Curve>,
    /// Contentment points for this city only (parks, baths, games); they do not spread.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub contentment: Option<Curve>,
    /// Share of this city's culture that goes to its overlord's city (a cultural exchange); all of them add up, at most 90%.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub culture_share: Option<Curve>,
    /// Troops of the overlord that may set out from this city (a garrison).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub garrison: Option<Curve>,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum SlotKind {
    /// Lives on a fixed resource slot.
    Field,
    /// Lives on any free slot in the village center.
    Center,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CostSpec {
    pub base: ResourceMap,
    pub factor: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TimeSpec {
    /// Seconds for level 1 at world speed 1.
    pub base: f64,
    pub factor: f64,
}

fn one() -> f64 {
    1.0
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Building {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub description: String,
    pub slot: SlotKind,
    pub max_level: u32,
    pub cost: CostSpec,
    pub time: TimeSpec,
    /// Population added per level; population pays upkeep.
    #[serde(default = "one")]
    pub population: f64,
    #[serde(default)]
    pub requires: BTreeMap<String, u32>,
    #[serde(default)]
    pub effects: Effects,
    /// At most one per village (the default). Non-unique center buildings can stand on
    /// several sites: their storage adds up and their training runs in parallel.
    #[serde(default = "yes")]
    pub unique: bool,
    /// Stands only in the foreign quarter that an overlord opens in a vassal city (an embassy, an exchange).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub foreign: bool,
}

fn yes() -> bool {
    true
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum UnitClass {
    Infantry,
    Cavalry,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Defense {
    pub infantry: f64,
    pub cavalry: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Unit {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub description: String,
    pub tribe: String,
    /// Building that trains it.
    pub building: String,
    #[serde(default)]
    pub requires: BTreeMap<String, u32>,
    pub cost: ResourceMap,
    #[serde(default = "one")]
    pub upkeep: f64,
    /// Seconds per unit at world speed 1.
    pub time: f64,
    pub attack: f64,
    pub defense: Defense,
    pub class: UnitClass,
    /// Tiles per hour at world speed 1.
    pub speed: f64,
    pub carry: f64,
    /// Technologies the village must have researched to train it.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub techs: Vec<String>,
}

/// A technology, researched once per village in a building.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Tech {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub description: String,
    /// Where it is researched, and the level that building needs.
    pub building: String,
    #[serde(default = "one_u32")]
    pub level: u32,
    /// Other buildings and levels needed.
    #[serde(default)]
    pub requires: BTreeMap<String, u32>,
    /// Technologies that must come first.
    #[serde(default)]
    pub after: Vec<String>,
    pub cost: ResourceMap,
    /// Seconds at world speed 1.
    pub time: f64,
    /// Extra parallel construction jobs this tech allows.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub build_queue: usize,
    /// Extra levels for production sites (field buildings) in the village that researched it.
    #[serde(default, skip_serializing_if = "is_zero_u32")]
    pub field_levels: u32,
}

fn is_zero_u32(n: &u32) -> bool {
    *n == 0
}

fn is_zero(n: &usize) -> bool {
    *n == 0
}

fn one_u32() -> u32 {
    1
}

/// How culture spreads and what it is worth in battle.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CultureRules {
    /// Distance in tiles at which a city's influence fades to nothing.
    #[serde(default = "culture_radius")]
    pub radius: f64,
    /// Largest battle bonus from cultural dominance (0.25 = +25%).
    #[serde(default = "prestige_max")]
    pub prestige_max: f64,
    /// Bonus per natural-log step of the influence ratio.
    #[serde(default = "prestige_scale")]
    pub prestige_scale: f64,
}

fn culture_radius() -> f64 {
    12.0
}
fn prestige_max() -> f64 {
    0.25
}
fn prestige_scale() -> f64 {
    0.12
}

impl Default for CultureRules {
    fn default() -> Self {
        Self { radius: culture_radius(), prestige_max: prestige_max(), prestige_scale: prestige_scale() }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Tribe {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub description: String,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum GeneratorKind {
    #[default]
    Grid,
    Islands,
}

fn speed_default() -> f64 {
    1.0
}
fn seed_default() -> u32 {
    1
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct World {
    #[serde(default = "speed_default")]
    pub speed: f64,
    pub width: i32,
    pub height: i32,
    #[serde(default = "seed_default")]
    pub seed: u32,
    #[serde(default)]
    pub generator: GeneratorKind,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StartBuilding {
    pub building: String,
    pub level: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StartRules {
    pub resources: ResourceMap,
    /// Center buildings present at founding, placed in the first center slots.
    #[serde(default)]
    pub buildings: Vec<StartBuilding>,
}

fn queue_default() -> usize {
    2
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VillageRules {
    #[serde(default)]
    pub base_production: ResourceMap,
    pub base_storage: f64,
    /// One entry per resource slot; each slot only holds the given field building.
    pub field_slots: Vec<String>,
    pub center_slots: usize,
    #[serde(default = "queue_default")]
    pub build_queue: usize,
    pub start: StartRules,
    /// Optional: center sites open up as one building grows, in phases.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub growth: Option<Growth>,
}

/// Settlement phases, like the village/town/city ages of real-time strategy games.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Growth {
    /// The center building whose level sets the phase, e.g. the town hall.
    pub building: String,
    /// In ascending order of level. The first phase applies from the start.
    pub phases: Vec<Phase>,
    /// More sites as the building keeps growing, on top of the phase's.
    #[serde(default)]
    pub extra_sites: Option<ExtraSites>,
    /// More production fields as the building keeps growing.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extra_fields: Option<ExtraFields>,
}

/// Every `every` levels of the growth building open one more field of each kind in
/// `fields`. These sites come after the center sites, in rounds of `fields`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExtraFields {
    pub every: u32,
    pub fields: Vec<String>,
}

/// `sites` more center sites at level `from` and again every `every` levels after it,
/// up to `village.center_slots`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExtraSites {
    pub from: u32,
    pub every: u32,
    pub sites: usize,
}

impl ExtraSites {
    pub fn at(&self, level: u32) -> usize {
        if level < self.from || self.every == 0 {
            0
        } else {
            ((level - self.from) / self.every + 1) as usize * self.sites
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Phase {
    pub id: String,
    pub name: String,
    /// Level of `growth.building` that reaches this phase.
    pub level: u32,
    /// Center sites open in this phase (the rest stay locked).
    pub center_slots: usize,
    /// Parallel construction jobs in this phase (default: `village.build_queue`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub build_queue: Option<usize>,
}

fn base_defense_default() -> f64 {
    10.0
}
fn loss_exponent_default() -> f64 {
    1.5
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CombatRules {
    #[serde(default = "base_defense_default")]
    pub base_defense: f64,
    #[serde(default = "loss_exponent_default")]
    pub loss_exponent: f64,
}

impl Default for CombatRules {
    fn default() -> Self {
        Self { base_defense: base_defense_default(), loss_exponent: loss_exponent_default() }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Pack {
    pub id: String,
    pub name: String,
    pub version: String,
    #[serde(default)]
    pub description: String,
    pub world: World,
    pub resources: Vec<Resource>,
    pub village: VillageRules,
    pub buildings: Vec<Building>,
    #[serde(default)]
    pub units: Vec<Unit>,
    pub tribes: Vec<Tribe>,
    #[serde(default)]
    pub combat: CombatRules,
    #[serde(default)]
    pub techs: Vec<Tech>,
    #[serde(default)]
    pub culture: CultureRules,
}

/// A validated pack plus lookup indexes. Build once at startup.
#[derive(Clone, Debug)]
pub struct Content {
    pub pack: Pack,
    pub upkeep_resource: Option<String>,
    buildings: HashMap<String, usize>,
    units: HashMap<String, usize>,
    tribes: HashMap<String, usize>,
    techs: HashMap<String, usize>,
}

fn valid_id(id: &str) -> bool {
    let mut chars = id.chars();
    matches!(chars.next(), Some('a'..='z'))
        && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

impl Content {
    /// Validate cross references and build indexes. Returns every problem found.
    pub fn load(pack: Pack) -> Result<Self, Vec<String>> {
        let mut problems = Vec::new();
        let mut index = |kind: &str, ids: Vec<&String>| -> HashMap<String, usize> {
            let mut m = HashMap::new();
            for (i, id) in ids.into_iter().enumerate() {
                if !valid_id(id) {
                    problems.push(format!("{kind} id \"{id}\" must be lower_snake_case"));
                }
                if m.insert(id.clone(), i).is_some() {
                    problems.push(format!("duplicate {kind} id \"{id}\""));
                }
            }
            m
        };
        let resources = index("resource", pack.resources.iter().map(|r| &r.id).collect());
        let buildings = index("building", pack.buildings.iter().map(|b| &b.id).collect());
        let units = index("unit", pack.units.iter().map(|u| &u.id).collect());
        let tribes = index("tribe", pack.tribes.iter().map(|t| &t.id).collect());
        let techs = index("tech", pack.techs.iter().map(|t| &t.id).collect());

        let upkeep: Vec<&Resource> = pack.resources.iter().filter(|r| r.upkeep).collect();
        if upkeep.len() > 1 {
            problems.push("at most one resource may have upkeep: true".into());
        }
        if pack.world.width <= 0 || pack.world.height <= 0 || pack.world.speed <= 0.0 {
            problems.push("world width, height and speed must be positive".into());
        }
        if pack.tribes.is_empty() {
            problems.push("a pack needs at least one tribe".into());
        }

        let check_res = |problems: &mut Vec<String>, at: &str, m: &ResourceMap| {
            for k in m.keys() {
                if !resources.contains_key(k) {
                    problems.push(format!("{at}: unknown resource \"{k}\""));
                }
            }
        };
        let check_req = |problems: &mut Vec<String>, at: &str, m: &BTreeMap<String, u32>| {
            for k in m.keys() {
                if !buildings.contains_key(k) {
                    problems.push(format!("{at}: requires unknown building \"{k}\""));
                }
            }
        };
        let kind_of = |id: &str| buildings.get(id).map(|&i| pack.buildings[i].slot);

        check_res(&mut problems, "village.base_production", &pack.village.base_production);
        check_res(&mut problems, "village.start.resources", &pack.village.start.resources);
        for id in &pack.village.field_slots {
            match kind_of(id) {
                None => problems.push(format!("village.field_slots: unknown building \"{id}\"")),
                Some(SlotKind::Center) => problems.push(format!("village.field_slots: \"{id}\" is a center building")),
                _ => {}
            }
        }
        if pack.village.start.buildings.len() > pack.village.center_slots {
            problems.push("village.start.buildings exceeds center_slots".into());
        }
        if let Some(g) = &pack.village.growth {
            match kind_of(&g.building) {
                None => problems.push(format!("village.growth: unknown building \"{}\"", g.building)),
                Some(SlotKind::Field) => problems.push(format!("village.growth: \"{}\" is a field building", g.building)),
                _ => {}
            }
            if pack.buildings.iter().any(|b| b.id == g.building && !b.unique) {
                problems.push(format!("village.growth: \"{}\" must be unique", g.building));
            }
            if let Some(x) = &g.extra_fields {
                if x.every == 0 {
                    problems.push("village.growth.extra_fields.every must be at least 1".into());
                }
                for id in &x.fields {
                    match kind_of(id) {
                        None => problems.push(format!("village.growth.extra_fields: unknown building \"{id}\"")),
                        Some(SlotKind::Center) => problems.push(format!("village.growth.extra_fields: \"{id}\" is a center building")),
                        _ => {}
                    }
                }
            }
            if g.phases.is_empty() {
                problems.push("village.growth needs at least one phase".into());
            }
            for w in g.phases.windows(2) {
                if w[1].level <= w[0].level || w[1].center_slots < w[0].center_slots {
                    problems.push(format!("village.growth: phase \"{}\" must come after \"{}\" in level and sites", w[1].id, w[0].id));
                }
            }
            for ph in &g.phases {
                if ph.center_slots > pack.village.center_slots {
                    problems.push(format!("village.growth: phase \"{}\" opens more sites than center_slots", ph.id));
                }
            }
            if g.phases.first().is_some_and(|p| p.center_slots < pack.village.start.buildings.len()) {
                problems.push("village.growth: the first phase must hold the start buildings".into());
            }
        }
        for s in &pack.village.start.buildings {
            match kind_of(&s.building) {
                None => problems.push(format!("village.start.buildings: unknown building \"{}\"", s.building)),
                Some(SlotKind::Field) => problems.push(format!("village.start.buildings: \"{}\" is a field building", s.building)),
                _ => {}
            }
        }
        for b in &pack.buildings {
            check_res(&mut problems, &format!("building {} cost", b.id), &b.cost.base);
            check_req(&mut problems, &format!("building {}", b.id), &b.requires);
            if let Some(p) = &b.effects.production {
                if !resources.contains_key(&p.resource) {
                    problems.push(format!("building {}: produces unknown resource \"{}\"", b.id, p.resource));
                }
            }
            if let Some(s) = &b.effects.storage {
                for r in &s.resources {
                    if !resources.contains_key(r) {
                        problems.push(format!("building {}: stores unknown resource \"{r}\"", b.id));
                    }
                }
            }
            if b.max_level == 0 {
                problems.push(format!("building {}: max_level must be positive", b.id));
            }
        }
        for u in &pack.units {
            check_res(&mut problems, &format!("unit {} cost", u.id), &u.cost);
            check_req(&mut problems, &format!("unit {}", u.id), &u.requires);
            if !tribes.contains_key(&u.tribe) {
                problems.push(format!("unit {}: unknown tribe \"{}\"", u.id, u.tribe));
            }
            if !buildings.contains_key(&u.building) {
                problems.push(format!("unit {}: unknown training building \"{}\"", u.id, u.building));
            }
            if u.speed <= 0.0 {
                problems.push(format!("unit {}: speed must be positive", u.id));
            }
            for t in &u.techs {
                if !techs.contains_key(t) {
                    problems.push(format!("unit {}: unknown tech \"{t}\"", u.id));
                }
            }
        }
        for (i, t) in pack.techs.iter().enumerate() {
            check_res(&mut problems, &format!("tech {} cost", t.id), &t.cost);
            check_req(&mut problems, &format!("tech {}", t.id), &t.requires);
            if !buildings.contains_key(&t.building) {
                problems.push(format!("tech {}: unknown research building \"{}\"", t.id, t.building));
            }
            for a in &t.after {
                // listing prerequisites first rules out cycles
                match techs.get(a) {
                    None => problems.push(format!("tech {}: unknown prerequisite \"{a}\"", t.id)),
                    Some(&j) if j >= i => problems.push(format!("tech {}: prerequisite \"{a}\" must be listed before it", t.id)),
                    _ => {}
                }
            }
        }
        if pack.culture.radius <= 0.0 {
            problems.push("culture.radius must be positive".into());
        }
        if !problems.is_empty() {
            return Err(problems);
        }
        let upkeep_resource = upkeep.first().map(|r| r.id.clone());
        Ok(Self { pack, upkeep_resource, buildings, units, tribes, techs })
    }

    pub fn building(&self, id: &str) -> Option<&Building> {
        self.buildings.get(id).map(|&i| &self.pack.buildings[i])
    }
    pub fn unit(&self, id: &str) -> Option<&Unit> {
        self.units.get(id).map(|&i| &self.pack.units[i])
    }
    pub fn tech(&self, id: &str) -> Option<&Tech> {
        self.techs.get(id).map(|&i| &self.pack.techs[i])
    }
    pub fn tribe(&self, id: &str) -> Option<&Tribe> {
        self.tribes.get(id).map(|&i| &self.pack.tribes[i])
    }
    pub fn resource_ids(&self) -> impl Iterator<Item = &str> {
        self.pack.resources.iter().map(|r| r.id.as_str())
    }
}
