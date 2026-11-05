import { Type } from '@angular/core';

/**
 * The client's feature registry. Routes and navigation are generated from
 * this list, so adding a screen is one entry here. Skins can hide entries
 * (skin.json layout.hide) and rename them (labels "nav.<id>").
 */
export interface Feature {
  id: string;
  path: string;
  load: () => Promise<Type<unknown>>;
  /** Show in the main navigation. */
  nav: boolean;
  /** Only superusers see it. */
  admin?: boolean;
  /** Only when the site has a hub (one account for many worlds). */
  hub?: boolean;
  /** Only hub administrators see it. */
  hubAdmin?: boolean;
}

export const FEATURES: Feature[] = [
  { id: 'village', path: 'village', nav: true, load: () => import('./features/village/village.component').then((m) => m.VillageComponent) },
  { id: 'map', path: 'map', nav: true, load: () => import('./features/map/map.component').then((m) => m.MapComponent) },
  { id: 'rally', path: 'rally', nav: true, load: () => import('./features/rally/rally.component').then((m) => m.RallyComponent) },
  { id: 'reports', path: 'reports', nav: true, load: () => import('./features/reports/reports.component').then((m) => m.ReportsComponent) },
  { id: 'rankings', path: 'rankings', nav: true, load: () => import('./features/rankings/rankings.component').then((m) => m.RankingsComponent) },
  { id: 'realm', path: 'realm', nav: true, load: () => import('./features/realm/realm.component').then((m) => m.RealmComponent) },
  { id: 'festival', path: 'festival', nav: true, load: () => import('./features/festival/festival.component').then((m) => m.FestivalComponent) },
  { id: 'chronicle', path: 'chronicle', nav: true, load: () => import('./features/chronicle/chronicle.component').then((m) => m.ChronicleComponent) },
  { id: 'governors', path: 'governors', nav: true, load: () => import('./features/governors/governors.component').then((m) => m.GovernorsComponent) },
  { id: 'admin', path: 'admin', nav: true, admin: true, load: () => import('./features/admin/admin.component').then((m) => m.AdminComponent) },
  { id: 'infra', path: 'infra', nav: true, admin: true, load: () => import('./features/admin/infra.component').then((m) => m.InfraComponent) },
  { id: 'account', path: 'account', nav: true, hub: true, load: () => import('./features/hub/account.component').then((m) => m.AccountComponent) },
  { id: 'hub-admin', path: 'hub-admin', nav: true, hubAdmin: true, load: () => import('./features/hub/hub-admin.component').then((m) => m.HubAdminComponent) },
  { id: 'settings', path: 'settings', nav: true, load: () => import('./features/settings/settings.component').then((m) => m.SettingsComponent) },
];
