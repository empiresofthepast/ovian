import { Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../../core/api.service';
import { GameStore } from '../../core/game.store';
import { RealtimeService } from '../../core/realtime.service';
import { UI } from '../../shared/ui';

const CHANNELS = ['global', 'trade', 'help'];

@Component({
  selector: 'ov-chat',
  imports: [FormsModule, ...UI],
  template: `
    <div class="chat">
      <div class="tabs" role="tablist">
        @for (c of channels; track c) {
          <button role="tab" class="tabs__tab" [class.tabs__tab--active]="channel() === c" (click)="open(c)">#{{ 'chat.' + c | label: c }}</button>
        }
      </div>
      <div class="chat__log" #log aria-live="polite">
        @for (m of messages(); track m.id) {
          <div class="chat__msg" [class.chat__msg--me]="m.from.id === game.me()?.id">
            <span class="chat__time muted">{{ m.at | clock }}</span>
            <strong>{{ m.from.name }}</strong> {{ m.text }}
          </div>
        } @empty {<p class="muted small">No messages yet.</p>}
      </div>
      <form class="chat__form" (ngSubmit)="send()">
        <input name="text" [(ngModel)]="text" maxlength="500" autocomplete="off" [attr.aria-label]="'Message #' + channel()" />
        <button class="btn btn--primary btn--small" [disabled]="!text.trim()">Send</button>
      </form>
    </div>
  `,
})
export class ChatComponent {
  protected readonly game = inject(GameStore);
  private readonly api = inject(Api);
  private readonly realtime = inject(RealtimeService);
  private readonly log = viewChild<ElementRef<HTMLDivElement>>('log');
  protected readonly channels = CHANNELS;
  protected readonly channel = signal('global');
  protected readonly messages = computed(() => this.game.chat()[this.channel()] ?? []);
  private readonly loaded = new Set<string>();
  protected text = '';

  constructor() {
    void this.open('global');
    effect(() => {
      this.messages();
      queueMicrotask(() => {
        const el = this.log()?.nativeElement;
        if (el) el.scrollTop = el.scrollHeight;
      });
    });
  }

  protected async open(channel: string): Promise<void> {
    this.channel.set(channel);
    if (this.loaded.has(channel)) return;
    this.loaded.add(channel);
    const history = await this.api.chatHistory(channel).catch(() => []);
    this.game.chat.update((c) => {
      const seen = new Set((c[channel] ?? []).map((m) => m.id));
      return { ...c, [channel]: [...history.filter((m) => !seen.has(m.id)), ...(c[channel] ?? [])] };
    });
  }

  protected async send(): Promise<void> {
    const text = this.text.trim();
    if (!text) return;
    this.text = '';
    if (!this.realtime.postChat(this.channel(), text)) {
      try {
        const msg = await this.api.chatPost(this.channel(), text);
        this.game.chat.update((c) => ({ ...c, [msg.channel]: [...(c[msg.channel] ?? []), msg] }));
      } catch (e) {
        this.game.toast(this.game.errorText(e), 'bad');
      }
    }
  }
}
