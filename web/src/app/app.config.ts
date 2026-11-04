import { ApplicationConfig, inject, provideAppInitializer, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { routes } from './app.routes';
import { CONFIG, RuntimeConfig } from './core/config';
import { GameStore } from './core/game.store';
import { Labels } from './core/labels';
import { SkinService } from './core/skin.service';

export function appConfig(config: RuntimeConfig): ApplicationConfig {
  return {
    providers: [
      provideBrowserGlobalErrorListeners(),
      { provide: CONFIG, useValue: config },
      { provide: Labels, useExisting: SkinService },
      provideRouter(routes, withComponentInputBinding()),
      provideAppInitializer(async () => {
        const skin = inject(SkinService);
        const game = inject(GameStore);
        await skin.init();
        try {
          await game.boot();
        } catch (e) {
          console.error('cannot reach the game server', e);
        }
      }),
    ],
  };
}
