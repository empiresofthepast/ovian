//! WebAssembly bindings for the web client. Same rules as the server, used
//! for live resource counters, cost previews and travel-time estimates.
//! Values cross as plain JS objects (maps become objects, not `Map`).

use ovian_engine::combat::BattleInput;
use ovian_engine::village::{QueuedBuild, Village};
use ovian_engine::{compute_loot, map, Content, Pack, Point, ResourceMap, Units};
use serde::Serialize;
use wasm_bindgen::prelude::*;

fn to_js<T: Serialize>(v: &T) -> Result<JsValue, JsError> {
    let ser = serde_wasm_bindgen::Serializer::json_compatible();
    v.serialize(&ser).map_err(|e| JsError::new(&e.to_string()))
}

fn from_js<T: serde::de::DeserializeOwned>(v: JsValue) -> Result<T, JsError> {
    serde_wasm_bindgen::from_value(v).map_err(|e| JsError::new(&e.to_string()))
}

#[wasm_bindgen]
pub struct Engine {
    content: Content,
}

#[wasm_bindgen]
impl Engine {
    #[wasm_bindgen(constructor)]
    pub fn new(pack: JsValue) -> Result<Engine, JsError> {
        let pack: Pack = from_js(pack)?;
        let content = Content::load(pack).map_err(|p| JsError::new(&p.join("\n")))?;
        Ok(Engine { content })
    }

    pub fn economy(&self, village: JsValue, extra_upkeep: f64) -> Result<JsValue, JsError> {
        let v: Village = from_js(village)?;
        to_js(&self.content.economy(&v, extra_upkeep))
    }

    pub fn accrue(&self, village: JsValue, now: f64, extra_upkeep: f64) -> Result<JsValue, JsError> {
        let v: Village = from_js(village)?;
        to_js(&self.content.accrue(&v, now as i64, extra_upkeep))
    }

    /// Returns `{ ok: true, plan }` or `{ ok: false, error }` instead of throwing,
    /// because the UI uses it to grey out buttons.
    #[wasm_bindgen(js_name = planBuild)]
    pub fn plan_build(&self, village: JsValue, queue: JsValue, slot: usize, building: Option<String>) -> Result<JsValue, JsError> {
        let v: Village = from_js(village)?;
        let q: Vec<QueuedBuild> = from_js(queue)?;
        outcome(self.content.plan_build(&v, &q, slot, building.as_deref()))
    }

    #[wasm_bindgen(js_name = planTraining)]
    pub fn plan_training(&self, village: JsValue, tribe: &str, unit: &str, count: f64) -> Result<JsValue, JsError> {
        let v: Village = from_js(village)?;
        outcome(self.content.plan_training(&v, tribe, unit, count.max(0.0) as u64))
    }

    #[wasm_bindgen(js_name = planResearch)]
    pub fn plan_research(&self, village: JsValue, queued: JsValue, tech: &str) -> Result<JsValue, JsError> {
        let v: Village = from_js(village)?;
        let q: Vec<String> = from_js(queued)?;
        outcome(self.content.plan_research(&v, &q, tech))
    }

    pub fn influence(&self, culture: f64, distance: f64) -> f64 {
        self.content.influence(culture, distance)
    }

    pub fn prestige(&self, own: f64, other: f64) -> f64 {
        self.content.prestige(own, other)
    }

    #[wasm_bindgen(js_name = buildCost)]
    pub fn build_cost(&self, building: &str, level: u32) -> Result<JsValue, JsError> {
        if self.content.building(building).is_none() {
            return Err(JsError::new("unknown_building"));
        }
        to_js(&self.content.build_cost(building, level))
    }

    #[wasm_bindgen(js_name = travelSeconds)]
    pub fn travel_seconds(&self, units: JsValue, fx: i32, fy: i32, tx: i32, ty: i32) -> Result<Option<f64>, JsError> {
        let u: Units = from_js(units)?;
        Ok(self.content.travel_seconds(&u, Point { x: fx, y: fy }, Point { x: tx, y: ty }).map(|s| s as f64))
    }

    #[wasm_bindgen(js_name = carryCapacity)]
    pub fn carry_capacity(&self, units: JsValue) -> Result<f64, JsError> {
        Ok(self.content.carry_capacity(&from_js(units)?))
    }

    /// Battle simulator for the UI.
    #[wasm_bindgen(js_name = resolveBattle)]
    pub fn resolve_battle(&self, battle: JsValue) -> Result<JsValue, JsError> {
        let input: BattleInput = from_js(battle)?;
        to_js(&self.content.resolve_battle(&input))
    }

    pub fn tiles(&self, x: i32, y: i32, w: i32, h: i32) -> Result<JsValue, JsError> {
        to_js(&map::tiles(&self.content.pack.world, x, y, w, h))
    }
}

#[derive(Serialize)]
struct Outcome<T: Serialize> {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    plan: Option<T>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<&'static str>,
}

fn outcome<T: Serialize>(r: Result<T, ovian_engine::PlanError>) -> Result<JsValue, JsError> {
    match r {
        Ok(plan) => to_js(&Outcome { ok: true, plan: Some(plan), error: None }),
        Err(e) => to_js(&Outcome::<T> { ok: false, plan: None, error: Some(e.code()) }),
    }
}

#[wasm_bindgen(js_name = computeLoot)]
pub fn compute_loot_js(available: JsValue, capacity: f64, hidden: f64) -> Result<JsValue, JsError> {
    let a: ResourceMap = from_js(available)?;
    to_js(&compute_loot(&a, capacity, hidden))
}
