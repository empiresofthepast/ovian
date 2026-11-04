import { Injectable, computed, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { Api, ApiError } from './api.service';
import { EngineService } from './engine.service';
import { ChatMessage, GameEvent, Me, VillageView, WorldInfo } from './models';
import { RealtimeMessage, RealtimeService } from './realtime.service';
import { Labels } from './labels';

export interface Toast {
  id: number;
  text: string;
  tone: 'info' | 'good' | 'bad';
}

const VILLAGE_KEY = 'ovian.village';

/** Client-side game state: session, current village, clock and realtime events. */
@Injectable({ providedIn: 'root' })
export class GameStore {
  private readonly api = inject(Api);
  private readonly engine = inject(EngineService);
  private readonly realtime = inject(RealtimeService);
  private readonly skin = inject(Labels);

  readonly world = signal<WorldInfo | null>(null);
  readonly me = signal<Me | null>(null);
  readonly village = signal<VillageView | null>(null);
  readonly toasts = signal<Toast[]>([]);
  readonly chat = signal<Record<string, ChatMessage[]>>({});
  readonly mapEvents = new Subject<GameEvent>();
  /** Alliance chat and other alliance events, for the alliance screen. */
  readonly allianceEvents = new Subject<GameEvent>();
  /** Events on the server topic (seasons, festival, medals, chronicle, rounds). */
  readonly serverEvents = new Subject<GameEvent>();
  /** Set when someone has won the world with a wonder. */
  readonly winner = signal<{ player: { id: number; name: string }; village: { name: string }; at: number } | null>(null);

  /** Estimated server time, ticking every second. */
  readonly now = signal(Date.now());
  private offset = 0;
  private toastSeq = 0;

  /** Live resource amounts of the current village. */
  readonly resources = computed(() => {
    const v = this.village();
    return v ? this.engine.accrue(v.state, v.economy, this.now(), v.hosted_upkeep) : {};
  });

  readonly loggedIn = computed(() => this.me() !== null);
  /** A superuser is looking at someone else's city (read-only). */
  readonly inspecting = computed(() => {
    const v = this.village();
    return !!v && !!this.me() && v.player_id !== this.me()!.id;
  });

  constructor() {
    setInterval(() => this.now.set(Date.now() + this.offset), 1000);
    this.realtime.messages.subscribe((m) => this.onMessage(m));
  }

  async boot(): Promise<void> {
    const [world, pack] = await Promise.all([this.api.world(), this.api.content()]);
    this.api.victory().then((v) => this.winner.set(v.winner)).catch(() => undefined);
    this.world.set(world);
    this.offset = world.server_time - Date.now();
    await this.engine.init(pack);
    if (this.api.token()) await this.enter().catch(() => this.logout());
  }

  async login(username: string, password: string): Promise<void> {
    const r = await this.api.login(username, password);
    this.api.setToken(r.token);
    await this.enter();
  }

  async register(username: string, password: string, tribe: string): Promise<void> {
    const r = await this.api.register(username, password, tribe);
    this.api.setToken(r.token);
    await this.enter(r.village_id);
  }

  logout(): void {
    this.api.setToken(null);
    this.realtime.disconnect();
    this.me.set(null);
    this.village.set(null);
  }

  private async enter(preferred?: number): Promise<void> {
    const me = await this.api.me();
    this.me.set(me);
    let saved: number | undefined = preferred;
    try {
      saved ??= Number(localStorage.getItem(VILLAGE_KEY)) || undefined;
    } catch {
      // ignore
    }
    const id = me.villages.find((v) => v.id === saved)?.id ?? me.villages[0]?.id;
    if (id) await this.selectVillage(id);
    void this.realtime.connect(this.api.token()!, me.id, this.world()!.topic_root);
    this.startHeartbeat();
  }

  private heartbeat: ReturnType<typeof setInterval> | null = null;

  /** Tell the server we are here, so superusers see who is online. */
  private startHeartbeat(): void {
    if (this.heartbeat) return;
    this.heartbeat = setInterval(() => {
      if (this.me() && !document.hidden) this.api.heartbeat().catch(() => undefined);
    }, 60_000);
  }

  /** Superusers: open any player's city, read-only. Leave with selectVillage. */
  async inspect(id: number): Promise<void> {
    this.apply(await this.api.adminVillage(id), true);
  }

  /** Back to the player's own (last) city. */
  async home(): Promise<void> {
    let saved: number | undefined;
    try {
      saved = Number(localStorage.getItem(VILLAGE_KEY)) || undefined;
    } catch {
      // ignore
    }
    const me = this.me();
    const id = me?.villages.find((v) => v.id === saved)?.id ?? me?.villages[0]?.id;
    if (id) await this.selectVillage(id);
  }

  async selectVillage(id: number): Promise<void> {
    try {
      localStorage.setItem(VILLAGE_KEY, String(id));
    } catch {
      // ignore
    }
    this.apply(await this.api.village(id), true);
  }

  async refreshMe(): Promise<void> {
    this.me.set(await this.api.me());
  }

  /** Take a new username; the server hands back a token with the new name. Throws on refusal. */
  /** Delete the account, then log out. */
  async deleteAccount(password: string, confirm: string): Promise<void> {
    await this.api.deleteAccount(password, confirm);
    this.logout();
  }

  async changeUsername(username: string, password: string): Promise<void> {
    const r = await this.api.changeUsername(username, password);
    this.api.setToken(r.token);
    await this.refreshMe();
    const v = this.village();
    if (v) await this.selectVillage(v.id);
  }

  /** Run an order; on success show the returned village, on failure show the reason. */
  async act(order: () => Promise<VillageView>, success?: string): Promise<boolean> {
    if (this.inspecting()) {
      this.toast(this.skin.label('read_only', 'You are only looking at this city; it is not yours to command.'), 'bad');
      return false;
    }
    try {
      this.apply(await order());
      if (success) this.toast(success, 'good');
      return true;
    } catch (e) {
      this.toast(this.errorText(e), 'bad');
      return false;
    }
  }

  errorText(e: unknown): string {
    if (e instanceof ApiError) {
      const key = `error.${e.code}`;
      const text = this.skin.label(key);
      return text === key ? e.message : text;
    }
    return String(e);
  }

  toast(text: string, tone: Toast['tone'] = 'info'): void {
    const t = { id: ++this.toastSeq, text, tone };
    this.toasts.update((l) => [...l.slice(-4), t]);
    setTimeout(() => this.toasts.update((l) => l.filter((x) => x.id !== t.id)), tone === 'bad' ? 7000 : 4500);
  }

  private apply(view: VillageView, force = false): void {
    this.offset = view.server_time - Date.now();
    this.now.set(view.server_time);
    if (force || this.village()?.id === view.id) this.village.set(view);
  }

  private onMessage({ path, event }: RealtimeMessage): void {
    const d = event.data;
    if (path.startsWith('chat/')) {
      if (event.type === 'chat.message') {
        this.chat.update((c) => ({ ...c, [d.channel]: [...(c[d.channel] ?? []), d].slice(-200) }));
      }
      return;
    }
    if (path === 'server') {
      if (event.type === 'world.won') {
        this.winner.set(d);
        this.toast(`${d.player.name} ${this.skin.label('won_world', 'has finished the wonder and won the world!')}`, 'good');
      } else if (event.type === 'season.changed') {
        this.toast(`${d.name} ${this.skin.label('season_begins', 'begins')}, ${this.skin.label('year', 'year')} ${d.year}`, 'info');
      } else if (event.type === 'festival.opened') {
        this.toast(`🏛 ${d.name}: ${this.skin.label('festival_open', 'the games are open, enter your champions!')}`, 'good');
      } else if (event.type === 'festival.ended') {
        const firsts = Object.values<any>(d.contests).map((c) => c.winners[0] && `${c.name}: ${c.winners[0].player.name}`).filter(Boolean);
        this.toast(`🏛 ${d.name} ${this.skin.label('festival_over', 'are over.')} ${firsts.join(' · ')}`, 'info');
      } else if (event.type === 'medals.awarded') {
        this.toast(`🏅 ${this.skin.label('medals_awarded', 'This week\'s medals have been awarded')}`, 'info');
      } else if (event.type === 'world.new_round') {
        this.toast(`${this.skin.label('new_round', 'A new round begins')}: ${this.skin.label('round', 'round')} ${d.round}`, 'good');
        setTimeout(() => location.reload(), 4000);
      }
      this.serverEvents.next(event);
      return;
    }
    if (event.type.startsWith('alliance.')) this.allianceEvents.next(event);
    if (path === 'map') {
      this.mapEvents.next(event);
      return;
    }
    const name = (kind: string, id: string) => this.skin.label(`${kind}.${id}`, (kind === 'building' ? this.engine.building(id)?.name : this.engine.unit(id)?.name) ?? id);
    switch (event.type) {
      case 'village.updated':
        this.apply(d as VillageView);
        this.me.update((m) => m && { ...m, villages: m.villages.map((v) => (v.id === d.id ? { ...v, name: d.name, population: d.population } : v)) });
        break;
      case 'build.completed':
        this.toast(`${name('building', d.building)} ${this.skin.label('level', 'level')} ${d.level}`, 'good');
        break;
      case 'train.completed':
        if (d.remaining === 0) this.toast(`${name('unit', d.unit)}: ${this.skin.label('training_done', 'training complete')}`, 'good');
        break;
      case 'research.completed':
        this.toast(`${this.engine.tech(d.tech)?.name ?? d.tech}: ${this.skin.label('research_done', 'research complete')}`, 'good');
        break;
      case 'alliance.invited':
        this.toast(`${this.skin.label('invited_to', 'Invitation to the alliance')} [${d.alliance.tag}] ${d.alliance.name}`, 'info');
        break;
      case 'trade.incoming':
        this.toast(`${this.skin.label('merchants_from', 'Merchants on their way from')} ${d.from.name}`, 'info');
        break;
      case 'trade.accepted':
        this.toast(this.skin.label('offer_accepted', 'Your market offer was accepted'), 'good');
        break;
      case 'hero.fallen':
        this.toast(this.skin.label('hero_fallen', 'Your hero has fallen in battle and will return'), 'bad');
        break;
      case 'achievement.unlocked':
        this.toast(`🏆 ${d.name}: ${d.description}`, 'good');
        break;
      case 'great.contribution':
        this.toast(`${d.from.name} ${this.skin.label('contributed', 'contributed to your')} ${this.engine.building(d.building)?.name ?? d.building}`, 'good');
        break;
      case 'village.founded':
        this.toast(`${d.village.name} ${this.skin.label('founded_by', 'founded by the migrants of')} ${d.mother.name}`, 'good');
        void this.refreshMe();
        break;
      case 'village.submitted':
        this.toast(`${d.vassal.name} ${this.skin.label('submitted_to', 'submitted to')} ${d.overlord.name}: ${Math.round(d.tribute * 100)}% ${this.skin.label('tribute', 'tribute')}`, 'bad');
        break;
      case 'village.vassal_gained':
        this.toast(`${d.vassal.name} ${this.skin.label('submitted_to', 'submitted to')} ${d.overlord.name}`, 'good');
        break;
      case 'village.freed':
        this.toast(`${d.vassal.name} ${this.skin.label('is_free', 'is free again')}`, 'good');
        break;
      case 'village.vassal_lost':
        this.toast(`${d.vassal.name} ${this.skin.label('broke_free', 'no longer pays tribute')}`, 'bad');
        break;
      case 'movement.incoming':
        if (d.kind === 'attack' || d.kind === 'raid') {
          this.toast(`${this.skin.label('kind.' + d.kind)} ⟵ ${d.from.name} (${d.from.x}|${d.from.y})`, 'bad');
        } else {
          this.toast(`${this.skin.label('kind.reinforce')} ⟵ ${d.from.name}`, 'info');
        }
        break;
      case 'report.new':
        this.me.update((m) => m && { ...m, unread_reports: m.unread_reports + 1 });
        this.toast(d.title, 'info');
        break;
      case 'chat.rejected':
        this.toast(this.skin.label(`error.${d.error}`, d.error), 'bad');
        break;
      case 'omen.new':
        this.toast(`✶ ${d.village.name}: ${d.title}`, 'info');
        break;
      case 'medal.won':
        this.toast(`${['🥇', '🥈', '🥉'][d.rank - 1] ?? '🏅'} ${d.name}`, 'good');
        break;
      case 'road.built':
        this.toast(`${this.skin.label('road_built', 'The road is finished')}: ${d.a.name} ⟷ ${d.b.name}`, 'good');
        break;
      case 'government.settled':
        this.toast(this.skin.label('government_settled', 'Order is restored: the new government rules'), 'good');
        break;
    }
  }
}
