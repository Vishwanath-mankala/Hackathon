import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stat-card',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="bg-surface border border-border-default p-4">
      <p class="text-[11px] text-text-secondary font-medium mb-1">
        {{ title() }}
      </p>
      <div class="flex items-baseline gap-2">
        <span class="text-[18px] font-mono font-semibold text-text-primary">
          {{ value() }}
        </span>
        @if (unit()) {
          <span class="text-[11px] text-text-secondary font-mono">{{ unit() }}</span>
        }
      </div>
      @if (subtitle()) {
        <p class="text-[11px] text-text-secondary mt-2 border-t border-border-default pt-2">
          {{ subtitle() }}
        </p>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatCardComponent {
  title = input.required<string>();
  value = input.required<string | number>();
  unit = input<string>('');
  subtitle = input<string>('');
  badge = input<string>('');
  accent = input<string>('primary');
}
