import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { GameStore } from './core/game.store';
import { Hub } from './core/hub';
import { FEATURES } from './features';
import { WorldsComponent } from './features/hub/worlds.component';
import { LoginComponent } from './features/login/login.component';
import { ShellComponent } from './shell/shell.component';

const signedIn = () => inject(GameStore).loggedIn() || inject(Router).createUrlTree(['/login']);
const signedOut = () => !inject(GameStore).loggedIn() || inject(Router).createUrlTree(['/village']);
/** With a hub, players sign in there and pick a world. */
const worldLogin = () => !inject(Hub).enabled || inject(Router).createUrlTree(['/worlds']);
const hubOnly = () => inject(Hub).enabled || inject(Router).createUrlTree(['/login']);

export const routes: Routes = [
  { path: 'login', component: LoginComponent, canActivate: [signedOut, worldLogin] },
  { path: 'worlds', component: WorldsComponent, canActivate: [hubOnly] },
  {
    path: '',
    component: ShellComponent,
    canActivate: [signedIn],
    children: [
      ...FEATURES.map((f) => ({ path: f.path, loadComponent: f.load })),
      { path: 'reports/:id', loadComponent: FEATURES.find((f) => f.id === 'reports')!.load },
      { path: '', pathMatch: 'full' as const, redirectTo: 'village' },
    ],
  },
  { path: '**', redirectTo: '' },
];
