// Shapes returned by the Ovian REST API and pushed over MQTT.

export type ResourceMap = Record<string, number>;
export type Units = Record<string, number>;
export type Curve = number[] | { base: number; factor: number; round?: number };

export interface Slot {
  building: string | null;
  level: number;
  /** The civilization whose architecture the building shows, set when it was founded. */
  style?: string;
  /** A site in the foreign quarter an overlord opened: only foreign buildings stand here. */
  foreign?: boolean;
}

export interface VillageState {
  resources: ResourceMap;
  resources_at: number;
  slots: Slot[];
  units: Units;
  /** Technologies researched in this village. */
  techs?: string[];
  /** Fraction of gross production paid to an overlord (vassals only). */
  tribute?: number;
  /** Hourly tribute received from vassals. */
  tribute_in?: ResourceMap;
}

export interface Economy {
  production: ResourceMap;
  gross: ResourceMap;
  capacity: ResourceMap;
  population: number;
  upkeep: number;
  defense_bonus: number;
  hidden: number;
  build_speed: number;
  /** Center sites open in the current growth phase. */
  center_sites: number;
  /** Extra production fields open (they follow the center sites). */
  extra_fields?: number;
  /** Growth phase id (see Pack.village.growth), if the pack has phases. */
  phase: string | null;
  /** Culture points (temples, universities). */
  culture?: number;
  /** Construction jobs that may run at once (phase + technologies). */
  build_queue?: number;
  /** Hourly tribute paid to the overlord. */
  tribute_out?: ResourceMap;
  /** Hourly tribute received from vassals. */
  tribute_in?: ResourceMap;
}

export interface VillageRef {
  id: number;
  name: string;
  x: number;
  y: number;
  player_id: number;
}

export interface BuildJob {
  id: number;
  slot: number;
  building: string;
  level: number;
  started_at: number;
  due_at: number;
}

export interface TrainJob {
  id: number;
  unit: string;
  building: string;
  remaining: number;
  each_ms: number;
  next_at: number;
  finishes_at: number;
}

export type MovementKind = 'attack' | 'raid' | 'reinforce' | 'return';

export interface Movement {
  id: number;
  kind: MovementKind;
  departs_at: number;
  arrives_at: number;
  from: VillageRef;
  to: VillageRef;
  units?: Units;
  loot?: ResourceMap;
  /** Scouts' mission: sabotage, steal or incite (none = look). */
  mission?: string | null;
}

export interface ResearchJob {
  id: number;
  tech: string;
  started_at: number;
  due_at: number;
}

export interface VillageView extends VillageRef {
  /** Opened by its overlord as steward: they may build here, paid from this city's stores. */
  steward?: boolean;
  population: number;
  state: VillageState;
  economy: Economy;
  hosted_upkeep: number;
  build_queue: BuildJob[];
  training: TrainJob[];
  research?: ResearchJob[];
  movements: { outgoing: Movement[]; incoming: Movement[] };
  reinforcements: {
    here: { id: number; units: Units; home: VillageRef }[];
    abroad: { id: number; units: Units; host: VillageRef }[];
  };
  server_time: number;
  /** The overlord this city submitted to, or null when free. */
  submission?: Submission | null;
  /** Cities submitted to this one. */
  vassals?: Vassal[];
  /** The overlord's tax range and realm-wide default (null: the usual tribute). */
  taxes?: { min: number; max: number; usual: number; voluntary: number; default: number | null };
  /** This city's pending offer of fealty. */
  fealty_offer?: FealtyOffer | null;
  /** Cities offering to become vassals of this one. */
  fealty_offers?: FealtyOffer[];
  /** Foreign quarters opened by overlords, past and present. */
  foreign?: ForeignQuarter[];
  /** How much lighter foreign exchanges make the tribute (a fraction). */
  exchange_relief?: number;
  /** Present while the city eats more of the upkeep resource than it produces. */
  starvation?: { resource: string; deficit: number; starving: boolean; empty_at: number | null; troops: number };
  /** Battles won in a row towards submission, against and by this city. */
  dominance?: Dominance;
  /** Only in a superuser's view of someone else's city. */
  owner?: { id: number; name: string; tribe: string; npc: boolean };
  /** Colonies this city can found (one every N levels of the city centre). */
  ver_sacrum?: VerSacrum;
  market?: MarketView;
  hero?: { name: string; template: string; status: string; here: boolean } | null;
  gods?: GodsView;
  great?: GreatBuilding[];
  contentment?: ContentmentView;
  /** Citizens who take up arms when the city is attacked (civil servants), as units. */
  militia?: Record<string, number>;
  government?: { id: string; label: string; anarchy_until: number };
  season?: SeasonNow;
  omen?: Omen;
  roads?: RoadsView;
  routes?: TradeRoute[];
  /** Layers under the sites, digs under way and the finds kept here. */
  archaeology?: ArchaeologyView;
  /** The governor ruling this city (a prefect when sent by the overlord). */
  governor?: Governorship | null;
  /** A governor on the way here. */
  governor_coming?: { id: number; name: string; arrives_at: number; prefect: boolean; traits: GovernorTrait[] } | null;
}

/** One layer of a building site: a building that ended there. */
export interface Layer {
  building: string;
  style?: string | null;
  level: number;
  /** demolished | ruined */
  end: string;
  from?: number | null;
  to?: number | null;
  dug: boolean;
}

/** A find, with its full context (format ovian-find/1: other games may import it). */
export interface Find {
  id: number;
  format: string;
  uri: string;
  name: string;
  /** common | fine | exceptional */
  grade: string;
  culture: number;
  found_at: number;
  found_by: string;
  owner: { player_id: number; name: string | null } | null;
  kept_in: { id: number; name: string; x: number; y: number; player_id: number } | null;
  context: {
    world: string;
    pack: string;
    site: { village_id: number; village: string; x: number; y: number; slot?: number };
    depth?: number;
    layer: {
      building?: string; building_name?: string; style?: string; style_name?: string; level?: number;
      from?: number | null; to?: number | null; built_by?: number | null; built_by_name?: string | null; end?: string;
      ancient?: string; people?: string; age?: string;
      /** spoils of a barbarian camp of this level */
      camp?: number;
    };
  };
}

export interface ArchaeologyView {
  cost: ResourceMap;
  hours: number;
  /** By slot index: the known layers (top last) and whether the site was dug to the rock. */
  sites: Record<string, { layers: Layer[]; probed: boolean }>;
  digs: { id: number; slot: number; started_at: number; due_at: number }[];
  finds: Find[];
  /** Finds are shown in the `building` (temples): `room` of them, the best first, adding `culture`. */
  display: { building: string; room: number; shown: number[]; culture: number };
}

export interface GovernorTrait {
  id: string;
  name?: string;
  text?: string;
  contentment?: number;
  unrest?: number;
  calm?: number;
  size?: number;
  tribute?: number;
  agitators?: number;
  production?: number;
  defense?: number;
}

/** The governor of a city, as the city sees it. */
export interface Governorship {
  id: number;
  name: string;
  tribe: string;
  traits: GovernorTrait[];
  player_id: number;
  prefect: boolean;
  since: number;
}

export interface Governor {
  id: number;
  name: string;
  tribe: string;
  traits: GovernorTrait[];
  village: VillageRef | null;
  moving_to: VillageRef | null;
  arrives_at: number | null;
  hired_at: number;
}

export interface GovernorsView {
  governors: Governor[];
  candidates: { index: number; name: string; traits: GovernorTrait[] }[];
  offer_until: number;
  count: number;
  max: number;
  cost: ResourceMap;
  speed: number;
}

export interface Auxiliaries {
  /** Levied troops of the vassal's people in the garrison (or out on campaign from it). */
  levied: number;
  queued: number;
  /** What the vassal's buildings can train, at the overlord's price. */
  options: { unit: string; name: string; seconds_each: number; cost_each: ResourceMap }[];
  training: { id: number; unit: string; remaining: number; next_at: number; finishes_at: number }[];
}

export interface TimedEffect { kind: 'contentment' | 'boost'; label: string; value: number; until: number }

export interface ContentmentView {
  /** Missing when the world has no contentment rules (then only effects). */
  score?: number;
  factors?: { label: string; value: number }[];
  /** Production change from contentment, as a fraction. */
  production?: number;
  /** Defense the citizens add when the city is attacked, as a fraction (above ``defense_from`` points). */
  defense?: number;
  defense_from?: number;
  unrest?: number;
  rebel_at?: number;
  rebel_below?: number;
  can_rebel?: boolean;
  /** What researched techs do to unrest: multipliers, and the shift of the restless line. */
  politics?: { unrest?: number; calm?: number; size?: number; tribute?: number; agitators?: number; rebel_below?: number };
  effects: TimedEffect[];
}

export interface SeasonNow {
  id: string; name: string; year: number; index: number; started_at: number; ends_at: number;
  festival?: { number: number; opens_at: number; closes_at: number; name: string };
}

export interface Season { id: string; name: string; production?: ResourceMap; travel?: number; contentment?: number }

export interface FestivalContest {
  name: string; text?: string; kind: 'resources' | 'army' | 'culture'; resources?: string[];
  standings: { player_id: number; username: string; score: number }[];
  mine: number | null;
}

export interface Calendar {
  season: (SeasonNow & Season) | null;
  seasons: Season[];
  season_ms: number | null;
  festival?: {
    name: string; text: string; season: string; active: boolean; number: number | null;
    opens_at: number | null; closes_at: number | null;
    prizes: { resources?: ResourceMap; favor?: number; contentment?: number }[];
    contests: Record<string, FestivalContest>;
    last: { number: number; name: string; contests: Record<string, { name: string; winners: { rank: number; player: { id: number; name: string }; score: number }[] }> } | null;
  };
}

export interface OmenChoice {
  id: string; label: string; cost: ResourceMap; gain: ResourceMap; available: boolean;
  favor_cost?: number; favor?: number; contentment?: number; boost?: number; hours?: number; unrest?: number;
}

export interface Omen { id: string; title: string; text: string; default: string; choices: OmenChoice[]; at: number; expires_at: number }

export interface Government {
  id: string; name: string; text?: string; production?: ResourceMap; attack?: number; defense?: number; contentment?: number;
  favor?: number; trade_speed?: number; march_speed?: number;
}

export interface GovernmentView {
  current: string; label: string; anarchy_until: number; can_change_at: number; anarchy_hours: number; options: Government[];
}

export interface RoadsView {
  speed: number; max: number; per_levels?: number; max_length: number; cost_per_tile: ResourceMap; seconds_per_tile: number;
  list: { id: number; ready_at: number; to: VillageRef }[];
}

export interface Road { id: number; player_id: number; ready: boolean; ready_at: number; a: VillageRef; b: VillageRef }

export interface TradeRoute { id: number; to: VillageRef; resources: ResourceMap; every_ms: number; next_at: number; last_error: string | null }

export interface Medal { category: string; name: string; rank: number; value: number; round: number; period: number; at: number; player: { id: number; name: string } }

export interface MedalTableRow { player_id: number; username: string; gold: number; silver: number; bronze: number }

export interface MedalsView {
  round: number; period: number; next_award_at: number | null;
  categories: { id: string; name: string; stat: string; unit: string; progress: number }[];
  latest: Medal[]; table: MedalTableRow[]; mine: Medal[];
}

export interface HallOfFame {
  current_round: number;
  rounds: { round: number; ended_at: number; data: {
    winner: Victory['winner']; started_at: number | null; speed: number; chronicle_entries: number;
    players: { id: number; username: string; tribe: string; cities: number; population: number; culture: number }[];
    alliances: { id: number; tag: string; name: string; members: number; population: number }[];
    medals: MedalTableRow[];
  } }[];
  all_time: MedalTableRow[];
}

export interface ChronicleEntry {
  id: number; round: number; at: number; kind: string; title: string; x: number | null; y: number | null;
  player: { id: number; name: string } | null; village_id: number | null; data: Record<string, any>;
}

export interface BattleResult {
  attacker_won: boolean;
  attack_power: number;
  defense_power: number;
  attacker_losses: Units;
  attacker_survivors: Units;
  defender_losses: Units[];
  defender_survivors: Units[];
}

export interface MarketView {
  merchants: number;
  busy: number;
  carry: number;
  speed: number;
  shipments: { outgoing: boolean; from: { id: number; name: string }; to: { id: number; name: string }; resources: ResourceMap; arrives_at: number }[];
  offers: { id: number; give: ResourceMap; want: ResourceMap; merchants: number; created_at: number }[];
}

export interface TradeOffer {
  id: number;
  give: ResourceMap;
  want: ResourceMap;
  created_at: number;
  mine: boolean;
  village: VillageRef;
  player_name: string;
  distance: number | null;
}

export interface Power {
  name: string;
  cost: number;
  description: string;
  target?: boolean;
  boost?: number;
  defense?: number;
  attack?: number;
  destroy?: number;
  hours?: number;
}

export interface GodsView {
  favor: number;
  favor_at: number;
  rate: number;
  max: number;
  powers: Record<string, Power>;
  blessing: { until: number; boost: number } | null;
  shield: { until: number; defense: number } | null;
  fury: number | null;
}

export interface GreatBuilding {
  building: string;
  slot: number;
  level: number;
  max_level: number;
  complete?: boolean;
  next_level?: number;
  cost?: number;
  points?: number;
  contributors?: { player_id: number; name: string; points: number }[];
  village?: VillageRef;
  owner?: string;
  distance?: number;
}

export interface HeroCandidate { id: string; name: string; title: string; icon: string | null; history: string }

export interface Hero {
  player_id: number;
  village_id: number | null;
  template: string;
  name: string;
  xp: number;
  level: number;
  level_xp: number;
  next_xp: number;
  unspent: number;
  points: { attack: number; defense: number; production: number };
  bonus: { attack: number; defense: number; production: number };
  status: 'home' | 'away' | 'dead';
  revive_at: number;
}

export interface HeroView {
  hero: Hero | null;
  candidates: HeroCandidate[];
  rules: Record<string, number>;
}

export interface AllianceMember { id: number; username: string; tribe: string; role: 'leader' | 'officer' | 'member'; population: number; villages: number; culture: number }

export interface Alliance {
  id: number;
  name: string;
  tag: string;
  description: string;
  members: AllianceMember[];
  population: number;
  diplomacy: { other_id: number; kind: 'ally' | 'nap' | 'war'; status: 'proposed' | 'active'; name: string; tag: string }[];
  proposals: { other_id: number; kind: 'ally' | 'nap'; name: string; tag: string }[];
}

export interface MyAlliance {
  alliance: Alliance | null;
  role: 'leader' | 'officer' | 'member' | null;
  invites: { id: number; name: string; tag: string; invited_by: string | null }[];
  sent_invites?: { id: number; username: string }[];
}

export interface Quest {
  id: string; title: string; text: string; reward: ResourceMap; have: number; need: number; complete: boolean;
  /** Tutorial: how to do it, and what the client should point at. */
  hint?: string;
  focus?: { building?: string; site?: boolean; screen?: string };
}

export interface Achievement { id: string; name: string; description: string; value: number; progress: number; unlocked_at: number | null }

export interface Victory {
  winner: { player: { id: number; name: string }; village: VillageRef; at: number } | null;
  building: string;
  max_level: number | null;
  race: { id: number; name: string; x: number; y: number; username: string; level: number }[];
}

export interface VerSacrum {
  level: number;
  every: number;
  earned: number;
  used: number;
  available: number;
  next_at_level: number;
  /** Farthest a colony may be founded, in tiles. */
  range: number;
  cost: ResourceMap;
  speed: number;
  migrations: { id: number; x: number; y: number; name: string; departs_at: number; arrives_at: number }[];
  colonies: { id: number; name: string; x: number; y: number }[];
}

/** A city and its owner, as the submission views list them. */
export interface CityRef {
  village: VillageRef;
  player_name: string;
  tribe: string;
}

export interface Submission extends CityRef {
  since: number;
  /** A colony of its own mother city, which can never be released. */
  colony?: boolean;
  /** Hourly tribute paid. */
  flow: ResourceMap;
  tribute: number;
  /** What a vassal gets for its tribute (none for a colony). */
  benefits?: { production?: number; defense?: number; contentment?: number; trade_speed?: number };
  /** Swore fealty of its own will: it may renounce it. */
  voluntary?: boolean;
  /** The tribute rate the overlord taxes this city at, and whether it is set for this city or the whole realm. */
  tax?: TaxInfo;
}

export interface TaxInfo {
  rate: number;
  source: 'city' | 'realm' | 'usual';
  usual: number;
  /** Contentment from the tax (negative when heavy); only on the overlord's side. */
  mood?: number;
}

/** An offer of fealty: a city that wants to become a vassal (or the city it offered itself to). */
export interface FealtyOffer extends CityRef {
  at: number;
  /** Tribute a voluntary vassal pays. */
  tribute: number;
}

/** The overlord's protection, as short lines. */
export function vassalBenefits(b: Submission['benefits']): string[] {
  const out: string[] = [];
  if (!b) return out;
  if (b.production) out.push(`+${Math.round(b.production * 100)}% production`);
  if (b.defense) out.push(`+${Math.round(b.defense * 100)}% defense against everyone but the overlord`);
  if (b.contentment) out.push(`+${b.contentment} contentment`);
  if (b.trade_speed) out.push(`merchants and reinforcements to the overlord's cities ${Math.round(b.trade_speed * 100)}% faster`);
  return out;
}

export interface Vassal extends CityRef {
  since: number;
  flow: ResourceMap;
  /** Founded by a ver sacrum: bound to its mother city for good. */
  colony?: boolean;
  /** This overlord's embassy in the vassal city (null when the world has none or it is a colony). */
  embassy?: EmbassyInfo | null;
  /** This overlord's other sites there (cultural exchange, garrison). */
  sites?: EmbassyInfo[];
  /** No governor rules it and the embassy is high enough: the overlord builds there as in their own city. */
  steward?: boolean;
  /** This overlord's garrison there: how many troops may be out on campaign at once, how many are, and who is stationed. */
  garrison?: { capacity: number; out: number; here: Units; auxiliaries?: Auxiliaries };
  tax?: TaxInfo;
}

export interface EmbassyInfo {
  slot: number;
  building: string | null;
  level: number;
  queued: { level: number; due_at: number }[];
  style?: string;
}

/** A foreign quarter opened in this city by an overlord. */
export interface ForeignQuarter {
  player_id: number;
  tribe: string;
  since: number;
  /** When that overlord lost the city. */
  until?: number | null;
  embassy: number;
  /** Sites only this overlord may build on (cultural exchange, garrison). */
  lord_sites?: number[];
  sites: number[];
}

export interface Dominance {
  needed: number;
  threats: { player_id: number; player_name: string; wins: number }[];
  conquests: (CityRef & { wins: number })[];
}

export interface BuildingDef {
  id: string;
  name: string;
  description: string;
  slot: 'field' | 'center';
  max_level: number;
  cost: { base: ResourceMap; factor: number };
  time: { base: number; factor: number };
  population: number;
  requires: Record<string, number>;
  /** At most one per village; non-unique buildings can stand on several sites. */
  unique?: boolean;
  /** Stands only in the foreign quarter of a vassal city (embassy, exchange). */
  foreign?: boolean;
  effects: {
    production?: { resource: string; curve: Curve };
    storage?: { resources: string[]; curve: Curve };
    build_speed?: Curve;
    train_speed?: Curve;
    defense?: Curve;
    hide?: Curve;
    culture?: Curve;
    /** Contentment points in this city only. */
    contentment?: Curve;
  };
}

export interface UnitDef {
  id: string;
  name: string;
  description: string;
  tribe: string;
  building: string;
  requires: Record<string, number>;
  cost: ResourceMap;
  upkeep: number;
  time: number;
  attack: number;
  defense: { infantry: number; cavalry: number };
  class: 'infantry' | 'cavalry';
  speed: number;
  carry: number;
  /** Technologies needed to train it. */
  techs?: string[];
}

export interface TechDef {
  id: string;
  name: string;
  description: string;
  building: string;
  level: number;
  requires: Record<string, number>;
  after: string[];
  cost: ResourceMap;
  time: number;
  /** Extra parallel construction jobs it allows. */
  build_queue?: number;
  /** Extra levels for production sites in the city that researched it. */
  field_levels?: number;
}

export interface CultureNeighbour {
  village: VillageRef;
  player_name: string;
  tribe: string;
  culture: number;
  distance: number;
  your_influence: number;
  their_influence: number;
  attack_bonus: number;
  defense_bonus: number;
}

export interface CultureView {
  village_id: number;
  culture: number;
  influence_here: number;
  radius: number;
  prestige_max: number;
  neighbours: CultureNeighbour[];
}

export interface Pack {
  id: string;
  name: string;
  version: string;
  description: string;
  world: { speed: number; width: number; height: number; seed: number; generator: string };
  resources: { id: string; name: string; upkeep: boolean }[];
  village: {
    field_slots: string[];
    center_slots: number;
    build_queue: number;
    base_storage: number;
    start?: { resources: ResourceMap; buildings: { building: string; level: number }[] };
    growth?: {
      building: string;
      phases: { id: string; name: string; level: number; center_slots: number; build_queue?: number }[];
      extra_fields?: { every: number; fields: string[] };
    };
  };
  buildings: BuildingDef[];
  units: UnitDef[];
  tribes: { id: string; name: string; description: string }[];
  techs?: TechDef[];
  culture?: { radius: number; prestige_max: number; prestige_scale: number };
  extensions: Record<string, unknown>;
}

export interface WorldInfo {
  id: string;
  pack: { id: string; name: string; version: string };
  speed: number;
  width: number;
  height: number;
  server_time: number;
  mqtt_url: string;
  topic_root: string;
}

export interface Me {
  id: number;
  username: string;
  tribe: string;
  protected_until: number;
  villages: { id: number; name: string; x: number; y: number; population: number }[];
  unread_reports: number;
  /** Superuser: may open the Admin screen. */
  is_admin?: boolean;
  /** On vacation until then (0 when not). */
  vacation_until?: number;
  /** An AI ruler. */
  bot?: boolean;
  /** Show the guided tutorial. */
  tutorial?: boolean;
  /** Earlier usernames, oldest first. */
  former_names?: string[];
  /** Set when the player comes from the hub (one account for many worlds): renames happen there. */
  account_id?: number | null;
  /** Badges from the hub (founder, patron, awards); also on GET /players/{id} and /rankings rows. */
  badges?: import('./hub').Badge[];
  /** Founder number (Founder #3), when a founder. */
  founder_no?: number | null;
  /** When the name may change again (null: now). */
  rename_ready_at?: number | null;
}

export interface AdminCity {
  id: number;
  name: string;
  x: number;
  y: number;
  population: number;
  culture: number;
  overlord_id: number | null;
  overlord_name: string | null;
  overlord_player: string | null;
  vassals: number;
}

export interface AdminPlayer {
  id: number;
  username: string;
  tribe: string;
  created_at: number;
  protected_until: number;
  protected: boolean;
  is_admin: boolean;
  last_login_at: number | null;
  last_seen_at: number | null;
  logins: number;
  /** Seen in the last few minutes. */
  online: boolean;
  /** Has logged in at least once since tracking began. */
  connected: boolean;
  cities: AdminCity[];
  /** Cities that are not vassals of another city. */
  own_cities: number;
  population: number;
}

export interface AdminView {
  server_time: number;
  online_window_ms: number;
  totals: { players: number; online: number; connected: number; with_own_city: number; cities: number; vassal_cities: number };
  players: AdminPlayer[];
  world?: { round: number; speed: number; winner: Victory['winner'] };
}

export interface Tile {
  x: number;
  y: number;
  terrain: string;
  settleable: boolean;
}

export interface MapVillage extends VillageRef {
  population: number;
  culture?: number;
  player_name: string;
  tribe: string;
  /** Set when this city is a vassal. */
  overlord_id?: number | null;
  overlord_name?: string | null;
  overlord_player_id?: number | null;
  overlord_player_name?: string | null;
  overlord_tribe?: string | null;
  /** Number of cities submitted to this one. */
  vassals?: number;
  /** Under beginner protection (or on vacation): cannot be attacked or raided. */
  protected?: boolean;
  protected_until?: number;
  vacation?: boolean;
  /** A barbarian camp (non-player). */
  npc?: boolean;
  /** An AI ruler. */
  bot?: boolean;
  camp_level?: number | null;
  alliance_tag?: string | null;
  alliance_id?: number | null;
}

export interface ReportSummary {
  id: number;
  kind: string;
  title: string;
  read: boolean;
  created_at: number;
}

export interface Report extends ReportSummary {
  data: any;
}

export interface ChatMessage {
  id: number;
  channel: string;
  from: { id: number; name: string };
  text: string;
  at: number;
}

export interface GameEvent<T = any> {
  type: string;
  at: number;
  data: T;
}

export type Plan<T> = { ok: true; plan: T } | { ok: false; error: string };

export interface BuildPlan {
  slot: number;
  building: string;
  level: number;
  cost: ResourceMap;
  seconds: number;
}

export interface ResearchPlan {
  tech: string;
  cost: ResourceMap;
  seconds: number;
}

export interface TrainPlan {
  unit: string;
  count: number;
  cost: ResourceMap;
  seconds_each: number;
}

/** A personal access token for scripts and AI assistants (the full value is shown only once). */
export interface AccessToken { id: number; name: string; prefix: string; created_at: number; last_used_at: number | null; token?: string }
