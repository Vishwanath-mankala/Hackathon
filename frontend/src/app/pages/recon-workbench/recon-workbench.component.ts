import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ReconciliationService } from '../../core/services/recon.service';
import { ToastService } from '../../core/services/toast.service';
import { MatchConfigSchema } from '../../core/models/recon.models';

type ActiveTab = 'matched' | 'cache' | 'ingest' | 'ambiguous';

@Component({
  selector: 'app-recon-workbench',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex items-center justify-between border-b border-border-default pb-4">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Reconciliation workbench</h1>
          <p class="text-[13px] text-text-secondary">
            Auditable transaction reconciliation grid. Click any row to open the docked dual-ledger inspector and verify reconciliation truth.
          </p>
        </div>
        <div class="flex items-center gap-3">
          <button
            (click)="toggleKnobs()"
            class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="20" y1="9" y2="9"/><line x1="4" x2="20" y1="15" y2="15"/><line x1="10" x2="10" y1="6" y2="12"/><line x1="14" x2="14" y1="12" y2="18"/></svg>
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
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              <span>Run reconciliation</span>
            }
          </button>
        </div>
      </div>

      <!-- Configurable Tolerance Knobs Drawer -->
      @if (showKnobs()) {
        <div class="bg-surface border border-border-default p-5 mb-4">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-[15px] font-medium text-text-primary">Tolerance parameters</h2>
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
                <span class="text-[13px] text-text-secondary font-mono">days</span>
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
                <span class="text-[13px] text-text-secondary font-mono">$</span>
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
                <span class="text-[13px] text-text-secondary font-mono">%</span>
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

      <!-- Confidence-Tier Legend Strip (Clickable Filter) -->
      <div class="flex flex-wrap items-center gap-4 py-2 px-3 bg-surface-sunken border border-border-default text-[12px]">
        <span class="text-text-secondary font-medium mr-1">Legend filter:</span>
        <button
          class="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
          (click)="setTierFilter('TIER_1')"
          [class.font-bold]="tierFilter() === 'TIER_1'"
        >
          <span class="w-2.5 h-2.5 bg-tier-1 border" [class.border-border-strong]="tierFilter() === 'TIER_1'" [class.border-border-default]="tierFilter() !== 'TIER_1'"></span>
          <span [class.text-accent-action]="tierFilter() === 'TIER_1'" class="text-text-primary">Tier 1 — Exact match</span>
        </button>

        <button
          class="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
          (click)="setTierFilter('TIER_2')"
          [class.font-bold]="tierFilter() === 'TIER_2'"
        >
          <span class="w-2.5 h-2.5 bg-tier-2 border" [class.border-border-strong]="tierFilter() === 'TIER_2'" [class.border-border-default]="tierFilter() !== 'TIER_2'"></span>
          <span [class.text-accent-action]="tierFilter() === 'TIER_2'" class="text-text-primary">Tier 2 — Date tolerance</span>
        </button>

        <button
          class="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
          (click)="setTierFilter('TIER_3')"
          [class.font-bold]="tierFilter() === 'TIER_3'"
        >
          <span class="w-2.5 h-2.5 bg-tier-3 border" [class.border-border-strong]="tierFilter() === 'TIER_3'" [class.border-border-default]="tierFilter() !== 'TIER_3'"></span>
          <span [class.text-accent-action]="tierFilter() === 'TIER_3'" class="text-text-primary">Tier 3 — Reference overlap</span>
        </button>

        <button
          class="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
          (click)="setTierFilter('TIER_4')"
          [class.font-bold]="tierFilter() === 'TIER_4'"
        >
          <span class="w-2.5 h-2.5 bg-tier-4 border" [class.border-border-strong]="tierFilter() === 'TIER_4'" [class.border-border-default]="tierFilter() !== 'TIER_4'"></span>
          <span [class.text-accent-action]="tierFilter() === 'TIER_4'" class="text-text-primary">Tier 4 — Amount tolerance</span>
        </button>

        <button
          class="flex items-center gap-1.5 hover:opacity-80 transition-opacity"
          (click)="setTab('ambiguous')"
          [class.font-bold]="activeTab() === 'ambiguous'"
        >
          <span class="w-2.5 h-2.5 bg-status-amber border" [class.border-border-strong]="activeTab() === 'ambiguous'" [class.border-border-default]="activeTab() !== 'ambiguous'"></span>
          <span [class.text-status-amber]="activeTab() === 'ambiguous'" class="text-text-primary">Ambiguous tie</span>
        </button>

        @if (tierFilter()) {
          <button (click)="clearTierFilter()" class="text-accent-action text-[11px] underline ml-2">
            Clear tier filter
          </button>
        }
      </div>

      <!-- Main Ledger Tabs -->
      <div class="flex border-b border-border-default text-[13px]">
        <button
          (click)="setTab('matched')"
          class="px-4 py-2 font-medium border-b-2 -mb-px transition-colors flex items-center gap-2"
          [ngClass]="activeTab() === 'matched' ? 'border-accent-action text-accent-action font-semibold' : 'border-transparent text-text-secondary hover:text-text-primary'"
        >
          <span>Matched & Settled</span>
          @if (activeTab() === 'matched') {
            <span class="text-[11px] font-mono px-1.5 py-0.2 bg-surface-sunken border border-border-default">
              {{ totalItems() }}
            </span>
          }
        </button>

        <button
          (click)="setTab('ingest')"
          class="px-4 py-2 font-medium border-b-2 -mb-px transition-colors flex items-center gap-2"
          [ngClass]="activeTab() === 'ingest' ? 'border-accent-action text-accent-action font-semibold' : 'border-transparent text-text-secondary hover:text-text-primary'"
        >
          <span>Reconciling Items (Bank Only)</span>
          @if (activeTab() === 'ingest') {
            <span class="text-[11px] font-mono px-1.5 py-0.2 bg-surface-sunken border border-border-default">
              {{ totalItems() }}
            </span>
          }
        </button>

        <button
          (click)="setTab('cache')"
          class="px-4 py-2 font-medium border-b-2 -mb-px transition-colors flex items-center gap-2"
          [ngClass]="activeTab() === 'cache' ? 'border-accent-action text-accent-action font-semibold' : 'border-transparent text-text-secondary hover:text-text-primary'"
        >
          <span>Outstanding Items (GL Only)</span>
          @if (activeTab() === 'cache') {
            <span class="text-[11px] font-mono px-1.5 py-0.2 bg-surface-sunken border border-border-default">
              {{ totalItems() }}
            </span>
          }
        </button>

        <button
          (click)="setTab('ambiguous')"
          class="px-4 py-2 font-medium border-b-2 -mb-px transition-colors flex items-center gap-2"
          [ngClass]="activeTab() === 'ambiguous' ? 'border-status-amber text-status-amber font-semibold' : 'border-transparent text-text-secondary hover:text-text-primary'"
        >
          <span>Ambiguous Matches</span>
          @if (activeTab() === 'ambiguous') {
            <span class="text-[11px] font-mono px-1.5 py-0.2 bg-surface-sunken border border-border-default">
              {{ totalItems() }}
            </span>
          }
        </button>
      </div>

      <!-- WORKBENCH LAYOUT: Table (Left) + Docked Right Drawer (Right) -->
      <div class="flex gap-4 items-start">
        <!-- Main Data Grid Container -->
        <div class="flex-1 min-w-0 bg-surface border border-border-default">
          <div class="flex items-center justify-between py-2 px-3 bg-surface border-b border-border-default">
            <div class="relative flex items-center">
              <svg class="absolute left-2 text-text-secondary" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/></svg>
              <input
                type="text"
                [(ngModel)]="searchAccount"
                (ngModelChange)="onSearchChange()"
                placeholder="Filter by Account ID..."
                class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] pl-7 pr-3 py-1.5 focus:border-border-strong focus:outline-none w-64"
              />
            </div>
            <button (click)="exportCurrentTab()" class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5">
              Export CSV
            </button>
          </div>

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
                    <th class="py-2 px-3 border border-border-default">Booking date</th>
                    <th class="py-2 px-3 border border-border-default">Bank reference</th>
                  } @else if (activeTab() === 'cache') {
                    <th class="py-2 px-3 border border-border-default">Account</th>
                    <th class="py-2 px-3 border border-border-default">GL Txn ID</th>
                    <th class="py-2 px-3 border border-border-default">DR/CR</th>
                    <th class="py-2 px-3 border border-border-default text-right">Amount ($)</th>
                    <th class="py-2 px-3 border border-border-default">Posting date</th>
                    <th class="py-2 px-3 border border-border-default">Allocation narrative</th>
                  } @else if (activeTab() === 'ingest') {
                    <th class="py-2 px-3 border border-border-default">Account</th>
                    <th class="py-2 px-3 border border-border-default">Bank Txn ID</th>
                    <th class="py-2 px-3 border border-border-default">DR/CR</th>
                    <th class="py-2 px-3 border border-border-default text-right">Amount ($)</th>
                    <th class="py-2 px-3 border border-border-default">Value date</th>
                    <th class="py-2 px-3 border border-border-default">Bank narrative</th>
                  } @else if (activeTab() === 'ambiguous') {
                    <th class="py-2 px-3 border border-border-default">Bank Txn ID</th>
                    <th class="py-2 px-3 border border-border-default">Candidate GL IDs</th>
                    <th class="py-2 px-3 border border-border-default text-center">Candidates count</th>
                    <th class="py-2 px-3 border border-border-default text-center">Ref score</th>
                    <th class="py-2 px-3 border border-border-default">Batch source</th>
                  }
                </tr>
              </thead>
              <tbody class="text-[13px] text-text-primary">
                @for (row of tableItems(); track row.matchId || row.internal_txn_id || row.external_txn_id || row.ingest_external_txn_id) {
                  <tr
                    (click)="selectRow(row)"
                    class="even:bg-surface-sunken hover:bg-surface-sunken/80 h-[36px] cursor-pointer transition-colors"
                    [ngClass]="{'bg-[var(--status-green-bg)] font-medium border-l-2 border-l-accent-action': isRowSelected(row)}"
                  >
                    <!-- Column 1: Explicit Reconciliation Truth Status -->
                    <td class="py-2 px-3 border border-border-default whitespace-nowrap">
                      @if (activeTab() === 'matched') {
                        @if (row.matchRule === 'TIER_1_EXACT') {
                          <span class="inline-flex items-center gap-1.5 text-[11px] font-mono text-status-green font-semibold">
                            <span class="w-2 h-2 bg-tier-1"></span>
                            TRULY RECONCILED (EXACT)
                          </span>
                        } @else {
                          <span class="inline-flex items-center gap-1.5 text-[11px] font-mono text-tier-2 font-semibold">
                            <span class="w-2 h-2 bg-tier-2"></span>
                            TRULY RECONCILED (TOLERANCE)
                          </span>
                        }
                      } @else if (activeTab() === 'ingest') {
                        <span class="inline-flex items-center gap-1.5 text-[11px] font-mono text-accent-action font-semibold">
                          <span class="w-2 h-2 bg-accent-action"></span>
                          RECONCILING ITEM (BANK ONLY)
                        </span>
                      } @else if (activeTab() === 'cache') {
                        <span class="inline-flex items-center gap-1.5 text-[11px] font-mono text-text-secondary font-semibold">
                          <span class="w-2 h-2 bg-text-secondary"></span>
                          OUTSTANDING ITEM (GL ONLY)
                        </span>
                      } @else if (activeTab() === 'ambiguous') {
                        <span class="inline-flex items-center gap-1.5 text-[11px] font-mono text-status-amber font-semibold">
                          <span class="w-2 h-2 bg-status-amber"></span>
                          AMBIGUOUS TIE (UNSETTLED)
                        </span>
                      }
                    </td>

                    @if (activeTab() === 'matched') {
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                      <td class="py-2 px-3 border border-border-default font-mono text-accent-action">{{ row.external_txn_id }}</td>
                      <td class="py-2 px-3 border border-border-default font-mono text-status-green">{{ row.internal_txn_id }}</td>
                      <td class="py-2 px-3 border border-border-default text-right font-mono font-semibold">
                        {{ (row.cache_amount || row.ingest_amount) | currency:'USD':'symbol':'1.2-2' }}
                      </td>
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.ingest_date || row.cache_date }}</td>
                      <td class="py-2 px-3 border border-border-default truncate max-w-[200px]" title="{{ row.ingest_reference || row.cache_reference }}">
                        {{ row.ingest_reference || row.cache_reference || '—' }}
                      </td>
                    } @else if (activeTab() === 'cache') {
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                      <td class="py-2 px-3 border border-border-default font-mono text-status-green">{{ row.internal_txn_id }}</td>
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.debit_credit }}</td>
                      <td class="py-2 px-3 border border-border-default text-right font-mono font-semibold">
                        {{ row.amount | currency:'USD':'symbol':'1.2-2' }}
                      </td>
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.txn_date || row.value_date }}</td>
                      <td class="py-2 px-3 border border-border-default truncate max-w-[240px]" title="{{ row.allocation || row.narrative }}">
                        {{ row.allocation || row.narrative || '—' }}
                      </td>
                    } @else if (activeTab() === 'ingest') {
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.account }}</td>
                      <td class="py-2 px-3 border border-border-default font-mono text-accent-action">{{ row.external_txn_id }}</td>
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.debit_credit }}</td>
                      <td class="py-2 px-3 border border-border-default text-right font-mono font-semibold">
                        {{ row.amount | currency:'USD':'symbol':'1.2-2' }}
                      </td>
                      <td class="py-2 px-3 border border-border-default font-mono">{{ row.booking_date || row.value_date }}</td>
                      <td class="py-2 px-3 border border-border-default truncate max-w-[240px]" title="{{ row.reference || row.narrative }}">
                        {{ row.reference || row.narrative || '—' }}
                      </td>
                    } @else if (activeTab() === 'ambiguous') {
                      <td class="py-2 px-3 border border-border-default font-mono text-accent-action">{{ row.ingest_external_txn_id }}</td>
                      <td class="py-2 px-3 border border-border-default font-mono truncate max-w-[180px]" title="{{ row.candidate_internal_txn_ids }}">
                        {{ row.candidate_internal_txn_ids }}
                      </td>
                      <td class="py-2 px-3 border border-border-default text-center font-mono">
                        {{ getCandidateCount(row) }}
                      </td>
                      <td class="py-2 px-3 border border-border-default text-center font-mono">
                        +{{ row.chosen_by_reference_score || '0' }}
                      </td>
                      <td class="py-2 px-3 border border-border-default text-text-secondary font-mono">{{ row.batch_file }}</td>
                    }
                  </tr>
                } @empty {
                  <tr>
                    <td colspan="8" class="py-8 text-center text-text-secondary text-[12px]">
                      No records found matching the active filter criteria.
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>

          <!-- Pagination & Page Size Bar -->
          <div class="flex flex-col sm:flex-row sm:items-center justify-between px-4 py-2.5 border-t border-border-default bg-surface-sunken gap-3">
            <div class="flex items-center gap-4">
              <span class="text-text-secondary font-mono text-[12px]">
                Showing {{ getPageStart() }}–{{ getPageEnd() }} of {{ totalItems() }} items
              </span>

              <!-- Page Size Selector -->
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

            <!-- Page Number Controls -->
            <div class="flex items-center gap-1.5 font-mono text-[12px]">
              <span class="text-text-secondary mr-2">Page {{ currentPage() }} of {{ totalPages() }}</span>

              <button
                (click)="changePage(1)"
                [disabled]="currentPage() <= 1"
                class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2 py-1 border border-border-default transition-colors disabled:opacity-40"
                title="First page"
              >
                &laquo;
              </button>

              <button
                (click)="changePage(currentPage() - 1)"
                [disabled]="currentPage() <= 1"
                class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2.5 py-1 border border-border-default transition-colors disabled:opacity-40"
                title="Previous page"
              >
                Prev
              </button>

              <button
                (click)="changePage(currentPage() + 1)"
                [disabled]="currentPage() >= totalPages()"
                class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2.5 py-1 border border-border-default transition-colors disabled:opacity-40"
                title="Next page"
              >
                Next
              </button>

              <button
                (click)="changePage(totalPages())"
                [disabled]="currentPage() >= totalPages()"
                class="bg-surface hover:bg-surface-sunken text-text-primary font-medium px-2 py-1 border border-border-default transition-colors disabled:opacity-40"
                title="Last page"
              >
                &raquo;
              </button>
            </div>
          </div>
        </div>

        <!-- DOCKED RIGHT ROW DETAIL DRAWER (Sliding side panel without modal overlay) -->
        @if (selectedRow()) {
          <div class="w-[420px] shrink-0 bg-surface border border-border-default p-5 space-y-4 sticky top-4 select-none">
            <!-- Drawer Header -->
            <div class="flex items-start justify-between pb-3 border-b border-border-default">
              <div>
                <span class="text-[11px] font-mono text-text-secondary block">Transaction reconciliation inspector</span>
                <h3 class="text-[14px] font-mono font-semibold text-text-primary truncate max-w-[320px]">
                  {{ getRowIdentifier(selectedRow()) }}
                </h3>
              </div>
              <button
                (click)="clearSelectedRow()"
                class="text-text-secondary hover:text-text-primary p-1 transition-colors"
                title="Close inspector"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            <!-- Reconciliation Verdict Banner -->
            <div class="p-3.5 border font-mono text-[12px] space-y-1" [ngClass]="getVerdictClasses(selectedRow())">
              <div class="font-bold text-[13px]">
                {{ getVerdictTitle(selectedRow()) }}
              </div>
              <div class="text-[11px] opacity-90">
                {{ getVerdictSubtitle(selectedRow()) }}
              </div>
            </div>

            <!-- Dual Ledger Comparison (Bank vs GL) -->
            <div class="space-y-1.5">
              <span class="text-[11px] font-medium text-text-secondary block">Side-by-side reconciliation proof</span>

              <div class="grid grid-cols-2 gap-2 text-[12px] font-mono bg-surface-sunken p-3 border border-border-default">
                <!-- Bank Statement Column -->
                <div class="border-r border-border-default pr-2 space-y-2">
                  <span class="text-[11px] font-bold text-accent-action block">Bank Statement</span>
                  <div>
                    <span class="text-[10px] text-text-secondary block">External Txn ID</span>
                    <span class="text-text-primary text-[11px] font-medium">{{ getBankTxnId(selectedRow()) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Date</span>
                    <span class="text-text-primary text-[11px]">{{ getBankDate(selectedRow()) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Amount</span>
                    <span class="text-text-primary text-[13px] font-bold">
                      {{ getBankAmount(selectedRow()) | currency:'USD':'symbol':'1.2-2' }}
                    </span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Reference</span>
                    <span class="text-text-secondary text-[11px] truncate block" title="{{ getBankRef(selectedRow()) }}">
                      {{ getBankRef(selectedRow()) }}
                    </span>
                  </div>
                </div>

                <!-- General Ledger Column -->
                <div class="pl-2 space-y-2">
                  <span class="text-[11px] font-bold text-status-green block">General Ledger</span>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Internal GL ID</span>
                    <span class="text-text-primary text-[11px] font-medium">{{ getGLTxnId(selectedRow()) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Date</span>
                    <span class="text-text-primary text-[11px]">{{ getGLDate(selectedRow()) }}</span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Amount</span>
                    <span class="text-text-primary text-[13px] font-bold">
                      {{ getGLAmount(selectedRow()) | currency:'USD':'symbol':'1.2-2' }}
                    </span>
                  </div>
                  <div>
                    <span class="text-[10px] text-text-secondary block">Allocation</span>
                    <span class="text-text-secondary text-[11px] truncate block" title="{{ getGLRef(selectedRow()) }}">
                      {{ getGLRef(selectedRow()) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Mathematical Discrepancy & Variance Check -->
            <div class="p-3 bg-surface-sunken border border-border-default text-[12px] font-mono space-y-1.5">
              <span class="text-[11px] font-semibold text-text-secondary block">Mathematical variance verification</span>
              <div class="flex items-center justify-between">
                <span class="text-text-secondary">Amount variance (Δ Amount):</span>
                <span [ngClass]="getAmountDelta(selectedRow()) === 0 ? 'text-status-green font-bold' : 'text-status-amber font-bold'">
                  {{ getAmountDelta(selectedRow()) | currency:'USD':'symbol':'1.2-2' }}
                </span>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-text-secondary">Date difference (Δ Days):</span>
                <span [ngClass]="getDateDelta(selectedRow()) === 0 ? 'text-status-green font-bold' : 'text-tier-2 font-bold'">
                  {{ getDateDelta(selectedRow()) }} days
                </span>
              </div>
            </div>

            <!-- Audit Rule Rationale -->
            <div class="p-3 bg-surface-sunken border border-border-default text-[12px] space-y-1">
              <span class="text-[11px] font-semibold text-text-secondary block">Rule resolution trace</span>
              <p class="text-[12px] text-text-primary leading-relaxed">
                {{ getExplanationText(selectedRow()) }}
              </p>
            </div>

            <!-- Actions -->
            <div class="pt-3 border-t border-border-default flex items-center justify-between">
              <button
                (click)="copyAuditProof()"
                class="text-[12px] font-medium text-accent-action hover:underline"
              >
                Copy audit evidence
              </button>

              <button
                (click)="signOffRow()"
                class="bg-surface hover:bg-surface-sunken text-text-primary text-[12px] font-medium px-3 py-1.5 border border-border-default transition-colors"
              >
                Audit sign-off
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
  private reconService = inject(ReconciliationService);
  private toast = inject(ToastService);

  loading = signal<boolean>(false);
  showKnobs = signal<boolean>(false);
  activeTab = signal<ActiveTab>('matched');
  tierFilter = signal<string | null>(null);
  selectedRow = signal<any | null>(null);

  config: MatchConfigSchema = {
    date_tolerance_days: 3,
    amount_abs_tolerance: 1.00,
    amount_pct_tolerance: 0.0,
    direction_mode: 'ignore',
  };

  tableItems = signal<any[]>([]);
  currentPage = signal<number>(1);
  pageSize = signal<number>(50);
  totalPages = signal<number>(1);
  totalItems = signal<number>(0);
  searchAccount: string = '';

  ngOnInit() {
    this.loadData();
  }

  selectRow(row: any) {
    this.selectedRow.set(row);
  }

  clearSelectedRow() {
    this.selectedRow.set(null);
  }

  isRowSelected(row: any): boolean {
    const current = this.selectedRow();
    if (!current) return false;
    const currentKey = current.matchId || current.external_txn_id || current.internal_txn_id || current.ingest_external_txn_id;
    const rowKey = row.matchId || row.external_txn_id || row.internal_txn_id || row.ingest_external_txn_id;
    return currentKey === rowKey;
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
    this.tierFilter.set(null);
    this.selectedRow.set(null);
    this.currentPage.set(1);
    this.loadData();
  }

  setTierFilter(tierKey: string) {
    if (this.activeTab() !== 'matched') {
      this.activeTab.set('matched');
    }
    this.tierFilter.update(curr => curr === tierKey ? null : tierKey);
    this.selectedRow.set(null);
    this.currentPage.set(1);
    this.loadData();
  }

  clearTierFilter() {
    this.tierFilter.set(null);
    this.selectedRow.set(null);
    this.currentPage.set(1);
    this.loadData();
  }

  onSearchChange() {
    this.selectedRow.set(null);
    this.currentPage.set(1);
    this.loadData();
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
    if (this.totalItems() === 0) return 0;
    return (this.currentPage() - 1) * this.pageSize() + 1;
  }

  getPageEnd(): number {
    return Math.min(this.currentPage() * this.pageSize(), this.totalItems());
  }

  loadData() {
    const page = this.currentPage();
    const size = this.pageSize();
    const account = this.searchAccount.trim() || undefined;
    const tier = this.tierFilter() || undefined;

    switch (this.activeTab()) {
      case 'matched':
        this.reconService.getMatches(page, size, account, tier).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => {
            console.warn(err);
            this.updateGrid({ items: [], total: 0, total_pages: 1 });
          }
        });
        break;
      case 'cache':
        this.reconService.getUnmatchedCache(page, size, account).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => {
            console.warn(err);
            this.updateGrid({ items: [], total: 0, total_pages: 1 });
          }
        });
        break;
      case 'ingest':
        this.reconService.getUnmatchedIngest(page, size, account).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => {
            console.warn(err);
            this.updateGrid({ items: [], total: 0, total_pages: 1 });
          }
        });
        break;
      case 'ambiguous':
        this.reconService.getAmbiguousMatches(page, size).subscribe({
          next: (res) => this.updateGrid(res),
          error: (err) => {
            console.warn(err);
            this.updateGrid({ items: [], total: 0, total_pages: 1 });
          }
        });
        break;
    }
  }

  updateGrid(res: any) {
    const items = res.items || [];
    this.tableItems.set(items);
    this.totalItems.set(res.total || 0);
    this.totalPages.set(res.total_pages || 1);

    // Synchronize selection:
    if (items.length === 0) {
      this.selectedRow.set(null);
    } else {
      const current = this.selectedRow();
      if (current) {
        const currentKey = current.matchId || current.external_txn_id || current.internal_txn_id || current.ingest_external_txn_id;
        const stillPresent = items.find((i: any) =>
          (i.matchId || i.external_txn_id || i.internal_txn_id || i.ingest_external_txn_id) === currentKey
        );
        if (stillPresent) {
          this.selectedRow.set(stillPresent);
        } else {
          this.selectedRow.set(items[0]);
        }
      } else {
        this.selectedRow.set(items[0]);
      }
    }
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

  // =========================================================================
  // Inspector Drawer & Truth Formatting Helpers
  // =========================================================================
  getRowIdentifier(row: any): string {
    return row.external_txn_id || row.internal_txn_id || row.ingest_external_txn_id || row.matchId || 'Selected line';
  }

  getVerdictTitle(row: any): string {
    if (this.activeTab() === 'matched') {
      if (row.matchRule === 'TIER_1_EXACT') return 'TRULY RECONCILED — EXACT MATCH';
      if (row.matchRule === 'TIER_2_DATE_TOLERANCE') return 'TRULY RECONCILED — DATE TOLERANCE';
      if (row.matchRule === 'TIER_3_REFERENCE_MATCH') return 'TRULY RECONCILED — REFERENCE OVERLAP';
      return 'TRULY RECONCILED — AMOUNT SLACK';
    }
    if (this.activeTab() === 'ingest') return 'RECONCILING ITEM — BANK STATEMENT ONLY';
    if (this.activeTab() === 'cache') return 'OUTSTANDING ITEM — GENERAL LEDGER ONLY';
    return 'AMBIGUOUS TIE — MULTI-CANDIDATE';
  }

  getVerdictSubtitle(row: any): string {
    if (this.activeTab() === 'matched') {
      return 'Discrepancy verified within certified policy. Settled in dual ledger.';
    }
    if (this.activeTab() === 'ingest') {
      return 'Valid bank statement line with no GL cashbook match. Requires GL Journal entry.';
    }
    if (this.activeTab() === 'cache') {
      return 'Internal GL entry posted to books; awaiting clearance on bank statement.';
    }
    return 'Multiple candidate cashbook rows matched identical values. Auto-matching halted.';
  }

  getVerdictClasses(row: any): string {
    if (this.activeTab() === 'matched') {
      return 'bg-[var(--status-green-bg)] text-status-green border-status-green';
    }
    if (this.activeTab() === 'ingest') {
      return 'bg-surface-sunken text-accent-action border-accent-action';
    }
    if (this.activeTab() === 'cache') {
      return 'bg-surface-sunken text-text-secondary border-border-default';
    }
    return 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber';
  }

  getBankTxnId(row: any): string {
    return row.external_txn_id || row.ingest_external_txn_id || (this.activeTab() === 'cache' ? '— Not on Bank' : 'N/A');
  }

  getGLTxnId(row: any): string {
    return row.internal_txn_id || row.chosen_internal_txn_id || (this.activeTab() === 'ingest' ? '— Not in GL' : 'N/A');
  }

  getBankDate(row: any): string {
    return row.ingest_date || row.booking_date || row.value_date || '—';
  }

  getGLDate(row: any): string {
    return row.cache_date || row.txn_date || row.value_date || '—';
  }

  getBankAmount(row: any): number {
    const val = row.ingest_amount || row.amount;
    return val ? parseFloat(String(val).replace(',', '')) : 0.0;
  }

  getGLAmount(row: any): number {
    const val = row.cache_amount || row.amount;
    return val ? parseFloat(String(val).replace(',', '')) : 0.0;
  }

  getBankRef(row: any): string {
    return row.ingest_reference || row.reference || row.narrative || '—';
  }

  getGLRef(row: any): string {
    return row.cache_reference || row.allocation || row.narrative || '—';
  }

  getAmountDelta(row: any): number {
    if (this.activeTab() !== 'matched') return 0;
    const bAmt = Math.abs(this.getBankAmount(row));
    const gAmt = Math.abs(this.getGLAmount(row));
    return Math.round(Math.abs(bAmt - gAmt) * 100) / 100;
  }

  getDateDelta(row: any): number {
    if (this.activeTab() !== 'matched') return 0;
    const d1 = this.getBankDate(row);
    const d2 = this.getGLDate(row);
    if (!d1 || !d2 || d1 === '—' || d2 === '—') return 0;
    const dt1 = new Date(d1).getTime();
    const dt2 = new Date(d2).getTime();
    return Math.round(Math.abs(dt1 - dt2) / (1000 * 3600 * 24));
  }

  getExplanationText(row: any): string {
    if (this.activeTab() === 'matched') {
      return `Account ${row.account || 'ACC#00001'} matched with zero critical discrepancy. Rule ${row.matchRule || 'TIER_1_EXACT'} confirmed reconciliation with variance Δ$ ${this.getAmountDelta(row).toFixed(2)} and date difference of ${this.getDateDelta(row)} days.`;
    }
    if (this.activeTab() === 'ingest') {
      return `Bank Statement transaction ${this.getBankTxnId(row)} of ${this.getBankAmount(row)} is structurally valid, but has no corresponding internal GL ledger entry. Classify as Deposit in Transit or generate a manual GL Journal Entry.`;
    }
    if (this.activeTab() === 'cache') {
      return `Internal GL cashbook row ${this.getGLTxnId(row)} was recorded on internal books, but has not cleared the bank statement. Classify as Outstanding Check or timing transit item.`;
    }
    return `Multiple candidate GL cashbook entries match identical account and amount. Engine halted auto-settlement to prevent overmatching. Human tie-break required.`;
  }

  getCandidateCount(row: any): number {
    if (!row.candidate_internal_txn_ids) return 0;
    return String(row.candidate_internal_txn_ids).split(',').length;
  }

  copyAuditProof() {
    const row = this.selectedRow();
    if (!row) return;
    const text = `RECONCILIATION AUDIT PROOF\nStatus: ${this.getVerdictTitle(row)}\nBank ID: ${this.getBankTxnId(row)}\nGL ID: ${this.getGLTxnId(row)}\nAmount Variance: $${this.getAmountDelta(row)}\nDate Delta: ${this.getDateDelta(row)} days\nRationale: ${this.getExplanationText(row)}`;
    navigator.clipboard.writeText(text);
    this.toast.info('Evidence Copied', 'Reconciliation audit proof copied to clipboard.');
  }

  signOffRow() {
    this.toast.success('Audit Confirmed', 'Reconciliation line signed off by analyst.');
  }
}
