import { bootstrapApplication } from '@angular/platform-browser';
import { loadConfig } from '@core/config';
import { App } from './app/app';
import { appConfig } from './app/app.config';

loadConfig()
  .then((config) => bootstrapApplication(App, appConfig(config)))
  .catch((err) => console.error(err));
