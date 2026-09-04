import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { ThemeService } from '../../core/services/theme.service';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  template: `
    <nav class="w-14 bg-surface border-r border-border-default flex flex-col items-center h-screen shrink-0 select-none">
      <!-- Brand mark -->
      <div class="h-12 flex items-center justify-center border-b border-border-default w-full">
        <span class="font-mono text-[11px] font-semibold text-accent-action">VL</span>
      </div>

      <!-- Navigation links -->
      <div class="flex-1 flex flex-col items-center gap-1 py-3 w-full">
        <!-- 1. Status Board -->
        <a routerLink="/dashboard"
           routerLinkActive="bg-accent-action text-white"
           [routerLinkActiveOptions]="{ exact: true }"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Batch Status Board & Telemetry">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
          </svg>
        </a>

        <!-- 2. Structural Gate & Ingestion -->
        <a routerLink="/gate"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Structural Gate & Ingestion">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>
          </svg>
        </a>

        <!-- 3. Anomaly Scorer & Human Review Queue -->
        <a routerLink="/anomalies"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Anomaly Scorer & Human Review Queue">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        </a>

        <!-- 4. GL Reconciliation Workbench -->
        <a routerLink="/recon"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="GL Reconciliation Workbench">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M16 3h5v5"/><path d="M8 3H3v5"/>
            <path d="M12 22v-8.3a4 4 0 0 0-1.172-2.872L3 3"/>
            <path d="m15 9 6-6"/><path d="M16 21h5v-5"/>
            <path d="M8 21H3v-5"/>
          </svg>
        </a>

        <!-- 5. Processing Time Estimator & SLA Analytics -->
        <a routerLink="/estimator"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Processing Time Estimator & SLA Analytics">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
        </a>
      </div>

      <!-- Theme toggle -->
      <div class="border-t border-border-default w-full flex items-center justify-center py-3">
        <button
          (click)="themeService.toggle()"
          class="w-10 h-10 flex items-center justify-center text-text-secondary
                 hover:bg-surface-sunken hover:text-text-primary transition-colors"
          [title]="themeService.isDark() ? 'Switch to light theme' : 'Switch to dark theme'"
        >
          @if (themeService.isDark()) {
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>
              <path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>
              <path d="M2 12h2"/><path d="M20 12h2"/>
              <path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
            </svg>
          } @else {
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
            </svg>
          }
        </button>
      </div>
    </nav>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SidebarComponent {
  themeService = inject(ThemeService);
}
