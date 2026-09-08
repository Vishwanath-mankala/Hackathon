import { Component, ChangeDetectionStrategy, input, output } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Uniform loading / error / empty surface for every API-backed panel.
 *
 * Renders projected content only once the request has resolved with data.
 * While in flight it shows a skeleton of the requested shape; on failure it
 * shows the server's message with a retry action. Nothing is ever rendered
 * from local placeholder data.
 */
@Component({
  selector: 'app-async-state',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (loading()) {
      <div class="p-4 space-y-3" role="status" [attr.aria-label]="'Loading ' + label()">
        @switch (skeleton()) {
          @case ('table') {
            <div class="h-7 skeleton"></div>
            @for (row of skeletonRows(); track row) {
              <div class="flex gap-3">
                <div class="h-5 skeleton flex-[2]"></div>
                <div class="h-5 skeleton flex-1"></div>
                <div class="h-5 skeleton flex-1"></div>
                <div class="h-5 skeleton flex-[1.5]"></div>
              </div>
            }
          }
          @case ('cards') {
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              @for (row of skeletonRows(); track row) {
                <div class="p-3.5 border border-border-default space-y-2">
                  <div class="h-3 w-1/2 skeleton"></div>
                  <div class="h-5 w-3/4 skeleton"></div>
                  <div class="h-3 w-full skeleton"></div>
                </div>
              }
            </div>
          }
          @case ('metrics') {
            <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
              @for (row of skeletonRows(); track row) {
                <div class="space-y-2">
                  <div class="h-3 w-3/4 skeleton"></div>
                  <div class="h-5 w-1/2 skeleton"></div>
                </div>
              }
            </div>
          }
          @default {
            @for (row of skeletonRows(); track row) {
              <div class="h-5 skeleton" [style.width.%]="row % 2 === 0 ? 100 : 70"></div>
            }
          }
        }
        <span class="sr-only">Loading {{ label() }}…</span>
      </div>
    } @else if (error()) {
      <div class="p-5 bg-[var(--status-red-bg)] border border-status-red space-y-3" role="alert">
        <div class="flex items-center gap-2 text-status-red font-medium text-[13px]">
          <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>
          </svg>
          <span>Could not load {{ label() }}</span>
        </div>

        <p class="text-[12px] font-mono text-text-primary break-words">{{ error() }}</p>

        <button
          (click)="retry.emit()"
          class="bg-surface hover:bg-surface-sunken text-text-primary text-[12px] font-medium px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>
          </svg>
          <span>Retry</span>
        </button>
      </div>
    } @else if (empty()) {
      <div class="py-8 text-center text-text-secondary text-[12px]">
        {{ emptyMessage() }}
      </div>
    } @else {
      <ng-content />
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AsyncStateComponent {
  /** Human-readable name of the resource, used in the loading and error copy. */
  label = input.required<string>();
  loading = input<boolean>(false);
  /** Server-supplied failure message. Null/empty means no error. */
  error = input<string | null>(null);
  /** True when the request succeeded but returned nothing. */
  empty = input<boolean>(false);
  emptyMessage = input<string>('No records returned by the API.');
  skeleton = input<'lines' | 'table' | 'cards' | 'metrics'>('lines');
  rows = input<number>(5);

  retry = output<void>();

  skeletonRows(): number[] {
    return Array.from({ length: this.rows() }, (_, i) => i);
  }
}
