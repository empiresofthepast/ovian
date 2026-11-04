import { Directive, inject, signal } from '@angular/core';
import { Api } from './api.service';
import { CONFIG } from './config';
import { GameStore } from './game.store';
import { AccessToken } from './models';

/** Settings → AI assistants: personal access tokens for the MCP server. Each client adds its own template. */
@Directive()
export abstract class AssistantTokensBase {
  protected readonly api = inject(Api);
  protected readonly game = inject(GameStore);
  protected readonly mcpUrl = inject(CONFIG).mcpUrl ?? '';
  protected readonly tokens = signal<AccessToken[]>([]);
  /** The token just created: shown once, with the setup command. */
  protected readonly fresh = signal<AccessToken | null>(null);
  protected tokenName = 'Claude';
  protected busy = false;

  constructor() {
    void this.load();
  }

  protected async load(): Promise<void> {
    try {
      this.tokens.set(await this.api.tokens());
    } catch {
      this.tokens.set([]);
    }
  }

  protected command(token: string): string {
    return `claude mcp add --transport http ovian ${this.mcpUrl} --header "Authorization: Bearer ${token}"`;
  }

  protected json(token: string): string {
    return JSON.stringify({ mcpServers: { ovian: { type: 'http', url: this.mcpUrl, headers: { Authorization: `Bearer ${token}` } } } }, null, 2);
  }

  protected async create(): Promise<void> {
    this.busy = true;
    try {
      this.fresh.set(await this.api.createToken(this.tokenName.trim() || 'Assistant'));
      await this.load();
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    } finally {
      this.busy = false;
    }
  }

  protected async revoke(t: AccessToken): Promise<void> {
    try {
      await this.api.revokeToken(t.id);
      if (this.fresh()?.id === t.id) this.fresh.set(null);
      await this.load();
      this.game.toast(`Token “${t.name}” revoked`, 'info');
    } catch (e) {
      this.game.toast(this.game.errorText(e), 'bad');
    }
  }

  protected async copy(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.game.toast('Copied', 'good');
    } catch {
      this.game.toast('Select the text and copy it by hand', 'info');
    }
  }
}
