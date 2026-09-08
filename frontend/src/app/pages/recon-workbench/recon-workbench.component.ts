import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService, describeHttpError } from '../../core/services/pipeline.service';
import { ReconciliationService } from '../../core/services/recon.service';
import { ToastService } from '../../core/services/toast.service';
import { ArtifactKind } from '../../core/models/pipeline.models';
import { AsyncStateComponent } from '../../shared/components/async-state/async-state.component';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';

type ReconDataset = 'matched' | 'unmatched_bank' | 'outstanding_gl' | 'ambiguous';

const ARTIFACT_FOR_DATASET: Record<ReconDataset, ArtifactKind> = {
  matched: 'matched',
  unmatched_bank: 'unmatched_bank',
  outstanding_gl: 'outstanding_gl',
  ambiguous: 'recon_exceptions',
};

@Component({
  selector: 'app-recon-workbench',
  standalone: true,
  imports: [CommonModule, FormsModule, AsyncStateComponent, SpinnerComponent],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col lg:flex-row lg:items-center justify-between border-b border-border-default pb-4 gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Reconciliation workbench</h1>
          <p class="text-[13px] text-text-secondary">
            Stage 6 output for the selected batch. The 4-tier waterfall runs automatically once the batch clears the
            rule engine and every escalation is signed off — click any row to open the dual-ledger inspector.
          </p>
        </div>

        <div class="flex items-center gap-2">
          <label class="text-[12px] text-text-secondary font-medium">Batch:</label>
          @if (batches().length > 0) {
            <select
              [ngModel]="selectedBatchId()"
              (ngModelChange)="onBatchChange($event)"
              class="bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono px-2.5 py-1.5 focus:border-border-strong focus:outline-none"
            >
              @for (b of batches(); track b.batch_id) {
                <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.stage }})</option>
              }
            </select>
          } @else if (pipeline.overviewLoading()) {
            <span class="h-7 w-56 skeleton inline-block"></span>
          } @else {
            <span class="text-[12px] font-mono text-text-secondary">No batches available</span>
          }

          <button
            (click)="loadData()"
            [disabled]="loading() || !selectedBatchId()"
            class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[12px] px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            @if (loading()) {
              <app-spinner [size]="12" label="Loading reconciliation results" />
              <span>Loading…</span>
            } @else {
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
              <span>Reload</span>
            }
          </button>
        </div>
      </div>

      <!-- Waterfall tier summary, straight from the batch's Stage 6 result -->
      <app-async-state
        label="reconciliation summary"
        skeleton="metrics"
        [rows]="6"
        [loading]="summaryLoading()"
        [error]="summaryError()"
        [empty]="!summary()"
        emptyMessage="Stage 6 has not produced a reconciliation summary for this batch yet."
        (retry)="loadSummary()"
      >
        @if (summary(); as sum) {
          <div class="bg-surface border border-border-default p-4">
            <div class="text-[12px] font-mono text-text-secondary mb-2">
              4-tier waterfall result · {{ selectedBatchId() }}
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 text-[13px] font-mono">
              <div>
                <span class="text-text-secondary block text-[11px]">Match rate</span>
                <span class="text-status-green font-semibold text-[16px]">{{ sum.match_rate_pct }}%</span>
              </div>
              <div>
                <span class="text-text-secondary block text-[11px]">Tier 1 — exact</span>
                <span class="text-tier-1 font-semibold text-[16px]">{{ sum.tier_1_exact | number }}</span>
              </div>
              <div>
                <span class="text-text-secondary block text-[11px]">Tier 2 — date</span>
                <span class="text-tier-2 font-semibold text-[16px]">{{ sum.tier_2_date | number }}</span>
              </div>
              <div>
                <span class="text-text-secondary block text-[11px]">Tier 3 — reference</span>
                <span class="text-tier-3 font-semibold text-[16px]">{{ sum.tier_3_ref | number }}</span>
              </div>
              <div>
                <span class="text-text-secondary block text-[11px]">Tier 4 — amount slack</span>
                <span class="text-tier-4 font-semibold text-[16px]">{{ sum.tier_4_amount | number }}</span>
              </div>
              <div>
                <span class="text-text-secondary block text-[11px]">Ambiguous ties</span>
                <span [ngClass]="sum.ambiguous_count > 0 ? 'text-status-amber' : 'text-text-secondary'"
                      class="font-semibold text-[16px]">{{ sum.ambiguous_count | number }}</span>
              </div>
            </div>
          </div>
        }
      </app-async-state>

      <!-- Ledger Tabs -->
      <div class="flex border-b border-border-default text-[13px] overflow-x-auto">
        @for (tab of tabs; track tab.key) {
          <button
            (click)="setTab(tab.key)"
            class="px-4 py-2 font-medium border-b-2 -mb-px transition-colors flex items-center gap-2 whitespace-nowrap"
            [ngClass]="activeTab() === tab.key
              ? (tab.key === 'ambiguous' ? 'border-status-amber text-status-amber font-semibold' : 'border-accent-action text-accent-action font-semibold')
              : 'border-transparent text-text-secondary hover:text-text-primary'"
          >
            <span>{{ tab.label }}</span>
            @if (activeTab() === tab.key && !loading()) {
              <span class="text-[11px] font-mono px-1.5 py-0.5 bg-surface-sunken border border-border-default">
                {{ totalItems() | number }}
              </span>
            }
          </button>
        }
      </div>

      <!-- Tier legend filter (matched tab only) -->
      @if (activeTab() === 'matched') {
        <div class="flex flex-wrap items-center gap-4 py-2 px-3 bg-surface-sunken border border-border-default text-[12px]">
          <span class="text-text-secondary font-medium mr-1">Tier filter:</span>
          @for (t of tierLegend; track t.key) {
            <button
              class="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
              (click)="setTierFilter(t.key)"
              [class.font-bold]="tierFilter() === t.key"
            >
              <span class="w-2.5 h-2.5 border"
                    [ngClass]="[t.swatch, tierFilter() === t.key ? 'border-border-strong' : 'border-border-default']"></span>
              <span [class.text-accent-action]="tierFilter() === t.key" class="text-text-primary">{{ t.label }}</span>
            </button>
          }
          @if (tierFilter()) {
            <button (click)="setTierFilter(null)" class="text-accent-action text-[11px] underline ml-2">
              Clear tier filter
            </button>
          }
        </div>
      }

      <!-- Grid + docked inspector -->
      <div class="flex gap-4 items-start">
        <div class="flex-1 min-w-0 bg-surface border border-border-default">
          <div class="flex items-center justify-between py-2 px-3 bg-surface border-b border-border-default gap-3">
            <div class="relative flex items-center">
              <svg class="absolute left-2 text-text-secondary" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/></svg>
              <input
                type="text"
                [(ngModel)]="searchAccount"
                (ngModelChange)="onSearchChange()"
                placeholder="Filter by Account ID…"
                class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] pl-7 pr-3 py-1.5 focus:border-border-strong focus:outline-none w-64"
              />
            </div>

            @if (selectedBatchId()) {
              <a [href]="exportUrl()" target="_blank" download
                 class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5 shrink-0">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
                <span>Export CSV</span>
              </a>
            }
          </div>

          <app-async-state
            label="reconciliation rows"
            skeleton="table"
            [rows]="8"
            [loading]="loading()"
            [error]="error()"
            [empty]="tableItems().length === 0"
            emptyMessage="No records in this result set for the active filters."
            (retry)="loadData()"
          >
            <div class="overflow-x-auto">
              <table class="w-full text-left border-collapse select-none">
                <thead>
                  <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
                    <th class="py-2 px-3 border border-border-default">Reconciliation truth</th>
                    @if (activeTab() === 'matched') {
                      <th class="py-2 px-3 border border-border-default">Account</th>
                      <th class="py-2 px-3 border border-border-default">Bank Txn ID</th>
                      <th class="py-2 px-3 border border-border-default">GL Txn ID</th>
                      <th class="py-2 px-3 border border-border-default text-right">Amount ($)</th>
                      <th class="py-2 px-3 border border-border-default">Value date</th>
                      <th class="py-2 px-3 border border-border-default">Bank reference</th>
                    } @else if (activeTab() === 'outstanding_gl') {
                      <th class="py-2 px-3 border border-border-default">Account</th>
                      <th class="py-2 px-3 border border-border-default">GL Txn ID</th>
                      <th class="py-2 px-3 border border-border-default">DR/CR</th>
                      <th class="py-2 px-3 border border-border-default text-right">Amount ($)</th>
                      <th class="py-2 px-3 border border-border-default">Posting date</th>
                      <th class="py-2 px-3 border border-border-default">Allocation narrative</th>
                    } @else if (activeTab() === 'unmatched_bank') {
                      <th class="py-2 px-3 border border-border-default">Account</th>
                      <th class="py-2 px-3 border border-border-default">Bank Txn ID</th>
                      <th class="py-2 px-3 border border-border-default">DR/CR</th>
                      <th class="py-2 px-3 border border-border-default text-right">Amount ($)</th>
                      <th class="py-2 px-3 border border-border-default">Value date</th>
                      <th class="py-2 px-3 border border-border-default">Bank narrative</th>
                    } @else {
                      <th class="py-2 px-3 border border-border-default">Bank Txn ID</th>
                      <th class="py-2 px-3 border border-border-default">Candidate GL IDs</th>
                      <th class="py-2 px-3 border border-border-default text-center">Candidates</th>
                      <th class="py-2 px-3 border border-border-default text-center">Ref score</th>
                      <th class="py-2 px-3 border border-border-default">Tier</th>
                    }
                  </tr>
                </thead>
                <tbody class="text-[13px] text-text-primary">
                  @for (row of tableItems(); track rowKey(row)) {
                    <tr
                      (click)="selectRow(row)"
                      class="even:bg-surface-sunken hover:bg-surface-sunken/80 h-[36px] cursor-pointer transition-colors"
                      [ngClass]="{'bg-[var(--status-green-bg)] font-medium border-l-2 border-l-accent-action': isRowSelected(row)}"
                    >
                      <td class="py-2 px-3 border border-border-default whitespace-nowrap">
                        <span class="inline-flex items-center gap-1.5 text-[11px] font-mono font-semibold"
                              [ngClass]="truthTextClass(row)">
                          <span class="w-2 h-2" [ngClass]="truthSwatchClass(row)"></span>
                          {{ truthLabel(row) }}
                        </span>
                      </td>

                      @if (activeTab() === 'matched') {
                        <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                        <td class="py-2 px-3 border border-border-default font-mono text-accent-action">{{ row.external_txn_id }}</td>
                        <td class="py-2 px-3 border border-border-default font-mono text-status-green">{{ row.internal_txn_id }}</td>
                        <td class="py-2 px-3 border border-border-default text-right font-mono font-semibold">
                          {{ getBankAmount(row) | currency:'USD':'symbol':'1.2-2' }}
                        </td>
                        <td class="py-2 px-3 border border-border-default font-mono">{{ getBankDate(row) }}</td>
                        <td class="py-2 px-3 border border-border-default truncate max-w-[200px]" [title]="getBankRef(row)">
                          {{ getBankRef(row) }}
                        </td>
                      } @else if (activeTab() === 'outstanding_gl') {
                        <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                        <td class="py-2 px-3 border border-border-default font-mono text-status-green">{{ row.internal_txn_id }}</td>
                        <td class="py-2 px-3 border border-border-default font-mono">{{ row.debit_credit }}</td>
                        <td class="py-2 px-3 border border-border-default text-right font-mono font-semibold">
                          {{ toNumber(row.amount) | currency:'USD':'symbol':'1.2-2' }}
                        </td>
                        <td class="py-2 px-3 border border-border-default font-mono">{{ getGLDate(row) }}</td>
                        <td class="py-2 px-3 border border-border-default truncate max-w-[240px]" [title]="getGLRef(row)">
                          {{ getGLRef(row) }}
                        </td>
                      } @else if (activeTab() === 'unmatched_bank') {
                        <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                        <td class="py-2 px-3 border border-border-default font-mono text-accent-action">{{ row.external_txn_id }}</td>
                        <td class="py-2 px-3 border border-border-default font-mono">{{ row.debit_credit }}</td>
                        <td class="py-2 px-3 border border-border-default text-right font-mono font-semibold">
                          {{ toNumber(row.amount) | currency:'USD':'symbol':'1.2-2' }}
                        </td>
                        <td class="py-2 px-3 border border-border-default font-mono">{{ getBankDate(row) }}</td>
                        <td class="py-2 px-3 border border-border-default truncate max-w-[240px]" [title]="getBankRef(row)">
                          {{ getBankRef(row) }}
                        </td>
                      } @else {
                        <td class="py-2 px-3 border border-border-default font-mono text-accent-action">{{ row.ingest_external_txn_id }}</td>
                        <td class="py-2 px-3 border border-border-default font-mono truncate max-w-[180px]" [title]="row.candidate_internal_txn_ids">
                          {{ row.candidate_internal_txn_ids }}
                        </td>
                        <td class="py-2 px-3 border border-border-default text-center font-mono">
                          {{ getCandidateCount(row) }}
                        </td>
                        <td class="py-2 px-3 border border-border-default text-center font-mono">
                          {{ row.chosen_by_reference_score }}
                        </td>
                        <td class="py-2 px-3 border border-border-default text-text-secondary font-mono">{{ row.tier }}</td>
                      }
                    </tr>
                  }
                </tbody>
              </table>
            </div>

            <!-- Pagination -->
            <div class="flex flex-col sm:flex-row sm:items-center justify-between px-4 py-2.5 border-t border-border-default bg-surface-sunken gap-3">
              <div class="flex items-center gap-4">
                <span class="text-text-secondary font-mono text-[12px]">
                  Showing {{ getPageStart() | number }}–{{ getPageEnd() | number }} of {{ totalItems() | number }} items
                </span>

                <div class="flex items-center gap-1.5 text-[12px] font-mono">
                  <span class="text-text-secondary">Rows per page:</span>
                  <select
                    [ngModel]="pageSize()"
                    (ngModelChange)="onPageSizeChange($event)"
                    class="bg-surface border border-border-default text-text-primary font-mono text-[12px] px-2 py-0.5 focus:border-border-strong focus:outline-none"
                  >
                    <option [value]="25">25</option>
                    <option [value]="50">50</option>
                    <option [value]="100">100</option>
                    <option [value]="200">200</option>
                  </select>
                </div>
              </div>

              <div class="flex items-center gap-1.5 font-mono text-[12px]">
                <span class="text-text-secondary mr-2">Page {{ currentPage() }} of {{ totalPages() }}</span>
                <button (click)="changePage(1)" [disabled]="currentPage() <= 1"
                        class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2 py-1 border border-border-default transition-colors disabled:opacity-40" title="First page">&laquo;</button>
                <button (click)="changePage(currentPage() - 1)" [disabled]="currentPage() <= 1"
                        class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2.5 py-1 border border-border-default transition-colors disabled:opacity-40">Prev</button>
                <button (click)="changePage(currentPage() + 1)" [disabled]="currentPage() >= totalPages()"
                        class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2.5 py-1 border border-border-default transition-colors disabled:opacity-40">Next</button>
                <button (click)="changePage(totalPages())" [disabled]="currentPage() >= totalPages()"
                        class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2 py-1 border border-border-default transition-colors disabled:opacity-40" title="Last page">&raquo;</button>
              </div>
            </div>
          </app-async-state>
        </div>

        <!-- Docked inspector -->
        @if (selectedRow(); as row) {
          <div class="w-[420px] shrink-0 bg-surface border border-border-default p-5 space-y-4 sticky top-4 select-none">
            <div class="flex items-start justify-between pb-3 border-b border-border-default">
              <div class="min-w-0">
                <span class="text-[11px] font-mono text-text-secondary block">Transaction reconciliation inspector</span>
                <h3 class="text-[14px] font-mono font-semibold text-text-primary truncate max-w-[320px]">
                  {{ getRowIdentifier(row) }}
                </h3>
              </div>
              <button (click)="clearSelectedRow()" class="text-text-secondary hover:text-text-primary p-1 transition-colors" title="Close inspector">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            <div class="p-3.5 border font-mono text-[12px] space-y-1" [ngClass]="getVerdictClasses()">
              <div class="font-bold text-[13px]">{{ getVerdictTitle(row) }}</div>
              <div class="text-[11px] opacity-90">{{ getVerdictSubtitle() }}</div>
            </div>

            <div class="space-y-1.5">
              <span class="text-[11px] font-medium text-text-secondary block">Side-by-side reconciliation proof</span>

              <div class="grid grid-cols-2 gap-2 text-[12px] font-mono bg-surface-sunken p-3 border border-border-default">
                <div class="border-r border-border-default pr-2 space-y-2">
                  <span class="text-[11px] font-bold text-accent-action block">Bank Statement</span>
                  <div>
                    <span class="text-[10px] text-text-secondary block">External Txn ID</span>
                    <span class="text-text-primary text-[11px] font-medium">{{ getBankTxnId(row) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Date</span>
                    <span class="text-text-primary text-[11px]">{{ getBankDate(row) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Amount</span>
                    <span class="text-text-primary text-[13px] font-bold">
                      {{ getBankAmount(row) | currency:'USD':'symbol':'1.2-2' }}
                    </span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Reference</span>
                    <span class="text-text-secondary text-[11px] truncate block" [title]="getBankRef(row)">{{ getBankRef(row) }}</span>
                  </div>
                </div>

                <div class="pl-2 space-y-2">
                  <span class="text-[11px] font-bold text-status-green block">General Ledger</span>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Internal GL ID</span>
                    <span class="text-text-primary text-[11px] font-medium">{{ getGLTxnId(row) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Date</span>
                    <span class="text-text-primary text-[11px]">{{ getGLDate(row) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Amount</span>
                    <span class="text-text-primary text-[13px] font-bold">
                      {{ getGLAmount(row) | currency:'USD':'symbol':'1.2-2' }}
                    </span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Allocation</span>
                    <span class="text-text-secondary text-[11px] truncate block" [title]="getGLRef(row)">{{ getGLRef(row) }}</span>
                  </div>
                </div>
              </div>
            </div>

            @if (activeTab() === 'matched') {
              <div class="p-3 bg-surface-sunken border border-border-default text-[12px] font-mono space-y-1.5">
                <span class="text-[11px] font-semibold text-text-secondary block">Mathematical variance verification</span>
                <div class="flex items-center justify-between">
                  <span class="text-text-secondary">Amount variance (Δ Amount):</span>
                  <span [ngClass]="getAmountDelta(row) === 0 ? 'text-status-green font-bold' : 'text-status-amber font-bold'">
                    {{ getAmountDelta(row) | currency:'USD':'symbol':'1.2-2' }}
                  </span>
                </div>
                <div class="flex items-center justify-between">
                  <span class="text-text-secondary">Date difference (Δ Days):</span>
                  <span [ngClass]="getDateDelta(row) === 0 ? 'text-status-green font-bold' : 'text-tier-2 font-bold'">
                    {{ getDateDelta(row) }} days
                  </span>
                </div>
              </div>
            }

            <div class="p-3 bg-surface-sunken border border-border-default text-[12px] space-y-1">
              <span class="text-[11px] font-semibold text-text-secondary block">Rule resolution trace</span>
              <p class="text-[12px] text-text-primary leading-relaxed">{{ getExplanationText(row) }}</p>
            </div>

            <div class="pt-3 border-t border-border-default">
              <button (click)="copyAuditProof()" class="text-[12px] font-medium text-accent-action hover:underline">
                Copy audit evidence
              </button>
            </div>
          </div>
        }
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReconWorkbenchComponent implements OnInit {
  pipeline = inject(PipelineService);
  private reconService = inject(ReconciliationService);
  private toast = inject(ToastService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;

  readonly tabs: { key: ReconDataset; label: string }[] = [
    { key: 'matched', label: 'Matched & Settled' },
    { key: 'unmatched_bank', label: 'Reconciling Items (Bank Only)' },
    { key: 'outstanding_gl', label: 'Outstanding Items (GL Only)' },
    { key: 'ambiguous', label: 'Ambiguous Matches' },
  ];

  readonly tierLegend = [
    { key: 'TIER_1_EXACT', label: 'Tier 1 — Exact match', swatch: 'bg-tier-1' },
    { key: 'TIER_2_DATE_TOLERANCE', label: 'Tier 2 — Date tolerance', swatch: 'bg-tier-2' },
    { key: 'TIER_3_REFERENCE_MATCH', label: 'Tier 3 — Reference overlap', swatch: 'bg-tier-3' },
    { key: 'TIER_4_AMOUNT_TOLERANCE', label: 'Tier 4 — Amount tolerance', swatch: 'bg-tier-4' },
  ];

  activeTab = signal<ReconDataset>('matched');
  tierFilter = signal<string | null>(null);
  selectedRow = signal<any | null>(null);

  tableItems = signal<any[]>([]);
  currentPage = signal<number>(1);
  pageSize = signal<number>(50);
  totalPages = signal<number>(1);
  totalItems = signal<number>(0);
  searchAccount = '';

  loading = signal<boolean>(false);
  error = signal<string | null>(null);

  summary = signal<any | null>(null);
  summaryLoading = signal<boolean>(false);
  summaryError = signal<string | null>(null);

  private searchDebounce?: ReturnType<typeof setTimeout>;

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        if (this.selectedBatchId()) {
          this.loadSummary();
          this.loadData();
        }
      },
      error: () => {}
    });
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.currentPage.set(1);
    this.selectedRow.set(null);
    this.loadSummary();
    this.loadData();
  }

  loadSummary() {
    const id = this.selectedBatchId();
    if (!id) return;

    this.summaryLoading.set(true);
    this.summaryError.set(null);

    this.pipeline.loadReconciliation(id).subscribe({
      next: (res) => {
        this.summary.set(res.summary ?? null);
        this.summaryLoading.set(false);
      },
      error: (err) => {
        this.summary.set(null);
        this.summaryError.set(describeHttpError(err));
        this.summaryLoading.set(false);
      }
    });
  }

  loadData() {
    const id = this.selectedBatchId();
    if (!id) {
      this.tableItems.set([]);
      this.totalItems.set(0);
      this.totalPages.set(1);
      return;
    }

    this.loading.set(true);
    this.error.set(null);

    this.reconService.getBatchDataset(
      id,
      this.activeTab(),
      this.currentPage(),
      this.pageSize(),
      this.searchAccount.trim() || undefined,
      this.activeTab() === 'matched' ? (this.tierFilter() ?? undefined) : undefined
    ).subscribe({
      next: (res) => {
        this.updateGrid(res);
        this.loading.set(false);
      },
      error: (err) => {
        this.tableItems.set([]);
        this.totalItems.set(0);
        this.totalPages.set(1);
        this.selectedRow.set(null);
        this.error.set(describeHttpError(err));
        this.loading.set(false);
      }
    });
  }

  updateGrid(res: any) {
    const items = res.items || [];
    this.tableItems.set(items);
    this.totalItems.set(res.total || 0);
    this.totalPages.set(res.total_pages || 1);

    if (items.length === 0) {
      this.selectedRow.set(null);
      return;
    }

    const current = this.selectedRow();
    const match = current
      ? items.find((i: any) => this.rowKey(i) === this.rowKey(current))
      : null;
    this.selectedRow.set(match ?? items[0]);
  }

  setTab(tab: ReconDataset) {
    if (this.activeTab() === tab) return;
    this.activeTab.set(tab);
    this.tierFilter.set(null);
    this.selectedRow.set(null);
    this.currentPage.set(1);
    this.loadData();
  }

  setTierFilter(tierKey: string | null) {
    this.tierFilter.update(curr => (curr === tierKey ? null : tierKey));
    this.selectedRow.set(null);
    this.currentPage.set(1);
    this.loadData();
  }

  onSearchChange() {
    if (this.searchDebounce) clearTimeout(this.searchDebounce);
    this.searchDebounce = setTimeout(() => {
      this.selectedRow.set(null);
      this.currentPage.set(1);
      this.loadData();
    }, 300);
  }

  onPageSizeChange(newSize: any) {
    const size = typeof newSize === 'string' ? parseInt(newSize, 10) : Number(newSize);
    this.pageSize.set(size || 50);
    this.currentPage.set(1);
    this.loadData();
  }

  changePage(newPage: number) {
    if (newPage < 1 || newPage > this.totalPages()) return;
    this.currentPage.set(newPage);
    this.loadData();
  }

  getPageStart(): number {
    return this.totalItems() === 0 ? 0 : (this.currentPage() - 1) * this.pageSize() + 1;
  }

  getPageEnd(): number {
    return Math.min(this.currentPage() * this.pageSize(), this.totalItems());
  }

  exportUrl(): string {
    const id = this.selectedBatchId();
    return id ? this.pipeline.getArtifactUrl(id, ARTIFACT_FOR_DATASET[this.activeTab()]) : '#';
  }

  // =========================================================================
  // Row helpers — every value is read from the API row, never substituted
  // =========================================================================
  rowKey(row: any): string {
    return row.matchId || row.external_txn_id || row.internal_txn_id || row.ingest_external_txn_id || JSON.stringify(row);
  }

  selectRow(row: any) { this.selectedRow.set(row); }
  clearSelectedRow() { this.selectedRow.set(null); }

  isRowSelected(row: any): boolean {
    const current = this.selectedRow();
    return !!current && this.rowKey(current) === this.rowKey(row);
  }

  toNumber(v: any): number {
    if (v === null || v === undefined || v === '') return 0;
    const n = parseFloat(String(v).replace(/,/g, ''));
    return Number.isFinite(n) ? n : 0;
  }

  truthLabel(row: any): string {
    switch (this.activeTab()) {
      case 'matched':
        return row.matchRule === 'TIER_1_EXACT'
          ? 'TRULY RECONCILED (EXACT)'
          : 'TRULY RECONCILED (TOLERANCE)';
      case 'unmatched_bank': return 'RECONCILING ITEM (BANK ONLY)';
      case 'outstanding_gl': return 'OUTSTANDING ITEM (GL ONLY)';
      default: return 'AMBIGUOUS TIE (UNSETTLED)';
    }
  }

  truthTextClass(row: any): string {
    switch (this.activeTab()) {
      case 'matched': return row.matchRule === 'TIER_1_EXACT' ? 'text-status-green' : 'text-tier-2';
      case 'unmatched_bank': return 'text-accent-action';
      case 'outstanding_gl': return 'text-text-secondary';
      default: return 'text-status-amber';
    }
  }

  truthSwatchClass(row: any): string {
    switch (this.activeTab()) {
      case 'matched': return row.matchRule === 'TIER_1_EXACT' ? 'bg-tier-1' : 'bg-tier-2';
      case 'unmatched_bank': return 'bg-accent-action';
      case 'outstanding_gl': return 'bg-text-secondary';
      default: return 'bg-status-amber';
    }
  }

  getRowIdentifier(row: any): string {
    return row.external_txn_id || row.internal_txn_id || row.ingest_external_txn_id || row.matchId || 'Selected line';
  }

  getVerdictTitle(row: any): string {
    if (this.activeTab() === 'matched') {
      switch (row.matchRule) {
        case 'TIER_1_EXACT': return 'TRULY RECONCILED — EXACT MATCH';
        case 'TIER_2_DATE_TOLERANCE': return 'TRULY RECONCILED — DATE TOLERANCE';
        case 'TIER_3_REFERENCE_MATCH': return 'TRULY RECONCILED — REFERENCE OVERLAP';
        case 'TIER_4_AMOUNT_TOLERANCE': return 'TRULY RECONCILED — AMOUNT SLACK';
        default: return `TRULY RECONCILED — ${row.matchRule}`;
      }
    }
    if (this.activeTab() === 'unmatched_bank') return 'RECONCILING ITEM — BANK STATEMENT ONLY';
    if (this.activeTab() === 'outstanding_gl') return 'OUTSTANDING ITEM — GENERAL LEDGER ONLY';
    return 'AMBIGUOUS TIE — MULTI-CANDIDATE';
  }

  getVerdictSubtitle(): string {
    switch (this.activeTab()) {
      case 'matched': return 'Discrepancy verified within certified policy. Settled in dual ledger.';
      case 'unmatched_bank': return 'Valid bank statement line with no GL cashbook match. Requires a GL journal entry.';
      case 'outstanding_gl': return 'Internal GL entry posted to books; awaiting clearance on the bank statement.';
      default: return 'Multiple candidate cashbook rows matched identical values. Auto-matching halted.';
    }
  }

  getVerdictClasses(): string {
    switch (this.activeTab()) {
      case 'matched': return 'bg-[var(--status-green-bg)] text-status-green border-status-green';
      case 'unmatched_bank': return 'bg-surface-sunken text-accent-action border-accent-action';
      case 'outstanding_gl': return 'bg-surface-sunken text-text-secondary border-border-default';
      default: return 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber';
    }
  }

  getBankTxnId(row: any): string {
    return row.external_txn_id || row.ingest_external_txn_id ||
      (this.activeTab() === 'outstanding_gl' ? '— Not on bank statement' : '—');
  }

  getGLTxnId(row: any): string {
    return row.internal_txn_id || row.chosen_internal_txn_id ||
      (this.activeTab() === 'unmatched_bank' ? '— Not in GL' : '—');
  }

  getBankDate(row: any): string {
    return row.ingest_date || row.value_date || row.booking_date || '—';
  }

  getGLDate(row: any): string {
    return row.cache_date || row.value_date || row.txn_date || '—';
  }

  getBankAmount(row: any): number {
    return this.toNumber(row.ingest_amount ?? row.amount);
  }

  getGLAmount(row: any): number {
    return this.toNumber(row.cache_amount ?? row.amount);
  }

  getBankRef(row: any): string {
    return row.ingest_reference || row.reference || row.narrative || '—';
  }

  getGLRef(row: any): string {
    return row.cache_reference || row.allocation || row.narrative || '—';
  }

  getAmountDelta(row: any): number {
    if (this.activeTab() !== 'matched') return 0;
    return Math.round(Math.abs(Math.abs(this.getBankAmount(row)) - Math.abs(this.getGLAmount(row))) * 100) / 100;
  }

  getDateDelta(row: any): number {
    if (this.activeTab() !== 'matched') return 0;
    const d1 = this.getBankDate(row);
    const d2 = this.getGLDate(row);
    if (d1 === '—' || d2 === '—') return 0;
    const t1 = new Date(d1).getTime();
    const t2 = new Date(d2).getTime();
    if (!Number.isFinite(t1) || !Number.isFinite(t2)) return 0;
    return Math.round(Math.abs(t1 - t2) / (1000 * 3600 * 24));
  }

  getExplanationText(row: any): string {
    switch (this.activeTab()) {
      case 'matched':
        return `Account ${row.account} settled under rule ${row.matchRule} with amount variance ` +
          `$${this.getAmountDelta(row).toFixed(2)} and a date difference of ${this.getDateDelta(row)} days.`;
      case 'unmatched_bank':
        return `Bank statement transaction ${this.getBankTxnId(row)} is structurally valid but has no ` +
          `corresponding internal GL ledger entry. Classify as a deposit in transit or raise a manual GL journal entry.`;
      case 'outstanding_gl':
        return `Internal GL cashbook row ${this.getGLTxnId(row)} was recorded on the books but has not cleared the ` +
          `bank statement. Classify as an outstanding check or timing transit item.`;
      default:
        return `${this.getCandidateCount(row)} candidate GL entries matched at ${row.tier} with identical account and ` +
          `amount. Reference similarity scored ${row.chosen_by_reference_score}; the engine halted auto-settlement to ` +
          `prevent overmatching. Human tie-break required.`;
    }
  }

  getCandidateCount(row: any): number {
    if (!row.candidate_internal_txn_ids) return 0;
    return String(row.candidate_internal_txn_ids).split(',').length;
  }

  copyAuditProof() {
    const row = this.selectedRow();
    if (!row) return;
    const text =
      `RECONCILIATION AUDIT PROOF\n` +
      `Batch: ${this.selectedBatchId()}\n` +
      `Status: ${this.getVerdictTitle(row)}\n` +
      `Bank ID: ${this.getBankTxnId(row)}\n` +
      `GL ID: ${this.getGLTxnId(row)}\n` +
      `Amount Variance: $${this.getAmountDelta(row)}\n` +
      `Date Delta: ${this.getDateDelta(row)} days\n` +
      `Rationale: ${this.getExplanationText(row)}`;
    navigator.clipboard.writeText(text).then(
      () => this.toast.info('Evidence copied', 'Reconciliation audit proof copied to clipboard.'),
      () => this.toast.error('Copy failed', 'The browser blocked clipboard access.')
    );
  }
}
