"""
Diagnostics service adapter.
Wraps 'Rule Engine/diagnose_ambiguity.py' and 'File-Gen Scripts/corrupt_batch_for_testing.py'.
"""
import os
import sys
from pathlib import Path
from typing import Dict, Optional
import pandas as pd
from fastapi import HTTPException

from app.config import settings
from app.models.diagnostics import (
    AmbiguityDiagnosisResponse,
    CorruptBatchResponse,
    RestoreBatchResponse,
)

RULE_ENGINE_DIR = str(settings.project_root / "Rule Engine")
FILE_GEN_DIR = str(settings.project_root / "File-Gen Scripts")
for p in [RULE_ENGINE_DIR, FILE_GEN_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import corrupt_batch_for_testing  # type: ignore


class DiagnosticsService:
    @staticmethod
    def diagnose_ambiguity(results_dir: Optional[str] = None) -> AmbiguityDiagnosisResponse:
        resolved_dir = Path(results_dir) if results_dir else settings.results_dir
        amb_path = resolved_dir / "ambiguous_matches_for_review.csv"
        matches_path = resolved_dir / "matched_transactions.csv"

        if not amb_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Ambiguous matches file not found at: {amb_path}. Run reconciliation first."
            )
        if not matches_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Matched transactions file not found at: {matches_path}. Run reconciliation first."
            )

        amb = pd.read_csv(amb_path, dtype=str, keep_default_na=False)
        matches = pd.read_csv(matches_path, dtype=str, keep_default_na=False)

        if amb.empty:
            return AmbiguityDiagnosisResponse(
                total_ambiguous=0,
                avg_candidates=0.0,
                max_candidates=0,
                ambiguity_by_tier={},
                resolved_by_reference=0,
                resolved_by_reference_pct=0.0,
                top_accounts={},
                top_amounts={},
                top_amounts_concentration_pct=0.0,
                is_concentrated=False,
                diagnostic_assessment="No ambiguous matches recorded.",
                output_detail_csv="",
            )

        def parse_cands(s):
            if isinstance(s, list):
                return s
            s_str = str(s).strip()
            if s_str.startswith("["):
                try:
                    return eval(s_str)
                except Exception:
                    return [s_str]
            return [s_str]

        amb["candidate_internal_txn_ids"] = amb["candidate_internal_txn_ids"].apply(parse_cands)
        amb["n_candidates"] = amb["candidate_internal_txn_ids"].apply(len)

        total_amb = len(amb)
        avg_cand = float(amb["n_candidates"].mean())
        max_cand = int(amb["n_candidates"].max())

        tier_counts = {str(k): int(v) for k, v in amb["tier"].value_counts().items()}

        resolved_ref = None
        resolved_ref_pct = None
        if "disambiguated_by_reference" in amb.columns:
            amb["disambiguated_by_reference_bool"] = (
                amb["disambiguated_by_reference"].astype(str).str.lower() == "true"
            )
            resolved_ref = int(amb["disambiguated_by_reference_bool"].sum())
            resolved_ref_pct = round((resolved_ref / total_amb) * 100, 2)

        joined = amb.merge(
            matches,
            left_on=["chosen_internal_txn_id"],
            right_on=["internal_txn_id"],
            how="left",
        )

        top_accounts = {str(k): int(v) for k, v in joined["account"].value_counts().head(15).items()}
        amt_counts = joined["cache_amount"].value_counts().head(15)
        top_amounts = {str(k): int(v) for k, v in amt_counts.items()}

        top15_share = float(amt_counts.sum() / total_amb) if total_amb else 0.0
        top15_share_pct = round(top15_share * 100, 2)
        is_concentrated = top15_share > 0.5

        if is_concentrated:
            assessment = (
                f"Ambiguity is CONCENTRATED ({top15_share_pct}% in top 15 recurring amounts). "
                "Disambiguation via reference text or targeted rules will resolve the majority of ties."
            )
        else:
            assessment = (
                f"Ambiguity is SPREAD ({top15_share_pct}% in top 15 amounts). "
                "Account+amount+date matching keys are not sufficiently unique across this dataset."
            )

        out_path = resolved_dir / "ambiguity_diagnostic_detail.csv"
        joined.to_csv(out_path, index=False)

        return AmbiguityDiagnosisResponse(
            total_ambiguous=total_amb,
            avg_candidates=round(avg_cand, 2),
            max_candidates=max_cand,
            ambiguity_by_tier=tier_counts,
            resolved_by_reference=resolved_ref,
            resolved_by_reference_pct=resolved_ref_pct,
            top_accounts=top_accounts,
            top_amounts=top_amounts,
            top_amounts_concentration_pct=top15_share_pct,
            is_concentrated=is_concentrated,
            diagnostic_assessment=assessment,
            output_detail_csv=str(out_path),
        )

    @staticmethod
    def corrupt_batch(batch_filename: str, mode: str) -> CorruptBatchResponse:
        batch_path = settings.batches_dir / batch_filename
        if not batch_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Batch file '{batch_filename}' not found in {settings.batches_dir}"
            )

        if mode not in corrupt_batch_for_testing.MODES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid corruption mode '{mode}'. Choose from: {list(corrupt_batch_for_testing.MODES.keys())}"
            )

        # Create backup first
        corrupt_batch_for_testing.do_backup(str(batch_path))

        # Apply corruption
        fn = corrupt_batch_for_testing.MODES[mode]
        fn(str(batch_path))

        bak_path = corrupt_batch_for_testing.backup_path(str(batch_path))
        return CorruptBatchResponse(
            message=f"Successfully injected '{mode}' corruption into {batch_filename}.",
            file=batch_filename,
            mode=mode,
            backup_path=bak_path,
        )

    @staticmethod
    def restore_batch(batch_filename: str) -> RestoreBatchResponse:
        batch_path = settings.batches_dir / batch_filename
        bak_path = Path(corrupt_batch_for_testing.backup_path(str(batch_path)))

        if not bak_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"No backup file (.bak) found for {batch_filename}."
            )

        corrupt_batch_for_testing.do_restore(str(batch_path))

        return RestoreBatchResponse(
            message=f"Successfully restored {batch_filename} from backup.",
            file=batch_filename,
            restored=True,
        )


diagnostics_service = DiagnosticsService()

