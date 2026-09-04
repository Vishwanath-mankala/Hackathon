import { Injectable, inject, signal } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import {
  PipelineOverview,
  BatchRecord,
  IngestionResponse,
  StructuralGateDetails,
  AnomalyItem,
  HumanResolveRequest,
  TimeEstimate,
  PublishEvent
} from '../models/pipeline.models';

@Injectable({
  providedIn: 'root'
})
export class PipelineService {
  private http = inject(HttpClient);
  private readonly baseUrl = 'http://localhost:8000/api/pipeline';

  // State signals
  readonly overview = signal<PipelineOverview | null>(null);
  readonly batches = signal<BatchRecord[]>([]);
  readonly selectedBatchId = signal<string | null>(null);
  readonly selectedBatch = signal<BatchRecord | null>(null);
  readonly currentAnomalies = signal<AnomalyItem[]>([]);
  readonly publishedEvents = signal<PublishEvent[]>([]);
  readonly isProcessing = signal<boolean>(false);

  // --------------------------------------------------------------------------
  // Overview & Batches
  // --------------------------------------------------------------------------
  loadOverview(): Observable<PipelineOverview> {
    return this.http.get<PipelineOverview>(`${this.baseUrl}/overview`).pipe(
      tap(ov => {
        this.overview.set(ov);
        this.batches.set(ov.batches);
        if (!this.selectedBatchId() && ov.batches.length > 0) {
          this.selectBatch(ov.batches[0].batch_id);
        }
      })
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
    if (found) {
      this.selectedBatch.set(found);
    }
    this.loadBatchDetails(batchId).subscribe();
    this.loadBatchAnomalies(batchId).subscribe();
  }

  loadBatchDetails(batchId: string): Observable<BatchRecord> {
    return this.http.get<BatchRecord>(`${this.baseUrl}/batches/${batchId}`).pipe(
      tap(b => this.selectedBatch.set(b))
    );
  }

  // --------------------------------------------------------------------------
  // Ingestion & Simulation
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
    if (declaredCount !== undefined) formData.append('declared_record_count', declaredCount.toString());
    if (declaredTotal !== undefined) formData.append('declared_control_total', declaredTotal.toString());

    return this.http.post<IngestionResponse>(`${this.baseUrl}/ingest`, formData).pipe(
      tap(() => {
        this.isProcessing.set(false);
        this.loadOverview().subscribe();
      })
    );
  }

  simulateSftp(filename?: string): Observable<IngestionResponse> {
    this.isProcessing.set(true);
    let params = new HttpParams();
    if (filename) params = params.set('filename', filename);

    return this.http.post<IngestionResponse>(`${this.baseUrl}/simulate-sftp`, null, { params }).pipe(
      tap(res => {
        this.isProcessing.set(false);
        this.loadOverview().subscribe({
          next: () => this.selectBatch(res.batch_id)
        });
      })
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
    let params = new HttpParams();
    if (status) params = params.set('status', status);
    if (severity) params = params.set('severity', severity);

    return this.http.get<AnomalyItem[]>(`${this.baseUrl}/batches/${batchId}/anomalies`, { params }).pipe(
      tap(items => this.currentAnomalies.set(items))
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
        this.loadBatchAnomalies(batchId).subscribe();
        this.loadOverview().subscribe();
      })
    );
  }

  // --------------------------------------------------------------------------
  // GL Reconciliation Results
  // --------------------------------------------------------------------------
  loadReconciliation(batchId: string): Observable<any> {
    return this.http.get<any>(`${this.baseUrl}/batches/${batchId}/recon`);
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
        this.loadOverview().subscribe();
        this.loadPublishEvents().subscribe();
      })
    );
  }

  loadPublishEvents(): Observable<PublishEvent[]> {
    return this.http.get<PublishEvent[]>(`${this.baseUrl}/publish/events`).pipe(
      tap(evts => this.publishedEvents.set(evts))
    );
  }
}

