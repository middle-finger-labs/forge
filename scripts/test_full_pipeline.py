#!/usr/bin/env python3
"""Manual validation script for running the real pipeline agents end-to-end.

Requires ANTHROPIC_API_KEY to be set in the environment (or in a .env file).

Usage:
    # Full pipeline (spec + coding + QA)
    python scripts/test_full_pipeline.py

    # Spec pipeline only (BA → Research → Architect → PM)
    python scripts/test_full_pipeline.py --skip-coding

    # Provide inline spec
    python scripts/test_full_pipeline.py --spec "Build a habit tracking app ..."

    # Provide spec from a file
    python scripts/test_full_pipeline.py --spec-file path/to/spec.txt

    # Override the LLM model
    python scripts/test_full_pipeline.py --model claude-sonnet-4-20250514
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Ensure the project root is on sys.path so agent imports work regardless of cwd.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SPEC = (
    "Build a habit tracking app where users can create daily habits, check them off, "
    "see streak counts, and get push notification reminders. Include social features "
    "where friends can see each other's streaks."
)

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    """Return a filesystem-safe timestamp string."""
    return datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")


def _ensure_output_dir() -> Path:
    """Create and return the outputs/ directory under the project root."""
    out = PROJECT_ROOT / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _print_step_header(step_num: int, title: str) -> None:
    """Print a decorated step header to the console."""
    console.print()
    console.rule(f"[bold cyan]Step {step_num}: {title}[/bold cyan]")
    console.print()


def _print_error(step_name: str, elapsed: float) -> None:
    """Print an error panel when a pipeline step fails."""
    console.print(
        Panel(
            f"[bold red]FAILED[/bold red]: {step_name} returned None after {elapsed:.1f}s.\n"
            "Pipeline stopped.",
            title="Error",
            border_style="red",
        )
    )


def _cost_str(cost: float) -> str:
    """Format a cost value as a dollar string."""
    return f"${cost:.4f}"


# ---------------------------------------------------------------------------
# Step runners — spec pipeline
# ---------------------------------------------------------------------------


async def step_ba(spec_text: str, model: str | None) -> tuple[dict | None, float, float]:
    """Run BA agent; return (result, cost, elapsed_seconds)."""
    from agents.ba_agent import run_ba_agent

    _print_step_header(1, "Business Analyst Agent")

    with console.status("[bold green]Running BA agent...[/bold green]", spinner="dots"):
        t0 = time.monotonic()
        result, cost = await run_ba_agent(spec_text, model=model)
        elapsed = time.monotonic() - t0

    if result is None:
        _print_error("BA Agent", elapsed)
        return None, cost, elapsed

    # Summary table
    table = Table(title="ProductSpec Summary", show_header=False, border_style="green")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Product name", result.get("product_name", "?"))
    table.add_row("Spec ID", result.get("spec_id", "?"))
    table.add_row("User stories", str(len(result.get("user_stories", []))))
    table.add_row("Open questions", str(len(result.get("open_questions", []))))
    table.add_row("Constraints", str(len(result.get("constraints", []))))
    table.add_row("Time", f"{elapsed:.1f}s")
    table.add_row("Cost", _cost_str(cost))
    console.print(table)

    return result, cost, elapsed


async def step_researcher(
    product_spec: dict, model: str | None
) -> tuple[dict | None, float, float]:
    """Run researcher agent; return (result, cost, elapsed_seconds)."""
    from agents.researcher_agent import run_researcher_agent

    _print_step_header(2, "Researcher Agent")

    with console.status("[bold green]Running researcher agent...[/bold green]", spinner="dots"):
        t0 = time.monotonic()
        result, cost = await run_researcher_agent(product_spec, model=model)
        elapsed = time.monotonic() - t0

    if result is None:
        _print_error("Researcher Agent", elapsed)
        return None, cost, elapsed

    findings = result.get("research_findings", [])
    competitors = result.get("competitors", [])

    table = Table(title="EnrichedSpec Summary", show_header=False, border_style="green")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Research findings", str(len(findings)))
    table.add_row("Competitors found", str(len(competitors)))
    if competitors:
        names = ", ".join(c.get("name", "?") for c in competitors)
        table.add_row("Competitor names", names)
    table.add_row("Recommended changes", str(len(result.get("recommended_changes", []))))
    table.add_row("Time", f"{elapsed:.1f}s")
    table.add_row("Cost", _cost_str(cost))
    console.print(table)

    return result, cost, elapsed


async def step_architect(
    enriched_spec: dict, model: str | None
) -> tuple[dict | None, float, float]:
    """Run architect agent; return (result, cost, elapsed_seconds)."""
    from agents.architect_agent import run_architect_agent

    _print_step_header(3, "Architect Agent")

    with console.status("[bold green]Running architect agent...[/bold green]", spinner="dots"):
        t0 = time.monotonic()
        result, cost = await run_architect_agent(enriched_spec, model=model)
        elapsed = time.monotonic() - t0

    if result is None:
        _print_error("Architect Agent", elapsed)
        return None, cost, elapsed

    services = result.get("services", [])
    endpoints = result.get("api_endpoints", [])
    tech_stack = result.get("tech_stack", {})

    table = Table(title="TechSpec Summary", show_header=False, border_style="green")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Spec ID", result.get("spec_id", "?"))
    table.add_row("Services", str(len(services)))
    table.add_row("API endpoints", str(len(endpoints)))
    table.add_row("Database models", str(len(result.get("database_models", []))))

    if tech_stack:
        stack_str = ", ".join(f"{k}: {v}" for k, v in tech_stack.items())
        table.add_row("Tech stack", stack_str)

    table.add_row("Time", f"{elapsed:.1f}s")
    table.add_row("Cost", _cost_str(cost))
    console.print(table)

    return result, cost, elapsed


async def step_pm(
    tech_spec: dict, enriched_spec: dict, model: str | None
) -> tuple[dict | None, float, float]:
    """Run PM agent; return (result, cost, elapsed_seconds)."""
    from agents.pm_agent import run_pm_agent

    _print_step_header(4, "PM Agent")

    with console.status("[bold green]Running PM agent...[/bold green]", spinner="dots"):
        t0 = time.monotonic()
        result, cost = await run_pm_agent(tech_spec, enriched_spec, model=model)
        elapsed = time.monotonic() - t0

    if result is None:
        _print_error("PM Agent", elapsed)
        return None, cost, elapsed

    tickets = result.get("tickets", [])
    exec_order = result.get("execution_order", [])
    critical_path = result.get("critical_path", [])

    table = Table(title="PRDBoard Summary", show_header=False, border_style="green")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Board ID", result.get("board_id", "?"))
    table.add_row("Tickets", str(len(tickets)))
    table.add_row("Execution order groups", str(len(exec_order)))
    table.add_row("Critical path length", str(len(critical_path)))

    if critical_path:
        table.add_row("Critical path", " -> ".join(critical_path))

    table.add_row("Time", f"{elapsed:.1f}s")
    table.add_row("Cost", _cost_str(cost))
    console.print(table)

    return result, cost, elapsed


# ---------------------------------------------------------------------------
# Step runners — coding phase
# ---------------------------------------------------------------------------


async def step_scaffold(tech_spec: dict, repo_path: str) -> float:
    """Scaffold the project; return elapsed_seconds."""
    from agents.project_scaffold import scaffold_project
    from agents.worktree_manager import WorktreeManager

    _print_step_header(5, "Project Scaffold")

    with console.status("[bold green]Scaffolding project...[/bold green]", spinner="dots"):
        t0 = time.monotonic()
        mgr = WorktreeManager(repo_path)
        await mgr.setup_repo(tech_spec)
        await scaffold_project(repo_path, tech_spec)
        elapsed = time.monotonic() - t0

    # Count files
    file_count = sum(
        len(files) for root, _dirs, files in os.walk(repo_path) if ".git" not in root.split(os.sep)
    )

    table = Table(title="Scaffold Result", show_header=False, border_style="green")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Repo path", repo_path)
    table.add_row("Files created", str(file_count))
    table.add_row("Time", f"{elapsed:.1f}s")
    console.print(table)

    return elapsed


async def step_coding(
    ticket: dict,
    tech_spec: dict,
    repo_path: str,
    ticket_num: int,
    total_tickets: int,
) -> tuple[dict | None, float, float, str]:
    """Code a single ticket; return (artifact, cost, elapsed, worktree_path)."""
    from agents.coding_agent import run_coding_agent_task
    from agents.worktree_manager import WorktreeManager

    ticket_key = ticket.get("ticket_key", "unknown")
    branch_name = f"forge/{ticket_key.lower()}"

    _print_step_header(6, f"Coding Agent [{ticket_num}/{total_tickets}]: {ticket_key}")

    console.print(f"  [dim]Title:[/dim] {ticket.get('title', '?')}")
    console.print(f"  [dim]Files:[/dim] {', '.join(ticket.get('files_owned', []))}")
    console.print()

    with console.status(f"[bold green]Coding {ticket_key}...[/bold green]", spinner="dots"):
        t0 = time.monotonic()

        # Create worktree
        wt_dir = os.path.join(os.path.dirname(repo_path), "worktrees")
        mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)
        wt_path = await mgr.create_worktree(ticket_key, branch_name)

        artifact, cost = await run_coding_agent_task(
            ticket=ticket,
            tech_spec_context=tech_spec,
            worktree_path=wt_path,
            branch_name=branch_name,
        )
        elapsed = time.monotonic() - t0

    if artifact is None:
        _print_error(f"Coding Agent ({ticket_key})", elapsed)
        return None, cost, elapsed, wt_path

    table = Table(
        title=f"Code Artifact: {ticket_key}",
        show_header=False,
        border_style="green",
    )
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Branch", artifact.get("git_branch", "?"))
    table.add_row("Files created", str(len(artifact.get("files_created", []))))
    table.add_row("Files modified", str(len(artifact.get("files_modified", []))))
    table.add_row("Time", f"{elapsed:.1f}s")
    table.add_row("Cost", _cost_str(cost))

    files_created = artifact.get("files_created", [])
    if files_created:
        table.add_row("Created", "\n".join(files_created[:10]))
        if len(files_created) > 10:
            table.add_row("", f"... and {len(files_created) - 10} more")

    console.print(table)

    return artifact, cost, elapsed, wt_path


async def step_qa(
    ticket: dict,
    code_artifact: dict,
    coding_standards: list[str],
    model: str | None,
    ticket_num: int,
    total_tickets: int,
) -> tuple[dict | None, str, float, float]:
    """QA review a ticket; return (review, verdict, cost, elapsed)."""
    from agents.qa_agent import run_qa_agent

    ticket_key = ticket.get("ticket_key", "unknown")

    _print_step_header(7, f"QA Agent [{ticket_num}/{total_tickets}]: {ticket_key}")

    with console.status(f"[bold green]Reviewing {ticket_key}...[/bold green]", spinner="dots"):
        t0 = time.monotonic()
        review, cost = await run_qa_agent(
            ticket=ticket,
            code_artifact=code_artifact,
            coding_standards=coding_standards,
            model=model,
        )
        elapsed = time.monotonic() - t0

    if review is None:
        _print_error(f"QA Agent ({ticket_key})", elapsed)
        return None, "error", cost, elapsed

    verdict = review.get("verdict", "unknown")
    score = review.get("code_quality_score", 0)

    verdict_style = {
        "approved": "[bold green]APPROVED[/bold green]",
        "needs_revision": "[bold yellow]NEEDS REVISION[/bold yellow]",
        "rejected": "[bold red]REJECTED[/bold red]",
    }.get(verdict, f"[bold]{verdict}[/bold]")

    table = Table(
        title=f"QA Review: {ticket_key}",
        show_header=False,
        border_style="yellow" if verdict != "approved" else "green",
    )
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Verdict", verdict_style)
    table.add_row("Quality score", f"{score}/10")
    table.add_row("Time", f"{elapsed:.1f}s")
    table.add_row("Cost", _cost_str(cost))

    # Show revision instructions if present
    rev_instructions = review.get("revision_instructions", [])
    if rev_instructions:
        table.add_row(
            "Revision instructions",
            "\n".join(f"- {r}" if isinstance(r, str) else f"- {r}" for r in rev_instructions[:5]),
        )

    # Show comments summary
    comments = review.get("comments", [])
    if comments:
        table.add_row("Comments", str(len(comments)))

    console.print(table)

    return review, verdict, cost, elapsed


async def step_revision(
    ticket: dict,
    review: dict,
    tech_spec: dict,
    wt_path: str,
    ticket_key: str,
    branch_name: str,
) -> tuple[dict | None, float, float]:
    """Run one revision cycle; return (new_artifact, cost, elapsed)."""
    from agents.coding_agent import run_coding_agent_task

    console.print()
    console.print(f"  [bold yellow]Running revision for {ticket_key}...[/bold yellow]")

    # Inject revision instructions into the ticket
    revised_ticket = {
        **ticket,
        "revision_instructions": review.get("revision_instructions", []),
        "previous_review": review,
    }

    with console.status(f"[bold yellow]Revising {ticket_key}...[/bold yellow]", spinner="dots"):
        t0 = time.monotonic()
        artifact, cost = await run_coding_agent_task(
            ticket=revised_ticket,
            tech_spec_context=tech_spec,
            worktree_path=wt_path,
            branch_name=branch_name,
        )
        elapsed = time.monotonic() - t0

    if artifact is None:
        console.print(f"  [red]Revision failed for {ticket_key}[/red]")
    else:
        console.print(
            f"  [green]Revision complete for {ticket_key}[/green] "
            f"({elapsed:.1f}s, {_cost_str(cost)})"
        )

    return artifact, cost, elapsed


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_pipeline(
    spec_text: str,
    model: str | None,
    skip_coding: bool,
) -> None:
    """Execute the pipeline and save results."""
    label = "Spec Pipeline" if skip_coding else "Full Pipeline"
    console.print(
        Panel(
            f"[bold]Spec:[/bold] {spec_text[:120]}{'...' if len(spec_text) > 120 else ''}",
            title=f"{label} Run",
            subtitle=f"Model override: {model or 'default'}",
            border_style="blue",
        )
    )

    total_cost = 0.0
    total_time = 0.0
    artifacts: dict[str, object] = {
        "spec_text": spec_text,
        "model": model,
        "skip_coding": skip_coding,
    }

    # Step 1: BA Agent
    product_spec, cost, elapsed = await step_ba(spec_text, model)
    total_cost += cost
    total_time += elapsed
    artifacts["product_spec"] = product_spec
    artifacts["ba_cost"] = cost
    artifacts["ba_time"] = elapsed
    if product_spec is None:
        _save_artifacts(artifacts, total_cost, total_time, success=False)
        return

    # Step 2: Researcher Agent
    enriched_spec, cost, elapsed = await step_researcher(product_spec, model)
    total_cost += cost
    total_time += elapsed
    artifacts["enriched_spec"] = enriched_spec
    artifacts["researcher_cost"] = cost
    artifacts["researcher_time"] = elapsed
    if enriched_spec is None:
        _save_artifacts(artifacts, total_cost, total_time, success=False)
        return

    # Step 3: Architect Agent
    tech_spec, cost, elapsed = await step_architect(enriched_spec, model)
    total_cost += cost
    total_time += elapsed
    artifacts["tech_spec"] = tech_spec
    artifacts["architect_cost"] = cost
    artifacts["architect_time"] = elapsed
    if tech_spec is None:
        _save_artifacts(artifacts, total_cost, total_time, success=False)
        return

    # Step 4: PM Agent
    prd_board, cost, elapsed = await step_pm(tech_spec, enriched_spec, model)
    total_cost += cost
    total_time += elapsed
    artifacts["prd_board"] = prd_board
    artifacts["pm_cost"] = cost
    artifacts["pm_time"] = elapsed
    if prd_board is None:
        _save_artifacts(artifacts, total_cost, total_time, success=False)
        return

    if skip_coding:
        _save_artifacts(artifacts, total_cost, total_time, success=True)
        return

    # -----------------------------------------------------------------------
    # Coding phase
    # -----------------------------------------------------------------------

    # Select tickets from the first execution_order group (up to 3)
    exec_order = prd_board.get("execution_order", [])
    if not exec_order:
        console.print("[yellow]No execution_order groups in PRDBoard — skipping coding.[/yellow]")
        _save_artifacts(artifacts, total_cost, total_time, success=True)
        return

    first_group = exec_order[0][:3]  # First group, capped at 3 tickets
    tickets_by_key = {t["ticket_key"]: t for t in prd_board.get("tickets", [])}
    selected_tickets = [tickets_by_key[k] for k in first_group if k in tickets_by_key]

    if not selected_tickets:
        console.print("[yellow]No tickets found for first group — skipping coding.[/yellow]")
        _save_artifacts(artifacts, total_cost, total_time, success=True)
        return

    console.print()
    console.rule("[bold cyan]Coding Phase[/bold cyan]")
    console.print(
        f"\n  Running {len(selected_tickets)} ticket(s) from group 1: "
        f"{', '.join(t['ticket_key'] for t in selected_tickets)}\n"
    )

    # Step 5: Scaffold
    tmp_base = tempfile.mkdtemp(prefix="forge-e2e-")
    repo_path = os.path.join(tmp_base, "project")

    try:
        elapsed = await step_scaffold(tech_spec, repo_path)
        total_time += elapsed
        artifacts["scaffold_time"] = elapsed
        artifacts["repo_path"] = repo_path

        # Step 6+7: Code and QA each ticket sequentially
        coding_standards = tech_spec.get("coding_standards", [])
        code_artifacts: list[dict] = []
        qa_reviews: list[dict] = []
        ticket_results: list[dict] = []

        for i, ticket in enumerate(selected_tickets, 1):
            ticket_key = ticket["ticket_key"]
            branch_name = f"forge/{ticket_key.lower()}"

            # -- Code --
            result = await step_coding(
                ticket,
                tech_spec,
                repo_path,
                ticket_num=i,
                total_tickets=len(selected_tickets),
            )
            artifact, cost, elapsed, wt_path = result
            total_cost += cost
            total_time += elapsed

            if artifact is None:
                ticket_results.append(
                    {
                        "ticket_key": ticket_key,
                        "coding": "failed",
                        "qa_verdict": None,
                        "revision": None,
                        "cost": cost,
                        "time": elapsed,
                    }
                )
                continue

            code_artifacts.append(artifact)

            # -- QA --
            review, verdict, qa_cost, qa_elapsed = await step_qa(
                ticket,
                artifact,
                coding_standards,
                model,
                ticket_num=i,
                total_tickets=len(selected_tickets),
            )
            total_cost += qa_cost
            total_time += qa_elapsed

            if review is not None:
                qa_reviews.append(review)

            ticket_result = {
                "ticket_key": ticket_key,
                "coding": "success",
                "qa_verdict": verdict,
                "revision": None,
                "files_created": artifact.get("files_created", []),
                "cost": cost + qa_cost,
                "time": elapsed + qa_elapsed,
            }

            # -- One revision cycle if not approved --
            if verdict in ("needs_revision", "rejected") and review is not None:
                rev_artifact, rev_cost, rev_elapsed = await step_revision(
                    ticket,
                    review,
                    tech_spec,
                    wt_path,
                    ticket_key,
                    branch_name,
                )
                total_cost += rev_cost
                total_time += rev_elapsed
                ticket_result["cost"] += rev_cost
                ticket_result["time"] += rev_elapsed

                if rev_artifact is not None:
                    # Replace original artifact
                    code_artifacts[-1] = rev_artifact

                    # Re-run QA on revised code
                    rev_review, rev_verdict, rev_qa_cost, rev_qa_elapsed = await step_qa(
                        ticket,
                        rev_artifact,
                        coding_standards,
                        model,
                        ticket_num=i,
                        total_tickets=len(selected_tickets),
                    )
                    total_cost += rev_qa_cost
                    total_time += rev_qa_elapsed
                    ticket_result["cost"] += rev_qa_cost
                    ticket_result["time"] += rev_qa_elapsed
                    ticket_result["revision"] = rev_verdict

                    if rev_review is not None:
                        qa_reviews.append(rev_review)
                        ticket_result["qa_verdict"] = rev_verdict
                else:
                    ticket_result["revision"] = "failed"

            ticket_results.append(ticket_result)

        # Store all coding artifacts
        artifacts["code_artifacts"] = code_artifacts
        artifacts["qa_reviews"] = qa_reviews
        artifacts["ticket_results"] = ticket_results

        # -- Print coding results summary --
        console.print()
        console.rule("[bold cyan]Coding Phase Results[/bold cyan]")
        console.print()

        results_table = Table(
            title="Ticket Results",
            border_style="cyan",
        )
        results_table.add_column("Ticket", style="bold")
        results_table.add_column("Coding")
        results_table.add_column("QA Verdict")
        results_table.add_column("Revision")
        results_table.add_column("Files Created")
        results_table.add_column("Cost")

        for tr in ticket_results:
            coding_status = "[green]OK[/green]" if tr["coding"] == "success" else "[red]FAIL[/red]"
            verdict = tr.get("qa_verdict") or "-"
            if verdict == "approved":
                verdict_display = "[green]approved[/green]"
            elif verdict == "needs_revision":
                verdict_display = "[yellow]needs_revision[/yellow]"
            elif verdict == "rejected":
                verdict_display = "[red]rejected[/red]"
            else:
                verdict_display = verdict

            revision = tr.get("revision")
            if revision is None:
                rev_display = "-"
            elif revision == "approved":
                rev_display = "[green]approved[/green]"
            elif revision == "failed":
                rev_display = "[red]failed[/red]"
            else:
                rev_display = f"[yellow]{revision}[/yellow]"

            files = tr.get("files_created", [])
            file_display = str(len(files)) if files else "-"

            results_table.add_row(
                tr["ticket_key"],
                coding_status,
                verdict_display,
                rev_display,
                file_display,
                _cost_str(tr["cost"]),
            )

        console.print(results_table)

    finally:
        # Clean up temp directory
        if os.path.exists(tmp_base):
            shutil.rmtree(tmp_base, ignore_errors=True)
            console.print(f"\n  [dim]Cleaned up temp dir: {tmp_base}[/dim]")

    _save_artifacts(artifacts, total_cost, total_time, success=True)


def _save_artifacts(
    artifacts: dict[str, object],
    total_cost: float,
    total_time: float,
    *,
    success: bool,
) -> None:
    """Print final summary and persist artifacts to JSON."""
    artifacts["total_cost"] = total_cost
    artifacts["total_time"] = total_time
    artifacts["success"] = success
    artifacts["timestamp"] = datetime.now(tz=UTC).isoformat()

    # Final summary
    console.print()
    console.rule("[bold magenta]Pipeline Complete[/bold magenta]")

    summary = Table(title="Final Summary", show_header=False, border_style="magenta")
    summary.add_column("Metric", style="bold")
    summary.add_column("Value")
    summary.add_row("Status", "[green]SUCCESS[/green]" if success else "[red]FAILED[/red]")
    summary.add_row("Total time", f"{total_time:.1f}s")
    summary.add_row("Total cost", _cost_str(total_cost))

    # Per-stage cost breakdown if available
    stage_costs = []
    for key in ("ba", "researcher", "architect", "pm"):
        c = artifacts.get(f"{key}_cost")
        if c is not None:
            stage_costs.append(f"{key.upper()}: {_cost_str(c)}")
    if stage_costs:
        summary.add_row("Stage costs", " | ".join(stage_costs))

    # Coding phase stats
    ticket_results = artifacts.get("ticket_results")
    if isinstance(ticket_results, list) and ticket_results:
        approved = sum(1 for tr in ticket_results if tr.get("qa_verdict") == "approved")
        total = len(ticket_results)
        coding_cost = sum(tr.get("cost", 0) for tr in ticket_results)
        summary.add_row("Tickets coded", str(total))
        summary.add_row("QA approved", f"{approved}/{total}")
        summary.add_row("Coding phase cost", _cost_str(coding_cost))

    console.print(summary)

    # Save to disk — strip repo_path (temp dir, now deleted)
    save_artifacts = {k: v for k, v in artifacts.items() if k != "repo_path"}

    out_dir = _ensure_output_dir()
    filename = f"pipeline_run_{_timestamp()}.json"
    out_path = out_dir / filename

    # Convert any non-serialisable bits to strings
    def _default(obj: object) -> str:
        return str(obj)

    with open(out_path, "w") as fh:
        json.dump(save_artifacts, fh, indent=2, default=_default)

    console.print(f"\nArtifacts saved to [bold]{out_path}[/bold]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the full pipeline test."""
    parser = argparse.ArgumentParser(
        description="Manual validation: run the full Forge pipeline end-to-end.",
    )
    spec_group = parser.add_mutually_exclusive_group()
    spec_group.add_argument(
        "--spec",
        type=str,
        default=None,
        help="Inline business specification text.",
    )
    spec_group.add_argument(
        "--spec-file",
        type=str,
        default=None,
        help="Path to a text file containing the business specification.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model name to override the default (e.g. claude-sonnet-4-20250514).",
    )
    parser.add_argument(
        "--skip-coding",
        action="store_true",
        default=False,
        help="Skip the coding phase (only run BA -> Research -> Architect -> PM).",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the full pipeline validation script."""
    args = parse_args()

    # Resolve the spec text
    if args.spec_file:
        spec_path = Path(args.spec_file)
        if not spec_path.exists():
            console.print(f"[red]Error:[/red] spec file not found: {spec_path}")
            sys.exit(1)
        spec_text = spec_path.read_text().strip()
    elif args.spec:
        spec_text = args.spec
    else:
        spec_text = DEFAULT_SPEC

    # Sanity check: ensure API key is available
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        console.print(
            "[red]Error:[/red] ANTHROPIC_API_KEY is not set. Export it or add it to a .env file."
        )
        sys.exit(1)

    asyncio.run(run_pipeline(spec_text, args.model, args.skip_coding))


if __name__ == "__main__":
    main()
