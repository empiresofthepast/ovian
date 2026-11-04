import { DatePipe } from '@angular/common';
import { Component } from '@angular/core';
import { AssistantTokensBase } from '../../core/assistants';

/** Settings → AI assistants. */
@Component({
  selector: 'ov-assistants',
  imports: [DatePipe],
  template: `
    <section class="panel">
      <h2 class="panel__title">AI assistants</h2>
      <p class="small muted">Let Claude or another AI assistant run your cities through the Ovian MCP server. It can do what you can do here,
        except change your name or create tokens. Revoke a token to cut it off.</p>
      @if (fresh(); as f) {
        <div class="token-fresh">
          <p class="small"><strong>Copy this token now:</strong> it is not shown again.</p>
          <textarea class="token-box" readonly rows="2" (focus)="$any($event.target).select()">{{ f.token }}</textarea>
          <p class="small">Claude Code:</p>
          <textarea class="token-box" readonly rows="3" (focus)="$any($event.target).select()">{{ command(f.token!) }}</textarea>
          <p class="small">Other clients (Claude Desktop, Cursor, …):</p>
          <textarea class="token-box" readonly rows="7" (focus)="$any($event.target).select()">{{ json(f.token!) }}</textarea>
          <button class="btn" (click)="copy(command(f.token!))">Copy command</button>
          <button class="btn" (click)="fresh.set(null)">Done</button>
        </div>
      }
      <form class="row-form" (submit)="$event.preventDefault(); create()">
        <input name="tokenname" [value]="tokenName" (input)="tokenName = $any($event.target).value" maxlength="60" aria-label="Token name" placeholder="Name, e.g. Claude" />
        <button class="btn" [disabled]="busy">New access token</button>
      </form>
      @if (tokens().length) {
        <table class="table small">
          @for (t of tokens(); track t.id) {
            <tr><td><strong>{{ t.name }}</strong> <code>{{ t.prefix }}…</code></td>
              <td class="muted">created {{ t.created_at | date: 'd MMM' }}</td>
              <td class="muted">{{ t.last_used_at ? 'last used ' + (t.last_used_at | date: 'd MMM, HH:mm') : 'never used' }}</td>
              <td><button class="btn" (click)="revoke(t)">Revoke</button></td></tr>
          }
        </table>
      }
      <p class="small muted">Server: <code>{{ mcpUrl }}</code></p>
    </section>
  `,
})
export class AssistantsComponent extends AssistantTokensBase {}
