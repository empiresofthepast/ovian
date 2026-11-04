//! Battle resolution and looting, following the classic browser-strategy model.

use crate::pack::{Content, ResourceMap, UnitClass, Units};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum AttackKind {
    /// Fight to the end: the loser is wiped out.
    Attack,
    /// Hit and run: both sides take partial losses.
    Raid,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BattleInput {
    pub kind: AttackKind,
    pub attackers: Units,
    /// Defending groups: home troops first, then each reinforcement.
    pub defenders: Vec<Units>,
    /// Fractional bonus from walls and any mod-provided modifiers.
    #[serde(default)]
    pub defense_bonus: f64,
    /// Multiplier on attack power, for mods (morale, hero, events). Default 1.
    #[serde(default = "one")]
    pub attack_multiplier: f64,
}

fn one() -> f64 {
    1.0
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct BattleResult {
    pub attacker_won: bool,
    pub attack_power: f64,
    pub defense_power: f64,
    pub attacker_loss_ratio: f64,
    pub defender_loss_ratio: f64,
    pub attacker_survivors: Units,
    pub attacker_losses: Units,
    pub defender_survivors: Vec<Units>,
    pub defender_losses: Vec<Units>,
}

pub struct Power {
    pub infantry: f64,
    pub cavalry: f64,
}

impl Power {
    pub fn total(&self) -> f64 {
        self.infantry + self.cavalry
    }
}

fn apply_ratio(units: &Units, ratio: f64) -> (Units, Units) {
    let mut survivors = Units::new();
    let mut losses = Units::new();
    for (id, &n) in units {
        let lost = ((n as f64 * ratio).round() as u64).min(n);
        if n - lost > 0 {
            survivors.insert(id.clone(), n - lost);
        }
        if lost > 0 {
            losses.insert(id.clone(), lost);
        }
    }
    (survivors, losses)
}

impl Content {
    pub fn attack_power(&self, units: &Units) -> Power {
        let mut p = Power { infantry: 0.0, cavalry: 0.0 };
        for (id, &n) in units {
            if let Some(u) = self.unit(id) {
                match u.class {
                    UnitClass::Infantry => p.infantry += u.attack * n as f64,
                    UnitClass::Cavalry => p.cavalry += u.attack * n as f64,
                }
            }
        }
        p
    }

    /// Defense against an attack that is `inf_share` infantry, the rest cavalry.
    pub fn defense_power(&self, groups: &[Units], inf_share: f64) -> f64 {
        groups
            .iter()
            .flat_map(|g| g.iter())
            .filter_map(|(id, &n)| self.unit(id).map(|u| (u, n)))
            .map(|(u, n)| (u.defense.infantry * inf_share + u.defense.cavalry * (1.0 - inf_share)) * n as f64)
            .sum()
    }

    /// - attack: loser loses everything, winner loses (weaker/stronger)^k
    /// - raid: x = (weaker/stronger)^k, winner loses x/(1+x), loser 1/(1+x)
    pub fn resolve_battle(&self, input: &BattleInput) -> BattleResult {
        let k = self.pack.combat.loss_exponent;
        let p = self.attack_power(&input.attackers);
        let a = p.total() * input.attack_multiplier;
        let inf_share = if p.total() > 0.0 { p.infantry / p.total() } else { 1.0 };
        let d = (self.defense_power(&input.defenders, inf_share) + self.pack.combat.base_defense)
            * (1.0 + input.defense_bonus);
        let attacker_won = a > d;
        let x = if a <= 0.0 { 0.0 } else { (a.min(d) / a.max(d)).powf(k) };

        let (atk_ratio, def_ratio) = if a <= 0.0 {
            (1.0, 0.0)
        } else {
            match input.kind {
                AttackKind::Attack if attacker_won => (x, 1.0),
                AttackKind::Attack => (1.0, x),
                AttackKind::Raid => {
                    let (winner, loser) = (x / (1.0 + x), 1.0 / (1.0 + x));
                    if attacker_won { (winner, loser) } else { (loser, winner) }
                }
            }
        };
        let (attacker_survivors, attacker_losses) = apply_ratio(&input.attackers, atk_ratio);
        let (defender_survivors, defender_losses) =
            input.defenders.iter().map(|g| apply_ratio(g, def_ratio)).unzip();
        BattleResult {
            attacker_won,
            attack_power: a,
            defense_power: d,
            attacker_loss_ratio: atk_ratio,
            defender_loss_ratio: def_ratio,
            attacker_survivors,
            attacker_losses,
            defender_survivors,
            defender_losses,
        }
    }

    pub fn carry_capacity(&self, units: &Units) -> f64 {
        units.iter().map(|(id, &n)| self.unit(id).map_or(0.0, |u| u.carry) * n as f64).sum()
    }
}

/// Split `capacity` across resources as evenly as possible, never touching the
/// `hidden` amount of each. Whole numbers only.
pub fn compute_loot(available: &ResourceMap, capacity: f64, hidden: f64) -> ResourceMap {
    let lootable: ResourceMap = available.iter().map(|(r, v)| (r.clone(), (v - hidden).max(0.0).floor())).collect();
    let mut loot: ResourceMap = lootable.keys().map(|r| (r.clone(), 0.0)).collect();
    let mut left = capacity.floor().max(0.0);
    loop {
        let open: Vec<String> = lootable.iter().filter(|(r, v)| loot[*r] < **v).map(|(r, _)| r.clone()).collect();
        if left <= 0.0 || open.is_empty() {
            break;
        }
        let share = (left / open.len() as f64).floor().max(1.0);
        for r in open {
            let take = share.min(lootable[&r] - loot[&r]).min(left);
            *loot.get_mut(&r).unwrap() += take;
            left -= take;
            if left <= 0.0 {
                break;
            }
        }
    }
    loot
}
