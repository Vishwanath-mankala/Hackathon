import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ReconciliationService } from '../../core/services/recon.service';
import { ToastService } from '../../core/services/toast.service';
import { AmbiguityDiagnosisResponse } from '../../core/models/recon.models';


@Component({
  selector: 'app-diagnostics-lab',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6">
      <!-- Section Header -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Diagnostics</h1>
          <p class="text-[13px] text-text-secondary">
            Analyze multi-candidate tie concentration and simulate real-world production data corruption to test gate enforcement.
          </p>
        </div>

        <button
          (click)="runAmbiguityDiagnostics()"
          [disabled]="loadingAmbiguity()"
          class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-refresh-cw"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
          <span>Re-analyze</span>
        </button>
      </div>

      <!-- SECTION A: AMBIGUITY CONCENTRATION ANALYTICS -->
      <div>
        @if (diagnosis()) {
          <div class="flex items-center gap-6 text-[13px] font-mono py-3 border-b border-border-default mb-4">
            <span class="text-text-primary">Ambiguous: {{ diagnosis()?.total_ambiguous || 0 }}</span>
            <span class="text-text-secondary">·</span>
            <span class="text-text-primary">Avg candidates: {{ diagnosis()?.avg_candidates || 0 }}</span>
            <span class="text-text-secondary">·</span>
            <span class="text-text-primary">Max candidates: {{ diagnosis()?.max_candidates || 0 }}</span>
            <span class="text-text-secondary">·</span>
            <span class="text-text-primary">Resolved by reference: {{ diagnosis()?.resolved_by_reference_pct || 0 }}%</span>
            <span class="text-text-secondary">·</span>
            <span class="text-text-primary">Top 15 concentration: {{ diagnosis()?.top_amounts_concentration_pct || 0 }}%</span>
          </div>

          <div class="border-l-2 border-l-accent-action pl-4 py-2 bg-surface-sunken mb-6">
            <div class="text-[12px] text-text-secondary font-medium mb-1">Engine assessment</div>
            <p class="text-[13px] text-text-primary">
              {{ diagnosis()?.diagnostic_assessment }}
            </p>
          </div>

          <!-- Top Accounts and Recurring Amounts Tables -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="bg-surface border border-border-default">
              <table class="w-full text-left border-collapse">
                <thead>
                  <tr>
                    <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium px-4 py-2 border-b border-border-default">Amount</th>
                    <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium px-4 py-2 border-b border-border-default text-right">Occurrences</th>
                  </tr>
                </thead>
                <tbody>
                  @for (item of topAmountsList(); track item.amount) {
                    <tr class="h-[36px] even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors">
                      <td class="px-4 py-1 border-b border-border-default font-mono text-status-green text-right">\${{ item.amount }}</td>
                      <td class="px-4 py-1 border-b border-border-default font-mono text-right">{{ item.count }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>

            <div class="bg-surface border border-border-default">
              <table class="w-full text-left border-collapse">
                <thead>
                  <tr>
                    <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium px-4 py-2 border-b border-border-default">Account</th>
                    <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium px-4 py-2 border-b border-border-default text-right">Occurrences</th>
                  </tr>
                </thead>
                <tbody>
                  @for (item of topAccountsList(); track item.account) {
                    <tr class="h-[36px] even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors">
                      <td class="px-4 py-1 border-b border-border-default font-mono text-accent-action">ACC-{{ item.account }}</td>
                      <td class="px-4 py-1 border-b border-border-default font-mono text-right">{{ item.count }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </div>
        }
      </div>

      <!-- SECTION B: REAL-WORLD CHAOS INJECTION SIMULATOR -->
      <div class="bg-surface border border-border-default p-5 mt-6">
        <h2 class="text-[16px] font-medium text-text-primary mb-4">Chaos simulation</h2>
        
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div class="flex flex-col gap-1.5">
            <label class="text-[13px] text-text-secondary font-medium">Target file</label>
            <input
              type="text"
              [(ngModel)]="chaosTargetFile"
              placeholder="e.g. ingest_batch_0065.csv"
              class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full"
            />
          </div>

          <div class="flex flex-col gap-1.5">
            <label class="text-[13px] text-text-secondary font-medium">Anomaly mode</label>
            <select
              [(ngModel)]="chaosMode"
              class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full"
            >
              <option value="truncate">truncate — Transfer cut off mid-file</option>
              <option value="dropped_row">dropped_row — Silent dropped row</option>
              <option value="duplicate_row">duplicate_row — Bank duplicate send</option>
              <option value="tampered_amount">tampered_amount — Manual Excel edit</option>
              <option value="missing_column">missing_column — Schema drift</option>
              <option value="bad_encoding">bad_encoding — Accented Latin-1</option>
            </select>
          </div>

          <div class="flex flex-col justify-end">
            <div class="flex items-center gap-3">
              <button
                (click)="injectChaos()"
                [disabled]="chaosLoading()"
                class="flex-1 bg-status-red hover:opacity-90 text-white font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-zap"><path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/></svg>
                <span>Inject anomaly</span>
              </button>

              <button
                (click)="restoreBatch()"
                [disabled]="chaosLoading()"
                class="bg-surface hover:bg-surface-sunken hover:border-status-green text-text-primary font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-rotate-ccw"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                <span>Restore</span>
              </button>
            </div>
          </div>
        </div>

        <div class="bg-surface-sunken border border-border-default p-4 mt-4 text-[12px] text-text-secondary">
          <div class="text-[13px] font-medium text-text-primary mb-2">How chaos testing works</div>
          <ol class="list-decimal list-inside space-y-1">
            <li>An automatic .bak backup is created before modifying the CSV.</li>
            <li>After injecting the error, navigate to the Structural Gate view to observe the failure detection.</li>
            <li>Click Restore to immediately return the file to its original clean state.</li>
          </ol>
        </div>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DiagnosticsLabComponent implements OnInit {
  private reconService = inject(ReconciliationService);
  private toast = inject(ToastService);

  loadingAmbiguity = signal<boolean>(false);
  chaosLoading = signal<boolean>(false);

  diagnosis = signal<AmbiguityDiagnosisResponse | null>(null);
  topAmountsList = signal<{ amount: string; count: number }[]>([]);
  topAccountsList = signal<{ account: string; count: number }[]>([]);

  chaosTargetFile: string = 'ingest_batch_0065.csv';
  chaosMode: any = 'truncate';

  ngOnInit() {
    this.runAmbiguityDiagnostics();
  }

  runAmbiguityDiagnostics() {
    this.loadingAmbiguity.set(true);
    this.reconService.diagnoseAmbiguity().subscribe({
      next: (res) => {
        this.loadingAmbiguity.set(false);
        this.diagnosis.set(res);

        if (res.top_amounts) {
          const amounts = Object.entries(res.top_amounts).map(([amount, count]) => ({
            amount,
            count: Number(count),
          }));
          this.topAmountsList.set(amounts);
        }

        if (res.top_accounts) {
          const accounts = Object.entries(res.top_accounts).map(([account, count]) => ({
            account,
            count: Number(count),
          }));
          this.topAccountsList.set(accounts);
        }
      },
      error: (err) => {
        this.loadingAmbiguity.set(false);
        console.warn('Could not load ambiguity diagnostics:', err);
      }
    });
  }

  injectChaos() {
    this.chaosLoading.set(true);
    this.reconService.corruptBatch({
      batch_filename: this.chaosTargetFile,
      mode: this.chaosMode
    }).subscribe({
      next: (res) => {
        this.chaosLoading.set(false);
        this.toast.warning(
          'Chaos Anomaly Injected',
          `Successfully applied '${res.mode}' on ${res.file}. Backed up to .bak copy.`
        );
      },
      error: (err) => {
        this.chaosLoading.set(false);
        this.toast.error('Chaos Injection Failed', err?.error?.detail || 'Could not corrupt batch.');
      }
    });
  }

  restoreBatch() {
    this.chaosLoading.set(true);
    this.reconService.restoreBatch({
      batch_filename: this.chaosTargetFile
    }).subscribe({
      next: (res) => {
        this.chaosLoading.set(false);
        this.toast.success(
          'Batch Restored',
          `Successfully restored ${res.file} from .bak copy.`
        );
      },
      error: (err) => {
        this.chaosLoading.set(false);
        this.toast.error('Restore Failed', err?.error?.detail || 'No backup found.');
      }
    });
  }
}
