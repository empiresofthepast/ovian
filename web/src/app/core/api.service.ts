import { Injectable, inject, signal } from '@angular/core';
import { CONFIG } from './config';
import {
  AccessToken,
  ChatMessage, CultureView, MapVillage, Me, Pack, Report, ReportSummary, Tile, Units, VillageView, WorldInfo, AdminView, Alliance, MyAlliance, TradeOffer, HeroView, Quest, Achievement, Victory, GreatBuilding, ResourceMap,
  GovernmentView, Calendar, Road, MedalsView, Medal, HallOfFame, ChronicleEntry, EmbassyInfo, Find, GovernorsView, Treaty, TreatiesView } from './models';

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

const TOKEN_KEY = 'ovian.token';

/** Thin typed client for the REST API. The API is the only way to change game state. */
@Injectable({ providedIn: 'root' })
export class Api {
  private readonly base = inject(CONFIG).apiUrl + '/api/v1';
  readonly token = signal<string | null>(readToken());

  setToken(token: string | null): void {
    this.token.set(token);
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      // storage may be unavailable (private mode); keep the token in memory
    }
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const token = this.token();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(this.base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new ApiError(0, 'network', 'The server cannot be reached.');
    }
    if (res.status === 204) return undefined as T;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401 && token) this.setToken(null);
      const detail = Array.isArray(data.detail) ? data.detail.map((d: any) => d.msg).join(', ') : undefined;
      throw new ApiError(res.status, data.error ?? 'error', data.message ?? detail ?? res.statusText);
    }
    return data as T;
  }

  // auth
  register(username: string, password: string, tribe: string) {
    return this.request<{ token: string; player: { id: number }; village_id: number }>('POST', '/auth/register', { username, password, tribe });
  }
  login(username: string, password: string) {
    return this.request<{ token: string; player: { id: number } }>('POST', '/auth/login', { username, password });
  }
  me() { return this.request<Me>('GET', '/me'); }

  // world
  world() { return this.request<WorldInfo>('GET', '/world'); }
  content() { return this.request<Pack>('GET', '/content'); }
  map(x: number, y: number, w: number, h: number) {
    return this.request<{ tiles: Tile[]; villages: MapVillage[] }>('GET', `/map?x=${x}&y=${y}&w=${w}&h=${h}`);
  }
  verSacrum(id: number, x: number, y: number, name: string) {
    return this.request<VillageView>('POST', `/villages/${id}/ver-sacrum`, { x, y, name });
  }
  /** The city at (x, y), if any. */
  async cityAt(x: number, y: number): Promise<MapVillage | undefined> {
    return (await this.map(x, y, 1, 1)).villages[0];
  }
  // alliances
  myAlliance() { return this.request<MyAlliance>('GET', '/alliance'); }
  alliances() { return this.request<any[]>('GET', '/alliances'); }
  foundAlliance(name: string, tag: string, description: string) { return this.request<Alliance>('POST', '/alliances', { name, tag, description }); }
  describeAlliance(description: string) { return this.request<Alliance>('PATCH', '/alliance', { description }); }
  inviteToAlliance(username: string) { return this.request<unknown>('POST', '/alliance/invites', { username }); }
  withdrawInvite(playerId: number) { return this.request<unknown>('DELETE', `/alliance/invites/${playerId}`); }
  joinAlliance(id: number) { return this.request<Alliance>('POST', `/alliances/${id}/join`); }
  declineInvite(id: number) { return this.request<unknown>('POST', `/alliance/invites/${id}/decline`); }
  leaveAlliance() { return this.request<unknown>('POST', '/alliance/leave'); }
  kick(playerId: number) { return this.request<Alliance>('POST', `/alliance/members/${playerId}/kick`); }
  setRole(playerId: number, role: string) { return this.request<Alliance>('POST', `/alliance/members/${playerId}/role`, { role }); }
  diplomacy(tag: string, kind: string) { return this.request<Alliance>('POST', '/alliance/diplomacy', { tag, kind }); }
  allianceMessages() { return this.request<ChatMessage[]>('GET', '/alliance/messages'); }
  allianceSay(text: string) { return this.request<ChatMessage>('POST', '/alliance/messages', { text }); }
  allianceReports() { return this.request<any[]>('GET', '/alliance/reports'); }
  // market
  ship(id: number, x: number, y: number, resources: ResourceMap) { return this.request<VillageView>('POST', `/villages/${id}/market/send`, { x, y, resources }); }
  offer(id: number, give: ResourceMap, want: ResourceMap) { return this.request<VillageView>('POST', `/villages/${id}/market/offers`, { give, want }); }
  offers(villageId: number) { return this.request<TradeOffer[]>('GET', `/market/offers?village_id=${villageId}`); }
  acceptOffer(offerId: number, villageId: number) { return this.request<VillageView>('POST', `/market/offers/${offerId}/accept?village_id=${villageId}`); }
  cancelOffer(offerId: number) { return this.request<VillageView>('DELETE', `/market/offers/${offerId}`); }
  // hero
  hero() { return this.request<HeroView>('GET', '/hero'); }
  chooseHero(template: string, villageId: number, name: string) { return this.request<HeroView>('POST', '/hero', { template, village_id: villageId, name }); }
  heroPoints(points: { attack?: number; defense?: number; production?: number }) { return this.request<HeroView>('POST', '/hero/points', points); }
  moveHero(villageId: number) { return this.request<HeroView>('POST', '/hero/move', { village_id: villageId }); }
  // quests, achievements, world
  quests() { return this.request<{ quests: Quest[]; done: number; total: number; tutorial: boolean }>('GET', '/quests'); }
  tutorial(on: boolean) { return this.request<{ tutorial: boolean }>('POST', '/me/tutorial', { on }); }
  // realm: government, calendar and festival, omens, roads and routes, medals, chronicle, rounds
  government() { return this.request<GovernmentView>('GET', '/me/government'); }
  setGovernment(id: string) { return this.request<GovernmentView>('POST', '/me/government', { id }); }
  calendar() { return this.request<Calendar>('GET', '/calendar'); }
  enterFestival(contest: string, villageId: number, resources: ResourceMap = {}) {
    return this.request<Calendar>('POST', `/festival/${contest}`, { village_id: villageId, resources });
  }
  answerOmen(villageId: number, choice: string) { return this.request<VillageView>('POST', `/villages/${villageId}/omen/${choice}`); }
  buildRoad(villageId: number, toId: number) { return this.request<VillageView>('POST', `/villages/${villageId}/roads`, { to_id: toId }); }
  abandonRoad(id: number) { return this.request<{ id: number }>('DELETE', `/roads/${id}`); }
  roads(x: number, y: number, w: number, h: number) { return this.request<Road[]>('GET', `/roads?x=${x}&y=${y}&w=${w}&h=${h}`); }
  addRoute(villageId: number, x: number, y: number, resources: ResourceMap, everyHours: number) {
    return this.request<VillageView>('POST', `/villages/${villageId}/routes`, { x, y, resources, every_hours: everyHours });
  }
  dropRoute(id: number) { return this.request<VillageView>('DELETE', `/routes/${id}`); }
  treaties() { return this.request<TreatiesView>('GET', '/treaties'); }
  proposeTreaty(to: string, tribute?: { payer: 'me' | 'them'; resources: ResourceMap; every_hours: number }) {
    return this.request<Treaty>('POST', '/treaties', tribute ? { to, tribute } : { to });
  }
  acceptTreaty(id: number) { return this.request<Treaty>('POST', `/treaties/${id}/accept`); }
  endTreaty(id: number) { return this.request<Treaty | { ended: true }>('DELETE', `/treaties/${id}`); }
  medals() { return this.request<MedalsView>('GET', '/medals'); }
  playerMedals(id: number) { return this.request<Medal[]>('GET', `/players/${id}/medals`); }
  hallOfFame() { return this.request<HallOfFame>('GET', '/hall-of-fame'); }
  chronicle(opts: { kind?: string; before?: number; round?: number; limit?: number } = {}) {
    const q = Object.entries(opts).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&');
    return this.request<{ round: number; kinds: string[]; entries: ChronicleEntry[] }>('GET', `/chronicle${q ? '?' + q : ''}`);
  }
  /** Absolute URL of the chronicle as GeoJSON (public, for downloads and map tools). */
  chronicleGeojsonUrl(round?: number) { return `${this.base}/chronicle.geojson${round ? '?round=' + round : ''}`; }
  newRound(speed?: number) { return this.request<{ round: number; speed: number; players: number }>('POST', '/admin/world/new-round', { speed }); }
  ban(playerId: number, days: number, reason: string) { return this.request<any>('POST', `/admin/players/${playerId}/ban`, { days, reason }); }
  unban(playerId: number) { return this.request<any>('POST', `/admin/players/${playerId}/unban`); }
  claimQuest(id: string, villageId: number) { return this.request<VillageView>('POST', `/quests/${id}/claim?village_id=${villageId}`); }
  achievements() { return this.request<Achievement[]>('GET', '/achievements'); }
  victory() { return this.request<Victory>('GET', '/world/victory'); }
  tokens() { return this.request<AccessToken[]>('GET', '/me/tokens'); }
  createToken(name: string) { return this.request<AccessToken>('POST', '/me/tokens', { name }); }
  revokeToken(id: number) { return this.request<void>('DELETE', `/me/tokens/${id}`); }
  /** Delete the account for good; needs the password and the username typed again. */
  deleteAccount(password: string, confirm: string) { return this.request<{ deleted: boolean }>('POST', '/me/delete', { password, confirm }); }
  changeUsername(username: string, password: string) {
    return this.request<{ token: string; player: { id: number; username: string } }>('POST', '/me/username', { username, password });
  }
  vacation(hours: number) { return this.request<{ vacation_until: number }>('POST', '/me/vacation', { hours }); }
  endVacation() { return this.request<{ vacation_until: number }>('POST', '/me/vacation/end'); }
  // gods and great buildings
  cast(id: number, power: string, x?: number, y?: number) { return this.request<VillageView>('POST', `/villages/${id}/powers/${power}`, { x, y }); }
  greatNear(x: number, y: number, radius = 25) { return this.request<GreatBuilding[]>('GET', `/great-buildings?x=${x}&y=${y}&radius=${radius}`); }
  contribute(ownerVillage: number, building: string, fromVillage: number, resources: ResourceMap) {
    return this.request<VillageView>('POST', `/villages/${ownerVillage}/great/${building}/contribute`, { from_village_id: fromVillage, resources });
  }
  heartbeat() { return this.request<void>('POST', '/me/heartbeat'); }
  adminVillage(id: number) { return this.request<VillageView>('GET', `/admin/villages/${id}`); }
  adminPlayers() { return this.request<AdminView>('GET', '/admin/players'); }
  rankings() { return this.request<any[]>('GET', '/rankings'); }
  player(id: number) { return this.request<any>('GET', `/players/${id}`); }

  // villages
  village(id: number) { return this.request<VillageView>('GET', `/villages/${id}`); }
  rename(id: number, name: string) { return this.request<VillageView>('PATCH', `/villages/${id}`, { name }); }
  build(id: number, slot: number, building?: string) {
    return this.request<VillageView>('POST', `/villages/${id}/build`, { slot, building });
  }
  train(id: number, unit: string, count: number) {
    return this.request<VillageView>('POST', `/villages/${id}/train`, { unit, count });
  }
  research(id: number, tech: string) {
    return this.request<VillageView>('POST', `/villages/${id}/research`, { tech });
  }
  /** Raise one of my overlord sites in a vassal city one level (a new building needs its id), paid by one of my cities. */
  buildOverlordSite(vassalId: number, slot: number, fromId: number, building?: string) {
    return this.request<VillageView & { site: EmbassyInfo }>('POST', `/villages/${vassalId}/foreign/${slot}`, { from: fromId, building });
  }
  /** Raise the embassy in a vassal city one level, paid by one of my cities. */
  buildEmbassy(vassalId: number, fromId: number) {
    return this.request<VillageView & { embassy: EmbassyInfo | null }>('POST', `/villages/${vassalId}/embassy`, { from: fromId });
  }
  /** Dig an empty site or a ruin; the find comes up when the dig is done. */
  excavate(id: number, slot: number) { return this.request<VillageView>('POST', `/villages/${id}/sites/${slot}/excavate`); }
  stopDigging(id: number, slot: number) { return this.request<VillageView>('DELETE', `/villages/${id}/sites/${slot}/excavate`); }
  myFinds() { return this.request<Find[]>('GET', '/me/finds'); }
  moveFind(findId: number, villageId: number) { return this.request<Find>('POST', `/finds/${findId}/move`, { village_id: villageId }); }
  /** Levy the vassal's own troops in my garrison there, paid by one of my cities. */
  levy(vassalId: number, fromId: number, unit: string, count: number) {
    return this.request<VillageView>('POST', `/villages/${vassalId}/auxiliaries`, { from: fromId, unit, count });
  }
  cancelLevy(vassalId: number, jobId: number) { return this.request<VillageView>('DELETE', `/villages/${vassalId}/auxiliaries/${jobId}`); }
  governors() { return this.request<GovernorsView>('GET', '/me/governors'); }
  hireGovernor(candidate: number, fromId: number) { return this.request<GovernorsView>('POST', '/me/governors', { candidate, from: fromId }); }
  appointGovernor(id: number, villageId: number) { return this.request<GovernorsView>('POST', `/governors/${id}/appoint`, { village_id: villageId }); }
  recallGovernor(id: number) { return this.request<GovernorsView>('POST', `/governors/${id}/recall`); }
  dismissGovernor(id: number) { return this.request<GovernorsView>('DELETE', `/governors/${id}`); }
  offerFealty(id: number, to: number) { return this.request<VillageView>('POST', `/villages/${id}/fealty`, { to }); }
  withdrawFealty(id: number) { return this.request<VillageView>('DELETE', `/villages/${id}/fealty`); }
  answerFealty(id: number, vassalId: number, answer: 'accept' | 'decline') {
    return this.request<VillageView>('POST', `/villages/${id}/fealty/${vassalId}/${answer}`);
  }
  taxVassal(id: number, vassalId: number, rate: number | null) {
    return this.request<VillageView>('POST', `/villages/${id}/vassals/${vassalId}/tax`, { rate });
  }
  taxRealm(rate: number | null) { return this.request<{ default: number | null; vassals: number }>('POST', '/me/vassal-tax', { rate }); }
  renounce(id: number) { return this.request<VillageView>('POST', `/villages/${id}/renounce`); }
  release(id: number, vassalId: number) {
    return this.request<VillageView>('POST', `/villages/${id}/vassals/${vassalId}/release`);
  }
  culture(id: number) { return this.request<CultureView>('GET', `/villages/${id}/culture`); }
  demolish(id: number, slot: number) { return this.request<VillageView>('POST', `/villages/${id}/sites/${slot}/demolish`); }
  cancel(id: number, jobId: number) { return this.request<VillageView>('DELETE', `/villages/${id}/jobs/${jobId}`); }
  send(id: number, kind: string, x: number, y: number, units: Units, hero = false, mission?: string, garrison?: number | null) {
    return this.request<VillageView>('POST', `/villages/${id}/send`,
      { kind, x, y, units, hero, mission: mission && mission !== 'look' ? mission : undefined, garrison: garrison ?? undefined });
  }
  recall(id: number, stationedId: number) {
    return this.request<VillageView>('POST', `/villages/${id}/reinforcements/${stationedId}/recall`);
  }
  dismiss(id: number, stationedId: number) {
    return this.request<VillageView>('POST', `/villages/${id}/reinforcements/${stationedId}/dismiss`);
  }

  // reports and chat
  reports(before?: number) { return this.request<ReportSummary[]>('GET', `/reports${before ? `?before=${before}` : ''}`); }
  report(id: number) { return this.request<Report>('GET', `/reports/${id}`); }
  deleteReport(id: number) { return this.request<void>('DELETE', `/reports/${id}`); }
  chatHistory(channel: string) { return this.request<ChatMessage[]>('GET', `/chat/${channel}`); }
  chatPost(channel: string, text: string) { return this.request<ChatMessage>('POST', `/chat/${channel}`, { text }); }
}

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
