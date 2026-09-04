import { Component, ChangeDetectionStrategy, inject, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ReconciliationService } from '../../core/services/recon.service';
import { ToastService } from '../../core/services/toast.service';
import { MatchConfigSchema, ReconRunResponse } from '../../core/models/recon.models';
import { StatusPillComponent } from '../../shared/components/status-pill/status-pill.component';

type ActiveTab = 'matched' | 'cache' | 'ingest' | 'ambiguous';

@Component({
  selector: 'app-recon-workbench',
  standalone: true,
  imports: [CommonModule, FormsModule, StatusPillComponent],
  template: `
    <div class="space-y-6">
      <!-- Section Header -->
      <div class="flex items-center justify-between border-b border-border-default pb-4">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Reconciliation workbench</h1>
          <p class="text-[13px] text-text-secondary">Tune tolerance parameters, execute sequential waterfall matching, and review settled ledgers and exceptions.</p>
        </div>
        <div class="flex items-center gap-3">
          <button
            (click)="toggleKnobs()"
            class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="20" y1="9" y2="9"/><line x1="4" x2="20" y1="15" y2="15"/><line x1="10" x2="10" y1="6" y2="12"/><line x1="14" x2="14" y1="12" y2="18"/></svg>
            <span>Tolerances</span>
          </button>
          <button
            (click)="executeReconciliation()"
            [disabled]="loading()"
            class="bg-accent-action hover:bg-accent-action-hover text-white font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50"
          >
            @if (loading()) {
              <span>Running...</span>
            } @else {
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              <span>Run reconciliation</span>
            }
          </button>
        </div>
      </div>

      <!-- Configurable Tolerance Knobs Drawer -->
      @if (showKnobs()) {
        <div class="bg-surface border border-border-default p-5 mb-4">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-[16px] font-medium text-text-primary">Tolerance parameters</h2>
            <button (click)="resetKnobs()" class="text-accent-action text-[12px] hover:underline">
              Reset defaults
            </button>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div class="flex flex-col gap-1.5">
              <label class="text-[13px] text-text-secondary font-medium">Date window (Tier 2)</label>
              <div class="flex items-center gap-2">
                <input
                  type="number"
                  [(ngModel)]="config.date_tolerance_days"
                  min="0"
                  max="30"
                  class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full"
                />
                <span class="text-[13px] text-text-secondary">days</span>
              </div>
            </div>

            <div class="flex flex-col gap-1.5">
              <label class="text-[13px] text-text-secondary font-medium">Abs amount slack (Tier 4)</label>
              <div class="flex items-center gap-2">
                <input
                  type="number"
                  [(ngModel)]="config.amount_abs_tolerance"
                  min="0"
                  step="0.05"
                  class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full"
                />
                <span class="text-[13px] text-text-secondary">$</span>
              </div>
            </div>

            <div class="flex flex-col gap-1.5">
              <label class="text-[13px] text-text-secondary font-medium">Pct amount slack (Tier 4)</label>
              <div class="flex items-center gap-2">
                <input
                  type="number"
                  [(ngModel)]="config.amount_pct_tolerance"
                  min="0"
                  max="0.1"
                  step="0.01"
                  class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full"
                />
                <span class="text-[13px] text-text-secondary">%</span>
              </div>
            </div>

            <div class="flex flex-col gap-1.5">
              <label class="text-[13px] text-text-secondary font-medium">Direction (DR/CR)</label>
              <select
                [(ngModel)]="config.direction_mode"
                class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full"
              >
                <option value="ignore">Ignore</option>
                <option value="same">Same (DR=DR, CR=CR)</option>
                <option value="opposite">Opposite (DR=CR)</option>
              </select>
            </div>
          </div>
        </div>
      }

      <div class="flex items-center gap-4 py-2 px-3 bg-surface-sunken border border-border-default mb-0 text-[12px]">
        <span class="text-text-secondary font-medium mr-1">Legend:</span>
        <button class="flex items-center gap-1.5 hover:opacity-80" (click)="setTierFilter('Tier 1')">
          <span class="w-2.5 h-2.5 bg-tier-1 border" [class.border-border-strong]="tierFilter() === 'Tier 1'" [class.border-border-default]="tierFilter() !== 'Tier 1'"></span>
          <span class="text-text-primary">Tier 1 — Exact match</span>
        </button>
        <button class="flex items-center gap-1.5 hover:opacity-80" (click)="setTierFilter('Tier 2')">
          <span class="w-2.5 h-2.5 bg-tier-2 border" [class.border-border-strong]="tierFilter() === 'Tier 2'" [class.border-border-default]="tierFilter() !== 'Tier 2'"></span>
          <span class="text-text-primary">Tier 2 — Date tolerance</span>
        </button>
        <button class="flex items-center gap-1.5 hover:opacity-80" (click)="setTierFilter('Tier 3')">
          <span class="w-2.5 h-2.5 bg-tier-3 border" [class.border-border-strong]="tierFilter() === 'Tier 3'" [class.border-border-default]="tierFilter() !== 'Tier 3'"></span>
          <span class="text-text-primary">Tier 3 — Reference overlap</span>
        </button>
        <button class="flex items-center gap-1.5 hover:opacity-80" (click)="setTierFilter('Tier 4')">
          <span class="w-2.5 h-2.5 bg-tier-4 border" [class.border-border-strong]="tierFilter() === 'Tier 4'" [class.border-border-default]="tierFilter() !== 'Tier 4'"></span>
          <span class="text-text-primary">Tier 4 — Amount tolerance</span>
        </button>
        <button class="flex items-center gap-1.5 hover:opacity-80" (click)="setTierFilter('Ambiguous')">
          <span class="w-2.5 h-2.5 bg-[var(--status-amber-bg)] border" [class.border-border-strong]="tierFilter() === 'Ambiguous'" [class.border-border-default]="tierFilter() !== 'Ambiguous'"></span>
          <span class="text-text-primary">Ambiguous</span>
        </button>
        <button class="flex items-center gap-1.5 hover:opacity-80" (click)="setTierFilter('Anomaly')">
          <span class="w-2.5 h-2.5 bg-[var(--status-red-bg)] border" [class.border-border-strong]="tierFilter() === 'Anomaly'" [class.border-border-default]="tierFilter() !== 'Anomaly'"></span>
          <span class="text-text-primary">Anomaly</span>
        </button>
      </div>

      <div class="border border-border-default -mt-[1px]">
        <div class="flex border-b border-border-default">
          <button (click)="setTab('matched')" class="px-4 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors" [class.border-accent-action]="activeTab() === 'matched'" [class.text-accent-action]="activeTab() === 'matched'" [class.border-transparent]="activeTab() !== 'matched'" [class.text-text-secondary]="activeTab() !== 'matched'" [class.hover:text-text-primary]="activeTab() !== 'matched'">Matched</button>
          <button (click)="setTab('cache')" class="px-4 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors" [class.border-accent-action]="activeTab() === 'cache'" [class.text-accent-action]="activeTab() === 'cache'" [class.border-transparent]="activeTab() !== 'cache'" [class.text-text-secondary]="activeTab() !== 'cache'" [class.hover:text-text-primary]="activeTab() !== 'cache'">Unmatched cache</button>
          <button (click)="setTab('ingest')" class="px-4 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors" [class.border-accent-action]="activeTab() === 'ingest'" [class.text-accent-action]="activeTab() === 'ingest'" [class.border-transparent]="activeTab() !== 'ingest'" [class.text-text-secondary]="activeTab() !== 'ingest'" [class.hover:text-text-primary]="activeTab() !== 'ingest'">Unmatched ingest</button>
          <button (click)="setTab('ambiguous')" class="px-4 py-2 text-[13px] font-medium border-b-2 -mb-px transition-colors" [class.border-accent-action]="activeTab() === 'ambiguous'" [class.text-accent-action]="activeTab() === 'ambiguous'" [class.border-transparent]="activeTab() !== 'ambiguous'" [class.text-text-secondary]="activeTab() !== 'ambiguous'" [class.hover:text-text-primary]="activeTab() !== 'ambiguous'">Ambiguous</button>
        </div>

        <div class="flex items-center justify-between py-2 px-3 bg-surface border-b border-border-default">
          <div class="relative flex items-center">
            <svg class="absolute left-2 text-text-secondary" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/></svg>
            <input type="text" [(ngModel)]="searchAccount" (ngModelChange)="onSearchChange()" placeholder="Filter by Account ID..." class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] pl-7 pr-3 py-1.5 focus:border-border-strong focus:outline-none w-64" />
          </div>
          <button (click)="exportCurrentTab()" class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5">
            Export CSV
          </button>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
                @if (activeTab() === 'matched') {
                  <th class="py-2 px-3 font-medium border border-border-default">Match ID</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Tier rule</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Account</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Internal ID (GL)</th>
                  <th class="py-2 px-3 font-medium border border-border-default">External ID (Bank)</th>
                  <th class="py-2 px-3 font-medium border border-border-default text-right">Amount ($)</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Value date</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Narrative reference</th>
                } @else if (activeTab() === 'cache') {
                  <th class="py-2 px-3 font-medium border border-border-default">Internal Txn ID</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Account</th>
                  <th class="py-2 px-3 font-medium border border-border-default">DR/CR</th>
                  <th class="py-2 px-3 font-medium border border-border-default text-right">Amount ($)</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Txn date</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Narrative / Allocation</th>
                } @else if (activeTab() === 'ingest') {
                  <th class="py-2 px-3 font-medium border border-border-default">External Txn ID</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Account</th>
                  <th class="py-2 px-3 font-medium border border-border-default">DR/CR</th>
                  <th class="py-2 px-3 font-medium border border-border-default text-right">Amount ($)</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Booking date</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Reference & Source Batch</th>
                } @else if (activeTab() === 'ambiguous') {
                  <th class="py-2 px-3 font-medium border border-border-default">Ingest Txn ID</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Tier</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Candidate GL IDs</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Chosen GL ID</th>
                  <th class="py-2 px-3 font-medium border border-border-default text-center">Ref score</th>
                  <th class="py-2 px-3 font-medium border border-border-default text-center">Disambiguated</th>
                  <th class="py-2 px-3 font-medium border border-border-default">Batch file</th>
                }
              </tr>
            </thead>
            <tbody class="text-[13px] text-text-primary">
              @for (row of filteredTableItems(); track row.matchId || row.internal_txn_id || row.external_txn_id || row.ingest_external_txn_id) {
                <tr class="even:bg-surface-sunken hover:bg-[var(--status-green-bg)] h-[36px]">
                  @if (activeTab() === 'matched') {
                    <td class="py-2 px-3 border border-border-default font-mono truncate max-w-[120px]" title="{{ row.matchId }}">
                      {{ row.matchId | slice:0:8 }}...
                    </td>
                    <td class="py-2 px-3 border border-border-default">
                      <app-status-pill [type]="row.matchRule === 'TIER_1_EXACT' ? 'matched' : 'matched-tolerance'" [text]="row.matchRule" />
                    </td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.internal_txn_id }}</td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.external_txn_id }}</td>
                    <td class="py-2 px-3 border border-border-default text-right font-mono">
                      {{ row.cache_amount || row.ingest_amount | currency:'USD':'symbol':'1.2-2' }}
                    </td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.cache_date || row.ingest_date }}</td>
                    <td class="py-2 px-3 border border-border-default truncate max-w-[200px]" title="{{ row.cache_reference || row.ingest_reference }}">
                      {{ row.cache_reference || row.ingest_reference || '—' }}
                    </td>
                  } @else if (activeTab() === 'cache') {
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.internal_txn_id }}</td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                    <td class="py-2 px-3 border border-border-default">
                      <span class="bg-surface-sunken border border-border-default text-[11px] font-mono font-medium px-1.5 py-0.5">
                        {{ row.debit_credit }}
                      </span>
                    </td>
                    <td class="py-2 px-3 border border-border-default text-right font-mono">
                      {{ row.amount | currency:'USD':'symbol':'1.2-2' }}
                    </td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.txn_date || row.value_date }}</td>
                    <td class="py-2 px-3 border border-border-default truncate max-w-[220px]">
                      {{ row.reference || row.narrative || row.allocation || '—' }}
                    </td>
                  } @else if (activeTab() === 'ingest') {
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.external_txn_id }}</td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                    <td class="py-2 px-3 border border-border-default">
                      <span class="bg-surface-sunken border border-border-default text-[11px] font-mono font-medium px-1.5 py-0.5">
                        {{ row.debit_credit }}
                      </span>
                    </td>
                    <td class="py-2 px-3 border border-border-default text-right font-mono">
                      {{ row.amount | currency:'USD':'symbol':'1.2-2' }}
                    </td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.booking_date || row.value_date }}</td>
                    <td class="py-2 px-3 border border-border-default">
                      {{ row.reference || '—' }}
                      <span class="text-[11px] font-mono text-text-secondary ml-2">({{ row._source_batch }})</span>
                    </td>
                  } @else if (activeTab() === 'ambiguous') {
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.ingest_external_txn_id }}</td>
                    <td class="py-2 px-3 border border-border-default">{{ row.tier }}</td>
                    <td class="py-2 px-3 border border-border-default font-mono truncate max-w-[180px]" title="{{ row.candidate_internal_txn_ids }}">
                      {{ row.candidate_internal_txn_ids }}
                    </td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.chosen_internal_txn_id }}</td>
                    <td class="py-2 px-3 border border-border-default text-center font-mono">
                      +{{ row.chosen_by_reference_score || '0' }}
                    </td>
                    <td class="py-2 px-3 border border-border-default text-center">
                      <app-status-pill [type]="row.disambiguated_by_reference === 'True' ? 'pass' : 'ambiguous'" [text]="row.disambiguated_by_reference === 'True' ? 'NARRATIVE-MATCH' : 'DATE-FALLBACK'" />
                    </td>
                    <td class="py-2 px-3 border border-border-default font-mono">{{ row.batch_file }}</td>
                  }
                </tr>
              } @empty {
                <tr>
                  <td colspan="8" class="py-8 px-4 text-center text-text-secondary text-[13px]">
                    No records found in current queue. Run reconciliation or adjust filter parameters.
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>

        <div class="flex items-center justify-between px-4 py-2 border-t border-border-default bg-surface-sunken">
          <span class="text-text-secondary font-mono text-[12px]">
            Page {{ currentPage() }} of {{ totalPages() }} ({{ totalItems() }} total)
          </span>

          <div class="flex items-center gap-2">
            <button
              (click)="changePage(currentPage() - 1)"
              [disabled]="currentPage() <= 1"
              class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-3 py-1 border border-border-default transition-colors disabled:opacity-50"
            >
              Prev
            </button>
            <button
              (click)="changePage(currentPage() + 1)"
              [disabled]="currentPage() >= totalPages()"
              class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-3 py-1 border border-border-default transition-colors disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReconWorkbenchComponent implements OnInit {
  private reconService = inject(ReconciliationService);
  private toast = inject(ToastService);

  loading = signal<boolean>(false);
  showKnobs = signal<boolean>(false);
  activeTab = signal<ActiveTab>('matched');
  tierFilter = signal<string | null>(null);

  // Tolerance Knobs
  config: MatchConfigSchema = {
    date_tolerance_days: 3,
    amount_abs_tolerance: 1.00,
    amount_pct_tolerance: 0.0,
    direction_mode: 'ignore',
  };

  // Grid Data & Pagination
  tableItems = signal<any[]>([]);
  
  filteredTableItems = computed(() => {
    const items = this.tableItems();
    const filter = this.tierFilter();
    if (!filter) return items;
    
    return items.filter(row => {
      const matchStr = String(row.matchRule || row.tier || '').toUpperCase();
      if (filter === 'Tier 1' && matchStr.includes('TIER_1')) return true;
      if (filter === 'Tier 2' && matchStr.includes('TIER_2')) return true;
      if (filter === 'Tier 3' && matchStr.includes('TIER_3')) return true;
      if (filter === 'Tier 4' && matchStr.includes('TIER_4')) return true;
      if (filter === 'Ambiguous' && matchStr.includes('AMBIGUOUS')) return true;
      if (filter === 'Anomaly' && matchStr.includes('ANOMALY')) return true;
      return false;
    });
  });

  currentPage = signal<number>(1);
  pageSize = signal<number>(50);
  totalPages = signal<number>(1);
  totalItems = signal<number>(0);
  searchAccount: string = '';

  ngOnInit() {
    this.loadData();
  }

  toggleKnobs() {
    this.showKnobs.update(v => !v);
  }

  resetKnobs() {
    this.config = {
      date_tolerance_days: 3,
      amount_abs_tolerance: 1.00,
      amount_pct_tolerance: 0.0,
      direction_mode: 'ignore',
    };
    this.toast.info('Knobs Reset', 'Reverted tolerances to default baseline parameters.');
  }

  setTab(tab: ActiveTab) {
    this.activeTab.set(tab);
    this.currentPage.set(1);
    this.loadData();
  }
  
  setTierFilter(tier: string) {
    this.tierFilter.update(current => current === tier ? null : tier);
  }

  onSearchChange() {
    this.currentPage.set(1);
    this.loadData();
  }

  changePage(newPage: number) {
    this.currentPage.set(newPage);
    this.loadData();
  }

  loadData() {
    const page = this.currentPage();
    const size = this.pageSize();
    const account = this.searchAccount.trim() || undefined;

    switch (this.activeTab()) {
      case 'matched':
        this.reconService.getMatches(page, size, account).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => console.warn(err)
        });
        break;
      case 'cache':
        this.reconService.getUnmatchedCache(page, size, account).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => console.warn(err)
        });
        break;
      case 'ingest':
        this.reconService.getUnmatchedIngest(page, size, account).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => console.warn(err)
        });
        break;
      case 'ambiguous':
        this.reconService.getAmbiguousMatches(page, size).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => console.warn(err)
        });
        break;
    }
  }

  updateGrid(res: any) {
    this.tableItems.set(res.items || []);
    this.totalItems.set(res.total || 0);
    this.totalPages.set(res.total_pages || 1);
  }

  executeReconciliation() {
    this.loading.set(true);
    this.reconService.runReconciliation({ config: this.config }).subscribe({
      next: (res) => {
        this.loading.set(false);
        this.loadData();
        this.toast.success(
          'Matching Complete',
          `Reconciled ${res.total_matched} transactions across 4 waterfall tiers.`
        );
      },
      error: (err) => {
        this.loading.set(false);
        this.toast.error('Run Failed', err?.error?.detail || 'Reconciliation engine encountered an error.');
      }
    });
  }

  exportCurrentTab() {
    let filename = 'matched_transactions.csv';
    if (this.activeTab() === 'cache') filename = 'unmatched_cache_remaining.csv';
    if (this.activeTab() === 'ingest') filename = 'unmatched_ingestion_exceptions.csv';
    if (this.activeTab() === 'ambiguous') filename = 'ambiguous_matches_for_review.csv';

    this.reconService.downloadCsv(filename).subscribe({
      next: (blob) => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        this.toast.success('Export Successful', `Downloaded ${filename}`);
      },
      error: () => this.toast.error('Export Failed', `Could not download ${filename}`)
    });
  }
}
