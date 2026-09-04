import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReconciliationService } from '../../core/services/recon.service';
import { ToastService } from '../../core/services/toast.service';
import { GateResultSchema } from '../../core/models/recon.models';
import { StatusPillComponent } from '../../shared/components/status-pill/status-pill.component';

@Component({
  selector: 'app-structural-gate',
  standalone: true,
  imports: [CommonModule, StatusPillComponent],
  template: `
    <div class="space-y-6">
      <!-- Header & Action -->
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Structural integrity gate</h1>
          <p class="text-[13px] text-text-secondary">
            Validates encoding, required headers, row counts, and trailer control totals before matching.
          </p>
        </div>
        <button
          (click)="runGateCheck()"
          [disabled]="loading()"
          class="bg-accent-action hover:bg-accent-action-hover text-white font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50"
        >
          @if (loading()) {
            <span class="inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent animate-spin"></span>
            <span>Running...</span>
          } @else {
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2-1 4-2 7-2 2.5 0 4.5 1 6.5 2a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>
            <span>Execute gatekeeper check</span>
          }
        </button>
      </div>

      <!-- Summary Inline -->
      <div class="flex items-center gap-6 text-[13px] font-mono py-3 border-b border-border-default mb-4">
        <span>Batches audited: {{ gateResults().length }}</span>
        <span>Passed: <span class="text-status-green">{{ passedCount() }}</span></span>
        <span>Quarantined: <span class="text-status-red">{{ failedCount() }}</span></span>
      </div>

      <!-- Checkpoints strip -->
      <div class="text-[12px] text-text-secondary mb-4">
        Checkpoints: UTF-8 encoding · 9 canonical headers · Record count parity · Control total balance
      </div>

      <!-- Table -->
      <div class="overflow-x-auto w-full border border-border-default">
        <table class="w-full text-left border-collapse">
          <thead>
            <tr>
              <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Batch file</th>
              <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Status</th>
              <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Encoding</th>
              <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Headers</th>
              <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3 text-right">Record count</th>
              <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3 text-right">Control total</th>
              <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Failure reasons</th>
            </tr>
          </thead>
          <tbody class="text-[12px] font-mono">
            @for (res of gateResults(); track res.file) {
              <tr class="h-[36px] hover:bg-[var(--status-green-bg)]" [ngClass]="res.passed ? 'bg-surface even:bg-surface-sunken' : 'bg-[var(--status-red-bg)]'">
                <td class="py-2 px-3 text-text-primary">
                  <div class="flex items-center gap-2">
                    @if (res.passed) {
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>
                    } @else {
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
                    }
                    <span>{{ res.file }}</span>
                  </div>
                </td>
                <td class="py-2 px-3">
                  <app-status-pill [type]="res.passed ? 'pass' : 'fail'" [text]="res.passed ? 'Passed' : 'Failed'" />
                </td>
                <td class="py-2 px-3 text-text-secondary">
                  {{ res.checks['encoding']?.detail || 'Checked' }}
                </td>
                <td class="py-2 px-3 text-text-secondary">
                  {{ res.checks['required_sections']?.detail || 'Present' }}
                </td>
                <td class="py-2 px-3 text-text-secondary text-right">
                  {{ res.checks['record_count']?.detail || 'OK' }}
                </td>
                <td class="py-2 px-3 text-text-secondary text-right">
                  {{ res.checks['control_total']?.detail || 'Balanced' }}
                </td>
                <td class="py-2 px-3 text-status-red">
                  @if (res.reasons.length > 0) {
                    <div class="flex flex-col gap-1">
                      @for (reason of res.reasons; track reason) {
                        <span>- {{ reason }}</span>
                      }
                    </div>
                  } @else {
                    <span class="text-text-secondary">—</span>
                  }
                </td>
              </tr>
            } @empty {
              <tr>
                <td colspan="7" class="py-8 text-center text-text-secondary font-sans text-[13px]">
                  No gate inspection run. Execute gatekeeper check to audit batches.
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StructuralGateComponent implements OnInit {
  private reconService = inject(ReconciliationService);
  private toast = inject(ToastService);

  loading = signal<boolean>(false);
  gateResults = signal<GateResultSchema[]>([]);
  passedCount = signal<number>(0);
  failedCount = signal<number>(0);

  ngOnInit() {
    this.runGateCheck();
  }

  runGateCheck() {
    this.loading.set(true);
    this.reconService.checkAllBatches().subscribe({
      next: (res) => {
        this.loading.set(false);
        this.gateResults.set(res.results);
        this.passedCount.set(res.passed_count);
        this.failedCount.set(res.failed_count);

        if (res.failed_count > 0) {
          this.toast.warning(
            'Structural Gate Alert',
            `${res.failed_count} corrupted batch(es) caught and isolated into quarantine.`
          );
        } else {
          this.toast.success(
            'Gate Complete',
            `All ${res.total_batches} statement batches passed 4-point structural verification.`
          );
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.toast.error('Gate Validation Failed', err?.error?.detail || 'Could not connect to structural gate service.');
      }
    });
  }
}
