import { Component, ChangeDetectionStrategy, computed, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Renders an agent execution report as a readable assessment rather than a JSON dump.
 *
 * The platform returns its report as a JSON string whose shape is set by the
 * agent's own prompt, so this parses what it recognises and renders the rest
 * generically. Nothing is ever dropped: unrecognised sections are still shown,
 * and the raw payload stays one click away — an operator has to be able to see
 * exactly what the agent said, not only our reading of it.
 */

/** One finding, assembled from the parallel arrays the report keys by entry_id. */
interface Finding {
  entryId: string;
  rowIndex?: number | string;
  externalTxnId?: string;
  account?: string;
  rawAmount?: number | string;
  bookingDate?: string;
  errorType?: string;
  category?: string;
  severityEngine?: string;
  severityFinal?: string;
  confidence?: number;
  description?: string;
  reasoning?: string;
  expertAssessment?: string;
  suggestedFixFromEngine?: any;
  recommendedAction?: string;
  routedTo?: string;
  routingRationale?: string;
  slaFlag?: string;
  agreement?: string;
  disagreementReason?: string;
  losslessDetermination?: string;
  justifyingValue?: string;
  systemicPatternLink?: string;
  regulatoryNote?: string;
}

interface Hypothesis {
  key: string;
  title?: string;
  detail?: string;
  recommendedInvestigation?: string;
}

/** Top-level keys this component lays out explicitly; anything else falls through. */
const KNOWN_KEYS = new Set([
  'batch_metadata',
  'schema_validation',
  'risk_anomaly_summary',
  'alert_log',
  'compliance_report',
  'audit_trail',
  'systemic_analysis',
]);

@Component({
  selector: 'app-agent-report',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="bg-surface border-t border-border-default">
      <!-- View switch -->
      <div class="flex items-center justify-between gap-2 px-3 py-2 border-b border-border-default bg-surface-sunken">
        <div class="flex items-center gap-1 text-[11px] font-mono">
          <button
            (click)="view.set('report')"
            class="px-2 py-1 border transition-colors"
            [ngClass]="view() === 'report'
              ? 'border-accent-action text-accent-action font-semibold'
              : 'border-border-default text-text-secondary hover:text-text-primary'"
          >Report</button>
          <button
            (click)="view.set('raw')"
            class="px-2 py-1 border transition-colors"
            [ngClass]="view() === 'raw'
              ? 'border-accent-action text-accent-action font-semibold'
              : 'border-border-default text-text-secondary hover:text-text-primary'"
          >Raw</button>
        </div>

        <div class="flex items-center gap-3 text-[11px] font-mono text-text-secondary">
          @if (!parsed()) {
            <span class="text-status-amber">Unstructured output — showing as text</span>
          }
          <button (click)="copyRaw()" class="text-accent-action hover:underline">
            {{ copied() ? 'Copied' : 'Copy raw' }}
          </button>
        </div>
      </div>

      @if (view() === 'raw' || !parsed()) {
        <pre class="whitespace-pre-wrap text-[11px] text-text-primary font-mono leading-relaxed p-3 max-h-[32rem] overflow-y-auto select-text">{{ rawText() }}</pre>
      } @else {
        <div class="p-3 space-y-3 max-h-[32rem] overflow-y-auto">

          <!-- ===== Verdict ===== -->
          @if (compliance(); as c) {
            <div class="border p-3 space-y-2" [ngClass]="verdictClass()">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-[10px] font-mono px-1.5 py-0.5 border font-semibold" [ngClass]="verdictClass()">
                  {{ c['overall_risk_rating'] || 'RATING NOT STATED' }}
                </span>
                @if (c['ledger_release_recommendation']) {
                  <span class="text-[13px] font-semibold">{{ c['ledger_release_recommendation'] }}</span>
                }
              </div>

              @if (c['ledger_release_justification']) {
                <p class="text-[12px] leading-relaxed opacity-90">{{ c['ledger_release_justification'] }}</p>
              }
            </div>

            <!-- Counts -->
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[12px] font-mono">
              @for (m of complianceMetrics(); track m.label) {
                <div class="p-2.5 bg-surface-sunken border border-border-default">
                  <span class="text-text-secondary block text-[10px]">{{ m.label }}</span>
                  <span class="font-semibold text-[15px]" [ngClass]="m.emphasis ? 'text-status-amber' : 'text-text-primary'">
                    {{ m.value }}
                  </span>
                </div>
              }
            </div>

            @if (breakdowns().length) {
              <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                @for (b of breakdowns(); track b.label) {
                  <div class="p-2.5 bg-surface-sunken border border-border-default">
                    <span class="text-text-secondary block text-[10px] font-mono mb-1">{{ b.label }}</span>
                    <div class="space-y-0.5">
                      @for (row of b.rows; track row.key) {
                        <div class="flex items-center justify-between text-[11px] font-mono">
                          <span [ngClass]="row.value ? 'text-text-primary' : 'text-text-secondary'">{{ row.key }}</span>
                          <span [ngClass]="row.value ? 'text-text-primary font-semibold' : 'text-text-secondary'">{{ row.value }}</span>
                        </div>
                      }
                    </div>
                  </div>
                }
              </div>
            }

            @if (c['severity_override_detail'] && c['severity_overrides_applied']) {
              <div class="p-2.5 bg-[var(--status-amber-bg)] border border-status-amber text-[12px] space-y-1">
                <span class="text-[11px] font-mono font-semibold text-status-amber block">
                  Agent overrode the rule engine ({{ c['severity_overrides_applied'] }})
                </span>
                <p class="text-text-primary leading-relaxed">{{ c['severity_override_detail'] }}</p>
              </div>
            }

            @if (c['audit_note']) {
              <div class="p-2.5 bg-surface-sunken border border-border-default text-[12px]">
                <span class="text-[11px] font-mono font-semibold text-text-secondary block mb-1">Audit note</span>
                <p class="text-text-primary leading-relaxed">{{ c['audit_note'] }}</p>
              </div>
            }
          }

          <!-- ===== Findings ===== -->
          @if (findings().length) {
            <div class="space-y-2">
              <h4 class="text-[11px] font-mono font-semibold text-text-secondary uppercase tracking-wider">
                Findings ({{ findings().length }})
              </h4>

              @for (f of findings(); track f.entryId) {
                <div class="border border-border-default bg-surface-sunken">
                  <!-- Identity line -->
                  <div class="flex flex-wrap items-center gap-2 p-2.5 border-b border-border-default text-[11px] font-mono">
                    @if (f.severityFinal) {
                      <span class="px-1.5 py-0.5 text-[10px] border font-semibold" [ngClass]="severityClass(f.severityFinal)">
                        {{ f.severityFinal }}
                      </span>
                    }
                    @if (isOverride(f)) {
                      <span class="text-[10px] text-status-amber" [title]="'Rule engine said ' + f.severityEngine">
                        ↑ raised from {{ f.severityEngine }}
                      </span>
                    }
                    @if (f.agreement) {
                      <span class="text-[10px] px-1.5 py-0.5 border"
                            [ngClass]="agreementClass(f.agreement)">{{ f.agreement }}</span>
                    }
                    @if (f.errorType) {
                      <span class="text-status-red font-medium">{{ f.errorType }}</span>
                    }
                    @if (f.category) {
                      <span class="px-1.5 py-0.5 text-[10px] border" [ngClass]="categoryClass(f.category)">{{ f.category }}</span>
                    }
                    <span class="text-text-secondary ml-auto flex items-center gap-2 flex-wrap">
                      @if (f.externalTxnId) { <span>Txn <strong class="text-accent-action">{{ f.externalTxnId }}</strong></span> }
                      @if (f.rowIndex !== undefined && f.rowIndex !== null) { <span>· Row #{{ f.rowIndex }}</span> }
                      @if (f.account) { <span>· {{ f.account }}</span> }
                      @if (f.rawAmount !== undefined && f.rawAmount !== null) { <span>· {{ f.rawAmount }}</span> }
                      @if (f.bookingDate) { <span>· {{ f.bookingDate }}</span> }
                      @if (f.confidence !== undefined) { <span>· {{ (f.confidence * 100).toFixed(0) }}% conf.</span> }
                    </span>
                  </div>

                  <div class="p-2.5 space-y-2 text-[12px]">
                    @if (f.description) {
                      <p class="text-text-primary leading-relaxed">{{ f.description }}</p>
                    }

                    @for (block of findingNarratives(f); track block.label) {
                      <div class="pl-2.5 border-l-2 border-border-default">
                        <span class="text-[10px] font-mono font-semibold text-text-secondary uppercase tracking-wider block">
                          {{ block.label }}
                        </span>
                        <p class="text-text-primary leading-relaxed">{{ block.text }}</p>
                      </div>
                    }

                    <!-- Routing -->
                    @if (f.recommendedAction || f.routedTo || f.slaFlag) {
                      <div class="flex flex-wrap items-center gap-2 pt-1 text-[11px] font-mono">
                        @if (f.recommendedAction) {
                          <span class="px-1.5 py-0.5 border border-accent-action text-accent-action">{{ f.recommendedAction }}</span>
                        }
                        @if (f.routedTo) {
                          <span class="text-text-secondary">→ {{ f.routedTo }}</span>
                        }
                        @if (f.slaFlag) {
                          <span class="px-1.5 py-0.5 border border-status-amber text-status-amber ml-auto">{{ f.slaFlag }}</span>
                        }
                      </div>
                    }

                    @if (f.suggestedFixFromEngine) {
                      <div class="text-[11px] font-mono text-text-secondary">
                        Rule-engine fix: <code class="text-text-primary">{{ f.suggestedFixFromEngine | json }}</code>
                      </div>
                    }
                  </div>
                </div>
              }
            </div>
          }

          <!-- ===== Systemic analysis ===== -->
          @if (systemic(); as sys) {
            <div class="border border-border-default bg-surface-sunken p-2.5 space-y-2 text-[12px]">
              <h4 class="text-[11px] font-mono font-semibold text-text-secondary uppercase tracking-wider">
                Systemic analysis
                @if (sys['pattern_id']) { <span class="text-text-primary normal-case">· {{ sys['pattern_id'] }}</span> }
              </h4>

              @if (sys['pattern_description']) {
                <p class="text-text-primary leading-relaxed">{{ sys['pattern_description'] }}</p>
              }

              @for (h of hypotheses(); track h.key) {
                <div class="p-2.5 bg-surface border border-border-default space-y-1">
                  <span class="text-[11px] font-semibold text-text-primary block">
                    {{ h.title || humanize(h.key) }}
                  </span>
                  @if (h.detail) {
                    <p class="text-[12px] text-text-primary leading-relaxed">{{ h.detail }}</p>
                  }
                  @if (h.recommendedInvestigation) {
                    <p class="text-[11px] text-text-secondary leading-relaxed">
                      <span class="font-mono font-semibold">Investigate: </span>{{ h.recommendedInvestigation }}
                    </p>
                  }
                </div>
              }

              @for (extra of systemicNarratives(); track extra.label) {
                <div class="pl-2.5 border-l-2 border-border-default">
                  <span class="text-[10px] font-mono font-semibold text-text-secondary uppercase tracking-wider block">
                    {{ extra.label }}
                  </span>
                  <p class="text-text-primary leading-relaxed">{{ extra.text }}</p>
                </div>
              }
            </div>
          }

          <!-- ===== Provenance ===== -->
          @if (provenance().length) {
            <details class="border border-border-default bg-surface-sunken">
              <summary class="px-2.5 py-2 text-[11px] font-mono font-semibold text-text-secondary uppercase tracking-wider cursor-pointer">
                Provenance &amp; schema validation
              </summary>
              <div class="px-2.5 pb-2.5 space-y-2 text-[12px]">
                @for (item of provenance(); track item.label) {
                  <div>
                    <span class="text-[10px] font-mono text-text-secondary block">{{ item.label }}</span>
                    <span class="text-text-primary break-words">{{ item.text }}</span>
                  </div>
                }
              </div>
            </details>
          }

          <!-- ===== Anything the layout above does not cover ===== -->
          @for (section of unknownSections(); track section.label) {
            <details class="border border-border-default bg-surface-sunken">
              <summary class="px-2.5 py-2 text-[11px] font-mono font-semibold text-text-secondary uppercase tracking-wider cursor-pointer">
                {{ section.label }}
              </summary>
              <pre class="px-2.5 pb-2.5 whitespace-pre-wrap text-[11px] font-mono text-text-primary select-text">{{ section.text }}</pre>
            </details>
          }
        </div>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentReportComponent {
  /** Raw execution output: a JSON string, an object, or free text. */
  output = input.required<any>();

  view = signal<'report' | 'raw'>('report');
  copied = signal<boolean>(false);

  /** The payload exactly as the agent returned it. */
  rawText = computed<string>(() => {
    const o = this.output();
    if (o === null || o === undefined) return '';
    return typeof o === 'string' ? o : JSON.stringify(o, null, 2);
  });

  /** Parsed object, or null when the output is not a JSON object. */
  parsed = computed<Record<string, any> | null>(() => {
    const o = this.output();
    if (o && typeof o === 'object' && !Array.isArray(o)) return o as Record<string, any>;
    if (typeof o !== 'string') return null;

    const text = o.trim();
    if (!text) return null;

    // Agents often wrap JSON in a ```json fence.
    const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
    const candidate = fenced ? fenced[1].trim() : text;
    if (!candidate.startsWith('{')) return null;

    try {
      const value = JSON.parse(candidate);
      return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
    } catch {
      return null;
    }
  });

  compliance = computed<Record<string, any> | null>(() => this.section('compliance_report'));
  systemic = computed<Record<string, any> | null>(() => this.section('systemic_analysis'));

  /**
   * Merges risk_anomaly_summary, alert_log and audit_trail into one card per
   * finding. They are three parallel views of the same entries keyed by
   * entry_id, so reading them side by side beats scrolling three tables.
   */
  findings = computed<Finding[]>(() => {
    const root = this.parsed();
    if (!root) return [];

    const summary = this.asArray(root['risk_anomaly_summary']);
    const alerts = this.asArray(root['alert_log']);
    const audit = this.asArray(root['audit_trail']);
    if (!summary.length && !alerts.length && !audit.length) return [];

    const byId = new Map<string, Finding>();
    const keyFor = (r: any, i: number) =>
      String(r?.['entry_id'] ?? r?.['external_txn_id'] ?? `entry-${i}`);

    summary.forEach((r, i) => {
      const id = keyFor(r, i);
      byId.set(id, {
        entryId: id,
        rowIndex: r['row_index'],
        externalTxnId: r['external_txn_id'],
        account: r['account'],
        rawAmount: r['raw_amount'],
        bookingDate: r['booking_date'],
        errorType: r['error_type'],
        category: r['category'],
        severityEngine: r['severity_rule_engine'],
        severityFinal: r['severity_confirmed'] ?? r['severity_rule_engine'],
        confidence: typeof r['confidence_score'] === 'number' ? r['confidence_score'] : undefined,
        description: r['description'],
        reasoning: r['one_line_reasoning'],
        expertAssessment: r['expert_assessment'],
        suggestedFixFromEngine: r['suggested_fix_from_engine'],
      });
    });

    alerts.forEach((r, i) => {
      const id = keyFor(r, i);
      const f = byId.get(id) ?? { entryId: id };
      f.recommendedAction = r['recommended_action'] ?? f.recommendedAction;
      f.routedTo = r['routed_to'] ?? f.routedTo;
      f.routingRationale = r['routing_rationale'] ?? f.routingRationale;
      f.slaFlag = r['sla_flag'] ?? f.slaFlag;
      f.externalTxnId ??= r['external_txn_id'];
      f.errorType ??= r['error_type'];
      f.severityFinal ??= r['severity'];
      byId.set(id, f);
    });

    audit.forEach((r, i) => {
      const id = keyFor(r, i);
      const f = byId.get(id) ?? { entryId: id };
      f.severityEngine ??= r['severity_rule_engine'];
      f.severityFinal = r['severity_final'] ?? f.severityFinal;
      f.agreement = r['agreement_with_rule_engine'] ?? f.agreement;
      f.disagreementReason = this.meaningful(r['reason_for_disagreement']);
      f.losslessDetermination = r['lossless_determination'] ?? f.losslessDetermination;
      f.justifyingValue = r['field_value_justifying_decision'] ?? f.justifyingValue;
      f.systemicPatternLink = r['systemic_pattern_link'] ?? f.systemicPatternLink;
      f.regulatoryNote = r['regulatory_note'] ?? f.regulatoryNote;
      byId.set(id, f);
    });

    return [...byId.values()];
  });

  complianceMetrics = computed(() => {
    const c = this.compliance();
    if (!c) return [];
    const defs: { label: string; key: string; emphasis?: boolean }[] = [
      { label: 'Total flags', key: 'total_anomaly_flags' },
      { label: 'Transactions affected', key: 'unique_transactions_affected' },
      { label: 'Safe to auto-remediate', key: 'safe_to_auto_remediate' },
      { label: 'Needs human review', key: 'requires_human_review', emphasis: true },
      { label: 'Severity overrides', key: 'severity_overrides_applied', emphasis: true },
      { label: 'Lossless fixes available', key: 'lossless_fixes_available' },
      { label: 'Non-lossless blocked', key: 'non_lossless_fixes_blocked', emphasis: true },
    ];
    return defs
      .filter(d => c[d.key] !== undefined && c[d.key] !== null)
      .map(d => ({ label: d.label, value: c[d.key], emphasis: !!d.emphasis && Number(c[d.key]) > 0 }));
  });

  breakdowns = computed(() => {
    const c = this.compliance();
    if (!c) return [];
    const defs = [
      { label: 'By category', key: 'counts_by_category' },
      { label: 'By severity', key: 'counts_by_severity' },
      { label: 'Routing', key: 'routing_breakdown' },
    ];
    return defs
      .filter(d => c[d.key] && typeof c[d.key] === 'object')
      .map(d => ({
        label: d.label,
        rows: Object.entries(c[d.key] as Record<string, any>)
          .map(([k, v]) => ({ key: this.humanize(k), value: Number(v) || 0 })),
      }));
  });

  hypotheses = computed<Hypothesis[]>(() => {
    const sys = this.systemic();
    if (!sys) return [];
    return Object.entries(sys)
      .filter(([k, v]) => /^hypothesis/i.test(k) && v && typeof v === 'object')
      .map(([k, v]) => ({
        key: k,
        title: (v as any)['title'],
        detail: (v as any)['detail'],
        recommendedInvestigation: (v as any)['recommended_investigation'],
      }));
  });

  systemicNarratives = computed(() => {
    const sys = this.systemic();
    if (!sys) return [];
    return [
      { label: 'Concentration risk', text: sys['concentration_risk'] },
      { label: 'Escalation recommendation', text: sys['escalation_recommendation'] },
    ].filter(x => typeof x.text === 'string' && x.text.trim()) as { label: string; text: string }[];
  });

  provenance = computed(() => {
    const root = this.parsed();
    if (!root) return [];
    const meta = this.section('batch_metadata') ?? {};
    const schema = this.section('schema_validation') ?? {};
    const items = [
      { label: 'Reviewed by', text: meta['reviewed_by'] },
      { label: 'Review timestamp', text: meta['review_timestamp'] },
      { label: 'Source file', text: meta['source_file'] },
      { label: 'Rows ingested', text: meta['total_rows_ingested'] },
      { label: 'File integrity', text: meta['file_integrity_note'] },
      { label: 'Schema validation', text: schema['status'] },
      { label: 'Schema notes', text: schema['anomalies_in_schema'] },
      { label: 'Sensitive data handling', text: schema['sensitive_data_handling'] },
    ];
    return items
      .filter(i => i.text !== undefined && i.text !== null && String(i.text).trim())
      .map(i => ({ label: i.label, text: String(i.text) }));
  });

  /** Top-level keys with no tailored layout — shown rather than silently dropped. */
  unknownSections = computed(() => {
    const root = this.parsed();
    if (!root) return [];
    return Object.entries(root)
      .filter(([k]) => !KNOWN_KEYS.has(k))
      .map(([k, v]) => ({
        label: this.humanize(k),
        text: typeof v === 'string' ? v : JSON.stringify(v, null, 2),
      }));
  });

  // ---------------------------------------------------------------------
  // Per-finding narrative blocks, in the order an analyst reads them.
  // ---------------------------------------------------------------------
  findingNarratives(f: Finding): { label: string; text: string }[] {
    return [
      { label: 'Why this matters', text: f.reasoning },
      { label: 'Assessment', text: f.expertAssessment },
      { label: 'Disagreement with rule engine', text: f.disagreementReason },
      { label: 'Lossless?', text: f.losslessDetermination },
      { label: 'Evidence', text: f.justifyingValue },
      { label: 'Routing rationale', text: f.routingRationale },
      { label: 'Systemic link', text: f.systemicPatternLink },
      { label: 'Regulatory note', text: f.regulatoryNote },
    ].filter(b => typeof b.text === 'string' && b.text.trim()) as { label: string; text: string }[];
  }

  isOverride(f: Finding): boolean {
    return !!f.severityEngine && !!f.severityFinal && f.severityEngine !== f.severityFinal;
  }

  verdictClass(): string {
    const rating = String(this.compliance()?.['overall_risk_rating'] ?? '').toUpperCase();
    const release = String(this.compliance()?.['ledger_release_recommendation'] ?? '').toUpperCase();
    if (rating === 'CRITICAL' || release.includes('HOLD') || release.includes('DO NOT')) {
      return 'bg-[var(--status-red-bg)] text-status-red border-status-red';
    }
    if (rating === 'HIGH' || release.includes('EXCEPTION')) {
      return 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber';
    }
    return 'bg-[var(--status-green-bg)] text-status-green border-status-green';
  }

  agreementClass(agreement: string): string {
    return /disagree/i.test(agreement)
      ? 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber'
      : 'bg-surface text-text-secondary border-border-default';
  }

  severityClass(sev: string): string {
    switch (String(sev).toUpperCase()) {
      case 'CRITICAL': return 'bg-[var(--status-red-bg)] text-status-red border-status-red';
      case 'HIGH': return 'bg-[var(--status-amber-bg)] text-status-amber border-status-amber';
      case 'MEDIUM': return 'bg-surface text-tier-2 border-border-default';
      default: return 'bg-surface text-text-secondary border-border-default';
    }
  }

  categoryClass(cat: string): string {
    switch (String(cat).toUpperCase()) {
      case 'STRUCTURAL': return 'bg-blue-500/10 text-blue-500 border-blue-500/30';
      case 'SEMANTIC': return 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30';
      case 'TIMING': return 'bg-teal-500/10 text-teal-500 border-teal-500/30';
      case 'REFERENTIAL': return 'bg-purple-500/10 text-purple-500 border-purple-500/30';
      default: return 'bg-surface text-text-secondary border-border-default';
    }
  }

  humanize(key: string): string {
    const spaced = key.replace(/[_-]+/g, ' ').trim();
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  }

  copyRaw() {
    navigator.clipboard.writeText(this.rawText()).then(
      () => {
        this.copied.set(true);
        setTimeout(() => this.copied.set(false), 2000);
      },
      () => this.copied.set(false)
    );
  }

  // ---------------------------------------------------------------------
  private section(key: string): Record<string, any> | null {
    const v = this.parsed()?.[key];
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, any>) : null;
  }

  private asArray(v: any): Record<string, any>[] {
    return Array.isArray(v) ? v.filter(x => x && typeof x === 'object') : [];
  }

  /** Drops placeholder text agents use for "nothing to report". */
  private meaningful(v: any): string | undefined {
    if (typeof v !== 'string') return undefined;
    const t = v.trim();
    if (!t || /^(n\/?a|none|null|-)$/i.test(t)) return undefined;
    return t;
  }
}
