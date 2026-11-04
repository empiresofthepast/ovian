import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { GameStore } from './core/game.store';
import { FEATURES } from './features';
import { LoginComponent } from './features/login/login.component';
import { ShellComponent } from './shell/shell.component';

const signedIn = () => inject(GameStore).loggedIn() || inject(Router).createUrlTree(['/login']);
const signedOut = () => !inject(GameStore).loggedIn() || inject(Router).createUrlTree(['/village']);

export const routes: Routes = [
  { path: 'login', component: LoginComponent, canActivate: [signedOut] },
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
