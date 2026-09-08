import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Small "i" marker that reveals an explanatory panel on hover or keyboard
 * focus. Pure CSS reveal, so it works inside OnPush templates without any
 * state. Keep the text to two or three plain sentences: it explains what a
 * number means and where it came from, never a value of its own.
 *
 *   <app-info-tip text="..." />            panel opens below, left-aligned
 *   <app-info-tip text="..." align="right" />  panel opens below, right-aligned
 */
@Component({
  selector: 'app-info-tip',
  standalone: true,
  imports: [CommonModule],
  template: `
    <span class="relative inline-flex align-middle group">
      <button
        type="button"
        class="inline-flex items-center justify-center w-[14px] h-[14px] border border-border-strong text-text-secondary text-[9px] font-mono font-semibold leading-none select-none cursor-help hover:text-text-primary hover:border-text-primary focus:outline-none focus:text-text-primary focus:border-accent-action transition-colors"
        [attr.aria-label]="label() || 'What is this?'"
        aria-haspopup="true"
      >i</button>
      <span
        role="tooltip"
        class="hidden group-hover:block group-focus-within:block absolute top-full mt-1.5 z-50 w-[270px] p-2.5 bg-surface border border-border-strong shadow-md text-[12px] leading-[1.45] font-sans font-normal normal-case tracking-normal text-text-primary text-left whitespace-normal"
        [ngClass]="align() === 'right' ? 'right-0' : 'left-0'"
      >
        @if (label()) {
          <span class="block text-[10px] font-mono uppercase tracking-wider text-text-secondary mb-1">{{ label() }}</span>
        }
        {{ text() }}
      </span>
    </span>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InfoTipComponent {
  /** The explanation. Plain prose, no values. */
  text = input.required<string>();
  /** Optional heading shown above the text and used as the aria-label. */
  label = input<string>('');
  /** Which edge of the marker the panel hangs from. */
  align = input<'left' | 'right'>('left');
}
