import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService } from '../../core/services/pipeline.service';
import { ToastService } from '../../core/services/toast.service';
import { AnomalyItem, BatchRecord } from '../../core/models/pipeline.models';

@Component({
  selector: 'app-anomaly-queue',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Anomaly & escalation queue</h1>
          <p class="text-[13px] text-text-secondary">
            Agentic detection of data anomalies, automated remediation audit logs, and human-in-the-loop review queue.
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
              <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.stage }})</option>
            }
          </select>
        </div>
      </div>

      <!-- Severity & Triage Summary Strip -->
      <div class="bg-surface border border-border-default p-4">
        <div class="text-[12px] font-mono text-text-secondary mb-2">
          Anomaly triage overview · Batch: {{ selectedBatchId() }}
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[13px] font-mono">
          <div>
            <span class="text-text-secondary block text-[11px]">Total anomalies</span>
            <span class="text-text-primary font-semibold text-[16px]">{{ anomalies().length }}</span>
          </div>
          <div>
            <span class="text-text-secondary block text-[11px]">Auto-remediated (re-validated)</span>
            <span class="text-status-green font-semibold text-[16px]">{{ autoRemediatedCount() }}</span>
          </div>
          <div>
            <span class="text-text-secondary block text-[11px]">Pending human review</span>
            <span class="text-status-amber font-semibold text-[16px]">{{ pendingEscalatedCount() }}</span>
          </div>
          <div>
            <span class="text-text-secondary block text-[11px]">Quarantined rows</span>
            <span class="text-status-red font-semibold text-[16px]">{{ quarantinedCount() }}</span>
          </div>
        </div>
      </div>

      <!-- Human Escalation Queue (Active Reviews) -->
      @if (pendingEscalatedCount() > 0) {
        <div class="bg-surface border border-status-amber p-5 space-y-4">
          <div class="flex items-center justify-between border-b border-border-default pb-3">
            <div>
              <h2 class="text-[15px] font-medium text-status-amber flex items-center gap-2">
                <span>Human review queue</span>
                <span class="text-[11px] font-mono text-text-primary px-1.5 py-0.2 bg-surface-sunken border border-border-default">
                  {{ pendingEscalatedCount() }} items
                </span>
              </h2>
              <p class="text-[12px] text-text-secondary mt-0.5">
                Financial, duplicate, or referential anomalies requiring analyst authorization before GL matching.
              </p>
            </div>
          </div>

          <div class="space-y-3">
            @for (item of pendingEscalated(); track item.id) {
              <div class="p-3.5 bg-surface-sunken border border-border-default space-y-2">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between text-[12px] font-mono gap-2">
                  <div class="flex items-center gap-2">
                    <span class="px-1.5 py-0.2 text-[10px] border border-status-amber text-status-amber font-semibold">
                      {{ item.severity }}
                    </span>
                    <span class="text-text-primary font-semibold">Row #{{ item.row_index }}</span>
                    <span class="text-text-secondary">· Txn ID: <strong class="text-accent-action">{{ item.external_txn_id }}</strong></span>
                    <span class="text-text-secondary">· Account: {{ item.account }}</span>
                    <span class="text-text-secondary">· Amount: {{ item.raw_amount || 'N/A' }}</span>
                  </div>

                  <span class="text-text-secondary text-[11px]">
                    Confidence: <strong class="text-status-green">{{ (item.confidence_score * 100) | number:'1.0-0' }}%</strong>
                  </span>
                </div>

                <div class="text-[12px] text-text-primary">
                  <span class="text-status-red font-mono font-medium">[{{ item.error_type }}]</span>
                  <span class="ml-1.5">{{ item.description }}</span>
                </div>

                <!-- Suggested Remediation Box -->
                @if (item.suggested_fix) {
                  <div class="p-2.5 bg-surface border border-border-default text-[12px] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div class="font-mono text-[11px] text-text-secondary">
                      Suggested Fix: <code class="text-status-green font-semibold">{{ item.suggested_fix | json }}</code>
                    </div>

                    <div class="flex items-center gap-2">
                      <button
                        (click)="resolveItem(item.id, 'APPROVE')"
                        class="bg-status-green hover:opacity-90 text-white text-[11px] font-medium px-2.5 py-1 transition-colors"
                      >
                        Approve fix
                      </button>

                      <button
                        (click)="resolveItem(item.id, 'QUARANTINE')"
                        class="bg-surface hover:bg-surface-sunken text-status-red text-[11px] font-medium px-2.5 py-1 border border-border-default transition-colors"
                      >
                        Quarantine row
                      </button>
                    </div>
                  </div>
                }
              </div>
            }
          </div>
        </div>
      }

      <!-- Complete Anomalies & Auto-Remediation Ledger Table -->
      <div class="bg-surface border border-border-default">
        <div class="px-4 py-3 border-b border-border-default flex items-center justify-between">
          <h2 class="text-[15px] font-medium text-text-primary">All detected data anomalies & remediation log</h2>
          <span class="text-[12px] font-mono text-text-secondary">
            {{ anomalies().length }} entries
          </span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
                <th class="py-2 px-3 font-mono">Row</th>
                <th class="py-2 px-3 font-mono">Txn ID</th>
                <th class="py-2 px-3">Error type</th>
                <th class="py-2 px-3 text-center">Severity</th>
                <th class="py-2 px-3 font-mono">Category</th>
                <th class="py-2 px-3">Remediation detail</th>
                <th class="py-2 px-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody class="text-[12px] font-mono divide-y divide-border-default">
              @for (item of anomalies(); track item.id) {
                <tr class="even:bg-surface-sunken hover:bg-surface-sunken/60 transition-colors">
                  <td class="py-2 px-3 text-text-secondary">#{{ item.row_index }}</td>
                  <td class="py-2 px-3 text-accent-action font-medium">{{ item.external_txn_id }}</td>
                  <td class="py-2 px-3 text-text-primary">{{ item.error_type }}</td>
                  <td class="py-2 px-3 text-center">
                    <span class="px-1.5 py-0.2 text-[10px] border"
                          [ngClass]="severityClass(item.severity)">
                      {{ item.severity }}
                    </span>
                  </td>
                  <td class="py-2 px-3 text-text-secondary">{{ item.category }}</td>
                  <td class="py-2 px-3 text-text-primary">
                    {{ item.remediation_notes || item.description }}
                  </td>
                  <td class="py-2 px-3 text-center">
                    @if (item.status === 'AUTO_REMEDIATED') {
                      <span class="text-[10px] text-status-green px-1.5 py-px border border-status-green">AUTO-FIXED</span>
                    } @else if (item.status === 'HUMAN_RESOLVED') {
                      <span class="text-[10px] text-accent-action px-1.5 py-px border border-accent-action">RESOLVED</span>
                    } @else if (item.status === 'ESCALATED') {
                      <span class="text-[10px] text-status-amber px-1.5 py-px border border-status-amber">PENDING</span>
                    } @else {
                      <span class="text-[10px] text-status-red px-1.5 py-px border border-status-red">QUARANTINED</span>
                    }
                  </td>
                </tr>
              } @empty {
                <tr>
                  <td colspan="7" class="py-8 text-center text-text-secondary text-[12px]">
                    No anomalies detected for the active batch.
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnomalyQueueComponent implements OnInit {
  pipeline = inject(PipelineService);
  toast = inject(ToastService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;
  anomalies = this.pipeline.currentAnomalies;

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        if (this.selectedBatchId()) {
          this.pipeline.loadBatchAnomalies(this.selectedBatchId()!).subscribe();
        }
      }
    });
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
  }

  autoRemediatedCount(): number {
    return this.anomalies().filter(a => a.status === 'AUTO_REMEDIATED').length;
  }

  pendingEscalatedCount(): number {
    return this.pendingEscalated().length;
  }

  pendingEscalated(): AnomalyItem[] {
    return this.anomalies().filter(a => a.status === 'ESCALATED');
  }

  quarantinedCount(): number {
    return this.anomalies().filter(a => a.status === 'QUARANTINED').length;
  }

  resolveItem(anomalyId: string, action: 'APPROVE' | 'QUARANTINE') {
    const batchId = this.selectedBatchId();
    if (!batchId) return;

    this.pipeline.resolveEscalation(batchId, anomalyId, { action }).subscribe({
      next: (b) => {
        this.toast.success(
          'Resolution Applied',
          `Row ${action === 'APPROVE' ? 're-validated and approved' : 'quarantined'}. Batch status: ${b.stage}`
        );
      },
      error: (err) => {
        this.toast.error('Resolution Failed', err?.error?.detail || 'Could not resolve escalation.');
      }
    });
  }

  severityClass(sev: string): string {
    switch (sev) {
      case 'CRITICAL':
        return 'bg-[var(--status-red-bg)] text-status-red border-status-red';
      case 'HIGH':
        return 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber';
      case 'MEDIUM':
        return 'bg-surface-sunken text-tier-2 border-border-default';
      default:
        return 'bg-surface-sunken text-text-secondary border-border-default';
    }
  }
}

