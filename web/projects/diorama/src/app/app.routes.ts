import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { GameStore } from '@core/game.store';
import { Hub } from '@core/hub';

const signedIn = () => inject(GameStore).loggedIn() || inject(Router).parseUrl('/welcome');
const signedOut = () => !inject(GameStore).loggedIn() || inject(Router).parseUrl('/');
/** With a hub, the welcome page is the hub's: sign in, then choose a world. */
const worldOnly = () => !inject(Hub).enabled || inject(Router).parseUrl('/worlds');
const withHub = () => inject(Hub).enabled || inject(Router).parseUrl('/welcome');

/** The village (3D scene + HUD) is the shell; other screens open over it as child routes. */
export const routes: Routes = [
  { path: 'welcome', canActivate: [signedOut, worldOnly], loadComponent: () => import('./login/login.component').then((m) => m.LoginComponent) },
  { path: 'worlds', title: 'Worlds', canActivate: [withHub], loadComponent: () => import('./hub/worlds.component').then((m) => m.WorldsComponent) },
  {
    path: '',
    canActivate: [signedIn],
    loadComponent: () => import('./village/village.component').then((m) => m.VillageComponent),
    children: [
      { path: '', children: [] },
      { path: 'map', title: 'Map', loadComponent: () => import('./screens/map.component').then((m) => m.MapComponent) },
      { path: 'rally', title: 'Rally point', loadComponent: () => import('./screens/rally.component').then((m) => m.RallyComponent) },
      { path: 'rankings', title: 'Rankings', loadComponent: () => import('./screens/rankings.component').then((m) => m.RankingsComponent) },
      { path: 'settings', title: 'Settings', loadComponent: () => import('./screens/settings.component').then((m) => m.SettingsComponent) },
      { path: 'market', title: 'Market', loadComponent: () => import('./screens/market.component').then((m) => m.MarketComponent) },
      { path: 'alliance', title: 'Alliance', loadComponent: () => import('./screens/alliance.component').then((m) => m.AllianceComponent) },
      { path: 'hero', title: 'Hero', loadComponent: () => import('./screens/hero.component').then((m) => m.HeroComponent) },
      { path: 'quests', title: 'Quests', loadComponent: () => import('./screens/quests.component').then((m) => m.QuestsComponent) },
      { path: 'realm', title: 'Realm', loadComponent: () => import('./screens/realm.component').then((m) => m.RealmComponent) },
      { path: 'governors', title: 'Governors', loadComponent: () => import('./screens/governors.component').then((m) => m.GovernorsComponent) },
      { path: 'finds', title: 'Finds', loadComponent: () => import('./screens/finds.component').then((m) => m.FindsComponent) },
      { path: 'year', title: 'Year and games', loadComponent: () => import('./screens/festival.component').then((m) => m.FestivalComponent) },
      { path: 'chronicle', title: 'Chronicle', loadComponent: () => import('./screens/chronicle.component').then((m) => m.ChronicleComponent) },
      { path: 'admin', title: 'Admin', loadComponent: () => import('./screens/admin.component').then((m) => m.AdminComponent) },
      { path: 'hub-admin', title: 'Hub administration', canActivate: [withHub], loadComponent: () => import('./hub/hub-admin.component').then((m) => m.HubAdminComponent) },
      { path: 'reports', title: 'Reports', loadComponent: () => import('./village/reports.component').then((m) => m.ReportsComponent) },
    ],
  },
  { path: '**', redirectTo: '' },
];
