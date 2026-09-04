import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService } from '../../core/services/pipeline.service';
import { TimeEstimate } from '../../core/models/pipeline.models';

@Component({
  selector: 'app-time-estimator',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Processing time & SLA analytics</h1>
          <p class="text-[13px] text-text-secondary">
            Predictive processing duration model based on file size, record volume, data quality anomalies, and historical throughput.
          </p>
        </div>

        <div class="flex items-center gap-2">
          <label class="text-[12px] text-text-secondary font-medium">Batch:</label>
          <select
            [ngModel]="selectedBatchId()"
            (ngModelChange)="onBatchChange($event)"
            class="bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono px-2.5 py-1.5 focus:border-border-strong focus:outline-none"
          >
            @for (b of batches(); track b.batch_id) {
              <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.total_records }} rows)</option>
            }
          </select>
        </div>
      </div>

      <!-- SLA Status & Headline ETA Card -->
      @if (estimate()) {
        <div class="bg-surface border border-border-default p-5 space-y-4">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border-default">
            <div>
              <div class="text-[11px] font-mono text-text-secondary mb-1">
                Batch processing forecast · {{ estimate()?.batch_id }}
              </div>
              <div class="flex items-baseline gap-3">
                <span class="text-[24px] font-mono font-semibold text-text-primary">
                  {{ estimate()?.total_estimated_seconds | number:'1.2-2' }}s
                </span>
                <span class="text-[13px] text-text-secondary font-mono">
                  (Estimated total runtime)
                </span>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <span class="text-[12px] text-text-secondary font-medium">SLA compliance:</span>
              @if (estimate()?.sla_status === 'ON_TRACK') {
                <span class="px-2 py-0.5 border border-status-green bg-[var(--status-green-bg)] text-status-green font-mono text-[12px] font-medium">
                  ON TRACK (&lt; 80% SLA)
                </span>
              } @else if (estimate()?.sla_status === 'AT_RISK') {
                <span class="px-2 py-0.5 border border-status-amber bg-[var(--status-amber-bg)] text-status-amber font-mono text-[12px] font-medium">
                  AT RISK (80–100% SLA)
                </span>
              } @else {
                <span class="px-2 py-0.5 border border-status-red bg-[var(--status-red-bg)] text-status-red font-mono text-[12px] font-medium">
                  BREACHED (&gt; 100% SLA)
                </span>
              }
            </div>
          </div>

          <!-- Key Metrics Grid -->
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[13px] font-mono">
            <div class="p-3 bg-surface-sunken border border-border-default">
              <span class="text-text-secondary block text-[11px]">Calculated ETA</span>
              <span class="text-text-primary font-semibold text-[14px]">{{ estimate()?.eta_timestamp }}</span>
            </div>
            <div class="p-3 bg-surface-sunken border border-border-default">
              <span class="text-text-secondary block text-[11px]">Throughput benchmark</span>
              <span class="text-status-green font-semibold text-[14px]">
                {{ estimate()?.throughput_records_per_sec | number:'1.0-0' }} rec/sec
              </span>
            </div>
            <div class="p-3 bg-surface-sunken border border-border-default">
              <span class="text-text-secondary block text-[11px]">Batch file size</span>
              <span class="text-text-primary font-semibold text-[14px]">
                {{ estimate()?.file_size_mb }} MB ({{ estimate()?.file_size_bytes | number }} B)
              </span>
            </div>
            <div class="p-3 bg-surface-sunken border border-border-default">
              <span class="text-text-secondary block text-[11px]">SLA target limit</span>
              <span class="text-text-primary font-semibold text-[14px]">
                {{ estimate()?.sla_target_seconds }}s (15 min)
              </span>
            </div>
          </div>
        </div>

        <!-- Component-Wise Duration Breakdown Table -->
        <div class="bg-surface border border-border-default">
          <div class="px-4 py-3 border-b border-border-default flex items-center justify-between">
            <h2 class="text-[15px] font-medium text-text-primary">Pipeline stage execution breakdown</h2>
            <span class="text-[12px] font-mono text-text-secondary">
              Predictive estimation factors
            </span>
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
              <tr class="even:bg-surface-sunken">
                <td class="py-2 px-3 text-text-primary font-medium">Stage 1: File ingestion & parsing</td>
                <td class="py-2 px-3 text-text-secondary">File size I/O ({{ estimate()?.file_size_mb }} MB)</td>
                <td class="py-2 px-3 text-right text-text-primary">{{ estimate()?.estimated_parse_time_sec | number:'1.3-3' }}s</td>
                <td class="py-2 px-3 text-right text-text-secondary">
                  {{ (estimate()!.estimated_parse_time_sec / max(0.01, estimate()!.total_estimated_seconds) * 100) | number:'1.1-1' }}%
                </td>
              </tr>
              <tr class="even:bg-surface-sunken">
                <td class="py-2 px-3 text-text-primary font-medium">Stage 2: Structural gatekeeper checks</td>
                <td class="py-2 px-3 text-text-secondary">Header, trailer, encoding checks</td>
                <td class="py-2 px-3 text-right text-text-primary">{{ estimate()?.estimated_gate_time_sec | number:'1.3-3' }}s</td>
                <td class="py-2 px-3 text-right text-text-secondary">
                  {{ (estimate()!.estimated_gate_time_sec / max(0.01, estimate()!.total_estimated_seconds) * 100) | number:'1.1-1' }}%
                </td>
              </tr>
              <tr class="even:bg-surface-sunken">
                <td class="py-2 px-3 text-text-primary font-medium">Stage 3: Cross-row rule validation</td>
                <td class="py-2 px-3 text-text-secondary">Record count ({{ estimate()?.total_records }} rows)</td>
                <td class="py-2 px-3 text-right text-text-primary">{{ estimate()?.estimated_rule_time_sec | number:'1.3-3' }}s</td>
                <td class="py-2 px-3 text-right text-text-secondary">
                  {{ (estimate()!.estimated_rule_time_sec / max(0.01, estimate()!.total_estimated_seconds) * 100) | number:'1.1-1' }}%
                </td>
              </tr>
              <tr class="even:bg-surface-sunken">
                <td class="py-2 px-3 text-text-primary font-medium">Stage 4-5: Anomaly scoring & triage</td>
                <td class="py-2 px-3 text-text-secondary">Anomaly volume ({{ estimate()?.anomaly_count }} items)</td>
                <td class="py-2 px-3 text-right" [ngClass]="estimate()!.estimated_anomaly_triage_sec > 1.0 ? 'text-status-amber font-semibold' : 'text-text-primary'">
                  {{ estimate()?.estimated_anomaly_triage_sec | number:'1.3-3' }}s
                </td>
                <td class="py-2 px-3 text-right text-text-secondary">
                  {{ (estimate()!.estimated_anomaly_triage_sec / max(0.01, estimate()!.total_estimated_seconds) * 100) | number:'1.1-1' }}%
                </td>
              </tr>
              <tr class="even:bg-surface-sunken">
                <td class="py-2 px-3 text-text-primary font-medium">Stage 6: Tiered GL reconciliation</td>
                <td class="py-2 px-3 text-text-secondary">Cache lookup (Tier 1–4 matches)</td>
                <td class="py-2 px-3 text-right text-text-primary">{{ estimate()?.estimated_gl_match_sec | number:'1.3-3' }}s</td>
                <td class="py-2 px-3 text-right text-text-secondary">
                  {{ (estimate()!.estimated_gl_match_sec / max(0.01, estimate()!.total_estimated_seconds) * 100) | number:'1.1-1' }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      } @else {
        <div class="p-8 bg-surface border border-border-default text-center text-text-secondary text-[12px]">
          Select a batch above to view detailed processing time analytics.
        </div>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimeEstimatorComponent implements OnInit {
  pipeline = inject(PipelineService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;
  estimate = signal<TimeEstimate | null>(null);

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        if (this.selectedBatchId()) {
          this.loadEstimate(this.selectedBatchId()!);
        }
      }
    });
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.loadEstimate(batchId);
  }

  loadEstimate(batchId: string) {
    this.pipeline.loadTimeEstimate(batchId).subscribe({
      next: (est) => this.estimate.set(est),
      error: () => this.estimate.set(null)
    });
  }

  max(a: number, b: number): number {
    return Math.max(a, b);
  }
}

