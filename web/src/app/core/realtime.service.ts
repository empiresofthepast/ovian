import { Injectable, inject, signal } from '@angular/core';
import type { MqttClient } from 'mqtt';
import { Subject } from 'rxjs';
import { CONFIG } from './config';
import { GameEvent } from './models';

export type RealtimeStatus = 'offline' | 'connecting' | 'online';

export interface RealtimeMessage {
  topic: string;
  /** Topic relative to the world root, e.g. "player/3/events" or "chat/global". */
  path: string;
  event: GameEvent;
}

/**
 * MQTT over WebSocket. Username is the player id, password the API token.
 * The broker only allows our own private topic, the map, chat channels and
 * posting chat to our own inbox.
 */
@Injectable({ providedIn: 'root' })
export class RealtimeService {
  private readonly url = inject(CONFIG).mqttUrl;
  private client: MqttClient | null = null;
  private root = '';
  private playerId = 0;
  readonly status = signal<RealtimeStatus>('offline');
  readonly messages = new Subject<RealtimeMessage>();

  async connect(token: string, playerId: number, topicRoot: string): Promise<void> {
    this.disconnect();
    this.root = topicRoot;
    this.playerId = playerId;
    this.status.set('connecting');
    // Loaded on demand: mqtt.js is the largest dependency and is not needed on the login page.
    const { default: mqtt } = await import('mqtt');
    const client = mqtt.connect(this.url, {
      username: String(playerId),
      password: token,
      clientId: `web-${playerId}-${Math.random().toString(16).slice(2, 10)}`,
      reconnectPeriod: 3000,
      connectTimeout: 10_000,
      clean: true,
    });
    client.on('connect', () => {
      this.status.set('online');
      client.subscribe([`${this.root}/player/${playerId}/events`, `${this.root}/map`, `${this.root}/chat/+`, `${this.root}/server`], { qos: 1 });
    });
    client.on('reconnect', () => this.status.set('connecting'));
    client.on('close', () => this.status.set('offline'));
    client.on('error', (e) => console.warn('mqtt', e.message));
    client.on('message', (topic, payload) => {
      try {
        const event = JSON.parse(new TextDecoder().decode(payload)) as GameEvent;
        this.messages.next({ topic, path: topic.slice(this.root.length + 1), event });
      } catch {
        // ignore malformed payloads
      }
    });
    this.client = client;
  }

  disconnect(): void {
    this.client?.end(true);
    this.client = null;
    this.status.set('offline');
  }

  /** Post chat through the broker. Returns false when offline so callers can fall back to REST. */
  postChat(channel: string, text: string): boolean {
    if (!this.client || this.status() !== 'online') return false;
    this.client.publish(`${this.root}/chat/${channel}/in/${this.playerId}`, JSON.stringify({ text }), { qos: 1 });
    return true;
  }
}
