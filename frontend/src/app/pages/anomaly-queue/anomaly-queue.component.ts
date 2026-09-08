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
import { ToastService } from '../../core/services/toast.service';
import { AgentExecution, AnomalyItem } from '../../core/models/pipeline.models';
import { AsyncStateComponent } from '../../shared/components/async-state/async-state.component';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';

/** Execution states that mean the agent job is finished — polling stops here. */
const TERMINAL_STATES = new Set(['SUCCESS', 'COMPLETED', 'FAILED', 'ERROR', 'CANCELLED', 'SKIPPED']);

const STAGE_ORDER = ['STAGE_1_EXTRACTION', 'STAGE_4_ANOMALY', 'STAGE_6_RECON', 'STAGE_7_SLA'];

@Component({
  selector: 'app-anomaly-queue',
  standalone: true,
  imports: [CommonModule, FormsModule, AsyncStateComponent, SpinnerComponent],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Anomaly &amp; escalation queue</h1>
          <p class="text-[13px] text-text-secondary">
            Agentic detection of data anomalies, automated remediation audit log, and the human-in-the-loop review queue.
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
        </div>
      </div>

      <!-- =====================================================================
           Automatic multi-agent dispatch monitor.
           Stage 4 / 6 / 7 agents are fired by the orchestrator as their input
           artefacts land — nothing here needs to be started by an operator.
           ===================================================================== -->
      <div class="bg-surface border border-border-default">
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 p-4 border-b border-border-default">
          <div class="space-y-1">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="w-2 h-2 rounded-full" [ngClass]="anyAgentRunning() ? 'bg-accent-action animate-pulse' : 'bg-status-green'"></span>
              <h2 class="text-[13px] font-mono text-text-primary font-semibold uppercase tracking-wider">
                Multi-agent dispatch · automatic
              </h2>
              <span class="text-[10px] font-mono px-1.5 py-0.5 bg-surface-sunken border border-border-default text-text-secondary">
                {{ anyAgentRunning() ? 'Polling platform' : 'Idle' }}
              </span>
            </div>
            <p class="text-[12px] text-text-secondary">
              Agents run on pipeline events, not button presses. Classification spans
              <span class="text-blue-500 font-mono font-medium">Structural</span>,
              <span class="text-emerald-500 font-mono font-medium">Semantic</span>,
              <span class="text-teal-500 font-mono font-medium">Timing</span> and
              <span class="text-purple-500 font-mono font-medium">Referential</span> dimensions.
            </p>
          </div>

          <div class="flex flex-wrap items-center gap-2 shrink-0">
            <button
              (click)="refreshAgents()"
              [disabled]="refreshing() || !selectedBatchId()"
              class="bg-surface hover:bg-surface-sunken text-text-primary text-[12px] font-medium px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              @if (refreshing()) {
                <app-spinner [size]="12" label="Refreshing agent status" />
                <span>Refreshing…</span>
              } @else {
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                <span>Refresh status</span>
              }
            </button>

            @if (selectedBatchId()) {
              <a [href]="artifactUrl('anomaly_candidates')" target="_blank" download
                 class="bg-surface hover:bg-surface-sunken text-text-primary text-[12px] font-medium px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
                <span>Flagged rows CSV</span>
              </a>

              <a [href]="artifactUrl('statement')" target="_blank" download
                 class="bg-surface hover:bg-surface-sunken text-text-primary text-[12px] font-medium px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <span>Batch CSV</span>
              </a>
            }
          </div>
        </div>

        <app-async-state
          label="agent dispatch log"
          skeleton="cards"
          [rows]="3"
          [loading]="pipeline.agentsLoading() && executionList().length === 0"
          [error]="pipeline.agentsError()"
          [empty]="executionList().length === 0"
          emptyMessage="No agent has been dispatched for this batch yet. Dispatches are recorded as each stage produces its input artefact."
          (retry)="refreshAgents()"
        >
          <div class="p-4 space-y-3">
            @for (exec of executionList(); track exec.stage) {
              <div class="border border-border-default bg-surface-sunken">
                <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-2 p-3">
                  <div class="min-w-0 space-y-1">
                    <div class="flex items-center gap-2 flex-wrap text-[12px] font-mono">
                      <span class="px-1.5 py-0.5 text-[10px] border" [ngClass]="statusClass(exec.status)">
                        {{ exec.status }}
                      </span>
                      <span class="text-text-primary font-semibold">{{ stageLabel(exec.stage) }}</span>
                      <span class="text-text-secondary">· {{ exec.agent_name }}</span>
                      @if (exec.agent_id) {
                        <span class="text-text-secondary">· ID {{ exec.agent_id }}</span>
                      } @else {
                        <span class="text-status-amber">· no agent ID configured</span>
                      }
                      <span class="text-[10px] px-1.5 py-0.5 border border-border-default text-text-secondary">
                        {{ exec.trigger }}
                      </span>
                    </div>

                    <div class="text-[11px] font-mono text-text-secondary break-words">
                      @if (exec.target_file) {
                        <span>Input: {{ exec.target_file }}</span>
                      }
                      @if (exec.agent_execution_id) {
                        <span class="ml-2">· Execution {{ exec.agent_execution_id }}</span>
                      }
                      @if (exec.submitted_at) {
                        <span class="ml-2">· {{ exec.submitted_at }}</span>
                      }
                    </div>

                    @if (exec.message) {
                      <div class="text-[11px] font-mono"
                           [ngClass]="exec.status === 'FAILED' ? 'text-status-red' : 'text-text-secondary'">
                        {{ exec.message }}
                      </div>
                    }
                  </div>

                  <div class="flex items-center gap-2 shrink-0">
                    @if (isRunning(exec.status)) {
                      <span class="text-[11px] font-mono text-accent-action flex items-center gap-1.5">
                        <app-spinner [size]="11" label="Agent running" />
                        <span>Agent running…</span>
                      </span>
                    }
                    @if (exec.status === 'FAILED') {
                      <button
                        (click)="redispatch(exec)"
                        [disabled]="redispatchingStage() === exec.stage"
                        class="text-[11px] font-medium text-accent-action hover:underline disabled:opacity-50 flex items-center gap-1.5"
                      >
                        @if (redispatchingStage() === exec.stage) {
                          <app-spinner [size]="10" label="Re-dispatching" />
                          <span>Retrying…</span>
                        } @else {
                          <span>Retry dispatch</span>
                        }
                      </button>
                    }
                    @if (exec.output) {
                      <button (click)="toggleOutput(exec.stage)" class="text-[11px] font-medium text-accent-action hover:underline">
                        {{ expandedStage() === exec.stage ? 'Hide output' : 'View output' }}
                      </button>
                    }
                  </div>
                </div>

                @if (expandedStage() === exec.stage && exec.output) {
                  <pre class="whitespace-pre-wrap text-[11px] text-text-primary font-mono leading-relaxed bg-surface p-3 border-t border-border-default max-h-96 overflow-y-auto select-text">{{ formatOutput(exec.output) }}</pre>
                }
              </div>
            }
          </div>
        </app-async-state>
      </div>

      <!-- Severity & Triage Summary Strip -->
      <div class="bg-surface border border-border-default">
        <div class="text-[12px] font-mono text-text-secondary px-4 pt-4 pb-1">
          Anomaly triage overview · Batch: {{ selectedBatchId() || '—' }}
        </div>

        <app-async-state
          label="anomaly triage summary"
          skeleton="metrics"
          [rows]="4"
          [loading]="pipeline.anomaliesLoading() && anomalies().length === 0"
          [error]="pipeline.anomaliesError()"
          (retry)="reloadAnomalies()"
        >
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[13px] font-mono px-4 pb-4">
            <div>
              <span class="text-text-secondary block text-[11px]">Total anomalies</span>
              <span class="text-text-primary font-semibold text-[16px]">{{ anomalies().length }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">Auto-remediated (re-validated)</span>
              <span class="text-status-green font-semibold text-[16px]">{{ autoRemediatedCount() }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">Pending human review</span>
              <span class="text-status-amber font-semibold text-[16px]">{{ pendingEscalated().length }}</span>
            </div>
            <div>
              <span class="text-text-secondary block text-[11px]">Quarantined rows</span>
              <span class="text-status-red font-semibold text-[16px]">{{ quarantinedCount() }}</span>
            </div>
          </div>
        </app-async-state>
      </div>

      <!-- Human Escalation Queue — the one stage that blocks on a person -->
      @if (pendingEscalated().length > 0) {
        <div class="bg-surface border border-status-amber p-5 space-y-4">
          <div class="flex items-center justify-between border-b border-border-default pb-3">
            <div>
              <h2 class="text-[15px] font-medium text-status-amber flex items-center gap-2">
                <span>Human review queue</span>
                <span class="text-[11px] font-mono text-text-primary px-1.5 py-0.5 bg-surface-sunken border border-border-default">
                  {{ pendingEscalated().length }} items
                </span>
              </h2>
              <p class="text-[12px] text-text-secondary mt-0.5">
                GL reconciliation is held for this batch until every item below is signed off.
              </p>
            </div>
          </div>

          <div class="space-y-3">
            @for (item of pendingEscalated(); track item.id) {
              <div class="p-3.5 bg-surface-sunken border border-border-default space-y-2">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between text-[12px] font-mono gap-2">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="px-1.5 py-0.5 text-[10px] border" [ngClass]="severityClass(item.severity)">
                      {{ item.severity }}
                    </span>
                    <span class="text-text-primary font-semibold">Row #{{ item.row_index }}</span>
                    <span class="text-text-secondary">· Txn ID: <strong class="text-accent-action">{{ item.external_txn_id }}</strong></span>
                    <span class="text-text-secondary">· Account: {{ item.account }}</span>
                    @if (item.raw_amount) {
                      <span class="text-text-secondary">· Amount: {{ item.raw_amount }}</span>
                    }
                  </div>

                  <span class="text-text-secondary text-[11px]">
                    Confidence: <strong class="text-status-green">{{ (item.confidence_score * 100) | number:'1.0-0' }}%</strong>
                  </span>
                </div>

                <div class="text-[12px] text-text-primary">
                  <span class="text-status-red font-mono font-medium">[{{ item.error_type }}]</span>
                  <span class="ml-1.5">{{ item.description }}</span>
                </div>

                <div class="p-2.5 bg-surface border border-border-default text-[12px] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div class="font-mono text-[11px] text-text-secondary break-words">
                    @if (item.suggested_fix) {
                      Suggested fix: <code class="text-status-green font-semibold">{{ item.suggested_fix | json }}</code>
                    } @else {
                      No automated fix proposed — analyst judgement required.
                    }
                  </div>

                  <div class="flex items-center gap-2 shrink-0">
                    @if (item.suggested_fix) {
                      <button
                        (click)="resolveItem(item.id, 'APPROVE')"
                        [disabled]="resolvingId() === item.id"
                        class="bg-status-green hover:opacity-90 text-white text-[11px] font-medium px-2.5 py-1 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                      >
                        @if (resolvingId() === item.id) {
                          <app-spinner [size]="10" label="Applying fix" />
                        }
                        <span>Approve fix</span>
                      </button>
                    }

                    <button
                      (click)="resolveItem(item.id, 'QUARANTINE')"
                      [disabled]="resolvingId() === item.id"
                      class="bg-surface hover:bg-surface-sunken text-status-red text-[11px] font-medium px-2.5 py-1 border border-border-default transition-colors disabled:opacity-50"
                    >
                      Quarantine row
                    </button>
                  </div>
                </div>
              </div>
            }
          </div>
        </div>
      }

      <!-- Complete Anomalies & Auto-Remediation Ledger -->
      <div class="bg-surface border border-border-default">
        <div class="px-4 py-3 border-b border-border-default flex items-center justify-between">
          <h2 class="text-[15px] font-medium text-text-primary">All detected anomalies &amp; remediation log</h2>
          @if (!pipeline.anomaliesLoading() && !pipeline.anomaliesError()) {
            <span class="text-[12px] font-mono text-text-secondary">{{ anomalies().length }} entries</span>
          }
        </div>

        <app-async-state
          label="anomaly ledger"
          skeleton="table"
          [rows]="6"
          [loading]="pipeline.anomaliesLoading() && anomalies().length === 0"
          [error]="pipeline.anomaliesError()"
          [empty]="anomalies().length === 0"
          emptyMessage="No anomalies detected for the active batch."
          (retry)="reloadAnomalies()"
        >
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="bg-surface-sunken text-[12px] text-text-secondary font-medium">
                  <th class="py-2 px-3 font-mono">Row</th>
                  <th class="py-2 px-3 font-mono">Txn ID</th>
                  <th class="py-2 px-3">Error type</th>
                  <th class="py-2 px-3 text-center">Severity</th>
                  <th class="py-2 px-3 font-mono">Category</th>
                  <th class="py-2 px-3">Remediation detail</th>
                  <th class="py-2 px-3 text-center">Status</th>
                </tr>
              </thead>
              <tbody class="text-[12px] font-mono divide-y divide-border-default">
                @for (item of anomalies(); track item.id) {
                  <tr class="even:bg-surface-sunken hover:bg-surface-sunken/60 transition-colors">
                    <td class="py-2 px-3 text-text-secondary">#{{ item.row_index }}</td>
                    <td class="py-2 px-3 text-accent-action font-medium">{{ item.external_txn_id }}</td>
                    <td class="py-2 px-3 text-text-primary">{{ item.error_type }}</td>
                    <td class="py-2 px-3 text-center">
                      <span class="px-1.5 py-0.5 text-[10px] border" [ngClass]="severityClass(item.severity)">
                        {{ item.severity }}
                      </span>
                    </td>
                    <td class="py-2 px-3">
                      <span class="px-1.5 py-0.5 text-[10px] font-mono border" [ngClass]="categoryClass(item.category)">
                        {{ item.category }}
                      </span>
                    </td>
                    <td class="py-2 px-3 text-text-primary">
                      {{ item.remediation_notes || item.description }}
                    </td>
                    <td class="py-2 px-3 text-center">
                      @if (item.status === 'AUTO_REMEDIATED') {
                        <span class="text-[10px] text-status-green px-1.5 py-px border border-status-green">AUTO-FIXED</span>
                      } @else if (item.status === 'HUMAN_RESOLVED') {
                        <span class="text-[10px] text-accent-action px-1.5 py-px border border-accent-action">RESOLVED</span>
                      } @else if (item.status === 'ESCALATED') {
                        <span class="text-[10px] text-status-amber px-1.5 py-px border border-status-amber">PENDING</span>
                      } @else {
                        <span class="text-[10px] text-status-red px-1.5 py-px border border-status-red">QUARANTINED</span>
                      }
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
export class AnomalyQueueComponent implements OnInit, OnDestroy {
  pipeline = inject(PipelineService);
  toast = inject(ToastService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;
  anomalies = this.pipeline.currentAnomalies;

  refreshing = signal<boolean>(false);
  redispatchingStage = signal<string | null>(null);
  resolvingId = signal<string | null>(null);
  expandedStage = signal<string | null>(null);

  /** Agent dispatches for the active batch, ordered by pipeline stage. */
  executionList = computed<AgentExecution[]>(() =>
    Object.values(this.pipeline.agentExecutions()).sort(
      (a, b) => STAGE_ORDER.indexOf(a.stage) - STAGE_ORDER.indexOf(b.stage)
    )
  );

  anyAgentRunning = computed(() =>
    this.executionList().some(e => this.isRunning(e.status))
  );

  private pollTimer?: ReturnType<typeof setInterval>;

  ngOnInit() {
    this.pipeline.loadOverview().subscribe({
      next: () => {
        const id = this.selectedBatchId();
        if (id) this.loadBatchData(id);
      },
      error: () => {}
    });

    // While any agent job is in flight, keep pulling its output from the
    // platform so the operator never has to press anything to see progress.
    this.pollTimer = setInterval(() => {
      const id = this.selectedBatchId();
      if (id && this.anyAgentRunning() && !this.refreshing()) {
        this.pipeline.refreshAgentOutputs(id).subscribe({ error: () => {} });
      }
    }, 6000);
  }

  ngOnDestroy() {
    if (this.pollTimer) clearInterval(this.pollTimer);
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.expandedStage.set(null);
    this.loadBatchData(batchId);
  }

  loadBatchData(batchId: string) {
    this.pipeline.loadBatchAnomalies(batchId).subscribe({ error: () => {} });
    this.pipeline.loadAgentStatus(batchId).subscribe({ error: () => {} });
  }

  reloadAnomalies() {
    const id = this.selectedBatchId();
    if (id) this.pipeline.loadBatchAnomalies(id).subscribe({ error: () => {} });
  }

  refreshAgents() {
    const id = this.selectedBatchId();
    if (!id) return;
    this.refreshing.set(true);
    this.pipeline.refreshAgentOutputs(id).subscribe({
      next: () => this.refreshing.set(false),
      error: (err) => {
        this.refreshing.set(false);
        this.toast.error('Agent status unavailable', describeHttpError(err));
      }
    });
  }

  redispatch(exec: AgentExecution) {
    const id = this.selectedBatchId();
    if (!id) return;

    this.redispatchingStage.set(exec.stage);
    // Null agent_id means the stage has none configured; let the backend
    // resolve the stage's own ID (and report clearly if there isn't one).
    this.pipeline.redispatchAgent(id, exec.stage, exec.agent_id ?? undefined).subscribe({
      next: (res) => {
        this.redispatchingStage.set(null);
        this.toast.success(
          'Agent re-dispatched',
          `${res.agent_name} resubmitted for ${this.stageLabel(res.stage)}.`
        );
      },
      error: (err) => {
        this.redispatchingStage.set(null);
        this.toast.error('Re-dispatch failed', describeHttpError(err));
      }
    });
  }

  toggleOutput(stage: string) {
    this.expandedStage.update(v => (v === stage ? null : stage));
  }

  formatOutput(output: any): string {
    if (typeof output === 'string') return output;
    return JSON.stringify(output, null, 2);
  }

  artifactUrl(kind: 'statement' | 'anomaly_candidates'): string {
    const id = this.selectedBatchId();
    return id ? this.pipeline.getArtifactUrl(id, kind) : '#';
  }

  isRunning(status: string): boolean {
    return !TERMINAL_STATES.has(status);
  }

  stageLabel(stage: string): string {
    switch (stage) {
      case 'STAGE_1_EXTRACTION': return 'Stage 1 · Extraction';
      case 'STAGE_4_ANOMALY': return 'Stage 4 · Anomaly scoring';
      case 'STAGE_6_RECON': return 'Stage 6 · Recon exceptions';
      case 'STAGE_7_SLA': return 'Stage 7 · SLA urgency';
      default: return stage;
    }
  }

  statusClass(status: string): string {
    switch (status) {
      case 'SUCCESS':
      case 'COMPLETED':
        return 'bg-[var(--status-green-bg)] text-status-green border-status-green';
      case 'FAILED':
      case 'ERROR':
      case 'CANCELLED':
        return 'bg-[var(--status-red-bg)] text-status-red border-status-red';
      case 'SKIPPED':
        return 'bg-surface-sunken text-text-secondary border-border-default';
      default:
        return 'bg-surface-sunken text-accent-action border-accent-action';
    }
  }

  autoRemediatedCount(): number {
    return this.anomalies().filter(a => a.status === 'AUTO_REMEDIATED').length;
  }

  pendingEscalated(): AnomalyItem[] {
    return this.anomalies().filter(a => a.status === 'ESCALATED');
  }

  quarantinedCount(): number {
    return this.anomalies().filter(a => a.status === 'QUARANTINED').length;
  }

  resolveItem(anomalyId: string, action: 'APPROVE' | 'QUARANTINE') {
    const batchId = this.selectedBatchId();
    if (!batchId) return;

    this.resolvingId.set(anomalyId);
    this.pipeline.resolveEscalation(batchId, anomalyId, { action }).subscribe({
      next: (b) => {
        this.resolvingId.set(null);
        this.toast.success(
          'Resolution applied',
          b.escalated_count === 0
            ? `Queue cleared — batch advanced to ${b.stage} and reconciled automatically.`
            : `Row ${action === 'APPROVE' ? 'approved' : 'quarantined'}. ${b.escalated_count} item(s) still pending.`
        );
        this.pipeline.loadAgentStatus(batchId).subscribe({ error: () => {} });
      },
      error: (err) => {
        this.resolvingId.set(null);
        this.toast.error('Resolution failed', describeHttpError(err));
      }
    });
  }

  categoryClass(cat: string): string {
    switch (cat?.toUpperCase()) {
      case 'STRUCTURAL':
        return 'bg-blue-500/10 text-blue-500 border-blue-500/30';
      case 'SEMANTIC':
        return 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30';
      case 'TIMING':
        return 'bg-teal-500/10 text-teal-500 border-teal-500/30';
      case 'REFERENTIAL':
        return 'bg-purple-500/10 text-purple-500 border-purple-500/30';
      default:
        return 'bg-surface-sunken text-text-secondary border-border-default';
    }
  }

  severityClass(sev: string): string {
    switch (sev) {
      case 'CRITICAL':
        return 'bg-[var(--status-red-bg)] text-status-red border-status-red';
      case 'HIGH':
        return 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber';
      case 'MEDIUM':
        return 'bg-surface-sunken text-tier-2 border-border-default';
      default:
        return 'bg-surface-sunken text-text-secondary border-border-default';
    }
  }
}
