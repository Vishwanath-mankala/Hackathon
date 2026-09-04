import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService } from '../../core/services/pipeline.service';
import { ToastService } from '../../core/services/toast.service';
import { StructuralGateDetails, BatchRecord } from '../../core/models/pipeline.models';

@Component({
  selector: 'app-structural-gate',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Structural integrity gate</h1>
          <p class="text-[13px] text-text-secondary">
            File-level hard gatekeeper. Verifies encoding, canonical columns, trailer row counts, and control totals before any transaction reaches the rule engine.
          </p>
        </div>

        <button
          (click)="triggerSftpSimulation()"
          [disabled]="loading()"
          class="bg-surface hover:bg-surface-sunken text-text-primary text-[13px] font-medium px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>
            <line x1="12" x2="12" y1="15" y2="3"/>
          </svg>
          <span>Simulate SFTP intake</span>
        </button>
      </div>

      <!-- Ingestion & Upload Container -->
      <div class="bg-surface border border-border-default p-5 space-y-4">
        <h2 class="text-[15px] font-medium text-text-primary">Ingest full bank statement (no splitting)</h2>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <!-- File selection -->
          <div>
            <label class="block text-[12px] text-text-secondary font-medium mb-1">
              Statement file (CSV, MT940, BAI2)
            </label>
            <input
              type="file"
              accept=".csv,.txt"
              (change)="onFileSelected($event)"
              class="w-full bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono p-1.5 focus:border-border-strong focus:outline-none file:bg-accent-action file:text-white file:border-0 file:px-3 file:py-1 file:text-[12px] file:font-medium"
            />
          </div>

          <!-- Declared Record Count (optional override) -->
          <div>
            <label class="block text-[12px] text-text-secondary font-medium mb-1">
              Declared record count (trailer)
            </label>
            <input
              type="number"
              [(ngModel)]="declaredCount"
              placeholder="Auto-extracted if blank"
              class="w-full bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-1.5 focus:border-border-strong focus:outline-none"
            />
          </div>

          <!-- Declared Control Total (optional override) -->
          <div>
            <label class="block text-[12px] text-text-secondary font-medium mb-1">
              Declared control total ($ trailer)
            </label>
            <input
              type="number"
              step="0.01"
              [(ngModel)]="declaredTotal"
              placeholder="Auto-extracted if blank"
              class="w-full bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-1.5 focus:border-border-strong focus:outline-none"
            />
          </div>
        </div>

        <div class="flex items-center justify-between pt-2 border-t border-border-default">
          <span class="text-[11px] font-mono text-text-secondary">
            * Whole file hard gate: files failing control totals are quarantined immediately.
          </span>

          <button
            (click)="uploadAndIngest()"
            [disabled]="!selectedFile || loading()"
            class="bg-accent-action hover:bg-accent-action-hover text-white text-[13px] font-medium px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50"
          >
            @if (loading()) {
              <span class="w-3.5 h-3.5 border-2 border-white border-t-transparent animate-spin"></span>
              <span>Running gate checks...</span>
            } @else {
              <span>Execute file-level gate</span>
            }
          </button>
        </div>
      </div>

      <!-- Batch Selector & Active Gate Report -->
      <div class="bg-surface border border-border-default p-5 space-y-4">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border-default">
          <div>
            <h2 class="text-[15px] font-medium text-text-primary">Gatekeeper audit verification</h2>
            <p class="text-[12px] text-text-secondary">
              Deterministic 4-checkpoint report for selected batch file.
            </p>
          </div>

          <div class="flex items-center gap-2">
            <label class="text-[12px] text-text-secondary font-medium">Batch:</label>
            <select
              [ngModel]="selectedBatchId()"
              (ngModelChange)="onBatchChange($event)"
              class="bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono px-2.5 py-1 focus:border-border-strong focus:outline-none"
            >
              @for (b of batches(); track b.batch_id) {
                <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.filename }})</option>
              }
            </select>
          </div>
        </div>

        <!-- 4 Deterministic Checkpoint Cards -->
        @if (gateDetails()) {
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <!-- 1. Encoding -->
            <div class="p-3.5 bg-surface-sunken border border-border-default space-y-1">
              <div class="flex items-center justify-between text-[11px] font-mono">
                <span class="text-text-secondary">Checkpoint 1</span>
                <span [ngClass]="gateDetails()?.checks?.['encoding']?.passed ? 'text-status-green' : 'text-status-red'">
                  {{ gateDetails()?.checks?.['encoding']?.passed ? 'PASSED' : 'FAILED' }}
                </span>
              </div>
              <h3 class="text-[13px] font-medium text-text-primary">UTF-8 encoding</h3>
              <p class="text-[11px] text-text-secondary font-mono">
                {{ gateDetails()?.checks?.['encoding']?.detail || 'Verified clean decode' }}
              </p>
            </div>

            <!-- 2. Required Columns -->
            <div class="p-3.5 bg-surface-sunken border border-border-default space-y-1">
              <div class="flex items-center justify-between text-[11px] font-mono">
                <span class="text-text-secondary">Checkpoint 2</span>
                <span [ngClass]="gateDetails()?.checks?.['required_columns']?.passed ? 'text-status-green' : 'text-status-red'">
                  {{ gateDetails()?.checks?.['required_columns']?.passed ? 'PASSED' : 'FAILED' }}
                </span>
              </div>
              <h3 class="text-[13px] font-medium text-text-primary">Canonical columns</h3>
              <p class="text-[11px] text-text-secondary font-mono">
                {{ gateDetails()?.checks?.['required_columns']?.detail || 'All required columns present' }}
              </p>
            </div>

            <!-- 3. Record Count Parity -->
            <div class="p-3.5 bg-surface-sunken border border-border-default space-y-1">
              <div class="flex items-center justify-between text-[11px] font-mono">
                <span class="text-text-secondary">Checkpoint 3</span>
                <span [ngClass]="gateDetails()?.checks?.['record_count']?.passed ? 'text-status-green' : 'text-status-red'">
                  {{ gateDetails()?.checks?.['record_count']?.passed ? 'PASSED' : 'FAILED' }}
                </span>
              </div>
              <h3 class="text-[13px] font-medium text-text-primary">Record count parity</h3>
              <p class="text-[11px] text-text-secondary font-mono">
                Declared: {{ gateDetails()?.declared_record_count || 'N/A' }} · Actual: {{ gateDetails()?.actual_record_count }}
              </p>
            </div>

            <!-- 4. Control Total Balance -->
            <div class="p-3.5 bg-surface-sunken border border-border-default space-y-1">
              <div class="flex items-center justify-between text-[11px] font-mono">
                <span class="text-text-secondary">Checkpoint 4</span>
                <span [ngClass]="gateDetails()?.checks?.['control_total']?.passed ? 'text-status-green' : 'text-status-red'">
                  {{ gateDetails()?.checks?.['control_total']?.passed ? 'PASSED' : 'FAILED' }}
                </span>
              </div>
              <h3 class="text-[13px] font-medium text-text-primary">Control total balance</h3>
              <p class="text-[11px] text-text-secondary font-mono">
                Actual: \${{ gateDetails()?.actual_control_total | number:'1.2-2' }}
              </p>
            </div>
          </div>

          <!-- Quarantine Warning Banner if failed -->
          @if (!gateDetails()?.passed) {
            <div class="p-4 bg-[var(--status-red-bg)] border border-status-red space-y-2">
              <div class="flex items-center gap-2 text-status-red font-medium text-[13px]">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>
                </svg>
                <span>BATCH QUARANTINED — DOWNSTREAM PROCESSING HALTED</span>
              </div>
              <p class="text-[12px] text-text-primary">
                This batch failed structural verification and has been isolated to the quarantine repository. Zero downstream row rules or reconciliation matches were executed.
              </p>
              <div class="space-y-1 text-[12px] font-mono text-status-red">
                @for (reason of gateDetails()?.reasons || []; track reason) {
                  <div>— {{ reason }}</div>
                }
              </div>
            </div>
          }
        } @else {
          <div class="py-6 text-center text-text-secondary text-[12px]">
            Select a batch above to view its 4-checkpoint structural verification report.
          </div>
        }
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StructuralGateComponent implements OnInit {
  pipeline = inject(PipelineService);
  toast = inject(ToastService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;
  gateDetails = signal<StructuralGateDetails | null>(null);

  selectedFile: File | null = null;
  declaredCount?: number;
  declaredTotal?: number;
  loading = signal<boolean>(false);

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        if (this.selectedBatchId()) {
          this.loadGate(this.selectedBatchId()!);
        }
      }
    });
  }

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.selectedFile = input.files[0];
    }
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.loadGate(batchId);
  }

  loadGate(batchId: string) {
    this.pipeline.loadGateDetails(batchId).subscribe({
      next: (details) => this.gateDetails.set(details),
      error: () => this.gateDetails.set(null)
    });
  }

  uploadAndIngest() {
    if (!this.selectedFile) return;
    this.loading.set(true);

    this.pipeline.ingestFile(
      this.selectedFile,
      'UPLOAD',
      this.declaredCount,
      this.declaredTotal
    ).subscribe({
      next: (res) => {
        this.loading.set(false);
        this.loadGate(res.batch_id);
        if (res.quarantined) {
          this.toast.error('Gate Failure', `Batch ${res.batch_id} quarantined due to structural mismatch.`);
        } else {
          this.toast.success('Gate Cleared', `Batch ${res.batch_id} passed all 4 checkpoints.`);
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.toast.error('Upload Error', err?.error?.detail || 'Failed to ingest statement.');
      }
    });
  }

  triggerSftpSimulation() {
    this.loading.set(true);
    this.pipeline.simulateSftp().subscribe({
      next: (res) => {
        this.loading.set(false);
        this.loadGate(res.batch_id);
        this.toast.info('SFTP Arrived', `Batch ${res.batch_id} processed through gate.`);
      },
      error: (err) => {
        this.loading.set(false);
        this.toast.error('Simulation Failed', err?.error?.detail || 'Could not simulate SFTP.');
      }
    });
  }
}
