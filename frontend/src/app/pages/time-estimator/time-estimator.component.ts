import {
  Component,
  ChangeDetectionStrategy,
  inject,
  OnInit,
  OnDestroy,
  signal,
  computed
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService, describeHttpError } from '../../core/services/pipeline.service';
import {
  TimeEstimate,
  ForecastComparison,
  RunHistoryRow,
  CalibrationSummary
} from '../../core/models/pipeline.models';
import { AsyncStateComponent } from '../../shared/components/async-state/async-state.component';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';
import { AgentReportComponent } from '../../shared/components/agent-report/agent-report.component';
import { isRunning } from '../../core/agent-states';

interface StageRow {
  label: string;
  driver: (e: TimeEstimate) => string;
  seconds: (e: TimeEstimate) => number;
  warnAbove?: number;
}

@Component({
  selector: 'app-time-estimator',
  standalone: true,
  imports: [CommonModule, FormsModule, AsyncStateComponent, SpinnerComponent, AgentReportComponent],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Processing time &amp; SLA analytics</h1>
          <p class="text-[13px] text-text-secondary">
            Local estimate calibrated from the run history, the forecast agent's prediction issued before
            processing, and the measured actual — side by side.
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
                <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.total_records }} rows)</option>
              }
            </select>
          } @else if (pipeline.overviewLoading()) {
            <span class="h-7 w-56 skeleton inline-block"></span>
          } @else {
            <span class="text-[12px] font-mono text-text-secondary">No batches available</span>
          }
        </div>
      </div>

      <app-async-state
        label="processing time estimate"
        skeleton="cards"
        [rows]="4"
        [loading]="loading()"
        [error]="error()"
        [empty]="!comparison()"
        emptyMessage="Select a batch above to view its processing time analytics."
        (retry)="reload()"
      >
        @if (comparison(); as cmp) {
          @if (estimate(); as est) {
            <!-- SLA Status & Headline ETA -->
            <div class="bg-surface border border-border-default p-5 space-y-4">
              <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border-default">
                <div>
                  <div class="text-[11px] font-mono text-text-secondary mb-1">
                    Local estimate · {{ est.batch_id }}
                  </div>
                  <div class="flex items-baseline gap-3 flex-wrap">
                    <span class="text-[24px] font-mono font-semibold text-text-primary">
                      {{ est.total_estimated_seconds | number:'1.2-2' }}s
                    </span>
                    <span class="text-[13px] text-text-secondary font-mono">estimated total runtime</span>
                    @if (cmp.actual?.wall_seconds != null) {
                      <span class="text-[13px] font-mono"
                            [ngClass]="cmp.actual!.wall_seconds! <= est.total_estimated_seconds ? 'text-status-green' : 'text-status-amber'">
                        · actual {{ cmp.actual!.wall_seconds | number:'1.2-2' }}s
                        @if (cmp.actual!.still_parked) { <span class="text-text-secondary">and counting</span> }
                      </span>
                    }
                  </div>
                </div>

                <div class="flex items-center gap-2">
                  <span class="text-[12px] text-text-secondary font-medium">SLA compliance:</span>
                  @if (est.sla_status === 'ON_TRACK') {
                    <span class="px-2 py-0.5 border border-status-green bg-[var(--status-green-bg)] text-status-green font-mono text-[12px] font-medium">
                      ON TRACK
                    </span>
                  } @else if (est.sla_status === 'AT_RISK') {
                    <span class="px-2 py-0.5 border border-status-amber bg-[var(--status-amber-bg)] text-status-amber font-mono text-[12px] font-medium">
                      AT RISK
                    </span>
                  } @else {
                    <span class="px-2 py-0.5 border border-status-red bg-[var(--status-red-bg)] text-status-red font-mono text-[12px] font-medium">
                      BREACHED
                    </span>
                  }
                  <span class="text-[11px] font-mono text-text-secondary">
                    {{ slaConsumedPct(est) | number:'1.1-1' }}% of budget
                  </span>
                </div>
              </div>

              <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[13px] font-mono">
                <div class="p-3 bg-surface-sunken border border-border-default">
                  <span class="text-text-secondary block text-[11px]">Calculated ETA</span>
                  <span class="text-text-primary font-semibold text-[14px]">{{ est.eta_timestamp }}</span>
                </div>
                <div class="p-3 bg-surface-sunken border border-border-default">
                  <span class="text-text-secondary block text-[11px]">Throughput used</span>
                  <span class="text-status-green font-semibold text-[14px]">
                    {{ est.baseline_throughput_used | number:'1.0-0' }} rec/sec
                  </span>
                </div>
                <div class="p-3 bg-surface-sunken border border-border-default">
                  <span class="text-text-secondary block text-[11px]">Batch file size</span>
                  <span class="text-text-primary font-semibold text-[14px]">
                    {{ est.file_size_mb }} MB ({{ est.file_size_bytes | number }} B)
                  </span>
                </div>
                <div class="p-3 bg-surface-sunken border border-border-default">
                  <span class="text-text-secondary block text-[11px]">SLA target limit</span>
                  <span class="text-text-primary font-semibold text-[14px]">
                    {{ est.sla_target_seconds | number:'1.0-0' }}s
                  </span>
                </div>
              </div>

              <!-- Where the constants came from -->
              <div class="text-[12px] font-mono flex items-start gap-2"
                   [ngClass]="cmp.calibration.source === 'HISTORY' ? 'text-text-secondary' : 'text-status-amber'">
                <span class="shrink-0 px-1.5 py-0.5 border text-[10px] uppercase tracking-wider"
                      [ngClass]="cmp.calibration.source === 'HISTORY'
                        ? 'border-status-green text-status-green bg-[var(--status-green-bg)]'
                        : 'border-status-amber text-status-amber bg-[var(--status-amber-bg)]'">
                  {{ cmp.calibration.source === 'HISTORY' ? 'Calibrated' : 'Default' }}
                </span>
                <span>{{ calibrationLine(cmp.calibration) }}</span>
              </div>
            </div>

            <!-- =============================================================
                 Forecast vs actual. Three columns: what the formula said, what
                 the agent predicted before processing, what was measured.
                 ============================================================= -->
            <div class="bg-surface border border-border-default mt-6">
              <div class="px-4 py-3 border-b border-border-default flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h2 class="text-[15px] font-medium text-text-primary">Forecast vs actual</h2>
                  <p class="text-[12px] text-text-secondary">
                    The agent forecast is issued at ingest, before Stage 2 runs, from this file's size and the
                    history of comparable batches. It is scored against the measured wall-clock afterwards.
                  </p>
                </div>
                <div class="flex items-center gap-2 text-[11px] font-mono shrink-0">
                  @if (forecastRunning()) {
                    <app-spinner [size]="11" label="Awaiting forecast" />
                    <span class="text-text-secondary">polling every 6s</span>
                  }
                  <a [href]="artifactUrl('forecast_input')" class="text-accent-action hover:underline" target="_blank" rel="noopener">
                    forecast input
                  </a>
                  <span class="text-text-secondary">·</span>
                  <a [href]="artifactUrl('run_history')" class="text-accent-action hover:underline" target="_blank" rel="noopener">
                    history the agent saw
                  </a>
                </div>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-border-default">
                <!-- Local estimate -->
                <div class="p-4 space-y-2">
                  <div class="text-[10px] font-mono uppercase tracking-wider text-text-secondary">Local estimate</div>
                  <div class="text-[22px] font-mono font-semibold text-text-primary">
                    {{ est.total_estimated_seconds | number:'1.2-2' }}s
                  </div>
                  <dl class="text-[12px] font-mono space-y-1">
                    <div class="flex justify-between gap-3">
                      <dt class="text-text-secondary">Machine work</dt>
                      <dd class="text-text-primary">{{ est.estimated_machine_seconds | number:'1.2-2' }}s</dd>
                    </div>
                    <div class="flex justify-between gap-3">
                      <dt class="text-text-secondary">Analyst queue wait</dt>
                      <dd class="text-text-primary">{{ est.estimated_queue_wait_sec | number:'1.2-2' }}s</dd>
                    </div>
                    @if (batchRecord()?.estimate_at_ingest_sec != null) {
                      <div class="flex justify-between gap-3">
                        <dt class="text-text-secondary">At ingest (quality unknown)</dt>
                        <dd class="text-text-primary">{{ batchRecord()!.estimate_at_ingest_sec | number:'1.2-2' }}s</dd>
                      </div>
                    }
                    @if (localErrorPct(); as err) {
                      <div class="flex justify-between gap-3 pt-1 border-t border-border-default">
                        <dt class="text-text-secondary">Error vs actual</dt>
                        <dd [ngClass]="errorClass(err)">{{ signed(err) }}%</dd>
                      </div>
                    }
                  </dl>
                </div>

                <!-- Agent forecast -->
                <div class="p-4 space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-[10px] font-mono uppercase tracking-wider text-text-secondary">Agent forecast</span>
                    @if (cmp.agent_forecast; as f) {
                      <span class="px-1.5 py-0.5 border text-[10px] font-mono uppercase tracking-wider" [ngClass]="forecastStatusClass(f.status)">
                        {{ f.status }}
                      </span>
                    }
                  </div>

                  @if (cmp.agent_forecast; as f) {
                    @switch (f.status) {
                      @case ('RECEIVED') {
                        <div class="text-[22px] font-mono font-semibold text-text-primary">
                          {{ f.forecast_seconds | number:'1.2-2' }}s
                        </div>
                        <dl class="text-[12px] font-mono space-y-1">
                          @if (f.p10_seconds != null || f.p90_seconds != null) {
                            <div class="flex justify-between gap-3">
                              <dt class="text-text-secondary">Range (p10–p90)</dt>
                              <dd class="text-text-primary">
                                {{ f.p10_seconds != null ? (f.p10_seconds | number:'1.1-1') : '?' }}s –
                                {{ f.p90_seconds != null ? (f.p90_seconds | number:'1.1-1') : '?' }}s
                              </dd>
                            </div>
                          }
                          @if (f.confidence) {
                            <div class="flex justify-between gap-3">
                              <dt class="text-text-secondary">Confidence</dt>
                              <dd class="text-text-primary">{{ f.confidence }}</dd>
                            </div>
                          }
                          @if (f.breach_probability_pct != null) {
                            <div class="flex justify-between gap-3">
                              <dt class="text-text-secondary">Breach probability</dt>
                              <dd [ngClass]="f.breach_probability_pct >= 50 ? 'text-status-red' : (f.breach_probability_pct >= 20 ? 'text-status-amber' : 'text-text-primary')">
                                {{ f.breach_probability_pct | number:'1.0-0' }}%
                              </dd>
                            </div>
                          }
                          @if (f.expected_escalation_rate_pct != null) {
                            <div class="flex justify-between gap-3">
                              <dt class="text-text-secondary">Expected escalation rate</dt>
                              <dd class="text-text-primary">{{ f.expected_escalation_rate_pct | number:'1.1-1' }}%</dd>
                            </div>
                          }
                          @if (f.error_pct != null) {
                            <div class="flex justify-between gap-3 pt-1 border-t border-border-default">
                              <dt class="text-text-secondary">Error vs actual</dt>
                              <dd [ngClass]="errorClass(f.error_pct)">{{ signed(f.error_pct) }}%</dd>
                            </div>
                          } @else if (cmp.actual?.still_parked) {
                            <div class="text-text-secondary pt-1 border-t border-border-default">Scored once the batch leaves the analyst queue.</div>
                          }
                        </dl>
                        @if (f.dashboard_line) {
                          <p class="text-[12px] text-text-primary border-l-2 border-border-strong pl-2">{{ f.dashboard_line }}</p>
                        }
                        @if (f.comparable_batches.length) {
                          <p class="text-[11px] font-mono text-text-secondary">
                            Compared against: {{ f.comparable_batches.slice(0, 4).join(', ') }}{{ f.comparable_batches.length > 4 ? '…' : '' }}
                          </p>
                        }
                      }
                      @case ('PENDING') {
                        <div class="flex items-center gap-2 text-[13px] text-text-secondary pt-2">
                          <app-spinner [size]="13" label="Awaiting forecast" />
                          <span>Submitted to the forecast agent{{ f.issued_at ? ' at ' + f.issued_at : '' }}. Waiting for its prediction.</span>
                        </div>
                      }
                      @case ('SKIPPED') {
                        <p class="text-[13px] text-text-secondary pt-2">Not requested.</p>
                        <p class="text-[12px] font-mono text-status-amber">{{ f.message || 'Set CREWAI_AGENT_FORECAST_ID in .env and restart the API.' }}</p>
                      }
                      @default {
                        <p class="text-[13px] text-text-secondary pt-2">No prediction recorded.</p>
                        @if (f.message) {
                          <p class="text-[12px] font-mono text-status-amber">{{ f.message }}</p>
                        }
                      }
                    }
                  } @else {
                    <p class="text-[13px] text-text-secondary pt-2">No forecast was issued for this batch.</p>
                  }

                  @if (cmp.execution?.output) {
                    <button (click)="showAgentOutput.set(!showAgentOutput())"
                            class="text-[11px] font-medium text-accent-action hover:underline">
                      {{ showAgentOutput() ? 'Hide agent report' : 'View agent report' }}
                    </button>
                  }
                </div>

                <!-- Measured actual -->
                <div class="p-4 space-y-2">
                  <div class="text-[10px] font-mono uppercase tracking-wider text-text-secondary">Measured actual</div>
                  @if (cmp.actual; as a) {
                    <div class="text-[22px] font-mono font-semibold"
                         [ngClass]="a.still_parked ? 'text-status-amber' : 'text-text-primary'">
                      {{ a.wall_seconds | number:'1.2-2' }}s
                    </div>
                    <dl class="text-[12px] font-mono space-y-1">
                      <div class="flex justify-between gap-3">
                        <dt class="text-text-secondary">Machine work</dt>
                        <dd class="text-text-primary">{{ a.machine_seconds | number:'1.2-2' }}s</dd>
                      </div>
                      <div class="flex justify-between gap-3">
                        <dt class="text-text-secondary">Analyst queue wait</dt>
                        <dd [ngClass]="(a.queue_wait_seconds || 0) > 0 ? 'text-status-amber' : 'text-text-primary'">
                          {{ a.queue_wait_seconds | number:'1.2-2' }}s
                        </dd>
                      </div>
                    </dl>
                    @if (a.still_parked) {
                      <p class="text-[12px] text-status-amber">
                        Parked at the analyst queue — the wait is still accruing. Clear the escalations to stop the clock.
                      </p>
                    }
                  } @else {
                    <p class="text-[13px] text-text-secondary pt-2">Not measured yet.</p>
                  }
                </div>
              </div>

              @if (showAgentOutput() && cmp.execution?.output) {
                <div class="border-t border-border-default p-4">
                  <app-agent-report [output]="cmp.execution!.output" />
                </div>
              }
            </div>

            <!-- Component-Wise Duration Breakdown -->
            <div class="bg-surface border border-border-default mt-6">
              <div class="px-4 py-3 border-b border-border-default flex items-center justify-between">
                <h2 class="text-[15px] font-medium text-text-primary">Pipeline stage execution breakdown</h2>
                <span class="text-[12px] font-mono text-text-secondary">Declared structure; throughput and queue wait are measured</span>
              </div>

              <table class="w-full text-left border-collapse">
                <thead>
                  <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
                    <th class="py-2 px-3">Stage component</th>
                    <th class="py-2 px-3 font-mono">Driver factor</th>
                    <th class="py-2 px-3 text-right font-mono">Est. duration (sec)</th>
                    <th class="py-2 px-3 text-right font-mono">Share of total</th>
                  </tr>
                </thead>
                <tbody class="text-[13px] font-mono divide-y divide-border-default">
                  @for (row of stageRows; track row.label) {
                    <tr class="even:bg-surface-sunken">
                      <td class="py-2 px-3 text-text-primary font-medium">{{ row.label }}</td>
                      <td class="py-2 px-3 text-text-secondary">{{ row.driver(est) }}</td>
                      <td class="py-2 px-3 text-right"
                          [ngClass]="row.warnAbove && row.seconds(est) > row.warnAbove ? 'text-status-amber font-semibold' : 'text-text-primary'">
                        {{ row.seconds(est) | number:'1.3-3' }}s
                      </td>
                      <td class="py-2 px-3 text-right text-text-secondary">
                        {{ share(row.seconds(est), est) | number:'1.1-1' }}%
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        }
      </app-async-state>

      <!-- =================================================================
           Run history: the knowledge base both the estimator and the
           forecast agent learn from.
           ================================================================= -->
      <div class="bg-surface border border-border-default">
        <div class="px-4 py-3 border-b border-border-default flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h2 class="text-[15px] font-medium text-text-primary">Run history &amp; forecast accuracy</h2>
            <p class="text-[12px] text-text-secondary">
              One row per completed run. Signed error: positive means over-estimated.
              Rows marked calibrated are the ones the estimator derives its constants from.
            </p>
          </div>
          <div class="flex items-center gap-3 text-[11px] font-mono shrink-0">
            @if (history()?.calibration; as cal) {
              <span class="text-text-secondary">
                {{ cal.total_runs_recorded }} runs ·
                local median error {{ cal.local_median_abs_error_pct != null ? (cal.local_median_abs_error_pct | number:'1.0-0') + '%' : '—' }} ·
                forecast median error {{ cal.forecast_median_abs_error_pct != null ? (cal.forecast_median_abs_error_pct | number:'1.0-0') + '%' : '—' }}
                ({{ cal.forecasts_received }} received)
              </span>
            }
            <a [href]="pipeline.getRunHistoryUrl()" class="text-accent-action hover:underline" target="_blank" rel="noopener">
              Download CSV
            </a>
          </div>
        </div>

        <app-async-state
          label="run history"
          skeleton="table"
          [rows]="6"
          [loading]="historyLoading()"
          [error]="historyError()"
          [empty]="!history() || history()!.rows.length === 0"
          emptyMessage="No run has completed yet. The first batch through the pipeline starts the history."
          (retry)="loadHistory()"
        >
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse min-w-[900px]">
              <thead>
                <tr class="bg-surface-sunken text-[11px] text-text-secondary font-medium">
                  <th class="py-2 px-3">Batch</th>
                  <th class="py-2 px-3">Completed</th>
                  <th class="py-2 px-3 text-right font-mono">Rows</th>
                  <th class="py-2 px-3">Outcome</th>
                  <th class="py-2 px-3 text-right font-mono">Local est.</th>
                  <th class="py-2 px-3 text-right font-mono">Forecast</th>
                  <th class="py-2 px-3 text-right font-mono">Actual</th>
                  <th class="py-2 px-3 text-right font-mono">Queue wait</th>
                  <th class="py-2 px-3 text-right font-mono">Local err.</th>
                  <th class="py-2 px-3 text-right font-mono">Forecast err.</th>
                  <th class="py-2 px-3 text-center">Calib.</th>
                </tr>
              </thead>
              <tbody class="text-[12px] font-mono divide-y divide-border-default">
                @for (r of history()?.rows ?? []; track r.batch_id) {
                  <tr class="even:bg-surface-sunken" [class.bg-[var(--status-amber-bg)]]="r.batch_id === selectedBatchId()">
                    <td class="py-1.5 px-3 text-text-primary">
                      <button (click)="onBatchChange(r.batch_id)" class="hover:underline text-left" [disabled]="!isKnownBatch(r.batch_id)">
                        {{ r.batch_id }}
                      </button>
                      @if (r.provenance !== 'LIVE') {
                        <span class="ml-1 text-[9px] uppercase tracking-wider text-text-secondary border border-border-default px-1" title="Recovered from an earlier run's SLA artefact; measured before queue wait was tracked">backfill</span>
                      }
                    </td>
                    <td class="py-1.5 px-3 text-text-secondary whitespace-nowrap">{{ r.completed_at }}</td>
                    <td class="py-1.5 px-3 text-right text-text-primary">{{ r.record_count | number }}</td>
                    <td class="py-1.5 px-3 text-text-secondary">{{ r.outcome }}</td>
                    <td class="py-1.5 px-3 text-right text-text-primary">{{ r.estimate_final_sec != null ? (r.estimate_final_sec | number:'1.2-2') + 's' : '—' }}</td>
                    <td class="py-1.5 px-3 text-right text-text-primary">{{ r.forecast_seconds != null ? (r.forecast_seconds | number:'1.2-2') + 's' : '—' }}</td>
                    <td class="py-1.5 px-3 text-right text-text-primary">{{ r.wall_seconds != null ? (r.wall_seconds | number:'1.2-2') + 's' : '—' }}</td>
                    <td class="py-1.5 px-3 text-right" [ngClass]="(r.queue_wait_seconds || 0) > 0 ? 'text-status-amber' : 'text-text-secondary'">
                      {{ r.queue_wait_seconds != null ? (r.queue_wait_seconds | number:'1.1-1') + 's' : '—' }}
                    </td>
                    <td class="py-1.5 px-3 text-right" [ngClass]="r.local_error_pct != null ? errorClass(r.local_error_pct) : 'text-text-secondary'">
                      {{ r.local_error_pct != null ? signed(r.local_error_pct) + '%' : '—' }}
                    </td>
                    <td class="py-1.5 px-3 text-right" [ngClass]="r.forecast_error_pct != null ? errorClass(r.forecast_error_pct) : 'text-text-secondary'">
                      {{ r.forecast_error_pct != null ? signed(r.forecast_error_pct) + '%' : '—' }}
                    </td>
                    <td class="py-1.5 px-3 text-center" [ngClass]="r.eligible_for_calibration ? 'text-status-green' : 'text-text-secondary'">
                      {{ r.eligible_for_calibration ? '✓' : '·' }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </app-async-state>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimeEstimatorComponent implements OnInit, OnDestroy {
  pipeline = inject(PipelineService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;

  comparison = signal<ForecastComparison | null>(null);
  loading = signal<boolean>(false);
  error = signal<string | null>(null);
  showAgentOutput = signal<boolean>(false);

  history = signal<{ rows: RunHistoryRow[]; calibration: CalibrationSummary } | null>(null);
  historyLoading = signal<boolean>(false);
  historyError = signal<string | null>(null);

  estimate = computed<TimeEstimate | null>(() => this.comparison()?.local_estimate ?? null);

  batchRecord = computed(() => {
    const id = this.selectedBatchId();
    return id ? this.batches().find(b => b.batch_id === id) ?? null : null;
  });

  /** True while the backend is still waiting on the forecast agent. */
  forecastRunning = computed(() => {
    const cmp = this.comparison();
    if (!cmp) return false;
    return cmp.agent_forecast?.status === 'PENDING' || isRunning(cmp.execution?.status);
  });

  localErrorPct = computed<number | null>(() => {
    const cmp = this.comparison();
    const wall = cmp?.actual?.wall_seconds;
    if (!cmp || wall == null || wall <= 0 || cmp.actual?.still_parked) return null;
    return ((cmp.local_estimate.total_estimated_seconds - wall) / wall) * 100;
  });

  private pollTimer?: ReturnType<typeof setInterval>;

  readonly stageRows: StageRow[] = [
    {
      label: 'Stage 1: File ingestion & parsing',
      driver: (e) => `File size I/O (${e.file_size_mb} MB)`,
      seconds: (e) => e.estimated_parse_time_sec,
    },
    {
      label: 'Stage 2: Structural gatekeeper checks',
      driver: () => 'Header, trailer, encoding checks',
      seconds: (e) => e.estimated_gate_time_sec,
    },
    {
      label: 'Stage 3: Cross-row rule validation',
      driver: (e) => `Record count (${e.total_records} rows) at ${Math.round(e.baseline_throughput_used)} rec/s`,
      seconds: (e) => e.estimated_rule_time_sec,
    },
    {
      label: 'Stage 4-5: Anomaly scoring & analyst queue',
      driver: (e) => `${e.anomaly_count} anomalies; queue wait ${e.estimated_queue_wait_sec.toFixed(1)}s`,
      seconds: (e) => e.estimated_anomaly_triage_sec,
      warnAbove: 1.0,
    },
    {
      label: 'Stage 6: Tiered GL reconciliation',
      driver: () => 'Cache lookup (Tier 1–4 waterfall)',
      seconds: (e) => e.estimated_gl_match_sec,
    },
  ];

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        const id = this.selectedBatchId();
        if (id) this.loadComparison(id);
      },
      error: () => {}
    });
    this.loadHistory();

    // The backend polls the agent platform itself; this only refreshes the
    // view while a forecast is outstanding, and nudges the platform poll so a
    // result is picked up even if the server-side poller has been restarted.
    this.pollTimer = setInterval(() => {
      const id = this.selectedBatchId();
      if (id && this.forecastRunning() && !this.loading()) {
        this.pipeline.refreshAgentOutputs(id).subscribe({ error: () => {} });
        this.loadComparison(id, true);
      }
    }, 6000);
  }

  ngOnDestroy() {
    if (this.pollTimer) clearInterval(this.pollTimer);
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.showAgentOutput.set(false);
    this.loadComparison(batchId);
  }

  reload() {
    const id = this.selectedBatchId();
    if (id) this.loadComparison(id);
    this.loadHistory();
  }

  isKnownBatch(batchId: string): boolean {
    return this.batches().some(b => b.batch_id === batchId);
  }

  loadComparison(batchId: string, silent: boolean = false) {
    if (!silent) {
      this.loading.set(true);
      this.error.set(null);
    }
    this.pipeline.loadForecast(batchId).subscribe({
      next: (cmp) => {
        const wasRunning = this.forecastRunning();
        this.comparison.set(cmp);
        this.loading.set(false);
        // A forecast that just landed changes the history table too.
        if (wasRunning && !this.forecastRunning()) this.loadHistory();
      },
      error: (err) => {
        if (!silent) {
          this.comparison.set(null);
          this.error.set(describeHttpError(err));
        }
        this.loading.set(false);
      }
    });
  }

  loadHistory() {
    this.historyLoading.set(true);
    this.historyError.set(null);
    this.pipeline.loadRunHistory(25).subscribe({
      next: (res) => {
        this.history.set({ rows: res.rows, calibration: res.calibration });
        this.historyLoading.set(false);
      },
      error: (err) => {
        this.history.set(null);
        this.historyError.set(describeHttpError(err));
        this.historyLoading.set(false);
      }
    });
  }

  artifactUrl(kind: 'forecast_input' | 'run_history'): string {
    const id = this.selectedBatchId();
    return id ? this.pipeline.getArtifactUrl(id, kind) : '#';
  }

  calibrationLine(cal: CalibrationSummary): string {
    if (cal.source === 'HISTORY') {
      const qw = cal.queue_wait_per_escalation_sec === cal.default_queue_wait_sec
        ? `queue wait ${cal.default_queue_wait_sec.toFixed(0)}s per escalation (default; no resolved escalations measured yet)`
        : `queue wait ${cal.queue_wait_per_escalation_sec.toFixed(1)}s per escalation measured`;
      return `Throughput ${Math.round(cal.baseline_throughput)} rec/s derived from ${cal.sample_size} runs on this machine ` +
        `(formula default ${Math.round(cal.default_throughput)}); ${qw}. ` +
        `Measured machine time runs ${cal.residual_factor.toFixed(2)}× the declared model.`;
    }
    return `Formula defaults: ${Math.round(cal.default_throughput)} rec/s, ${cal.default_queue_wait_sec.toFixed(0)}s per escalation. ` +
      `${cal.sample_size} of ${cal.min_runs_required} eligible runs recorded — calibration starts once enough batches of ` +
      `200+ rows have completed.`;
  }

  share(seconds: number, est: TimeEstimate): number {
    return (seconds / Math.max(0.01, est.total_estimated_seconds)) * 100;
  }

  slaConsumedPct(est: TimeEstimate): number {
    return (est.total_estimated_seconds / Math.max(1, est.sla_target_seconds)) * 100;
  }

  signed(pct: number): string {
    const rounded = Math.round(pct * 10) / 10;
    return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)}`;
  }

  errorClass(pct: number): string {
    const abs = Math.abs(pct);
    if (abs <= 25) return 'text-status-green';
    if (abs <= 100) return 'text-status-amber';
    return 'text-status-red';
  }

  forecastStatusClass(status: string): string {
    switch (status) {
      case 'RECEIVED': return 'border-status-green text-status-green bg-[var(--status-green-bg)]';
      case 'PENDING': return 'border-border-strong text-text-secondary';
      case 'SKIPPED': return 'border-border-default text-text-secondary';
      default: return 'border-status-amber text-status-amber bg-[var(--status-amber-bg)]';
    }
  }
}
