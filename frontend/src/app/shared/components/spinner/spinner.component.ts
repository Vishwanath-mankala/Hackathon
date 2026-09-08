import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Inline activity indicator for in-flight requests — used inside buttons and
 * beside live status text so an API call is never silent.
 */
@Component({
  selector: 'app-spinner',
  standalone: true,
  imports: [CommonModule],
  template: `
    <span
      class="inline-block border-2 border-t-transparent rounded-full animate-spin align-[-2px]"
      [style.width.px]="size()"
      [style.height.px]="size()"
      [style.borderColor]="'currentColor'"
      [style.borderTopColor]="'transparent'"
      role="status"
      [attr.aria-label]="label()"
    ></span>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SpinnerComponent {
  size = input<number>(13);
  label = input<string>('Loading');
}
