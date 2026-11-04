use ovian_engine::combat::{AttackKind, BattleInput};
use ovian_engine::village::QueuedBuild;
use ovian_engine::*;
use std::collections::BTreeMap;

fn load(name: &str) -> Content {
    let path = format!("{}/../../../content/{name}/pack.yaml", env!("CARGO_MANIFEST_DIR"));
    let text = std::fs::read_to_string(&path).expect("pack file");
    let pack: Pack = serde_yaml::from_str(&text).expect("pack parses");
    Content::load(pack).unwrap_or_else(|p| panic!("{name} invalid: {p:#?}"))
}

fn units(pairs: &[(&str, u64)]) -> Units {
    pairs.iter().map(|(k, v)| (k.to_string(), *v)).collect()
}

const HOUR: i64 = 3_600_000;

#[test]
fn shipped_packs_are_valid() {
    for name in ["classic", "isles", "antiquity"] {
        let c = load(name);
        assert!(c.upkeep_resource.is_some(), "{name} has an upkeep resource");
    }
}

#[test]
fn invalid_pack_reports_every_problem() {
    let mut pack = load("classic").pack.clone();
    pack.units[0].tribe = "nobody".into();
    pack.buildings[0].requires.insert("ghost".into(), 1);
    let problems = Content::load(pack).unwrap_err();
    assert!(problems.iter().any(|p| p.contains("unknown tribe")));
    assert!(problems.iter().any(|p| p.contains("ghost")));
}

#[test]
fn curves() {
    assert_eq!(Curve::Table(vec![1.0, 2.0, 3.0]).at(0), 0.0);
    assert_eq!(Curve::Table(vec![1.0, 2.0, 3.0]).at(2), 2.0);
    assert_eq!(Curve::Table(vec![1.0, 2.0, 3.0]).at(9), 3.0, "clamps to the last entry");
    let f = Curve::Formula { base: 1200.0, factor: 1.28, round: Some(100.0) };
    assert_eq!(f.at(1), 1200.0);
    assert_eq!(f.at(2), 1500.0);
}

#[test]
fn new_village_matches_rules() {
    let c = load("classic");
    let v = c.create_village(0);
    assert_eq!(v.slots.len(), 18 + 47 + c.extra_field_slots());
    assert_eq!(v.slots[18].building.as_deref(), Some("town_hall"));
    assert_eq!(v.resources["wood"], 750.0);
}

#[test]
fn production_accrues_and_caps() {
    let c = load("classic");
    let v = c.create_village(0);
    let eco = c.economy(&v, 0.0);
    // base 6/h for wood; grain (12/h) also pays upkeep for town hall (2) + rally point (1)
    assert_eq!(eco.production["wood"], 6.0);
    assert_eq!(eco.production["grain"], 9.0);
    let later = c.accrue(&v, 5 * HOUR, 0.0);
    assert!((later.resources["wood"] - 780.0).abs() < 1e-6);
    let much_later = c.accrue(&v, 10_000 * HOUR, 0.0);
    assert_eq!(much_later.resources["wood"], 800.0, "capped by base storage");
}

#[test]
fn upkeep_can_drain_but_not_below_zero() {
    let c = load("classic");
    let mut v = c.create_village(0);
    v.units = units(&[("legionary", 100)]);
    let eco = c.economy(&v, 0.0);
    assert!(eco.production["grain"] < 0.0);
    assert_eq!(c.accrue(&v, 1000 * HOUR, 0.0).resources["grain"], 0.0);
}

#[test]
fn build_plan_rules() {
    let c = load("classic");
    let v = c.create_village(0);
    // field slot 0 is a woodcutter
    let plan = c.plan_build(&v, &[], 0, None).unwrap();
    assert_eq!((plan.building.as_str(), plan.level), ("woodcutter", 1));
    assert_eq!(plan.cost["clay"], 100.0);
    assert_eq!(c.plan_build(&v, &[], 0, Some("farm")), Err(PlanError::WrongBuilding));
    // a fresh center slot needs a building id
    assert_eq!(c.plan_build(&v, &[], 20, None), Err(PlanError::UnknownBuilding));
    assert_eq!(c.plan_build(&v, &[], 20, Some("woodcutter")), Err(PlanError::SlotType));
    assert_eq!(c.plan_build(&v, &[], 20, Some("barracks")), Err(PlanError::Requirements));
    assert_eq!(c.plan_build(&v, &[], 20, Some("town_hall")), Err(PlanError::AlreadyBuilt));
    assert!(c.plan_build(&v, &[], 20, Some("warehouse")).is_ok());
    assert_eq!(c.plan_build(&v, &[], 999, None), Err(PlanError::InvalidSlot));

    // queued levels stack on the same slot and count against the queue
    let q = vec![QueuedBuild { slot: 0, building: "woodcutter".into(), level: 1 }];
    assert_eq!(c.plan_build(&v, &q, 0, None).unwrap().level, 2);
    let q2 = vec![q[0].clone(), QueuedBuild { slot: 1, building: "woodcutter".into(), level: 1 }];
    assert_eq!(c.plan_build(&v, &q2, 2, None), Err(PlanError::QueueFull));
    // a unique building queued in another slot blocks a second one; a non-unique one does not
    let q3 = vec![QueuedBuild { slot: 20, building: "wall".into(), level: 1 }];
    assert_eq!(c.plan_build(&v, &q3, 21, Some("wall")), Err(PlanError::AlreadyBuilt));
    let q4 = vec![QueuedBuild { slot: 20, building: "warehouse".into(), level: 1 }];
    assert!(c.plan_build(&v, &q4, 21, Some("warehouse")).is_ok());

    let mut poor = v.clone();
    poor.resources.values_mut().for_each(|r| *r = 0.0);
    assert_eq!(c.plan_build(&poor, &[], 0, None), Err(PlanError::InsufficientResources));
}

#[test]
fn town_hall_speeds_construction() {
    let c = load("classic");
    let v = c.create_village(0);
    let slow = c.build_seconds(&v, "woodcutter", 1);
    let fast = c.build_seconds(&c.complete_build(&v, 18, "town_hall", 10), "woodcutter", 1);
    assert!(fast < slow);
}

#[test]
fn completed_buildings_change_economy() {
    let c = load("classic");
    let v = c.create_village(0);
    let v = c.complete_build(&v, 0, "woodcutter", 1);
    let v = c.complete_build(&v, 20, "warehouse", 2);
    let eco = c.economy(&v, 0.0);
    assert_eq!(eco.production["wood"], 14.0);
    assert_eq!(eco.capacity["wood"], 1500.0);
    assert_eq!(eco.capacity["grain"], 800.0);
}

#[test]
fn training_rules() {
    let c = load("classic");
    let v = c.create_village(0);
    assert_eq!(c.plan_training(&v, "legion", "legionary", 1), Err(PlanError::Requirements));
    let v = c.complete_build(&v, 20, "barracks", 1);
    assert_eq!(c.plan_training(&v, "clans", "legionary", 1), Err(PlanError::WrongTribe));
    assert_eq!(c.plan_training(&v, "legion", "legionary", 0), Err(PlanError::InvalidCount));
    assert_eq!(c.plan_training(&v, "legion", "guardian", 1), Err(PlanError::Requirements));
    let plan = c.plan_training(&v, "legion", "legionary", 3).unwrap();
    assert_eq!(plan.cost["iron"], 450.0);
    assert_eq!(plan.seconds_each, 900);
    assert_eq!(c.plan_training(&v, "legion", "legionary", 50), Err(PlanError::InsufficientResources));
}

#[test]
fn attack_strong_beats_weak() {
    let c = load("classic");
    let r = c.resolve_battle(&BattleInput {
        kind: AttackKind::Attack,
        attackers: units(&[("clubman", 100)]),
        defenders: vec![units(&[("legionary", 10)])],
        defense_bonus: 0.0,
        attack_multiplier: 1.0,
    });
    assert!(r.attacker_won);
    assert!(r.defender_survivors[0].is_empty());
    assert!(r.attacker_loss_ratio < 0.2);
    assert!(r.attacker_survivors["clubman"] > 80);
}

#[test]
fn antiquity_spears_hold_against_horse() {
    // Converted from 0 A.D.: spearmen carry a bonus against cavalry, swordsmen do not.
    let c = load("antiquity");
    let charge = |defender: &str| {
        c.resolve_battle(&BattleInput {
            kind: AttackKind::Raid,
            attackers: units(&[("rome_cavalry_spearman", 40)]),
            defenders: vec![units(&[(defender, 50)])],
            defense_bonus: 0.0,
            attack_multiplier: 1.0,
        })
    };
    let spears = charge("rome_infantry_spearman");
    let swords = charge("rome_infantry_swordsman");
    assert!(spears.attacker_loss_ratio > swords.attacker_loss_ratio);
    assert!(!spears.attacker_won);
    assert!(swords.attacker_won);
}

#[test]
fn walls_turn_the_battle() {
    let c = load("classic");
    let input = |bonus| BattleInput {
        kind: AttackKind::Attack,
        attackers: units(&[("clubman", 30)]),
        defenders: vec![units(&[("guardian", 18)])],
        defense_bonus: bonus,
        attack_multiplier: 1.0,
    };
    assert!(c.resolve_battle(&input(0.0)).attacker_won);
    let walled = c.resolve_battle(&input(0.6));
    assert!(!walled.attacker_won);
    assert!(walled.attacker_survivors.is_empty());
}

#[test]
fn raid_leaves_survivors_on_both_sides() {
    let c = load("classic");
    let r = c.resolve_battle(&BattleInput {
        kind: AttackKind::Raid,
        attackers: units(&[("clubman", 50)]),
        defenders: vec![units(&[("spearbearer", 20)])],
        defense_bonus: 0.0,
        attack_multiplier: 1.0,
    });
    assert!(!r.attacker_survivors.is_empty());
    assert!(!r.defender_survivors[0].is_empty());
}

#[test]
fn empty_village_falls_to_anything() {
    let c = load("classic");
    let r = c.resolve_battle(&BattleInput {
        kind: AttackKind::Raid,
        attackers: units(&[("clubman", 1)]),
        defenders: vec![],
        defense_bonus: 0.0,
        attack_multiplier: 1.0,
    });
    assert!(r.attacker_won);
}

#[test]
fn loot_respects_capacity_and_hiding() {
    let avail: ResourceMap = [("wood", 500.0), ("clay", 50.0), ("iron", 1000.0)]
        .iter()
        .map(|(k, v)| (k.to_string(), *v))
        .collect();
    let loot = compute_loot(&avail, 600.0, 100.0);
    assert_eq!(loot["clay"], 0.0, "all clay is hidden");
    assert_eq!(loot.values().sum::<f64>(), 600.0);
    let all = compute_loot(&avail, 1e9, 0.0);
    assert_eq!(all, avail);
}

#[test]
fn travel_time_uses_slowest_unit() {
    let c = load("classic");
    let a = Point { x: 0, y: 0 };
    let b = Point { x: 3, y: 4 };
    assert_eq!(c.travel_seconds(&units(&[("lancer", 1)]), a, b), Some(1125)); // 5 tiles @ 16/h
    assert_eq!(c.travel_seconds(&units(&[("lancer", 1), ("guardian", 1)]), a, b), Some(3600));
    assert_eq!(c.travel_seconds(&BTreeMap::new(), a, b), None);
}

#[test]
fn map_is_deterministic_and_has_room() {
    for name in ["classic", "isles", "antiquity"] {
        let c = load(name);
        let w = &c.pack.world;
        assert_eq!(tile_at(w, 10, 10), tile_at(w, 10, 10));
        assert!(!tile_at(w, -1, 0).settleable);
        let spawns = spawn_candidates(w, 12345, 50);
        assert_eq!(spawns.len(), 50, "{name} has spawn room");
        assert!(spawns.iter().all(|&(x, y)| tile_at(w, x, y).settleable));
        let area = tiles(w, 0, 0, 20, 20);
        assert_eq!(area.len(), 400);
    }
    let isles = load("isles");
    let water = tiles(&isles.pack.world, 0, 0, 64, 64).iter().filter(|t| t.terrain == Terrain::Water).count();
    assert!(water > 500, "the isles pack is mostly sea ({water})");
}

#[test]
fn sites_open_as_the_town_hall_grows() {
    let c = load("classic");
    let mut v = c.create_village(0);
    v.resources = c.resource_ids().map(|r| (r.to_string(), 1e9)).collect();
    let fields = c.pack.village.field_slots.len();
    let eco = c.economy(&v, 0.0);
    assert_eq!(eco.center_sites, 8);
    assert_eq!(eco.phase.as_deref(), Some("village"));
    assert!(c.plan_build(&v, &[], fields + 7, Some("cranny")).is_ok());
    assert_eq!(c.plan_build(&v, &[], fields + 8, Some("cranny")).unwrap_err(), PlanError::SiteLocked);
    let hall = v.slots.iter().position(|s| s.building.as_deref() == Some("town_hall")).unwrap();
    let v = c.complete_build(&v, hall, "town_hall", 5);
    assert_eq!(c.economy(&v, 0.0).center_sites, 14);
    assert_eq!(c.economy(&v, 0.0).phase.as_deref(), Some("town"));
    assert!(c.plan_build(&v, &[], fields + 8, Some("cranny")).is_ok());
    // from the city on, more construction jobs run at once
    // ...and from level 20 every 5 levels open 3 more sites
    for (level, jobs, sites, phase) in [(10, 3, 20, "city"), (19, 3, 20, "city"), (20, 4, 23, "metropolis"), (24, 4, 23, "metropolis"),
                                        (25, 4, 26, "metropolis"), (40, 5, 35, "capital"), (60, 6, 47, "imperial")] {
        let v = c.complete_build(&v, hall, "town_hall", level);
        let eco = c.economy(&v, 0.0);
        assert_eq!((eco.build_queue, eco.center_sites, eco.phase.as_deref()), (jobs, sites, Some(phase)), "level {level}");
    }
    let v60 = c.complete_build(&v, hall, "town_hall", 60);
    assert!(c.plan_build(&v60, &[], fields + 46, Some("cranny")).is_ok());
    assert_eq!(c.plan_build(&v60, &[], fields + 47, Some("cranny")).unwrap_err(), PlanError::WrongBuilding); // the first extra field
    assert_eq!(c.plan_build(&v60, &[], fields + 47 + c.extra_field_slots(), Some("cranny")).unwrap_err(), PlanError::InvalidSlot);
    // Architecture adds one more job
    let v = c.complete_build(&v, hall, "town_hall", 10);
    let busy: Vec<QueuedBuild> = (0..3).map(|i| QueuedBuild { slot: i, building: "woodcutter".into(), level: 1 }).collect();
    assert_eq!(c.plan_build(&v, &busy, 3, None).unwrap_err(), PlanError::QueueFull);
    let v = c.complete_research(&v, "architecture");
    assert_eq!(c.economy(&v, 0.0).build_queue, 4);
    assert!(c.plan_build(&v, &busy, 3, None).is_ok());
}

#[test]
fn normalize_fits_villages_to_the_pack() {
    let c = load("classic");
    let mut v = c.create_village(0);
    let all = 18 + 47 + c.extra_field_slots();
    v.slots.truncate(18 + 15); // founded when the pack had fewer sites
    let n = c.normalize(&v);
    assert_eq!(n.slots.len(), all);
    assert_eq!(n.slots[all - 1].building.as_deref(), c.field_building(all - 1));
    let mut v = c.create_village(0);
    v.slots.extend((0..13).map(|_| Slot::default())); // more than the pack has now
    assert_eq!(c.normalize(&v).slots.len(), all);
}

#[test]
fn non_unique_buildings_can_repeat() {
    let c = load("classic");
    let mut v = c.create_village(0);
    v.resources = c.resource_ids().map(|r| (r.to_string(), 1e9)).collect();
    let f = c.pack.village.field_slots.len();
    // unique: a second town hall is refused; non-unique: a second warehouse is fine
    assert_eq!(c.plan_build(&v, &[], f + 2, Some("town_hall")).unwrap_err(), PlanError::AlreadyBuilt);
    let v = c.complete_build(&v, f + 2, "warehouse", 3);
    assert!(c.plan_build(&v, &[], f + 3, Some("warehouse")).is_ok());
    // copies of one building add their storage
    let one = c.economy(&v, 0.0).capacity["wood"];
    let v = c.complete_build(&v, f + 3, "warehouse", 3);
    assert_eq!(c.economy(&v, 0.0).capacity["wood"], one * 2.0);
    // copies of a training building train in parallel
    let v = c.complete_build(&v, f + 4, "barracks", 1);
    let single = c.plan_training(&v, "legion", "legionary", 1).unwrap().seconds_each;
    let v = c.complete_build(&v, f + 5, "barracks", 1);
    let double = c.plan_training(&v, "legion", "legionary", 1).unwrap().seconds_each;
    assert!((double as f64 - single as f64 / 2.0).abs() <= 1.0, "{single} vs {double}");
}

#[test]
fn tech_tree_unlocks_advanced_units() {
    let c = load("antiquity");
    let mut v = c.create_village(0);
    v.resources = c.resource_ids().map(|r| (r.to_string(), 1e9)).collect();
    let f = c.pack.village.field_slots.len();
    let civic = v.slots.iter().position(|s| s.building.as_deref() == Some("civic_centre")).unwrap();
    let v = c.complete_build(&v, civic, "civic_centre", 10);
    let v = c.complete_build(&v, f + 2, "barracks", 10);
    let v = c.complete_build(&v, f + 3, "university", 3);
    // advanced infantry needs Metallurgy, which needs Philosophy first
    assert_eq!(c.plan_training(&v, "rome", "rome_infantry_antesignanus", 1).unwrap_err(), PlanError::TechMissing);
    assert!(c.plan_training(&v, "rome", "rome_infantry_swordsman", 1).is_ok());
    assert_eq!(c.plan_research(&v, &[], "metallurgy").unwrap_err(), PlanError::TechMissing);
    assert_eq!(c.plan_research(&v, &[], "rites").unwrap_err(), PlanError::Requirements); // no temple
    let v = c.complete_research(&v, "philosophy");
    assert_eq!(c.plan_research(&v, &[], "philosophy").unwrap_err(), PlanError::AlreadyResearched);
    assert_eq!(c.plan_research(&v, &["metallurgy".into()], "metallurgy").unwrap_err(), PlanError::AlreadyResearched);
    assert!(c.plan_research(&v, &[], "metallurgy").is_ok());
    let v = c.complete_research(&v, "metallurgy");
    assert!(c.plan_training(&v, "rome", "rome_infantry_antesignanus", 1).is_ok());
}

#[test]
fn culture_spreads_and_wins_prestige() {
    let c = load("antiquity");
    let v = c.create_village(0);
    let f = c.pack.village.field_slots.len();
    assert_eq!(c.economy(&v, 0.0).culture, 0.0);
    let v = c.complete_build(&v, f + 2, "temple", 5);
    let v = c.complete_build(&v, f + 3, "university", 5);
    let culture = c.economy(&v, 0.0).culture;
    assert!(culture > 30.0, "{culture}");
    // full at the city, fading to nothing at the radius
    assert_eq!(c.influence(culture, 0.0), culture);
    assert!(c.influence(culture, 6.0) < culture && c.influence(culture, 6.0) > 0.0);
    assert_eq!(c.influence(culture, 12.0), 0.0);
    // only the dominant side gains, and never more than the cap
    assert_eq!(c.prestige(10.0, 50.0), 0.0);
    assert!(c.prestige(50.0, 10.0) > 0.05);
    assert_eq!(c.prestige(1e9, 0.0), c.pack.culture.prestige_max);
}

#[test]
fn vassals_pay_tribute() {
    let c = load("classic");
    let mut v = c.create_village(0);
    let free = c.economy(&v, 0.0);
    assert!(free.tribute_out.is_empty());
    v.tribute = 0.1;
    let eco = c.economy(&v, 0.0);
    for (r, gross) in &eco.gross {
        if *gross > 0.0 {
            assert!((eco.tribute_out[r] - gross * 0.1).abs() < 1e-9);
            assert!((free.production[r] - eco.production[r] - gross * 0.1).abs() < 1e-9, "{r}");
        }
    }
    // the overlord receives it on top of its own production
    let mut lord = c.create_village(0);
    lord.tribute_in = eco.tribute_out.clone();
    let got = c.economy(&lord, 0.0);
    let after = c.accrue(&lord, 3_600_000, 0.0);
    for (r, p) in &eco.tribute_out {
        assert!((got.production[r] - free.production[r] - p).abs() < 1e-9);
        assert!(after.resources[r] > c.accrue(&c.create_village(0), 3_600_000, 0.0).resources[r]);
    }
    // a free village serializes without the tribute fields
    let json = serde_json::to_value(c.create_village(0)).unwrap();
    assert!(json.get("tribute").is_none() && json.get("tribute_in").is_none());
}

#[test]
fn boost_raises_production() {
    let c = load("classic");
    let mut v = c.create_village(0);
    let base = c.economy(&v, 0.0).gross;
    v.boost = 0.25;
    let boosted = c.economy(&v, 0.0).gross;
    for (r, p) in &base {
        assert!((boosted[r] - p * 1.25).abs() < 1e-9);
    }
}

#[test]
fn per_resource_modifiers_can_lower_production() {
    let c = load("classic");
    let mut v = c.create_village(0);
    let base = c.economy(&v, 0.0).gross;
    v.boost = -0.1;
    v.boost_by.insert("grain".into(), 0.3);
    v.boost_by.insert("wood".into(), -5.0);
    let g = c.economy(&v, 0.0).gross;
    assert!((g["grain"] - base["grain"] * 1.2).abs() < 1e-9);
    assert!((g["clay"] - base["clay"] * 0.9).abs() < 1e-9);
    assert!((g["wood"] - base["wood"] * 0.1).abs() < 1e-9, "never below 10%");
}

#[test]
fn extra_fields_open_every_ten_levels() {
    let c = load("antiquity");
    let mut v = c.create_village(0);
    v.resources = c.resource_ids().map(|r| (r.to_string(), 1e9)).collect();
    let base = c.extra_field_base();
    assert_eq!(c.extra_field_slots(), 24); // 4 kinds x 6 rounds up to level 60
    assert_eq!(v.slots.len(), base + 24);
    assert_eq!(v.slots[base].building.as_deref(), Some("woodline"));
    assert_eq!(c.economy(&v, 0.0).extra_fields, 0);
    assert_eq!(c.plan_build(&v, &[], base, None).unwrap_err(), PlanError::SiteLocked);
    let civic = v.slots.iter().position(|s| s.building.as_deref() == Some("civic_centre")).unwrap();
    let v = c.complete_build(&v, civic, "civic_centre", 10);
    assert_eq!(c.economy(&v, 0.0).extra_fields, 4);
    let p = c.plan_build(&v, &[], base + 3, None).unwrap();
    assert_eq!((p.building.as_str(), p.level), ("field", 1));
    assert_eq!(c.plan_build(&v, &[], base + 3, Some("barracks")).unwrap_err(), PlanError::WrongBuilding);
    assert_eq!(c.plan_build(&v, &[], base + 4, None).unwrap_err(), PlanError::SiteLocked);
    // a new field produces like the old ones
    let before = c.economy(&v, 0.0).gross["food"];
    let v = c.complete_build(&v, base + 3, "field", 1);
    assert!(c.economy(&v, 0.0).gross["food"] > before);
    let v = c.complete_build(&v, civic, "civic_centre", 25);
    assert_eq!(c.economy(&v, 0.0).extra_fields, 8);
}

#[test]
fn amenities_add_contentment() {
    let c = load("antiquity");
    let mut v = c.create_village(0);
    assert_eq!(c.economy(&v, 0.0).contentment, 0.0);
    let civic = v.slots.iter().position(|s| s.building.as_deref() == Some("civic_centre")).unwrap();
    v = c.complete_build(&v, civic, "civic_centre", 20);
    let free = |v: &Village| v.slots.iter().position(|s| s.building.is_none()).unwrap();
    let g = free(&v);
    v = c.complete_build(&v, g, "gardens", 10);
    let b = free(&v);
    v = c.complete_build(&v, b, "baths", 1);
    let e = c.economy(&v, 0.0);
    assert_eq!(e.contentment, 5.0 + 2.0); // gardens 10 (rounded), baths 1
    // amenities do not radiate culture, except the amphitheatre
    let a = free(&v);
    let culture = e.culture;
    v = c.complete_build(&v, a, "amphitheatre", 1);
    let e = c.economy(&v, 0.0);
    assert_eq!(e.contentment, 10.0);
    assert!(e.culture > culture);
}

#[test]
fn foreign_quarter_takes_only_foreign_buildings() {
    let c = load("antiquity");
    let mut v = c.create_village(0);
    v.resources = c.resource_ids().map(|r| (r.to_string(), 1e9)).collect();
    let n = v.slots.len();
    v.slots.push(Slot { building: Some("embassy".into()), level: 0, style: Some("rome".into()), foreign: true });
    v.slots.push(Slot { foreign: true, ..Slot::default() });
    // normalizing keeps the foreign quarter, last
    let v = c.normalize(&v);
    assert_eq!(v.slots.len(), n + 2);
    let p = c.plan_build(&v, &[], n, None).unwrap();
    assert_eq!((p.building.as_str(), p.level), ("embassy", 1));
    assert_eq!(c.plan_build(&v, &[], n + 1, Some("temple")).unwrap_err(), PlanError::SlotType);
    assert_eq!(c.plan_build(&v, &[], n + 1, Some("exchange")).unwrap().building, "exchange");
    // and foreign buildings stay out of the city proper
    let free = v.slots.iter().position(|s| !s.foreign && s.building.is_none()).unwrap();
    assert_eq!(c.plan_build(&v, &[], free, Some("exchange")).unwrap_err(), PlanError::SlotType);
    // completing a level keeps the style
    let v = c.complete_build(&v, n, "embassy", 1);
    assert_eq!(v.slots[n].style.as_deref(), Some("rome"));
    assert!(v.slots[n].foreign);
}

#[test]
fn industry_raises_production_sites_to_fifteen() {
    let c = load("antiquity");
    let mut v = c.create_village(0);
    v.resources = c.resource_ids().map(|r| (r.to_string(), 1e12)).collect();
    let v = c.complete_build(&v, 0, "woodline", 10);
    assert_eq!(c.plan_build(&v, &[], 0, None).unwrap_err(), PlanError::MaxLevel);
    let mut v = v;
    v.techs.push("industry".into());
    let p = c.plan_build(&v, &[], 0, None).unwrap();
    assert_eq!(p.level, 11);
    let v = c.complete_build(&v, 0, "woodline", 15);
    assert_eq!(c.plan_build(&v, &[], 0, None).unwrap_err(), PlanError::MaxLevel);
    assert!(c.economy(&v, 0.0).gross["wood"] > 400.0);
    // centre buildings keep their own cap
    let temple = c.building("temple").unwrap();
    assert_eq!(c.max_level(&v, temple), temple.max_level);
}

#[test]
fn cultural_exchange_and_garrison() {
    let c = load("antiquity");
    let mut v = c.create_village(0);
    let n = v.slots.len();
    let temple = v.slots.iter().position(|s| s.building.is_none() && !s.foreign).unwrap();
    v = c.complete_build(&v, temple, "temple", 5);
    let before = c.economy(&v, 0.0).culture;
    v.slots.push(Slot { building: Some("cultural_exchange".into()), level: 0, style: Some("rome".into()), foreign: true });
    v.slots.push(Slot { building: Some("garrison".into()), level: 0, style: Some("rome".into()), foreign: true });
    let v = c.complete_build(&v, n, "cultural_exchange", 4);
    let v = c.complete_build(&v, n + 1, "garrison", 3);
    let e = c.economy(&v, 0.0);
    assert!((e.culture_out - before * 0.2).abs() < 1e-9, "{} {}", e.culture_out, before);
    assert!((e.culture - before * 0.8).abs() < 1e-9);
    assert_eq!(e.garrison, 300.0);
    // the overlord's city counts what it receives
    let mut lord = c.create_village(0);
    lord.culture_in = 12.0;
    lord.culture_relics = 3.0;
    assert_eq!(c.economy(&lord, 0.0).culture, c.economy(&c.create_village(0), 0.0).culture + 15.0);
}
