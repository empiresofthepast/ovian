//! Small helpers on resource and unit maps.

use crate::pack::{ResourceMap, Units};

pub fn scale(m: &ResourceMap, k: f64) -> ResourceMap {
    m.iter().map(|(r, v)| (r.clone(), v * k)).collect()
}

pub fn round(m: &ResourceMap) -> ResourceMap {
    m.iter().map(|(r, v)| (r.clone(), v.round())).collect()
}

pub fn add(a: &ResourceMap, b: &ResourceMap) -> ResourceMap {
    let mut out = a.clone();
    for (r, v) in b {
        *out.entry(r.clone()).or_insert(0.0) += v;
    }
    out
}

pub fn subtract(a: &ResourceMap, b: &ResourceMap) -> ResourceMap {
    add(a, &scale(b, -1.0))
}

/// True when `have` holds at least `need` of every resource.
pub fn covers(have: &ResourceMap, need: &ResourceMap) -> bool {
    need.iter().all(|(r, v)| have.get(r).copied().unwrap_or(0.0) + 1e-9 >= *v)
}

pub fn add_units(a: &Units, b: &Units) -> Units {
    let mut out = a.clone();
    for (k, n) in b {
        *out.entry(k.clone()).or_insert(0) += n;
    }
    out.retain(|_, n| *n > 0);
    out
}

/// `a - b`, or `None` when `a` does not hold enough units.
pub fn take_units(a: &Units, b: &Units) -> Option<Units> {
    let mut out = a.clone();
    for (k, n) in b {
        let have = out.get(k).copied().unwrap_or(0);
        if have < *n {
            return None;
        }
        out.insert(k.clone(), have - n);
    }
    out.retain(|_, n| *n > 0);
    Some(out)
}

pub fn count_units(u: &Units) -> u64 {
    u.values().sum()
}
