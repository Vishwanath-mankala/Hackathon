import { Injectable, inject, signal } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import { HealthResponse, PaginatedQueryResponse } from '../models/recon.models';
import { environment } from '../../../environments/environment.generated';

/**
 * System health plus paged access to a batch's Stage 6 reconciliation output.
 *
 * Reconciliation itself is not started from here — the orchestrator runs the
 * 4-tier waterfall automatically once a batch clears the rule engine and every
 * escalation is signed off. This service only reads what that run produced.
 */
@Injectable({
  providedIn: 'root'
})
export class ReconciliationService {
  private http = inject(HttpClient);
  private readonly baseUrl = environment.apiBaseUrl;

  readonly systemHealth = signal<HealthResponse | null>(null);

  getHealth(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.baseUrl}/health`).pipe(
      tap(health => this.systemHealth.set(health))
    );
  }

  /**
   * Pages through one Stage 6 result set of a live pipeline batch.
   * dataset: matched | unmatched_bank | outstanding_gl | ambiguous
   */
  getBatchDataset(
    batchId: string,
    dataset: string,
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

    return this.http.get<PaginatedQueryResponse>(
      `${this.baseUrl}/api/pipeline/batches/${batchId}/recon/${dataset}`,
      { params }
    );
  }
}
