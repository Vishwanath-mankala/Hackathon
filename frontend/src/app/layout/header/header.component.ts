import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReconciliationService } from '../../core/services/recon.service';
import { PipelineService, describeHttpError } from '../../core/services/pipeline.service';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, SpinnerComponent],
  template: `
    <header class="h-10 bg-surface border-b border-border-default px-4 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-0 text-[12px] font-mono text-text-secondary">
        <span class="text-text-primary font-medium">Recon Master</span>
        <span class="mx-2 text-border-strong">·</span>
        <span>Reconciliation console</span>
        @if (health(); as h) {
          <span class="mx-2 text-border-strong">·</span>
          <span class="text-status-green">v{{ h.version }}</span>
          <span class="mx-2 text-border-strong">·</span>
          <span>{{ formatUptime(h.uptime_seconds) }}</span>
        }
      </div>

      <div class="flex items-center gap-3">
        <!-- Global in-flight indicator: no API call is ever silent -->
        @if (pipeline.busy()) {
          <span class="text-[11px] font-mono text-accent-action flex items-center gap-1.5">
            <app-spinner [size]="10" label="Request in flight" />
            <span>Working…</span>
          </span>
        }

        @if (checking()) {
          <span class="text-[11px] font-mono text-text-secondary flex items-center gap-1.5">
            <app-spinner [size]="10" label="Checking backend" />
            <span>Checking…</span>
          </span>
        } @else if (health()) {
          <span class="text-[11px] font-mono text-status-green">Connected</span>
        } @else {
          <span class="text-[11px] font-mono text-status-red" [title]="healthError() || 'Backend unreachable'">
            Disconnected
          </span>
        }

        <button
          (click)="refreshHealth()"
          [disabled]="checking()"
          title="Refresh connection"
          class="p-1.5 text-text-secondary hover:text-text-primary hover:bg-surface-sunken transition-colors disabled:opacity-40"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/>
            <path d="M16 16h5v5"/>
          </svg>
        </button>
      </div>
    </header>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HeaderComponent implements OnInit {
  private reconService = inject(ReconciliationService);
  pipeline = inject(PipelineService);

  health = this.reconService.systemHealth;
  checking = signal<boolean>(false);
  healthError = signal<string | null>(null);

  ngOnInit() {
    this.refreshHealth();
  }

  refreshHealth() {
    this.checking.set(true);
    this.healthError.set(null);
    this.reconService.getHealth().subscribe({
      next: () => this.checking.set(false),
      error: (err) => {
        this.checking.set(false);
        this.healthError.set(describeHttpError(err));
      }
    });
  }

  formatUptime(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    return `${mins}m ${Math.round(seconds % 60)}s`;
  }
}
