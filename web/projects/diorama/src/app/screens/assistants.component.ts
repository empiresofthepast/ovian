import { DatePipe } from '@angular/common';
import { Component } from '@angular/core';
import { AssistantTokensBase } from '@core/assistants';
import { UI } from '../ui';

/** Settings → AI assistants. */
@Component({
  selector: 'dio-assistants',
  imports: [DatePipe, ...UI],
  template: `
    <h3 class="subhead">AI assistants</h3>
    <p class="small muted">Let Claude or another AI assistant run your cities through the Ovian MCP server. It can do what you can do from here,
      except change your name or create tokens. Revoke a token to cut it off.</p>
    @if (fresh(); as f) {
      <div class="token-fresh">
        <p class="small"><strong>Copy this token now:</strong> it is not shown again.</p>
        <textarea class="token-box" readonly rows="2" (focus)="$any($event.target).select()">{{ f.token }}</textarea>
        <p class="small">Claude Code:</p>
        <textarea class="token-box" readonly rows="3" (focus)="$any($event.target).select()">{{ command(f.token!) }}</textarea>
        <p class="small">Other clients (Claude Desktop, Cursor, …):</p>
        <textarea class="token-box" readonly rows="7" (focus)="$any($event.target).select()">{{ json(f.token!) }}</textarea>
        <div class="btn-row">
          <button class="btn btn--small" (click)="copy(command(f.token!))">Copy command</button>
          <button class="btn btn--ghost btn--small" (click)="fresh.set(null)">Done</button>
        </div>
      </div>
    }
    <form class="row-form" (submit)="$event.preventDefault(); create()">
      <input name="tokenname" [value]="tokenName" (input)="tokenName = $any($event.target).value" maxlength="60" aria-label="Token name" placeholder="Name, e.g. Claude" />
      <button class="btn btn--small" [disabled]="busy">New access token</button>
    </form>
    @for (t of tokens(); track t.id) {
      <div class="token-row small">
        <span class="grow"><strong>{{ t.name }}</strong> <code>{{ t.prefix }}…</code><br />
          <span class="muted">created {{ t.created_at | date: 'd MMM' }} · {{ t.last_used_at ? 'last used ' + (t.last_used_at | date: 'd MMM, HH:mm') : 'never used' }}</span></span>
        <button class="btn btn--ghost btn--small" (click)="revoke(t)">Revoke</button>
      </div>
    }
    <p class="small muted">Server: <code>{{ mcpUrl }}</code></p>
  `,
})
export class AssistantsComponent extends AssistantTokensBase {}
