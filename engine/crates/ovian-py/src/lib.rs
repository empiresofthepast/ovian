//! Python bindings. All state crosses the boundary as plain dicts/lists, so
//! Python code can store it as JSON and hand it back unchanged.
//!
//! ```python
//! from ovian_engine import Engine, PlanError
//! engine = Engine(pack_dict)
//! village = engine.create_village(now_ms)
//! plan = engine.plan_build(village, [], 0, None)   # raises PlanError("insufficient_resources")
//! ```

#![allow(unexpected_cfgs)] // pyo3 0.22 macros reference a cfg newer rustc does not know

use ovian_engine::combat::BattleInput;
use ovian_engine::village::{QueuedBuild, Village};
use ovian_engine::{compute_loot, map, Content, Pack, PlanError as EnginePlanError, Point, ResourceMap, Units};
use pyo3::create_exception;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pythonize::{depythonize, pythonize};
use serde::Serialize;

create_exception!(ovian_engine, PackError, PyValueError, "The content pack is invalid.");
create_exception!(ovian_engine, PlanError, PyValueError, "An order breaks the game rules. args[0] is the error code.");

fn to_py<T: Serialize>(py: Python<'_>, v: &T) -> PyResult<PyObject> {
    Ok(pythonize(py, v)?.unbind())
}

fn from_py<'py, T: serde::de::DeserializeOwned>(obj: &Bound<'py, PyAny>) -> PyResult<T> {
    Ok(depythonize(obj)?)
}

fn plan_err(e: EnginePlanError) -> PyErr {
    PlanError::new_err(e.code())
}

#[pyclass(frozen, module = "ovian_engine")]
struct Engine {
    content: Content,
}

#[pymethods]
impl Engine {
    #[new]
    fn new(pack: &Bound<'_, PyAny>) -> PyResult<Self> {
        let pack: Pack = depythonize(pack).map_err(|e| PackError::new_err(e.to_string()))?;
        let content = Content::load(pack).map_err(|p| PackError::new_err(p.join("\n")))?;
        Ok(Self { content })
    }

    /// The normalised pack (defaults filled in), as served to clients.
    fn pack(&self, py: Python<'_>) -> PyResult<PyObject> {
        to_py(py, &self.content.pack)
    }

    #[getter]
    fn upkeep_resource(&self) -> Option<String> {
        self.content.upkeep_resource.clone()
    }

    fn create_village(&self, py: Python<'_>, now: i64) -> PyResult<PyObject> {
        to_py(py, &self.content.create_village(now))
    }

    #[pyo3(signature = (village, extra_upkeep = 0.0))]
    fn economy(&self, py: Python<'_>, village: &Bound<'_, PyAny>, extra_upkeep: f64) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        to_py(py, &self.content.economy(&v, extra_upkeep))
    }

    #[pyo3(signature = (village, now, extra_upkeep = 0.0))]
    fn accrue(&self, py: Python<'_>, village: &Bound<'_, PyAny>, now: i64, extra_upkeep: f64) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        to_py(py, &self.content.accrue(&v, now, extra_upkeep))
    }

    fn deposit(&self, py: Python<'_>, village: &Bound<'_, PyAny>, amount: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        let a: ResourceMap = from_py(amount)?;
        to_py(py, &self.content.deposit(&v, &a))
    }

    fn building_levels(&self, py: Python<'_>, village: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        to_py(py, &self.content.building_levels(&v))
    }

    #[pyo3(signature = (village, queue, slot, building = None))]
    fn plan_build(
        &self,
        py: Python<'_>,
        village: &Bound<'_, PyAny>,
        queue: &Bound<'_, PyAny>,
        slot: usize,
        building: Option<&str>,
    ) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        let q: Vec<QueuedBuild> = from_py(queue)?;
        let plan = self.content.plan_build(&v, &q, slot, building).map_err(plan_err)?;
        to_py(py, &plan)
    }

    fn build_cost(&self, py: Python<'_>, building: &str, level: u32) -> PyResult<PyObject> {
        if self.content.building(building).is_none() {
            return Err(plan_err(EnginePlanError::UnknownBuilding));
        }
        to_py(py, &self.content.build_cost(building, level))
    }

    fn complete_build(
        &self,
        py: Python<'_>,
        village: &Bound<'_, PyAny>,
        slot: usize,
        building: &str,
        level: u32,
    ) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        to_py(py, &self.content.complete_build(&v, slot, building, level))
    }

    fn plan_training(
        &self,
        py: Python<'_>,
        village: &Bound<'_, PyAny>,
        tribe: &str,
        unit: &str,
        count: u64,
    ) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        let plan = self.content.plan_training(&v, tribe, unit, count).map_err(plan_err)?;
        to_py(py, &plan)
    }

    /// `queued` lists techs already being researched in this village.
    fn plan_research(
        &self,
        py: Python<'_>,
        village: &Bound<'_, PyAny>,
        queued: Vec<String>,
        tech: &str,
    ) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        let plan = self.content.plan_research(&v, &queued, tech).map_err(plan_err)?;
        to_py(py, &plan)
    }

    fn complete_research(&self, py: Python<'_>, village: &Bound<'_, PyAny>, tech: &str) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        to_py(py, &self.content.complete_research(&v, tech))
    }

    /// Pad an older village with the center sites a newer pack adds.
    fn normalize(&self, py: Python<'_>, village: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        let v: Village = from_py(village)?;
        to_py(py, &self.content.normalize(&v))
    }

    /// Influence of a city with `culture` points at `distance` tiles.
    fn influence(&self, culture: f64, distance: f64) -> f64 {
        self.content.influence(culture, distance)
    }

    /// Battle bonus for the side with influence `own` against `other`.
    fn prestige(&self, own: f64, other: f64) -> f64 {
        self.content.prestige(own, other)
    }

    fn unit_upkeep(&self, units: &Bound<'_, PyAny>) -> PyResult<f64> {
        let u: Units = from_py(units)?;
        Ok(self.content.unit_upkeep(&u))
    }

    fn carry_capacity(&self, units: &Bound<'_, PyAny>) -> PyResult<f64> {
        let u: Units = from_py(units)?;
        Ok(self.content.carry_capacity(&u))
    }

    /// `battle` is a dict: kind ("attack"/"raid"), attackers, defenders (list), defense_bonus, attack_multiplier.
    fn resolve_battle(&self, py: Python<'_>, battle: &Bound<'_, PyAny>) -> PyResult<PyObject> {
        let input: BattleInput = from_py(battle)?;
        to_py(py, &self.content.resolve_battle(&input))
    }

    /// Seconds to travel between two (x, y) points, or None for an empty group.
    fn travel_seconds(&self, units: &Bound<'_, PyAny>, origin: (i32, i32), target: (i32, i32)) -> PyResult<Option<i64>> {
        let u: Units = from_py(units)?;
        let from = Point { x: origin.0, y: origin.1 };
        let to = Point { x: target.0, y: target.1 };
        Ok(self.content.travel_seconds(&u, from, to))
    }

    fn tile(&self, py: Python<'_>, x: i32, y: i32) -> PyResult<PyObject> {
        to_py(py, &map::tile_at(&self.content.pack.world, x, y))
    }

    fn tiles(&self, py: Python<'_>, x: i32, y: i32, w: i32, h: i32) -> PyResult<PyObject> {
        to_py(py, &map::tiles(&self.content.pack.world, x, y, w, h))
    }

    fn spawn_candidates(&self, rng_seed: u64, count: usize) -> Vec<(i32, i32)> {
        map::spawn_candidates(&self.content.pack.world, rng_seed, count)
    }
}

#[pyfunction]
#[pyo3(name = "compute_loot")]
fn py_compute_loot(py: Python<'_>, available: &Bound<'_, PyAny>, capacity: f64, hidden: f64) -> PyResult<PyObject> {
    let a: ResourceMap = from_py(available)?;
    to_py(py, &compute_loot(&a, capacity, hidden))
}

#[pymodule]
#[pyo3(name = "ovian_engine")]
fn init_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Engine>()?;
    m.add_function(wrap_pyfunction!(py_compute_loot, m)?)?;
    m.add("PackError", m.py().get_type_bound::<PackError>())?;
    m.add("PlanError", m.py().get_type_bound::<PlanError>())?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
