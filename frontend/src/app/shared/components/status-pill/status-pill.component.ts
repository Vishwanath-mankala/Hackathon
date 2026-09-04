import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { CommonModule } from '@angular/common';

export type StatusType =
  | 'tier-1' | 'tier-2' | 'tier-3' | 'tier-4'
  | 'matched' | 'matched-exact' | 'matched-tolerance'
  | 'ambiguous' | 'exception' | 'fail'
  | 'pass' | 'resolved' | 'healthy';

@Component({
  selector: 'app-status-pill',
  standalone: true,
  imports: [CommonModule],
  template: `
    <span
      class="inline-flex items-center gap-1.5 px-2 py-px text-[11px] font-mono font-medium border select-none"
      [ngClass]="badgeClasses()"
    >
      <span
        class="w-2 h-2 shrink-0 border"
        [ngClass]="swatchClasses()"
      ></span>
      {{ label() }}
    </span>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatusPillComponent {
  type = input<StatusType>('matched');
  text = input<string>('');

  label(): string {
    return this.text() || this.type().replace(/-/g, ' ');
  }

  badgeClasses(): string {
    switch (this.type()) {
      case 'tier-1':
      case 'matched':
      case 'matched-exact':
        return 'bg-[var(--status-green-bg)] text-status-green border-border-default';
      case 'tier-2':
      case 'matched-tolerance':
        return 'bg-surface-sunken text-tier-2 border-border-default';
      case 'tier-3':
        return 'bg-surface-sunken text-tier-3 border-border-default';
      case 'tier-4':
        return 'bg-surface-sunken text-tier-4 border-border-default';
      case 'ambiguous':
        return 'bg-[var(--status-amber-bg)] text-status-amber border-border-default';
      case 'exception':
      case 'fail':
        return 'bg-[var(--status-red-bg)] text-status-red border-border-default';
      case 'pass':
      case 'resolved':
      case 'healthy':
        return 'bg-[var(--status-green-bg)] text-status-green border-border-default';
      default:
        return 'bg-surface-sunken text-text-secondary border-border-default';
    }
  }

  swatchClasses(): string {
    switch (this.type()) {
      case 'tier-1':
      case 'matched':
      case 'matched-exact':
        return 'bg-tier-1 border-tier-1';
      case 'tier-2':
      case 'matched-tolerance':
        return 'bg-tier-2 border-tier-2';
      case 'tier-3':
        return 'bg-tier-3 border-tier-3';
      case 'tier-4':
        return 'bg-tier-4 border-tier-4';
      case 'ambiguous':
        return 'bg-status-amber border-status-amber';
      case 'exception':
      case 'fail':
        return 'bg-status-red border-status-red';
      case 'pass':
      case 'resolved':
      case 'healthy':
        return 'bg-status-green border-status-green';
      default:
        return 'bg-text-secondary border-text-secondary';
    }
  }
}
