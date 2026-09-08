import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService, describeHttpError } from '../../core/services/pipeline.service';
import { ToastService } from '../../core/services/toast.service';
import { StructuralGateDetails } from '../../core/models/pipeline.models';
import { AsyncStateComponent } from '../../shared/components/async-state/async-state.component';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';

/** The four deterministic file-level checks, in gate execution order. */
const CHECKPOINTS: { key: string; label: string }[] = [
  { key: 'encoding', label: 'UTF-8 encoding' },
  { key: 'required_columns', label: 'Canonical columns' },
  { key: 'record_count', label: 'Record count parity' },
  { key: 'control_total', label: 'Control total balance' },
];

@Component({
  selector: 'app-structural-gate',
  standalone: true,
  imports: [CommonModule, FormsModule, AsyncStateComponent, SpinnerComponent],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Structural integrity gate</h1>
          <p class="text-[13px] text-text-secondary">
            File-level hard gatekeeper. Verifies encoding, canonical columns, trailer row counts and control totals
            before any transaction reaches the rule engine.
          </p>
        </div>

        <button
          (click)="triggerSftpIntake()"
          [disabled]="ingesting()"
          class="bg-surface hover:bg-surface-sunken text-text-primary text-[13px] font-medium px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50"
        >
          @if (ingesting()) {
            <app-spinner [size]="14" label="Running pipeline" />
            <span>Running pipeline…</span>
          } @else {
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>
              <line x1="12" x2="12" y1="15" y2="3"/>
            </svg>
            <span>Pull next SFTP drop</span>
          }
        </button>
      </div>

      <!-- Ingestion & Upload -->
      <div class="bg-surface border border-border-default p-5 space-y-4">
        <h2 class="text-[15px] font-medium text-text-primary">Ingest full bank statement (no splitting)</h2>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label class="block text-[12px] text-text-secondary font-medium mb-1">
              Statement file (CSV, MT940, BAI2)
            </label>
            <input
              type="file"
              accept=".csv,.txt"
              (change)="onFileSelected($event)"
              [disabled]="ingesting()"
              class="w-full bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono p-1.5 focus:border-border-strong focus:outline-none disabled:opacity-50 file:bg-accent-action file:text-white file:border-0 file:px-3 file:py-1 file:text-[12px] file:font-medium"
            />
          </div>

          <div>
            <label class="block text-[12px] text-text-secondary font-medium mb-1">
              Declared record count (trailer)
            </label>
            <input
              type="number"
              [(ngModel)]="declaredCount"
              [disabled]="ingesting()"
              placeholder="Read from the file trailer if blank"
              class="w-full bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-1.5 focus:border-border-strong focus:outline-none disabled:opacity-50"
            />
          </div>

          <div>
            <label class="block text-[12px] text-text-secondary font-medium mb-1">
              Declared control total ($ trailer)
            </label>
            <input
              type="number"
              step="0.01"
              [(ngModel)]="declaredTotal"
              [disabled]="ingesting()"
              placeholder="Read from the file trailer if blank"
              class="w-full bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-1.5 focus:border-border-strong focus:outline-none disabled:opacity-50"
            />
          </div>
        </div>

        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 border-t border-border-default">
          <span class="text-[11px] font-mono text-text-secondary">
            Whole-file hard gate. A file failing any checkpoint is quarantined immediately and never reaches the rule engine.
          </span>

          <button
            (click)="uploadAndIngest()"
            [disabled]="!selectedFile || ingesting()"
            class="bg-accent-action hover:bg-accent-action-hover text-white text-[13px] font-medium px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50 shrink-0"
          >
            @if (ingesting()) {
              <app-spinner [size]="14" label="Running gate checks" />
              <span>Running 8-stage pipeline…</span>
            } @else {
              <span>Ingest &amp; run pipeline</span>
            }
          </button>
        </div>

        @if (ingesting()) {
          <p class="text-[11px] font-mono text-text-secondary">
            Gate → rule engine → agentic scoring → GL reconciliation → SLA estimate → publish all run automatically on ingest.
          </p>
        }
      </div>

      <!-- Gate Report -->
      <div class="bg-surface border border-border-default">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-5 border-b border-border-default">
          <div>
            <h2 class="text-[15px] font-medium text-text-primary">Gatekeeper audit verification</h2>
            <p class="text-[12px] text-text-secondary">
              Deterministic 4-checkpoint report for the selected batch file.
            </p>
          </div>

          <div class="flex items-center gap-2">
            <label class="text-[12px] text-text-secondary font-medium">Batch:</label>
            @if (batches().length > 0) {
              <select
                [ngModel]="selectedBatchId()"
                (ngModelChange)="onBatchChange($event)"
                class="bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono px-2.5 py-1 focus:border-border-strong focus:outline-none"
              >
                @for (b of batches(); track b.batch_id) {
                  <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.filename }})</option>
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
          label="structural gate report"
          skeleton="cards"
          [rows]="4"
          [loading]="gateLoading()"
          [error]="gateError()"
          [empty]="!gateDetails()"
          emptyMessage="Select a batch above to view its 4-checkpoint structural verification report."
          (retry)="reloadGate()"
        >
          <div class="p-5 space-y-4">
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              @for (cp of checkpoints; track cp.key; let i = $index) {
                <div class="p-3.5 bg-surface-sunken border border-border-default space-y-1">
                  <div class="flex items-center justify-between text-[11px] font-mono">
                    <span class="text-text-secondary">Checkpoint {{ i + 1 }}</span>
                    <span [ngClass]="checkPassed(cp.key) ? 'text-status-green' : 'text-status-red'">
                      {{ checkPassed(cp.key) ? 'PASSED' : 'FAILED' }}
                    </span>
                  </div>
                  <h3 class="text-[13px] font-medium text-text-primary">{{ cp.label }}</h3>
                  <p class="text-[11px] text-text-secondary font-mono break-words">
                    {{ checkDetail(cp.key) }}
                  </p>
                </div>
              }
            </div>

            <!-- Declared vs actual, straight from the gate report -->
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 text-[12px] font-mono">
              <div class="p-3 bg-surface-sunken border border-border-default flex items-center justify-between">
                <span class="text-text-secondary">Record count (declared / actual)</span>
                <span class="text-text-primary font-semibold">
                  {{ gateDetails()?.declared_record_count ?? '—' }} / {{ gateDetails()?.actual_record_count }}
                </span>
              </div>
              <div class="p-3 bg-surface-sunken border border-border-default flex items-center justify-between">
                <span class="text-text-secondary">Control total (declared / actual)</span>
                <span class="text-text-primary font-semibold">
                  {{ gateDetails()?.declared_control_total != null ? (gateDetails()!.declared_control_total | currency:'USD':'symbol':'1.2-2') : '—' }}
                  /
                  {{ gateDetails()?.actual_control_total | currency:'USD':'symbol':'1.2-2' }}
                </span>
              </div>
            </div>

            @if (gateDetails() && !gateDetails()!.passed) {
              <div class="p-4 bg-[var(--status-red-bg)] border border-status-red space-y-2">
                <div class="flex items-center gap-2 text-status-red font-medium text-[13px]">
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>
                  </svg>
                  <span>BATCH QUARANTINED — DOWNSTREAM PROCESSING HALTED</span>
                </div>
                <p class="text-[12px] text-text-primary">
                  This batch failed structural verification and was isolated to the quarantine repository.
                  No row rules or reconciliation matches were executed.
                </p>
                <div class="space-y-1 text-[12px] font-mono text-status-red">
                  @for (reason of gateDetails()!.reasons; track reason) {
                    <div>— {{ reason }}</div>
                  }
                </div>
                @if (gateDetails()!.quarantine_path) {
                  <div class="text-[11px] font-mono text-text-secondary break-all">
                    Isolated to: {{ gateDetails()!.quarantine_path }}
                  </div>
                }
              </div>
            }
          </div>
        </app-async-state>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StructuralGateComponent implements OnInit {
  pipeline = inject(PipelineService);
  toast = inject(ToastService);

  readonly checkpoints = CHECKPOINTS;

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;

  gateDetails = signal<StructuralGateDetails | null>(null);
  gateLoading = signal<boolean>(false);
  gateError = signal<string | null>(null);

  selectedFile: File | null = null;
  declaredCount?: number;
  declaredTotal?: number;
  ingesting = signal<boolean>(false);

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        const id = this.selectedBatchId();
        if (id) this.loadGate(id);
      },
      error: () => {}
    });
  }

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files?.length ? input.files[0] : null;
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.loadGate(batchId);
  }

  reloadGate() {
    const id = this.selectedBatchId();
    if (id) this.loadGate(id);
  }

  loadGate(batchId: string) {
    this.gateLoading.set(true);
    this.gateError.set(null);

    this.pipeline.loadGateDetails(batchId).subscribe({
      next: (details) => {
        this.gateDetails.set(details);
        this.gateLoading.set(false);
      },
      error: (err) => {
        this.gateDetails.set(null);
        this.gateError.set(describeHttpError(err));
        this.gateLoading.set(false);
      }
    });
  }

  checkPassed(key: string): boolean {
    return this.gateDetails()?.checks?.[key]?.passed === true;
  }

  /** Detail text as reported by the gate. Never substitutes a placeholder. */
  checkDetail(key: string): string {
    return this.gateDetails()?.checks?.[key]?.detail ?? 'Not reported by the gate.';
  }

  uploadAndIngest() {
    if (!this.selectedFile) return;
    this.ingesting.set(true);

    this.pipeline.ingestFile(
      this.selectedFile,
      'UPLOAD',
      this.declaredCount,
      this.declaredTotal
    ).subscribe({
      next: (res) => {
        this.ingesting.set(false);
        this.loadGate(res.batch_id);
        if (res.quarantined) {
          this.toast.error('Gate failure', `Batch ${res.batch_id} quarantined due to a structural mismatch.`);
        } else {
          this.toast.success('Gate cleared', `Batch ${res.batch_id} passed all 4 checkpoints — pipeline running.`);
        }
      },
      error: (err) => {
        this.ingesting.set(false);
        this.toast.error('Upload failed', describeHttpError(err));
      }
    });
  }

  triggerSftpIntake() {
    this.ingesting.set(true);
    this.pipeline.simulateSftp().subscribe({
      next: (res) => {
        this.ingesting.set(false);
        this.loadGate(res.batch_id);
        this.toast.info('SFTP drop ingested', res.message);
      },
      error: (err) => {
        this.ingesting.set(false);
        this.toast.error('Intake failed', describeHttpError(err));
      }
    });
  }
}
