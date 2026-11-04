//! Troop movement timing.

use crate::pack::{Content, Units};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq)]
pub struct Point {
    pub x: i32,
    pub y: i32,
}

pub fn distance(a: Point, b: Point) -> f64 {
    (((a.x - b.x) as f64).powi(2) + ((a.y - b.y) as f64).powi(2)).sqrt()
}

impl Content {
    /// Speed of the slowest unit in the group (tiles/hour), `None` if empty.
    pub fn slowest_speed(&self, units: &Units) -> Option<f64> {
        units
            .iter()
            .filter(|(_, &n)| n > 0)
            .filter_map(|(id, _)| self.unit(id).map(|u| u.speed))
            .reduce(f64::min)
    }

    /// Travel time in whole seconds (at least 1), `None` for an empty group.
    pub fn travel_seconds(&self, units: &Units, from: Point, to: Point) -> Option<i64> {
        let speed = self.slowest_speed(units)?;
        let hours = distance(from, to) / (speed * self.pack.world.speed);
        Some(((hours * 3600.0).round() as i64).max(1))
    }
}
