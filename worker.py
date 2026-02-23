"""Temporal worker process for the Forge pipeline.

Starts two concurrent workers:
  - Pipeline worker on "forge-pipeline" queue (workflow + non-coding activities)
  - Coding worker on "forge-coding" queue (run_coding_task only)

Usage:
    python -m worker
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import timedelta

import structlog
from temporalio.client import Client
from temporalio.worker import Worker

from activities.pipeline_activities import (
    clone_remote_repo,
    emit_pipeline_event,
    extract_pipeline_lessons,
    finalize_pipeline_state,
    initialize_pipeline_state,
    push_pipeline_results,
    run_architecture,
    run_business_analysis,
    run_coding_group,
    run_coding_task,
    run_cto_intervention,
    run_integration_check,
    run_merge,
    run_qa_review,
    run_research,
    run_scaffold_project,
    run_task_decomposition,
    run_validate_execution_order,
    store_agent_memory,
)
from workflows.pipeline import CODING_QUEUE, PIPELINE_QUEUE, ForgePipeline

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Worker setup
# ---------------------------------------------------------------------------

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

PIPELINE_ACTIVITIES = [
    run_business_analysis,
    run_research,
    run_architecture,
    run_task_decomposition,
    run_scaffold_project,
    run_validate_execution_order,
    run_qa_review,
    run_merge,
    run_cto_intervention,
    emit_pipeline_event,
    initialize_pipeline_state,
    finalize_pipeline_state,
    extract_pipeline_lessons,
    store_agent_memory,
    clone_remote_repo,
    push_pipeline_results,
]

CODING_ACTIVITIES = [
    run_coding_task,
    run_coding_group,
    run_integration_check,
]


async def _init_local_models() -> None:
    """Check local model availability and warm up if present.

    Called at worker startup so the first coding ticket doesn't pay
    cold-start latency.  If Ollama is unreachable or the model isn't
    pulled, logs a notice and continues — all coding will use cloud APIs.
    """
    try:
        from config.local_models import get_local_model_manager

        mgr = get_local_model_manager()
        health = await mgr.health_check()

        if not health["ollama_running"]:
            log.warning(
                "ollama not running — all coding will use cloud APIs "
                "(run scripts/setup_local_models.sh to set up local inference)",
                url=health["ollama_url"],
            )
            return

        ready = await mgr.ensure_model_available()
        if not ready:
            log.warning(
                "local model not available — coding tasks will use cloud APIs "
                "(run scripts/setup_local_models.sh to pull the model)",
            )
            return

        if health.get("gpu_available"):
            log.info(
                "GPU detected",
                gpu=health["gpu_name"],
                vram_total_mb=health["vram_total_mb"],
                vram_free_mb=health["vram_free_mb"],
            )

        await mgr.warm_up_model()
        log.info("local model ready for inference")

    except Exception as exc:
        log.warning(
            "local model init failed — falling back to cloud APIs",
            error=str(exc)[:200],
        )


async def run_workers() -> None:
    """Connect to Temporal and run both workers until interrupted."""

    log.info(
        "connecting to Temporal",
        address=TEMPORAL_ADDRESS,
        namespace=TEMPORAL_NAMESPACE,
    )
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    log.info("connected to Temporal")

    try:
        # Initialise local model (non-blocking — failure is non-fatal)
        await _init_local_models()

        shutdown_event = asyncio.Event()

        def request_shutdown(sig: signal.Signals) -> None:
            log.info("shutdown requested", signal=sig.name)
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, request_shutdown, sig)

        # Grace period gives in-flight activities time to finish before the
        # worker forcibly exits.  Coding activities can run up to 15 minutes,
        # so we allow a generous window for the most common case.
        graceful_shutdown = timedelta(seconds=120)

        pipeline_worker = Worker(
            client,
            task_queue=PIPELINE_QUEUE,
            workflows=[ForgePipeline],
            activities=PIPELINE_ACTIVITIES,
            graceful_shutdown_timeout=graceful_shutdown,
            max_concurrent_activities=10,
        )

        coding_worker = Worker(
            client,
            task_queue=CODING_QUEUE,
            activities=CODING_ACTIVITIES,
            graceful_shutdown_timeout=graceful_shutdown,
            max_concurrent_activities=5,
        )

        log.info(
            "starting workers",
            pipeline_queue=PIPELINE_QUEUE,
            pipeline_activities=len(PIPELINE_ACTIVITIES),
            coding_queue=CODING_QUEUE,
            coding_activities=len(CODING_ACTIVITIES),
        )

        async with pipeline_worker, coding_worker:
            log.info("workers running — press Ctrl+C to stop")
            await shutdown_event.wait()

        log.info("workers shut down cleanly")
    finally:
        log.info("closing Temporal client")


def main() -> None:
    try:
        asyncio.run(run_workers())
    except KeyboardInterrupt:
        pass
    finally:
        log.info("exiting")


if __name__ == "__main__":
    main()
