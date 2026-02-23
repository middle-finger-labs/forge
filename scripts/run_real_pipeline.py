#!/usr/bin/env python3
"""Run a real Forge pipeline end-to-end with live LLM calls.

Starts the worker and API server as subprocesses, submits a spec,
auto-approves both human approval gates (with brief summary), polls
pipeline state until completion or timeout, then collects a
comprehensive report and saves it to disk.

Usage::

    python scripts/run_real_pipeline.py                  # from repo root
    python -m scripts.run_real_pipeline                  # module invocation

Environment variables:
    ANTHROPIC_API_KEY   — required (LLM calls)
    FORGE_MAX_COST      — budget cap, default 5.0
    FORGE_MAX_TICKETS   — max coding tickets, default 3
    FORGE_TIMEOUT_MIN   — overall timeout in minutes, default 15

Exit code 0 if the pipeline completes successfully, 1 otherwise.
"""

from __future__ import annotations

import datetime
import json
import os
import signal
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BUSINESS_SPEC = """\
Build a bookmark manager where users can save URLs with tags, search \
their bookmarks, and share curated collections publicly. Include \
browser extension support.\
"""

PROJECT_NAME = "BookmarkManager"
MAX_COST_USD = float(os.environ.get("FORGE_MAX_COST", "5.0"))
MAX_TICKETS = int(os.environ.get("FORGE_MAX_TICKETS", "3"))
TIMEOUT_MINUTES = int(os.environ.get("FORGE_TIMEOUT_MIN", "15"))
API_PORT = 8000
POLL_INTERVAL = 5  # seconds between state polls
REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

# Stages in pipeline order (for timing)
STAGE_ORDER = [
    "intake",
    "business_analysis",
    "research",
    "architecture",
    "task_decomposition",
    "coding",
    "qa_review",
    "merge",
    "complete",
]

# Approval gates: stage name → approval stage value for the API
APPROVAL_GATES = {
    "business_analysis": "business_analysis",
    "architecture": "architecture",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_ts()}] {msg}", flush=True)


def _api(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Call the local API and return parsed JSON."""
    url = f"http://127.0.0.1:{API_PORT}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _api_safe(method: str, path: str, body: dict | None = None) -> dict | None:
    """Like _api but returns None on error instead of raising."""
    try:
        return _api(method, path, body)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Subprocess management
# ---------------------------------------------------------------------------


_subprocesses: list[subprocess.Popen] = []


def _start_subprocess(args: list[str], label: str) -> subprocess.Popen:
    """Start a subprocess and register it for cleanup."""
    env = {**os.environ}
    _log(f"Starting {label}: {' '.join(args)}")
    proc = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )
    _subprocesses.append(proc)
    return proc


def _cleanup_subprocesses() -> None:
    """Kill all managed subprocesses."""
    for proc in _subprocesses:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass
    _subprocesses.clear()


def _wait_for_health(max_wait: int = 30) -> bool:
    """Wait for the API server health endpoint to respond."""
    for _ in range(max_wait * 4):
        try:
            resp = _api("GET", "/api/health")
            if resp.get("healthy") or resp.get("services"):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


def run_pipeline() -> dict:
    """Execute the full pipeline and return a report dict."""
    report: dict = {
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "business_spec": BUSINESS_SPEC,
        "project_name": PROJECT_NAME,
        "max_cost_usd": MAX_COST_USD,
        "max_tickets": MAX_TICKETS,
        "timeout_minutes": TIMEOUT_MINUTES,
        "pipeline_id": None,
        "workflow_id": None,
        "final_status": "unknown",
        "stages": {},
        "approvals": [],
        "errors": [],
        "tickets": [],
        "events_count": 0,
        "total_cost_usd": 0.0,
        "duration_seconds": 0.0,
    }

    t0 = time.monotonic()
    deadline = t0 + TIMEOUT_MINUTES * 60

    # --- Start infrastructure subprocesses ---
    _start_subprocess(
        [sys.executable, "-m", "worker"],
        "Temporal worker",
    )
    _start_subprocess(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
            "--log-level",
            "warning",
        ],
        "API server",
    )

    # Wait for API health
    _log("Waiting for API server health...")
    if not _wait_for_health():
        report["errors"].append("API server failed to start within 30s")
        report["final_status"] = "infra_failure"
        return report
    _log("API server is healthy")

    # --- Submit pipeline ---
    _log(f"Submitting pipeline: {PROJECT_NAME}")
    try:
        resp = _api(
            "POST",
            "/api/pipelines",
            {
                "business_spec": BUSINESS_SPEC,
                "project_name": PROJECT_NAME,
            },
        )
    except Exception as exc:
        report["errors"].append(f"Failed to submit pipeline: {exc}")
        report["final_status"] = "submit_failure"
        return report

    pipeline_id = resp["pipeline_id"]
    workflow_id = resp.get("workflow_id", "")
    report["pipeline_id"] = pipeline_id
    report["workflow_id"] = workflow_id
    _log(f"Pipeline started: {pipeline_id} (workflow: {workflow_id})")

    # --- Poll loop ---
    stage_times: dict[str, dict] = {}
    last_stage = ""
    approvals_sent: set[str] = set()

    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)

        # Query workflow state
        state = _api_safe("GET", f"/api/pipelines/{pipeline_id}/state")
        if state is None:
            # Workflow may not be queryable yet or may have finished
            # Try the DB endpoint as fallback
            db_data = _api_safe("GET", f"/api/pipelines/{pipeline_id}")
            if db_data and db_data.get("status") in ("complete", "failed"):
                state = {
                    "current_stage": db_data.get("current_stage", "unknown"),
                    "total_cost_usd": db_data.get("total_cost_usd", 0),
                    "aborted": db_data.get("status") == "failed",
                }
            else:
                continue

        current_stage = state.get("current_stage", "unknown")
        cost = state.get("total_cost_usd", 0)
        aborted = state.get("aborted", False)
        pending_approval = state.get("pending_approval")

        # Track stage transitions
        if current_stage != last_stage:
            now = time.monotonic()
            if last_stage and last_stage in stage_times:
                stage_times[last_stage]["ended"] = now
                stage_times[last_stage]["duration_s"] = round(
                    now - stage_times[last_stage]["started"], 1
                )
            if current_stage not in stage_times:
                stage_times[current_stage] = {"started": now}
            _log(f"Stage: {current_stage}  |  Cost: ${cost:.4f}")
            last_stage = current_stage

        # Auto-approve gates
        if pending_approval and pending_approval not in approvals_sent:
            gate = pending_approval
            if gate in APPROVAL_GATES:
                # Build summary from state
                summary = _build_approval_summary(gate, state)
                _log(f"Approving gate: {gate}")
                _log(f"  Summary: {summary[:200]}")
                try:
                    _api(
                        "POST",
                        f"/api/pipelines/{pipeline_id}/approve",
                        {
                            "stage": APPROVAL_GATES[gate],
                            "notes": summary,
                            "approved_by": "run_real_pipeline",
                        },
                    )
                    approvals_sent.add(gate)
                    report["approvals"].append(
                        {
                            "stage": gate,
                            "summary": summary,
                            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                        }
                    )
                except Exception as exc:
                    report["errors"].append(f"Failed to approve {gate}: {exc}")
            else:
                # Unexpected approval gate — approve anyway
                _log(f"Approving unexpected gate: {gate}")
                try:
                    _api(
                        "POST",
                        f"/api/pipelines/{pipeline_id}/approve",
                        {
                            "stage": gate,
                            "notes": "Auto-approved by run_real_pipeline",
                            "approved_by": "run_real_pipeline",
                        },
                    )
                    approvals_sent.add(gate)
                except Exception:
                    pass

        # Check termination
        if current_stage == "complete":
            _log("Pipeline completed successfully!")
            report["final_status"] = "complete"
            break
        if current_stage == "failed" or aborted:
            reason = state.get("abort_reason", "unknown")
            _log(f"Pipeline failed/aborted: {reason}")
            report["final_status"] = "failed"
            report["errors"].append(f"Pipeline aborted: {reason}")
            break
    else:
        _log(f"Pipeline timed out after {TIMEOUT_MINUTES} minutes")
        report["final_status"] = "timeout"
        report["errors"].append(f"Timed out after {TIMEOUT_MINUTES} minutes at stage: {last_stage}")
        # Try to abort gracefully
        _api_safe(
            "POST",
            f"/api/pipelines/{pipeline_id}/abort",
            {
                "reason": "Timeout in run_real_pipeline.py",
            },
        )

    # --- Finalize timing ---
    elapsed = time.monotonic() - t0
    report["duration_seconds"] = round(elapsed, 1)

    # Close out last stage timing
    if last_stage and last_stage in stage_times and "ended" not in stage_times[last_stage]:
        now = time.monotonic()
        stage_times[last_stage]["ended"] = now
        stage_times[last_stage]["duration_s"] = round(now - stage_times[last_stage]["started"], 1)

    # Convert stage_times to report format (drop monotonic references)
    for stage, info in stage_times.items():
        report["stages"][stage] = {
            "duration_seconds": info.get("duration_s", 0),
        }

    # --- Collect final state ---
    final_state = _api_safe("GET", f"/api/pipelines/{pipeline_id}/state")
    if final_state:
        report["total_cost_usd"] = final_state.get("total_cost_usd", 0)
        report["model_downgraded"] = final_state.get("model_downgraded", False)
        report["aborted"] = final_state.get("aborted", False)

        # Artifact summaries (truncated)
        for key in ("product_spec", "enriched_spec", "tech_spec", "prd_board"):
            val = final_state.get(key)
            if val:
                if isinstance(val, str) and len(val) > 2000:
                    report[key] = val[:2000] + "... [truncated]"
                elif isinstance(val, dict):
                    s = json.dumps(val, default=str)
                    if len(s) > 2000:
                        report[key] = s[:2000] + "... [truncated]"
                    else:
                        report[key] = val
                else:
                    report[key] = val

    # --- Collect events ---
    events = _api_safe("GET", f"/api/pipelines/{pipeline_id}/events")
    if isinstance(events, list):
        report["events_count"] = len(events)
        # Extract error events
        for evt in events:
            if isinstance(evt, dict):
                etype = evt.get("event_type", "")
                if "error" in etype or "fail" in etype:
                    report["errors"].append(
                        {
                            "event_type": etype,
                            "stage": evt.get("stage"),
                            "message": str(evt.get("payload", {}))[:500],
                        }
                    )

    # --- Collect tickets ---
    tickets = _api_safe("GET", f"/api/pipelines/{pipeline_id}/tickets")
    if isinstance(tickets, list):
        for t in tickets:
            if isinstance(t, dict):
                report["tickets"].append(
                    {
                        "ticket_id": t.get("ticket_id", ""),
                        "status": t.get("status", ""),
                        "qa_passed": t.get("qa_passed"),
                        "attempts": t.get("attempts", 0),
                        "error": t.get("error"),
                    }
                )

    # --- Collect memories/lessons ---
    lessons = _api_safe("GET", "/api/memory/lessons?limit=50")
    if isinstance(lessons, list):
        report["lessons_count"] = len(lessons)

    report["ended_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    return report


def _build_approval_summary(gate: str, state: dict) -> str:
    """Build a brief human-readable summary for an approval gate."""
    if gate == "business_analysis":
        spec = state.get("product_spec")
        if isinstance(spec, dict):
            name = spec.get("product_name", spec.get("name", ""))
            features = spec.get("features", spec.get("feature_list", []))
            if isinstance(features, list):
                feat_summary = ", ".join(str(f)[:50] for f in features[:5])
            else:
                feat_summary = str(features)[:200]
            return f"Auto-approved BA output for '{name}'. Features: {feat_summary}"
        if isinstance(spec, str):
            return f"Auto-approved BA output. Spec: {spec[:300]}"
        return "Auto-approved BA output (spec available in pipeline state)"

    if gate == "architecture":
        tech = state.get("tech_spec")
        if isinstance(tech, dict):
            arch = tech.get("architecture_type", tech.get("pattern", ""))
            stack = tech.get("tech_stack", tech.get("stack", {}))
            return (
                f"Auto-approved architecture. "
                f"Pattern: {arch}. Stack: {json.dumps(stack, default=str)[:200]}"
            )
        if isinstance(tech, str):
            return f"Auto-approved architecture. Spec: {tech[:300]}"
        return "Auto-approved architecture (spec available in pipeline state)"

    return f"Auto-approved gate: {gate}"


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------


def save_report(report: dict) -> str:
    """Save the report JSON and return the file path."""
    os.makedirs(REPORT_DIR, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pid = report.get("pipeline_id", "unknown")
    filename = f"pipeline_{pid}_{ts}.json"
    filepath = os.path.join(REPORT_DIR, filename)

    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return filepath


def print_summary(report: dict) -> None:
    """Print a human-readable summary to stdout."""
    print(f"\n{'═' * 60}")
    print("  Pipeline Run Report")
    print(f"{'═' * 60}")
    print(f"  Pipeline ID:  {report.get('pipeline_id', '?')}")
    print(f"  Status:       {report.get('final_status', '?')}")
    print(f"  Duration:     {report.get('duration_seconds', 0):.1f}s")
    print(f"  Total Cost:   ${report.get('total_cost_usd', 0):.4f}")
    print(f"  Events:       {report.get('events_count', 0)}")
    print(f"  Tickets:      {len(report.get('tickets', []))}")
    print(f"  Errors:       {len(report.get('errors', []))}")

    stages = report.get("stages", {})
    if stages:
        print(f"\n{'─' * 60}")
        print("  Stage Durations")
        print(f"{'─' * 60}")
        for stage in STAGE_ORDER:
            info = stages.get(stage)
            if info:
                dur = info.get("duration_seconds", 0)
                print(f"  {stage:<25} {dur:>7.1f}s")

    tickets = report.get("tickets", [])
    if tickets:
        print(f"\n{'─' * 60}")
        print("  Tickets")
        print(f"{'─' * 60}")
        for t in tickets:
            qa = "passed" if t.get("qa_passed") else "failed"
            status = t.get("status", "?")
            print(f"  {t.get('ticket_id', '?'):<20} {status:<12} QA: {qa}")

    approvals = report.get("approvals", [])
    if approvals:
        print(f"\n{'─' * 60}")
        print("  Approval Gates")
        print(f"{'─' * 60}")
        for a in approvals:
            print(f"  {a['stage']}: {a.get('summary', '')[:80]}")

    errors = report.get("errors", [])
    if errors:
        print(f"\n{'─' * 60}")
        print("  Errors")
        print(f"{'─' * 60}")
        for e in errors:
            if isinstance(e, dict):
                print(
                    f"  [{e.get('event_type', '?')}] {e.get('stage', '?')}: "
                    f"{e.get('message', '')[:100]}"
                )
            else:
                print(f"  {str(e)[:120]}")

    print(f"\n{'═' * 60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    # Preflight check
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Real pipeline requires LLM access.")
        return 1

    # Ensure we're running from the repo root
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    os.chdir(repo_root)

    print("Forge Real Pipeline Runner")
    print(f"Working directory: {os.getcwd()}")
    print(f"Python: {sys.executable}")
    print(f"Budget: ${MAX_COST_USD:.2f} | Max tickets: {MAX_TICKETS} | Timeout: {TIMEOUT_MINUTES}m")
    print()

    report: dict = {"final_status": "crash"}
    try:
        report = run_pipeline()
    except KeyboardInterrupt:
        _log("Interrupted by user")
        report["final_status"] = "interrupted"
        report["errors"] = report.get("errors", []) + ["Interrupted by user"]
    except Exception as exc:
        _log(f"Unexpected error: {exc}")
        traceback.print_exc()
        report["final_status"] = "crash"
        report["errors"] = report.get("errors", []) + [f"Crash: {traceback.format_exc()}"]
    finally:
        _log("Cleaning up subprocesses...")
        _cleanup_subprocesses()

    # Save and display
    filepath = save_report(report)
    print_summary(report)
    _log(f"Full report saved to: {filepath}")

    return 0 if report.get("final_status") == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
