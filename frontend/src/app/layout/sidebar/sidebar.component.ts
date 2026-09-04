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
        <a routerLink="/dashboard"
           routerLinkActive="bg-accent-action text-white"
           [routerLinkActiveOptions]="{ exact: true }"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Pipeline overview">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
          </svg>
        </a>

        <a routerLink="/feed"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Feed ingestion">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>
            <line x1="12" x2="12" y1="15" y2="3"/>
          </svg>
        </a>

        <a routerLink="/gate"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Structural gate">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>
          </svg>
        </a>

        <a routerLink="/recon"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Reconciliation workbench">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M16 3h5v5"/><path d="M8 3H3v5"/>
            <path d="M12 22v-8.3a4 4 0 0 0-1.172-2.872L3 3"/>
            <path d="m15 9 6-6"/><path d="M16 21h5v-5"/>
            <path d="M8 21H3v-5"/>
          </svg>
        </a>

        <a routerLink="/diagnostics"
           routerLinkActive="bg-accent-action text-white"
           class="w-10 h-10 flex items-center justify-center text-text-secondary
                  hover:bg-surface-sunken hover:text-text-primary transition-colors"
           title="Diagnostics lab">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/>
            <path d="M8.5 2h7"/><path d="M7 16h10"/>
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
