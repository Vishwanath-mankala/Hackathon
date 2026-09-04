import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ReconciliationService } from '../../core/services/recon.service';
import { ToastService } from '../../core/services/toast.service';
import { ManifestRecord } from '../../core/models/recon.models';
import { StatusPillComponent } from '../../shared/components/status-pill/status-pill.component';

@Component({
  selector: 'app-feed-ingestion',
  standalone: true,
  imports: [CommonModule, FormsModule, StatusPillComponent],
  template: `
    <div class="space-y-8 animate-fade-in">
      <!-- Page Header -->
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-border-default pb-6">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Feed ingestion</h1>
          <p class="text-[13px] text-text-secondary">
            Segment monolithic 60,000+ row exports into a pre-loaded internal cashbook cache and sequential bank statement drops.
          </p>
        </div>

        <button
          (click)="loadManifest()"
          class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-refresh-cw"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
          <span>Refresh manifest</span>
        </button>
      </div>

      <!-- Configuration Section -->
      <div class="bg-surface border border-border-default p-5 space-y-6">
        <h2 class="text-[16px] font-medium text-text-primary mb-4">Batch configuration</h2>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          <!-- Strategy Picker -->
          <div class="flex flex-col">
            <label class="text-[13px] text-text-secondary font-medium mb-1.5">
              Batching strategy
            </label>
            <select
              [(ngModel)]="splitBy"
              class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full"
            >
              <option value="size">Fixed batch size (e.g. 500 rows per simulated drop)</option>
              <option value="date">Calendar day grouping (One file per booking date)</option>
            </select>
          </div>

          <!-- Batch Size (if size) -->
          <div class="flex flex-col">
            <label class="text-[13px] text-text-secondary font-medium mb-1.5">
              Rows per batch
            </label>
            <input
              type="number"
              [(ngModel)]="batchSize"
              [disabled]="splitBy !== 'size'"
              min="50"
              max="5000"
              step="50"
              class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full disabled:opacity-50"
            />
          </div>

          <!-- Custom File Input -->
          <div class="flex flex-col">
            <label class="text-[13px] text-text-secondary font-medium mb-1.5">
              Source file CSV
            </label>
            <input
              type="file"
              accept=".csv"
              (change)="onFileSelected($event)"
              class="bg-surface-sunken border border-border-default text-text-primary font-mono text-[13px] px-3 py-2 focus:border-border-strong focus:outline-none w-full file:bg-accent-action file:text-white file:border-0 file:px-2.5 file:py-1 file:text-[12px] file:font-medium cursor-pointer"
            />
          </div>
        </div>

        <div class="flex items-center justify-between pt-2">
          <p class="text-[11px] text-text-secondary">
            * Leaves original GL internal cashbook (A-side) in cache, segments external statement (B-side) into manifest.
          </p>

          <button
            (click)="runSplit()"
            [disabled]="loading()"
            class="bg-accent-action hover:bg-accent-action-hover text-white font-medium text-[13px] px-4 py-2 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            @if (loading()) {
              <span class="inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent animate-spin"></span>
              <span>Splitting feed...</span>
            } @else {
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-zap"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              <span>Execute batch segmentation</span>
            }
          </button>
        </div>
      </div>

      <!-- Batch Manifest Grid -->
      <div class="bg-surface border border-border-default">
        <div class="flex items-center justify-between border-b border-border-default p-5">
          <div>
            <h3 class="text-[16px] font-medium text-text-primary mb-1">
              Active ingestion manifest
            </h3>
            <p class="text-[13px] text-text-secondary">
              Ordered sequence of statement batch files ready for structural gating and simulation matching.
            </p>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-[13px] text-text-secondary">
              Total batches: <strong class="text-text-primary font-mono">{{ manifestRecords().length }}</strong>
            </span>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr>
                <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Seq</th>
                <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Batch filename</th>
                <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3 text-right">Declared count</th>
                <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3 text-right">Declared total ($)</th>
                <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3">Booking date range</th>
                <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3 text-center">Status</th>
                <th class="bg-surface-sunken text-[12px] text-text-secondary font-medium py-2 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="text-[13px]">
              @for (batch of manifestRecords(); track batch.file) {
                <tr class="even:bg-surface-sunken hover:bg-[var(--status-green-bg)] h-[36px]">
                  <td class="py-1 px-3 text-text-secondary font-mono">#{{ batch.sequence }}</td>
                  <td class="py-1 px-3 text-text-primary font-mono flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-file-text"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>
                    <span>{{ batch.file }}</span>
                  </td>
                  <td class="py-1 px-3 text-right font-mono text-text-primary">{{ batch.declared_record_count }}</td>
                  <td class="py-1 px-3 text-right font-mono text-text-primary">
                    {{ batch.declared_control_total | currency:'USD':'symbol':'1.2-2' }}
                  </td>
                  <td class="py-1 px-3 text-text-secondary font-mono">
                    {{ batch.min_booking_date || 'N/A' }} &rarr; {{ batch.max_booking_date || 'N/A' }}
                  </td>
                  <td class="py-1 px-3 text-center">
                    <app-status-pill type="pass" text="READY" />
                  </td>
                  <td class="py-1 px-3 text-right">
                    <button
                      (click)="downloadBatch(batch.file)"
                      class="bg-surface hover:bg-surface-sunken text-text-primary font-medium text-[12px] px-3 py-1 border border-border-default transition-colors"
                    >
                      Download CSV
                    </button>
                  </td>
                </tr>
              } @empty {
                <tr class="h-[36px]">
                  <td colspan="7" class="py-4 text-center text-text-secondary text-[13px]">
                    No ingestion manifest loaded. Click "Execute batch segmentation" to generate batch files.
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FeedIngestionComponent implements OnInit {
  private reconService = inject(ReconciliationService);
  private toast = inject(ToastService);

  splitBy: 'size' | 'date' = 'size';
  batchSize: number = 500;
  selectedFile: File | null = null;

  loading = signal<boolean>(false);
  manifestRecords = signal<ManifestRecord[]>([]);

  ngOnInit() {
    this.loadManifest();
  }

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.selectedFile = input.files[0];
    }
  }

  loadManifest() {
    this.reconService.getManifest().subscribe({
      next: (res) => {
        this.manifestRecords.set(res.records || []);
      },
      error: (err) => {
        console.warn('Could not load existing manifest:', err);
      }
    });
  }

  runSplit() {
    this.loading.set(true);
    this.reconService.splitFeed(this.selectedFile, null, this.splitBy, this.batchSize).subscribe({
      next: (res) => {
        this.loading.set(false);
        this.manifestRecords.set(res.manifest);
        this.toast.success(
          'Feed Split Complete',
          `Successfully generated ${res.batch_count} statement batches and pre-loaded ${res.cache_rows} cashbook cache rows.`
        );
      },
      error: (err) => {
        this.loading.set(false);
        this.toast.error('Segmentation Failed', err?.error?.detail || 'An unexpected error occurred during splitting.');
      }
    });
  }

  downloadBatch(filename: string) {
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
        this.toast.info('Download Started', filename);
      },
      error: () => this.toast.error('Download Failed', `Could not download ${filename}`)
    });
  }
}
