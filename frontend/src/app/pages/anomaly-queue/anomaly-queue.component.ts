import { Component, ChangeDetectionStrategy, inject, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PipelineService } from '../../core/services/pipeline.service';
import { ToastService } from '../../core/services/toast.service';
import { AnomalyItem, BatchRecord } from '../../core/models/pipeline.models';

@Component({
  selector: 'app-anomaly-queue',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6 animate-fade-in">
      <!-- Section Header -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-border-default gap-3">
        <div>
          <h1 class="text-[20px] font-medium text-text-primary mb-1">Anomaly & escalation queue</h1>
          <p class="text-[13px] text-text-secondary">
            Agentic detection of data anomalies, automated remediation audit logs, and human-in-the-loop review queue.
          </p>
        </div>

        <div class="flex items-center gap-2">
          <label class="text-[12px] text-text-secondary font-medium">Batch:</label>
          <select
            [ngModel]="selectedBatchId()"
            (ngModelChange)="onBatchChange($event)"
            class="bg-surface-sunken border border-border-default text-text-primary text-[12px] font-mono px-2.5 py-1.5 focus:border-border-strong focus:outline-none"
          >
            @for (b of batches(); track b.batch_id) {
              <option [value]="b.batch_id">{{ b.batch_id }} ({{ b.stage }})</option>
            }
          </select>
        </div>
      </div>

      <!-- Stage 4: External Agent Integration & File Export Bar -->
      <div class="bg-surface border border-border-default p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div class="space-y-1">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-status-green animate-pulse"></span>
            <span class="text-[12px] font-mono text-text-primary font-semibold uppercase tracking-wider">
              Stage 4 Agentic Classifier · Agent ID: 7723
            </span>
            <span class="text-[10px] font-mono px-1.5 py-0.5 bg-surface-sunken border border-border-default text-text-secondary">
              Aava AI Cloud
            </span>
          </div>
          <p class="text-[12px] text-text-secondary">
            Multi-agent classification across 4 dimensions:
            <span class="text-blue-500 font-mono font-medium ml-1">Structural</span>,
            <span class="text-emerald-500 font-mono font-medium ml-1">Semantic</span>,
            <span class="text-teal-500 font-mono font-medium ml-1">Timing</span>,
            <span class="text-purple-500 font-mono font-medium ml-1">Referential</span>.
          </p>

          @if (activeAgentJob()) {
            <div class="mt-2 text-[11px] font-mono text-status-green flex flex-wrap items-center gap-2 bg-surface-sunken p-2 border border-border-default">
              <span>Job #{{ activeAgentJob()?.job_id || 'Active' }}</span>
              <span>·</span>
              <span class="truncate max-w-[280px]">Execution: {{ activeAgentJob()?.agent_execution_id }}</span>
              <span>·</span>
              <span class="px-1.5 py-0.5 bg-status-green/20 text-status-green font-semibold">
                {{ activeAgentJob()?.output_details?.status || 'SUBMITTED' }}
              </span>
              <button
                (click)="fetchAgentOutput()"
                [disabled]="fetchingOutput()"
                class="ml-auto text-[11px] text-accent-action hover:underline font-mono flex items-center gap-1"
              >
                @if (fetchingOutput()) {
                  <span class="inline-block w-2.5 h-2.5 border-2 border-accent-action border-t-transparent rounded-full animate-spin"></span>
                  <span>Fetching...</span>
                } @else {
                  <span>Fetch Agent Output</span>
                }
              </button>
            </div>

            @if (agentOutput()) {
              <div class="mt-2 p-3 bg-surface border border-border-default text-[11px] font-mono max-h-96 overflow-y-auto space-y-2 shadow-sm">
                <div class="flex items-center justify-between text-text-primary font-semibold border-b border-border-default pb-2">
                  <div class="flex items-center gap-2">
                    <span
                      class="inline-block w-2 h-2 rounded-full"
                      [class.bg-status-green]="agentOutput()?.status === 'SUCCESS'"
                      [class.bg-status-amber]="agentOutput()?.status === 'IN_PROGRESS'"
                      [class.bg-status-red]="agentOutput()?.status === 'FAILED'"
                    ></span>
                    <span>{{ agentOutput()?.agentName || 'Agent Execution Report' }}</span>
                    <span
                      class="px-1.5 py-0.2 text-[10px] font-semibold border"
                      [class.border-status-green]="agentOutput()?.status === 'SUCCESS'"
                      [class.text-status-green]="agentOutput()?.status === 'SUCCESS'"
                      [class.border-status-amber]="agentOutput()?.status === 'IN_PROGRESS'"
                      [class.text-status-amber]="agentOutput()?.status === 'IN_PROGRESS'"
                      [class.border-status-red]="agentOutput()?.status === 'FAILED'"
                      [class.text-status-red]="agentOutput()?.status === 'FAILED'"
                    >
                      {{ agentOutput()?.status || 'RECEIVED' }}
                    </span>
                  </div>
                  <div class="flex items-center gap-2">
                    <span class="text-[10px] text-text-secondary">{{ agentOutput()?.modifiedAt || agentOutput()?.createdAt }}</span>
                    <button (click)="agentOutput.set(null)" class="text-text-secondary hover:text-text-primary text-[11px] font-mono px-1">✕</button>
                  </div>
                </div>
                <pre class="whitespace-pre-wrap text-[11px] text-text-primary font-mono leading-relaxed bg-surface-sunken p-2.5 border border-border-default select-text">{{ agentOutput()?.output || (agentOutput() | json) }}</pre>
              </div>
            }
          }
        </div>

        <div class="flex flex-wrap items-center gap-2 shrink-0">
          <select
            [value]="selectedAgentId()"
            (change)="onAgentSelect($event)"
            class="bg-surface-sunken border border-border-default text-text-primary text-[12px] px-2 py-1.5 font-mono focus:outline-none focus:border-accent-action"
          >
            @for (agent of availableAgents(); track agent.id) {
              <option [value]="agent.id">{{ agent.id }} · {{ agent.name }}</option>
            }
          </select>

          <button
            (click)="triggerAgent()"
            [disabled]="submittingAgent() || !selectedBatchId()"
            class="bg-accent-action hover:opacity-90 disabled:opacity-50 text-white text-[12px] font-medium px-3 py-1.5 transition-colors flex items-center gap-1.5"
          >
            @if (submittingAgent()) {
              <span class="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
              <span>Submitting...</span>
            } @else {
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>
              <span>Send to Agent ({{ selectedAgentId() }})</span>
            }
          </button>

          <a
            [href]="anomalyFileUrl()"
            target="_blank"
            download
            class="bg-surface hover:bg-surface-sunken text-text-primary text-[12px] font-medium px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg>
            <span>Flagged rows CSV</span>
          </a>

          <a
            [href]="batchFileUrl()"
            target="_blank"
            download
            class="bg-surface hover:bg-surface-sunken text-text-primary text-[12px] font-medium px-3 py-1.5 border border-border-default transition-colors flex items-center gap-1.5"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span>Batch CSV</span>
          </a>
        </div>
      </div>

      <!-- Severity & Triage Summary Strip -->
      <div class="bg-surface border border-border-default p-4">

        <div class="text-[12px] font-mono text-text-secondary mb-2">
          Anomaly triage overview · Batch: {{ selectedBatchId() }}
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[13px] font-mono">
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
            <span class="text-status-amber font-semibold text-[16px]">{{ pendingEscalatedCount() }}</span>
          </div>
          <div>
            <span class="text-text-secondary block text-[11px]">Quarantined rows</span>
            <span class="text-status-red font-semibold text-[16px]">{{ quarantinedCount() }}</span>
          </div>
        </div>
      </div>

      <!-- Human Escalation Queue (Active Reviews) -->
      @if (pendingEscalatedCount() > 0) {
        <div class="bg-surface border border-status-amber p-5 space-y-4">
          <div class="flex items-center justify-between border-b border-border-default pb-3">
            <div>
              <h2 class="text-[15px] font-medium text-status-amber flex items-center gap-2">
                <span>Human review queue</span>
                <span class="text-[11px] font-mono text-text-primary px-1.5 py-0.2 bg-surface-sunken border border-border-default">
                  {{ pendingEscalatedCount() }} items
                </span>
              </h2>
              <p class="text-[12px] text-text-secondary mt-0.5">
                Financial, duplicate, or referential anomalies requiring analyst authorization before GL matching.
              </p>
            </div>
          </div>

          <div class="space-y-3">
            @for (item of pendingEscalated(); track item.id) {
              <div class="p-3.5 bg-surface-sunken border border-border-default space-y-2">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between text-[12px] font-mono gap-2">
                  <div class="flex items-center gap-2">
                    <span class="px-1.5 py-0.2 text-[10px] border border-status-amber text-status-amber font-semibold">
                      {{ item.severity }}
                    </span>
                    <span class="text-text-primary font-semibold">Row #{{ item.row_index }}</span>
                    <span class="text-text-secondary">· Txn ID: <strong class="text-accent-action">{{ item.external_txn_id }}</strong></span>
                    <span class="text-text-secondary">· Account: {{ item.account }}</span>
                    <span class="text-text-secondary">· Amount: {{ item.raw_amount || 'N/A' }}</span>
                  </div>

                  <span class="text-text-secondary text-[11px]">
                    Confidence: <strong class="text-status-green">{{ (item.confidence_score * 100) | number:'1.0-0' }}%</strong>
                  </span>
                </div>

                <div class="text-[12px] text-text-primary">
                  <span class="text-status-red font-mono font-medium">[{{ item.error_type }}]</span>
                  <span class="ml-1.5">{{ item.description }}</span>
                </div>

                <!-- Suggested Remediation Box -->
                @if (item.suggested_fix) {
                  <div class="p-2.5 bg-surface border border-border-default text-[12px] flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div class="font-mono text-[11px] text-text-secondary">
                      Suggested Fix: <code class="text-status-green font-semibold">{{ item.suggested_fix | json }}</code>
                    </div>

                    <div class="flex items-center gap-2">
                      <button
                        (click)="resolveItem(item.id, 'APPROVE')"
                        class="bg-status-green hover:opacity-90 text-white text-[11px] font-medium px-2.5 py-1 transition-colors"
                      >
                        Approve fix
                      </button>

                      <button
                        (click)="resolveItem(item.id, 'QUARANTINE')"
                        class="bg-surface hover:bg-surface-sunken text-status-red text-[11px] font-medium px-2.5 py-1 border border-border-default transition-colors"
                      >
                        Quarantine row
                      </button>
                    </div>
                  </div>
                }
              </div>
            }
          </div>
        </div>
      }

      <!-- Complete Anomalies & Auto-Remediation Ledger Table -->
      <div class="bg-surface border border-border-default">
        <div class="px-4 py-3 border-b border-border-default flex items-center justify-between">
          <h2 class="text-[15px] font-medium text-text-primary">All detected data anomalies & remediation log</h2>
          <span class="text-[12px] font-mono text-text-secondary">
            {{ anomalies().length }} entries
          </span>
        </div>

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
                    <span class="px-1.5 py-0.2 text-[10px] border"
                          [ngClass]="severityClass(item.severity)">
                      {{ item.severity }}
                    </span>
                  </td>
                  <td class="py-2 px-3">
                    <span class="px-1.5 py-0.5 text-[10px] font-mono border"
                          [ngClass]="categoryClass(item.category)">
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
              } @empty {
                <tr>
                  <td colspan="7" class="py-8 text-center text-text-secondary text-[12px]">
                    No anomalies detected for the active batch.
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
export class AnomalyQueueComponent implements OnInit {
  pipeline = inject(PipelineService);
  toast = inject(ToastService);

  batches = this.pipeline.batches;
  selectedBatchId = this.pipeline.selectedBatchId;
  anomalies = this.pipeline.currentAnomalies;

  submittingAgent = signal<boolean>(false);
  fetchingOutput = signal<boolean>(false);
  activeAgentJob = signal<any>(null);
  agentOutput = signal<any>(null);

  selectedAgentId = signal<string>('56800');
  availableAgents = signal<Array<any>>([
    { id: '56800', name: 'Enterprise Risk & Anomaly Detection Engine A5', stage: 'Stage 4: Anomaly & Risk' },
    { id: '55551', name: 'SLA Analysis & Urgency Classifier', stage: 'Stage 5: SLA Prediction' },
    { id: '56797', name: 'Verification Reconciliation Specialist', stage: 'Stage 6: Recon Review' },
    { id: '56231', name: 'Financial Statement Extraction Agent', stage: 'Stage 2: Data Extraction' },
    { id: '7723', name: 'Frontend Architecture Collab Agent', stage: 'Workbench Collab' }
  ]);

  batchFileUrl = computed(() => {
    const bId = this.selectedBatchId();
    return bId ? this.pipeline.getBatchFileUrl(bId) : '#';
  });

  anomalyFileUrl = computed(() => {
    const bId = this.selectedBatchId();
    return bId ? this.pipeline.getAnomalyFileUrl(bId) : '#';
  });

  ngOnInit() {
    this.pipeline.loadAvailableAgents().subscribe({
      next: (agents) => {
        if (agents && agents.length > 0) {
          this.availableAgents.set(agents);
          const defaultAgent = agents.find(a => a.is_default);
          if (defaultAgent) {
            this.selectedAgentId.set(defaultAgent.id);
          }
        }
      }
    });

    this.pipeline.loadOverview().subscribe({
      next: () => {
        if (this.selectedBatchId()) {
          this.loadBatchData(this.selectedBatchId()!);
        }
      }
    });
  }

  onBatchChange(batchId: string) {
    this.pipeline.selectBatch(batchId);
    this.loadBatchData(batchId);
  }

  onAgentSelect(event: Event) {
    const val = (event.target as HTMLSelectElement).value;
    this.selectedAgentId.set(val);
  }

  loadBatchData(batchId: string) {
    this.pipeline.loadBatchAnomalies(batchId).subscribe();
    this.pipeline.loadBatchAgentStatus(batchId).subscribe({
      next: (info) => {
        if (info && info.agent_execution) {
          this.activeAgentJob.set(info.agent_execution);
          if (info.agent_execution.output_details) {
            this.agentOutput.set(info.agent_execution.output_details);
          } else {
            this.agentOutput.set(null);
          }
        } else {
          this.activeAgentJob.set(null);
          this.agentOutput.set(null);
        }
      }
    });
  }

  autoRemediatedCount(): number {
    return this.anomalies().filter(a => a.status === 'AUTO_REMEDIATED').length;
  }

  pendingEscalatedCount(): number {
    return this.pendingEscalated().length;
  }

  pendingEscalated(): AnomalyItem[] {
    return this.anomalies().filter(a => a.status === 'ESCALATED');
  }

  quarantinedCount(): number {
    return this.anomalies().filter(a => a.status === 'QUARANTINED').length;
  }

  triggerAgent() {
    const batchId = this.selectedBatchId();
    if (!batchId) return;

    const agentId = this.selectedAgentId();
    this.submittingAgent.set(true);
    this.pipeline.triggerAgentClassification(batchId, true, agentId).subscribe({
      next: (res) => {
        this.submittingAgent.set(false);
        this.activeAgentJob.set(res);
        this.agentOutput.set(null);
        this.toast.success(
          'Agent Dispatched',
          `Submitted to Aava AI Agent ${agentId}. Job ID: ${res.job_id || 'Active'} · Execution: ${res.agent_execution_id || 'Running'}`
        );
      },
      error: (err) => {
        this.submittingAgent.set(false);
        this.toast.error('Agent Trigger Failed', err?.error?.detail || 'Could not dispatch to external agent.');
      }
    });
  }

  fetchAgentOutput() {
    const batchId = this.selectedBatchId();
    if (!batchId) return;

    this.fetchingOutput.set(true);
    this.pipeline.loadBatchAgentOutput(batchId).subscribe({
      next: (output) => {
        this.fetchingOutput.set(false);
        this.agentOutput.set(output);
        this.toast.success(
          'Agent Output Retrieved',
          `Status: ${output?.status || 'Received'} from ${output?.agentName || 'Agent'}`
        );
      },
      error: (err) => {
        this.fetchingOutput.set(false);
        this.toast.error('Fetch Output Failed', err?.error?.detail || 'Could not fetch agent output.');
      }
    });
  }

  resolveItem(anomalyId: string, action: 'APPROVE' | 'QUARANTINE') {
    const batchId = this.selectedBatchId();
    if (!batchId) return;

    this.pipeline.resolveEscalation(batchId, anomalyId, { action }).subscribe({
      next: (b) => {
        this.toast.success(
          'Resolution Applied',
          `Row ${action === 'APPROVE' ? 're-validated and approved' : 'quarantined'}. Batch status: ${b.stage}`
        );
      },
      error: (err) => {
        this.toast.error('Resolution Failed', err?.error?.detail || 'Could not resolve escalation.');
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


