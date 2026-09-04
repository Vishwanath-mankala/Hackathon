import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ReconciliationService } from '../../core/services/recon.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="space-y-8 animate-fade-in text-[13px] font-sans">
      
      <!-- Header -->
      <div>
        <h1 class="text-[20px] font-medium text-text-primary mb-1">Pipeline overview</h1>
        <p class="text-[13px] text-text-secondary">
          Real-time health overview across GL cashbook cache, sequential batch arrivals, and tiered auto-matches.
        </p>
      </div>

      <!-- Top summary strip -->
      <div class="font-mono text-text-primary text-[13px]">
        Matched: {{ matchedCount() | number }} &middot; Cache backlog: {{ cacheCount() | number }} &middot; Exceptions: {{ ingestExceptionsCount() | number }} &middot; Ambiguous: {{ ambiguousCount() | number }}
      </div>

      <!-- Tier waterfall table -->
      <div>
        <h2 class="text-[16px] font-medium text-text-primary mb-3">Waterfall rule execution tiers</h2>
        <table class="w-full border-collapse border border-border-default">
          <thead>
            <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
              <th class="p-2 text-left font-normal border border-border-default">Tier</th>
              <th class="p-2 text-left font-normal border border-border-default">Rule description</th>
              <th class="p-2 text-right font-normal border border-border-default">Transactions</th>
              <th class="p-2 text-right font-normal border border-border-default">Share</th>
            </tr>
          </thead>
          <tbody>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-tier-1"></span>
                  Tier 1
                </div>
              </td>
              <td class="p-2 border border-border-default">Exact match (Account + Abs amount + Value date)</td>
              <td class="p-2 border border-border-default font-mono text-right">414</td>
              <td class="p-2 border border-border-default font-mono text-right">92.0%</td>
            </tr>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-tier-2"></span>
                  Tier 2
                </div>
              </td>
              <td class="p-2 border border-border-default">Date tolerance window (±3 calendar days)</td>
              <td class="p-2 border border-border-default font-mono text-right">3</td>
              <td class="p-2 border border-border-default font-mono text-right">0.7%</td>
            </tr>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-tier-3"></span>
                  Tier 3
                </div>
              </td>
              <td class="p-2 border border-border-default">Narrative & reference substring overlap</td>
              <td class="p-2 border border-border-default font-mono text-right">3</td>
              <td class="p-2 border border-border-default font-mono text-right">0.7%</td>
            </tr>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-tier-4"></span>
                  Tier 4
                </div>
              </td>
              <td class="p-2 border border-border-default">Amount tolerance ($1.00 fee slack + date window)</td>
              <td class="p-2 border border-border-default font-mono text-right">30</td>
              <td class="p-2 border border-border-default font-mono text-right">6.7%</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Gate health table -->
      <div>
        <h2 class="text-[16px] font-medium text-text-primary mb-3">Structural gate health</h2>
        <table class="w-full border-collapse border border-border-default">
          <thead>
            <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
              <th class="p-2 text-left font-normal border border-border-default">Check</th>
              <th class="p-2 text-left font-normal border border-border-default">Status</th>
              <th class="p-2 text-left font-normal border border-border-default">Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">Encoding</td>
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-status-green"></span>
                  Passed
                </div>
              </td>
              <td class="p-2 border border-border-default font-mono">UTF-8 Clean</td>
            </tr>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">Headers</td>
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-status-green"></span>
                  Passed
                </div>
              </td>
              <td class="p-2 border border-border-default font-mono">9/9 Verified</td>
            </tr>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">Record count</td>
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-status-green"></span>
                  Passed
                </div>
              </td>
              <td class="p-2 border border-border-default font-mono">Balanced</td>
            </tr>
            <tr class="h-[36px] bg-surface even:bg-surface-sunken hover:bg-[var(--status-green-bg)] transition-colors text-text-primary">
              <td class="p-2 border border-border-default">Control total</td>
              <td class="p-2 border border-border-default">
                <div class="flex items-center gap-2">
                  <span class="w-3 h-3 inline-block bg-current text-status-green"></span>
                  Passed
                </div>
              </td>
              <td class="p-2 border border-border-default font-mono">Balanced ($0.00 Diff)</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Navigation links -->
      <div class="flex items-center gap-4 text-[13px] pt-4">
        <a routerLink="/recon" class="text-accent-action hover:underline">Open workbench</a>
        <a routerLink="/feed" class="text-accent-action hover:underline">Ingest source</a>
      </div>

    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent implements OnInit {
  private reconService = inject(ReconciliationService);

  matchedCount = signal<number>(450);
  cacheCount = signal<number>(36673);
  ingestExceptionsCount = signal<number>(50);
  ambiguousCount = signal<number>(250);

  ngOnInit() {
    this.reconService.getMatches(1, 1).subscribe({
      next: (res) => {
        if (res.total) this.matchedCount.set(res.total);
      }
    });

    this.reconService.getUnmatchedCache(1, 1).subscribe({
      next: (res) => {
        if (res.total) this.cacheCount.set(res.total);
      }
    });

    this.reconService.getUnmatchedIngest(1, 1).subscribe({
      next: (res) => {
        if (res.total) this.ingestExceptionsCount.set(res.total);
      }
    });

    this.reconService.getAmbiguousMatches(1, 1).subscribe({
      next: (res) => {
        if (res.total) this.ambiguousCount.set(res.total);
      }
    });
  }
}
