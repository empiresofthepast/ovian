import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Api } from '../../core/api.service';
import { InfraView } from '../../core/models';
import { UI } from '../../shared/ui';

const EVERY_MS = 5000;
const KEEP = 120; // ten minutes of samples

interface Sample { at: number; cpu: number; mem: number; hostCpu: number | null }

/** How much the infrastructure weighs: CPU and memory of the stack's containers and of the host (superusers). */
@Component({
  selector: 'ov-infra',
  imports: [DecimalPipe, ...UI],
  template: `
    <div class="page-head">
      <h1 class="page-title">{{ 'nav.infra' | label: 'Infrastructure' }}</h1>
      <label class="small muted"><input type="checkbox" [checked]="live()" (change)="live.set(!live())" /> live, every {{ every / 1000 }} s</label>
    </div>
    @if (error()) {<p class="bad">{{ error() }}</p>}
    @if (data(); as d) {
      <div class="infra-totals">
        <div class="panel">
          <span class="muted small">Ovian · CPU</span>
          <strong>{{ d.totals.cpu_percent | number: '1.0-1' }}%</strong>
          <span class="muted small">of one core @if (d.host) {· {{ d.totals.cpu_percent / d.host.cpus | number: '1.0-2' }}% of the machine}</span>
          <svg class="spark" viewBox="0 0 120 30" preserveAspectRatio="none"><polyline [attr.points]="line('cpu')" /></svg>
        </div>
        <div class="panel">
          <span class="muted small">Ovian · memory</span>
          <strong>{{ mib(d.totals.mem_used) }}</strong>
          <span class="muted small">@if (d.host) { {{ 100 * d.totals.mem_used / d.host.mem_total | number: '1.0-2' }}% of the machine's RAM }</span>
          <svg class="spark" viewBox="0 0 120 30" preserveAspectRatio="none"><polyline [attr.points]="line('mem')" /></svg>
        </div>
        @if (d.host; as h) {
          <div class="panel">
            <span class="muted small">Whole machine · CPU ({{ h.cpus }} cores)</span>
            <strong>{{ h.cpu_percent | number: '1.0-1' }}%</strong>
            <span class="muted small">every service on it, not only Ovian</span>
            <svg class="spark" viewBox="0 0 120 30" preserveAspectRatio="none"><polyline [attr.points]="line('hostCpu')" /></svg>
          </div>
          <div class="panel">
            <span class="muted small">Whole machine · memory</span>
            <strong>{{ gib(h.mem_used) }} / {{ gib(h.mem_total) }}</strong>
            <span class="muted small">{{ gib(h.mem_available) }} available</span>
            <div class="bar"><div class="bar__fill" [style.width.%]="100 * h.mem_used / h.mem_total"></div></div>
          </div>
        }
      </div>

      <section class="panel">
        <h2 class="panel__title">Containers <span class="muted small">{{ d.totals.running }} of {{ d.totals.containers }} running · CPU in % of one core</span></h2>
        <div class="table-wrap">
          <table class="table infra-table">
            <thead><tr><th>Service</th><th>State</th><th class="num">CPU</th><th></th><th class="num">Memory</th><th></th><th class="num">Processes</th></tr></thead>
            <tbody>
              @for (c of d.containers; track c.name) {
                <tr>
                  <td><strong>{{ c.service ?? c.name }}</strong><div class="muted small">{{ c.image }}</div></td>
                  <td class="small" [class.bad]="c.state !== 'running'">{{ c.status }}</td>
                  <td class="num">{{ c.cpu_percent | number: '1.1-1' }}%</td>
                  <td class="infra-bar"><div class="bar"><div class="bar__fill" [style.width.%]="share(c.cpu_percent, maxCpu())"></div></div></td>
                  <td class="num">{{ mib(c.mem_used) }}</td>
                  <td class="infra-bar"><div class="bar"><div class="bar__fill" [style.width.%]="share(c.mem_used, maxMem())"></div></div></td>
                  <td class="num">{{ c.pids ?? '—' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <p class="small muted">Read {{ ago(d.at) }}. Memory leaves out the page cache, like <code>docker stats</code>. The sparklines keep the last ten minutes while this page is open.</p>
      </section>
    } @else if (!error()) {
      <p class="muted">Reading the containers…</p>
    }
  `,
  styles: [`
    .infra-totals { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: .75rem; margin-bottom: 1rem; }
    .infra-totals .panel { display: flex; flex-direction: column; gap: .2rem; margin: 0; }
    .infra-totals strong { font-size: 1.6rem; }
    .spark { width: 100%; height: 2rem; margin-top: .25rem; }
    .spark polyline { fill: none; stroke: currentColor; stroke-width: 1.5; vector-effect: non-scaling-stroke; opacity: .7; }
    .table-wrap { overflow-x: auto; }
    .infra-table { width: 100%; }
    .infra-table .num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
    .infra-bar { width: 18%; min-width: 4rem; }
    .bar { height: .45rem; border-radius: 1rem; background: var(--border); overflow: hidden; margin-top: .3rem; }
    .bar__fill { height: 100%; background: var(--accent); border-radius: 1rem; }
  `],
})
export class InfraComponent implements OnInit, OnDestroy {
  private readonly api = inject(Api);
  protected readonly every = EVERY_MS;
  protected readonly data = signal<InfraView | null>(null);
  protected readonly error = signal('');
  protected readonly live = signal(true);
  protected readonly samples = signal<Sample[]>([]);
  protected readonly maxCpu = computed(() => Math.max(1, ...(this.data()?.containers ?? []).map((c) => c.cpu_percent)));
  protected readonly maxMem = computed(() => Math.max(1, ...(this.data()?.containers ?? []).map((c) => c.mem_used)));
  private timer: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    void this.load();
    this.timer = setInterval(() => { if (this.live()) void this.load(); }, EVERY_MS);
  }

  ngOnDestroy(): void {
    if (this.timer) clearInterval(this.timer);
  }

  async load(): Promise<void> {
    try {
      const d = await this.api.adminInfra();
      this.data.set(d);
      this.error.set('');
      this.samples.update((s) => [...s, { at: d.at, cpu: d.totals.cpu_percent, mem: d.totals.mem_used, hostCpu: d.host?.cpu_percent ?? null }].slice(-KEEP));
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected line(key: 'cpu' | 'mem' | 'hostCpu'): string {
    const s = this.samples().filter((x) => x[key] !== null);
    if (s.length < 2) return '';
    const vals = s.map((x) => x[key] as number);
    const max = Math.max(...vals) || 1;
    const min = key === 'mem' ? Math.min(...vals) * 0.98 : 0;
    return vals.map((v, i) => `${(i / (vals.length - 1)) * 120},${30 - ((v - min) / (max - min || 1)) * 28 - 1}`).join(' ');
  }

  protected share(v: number, max: number): number {
    return Math.min(100, (100 * v) / max);
  }

  protected mib(bytes: number): string {
    return bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GiB` : `${Math.round(bytes / 1024 ** 2)} MiB`;
  }

  protected gib(bytes: number): string {
    return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
  }

  protected ago(at: number): string {
    const s = Math.max(0, Math.round((Date.now() - at) / 1000));
    return s < 2 ? 'just now' : `${s} s ago`;
  }
}
