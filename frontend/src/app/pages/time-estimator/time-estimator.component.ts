import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService, describeHttpError } from '../../core/services/pipeline.service';
import { TimeEstimate } from '../../core/models/pipeline.models';
import { AsyncStateComponent } from '../../shared/components/async-state/async-state.component';

interface StageRow {
  label: string;
  driver: (e: TimeEstimate) => string;
  seconds: (e: TimeEstimate) => number;
  warnAbove?: number;
}

@Component({
  selector: 'app-time-estimator',
  standalone: true,
  imports: [CommonModule, FormsModule, AsyncStateComponent],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Processing time &amp; SLA analytics</h1>
          <p class="text-[13px] text-text-secondary">
            Predictive processing duration model based on file size, record volume, data quality anomalies
            and historical throughput.
          </p>
        </div>

        <div class="flex items-center gap-2">
          <label class="text-[12px] text-text-secondary font-medium">Batch:</label>
          @if (batches().length > 0) {
            <select
              [ngModel]="selectedBatchId()"
              (ngModelChange)="onBatchChange($event)"
              class="bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono px-2.5 py-1.5 focus:border-border-strong focus:outline-none"
            >
              @for (b of batches(); track b.batch_id) {
                <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.total_records }} rows)</option>
              }
            </select>
          } @else if (pipeline.overviewLoading()) {
            <span class="h-7 w-56 skeleton inline-block"></span>
          } @else {
            <span class="text-[12px] font-mono text-text-secondary">No batches available</span>
          }
        </div>
      </div>

      <app-async-state
        label="processing time estimate"
        skeleton="cards"
        [rows]="4"
        [loading]="loading()"
        [error]="error()"
        [empty]="!estimate()"
        emptyMessage="Select a batch above to view its processing time analytics."
        (retry)="reload()"
      >
        @if (estimate(); as est) {
          <!-- SLA Status & Headline ETA -->
          <div class="bg-surface border border-border-default p-5 space-y-4">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border-default">
              <div>
                <div class="text-[11px] font-mono text-text-secondary mb-1">
                  Batch processing forecast · {{ est.batch_id }}
                </div>
                <div class="flex items-baseline gap-3 flex-wrap">
                  <span class="text-[24px] font-mono font-semibold text-text-primary">
                    {{ est.total_estimated_seconds | number:'1.2-2' }}s
                  </span>
                  <span class="text-[13px] text-text-secondary font-mono">estimated total runtime</span>
                  @if (est.actual_duration_seconds != null) {
                    <span class="text-[13px] font-mono"
                          [ngClass]="est.actual_duration_seconds <= est.total_estimated_seconds ? 'text-status-green' : 'text-status-amber'">
                      · actual {{ est.actual_duration_seconds | number:'1.2-2' }}s
                    </span>
                  }
                </div>
              </div>

              <div class="flex items-center gap-2">
                <span class="text-[12px] text-text-secondary font-medium">SLA compliance:</span>
                @if (est.sla_status === 'ON_TRACK') {
                  <span class="px-2 py-0.5 border border-status-green bg-[var(--status-green-bg)] text-status-green font-mono text-[12px] font-medium">
                    ON TRACK
                  </span>
                } @else if (est.sla_status === 'AT_RISK') {
                  <span class="px-2 py-0.5 border border-status-amber bg-[var(--status-amber-bg)] text-status-amber font-mono text-[12px] font-medium">
                    AT RISK
                  </span>
                } @else {
                  <span class="px-2 py-0.5 border border-status-red bg-[var(--status-red-bg)] text-status-red font-mono text-[12px] font-medium">
                    BREACHED
                  </span>
                }
                <span class="text-[11px] font-mono text-text-secondary">
                  {{ slaConsumedPct(est) | number:'1.1-1' }}% of budget
                </span>
              </div>
            </div>

            <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[13px] font-mono">
              <div class="p-3 bg-surface-sunken border border-border-default">
                <span class="text-text-secondary block text-[11px]">Calculated ETA</span>
                <span class="text-text-primary font-semibold text-[14px]">{{ est.eta_timestamp }}</span>
              </div>
              <div class="p-3 bg-surface-sunken border border-border-default">
                <span class="text-text-secondary block text-[11px]">Throughput benchmark</span>
                <span class="text-status-green font-semibold text-[14px]">
                  {{ est.throughput_records_per_sec | number:'1.0-0' }} rec/sec
                </span>
              </div>
              <div class="p-3 bg-surface-sunken border border-border-default">
                <span class="text-text-secondary block text-[11px]">Batch file size</span>
                <span class="text-text-primary font-semibold text-[14px]">
                  {{ est.file_size_mb }} MB ({{ est.file_size_bytes | number }} B)
                </span>
              </div>
              <div class="p-3 bg-surface-sunken border border-border-default">
                <span class="text-text-secondary block text-[11px]">SLA target limit</span>
                <span class="text-text-primary font-semibold text-[14px]">
                  {{ est.sla_target_seconds | number:'1.0-0' }}s
                </span>
              </div>
            </div>
          </div>

          <!-- Component-Wise Duration Breakdown -->
          <div class="bg-surface border border-border-default mt-6">
            <div class="px-4 py-3 border-b border-border-default flex items-center justify-between">
              <h2 class="text-[15px] font-medium text-text-primary">Pipeline stage execution breakdown</h2>
              <span class="text-[12px] font-mono text-text-secondary">Predictive estimation factors</span>
            </div>

            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
                  <th class="py-2 px-3">Stage component</th>
                  <th class="py-2 px-3 font-mono">Driver factor</th>
                  <th class="py-2 px-3 text-right font-mono">Est. duration (sec)</th>
                  <th class="py-2 px-3 text-right font-mono">Share of total</th>
                </tr>
              </thead>
              <tbody class="text-[13px] font-mono divide-y divide-border-default">
                @for (row of stageRows; track row.label) {
                  <tr class="even:bg-surface-sunken">
                    <td class="py-2 px-3 text-text-primary font-medium">{{ row.label }}</td>
                    <td class="py-2 px-3 text-text-secondary">{{ row.driver(est) }}</td>
                    <td class="py-2 px-3 text-right"
                        [ngClass]="row.warnAbove && row.seconds(est) > row.warnAbove ? 'text-status-amber font-semibold' : 'text-text-primary'">
                      {{ row.seconds(est) | number:'1.3-3' }}s
                    </td>
                    <td class="py-2 px-3 text-right text-text-secondary">
                      {{ share(row.seconds(est), est) | number:'1.1-1' }}%
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </app-async-state>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimeEstimatorComponent implements OnInit {
  pipeline = inject(PipelineService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;

  estimate = signal<TimeEstimate | null>(null);
  loading = signal<boolean>(false);
  error = signal<string | null>(null);

  readonly stageRows: StageRow[] = [
    {
      label: 'Stage 1: File ingestion & parsing',
      driver: (e) => `File size I/O (${e.file_size_mb} MB)`,
      seconds: (e) => e.estimated_parse_time_sec,
    },
    {
      label: 'Stage 2: Structural gatekeeper checks',
      driver: () => 'Header, trailer, encoding checks',
      seconds: (e) => e.estimated_gate_time_sec,
    },
    {
      label: 'Stage 3: Cross-row rule validation',
      driver: (e) => `Record count (${e.total_records} rows)`,
      seconds: (e) => e.estimated_rule_time_sec,
    },
    {
      label: 'Stage 4-5: Anomaly scoring & triage',
      driver: (e) => `Anomaly volume (${e.anomaly_count} items)`,
      seconds: (e) => e.estimated_anomaly_triage_sec,
      warnAbove: 1.0,
    },
    {
      label: 'Stage 6: Tiered GL reconciliation',
      driver: () => 'Cache lookup (Tier 1–4 waterfall)',
      seconds: (e) => e.estimated_gl_match_sec,
    },
  ];

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        const id = this.selectedBatchId();
        if (id) this.loadEstimate(id);
      },
      error: () => {}
    });
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.loadEstimate(batchId);
  }

  reload() {
    const id = this.selectedBatchId();
    if (id) this.loadEstimate(id);
  }

  loadEstimate(batchId: string) {
    this.loading.set(true);
    this.error.set(null);

    this.pipeline.loadTimeEstimate(batchId).subscribe({
      next: (est) => {
        this.estimate.set(est);
        this.loading.set(false);
      },
      error: (err) => {
        this.estimate.set(null);
        this.error.set(describeHttpError(err));
        this.loading.set(false);
      }
    });
  }

  share(seconds: number, est: TimeEstimate): number {
    return (seconds / Math.max(0.01, est.total_estimated_seconds)) * 100;
  }

  slaConsumedPct(est: TimeEstimate): number {
    return (est.total_estimated_seconds / Math.max(1, est.sla_target_seconds)) * 100;
  }
}
