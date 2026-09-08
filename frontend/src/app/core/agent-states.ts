/**
 * Shared vocabulary for the automatic agent dispatch log.
 *
 * One copy, so the anomaly queue's monitor and the estimator's forecast panel
 * agree on what "finished" means and on the order stages are listed in.
 */

/** Execution states that mean the agent job is finished — polling stops here. */
export const TERMINAL_STATES: ReadonlySet<string> = new Set([
  'SUCCESS', 'COMPLETED', 'FAILED', 'ERROR', 'CANCELLED', 'SKIPPED'
]);

/** Pipeline order of the stage hooks that dispatch an agent. */
export const STAGE_ORDER: readonly string[] = [
  'STAGE_1_FORECAST',
  'STAGE_1_EXTRACTION',
  'STAGE_4_ANOMALY',
  'STAGE_6_RECON',
  'STAGE_7_SLA'
];

export function isRunning(status: string | null | undefined): boolean {
  return !!status && !TERMINAL_STATES.has(status);
}

export function stageIndex(stage: string): number {
  const i = STAGE_ORDER.indexOf(stage);
  return i === -1 ? STAGE_ORDER.length : i;
}

export function stageLabel(stage: string): string {
  switch (stage) {
    case 'STAGE_1_FORECAST': return 'Stage 1 · Processing forecast';
    case 'STAGE_1_EXTRACTION': return 'Stage 1 · Extraction';
    case 'STAGE_4_ANOMALY': return 'Stage 4 · Anomaly scoring';
    case 'STAGE_6_RECON': return 'Stage 6 · Recon exceptions';
    case 'STAGE_7_SLA': return 'Stage 7 · SLA urgency';
    default: return stage;
  }
}
