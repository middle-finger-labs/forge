"""Cost budget guardrails for the Forge pipeline.

Enforces spend limits at 50% (warning), 80% (alert + model downgrade),
and 100% (hard stop).  Provides per-stage budget caps, remaining-cost
estimation, and optimisation suggestions.

Usage::

    from config.budget import get_budget_manager

    bm = get_budget_manager()
    status = bm.check_budget(current_cost=12.5, current_stage="coding")
    if status.hard_stop:
        raise RuntimeError("Budget exceeded")
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Budget status
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """Snapshot of budget utilisation returned by ``BudgetManager.check_budget``."""

    total_budget: float
    current_cost: float
    remaining: float
    utilisation_pct: float
    warning: bool = False  # >= 50 %
    alert: bool = False  # >= 80 %
    hard_stop: bool = False  # >= 100 %
    stage_budget_exceeded: bool = False
    current_stage: str = ""
    message: str = ""


# ---------------------------------------------------------------------------
# Per-stage budget caps (USD)
# ---------------------------------------------------------------------------

_DEFAULT_STAGE_BUDGETS: dict[str, float] = {
    "business_analysis": 3.0,
    "research": 6.0,
    "architecture": 4.0,
    "task_decomposition": 3.0,
    "coding": 25.0,
    "qa_review": 6.0,
    "merge": 1.0,
}

# Average cost per LLM call by tier (used for remaining-cost estimation)
_AVG_COST_PER_CALL: dict[str, float] = {
    "frontier": 0.08,
    "strong": 0.05,
    "local_coder": 0.00,
}

# Stages remaining after each stage (used for remaining-cost estimation)
_STAGES_AFTER: dict[str, list[str]] = {
    "intake": [
        "business_analysis",
        "research",
        "architecture",
        "task_decomposition",
        "coding",
        "qa_review",
        "merge",
    ],
    "business_analysis": [
        "research",
        "architecture",
        "task_decomposition",
        "coding",
        "qa_review",
        "merge",
    ],
    "research": [
        "architecture",
        "task_decomposition",
        "coding",
        "qa_review",
        "merge",
    ],
    "architecture": [
        "task_decomposition",
        "coding",
        "qa_review",
        "merge",
    ],
    "task_decomposition": ["coding", "qa_review", "merge"],
    "coding": ["qa_review", "merge"],
    "qa_review": ["merge"],
    "merge": [],
}


# ---------------------------------------------------------------------------
# BudgetManager
# ---------------------------------------------------------------------------


class BudgetManager:
    """Enforce and monitor cost budgets for a pipeline run.

    Thresholds
    ----------
    - **50 %** utilisation: emits a warning (logged, non-blocking).
    - **80 %** utilisation: emits a cost alert; callers should switch
      engineers to cheaper / local models.
    - **100 %** utilisation: hard stop; the pipeline must abort.
    """

    def __init__(
        self,
        max_pipeline_cost: float = 50.0,
        alert_threshold: float = 25.0,
    ) -> None:
        self.max_pipeline_cost = float(
            os.environ.get("FORGE_MAX_COST_USD", max_pipeline_cost),
        )
        self.alert_threshold = float(
            os.environ.get("FORGE_COST_ALERT_USD", alert_threshold),
        )
        self.stage_budgets: dict[str, float] = dict(_DEFAULT_STAGE_BUDGETS)
        self._stage_costs: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def check_budget(
        self,
        current_cost: float,
        current_stage: str = "",
        stage_cost: float = 0.0,
    ) -> BudgetStatus:
        """Evaluate the budget and return a ``BudgetStatus`` snapshot.

        Parameters
        ----------
        current_cost:
            Total accumulated pipeline cost so far (USD).
        current_stage:
            The pipeline stage currently running.
        stage_cost:
            Cost accumulated in *current_stage* only (for per-stage cap check).
        """
        remaining = max(self.max_pipeline_cost - current_cost, 0.0)

        if self.max_pipeline_cost <= 0:
            # Zero or negative budget → immediate hard stop
            utilisation = 100.0
        else:
            utilisation = current_cost / self.max_pipeline_cost * 100

        warning = utilisation >= 50.0
        alert = utilisation >= 80.0
        hard_stop = utilisation >= 100.0

        # Per-stage cap
        stage_cap = self.stage_budgets.get(current_stage, float("inf"))
        stage_exceeded = stage_cost > stage_cap

        # Build human-readable message
        if hard_stop:
            msg = (
                f"BUDGET EXCEEDED: ${current_cost:.2f} / "
                f"${self.max_pipeline_cost:.2f} "
                f"({utilisation:.0f}%). Pipeline must stop."
            )
        elif alert:
            msg = (
                f"COST ALERT: ${current_cost:.2f} / "
                f"${self.max_pipeline_cost:.2f} "
                f"({utilisation:.0f}%). Consider switching to cheaper models."
            )
        elif warning:
            msg = (
                f"Cost warning: ${current_cost:.2f} / "
                f"${self.max_pipeline_cost:.2f} "
                f"({utilisation:.0f}%)."
            )
        else:
            msg = (
                f"Budget OK: ${current_cost:.2f} / "
                f"${self.max_pipeline_cost:.2f} "
                f"({utilisation:.0f}%)."
            )

        if stage_exceeded:
            msg += (
                f" Stage '{current_stage}' exceeded its "
                f"${stage_cap:.2f} cap (${stage_cost:.2f} spent)."
            )

        return BudgetStatus(
            total_budget=self.max_pipeline_cost,
            current_cost=current_cost,
            remaining=remaining,
            utilisation_pct=round(utilisation, 1),
            warning=warning,
            alert=alert,
            hard_stop=hard_stop,
            stage_budget_exceeded=stage_exceeded,
            current_stage=current_stage,
            message=msg,
        )

    # ------------------------------------------------------------------
    # Track per-stage spend
    # ------------------------------------------------------------------

    def record_stage_cost(self, stage: str, cost_delta: float) -> float:
        """Add *cost_delta* to the running total for *stage*. Returns new total."""
        self._stage_costs[stage] = self._stage_costs.get(stage, 0.0) + cost_delta
        return self._stage_costs[stage]

    def get_stage_cost(self, stage: str) -> float:
        """Return cost accumulated so far for *stage*."""
        return self._stage_costs.get(stage, 0.0)

    # ------------------------------------------------------------------
    # Remaining cost estimation
    # ------------------------------------------------------------------

    def estimate_remaining_cost(
        self,
        current_stage: str,
        tickets_remaining: int = 0,
        avg_cost_per_ticket: float | None = None,
    ) -> float:
        """Estimate remaining cost based on stages left and tickets remaining.

        Uses per-stage budget caps as upper-bound estimates for non-coding
        stages, and ``avg_cost_per_ticket * tickets_remaining`` for coding.
        """
        remaining_stages = _STAGES_AFTER.get(current_stage, [])
        estimate = 0.0

        for stage in remaining_stages:
            if stage == "coding" and tickets_remaining > 0:
                per_ticket = avg_cost_per_ticket or _AVG_COST_PER_CALL["strong"]
                estimate += per_ticket * tickets_remaining
            elif stage == "qa_review" and tickets_remaining > 0:
                estimate += _AVG_COST_PER_CALL["frontier"] * tickets_remaining
            else:
                # Use 60% of the stage cap as a realistic estimate
                estimate += self.stage_budgets.get(stage, 1.0) * 0.6

        return round(estimate, 4)

    # ------------------------------------------------------------------
    # Optimisation suggestions
    # ------------------------------------------------------------------

    def get_cost_optimization_suggestions(
        self,
        current_cost: float,
        current_stage: str,
    ) -> list[str]:
        """Return actionable suggestions based on current spend patterns."""
        suggestions: list[str] = []
        utilisation = (
            (current_cost / self.max_pipeline_cost * 100) if self.max_pipeline_cost > 0 else 0.0
        )

        if utilisation >= 80:
            suggestions.append(
                "Switch all engineer agents to local models "
                "(ollama/qwen2.5-coder:32b) to eliminate API costs."
            )
            suggestions.append("Reduce QA max_revisions to 1 to limit retry spending.")

        if utilisation >= 50:
            suggestions.append(
                "Consider using Haiku 4.5 instead of Sonnet 4.5 "
                "for research and ticket decomposition stages."
            )

        # Check per-stage overruns
        for stage, spent in self._stage_costs.items():
            cap = self.stage_budgets.get(stage, float("inf"))
            if spent > cap * 0.8:
                suggestions.append(
                    f"Stage '{stage}' is at {spent / cap * 100:.0f}% of its ${cap:.2f} budget cap."
                )

        if current_stage in ("coding", "qa_review"):
            suggestions.append(
                "Enable auto_approve_minor_only to skip revision "
                "cycles for non-critical QA comments."
            )

        return suggestions


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_budget_manager: BudgetManager | None = None


def get_budget_manager(
    max_pipeline_cost: float = 50.0,
    alert_threshold: float = 25.0,
) -> BudgetManager:
    """Return the process-wide BudgetManager singleton."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = BudgetManager(max_pipeline_cost, alert_threshold)
    return _budget_manager


def reset_budget_manager() -> None:
    """Reset the singleton (useful for tests and new pipeline runs)."""
    global _budget_manager
    _budget_manager = None
