import { ApplicationConfig, inject, provideAppInitializer, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { CONFIG, RuntimeConfig } from '@core/config';
import { DEFAULT_LABELS } from '@core/defaults';
import { GameStore } from '@core/game.store';
import { Labels, PlainLabels } from '@core/labels';
import { routes } from './app.routes';
import { ArtService } from './art/art.service';

const LABELS: Record<string, string> = {
  ...DEFAULT_LABELS,
  'error.network': 'The game server cannot be reached.',
};

export function appConfig(config: RuntimeConfig): ApplicationConfig {
  return {
    providers: [
      provideBrowserGlobalErrorListeners(),
      { provide: CONFIG, useValue: config },
      { provide: Labels, useValue: new PlainLabels(LABELS) },
      provideRouter(routes, withComponentInputBinding()),
      provideAppInitializer(async () => {
        const art = inject(ArtService);
        const game = inject(GameStore);
        await Promise.all([
          art.init(),
          game.boot().catch((e) => console.error('cannot reach the game server', e)),
        ]);
      }),
    ],
  };
}
