import { Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Observable, catchError, finalize, tap, throwError } from 'rxjs';
import {
  PipelineOverview,
  BatchRecord,
  IngestionResponse,
  StructuralGateDetails,
  AnomalyItem,
  HumanResolveRequest,
  TimeEstimate,
  PublishEvent,
  AgentExecution,
  AgentStatusResponse,
  ArtifactKind,
  AuditSignoff,
  BatchReconResponse,
  ConfiguredAgent,
  SignoffRequest
} from '../models/pipeline.models';
import { environment } from '../../../environments/environment.generated';

/** Turns any transport/HTTP failure into a message worth showing an operator. */
export function describeHttpError(err: unknown): string {
  const e = err as HttpErrorResponse;
  if (e?.error?.detail) {
    return typeof e.error.detail === 'string' ? e.error.detail : JSON.stringify(e.error.detail);
  }
  if (e?.status === 0) {
    return `Backend unreachable at ${environment.apiBaseUrl} — the API is not responding.`;
  }
  if (e?.status) {
    return `API returned HTTP ${e.status} ${e.statusText || ''}`.trim();
  }
  return (e as any)?.message || 'Unknown error contacting the pipeline API.';
}

@Injectable({
  providedIn: 'root'
})
export class PipelineService {
  private http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/pipeline`;

  // ---- Data state (populated only from API responses) -----------------------
  readonly overview = signal<PipelineOverview | null>(null);
  readonly batches = signal<BatchRecord[]>([]);
  readonly selectedBatchId = signal<string | null>(null);
  readonly selectedBatch = signal<BatchRecord | null>(null);
  readonly currentAnomalies = signal<AnomalyItem[]>([]);
  readonly publishedEvents = signal<PublishEvent[]>([]);
  readonly agentExecutions = signal<Record<string, AgentExecution>>({});
  readonly configuredAgents = signal<ConfiguredAgent[]>([]);

  // ---- Request state --------------------------------------------------------
  readonly overviewLoading = signal<boolean>(false);
  readonly overviewError = signal<string | null>(null);

  readonly anomaliesLoading = signal<boolean>(false);
  readonly anomaliesError = signal<string | null>(null);

  readonly eventsLoading = signal<boolean>(false);
  readonly eventsError = signal<string | null>(null);

  readonly agentsLoading = signal<boolean>(false);
  readonly agentsError = signal<string | null>(null);

  readonly isProcessing = signal<boolean>(false);

  /** True while any pipeline request is in flight — drives the global header indicator. */
  readonly busy = computed(() =>
    this.overviewLoading() ||
    this.anomaliesLoading() ||
    this.eventsLoading() ||
    this.agentsLoading() ||
    this.isProcessing()
  );

  // --------------------------------------------------------------------------
  // Overview & Batches
  // --------------------------------------------------------------------------
  loadOverview(): Observable<PipelineOverview> {
    this.overviewLoading.set(true);
    this.overviewError.set(null);

    return this.http.get<PipelineOverview>(`${this.baseUrl}/overview`).pipe(
      tap(ov => {
        this.overview.set(ov);
        this.batches.set(ov.batches);
        const current = this.selectedBatchId();
        const stillPresent = current && ov.batches.some(b => b.batch_id === current);
        if (!stillPresent && ov.batches.length > 0) {
          this.selectBatch(ov.batches[0].batch_id);
        }
      }),
      catchError(err => {
        this.overviewError.set(describeHttpError(err));
        this.overview.set(null);
        this.batches.set([]);
        return throwError(() => err);
      }),
      finalize(() => this.overviewLoading.set(false))
    );
  }

  loadBatches(stage?: string): Observable<BatchRecord[]> {
    let params = new HttpParams();
    if (stage) params = params.set('stage', stage);
    return this.http.get<BatchRecord[]>(`${this.baseUrl}/batches`, { params }).pipe(
      tap(list => this.batches.set(list))
    );
  }

  selectBatch(batchId: string): void {
    this.selectedBatchId.set(batchId);
    const found = this.batches().find(b => b.batch_id === batchId);
    this.selectedBatch.set(found ?? null);
  }

  loadBatchDetails(batchId: string): Observable<BatchRecord> {
    return this.http.get<BatchRecord>(`${this.baseUrl}/batches/${batchId}`).pipe(
      tap(b => {
        this.selectedBatch.set(b);
        this.agentExecutions.set(b.agent_executions || {});
      })
    );
  }

  // --------------------------------------------------------------------------
  // Ingestion
  // --------------------------------------------------------------------------
  ingestFile(
    file: File,
    source: string = 'UPLOAD',
    declaredCount?: number,
    declaredTotal?: number
  ): Observable<IngestionResponse> {
    this.isProcessing.set(true);
    const formData = new FormData();
    formData.append('file', file, file.name);
    formData.append('source', source);
    if (declaredCount !== undefined && declaredCount !== null) {
      formData.append('declared_record_count', declaredCount.toString());
    }
    if (declaredTotal !== undefined && declaredTotal !== null) {
      formData.append('declared_control_total', declaredTotal.toString());
    }

    return this.http.post<IngestionResponse>(`${this.baseUrl}/ingest`, formData).pipe(
      tap(res => {
        this.loadOverview().subscribe({
          next: () => this.selectBatch(res.batch_id),
          error: () => {}
        });
      }),
      finalize(() => this.isProcessing.set(false))
    );
  }

  simulateSftp(filename?: string): Observable<IngestionResponse> {
    this.isProcessing.set(true);
    let params = new HttpParams();
    if (filename) params = params.set('filename', filename);

    return this.http.post<IngestionResponse>(`${this.baseUrl}/simulate-sftp`, null, { params }).pipe(
      tap(res => {
        this.loadOverview().subscribe({
          next: () => this.selectBatch(res.batch_id),
          error: () => {}
        });
      }),
      finalize(() => this.isProcessing.set(false))
    );
  }

  // --------------------------------------------------------------------------
  // Structural Gate
  // --------------------------------------------------------------------------
  loadGateDetails(batchId: string): Observable<StructuralGateDetails> {
    return this.http.get<StructuralGateDetails>(`${this.baseUrl}/batches/${batchId}/gate`);
  }

  // --------------------------------------------------------------------------
  // Anomalies & Human Escalation
  // --------------------------------------------------------------------------
  loadBatchAnomalies(batchId: string, status?: string, severity?: string): Observable<AnomalyItem[]> {
    this.anomaliesLoading.set(true);
    this.anomaliesError.set(null);

    let params = new HttpParams();
    if (status) params = params.set('status', status);
    if (severity) params = params.set('severity', severity);

    return this.http.get<AnomalyItem[]>(`${this.baseUrl}/batches/${batchId}/anomalies`, { params }).pipe(
      tap(items => this.currentAnomalies.set(items)),
      catchError(err => {
        this.anomaliesError.set(describeHttpError(err));
        this.currentAnomalies.set([]);
        return throwError(() => err);
      }),
      finalize(() => this.anomaliesLoading.set(false))
    );
  }

  resolveEscalation(
    batchId: string,
    anomalyId: string,
    req: HumanResolveRequest
  ): Observable<BatchRecord> {
    return this.http.post<BatchRecord>(
      `${this.baseUrl}/batches/${batchId}/anomalies/${anomalyId}/resolve`,
      req
    ).pipe(
      tap(updatedBatch => {
        this.selectedBatch.set(updatedBatch);
        this.agentExecutions.set(updatedBatch.agent_executions || {});
        this.loadBatchAnomalies(batchId).subscribe({ error: () => {} });
        this.loadOverview().subscribe({ error: () => {} });
      })
    );
  }

  // --------------------------------------------------------------------------
  // GL Reconciliation Results
  // --------------------------------------------------------------------------
  loadReconciliation(batchId: string): Observable<BatchReconResponse> {
    return this.http.get<BatchReconResponse>(`${this.baseUrl}/batches/${batchId}/recon`);
  }

  // --------------------------------------------------------------------------
  // Time Estimation & SLA
  // --------------------------------------------------------------------------
  loadTimeEstimate(batchId: string): Observable<TimeEstimate> {
    return this.http.get<TimeEstimate>(`${this.baseUrl}/batches/${batchId}/estimator`);
  }

  // --------------------------------------------------------------------------
  // Publishing
  // --------------------------------------------------------------------------
  publishBatch(batchId: string): Observable<PublishEvent> {
    return this.http.post<PublishEvent>(`${this.baseUrl}/batches/${batchId}/publish`, {}).pipe(
      tap(() => {
        this.loadOverview().subscribe({ error: () => {} });
        this.loadPublishEvents().subscribe({ error: () => {} });
      })
    );
  }

  loadPublishEvents(): Observable<PublishEvent[]> {
    this.eventsLoading.set(true);
    this.eventsError.set(null);

    return this.http.get<PublishEvent[]>(`${this.baseUrl}/publish/events`).pipe(
      tap(evts => this.publishedEvents.set(evts)),
      catchError(err => {
        this.eventsError.set(describeHttpError(err));
        this.publishedEvents.set([]);
        return throwError(() => err);
      }),
      finalize(() => this.eventsLoading.set(false))
    );
  }

  // --------------------------------------------------------------------------
  // Multi-Agent Platform (Aava AI / CrewAI)
  //
  // Stage 4, 6 and 7 agents are dispatched automatically by the backend as
  // their input artefacts are produced. The console only observes them; the
  // manual re-dispatch below exists to retry a failed submission.
  // --------------------------------------------------------------------------
  loadAgentStatus(batchId: string): Observable<AgentStatusResponse> {
    this.agentsLoading.set(true);
    this.agentsError.set(null);

    return this.http.get<AgentStatusResponse>(`${this.baseUrl}/batches/${batchId}/agent/status`).pipe(
      tap(res => this.agentExecutions.set(res.executions || {})),
      catchError(err => {
        this.agentsError.set(describeHttpError(err));
        this.agentExecutions.set({});
        return throwError(() => err);
      }),
      finalize(() => this.agentsLoading.set(false))
    );
  }

  /** Polls the agent platform for output on every in-flight execution of a batch. */
  refreshAgentOutputs(batchId: string): Observable<Record<string, AgentExecution>> {
    return this.http.get<Record<string, AgentExecution>>(
      `${this.baseUrl}/batches/${batchId}/agent/output`
    ).pipe(
      tap(execs => this.agentExecutions.set(execs || {}))
    );
  }

  redispatchAgent(batchId: string, stageKey: string, agentId?: string): Observable<AgentExecution> {
    let params = new HttpParams().set('stage_key', stageKey);
    if (agentId) params = params.set('agent_id', agentId);

    return this.http.post<AgentExecution>(
      `${this.baseUrl}/batches/${batchId}/agent/classify`,
      {},
      { params }
    ).pipe(
      tap(() => this.loadAgentStatus(batchId).subscribe({ error: () => {} }))
    );
  }

  loadConfiguredAgents(): Observable<ConfiguredAgent[]> {
    return this.http.get<ConfiguredAgent[]>(`${this.baseUrl}/agent/available-agents`).pipe(
      tap(agents => this.configuredAgents.set(agents))
    );
  }

  // --------------------------------------------------------------------------
  // Analyst sign-off & audit trail
  //
  // Stage 6 leaves ambiguous ties and reconciling items for a person to decide.
  // Sign-offs are append-only: a correction supersedes, it never overwrites.
  // --------------------------------------------------------------------------
  loadSignoffs(batchId: string, effectiveOnly: boolean = false): Observable<AuditSignoff[]> {
    const params = new HttpParams().set('effective_only', effectiveOnly.toString());
    return this.http.get<AuditSignoff[]>(`${this.baseUrl}/batches/${batchId}/signoffs`, { params });
  }

  recordSignoff(batchId: string, dataset: string, req: SignoffRequest): Observable<AuditSignoff> {
    return this.http.post<AuditSignoff>(
      `${this.baseUrl}/batches/${batchId}/recon/${dataset}/signoff`,
      req
    );
  }

  getSignoffTrailUrl(batchId: string): string {
    return `${this.baseUrl}/batches/${batchId}/signoffs/file`;
  }

  // --------------------------------------------------------------------------
  // Artefact downloads
  // --------------------------------------------------------------------------
  getArtifactUrl(batchId: string, kind: ArtifactKind): string {
    return `${this.baseUrl}/batches/${batchId}/artifacts/${kind}`;
  }
}
