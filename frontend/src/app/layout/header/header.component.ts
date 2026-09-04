import { Component, ChangeDetectionStrategy, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReconciliationService } from '../../core/services/recon.service';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule],
  template: `
    <header class="h-10 bg-surface border-b border-border-default px-4 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-0 text-[12px] font-mono text-text-secondary">
        <span class="text-text-primary font-medium">Vanguard Ledger</span>
        <span class="mx-2 text-border-strong">·</span>
        <span>Reconciliation console</span>
        @if (health()) {
          <span class="mx-2 text-border-strong">·</span>
          <span class="text-status-green">v{{ health()!.version }}</span>
          <span class="mx-2 text-border-strong">·</span>
          <span>{{ formatUptime(health()!.uptime_seconds) }}</span>
        }
      </div>

      <div class="flex items-center gap-3">
        @if (health()) {
          <span class="text-[11px] font-mono text-status-green">Connected</span>
        } @else {
          <span class="text-[11px] font-mono text-status-red">Disconnected</span>
        }
        <button
          (click)="refreshHealth()"
          title="Refresh connection"
          class="p-1.5 text-text-secondary hover:text-text-primary hover:bg-surface-sunken transition-colors"
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
  health = this.reconService.systemHealth;

  ngOnInit() {
    this.refreshHealth();
  }

  refreshHealth() {
    this.reconService.getHealth().subscribe({
      error: () => console.warn('Backend unreachable')
    });
  }

  formatUptime(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    return `${mins}m ${Math.round(seconds % 60)}s`;
  }
}
