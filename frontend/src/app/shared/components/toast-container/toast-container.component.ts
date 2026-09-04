import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ToastService, ToastMessage } from '../../../core/services/toast.service';

@Component({
  selector: 'app-toast-container',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
      @for (toast of toastService.toasts(); track toast.id) {
        <div
          class="pointer-events-auto flex items-start justify-between p-3 bg-surface border border-border-default"
          [ngClass]="borderClass(toast.type)"
        >
          <div class="flex items-start gap-2.5">
            <span class="w-2 h-2 mt-1 shrink-0" [ngClass]="swatchClass(toast.type)"></span>
            <div>
              <p class="text-[12px] font-medium text-text-primary">{{ toast.title }}</p>
              <p class="text-[11px] text-text-secondary mt-0.5">{{ toast.message }}</p>
            </div>
          </div>
          <button
            (click)="toastService.dismiss(toast.id)"
            class="text-text-secondary hover:text-text-primary text-[12px] ml-3 p-0.5 transition-colors shrink-0"
            aria-label="Dismiss"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
            </svg>
          </button>
        </div>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToastContainerComponent {
  toastService = inject(ToastService);

  borderClass(type: ToastMessage['type']): string {
    switch (type) {
      case 'success': return 'border-l-2 border-l-status-green';
      case 'error': return 'border-l-2 border-l-status-red';
      case 'warning': return 'border-l-2 border-l-status-amber';
      default: return 'border-l-2 border-l-accent-action';
    }
  }

  swatchClass(type: ToastMessage['type']): string {
    switch (type) {
      case 'success': return 'bg-status-green';
      case 'error': return 'bg-status-red';
      case 'warning': return 'bg-status-amber';
      default: return 'bg-accent-action';
    }
  }
}
