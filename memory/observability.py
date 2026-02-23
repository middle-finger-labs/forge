"""Langfuse observability for LLM calls in the Forge pipeline.

Provides:
- ``get_langfuse()`` — lazy singleton Langfuse client (no-op if unconfigured)
- ``set_pipeline_context()`` / ``get_pipeline_context()`` — pipeline metadata
  propagation via contextvars
- ``create_trace()`` / ``end_trace()`` — manual trace lifecycle
- ``record_generation()`` — record an LLM generation on the current trace
- ``traced_agent()`` — decorator for wrapping agent functions
- ``get_pipeline_cost_summary()`` — aggregate cost data from Langfuse

If ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are not set,
*all* functions degrade to silent no-ops — the pipeline runs without
any observability overhead.

Usage::

    from memory.observability import set_pipeline_context, traced_agent

    # In an activity:
    set_pipeline_context(pipeline_id="abc", agent_role="architect")

    # As a decorator:
    @traced_agent("business_analyst")
    async def run_ba_agent(spec: str) -> tuple[dict | None, float]:
        ...
"""

from __future__ import annotations

import contextvars
import functools
import os
from typing import Any

import structlog

log = structlog.get_logger().bind(component="observability")

# ---------------------------------------------------------------------------
# Context variables
# ---------------------------------------------------------------------------

_pipeline_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "pipeline_context",
    default=None,
)
_current_trace: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "langfuse_trace",
    default=None,
)

# ---------------------------------------------------------------------------
# Langfuse singleton
# ---------------------------------------------------------------------------

_langfuse: Any = None
_langfuse_checked: bool = False


def get_langfuse() -> Any:
    """Return the singleton Langfuse client, or *None* if not configured."""
    global _langfuse, _langfuse_checked  # noqa: PLW0603
    if _langfuse_checked:
        return _langfuse
    _langfuse_checked = True

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        log.debug("langfuse not configured (missing keys)")
        return None

    try:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=os.environ.get("LANGFUSE_HOST", "http://localhost:3001"),
        )
        log.info("langfuse client initialised")
        return _langfuse
    except Exception as exc:
        log.warning("langfuse initialisation failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Pipeline context helpers
# ---------------------------------------------------------------------------


def set_pipeline_context(
    pipeline_id: str,
    agent_role: str = "",
    ticket_id: str = "",
    stage: str = "",
    org_id: str = "",
) -> None:
    """Set pipeline metadata for the current async context.

    Call this at the top of an activity before invoking an agent so that
    ``run_agent()`` and ``record_generation()`` can tag their traces.
    """
    _pipeline_context.set(
        {
            "pipeline_id": pipeline_id,
            "agent_role": agent_role,
            "ticket_id": ticket_id,
            "stage": stage,
            "org_id": org_id,
        }
    )


def get_pipeline_context() -> dict | None:
    """Return the current pipeline context, or *None*."""
    return _pipeline_context.get()


# ---------------------------------------------------------------------------
# Trace lifecycle
# ---------------------------------------------------------------------------


def get_current_trace() -> Any:
    """Return the active Langfuse trace, or *None*."""
    return _current_trace.get()


def create_trace(agent_role: str | None = None) -> Any:
    """Create a Langfuse trace from pipeline context.

    Returns the trace object, or *None* if Langfuse is not configured.
    Also stores the trace in the contextvar so ``record_generation()``
    can find it.
    """
    langfuse = get_langfuse()
    if not langfuse:
        return None

    ctx = get_pipeline_context() or {}
    name = agent_role or ctx.get("agent_role") or "unknown"
    pipeline_id = ctx.get("pipeline_id", "")

    try:
        tags = [f"pipeline:{pipeline_id}"] if pipeline_id else []
        trace = langfuse.trace(name=name, tags=tags, metadata=ctx)
        _current_trace.set(trace)
        return trace
    except Exception as exc:
        log.debug("failed to create langfuse trace", error=str(exc))
        return None


def end_trace(
    output: dict | None = None,
    error: str | None = None,
) -> None:
    """Complete the current trace and flush to Langfuse."""
    trace = _current_trace.get()
    if trace is None:
        return

    try:
        if error:
            trace.event(name="error", metadata={"error": error})
        if output:
            trace.update(output=output)
    except Exception:
        pass

    try:
        langfuse = get_langfuse()
        if langfuse:
            langfuse.flush()
    except Exception:
        pass

    _current_trace.set(None)


# ---------------------------------------------------------------------------
# Generation recording
# ---------------------------------------------------------------------------


def record_generation(
    *,
    name: str = "llm-call",
    model: str = "",
    input_messages: list[dict] | None = None,
    output: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: float = 0.0,
    metadata: dict | None = None,
) -> None:
    """Record an LLM generation span on the current trace.

    No-op if there is no active trace (i.e. Langfuse is not configured).
    """
    trace = _current_trace.get()
    if trace is None:
        return

    try:
        gen = trace.generation(
            name=name,
            model=model,
            input=input_messages or [],
            output=output,
            usage={"input": input_tokens, "output": output_tokens},
            metadata={
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                **(metadata or {}),
            },
        )
        gen.end()
    except Exception as exc:
        log.debug("failed to record langfuse generation", error=str(exc))


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def traced_agent(agent_role: str):
    """Decorator that wraps an async agent function with Langfuse tracing.

    Creates a trace before the function runs, records the result on
    completion, and captures errors.  If Langfuse is not configured the
    decorator is a transparent passthrough.

    Usage::

        @traced_agent("business_analyst")
        async def run_ba_agent(spec: str) -> tuple[dict | None, float]:
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if get_langfuse() is None:
                return await func(*args, **kwargs)

            create_trace(agent_role=agent_role)
            try:
                result = await func(*args, **kwargs)
                # Agent functions return (dict | None, cost_usd)
                if isinstance(result, tuple) and len(result) >= 2:
                    end_trace(
                        output={
                            "success": result[0] is not None,
                            "cost_usd": result[1],
                        }
                    )
                else:
                    end_trace(output={"result": str(result)[:500]})
                return result
            except Exception as exc:
                end_trace(error=str(exc))
                raise

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Cost summary query
# ---------------------------------------------------------------------------


async def get_pipeline_cost_summary(pipeline_id: str) -> dict:
    """Query Langfuse for aggregate cost data for a pipeline.

    Returns a dict with total cost, cost-by-role breakdown, total tokens,
    average latency, and LLM call count.  Runs synchronous Langfuse API
    calls in the current thread (suitable for activities).
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return {"available": False, "error": "Langfuse not configured"}

    try:
        traces_resp = langfuse.fetch_traces(
            tags=[f"pipeline:{pipeline_id}"],
            limit=100,
        )
        traces = traces_resp.data if hasattr(traces_resp, "data") else []

        total_cost = 0.0
        total_tokens = 0
        cost_by_role: dict[str, float] = {}
        latencies: list[float] = []
        llm_calls = 0

        for trace in traces:
            role = getattr(trace, "name", "unknown") or "unknown"

            obs_resp = langfuse.fetch_observations(
                trace_id=trace.id,
                type="GENERATION",
                limit=100,
            )
            observations = obs_resp.data if hasattr(obs_resp, "data") else []

            for obs in observations:
                llm_calls += 1

                obs_cost = getattr(obs, "calculated_total_cost", None) or 0.0
                total_cost += obs_cost
                cost_by_role[role] = cost_by_role.get(role, 0.0) + obs_cost

                usage = getattr(obs, "usage", None)
                if isinstance(usage, dict):
                    total_tokens += usage.get("input", 0) + usage.get("output", 0)

                start = getattr(obs, "start_time", None)
                end = getattr(obs, "end_time", None)
                if start and end:
                    delta_ms = (end - start).total_seconds() * 1000
                    latencies.append(delta_ms)

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        return {
            "available": True,
            "pipeline_id": pipeline_id,
            "total_cost_usd": round(total_cost, 6),
            "cost_by_role": {k: round(v, 6) for k, v in cost_by_role.items()},
            "total_tokens": total_tokens,
            "avg_latency_ms": round(avg_latency, 1),
            "llm_calls": llm_calls,
            "traces": len(traces),
        }
    except Exception as exc:
        log.warning("failed to fetch pipeline cost summary", error=str(exc))
        return {"available": False, "error": str(exc)}
