import { Component, ChangeDetectionStrategy, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { PipelineService, describeHttpError } from '../../core/services/pipeline.service';
import { ToastService } from '../../core/services/toast.service';
import { AsyncStateComponent } from '../../shared/components/async-state/async-state.component';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink, AsyncStateComponent, SpinnerComponent],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Batch status board</h1>
          <p class="text-[13px] text-text-secondary">
            End-of-day bank reconciliation pipeline telemetry, processing time estimates, and downstream dispatch.
          </p>
        </div>

        <div class="flex items-center gap-2.5">
          <button
            (click)="simulateSftpDrop()"
            [disabled]="pipeline.isProcessing()"
            class="bg-surface hover:bg-surface-sunken text-text-primary text-[13px] font-medium px-3.5 py-1.5 border border-border-default transition-colors flex items-center gap-2 disabled:opacity-50"
            title="Ingest the next statement waiting in the SFTP dropbox"
          >
            @if (pipeline.isProcessing()) {
              <app-spinner [size]="13" label="Ingesting batch" />
              <span>Running pipeline…</span>
            } @else {
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>
                <line x1="12" x2="12" y1="15" y2="3"/>
              </svg>
              <span>Pull next SFTP drop</span>
            }
          </button>

          <a
            routerLink="/gate"
            class="bg-accent-action hover:bg-accent-action-hover text-white text-[13px] font-medium px-3.5 py-1.5 border border-border-default transition-colors flex items-center gap-2"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5v14"/><path d="M5 12h14"/>
            </svg>
            <span>Ingest batch</span>
          </a>
        </div>
      </div>

      <!-- Live Operations Strip -->
      <div class="bg-surface border border-border-default">
        <div class="flex items-center justify-between px-4 pt-4 pb-1">
          <div class="text-[12px] font-mono text-text-secondary">
            System telemetry · All active batches
          </div>
          @if (pipeline.overviewLoading() && overview()) {
            <span class="text-[11px] font-mono text-text-secondary flex items-center gap-1.5">
              <app-spinner [size]="10" label="Refreshing telemetry" />
              Refreshing…
            </span>
          }
        </div>

        <app-async-state
          label="pipeline telemetry"
          skeleton="metrics"
          [rows]="6"
          [loading]="pipeline.overviewLoading() && !overview()"
          [error]="pipeline.overviewError()"
          (retry)="reload()"
        >
          <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 text-[13px] font-mono px-4 pb-4">
            <div>
              <span class="text-text-secondary block text-[11px]">Total batches</span>
              <span class="text-text-primary font-semibold text-[16px]">{{ overview()?.total_batches }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">Active batches</span>
              <span class="text-accent-action font-semibold text-[16px]">{{ overview()?.active_batches }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">Completed batches</span>
              <span class="text-status-green font-semibold text-[16px]">{{ overview()?.completed_batches }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">Quarantined</span>
              <span class="text-status-red font-semibold text-[16px]">{{ overview()?.quarantined_batches }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">Records processed</span>
              <span class="text-text-primary font-semibold text-[16px]">{{ overview()?.total_records_processed | number }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">SLA risk alerts</span>
              <span [ngClass]="slaAlertCount() > 0 ? 'text-status-red' : 'text-status-green'" class="font-semibold text-[16px]">
                {{ slaAlertCount() }}
              </span>
            </div>
          </div>
        </app-async-state>
      </div>

      <!-- Batches Processing Queue Table -->
      <div class="bg-surface border border-border-default">
        <div class="px-4 py-3 border-b border-border-default flex items-center justify-between">
          <h2 class="text-[15px] font-medium text-text-primary">Batches execution matrix</h2>
          @if (!pipeline.overviewLoading() && !pipeline.overviewError()) {
            <span class="text-[12px] font-mono text-text-secondary">
              {{ batches().length }} batches logged
            </span>
          }
        </div>

        <app-async-state
          label="batch queue"
          skeleton="table"
          [rows]="6"
          [loading]="pipeline.overviewLoading() && batches().length === 0"
          [error]="pipeline.overviewError()"
          [empty]="batches().length === 0"
          emptyMessage="No batches in the pipeline. Drop a statement into incoming_sftp/ or use “Ingest batch”."
          (retry)="reload()"
        >
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
                  <th class="py-2 px-3">Batch ID</th>
                  <th class="py-2 px-3">Source file</th>
                  <th class="py-2 px-3 text-center">Stage</th>
                  <th class="py-2 px-3 text-right font-mono">Records</th>
                  <th class="py-2 px-3 text-right font-mono">Anomalies</th>
                  <th class="py-2 px-3 text-right font-mono">Matched</th>
                  <th class="py-2 px-3 text-center">Agents</th>
                  <th class="py-2 px-3 font-mono">Est. ETA</th>
                  <th class="py-2 px-3 text-center">SLA status</th>
                  <th class="py-2 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody class="text-[13px] font-mono divide-y divide-border-default">
                @for (batch of batches(); track batch.batch_id) {
                  <tr class="even:bg-surface-sunken hover:bg-surface-sunken/60 transition-colors"
                      [ngClass]="{'bg-[var(--status-red-bg)]': batch.stage === 'GATE_QUARANTINED'}">
                    <td class="py-2 px-3 font-medium text-accent-action">
                      {{ batch.batch_id }}
                    </td>
                    <td class="py-2 px-3 text-text-primary text-[12px]">
                      {{ batch.filename }}
                      <span class="text-[11px] text-text-secondary ml-1">({{ batch.source }})</span>
                    </td>
                    <td class="py-2 px-3 text-center">
                      <span class="text-[11px] px-1.5 py-0.5 border" [ngClass]="stageClass(batch.stage)">
                        {{ batch.stage }}
                      </span>
                    </td>
                    <td class="py-2 px-3 text-right text-text-primary">
                      {{ batch.total_records | number }}
                    </td>
                    <td class="py-2 px-3 text-right"
                        [ngClass]="batch.anomaly_count > 0 ? 'text-status-amber font-semibold' : 'text-text-secondary'">
                      {{ batch.anomaly_count }}
                      @if (batch.auto_remediated_count > 0) {
                        <span class="text-[10px] text-status-green block">({{ batch.auto_remediated_count }} fixed)</span>
                      }
                    </td>
                    <td class="py-2 px-3 text-right text-status-green">
                      {{ batch.matched_count | number }}
                      @if (batch.unmatched_count > 0) {
                        <span class="text-[10px] text-text-secondary block">({{ batch.unmatched_count }} recon)</span>
                      }
                    </td>
                    <!-- Automatic multi-agent dispatch, at a glance -->
                    <td class="py-2 px-3 text-center">
                      <span class="inline-flex items-center gap-1">
                        @for (exec of agentList(batch); track exec.stage) {
                          <span
                            class="w-2 h-2 inline-block"
                            [ngClass]="agentDotClass(exec.status)"
                            [title]="exec.agent_name + ' (' + exec.stage + '): ' + exec.status"
                          ></span>
                        } @empty {
                          <span class="text-[11px] text-text-secondary">—</span>
                        }
                      </span>
                    </td>
                    <td class="py-2 px-3 text-[12px] text-text-secondary">
                      {{ batch.time_estimate?.eta_timestamp || '—' }}
                    </td>
                    <td class="py-2 px-3 text-center">
                      @if (batch.time_estimate?.sla_status === 'ON_TRACK') {
                        <span class="text-[11px] text-status-green px-1.5 py-px border border-status-green">ON TRACK</span>
                      } @else if (batch.time_estimate?.sla_status === 'AT_RISK') {
                        <span class="text-[11px] text-status-amber px-1.5 py-px border border-status-amber">AT RISK</span>
                      } @else if (batch.time_estimate?.sla_status === 'BREACHED') {
                        <span class="text-[11px] text-status-red px-1.5 py-px border border-status-red">BREACHED</span>
                      } @else {
                        <span class="text-[11px] text-text-secondary">—</span>
                      }
                    </td>
                    <td class="py-2 px-3 text-right">
                      @if (batch.stage === 'ESCALATED_FOR_REVIEW') {
                        <a routerLink="/anomalies" (click)="selectBatch(batch.batch_id)"
                           class="text-status-amber hover:underline text-[12px]">
                          Review {{ batch.escalated_count }} item{{ batch.escalated_count === 1 ? '' : 's' }}
                        </a>
                      } @else if (batch.stage === 'GATE_QUARANTINED') {
                        <a routerLink="/gate" (click)="selectBatch(batch.batch_id)"
                           class="text-status-red hover:underline text-[12px]">
                          Gate report
                        </a>
                      } @else if (batch.published) {
                        <span class="text-[11px] text-status-green">Published</span>
                      } @else if (batch.stage === 'RECONCILED') {
                        <button (click)="publishBatch(batch.batch_id)"
                                [disabled]="publishingId() === batch.batch_id"
                                class="text-accent-action hover:underline text-[12px] disabled:opacity-50 inline-flex items-center gap-1.5">
                          @if (publishingId() === batch.batch_id) {
                            <app-spinner [size]="10" label="Publishing" />
                            <span>Publishing…</span>
                          } @else {
                            <span>Publish</span>
                          }
                        </button>
                      } @else {
                        <a routerLink="/gate" (click)="selectBatch(batch.batch_id)"
                           class="text-text-secondary hover:text-text-primary text-[12px]">
                          Inspect
                        </a>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </app-async-state>
      </div>

      <!-- Downstream Publish & Consumer Broadcast Log -->
      <div class="bg-surface border border-border-default">
        <div class="flex items-center justify-between p-4 border-b border-border-default">
          <div>
            <h2 class="text-[15px] font-medium text-text-primary">Downstream event bus log</h2>
            <p class="text-[12px] text-text-secondary">
              Broadcasted batch completions and ETAs delivered to downstream consumers.
            </p>
          </div>
          <button
            (click)="loadPublishEvents()"
            [disabled]="pipeline.eventsLoading()"
            class="text-accent-action text-[12px] hover:underline disabled:opacity-50 flex items-center gap-1.5"
          >
            @if (pipeline.eventsLoading()) {
              <app-spinner [size]="11" label="Refreshing events" />
              <span>Refreshing…</span>
            } @else {
              <span>Refresh events</span>
            }
          </button>
        </div>

        <app-async-state
          label="downstream events"
          skeleton="lines"
          [rows]="3"
          [loading]="pipeline.eventsLoading() && events().length === 0"
          [error]="pipeline.eventsError()"
          [empty]="events().length === 0"
          emptyMessage="No publish events recorded yet. Completed batches broadcast here automatically."
          (retry)="loadPublishEvents()"
        >
          <div class="space-y-2 max-h-56 overflow-y-auto p-4">
            @for (evt of events(); track evt.event_id) {
              <div class="p-2.5 bg-surface-sunken border border-border-default text-[12px] font-mono flex items-start justify-between gap-3">
                <div>
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-status-green font-semibold">[{{ evt.status }}]</span>
                    <span class="text-text-primary font-medium">{{ evt.event_id }}</span>
                    <span class="text-text-secondary">· Batch: {{ evt.batch_id }}</span>
                  </div>
                  @if (evt.summary['subscribers_notified']?.length) {
                    <div class="text-[11px] text-text-secondary mt-1">
                      Subscribers: {{ evt.summary['subscribers_notified'].join(', ') }}
                    </div>
                  }
                </div>
                <span class="text-[11px] text-text-secondary shrink-0">{{ evt.published_at }}</span>
              </div>
            }
          </div>
        </app-async-state>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent implements OnInit {
  pipeline = inject(PipelineService);
  toast = inject(ToastService);

  overview = this.pipeline.overview;
  batches = this.pipeline.batches;
  events = this.pipeline.publishedEvents;

  publishingId = signal<string | null>(null);

  ngOnInit() {
    this.reload();
    this.loadPublishEvents();
  }

  reload() {
    this.pipeline.loadOverview().subscribe({ error: () => {} });
  }

  loadPublishEvents() {
    this.pipeline.loadPublishEvents().subscribe({ error: () => {} });
  }

  selectBatch(batchId: string) {
    this.pipeline.selectBatch(batchId);
  }

  slaAlertCount(): number {
    const ov = this.overview();
    if (!ov) return 0;
    return ov.sla_breaches + ov.at_risk_count;
  }

  /** Per-stage agent dispatches for a batch, ordered by pipeline stage. */
  agentList(batch: { agent_executions?: Record<string, any> }) {
    const execs = batch.agent_executions;
    if (!execs) return [];
    const order = ['STAGE_1_EXTRACTION', 'STAGE_4_ANOMALY', 'STAGE_6_RECON', 'STAGE_7_SLA'];
    return Object.values(execs).sort(
      (a: any, b: any) => order.indexOf(a.stage) - order.indexOf(b.stage)
    );
  }

  agentDotClass(status: string): string {
    switch (status) {
      case 'SUCCESS':
      case 'COMPLETED':
        return 'bg-status-green';
      case 'FAILED':
      case 'ERROR':
      case 'CANCELLED':
        return 'bg-status-red';
      case 'SKIPPED':
        return 'bg-border-strong';
      default:
        return 'bg-accent-action animate-pulse';
    }
  }

  simulateSftpDrop() {
    this.pipeline.simulateSftp().subscribe({
      next: (res) => {
        // res.message states whether this came from the real dropbox or the
        // generated sample feed — pass it through rather than paraphrasing.
        this.toast.success('Batch ingested', res.message);
      },
      error: (err) => {
        this.toast.error('Ingestion failed', describeHttpError(err));
      }
    });
  }

  publishBatch(batchId: string) {
    this.publishingId.set(batchId);
    this.pipeline.publishBatch(batchId).subscribe({
      next: () => {
        this.publishingId.set(null);
        this.toast.success('Batch published', `Dispatched ${batchId} to the downstream reconciliation bus.`);
      },
      error: (err) => {
        this.publishingId.set(null);
        this.toast.error('Publish failed', describeHttpError(err));
      }
    });
  }

  stageClass(stage: string): string {
    switch (stage) {
      case 'GATE_PASSED':
      case 'RULE_VALIDATED':
      case 'RECONCILED':
      case 'PUBLISHED':
        return 'bg-[var(--status-green-bg)] text-status-green border-status-green';
      case 'ESCALATED_FOR_REVIEW':
        return 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber';
      case 'GATE_QUARANTINED':
        return 'bg-[var(--status-red-bg)] text-status-red border-status-red';
      default:
        return 'bg-surface-sunken text-accent-action border-border-default';
    }
  }
}
