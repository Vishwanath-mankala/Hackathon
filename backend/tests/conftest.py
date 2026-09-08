"""
Test isolation for durable state.

The pipeline singleton is built when `app.main` is imported, and its
constructor loads the batch registry from the database, backfills the run
history from whatever SLA artefacts are on disk, and syncs the sample-feed
queue. Left alone, the suite would write dozens of 1–2 row test batches into
the developer's real `data/recon.db`, drag the calibration towards its clamp
floor, and advance the demo feed. So before any test module imports the app,
point the database and the artefact directories at a scratch location.
"""
import tempfile
from pathlib import Path

import pytest

from app.config import settings
from app.services.run_history_service import run_history_service

_SCRATCH = Path(tempfile.mkdtemp(prefix="recon-tests-"))

# The suite never talks to the real agent platform. With a developer's live
# .env it otherwise submits every test batch to Aava (slow, spends quota) and
# leaves poller threads running for minutes that write into the shared test
# database after later tests have reset it. Dispatches report SKIPPED; the
# submit path itself is covered with a monkeypatched bridge.
settings.crewai_api_url = ""
settings.crewai_api_key = None

settings.db_path = _SCRATCH / "recon.db"
settings.sla_metrics_dir = _SCRATCH / "sla_metrics"
settings.forecast_dir = _SCRATCH / "forecasts"
settings.working_frames_dir = _SCRATCH / "working_frames"
for _d in (settings.sla_metrics_dir, settings.forecast_dir, settings.working_frames_dir):
    _d.mkdir(parents=True, exist_ok=True)
run_history_service.configure(settings.forecast_dir)


@pytest.fixture(autouse=True)
def _fresh_state():
    """Every test starts with an empty history, an uncalibrated estimator and an
    empty batch registry (the feed queue is left as the test finds it)."""
    from app.services.time_estimator_service import time_estimator_service
    from app.services.pipeline_orchestrator import pipeline_orchestrator

    pipeline_orchestrator.reset_state(requeue=False)
    run_history_service.reset()
    time_estimator_service.reset_calibration()
    yield
