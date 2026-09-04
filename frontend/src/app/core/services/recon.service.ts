import { Injectable, inject, signal } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import {
  HealthResponse,
  SplitReconResponse,
  ManifestResponse,
  BatchesListResponse,
  GateCheckRequest,
  GateResultSchema,
  GateAllRequest,
  GateSummaryResponse,
  ReconRunRequest,
  ReconRunResponse,
  PaginatedQueryResponse,
  AmbiguityDiagnosisRequest,
  AmbiguityDiagnosisResponse,
  CorruptBatchRequest,
  CorruptBatchResponse,
  RestoreBatchRequest,
  RestoreBatchResponse
} from '../models/recon.models';

@Injectable({
  providedIn: 'root'
})
export class ReconciliationService {
  private http = inject(HttpClient);
  private readonly baseUrl = 'http://localhost:8000';

  // Shared application state signals
  readonly systemHealth = signal<HealthResponse | null>(null);
  readonly activeManifest = signal<ManifestResponse | null>(null);
  readonly latestReconRun = signal<ReconRunResponse | null>(null);
  readonly isProcessing = signal<boolean>(false);

  // --------------------------------------------------------------------------
  // 1. System Endpoints
  // --------------------------------------------------------------------------
  getHealth(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.baseUrl}/health`).pipe(
      tap(health => this.systemHealth.set(health))
    );
  }

  // --------------------------------------------------------------------------
  // 2. Ingestion & Batching (/api/feed)
  // --------------------------------------------------------------------------
  splitFeed(
    file?: File | null,
    inputPath?: string | null,
    splitBy: 'size' | 'date' = 'size',
    batchSize: number = 500,
    outDir?: string | null
  ): Observable<SplitReconResponse> {
    const formData = new FormData();
    if (file) {
      formData.append('file', file, file.name);
    }
    if (inputPath) {
      formData.append('input_path', inputPath);
    }
    formData.append('split_by', splitBy);
    formData.append('batch_size', batchSize.toString());
    if (outDir) {
      formData.append('out_dir', outDir);
    }
    return this.http.post<SplitReconResponse>(`${this.baseUrl}/api/feed/split`, formData);
  }

  getManifest(manifestPath?: string): Observable<ManifestResponse> {
    let params = new HttpParams();
    if (manifestPath) {
      params = params.set('manifest_path', manifestPath);
    }
    return this.http.get<ManifestResponse>(`${this.baseUrl}/api/feed/manifest`, { params }).pipe(
      tap(manifest => this.activeManifest.set(manifest))
    );
  }

  listBatches(batchesDir?: string): Observable<BatchesListResponse> {
    let params = new HttpParams();
    if (batchesDir) {
      params = params.set('batches_dir', batchesDir);
    }
    return this.http.get<BatchesListResponse>(`${this.baseUrl}/api/feed/batches`, { params });
  }

  // --------------------------------------------------------------------------
  // 3. Structural Gate (/api/gate)
  // --------------------------------------------------------------------------
  checkBatch(req: GateCheckRequest): Observable<GateResultSchema> {
    return this.http.post<GateResultSchema>(`${this.baseUrl}/api/gate/check-batch`, req);
  }

  checkAllBatches(req: GateAllRequest = {}): Observable<GateSummaryResponse> {
    return this.http.post<GateSummaryResponse>(`${this.baseUrl}/api/gate/check-all`, req);
  }

  // --------------------------------------------------------------------------
  // 4. Reconciliation Engine (/api/recon)
  // --------------------------------------------------------------------------
  runReconciliation(req: ReconRunRequest): Observable<ReconRunResponse> {
    return this.http.post<ReconRunResponse>(`${this.baseUrl}/api/recon/run`, req).pipe(
      tap(res => this.latestReconRun.set(res))
    );
  }

  getMatches(
    page: number = 1,
    pageSize: number = 50,
    account?: string,
    tier?: string
  ): Observable<PaginatedQueryResponse> {
    let params = new HttpParams()
      .set('page', page.toString())
      .set('page_size', pageSize.toString());
    if (account) params = params.set('account', account);
    if (tier) params = params.set('tier', tier);
    return this.http.get<PaginatedQueryResponse>(`${this.baseUrl}/api/recon/matches`, { params });
  }

  getUnmatchedCache(
    page: number = 1,
    pageSize: number = 50,
    account?: string
  ): Observable<PaginatedQueryResponse> {
    let params = new HttpParams()
      .set('page', page.toString())
      .set('page_size', pageSize.toString());
    if (account) params = params.set('account', account);
    return this.http.get<PaginatedQueryResponse>(`${this.baseUrl}/api/recon/unmatched-cache`, { params });
  }

  getUnmatchedIngest(
    page: number = 1,
    pageSize: number = 50,
    account?: string
  ): Observable<PaginatedQueryResponse> {
    let params = new HttpParams()
      .set('page', page.toString())
      .set('page_size', pageSize.toString());
    if (account) params = params.set('account', account);
    return this.http.get<PaginatedQueryResponse>(`${this.baseUrl}/api/recon/unmatched-ingest`, { params });
  }

  getAmbiguousMatches(
    page: number = 1,
    pageSize: number = 50
  ): Observable<PaginatedQueryResponse> {
    const params = new HttpParams()
      .set('page', page.toString())
      .set('page_size', pageSize.toString());
    return this.http.get<PaginatedQueryResponse>(`${this.baseUrl}/api/recon/ambiguous`, { params });
  }

  downloadCsv(filename: string): Observable<Blob> {
    return this.http.get(`${this.baseUrl}/api/recon/download/${filename}`, {
      responseType: 'blob'
    });
  }

  // --------------------------------------------------------------------------
  // 5. Diagnostics & Simulation (/api/diagnostics)
  // --------------------------------------------------------------------------
  diagnoseAmbiguity(req: AmbiguityDiagnosisRequest = {}): Observable<AmbiguityDiagnosisResponse> {
    return this.http.post<AmbiguityDiagnosisResponse>(`${this.baseUrl}/api/diagnostics/ambiguity`, req);
  }

  corruptBatch(req: CorruptBatchRequest): Observable<CorruptBatchResponse> {
    return this.http.post<CorruptBatchResponse>(`${this.baseUrl}/api/diagnostics/corrupt-batch`, req);
  }

  restoreBatch(req: RestoreBatchRequest): Observable<RestoreBatchResponse> {
    return this.http.post<RestoreBatchResponse>(`${this.baseUrl}/api/diagnostics/restore-batch`, req);
  }
}

