//! Village economy, construction and training rules.

use crate::pack::{Content, Curve, ResourceMap, SlotKind, Units};
use crate::resources::{add, covers, round, scale};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fmt;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Slot {
    pub building: Option<String>,
    pub level: u32,
    /// The civilization whose architecture this building shows (set by the server when it is founded).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub style: Option<String>,
    /// A site in the foreign quarter, opened by an overlord: only `foreign` buildings stand here.
    /// Foreign sites follow every other site.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub foreign: bool,
}

/// Persisted village state. Resources are lazy: `resources` is the amount at
/// `resources_at` (epoch milliseconds); `accrue` brings it to a later time.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Village {
    pub resources: ResourceMap,
    pub resources_at: i64,
    /// Field slots first (fixed building type), then center slots.
    pub slots: Vec<Slot>,
    /// Troops at home that belong to this village.
    #[serde(default)]
    pub units: Units,
    /// Technologies researched here.
    #[serde(default)]
    pub techs: Vec<String>,
    /// Fraction of gross production paid to an overlord (0 when free).
    #[serde(default, skip_serializing_if = "is_zero")]
    pub tribute: f64,
    /// Hourly tribute received from vassals, already at world speed.
    #[serde(default, skip_serializing_if = "ResourceMap::is_empty")]
    pub tribute_in: ResourceMap,
    /// Culture this city receives from its vassals' cultural exchanges (kept by the server).
    #[serde(default, skip_serializing_if = "is_zero")]
    pub culture_in: f64,
    /// Culture from the relics shown in this city (kept by the server).
    #[serde(default, skip_serializing_if = "is_zero")]
    pub culture_relics: f64,
    /// Temporary production bonus as a fraction (blessings, events); 0 when none.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub boost: f64,
    /// Per-resource production modifiers (seasons, governments, ...), added to `boost`;
    /// may be negative. A resource never drops below 10% of its production.
    #[serde(default, skip_serializing_if = "ResourceMap::is_empty")]
    pub boost_by: ResourceMap,
    /// Parallel construction jobs granted to this city by an administrator, replacing the phase's and the
    /// technologies' count when set.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub build_queue: Option<usize>,
}

fn is_zero(x: &f64) -> bool {
    *x == 0.0
}

/// A construction job that has been ordered but not finished.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QueuedBuild {
    pub slot: usize,
    pub building: String,
    pub level: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Economy {
    /// Net hourly production after upkeep, world speed applied.
    pub production: ResourceMap,
    /// Gross hourly production before upkeep.
    pub gross: ResourceMap,
    pub capacity: ResourceMap,
    pub population: f64,
    /// Hourly upkeep, paid in the upkeep resource.
    pub upkeep: f64,
    pub defense_bonus: f64,
    /// Amount of each resource hidden from raids.
    pub hidden: f64,
    /// Construction time multiplier.
    pub build_speed: f64,
    /// Center sites open for building (see `village.growth`).
    #[serde(default)]
    pub center_sites: usize,
    /// Extra production fields open (see `village.growth.extra_fields`); they follow the center sites.
    #[serde(default)]
    pub extra_fields: usize,
    /// Current growth phase id, if the pack has phases.
    #[serde(default)]
    pub phase: Option<String>,
    /// Culture points of this village (temples, universities, ...).
    #[serde(default)]
    pub culture: f64,
    /// Contentment points from this village's buildings (parks, baths, ...).
    #[serde(default)]
    pub contentment: f64,
    /// Culture this village gives its overlord (already taken out of `culture`).
    #[serde(default)]
    pub culture_out: f64,
    /// Overlord troops that may set out from here (garrisons).
    #[serde(default)]
    pub garrison: f64,
    /// Construction jobs that may run at the same time.
    #[serde(default)]
    pub build_queue: usize,
    /// Hourly tribute this village pays to its overlord.
    #[serde(default)]
    pub tribute_out: ResourceMap,
    /// Hourly tribute this village receives from its vassals.
    #[serde(default)]
    pub tribute_in: ResourceMap,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PlanError {
    InvalidSlot,
    UnknownBuilding,
    UnknownUnit,
    WrongBuilding,
    SlotType,
    AlreadyBuilt,
    MaxLevel,
    Requirements,
    QueueFull,
    InsufficientResources,
    WrongTribe,
    InvalidCount,
    NoUnits,
    SiteLocked,
    UnknownTech,
    TechMissing,
    AlreadyResearched,
}

impl PlanError {
    pub fn code(self) -> &'static str {
        match self {
            PlanError::InvalidSlot => "invalid_slot",
            PlanError::UnknownBuilding => "unknown_building",
            PlanError::UnknownUnit => "unknown_unit",
            PlanError::WrongBuilding => "wrong_building",
            PlanError::SlotType => "slot_type",
            PlanError::AlreadyBuilt => "already_built",
            PlanError::MaxLevel => "max_level",
            PlanError::Requirements => "requirements",
            PlanError::QueueFull => "queue_full",
            PlanError::InsufficientResources => "insufficient_resources",
            PlanError::WrongTribe => "wrong_tribe",
            PlanError::InvalidCount => "invalid_count",
            PlanError::NoUnits => "no_units",
            PlanError::SiteLocked => "site_locked",
            PlanError::UnknownTech => "unknown_tech",
            PlanError::TechMissing => "tech_missing",
            PlanError::AlreadyResearched => "already_researched",
        }
    }
}

impl fmt::Display for PlanError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for PlanError {}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct BuildPlan {
    pub slot: usize,
    pub building: String,
    pub level: u32,
    pub cost: ResourceMap,
    pub seconds: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ResearchPlan {
    pub tech: String,
    pub cost: ResourceMap,
    pub seconds: i64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TrainPlan {
    pub unit: String,
    pub count: u64,
    pub cost: ResourceMap,
    pub seconds_each: i64,
}

impl Content {
    pub fn create_village(&self, now: i64) -> Village {
        let rules = &self.pack.village;
        let mut slots: Vec<Slot> = rules
            .field_slots
            .iter()
            .map(|b| Slot { building: Some(b.clone()), ..Slot::default() })
            .collect();
        for i in 0..rules.center_slots {
            slots.push(match rules.start.buildings.get(i) {
                Some(s) => Slot { building: Some(s.building.clone()), level: s.level, ..Slot::default() },
                None => Slot::default(),
            });
        }
        for i in 0..self.extra_field_slots() {
            slots.push(Slot { building: self.field_building(self.extra_field_base() + i).map(String::from), ..Slot::default() });
        }
        let resources = self
            .resource_ids()
            .map(|r| (r.to_string(), rules.start.resources.get(r).copied().unwrap_or(0.0)))
            .collect();
        Village { resources, resources_at: now, slots, units: Units::new(), techs: Vec::new(), tribute: 0.0, tribute_in: ResourceMap::new(), culture_in: 0.0, culture_relics: 0.0, boost: 0.0, boost_by: ResourceMap::new(), build_queue: None }
    }

    /// Highest level of each building present.
    pub fn building_levels(&self, v: &Village) -> BTreeMap<String, u32> {
        let mut out = BTreeMap::new();
        for s in &v.slots {
            if let (Some(b), l) = (&s.building, s.level) {
                if l > 0 {
                    let e = out.entry(b.clone()).or_insert(0);
                    *e = (*e).max(l);
                }
            }
        }
        out
    }

    pub fn meets_requirements(&self, v: &Village, requires: &BTreeMap<String, u32>) -> bool {
        let lv = self.building_levels(v);
        requires.iter().all(|(b, l)| lv.get(b).copied().unwrap_or(0) >= *l)
    }

    pub fn unit_upkeep(&self, units: &Units) -> f64 {
        units.iter().map(|(id, n)| self.unit(id).map_or(0.0, |u| u.upkeep) * *n as f64).sum()
    }

    /// Derived economy. `extra_upkeep` is the upkeep of foreign troops stationed here.
    pub fn economy(&self, v: &Village, extra_upkeep: f64) -> Economy {
        let pack = &self.pack;
        let speed = pack.world.speed;
        let mut gross = ResourceMap::new();
        let mut capacity = ResourceMap::new();
        for r in self.resource_ids() {
            gross.insert(r.into(), pack.village.base_production.get(r).copied().unwrap_or(0.0));
            capacity.insert(r.into(), pack.village.base_storage);
        }
        let (mut population, mut defense_bonus, mut hidden, mut build_speed, mut culture, mut contentment) = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0);
        let (mut culture_share, mut garrison) = (0.0_f64, 0.0);
        // Copies of one building add their storage; different buildings do not stack.
        let mut stored: BTreeMap<(String, String), f64> = BTreeMap::new();
        for s in &v.slots {
            let (Some(id), level) = (&s.building, s.level) else { continue };
            if level == 0 {
                continue;
            }
            let Some(b) = self.building(id) else { continue };
            population += b.population * level as f64;
            let e = &b.effects;
            if let Some(p) = &e.production {
                *gross.entry(p.resource.clone()).or_insert(0.0) += p.curve.at(level);
            }
            if let Some(st) = &e.storage {
                let cap = st.curve.at(level);
                for r in &st.resources {
                    *stored.entry((id.clone(), r.clone())).or_insert(0.0) += cap;
                }
            }
            if let Some(d) = &e.defense {
                defense_bonus += d.at(level);
            }
            if let Some(h) = &e.hide {
                hidden += h.at(level);
            }
            if let Some(c) = &e.culture {
                culture += c.at(level);
            }
            if let Some(c) = &e.contentment {
                contentment += c.at(level);
            }
            if let Some(c) = &e.culture_share {
                culture_share += c.at(level);
            }
            if let Some(c) = &e.garrison {
                garrison += c.at(level);
            }
            build_speed *= Curve::multiplier(e.build_speed.as_ref(), level);
        }
        for ((_, r), cap) in stored {
            let c = capacity.entry(r).or_insert(0.0);
            *c = c.max(cap);
        }
        if v.boost != 0.0 || !v.boost_by.is_empty() {
            for (r, p) in gross.iter_mut() {
                if *p > 0.0 {
                    *p *= (1.0 + v.boost + v.boost_by.get(r).copied().unwrap_or(0.0)).max(0.1);
                }
            }
        }
        let gross = scale(&gross, speed);
        let upkeep = (population + self.unit_upkeep(&v.units) + extra_upkeep) * speed;
        // Vassals pay a share of their gross production; overlords receive it.
        let share = v.tribute.clamp(0.0, 1.0);
        let tribute_out: ResourceMap = gross.iter().filter(|(_, p)| **p > 0.0 && share > 0.0).map(|(r, p)| (r.clone(), p * share)).collect();
        let mut production = gross.clone();
        for (r, p) in &tribute_out {
            *production.entry(r.clone()).or_insert(0.0) -= p;
        }
        for (r, p) in &v.tribute_in {
            *production.entry(r.clone()).or_insert(0.0) += p;
        }
        if let Some(r) = &self.upkeep_resource {
            *production.entry(r.clone()).or_insert(0.0) -= upkeep;
        }
        let (center_sites, phase) = self.growth(v);
        let culture_out = culture * culture_share.clamp(0.0, 0.9);
        Economy { production, gross, capacity, population, upkeep, defense_bonus, hidden, build_speed, center_sites, extra_fields: self.open_extra_fields(v), phase, culture: culture - culture_out + v.culture_in + v.culture_relics, contentment, culture_out, garrison, build_queue: self.build_queue(v), tribute_out, tribute_in: v.tribute_in.clone() }
    }

    /// The current growth phase, if the pack has phases.
    fn growth_level(&self, v: &Village) -> u32 {
        let Some(g) = self.pack.village.growth.as_ref() else { return 0 };
        v.slots.iter().filter(|s| s.building.as_deref() == Some(g.building.as_str())).map(|s| s.level).max().unwrap_or(0)
    }

    fn phase(&self, v: &Village) -> Option<&crate::pack::Phase> {
        let g = self.pack.village.growth.as_ref()?;
        let level = self.growth_level(v);
        g.phases.iter().rev().find(|p| p.level <= level).or(g.phases.first())
    }

    /// Open center sites and the phase id, from the growth building's level.
    pub fn growth(&self, v: &Village) -> (usize, Option<String>) {
        let rules = &self.pack.village;
        match self.phase(v) {
            Some(p) => {
                let extra = rules.growth.as_ref().and_then(|g| g.extra_sites.as_ref()).map_or(0, |e| e.at(self.growth_level(v)));
                ((p.center_slots + extra).min(rules.center_slots), Some(p.id.clone()))
            }
            None => (rules.center_slots, None),
        }
    }

    /// Parallel construction jobs: the phase's (or the pack's) plus any from technologies,
    /// unless an administrator set the city's own.
    pub fn build_queue(&self, v: &Village) -> usize {
        if let Some(n) = v.build_queue {
            return n;
        }
        let base = self.phase(v).and_then(|p| p.build_queue).unwrap_or(self.pack.village.build_queue);
        base + v.techs.iter().filter_map(|t| self.tech(t)).map(|t| t.build_queue).sum::<usize>()
    }

    /// Index of the first extra field: after the fixed fields and the center sites.
    pub fn extra_field_base(&self) -> usize {
        self.pack.village.field_slots.len() + self.pack.village.center_slots
    }

    /// How many extra field sites a village can ever have (at the growth building's top level).
    pub fn extra_field_slots(&self) -> usize {
        let Some(g) = self.pack.village.growth.as_ref() else { return 0 };
        let Some(x) = g.extra_fields.as_ref().filter(|x| x.every > 0) else { return 0 };
        let max = self.building(&g.building).map_or(0, |b| b.max_level);
        (max / x.every) as usize * x.fields.len()
    }

    /// Extra field sites open now.
    pub fn open_extra_fields(&self, v: &Village) -> usize {
        let Some(x) = self.pack.village.growth.as_ref().and_then(|g| g.extra_fields.as_ref()).filter(|x| x.every > 0) else { return 0 };
        ((self.growth_level(v) / x.every) as usize * x.fields.len()).min(self.extra_field_slots())
    }

    /// The fixed building of a field site (a regular or an extra field), `None` for a center site.
    pub fn field_building(&self, slot: usize) -> Option<&str> {
        let rules = &self.pack.village;
        if slot < rules.field_slots.len() {
            return Some(rules.field_slots[slot].as_str());
        }
        let base = self.extra_field_base();
        if slot < base || slot >= base + self.extra_field_slots() {
            return None;
        }
        let x = rules.growth.as_ref()?.extra_fields.as_ref()?;
        x.fields.get((slot - base) % x.fields.len()).map(String::as_str)
    }

    /// Fit an older village to the pack's slot count: add sites a newer pack has,
    /// drop trailing empty sites it no longer has.
    pub fn normalize(&self, v: &Village) -> Village {
        let want = self.extra_field_base() + self.extra_field_slots();
        let mut out = v.clone();
        // the foreign quarter always comes last, whatever the pack does to the other sites
        let foreign: Vec<Slot> = out.slots.iter().filter(|s| s.foreign).cloned().collect();
        out.slots.retain(|s| !s.foreign);
        while out.slots.len() < want {
            let building = self.field_building(out.slots.len()).map(String::from);
            out.slots.push(Slot { building, ..Slot::default() });
        }
        while out.slots.len() > want && out.slots.last().is_some_and(|s| s.building.is_none() || s.level == 0) {
            out.slots.pop();
        }
        out.slots.extend(foreign);
        out
    }

    /// Bring resources up to `now`, capped by storage and floored at zero.
    /// A stock already above capacity (e.g. after loot) is kept but does not grow.
    pub fn accrue(&self, v: &Village, now: i64, extra_upkeep: f64) -> Village {
        let hours = (now - v.resources_at).max(0) as f64 / 3_600_000.0;
        let eco = self.economy(v, extra_upkeep);
        let mut resources = ResourceMap::new();
        for r in self.resource_ids() {
            let current = v.resources.get(r).copied().unwrap_or(0.0);
            let cap = eco.capacity.get(r).copied().unwrap_or(f64::INFINITY);
            let next = current + eco.production.get(r).copied().unwrap_or(0.0) * hours;
            let value = if current > cap { current.min(next) } else { cap.min(next) };
            resources.insert(r.to_string(), value.max(0.0));
        }
        Village { resources, resources_at: now.max(v.resources_at), ..v.clone() }
    }

    /// Add resources (loot, refunds) without exceeding storage.
    pub fn deposit(&self, v: &Village, amount: &ResourceMap) -> Village {
        let cap = self.economy(v, 0.0).capacity;
        let mut resources = add(&v.resources, amount);
        for (r, value) in resources.iter_mut() {
            let before = v.resources.get(r).copied().unwrap_or(0.0);
            let limit = cap.get(r).copied().unwrap_or(f64::INFINITY).max(before);
            *value = value.min(limit);
        }
        Village { resources, ..v.clone() }
    }

    pub fn build_cost(&self, building: &str, level: u32) -> ResourceMap {
        let b = self.building(building).expect("known building");
        round(&scale(&b.cost.base, b.cost.factor.powi(level as i32 - 1)))
    }

    pub fn build_seconds(&self, v: &Village, building: &str, level: u32) -> i64 {
        let b = self.building(building).expect("known building");
        let raw = b.time.base * b.time.factor.powi(level as i32 - 1);
        let secs = raw * self.economy(v, 0.0).build_speed / self.pack.world.speed;
        (secs.round() as i64).max(1)
    }

    /// Validate a construction order. `v` must be accrued to now.
    /// Highest level of a building in this village: field buildings gain `field_levels` from techs.
    pub fn max_level(&self, v: &Village, def: &crate::pack::Building) -> u32 {
        if def.slot != SlotKind::Field {
            return def.max_level;
        }
        def.max_level + v.techs.iter().filter_map(|t| self.tech(t)).map(|t| t.field_levels).sum::<u32>()
    }

    pub fn plan_build(
        &self,
        v: &Village,
        queue: &[QueuedBuild],
        slot: usize,
        building: Option<&str>,
    ) -> Result<BuildPlan, PlanError> {
        let rules = &self.pack.village;
        let current = v.slots.get(slot).ok_or(PlanError::InvalidSlot)?;
        if queue.len() >= self.build_queue(v) {
            return Err(PlanError::QueueFull);
        }
        let fields = rules.field_slots.len();
        if slot >= fields && slot < self.extra_field_base() && current.building.is_none() && slot - fields >= self.growth(v).0 {
            return Err(PlanError::SiteLocked);
        }
        let queued_here: Vec<&QueuedBuild> = queue.iter().filter(|q| q.slot == slot).collect();
        let occupant = current.building.clone().or_else(|| queued_here.first().map(|q| q.building.clone()));

        let base = self.extra_field_base();
        if !current.foreign && slot >= base && slot - base >= self.open_extra_fields(v) {
            return Err(PlanError::SiteLocked);
        }
        let fixed = if current.foreign { None } else { self.field_building(slot).map(String::from) };
        let id: String = if let Some(fixed) = fixed {
            if building.is_some_and(|b| b != fixed) {
                return Err(PlanError::WrongBuilding);
            }
            fixed
        } else if let Some(occ) = occupant {
            if building.is_some_and(|b| b != occ) {
                return Err(PlanError::AlreadyBuilt);
            }
            occ
        } else {
            let id = building.ok_or(PlanError::UnknownBuilding)?;
            let def = self.building(id).ok_or(PlanError::UnknownBuilding)?;
            if def.slot != SlotKind::Center || def.foreign != current.foreign {
                return Err(PlanError::SlotType);
            }
            let elsewhere = v.slots.iter().any(|s| s.building.as_deref() == Some(id))
                || queue.iter().any(|q| q.building == id);
            if def.unique && elsewhere {
                return Err(PlanError::AlreadyBuilt);
            }
            id.to_string()
        };

        let def = self.building(&id).ok_or(PlanError::UnknownBuilding)?;
        let pending = queued_here.iter().map(|q| q.level).fold(current.level, u32::max);
        let level = pending + 1;
        if level > self.max_level(v, def) {
            return Err(PlanError::MaxLevel);
        }
        if !self.meets_requirements(v, &def.requires) {
            return Err(PlanError::Requirements);
        }
        let cost = self.build_cost(&id, level);
        if !covers(&v.resources, &cost) {
            return Err(PlanError::InsufficientResources);
        }
        let seconds = self.build_seconds(v, &id, level);
        Ok(BuildPlan { slot, building: id, level, cost, seconds })
    }

    /// Validate a research order. `queued` are techs already being researched here.
    pub fn plan_research(&self, v: &Village, queued: &[String], tech: &str) -> Result<ResearchPlan, PlanError> {
        let t = self.tech(tech).ok_or(PlanError::UnknownTech)?;
        if v.techs.iter().any(|x| x == tech) || queued.iter().any(|x| x == tech) {
            return Err(PlanError::AlreadyResearched);
        }
        let lv = self.building_levels(v);
        if lv.get(&t.building).copied().unwrap_or(0) < t.level || !self.meets_requirements(v, &t.requires) {
            return Err(PlanError::Requirements);
        }
        if !t.after.iter().all(|a| v.techs.contains(a)) {
            return Err(PlanError::TechMissing);
        }
        let cost = round(&t.cost);
        if !covers(&v.resources, &cost) {
            return Err(PlanError::InsufficientResources);
        }
        let seconds = ((t.time / self.pack.world.speed).round() as i64).max(1);
        Ok(ResearchPlan { tech: tech.to_string(), cost, seconds })
    }

    pub fn complete_research(&self, v: &Village, tech: &str) -> Village {
        let mut out = v.clone();
        if !out.techs.iter().any(|t| t == tech) {
            out.techs.push(tech.to_string());
        }
        out
    }

    /// Influence a city of `culture` points exerts at `distance` tiles: full at the city,
    /// fading linearly to nothing at `culture.radius`.
    pub fn influence(&self, culture: f64, distance: f64) -> f64 {
        let r = self.pack.culture.radius;
        if culture <= 0.0 || distance >= r {
            0.0
        } else {
            culture * (1.0 - distance / r)
        }
    }

    /// Battle bonus of the side whose summed influence at the battlefield is `own`
    /// against `other`. Zero unless `own` is larger.
    pub fn prestige(&self, own: f64, other: f64) -> f64 {
        let c = &self.pack.culture;
        if own <= other {
            return 0.0;
        }
        (c.prestige_scale * ((own + 10.0) / (other + 10.0)).ln()).min(c.prestige_max)
    }

    pub fn complete_build(&self, v: &Village, slot: usize, building: &str, level: u32) -> Village {
        let mut out = v.clone();
        if let Some(s) = out.slots.get_mut(slot) {
            s.building = Some(building.to_string());
            s.level = s.level.max(level);
        }
        out
    }

    /// Validate a training order. `v` must be accrued to now.
    pub fn plan_training(&self, v: &Village, tribe: &str, unit: &str, count: u64) -> Result<TrainPlan, PlanError> {
        let u = self.unit(unit).ok_or(PlanError::UnknownUnit)?;
        if u.tribe != tribe {
            return Err(PlanError::WrongTribe);
        }
        if count == 0 || count > 100_000 {
            return Err(PlanError::InvalidCount);
        }
        let trainers: Vec<u32> = v
            .slots
            .iter()
            .filter(|s| s.building.as_deref() == Some(u.building.as_str()) && s.level > 0)
            .map(|s| s.level)
            .collect();
        if trainers.is_empty() || !self.meets_requirements(v, &u.requires) {
            return Err(PlanError::Requirements);
        }
        if !u.techs.iter().all(|t| v.techs.contains(t)) {
            return Err(PlanError::TechMissing);
        }
        let cost = round(&scale(&u.cost, count as f64));
        if !covers(&v.resources, &cost) {
            return Err(PlanError::InsufficientResources);
        }
        let def = self.building(&u.building).ok_or(PlanError::UnknownBuilding)?;
        // every copy of the training building works in parallel: their rates add up
        let rate: f64 = trainers.iter().map(|l| 1.0 / Curve::multiplier(def.effects.train_speed.as_ref(), *l)).sum();
        let seconds_each = ((u.time / rate / self.pack.world.speed).round() as i64).max(1);
        Ok(TrainPlan { unit: unit.to_string(), count, cost, seconds_each })
    }
}
