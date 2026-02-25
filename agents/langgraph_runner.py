"""Reusable LangGraph runner for any Forge pipeline agent.

Builds a StateGraph with LLM call -> JSON validation -> retry loop, so every
agent gets structured output with automatic repair on schema violations.

When MCP tools are available (via ``org_id`` + ``agent_role``), the graph
gains a tool-execution loop:

    START -> call_llm -> route_response -> execute_tools -> call_llm -> ...
                             |
                             v
                       validate_output -> should_retry -> END

LLM calls are routed through :class:`~config.model_router.ModelRouter` which
uses LiteLLM under the hood.  The router selects models based on agent role
and task complexity, with automatic fallback on failure.

Error handling:
- 429 Too Many Requests: respect Retry-After, back off
- 500/502/503: exponential backoff, max 3 retries
- Timeout: increase timeout and retry once
- ContentFilterError: fail the activity immediately with a clear message
- AuthenticationError: fail immediately

Usage::

    from agents.langgraph_runner import run_agent
    from contracts.schemas import ProductSpec

    result, cost = await run_agent(
        system_prompt=STAGE_1_SYSTEM_PROMPT,
        human_prompt=rendered_template,
        output_model=ProductSpec,
        agent_role="business_analyst",
        org_id="org-123",  # enables MCP tool injection
    )
"""

from __future__ import annotations

import json
import os
import time
from typing import Annotated, TypedDict

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

log = structlog.get_logger().bind(component="langgraph_runner")

# ---------------------------------------------------------------------------
# Cost constants (USD per million tokens)
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-sonnet-4-5-latest": (3.0, 15.0),
    "claude-haiku-4-5-20241022": (1.0, 5.0),
    "ollama/qwen2.5-coder:32b": (0.0, 0.0),
}

_DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


def _cost_for_tokens(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    input_price, output_price = _PRICING.get(model, (3.0, 15.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


# ---------------------------------------------------------------------------
# Error classification (mirrors config.model_router._classify_error)
# ---------------------------------------------------------------------------

_CONTENT_FILTER_MARKERS = ("content_filter", "content_policy", "content moderation")
_AUTH_ERROR_MARKERS = ("authentication", "auth", "invalid_api_key", "permission")


def _classify_error(exc: Exception) -> str:
    """Classify *exc* into a retry category."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)

    if status == 429 or "rate_limit" in msg or "429" in msg:
        return "rate_limit"
    if status in (500, 502, 503) or "server_error" in msg or "overloaded" in msg:
        return "server_error"
    if "timeout" in name or "timeout" in msg or isinstance(exc, TimeoutError):
        return "timeout"
    for marker in _CONTENT_FILTER_MARKERS:
        if marker in msg:
            return "content_filter"
    for marker in _AUTH_ERROR_MARKERS:
        if marker in name or marker in msg:
            return "auth"
    return "unknown"


def _get_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After seconds from a 429 response if available."""
    headers = getattr(exc, "headers", None) or {}
    if isinstance(headers, dict):
        val = headers.get("retry-after") or headers.get("Retry-After")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return None


# ---------------------------------------------------------------------------
# Message format conversion helpers
# ---------------------------------------------------------------------------


def _langchain_to_litellm(messages: list[BaseMessage]) -> list[dict]:
    """Convert LangChain BaseMessage objects to litellm/OpenAI dicts."""
    result = []
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": content})
        elif isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": content})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": content})
        else:
            result.append({"role": "user", "content": content})
    return result


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """Typed state dict for the LangGraph agent loop.

    Tracks messages, validated output, retry budget, accumulated cost,
    and pending MCP tool calls from the LLM.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    output_json: str | None
    retries_remaining: int
    validation_errors: list[str]
    stage_name: str
    cost_usd: float
    # MCP tool call support
    pending_tool_calls: list[dict]  # [{name, arguments, call_id}] from LLM response


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_agent_graph(
    system_prompt: str,
    output_model: type,
    *,
    max_retries: int = 3,
    model: str | None = None,
    memory_context: str | None = None,
    codebase_context: str | None = None,
    agent_role: str | None = None,
    mcp_tools: list | None = None,
    mcp_tool_executor: object | None = None,
    org_id: str | None = None,
    pipeline_id: str | None = None,
) -> StateGraph:
    """Return a compiled StateGraph that calls an LLM and validates output.

    When *agent_role* is provided, the :class:`~config.model_router.ModelRouter`
    selects the model.  Otherwise *model* (or the ``FORGE_MODEL`` env var) is
    used directly.

    When *mcp_tools* is provided, tool definitions are injected into the
    system prompt and the graph gains a tool-execution loop that routes
    tool calls through *mcp_tool_executor*.
    """
    from connections.agent_tools import AgentConnectionTools, AgentTool

    resolved_model = model or os.environ.get("FORGE_MODEL", _DEFAULT_MODEL)
    _agent_role = agent_role  # captured by the closure below
    _mcp_tools: list[AgentTool] = mcp_tools or []
    _mcp_executor: AgentConnectionTools | None = mcp_tool_executor
    _org_id = org_id
    _pipeline_id = pipeline_id
    _has_tools = bool(_mcp_tools and _mcp_executor)

    # Build a lookup for fast tool dispatch
    _tool_map: dict[str, AgentTool] = {t.name: t for t in _mcp_tools}

    # Prepend memory context and codebase context to the system prompt
    effective_system_prompt = system_prompt
    if codebase_context:
        effective_system_prompt = (
            f"<codebase_context>\n{codebase_context}\n"
            f"</codebase_context>\n\n{effective_system_prompt}"
        )
    if memory_context:
        effective_system_prompt = (
            f"<context_from_previous_runs>\n{memory_context}\n"
            f"</context_from_previous_runs>\n\n{effective_system_prompt}"
        )
    if _has_tools:
        effective_system_prompt = _inject_tool_prompt(
            effective_system_prompt, _mcp_tools
        )

    # Langfuse generation recording (lazy import, no-op if unavailable)
    try:
        from memory.observability import record_generation as _record_gen
    except ImportError:
        _record_gen = None

    # -- nodes --------------------------------------------------------------

    async def call_llm(state: AgentState) -> dict:
        """Send messages to the LLM via ModelRouter and return the response."""
        import asyncio as _asyncio

        full_messages = [SystemMessage(content=effective_system_prompt), *state["messages"]]

        # Determine which model to use
        actual_model = resolved_model
        if _agent_role:
            try:
                from config.model_router import get_model_router

                router = get_model_router()
                actual_model = await router.route_request(_agent_role)
            except Exception:
                pass  # fall back to resolved_model

        # Convert to litellm format and call via ModelRouter
        litellm_messages = _langchain_to_litellm(full_messages)
        msg_count = len(litellm_messages)

        # -- Stream llm.request_started event --------------------------------
        _pipeline_ctx = None
        try:
            from memory.observability import get_pipeline_context
            _pipeline_ctx = get_pipeline_context()
        except Exception:
            pass

        if _pipeline_ctx and _pipeline_ctx.get("pipeline_id"):
            try:
                from memory.agent_log import stream_agent_log
                await stream_agent_log(
                    _pipeline_ctx["pipeline_id"],
                    "llm.request_started",
                    agent_role=_pipeline_ctx.get("agent_role") or _agent_role,
                    stage=_pipeline_ctx.get("stage"),
                    payload={"model": actual_model, "message_count": msg_count},
                )
            except Exception:
                pass

        start_ts = time.monotonic()

        try:
            from config.model_router import get_model_router

            router = get_model_router()

            log.debug(
                "call_llm start",
                model=actual_model,
                agent_role=_agent_role,
                message_count=msg_count,
            )

            result = await router.complete(
                actual_model,
                litellm_messages,
                max_tokens=16384,
                temperature=0.1,
            )
            latency_ms = result["latency_ms"]

            content = result["content"]
            input_tokens = result["input_tokens"]
            output_tokens = result["output_tokens"]
            cost_delta = result["cost_usd"]
            actual_model = result["model_used"]

            log.debug(
                "call_llm success",
                model=actual_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost_delta, 6),
                latency_ms=round(latency_ms, 1),
            )

            # -- Stream llm.request_completed event --------------------------
            if _pipeline_ctx and _pipeline_ctx.get("pipeline_id"):
                try:
                    from memory.agent_log import stream_agent_log
                    await stream_agent_log(
                        _pipeline_ctx["pipeline_id"],
                        "llm.request_completed",
                        agent_role=_pipeline_ctx.get("agent_role") or _agent_role,
                        stage=_pipeline_ctx.get("stage"),
                        payload={
                            "model": actual_model,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "cost_usd": round(cost_delta, 6),
                            "latency_ms": round(latency_ms, 1),
                        },
                    )
                except Exception:
                    pass

        except Exception as primary_exc:
            category = _classify_error(primary_exc)

            # -- Stream llm.request_failed event -----------------------------
            if _pipeline_ctx and _pipeline_ctx.get("pipeline_id"):
                try:
                    from memory.agent_log import stream_agent_log
                    await stream_agent_log(
                        _pipeline_ctx["pipeline_id"],
                        "llm.request_failed",
                        agent_role=_pipeline_ctx.get("agent_role") or _agent_role,
                        stage=_pipeline_ctx.get("stage"),
                        payload={
                            "model": actual_model,
                            "error_category": category,
                            "error": str(primary_exc)[:200],
                        },
                    )
                except Exception:
                    pass

            # Non-retryable at the runner level — propagate immediately
            if category in ("content_filter", "auth"):
                log.error(
                    "call_llm non-retryable error",
                    model=actual_model,
                    error_category=category,
                    error=str(primary_exc)[:200],
                )
                raise

            # Retryable errors: attempt ChatAnthropic fallback
            log.warning(
                "call_llm primary path failed, trying ChatAnthropic fallback",
                model=actual_model,
                error_category=category,
                error=str(primary_exc)[:200],
            )

            # For timeout errors, retry once with a longer timeout
            retry_delay = 0.0
            if category == "rate_limit":
                retry_delay = _get_retry_after(primary_exc) or 5.0
            elif category == "timeout":
                retry_delay = 1.0
            elif category == "server_error":
                retry_delay = 2.0

            if retry_delay > 0:
                await _asyncio.sleep(retry_delay)

            try:
                from langchain_anthropic import ChatAnthropic

                llm = ChatAnthropic(model=actual_model, temperature=0.1)
                response: AIMessage = llm.invoke(full_messages)
                latency_ms = (time.monotonic() - start_ts) * 1000

                content = response.content if isinstance(response.content, str) else ""
                input_tokens = 0
                output_tokens = 0
                cost_delta = 0.0
                if response.usage_metadata:
                    input_tokens = response.usage_metadata.get("input_tokens", 0)
                    output_tokens = response.usage_metadata.get("output_tokens", 0)
                    cost_delta = _cost_for_tokens(
                        actual_model,
                        input_tokens,
                        output_tokens,
                    )

                log.debug(
                    "call_llm fallback success",
                    model=actual_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=round(cost_delta, 6),
                    latency_ms=round(latency_ms, 1),
                )

                return {
                    "messages": [response],
                    "cost_usd": state["cost_usd"] + cost_delta,
                }

            except Exception as fallback_exc:
                fb_category = _classify_error(fallback_exc)
                log.error(
                    "call_llm fallback also failed",
                    model=actual_model,
                    error_category=fb_category,
                    error=str(fallback_exc)[:200],
                )
                raise primary_exc from fallback_exc

        # Wrap content as an AIMessage for LangGraph state
        ai_message = AIMessage(
            content=content,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

        # Record generation span in Langfuse
        if _record_gen is not None:
            human_msgs = [
                {"role": "human", "content": m.content[:500]}
                for m in state["messages"]
                if isinstance(m, HumanMessage) and isinstance(m.content, str)
            ]
            _record_gen(
                model=actual_model,
                input_messages=[
                    {"role": "system", "content": effective_system_prompt[:500]},
                    *human_msgs,
                ],
                output=content[:2000],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_delta,
                latency_ms=latency_ms,
            )

        return {
            "messages": [ai_message],
            "cost_usd": state["cost_usd"] + cost_delta,
        }

    # -- tool execution nodes (only active when MCP tools are available) ----

    def route_response(state: AgentState) -> str:
        """After validate_output: route to tool execution, retry, or end."""
        pending = state.get("pending_tool_calls") or []
        if pending:
            return "execute_tools"
        # Fall through to normal should_retry logic
        if state["output_json"] is not None:
            return END
        if state["retries_remaining"] <= 0:
            return END
        return "call_llm"

    async def execute_tools(state: AgentState) -> dict:
        """Execute pending MCP tool calls and return results to the LLM."""
        pending = state.get("pending_tool_calls") or []
        if not pending:
            return {"pending_tool_calls": []}

        results_text_parts: list[str] = []
        for call in pending:
            tool_name = call.get("name", "")
            arguments = call.get("arguments", {})
            call_id = call.get("call_id", "")

            agent_tool = _tool_map.get(tool_name)
            if agent_tool is None:
                results_text_parts.append(
                    f"<tool_result name=\"{tool_name}\" call_id=\"{call_id}\">\n"
                    f"Error: Unknown tool '{tool_name}'. "
                    f"Available tools: {', '.join(_tool_map.keys())}\n"
                    f"</tool_result>"
                )
                continue

            try:
                result = await _mcp_executor.execute_tool(
                    agent_tool,
                    arguments,
                    org_id=_org_id,
                    agent_role=_agent_role,
                    pipeline_id=_pipeline_id,
                )
                # Format result text
                content_blocks = result.get("content", [])
                text_parts = [
                    block.get("text", str(block))
                    for block in content_blocks
                ]
                result_text = "\n".join(text_parts) if text_parts else "(empty result)"
                is_error = result.get("is_error", False)

                results_text_parts.append(
                    f"<tool_result name=\"{tool_name}\" call_id=\"{call_id}\""
                    f"{' error=\"true\"' if is_error else ''}>\n"
                    f"{result_text}\n"
                    f"</tool_result>"
                )

            except Exception as exc:
                log.warning(
                    "MCP tool execution failed",
                    tool_name=tool_name,
                    error=str(exc),
                )
                results_text_parts.append(
                    f"<tool_result name=\"{tool_name}\" call_id=\"{call_id}\" error=\"true\">\n"
                    f"Error executing tool: {str(exc)[:200]}\n"
                    f"</tool_result>"
                )

        # Inject results back as a HumanMessage for the next LLM turn
        results_message = HumanMessage(
            content="Here are the results of your tool calls:\n\n"
            + "\n\n".join(results_text_parts)
            + "\n\nUse these results to continue your task. "
            "When you have enough information, produce your final JSON output."
        )

        return {
            "messages": [results_message],
            "pending_tool_calls": [],
        }

    def validate_output(state: AgentState) -> dict:
        """Parse the last AI message as JSON and validate against the output model."""
        last_msg = state["messages"][-1]
        text = last_msg.content if isinstance(last_msg.content, str) else ""

        # If tools are available, check for tool calls in the response first
        if _has_tools:
            tool_calls = _extract_tool_calls(text, _tool_map)
            if tool_calls:
                return {"pending_tool_calls": tool_calls}

        try:
            parsed = output_model.model_validate_json(text)
            return {"output_json": parsed.model_dump_json()}
        except (json.JSONDecodeError, ValidationError) as exc:
            error_detail = str(exc)
            remaining = state["retries_remaining"] - 1
            fix_prompt = (
                f"Your previous output failed validation:\n{error_detail}\n\n"
                "Please fix your JSON output to match the required schema "
                "and return ONLY valid JSON."
            )
            return {
                "retries_remaining": remaining,
                "validation_errors": [*state["validation_errors"], error_detail],
                "messages": [HumanMessage(content=fix_prompt)],
            }

    def should_retry(state: AgentState) -> str:
        """Return the next node name, or END if output is valid or retries are exhausted."""
        if state["output_json"] is not None:
            return END
        if state["retries_remaining"] <= 0:
            return END
        return "call_llm"

    # -- graph assembly -----------------------------------------------------

    graph = StateGraph(AgentState)

    graph.add_node("call_llm", call_llm)
    graph.add_node("validate_output", validate_output)

    if _has_tools:
        graph.add_node("execute_tools", execute_tools)

        graph.add_edge(START, "call_llm")
        graph.add_edge("call_llm", "validate_output")
        # validate_output detects tool calls -> sets pending_tool_calls
        # route_response checks pending_tool_calls to decide next step
        graph.add_conditional_edges("validate_output", route_response)
        graph.add_edge("execute_tools", "call_llm")
    else:
        graph.add_edge(START, "call_llm")
        graph.add_edge("call_llm", "validate_output")
        graph.add_conditional_edges("validate_output", should_retry)

    return graph.compile()


# ---------------------------------------------------------------------------
# High-level async entry point
# ---------------------------------------------------------------------------


async def run_agent(
    system_prompt: str,
    human_prompt: str,
    output_model: type,
    *,
    model: str | None = None,
    max_retries: int = 3,
    memory_context: str | None = None,
    codebase_context: str | None = None,
    agent_role: str | None = None,
    org_id: str | None = None,
) -> tuple[dict | None, float]:
    """Run an agent graph and return (parsed_output_dict | None, cost_usd).

    Parameters
    ----------
    system_prompt:
        The system prompt defining the agent's role and instructions.
    human_prompt:
        The user message containing the task input.
    output_model:
        A Pydantic model class used to validate the LLM's JSON output.
    model:
        Override the LLM model name.  Falls back to ``FORGE_MODEL`` env var,
        then to the default Sonnet 4.5 model.
    max_retries:
        Maximum validation retry attempts before giving up.
    memory_context:
        Optional context from semantic memory to prepend to the system prompt.
    codebase_context:
        Optional assembled codebase context to prepend to the system prompt.
    agent_role:
        Agent role string (e.g. ``"architect"``, ``"developer"``).  When
        provided, :class:`~config.model_router.ModelRouter` selects the
        model, overriding the *model* parameter.
    org_id:
        Organisation ID.  When provided alongside *agent_role*, MCP tools
        are fetched and injected into the agent's execution loop.

    Returns
    -------
    tuple[dict | None, float]
        A 2-tuple of (parsed JSON dict or None on failure, accumulated cost).
    """

    # If agent_role is provided, route via ModelRouter to determine the model
    routed_model = model
    if agent_role:
        try:
            from config.model_router import get_model_router

            router = get_model_router()
            routed_model = await router.route_request(agent_role)
        except Exception:
            pass  # fall back to model / env var / default

    # Resolve pipeline context for pipeline_id
    _pipeline_id: str | None = None
    try:
        from memory.observability import get_pipeline_context
        ctx = get_pipeline_context()
        if ctx:
            _pipeline_id = ctx.get("pipeline_id")
    except Exception:
        pass

    # Fetch MCP tools if org_id and agent_role are available
    mcp_tools = None
    mcp_executor = None
    if org_id and agent_role:
        try:
            mcp_tools, mcp_executor = await _load_mcp_tools(org_id, agent_role)
        except Exception as exc:
            log.debug("MCP tool loading skipped", error=str(exc))

    # Create a Langfuse trace if configured and no parent trace exists
    _owns_trace = False
    try:
        from memory.observability import create_trace, end_trace, get_current_trace

        if get_current_trace() is None:
            create_trace(agent_role=output_model.__name__)
            _owns_trace = True
    except ImportError:
        pass

    compiled = build_agent_graph(
        system_prompt,
        output_model,
        max_retries=max_retries,
        model=routed_model,
        memory_context=memory_context,
        codebase_context=codebase_context,
        agent_role=agent_role,
        mcp_tools=mcp_tools,
        mcp_tool_executor=mcp_executor,
        org_id=org_id,
        pipeline_id=_pipeline_id,
    )

    initial_state: AgentState = {
        "messages": [HumanMessage(content=human_prompt)],
        "output_json": None,
        "retries_remaining": max_retries,
        "validation_errors": [],
        "stage_name": "",
        "cost_usd": 0.0,
        "pending_tool_calls": [],
    }

    result = await compiled.ainvoke(initial_state)

    output: dict | None = None
    if result["output_json"] is not None:
        output = json.loads(result["output_json"])

    # Complete the trace we own
    if _owns_trace:
        try:
            end_trace(
                output={
                    "success": output is not None,
                    "cost_usd": result["cost_usd"],
                }
            )
        except Exception:
            pass

    return output, result["cost_usd"]


# ---------------------------------------------------------------------------
# MCP tool integration helpers
# ---------------------------------------------------------------------------


async def _load_mcp_tools(
    org_id: str,
    agent_role: str,
) -> tuple[list, object]:
    """Fetch MCP tools for the agent and return (tools, executor).

    Returns empty list / None if no tools are available or the connections
    module is not initialised.
    """
    from connections.agent_tools import AgentConnectionTools
    from connections.client_manager import MCPClientManager
    from connections.registry import ConnectionRegistry
    from connections.tool_filter import ToolFilter

    # Use the global client manager if available, otherwise create a temporary one
    try:
        from api.server import _mcp_manager
        manager = _mcp_manager
    except (ImportError, AttributeError):
        manager = MCPClientManager(ConnectionRegistry())

    executor = AgentConnectionTools(manager, ToolFilter())
    tools = await executor.get_tools_for_agent(org_id, agent_role)

    if not tools:
        return None, None

    log.info(
        "MCP tools loaded for agent",
        agent_role=agent_role,
        org_id=org_id,
        tool_count=len(tools),
        tools=[t.name for t in tools],
    )
    return tools, executor


def _inject_tool_prompt(system_prompt: str, tools: list) -> str:
    """Append rich connection context and MCP tool definitions to the prompt.

    Groups tools by service/connection with permission-level descriptions
    so the agent understands what each connection offers, then includes
    XML tool definitions for precise calling.
    """
    from collections import defaultdict

    # Group tools by (service, display_name) to describe each connection
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for tool in tools:
        key = (tool.service, tool.display_name)
        groups[key].append(tool)

    service_icons = {
        "notion": "\U0001f4d3",
        "linear": "\U0001f537",
        "figma": "\U0001f3a8",
        "jira": "\U0001f3ab",
        "google_drive": "\U0001f4c4",
    }

    # Build human-readable connection descriptions
    sections: list[str] = [
        "\n\n## Available External Tools\n",
        "You have access to the following connected services via MCP. "
        "Use them proactively when they can improve your output.\n",
    ]

    for (service, display_name), group_tools in groups.items():
        icon = service_icons.get(service, "\U0001f527")
        # Infer permission level from available tool classifications
        has_write = any(
            any(w in t.original_tool_name.lower() for w in (
                "create", "update", "add", "set", "post", "put", "edit",
                "modify", "write", "send", "submit",
            ))
            for t in group_tools
        )
        has_admin = any(
            any(w in t.original_tool_name.lower() for w in (
                "delete", "remove", "archive", "destroy",
            ))
            for t in group_tools
        )
        if has_admin:
            perm_label = "full access"
        elif has_write:
            perm_label = "read + write"
        else:
            perm_label = "read only"

        sections.append(
            f"### {icon} {display_name} \u2014 "
            f"{service.replace('_', ' ').title()} ({perm_label})"
        )
        sections.append("")
        sections.append("Available tools:")
        for t in group_tools:
            # Strip the "[Display Name]" prefix from description for cleaner display
            desc = t.description
            if desc.startswith("["):
                desc = desc.split("] ", 1)[-1]
            sections.append(f"- `{t.name}`: {desc}")
        sections.append("")

    # Add calling convention
    sections.append(
        "To call a tool, include a `<tool_call>` block in your response "
        "BEFORE your final JSON output:"
    )
    sections.append("")
    sections.append('```')
    sections.append('<tool_call name="tool_name">')
    sections.append('{"param1": "value1", "param2": "value2"}')
    sections.append("</tool_call>")
    sections.append('```')
    sections.append("")
    sections.append(
        "You may call multiple tools in a single response. After receiving "
        "tool results, use them to inform your final JSON output."
    )

    # XML tool definitions for precise parameter schemas
    tool_defs: list[str] = []
    for tool in tools:
        params_json = json.dumps(tool.input_schema, indent=2) if tool.input_schema else "{}"
        tool_defs.append(
            f"  <tool name=\"{tool.name}\">\n"
            f"    <description>{tool.description}</description>\n"
            f"    <parameters>{params_json}</parameters>\n"
            f"  </tool>"
        )

    sections.append("")
    sections.append("<tool_definitions>")
    sections.extend(tool_defs)
    sections.append("</tool_definitions>")

    return system_prompt + "\n".join(sections)


def _extract_tool_calls(text: str, tool_map: dict) -> list[dict]:
    """Parse ``<tool_call>`` blocks from the LLM's response text.

    Returns a list of ``{"name": ..., "arguments": ..., "call_id": ...}``
    dicts, or an empty list if no tool calls are found.
    """
    import re
    import uuid

    pattern = re.compile(
        r'<tool_call\s+name="([^"]+)">\s*(\{.*?\})\s*</tool_call>',
        re.DOTALL,
    )

    calls: list[dict] = []
    for match in pattern.finditer(text):
        name = match.group(1)
        args_str = match.group(2)

        # Only accept known tools
        if name not in tool_map:
            continue

        try:
            arguments = json.loads(args_str)
        except json.JSONDecodeError:
            log.warning("failed to parse tool call arguments", tool_name=name)
            continue

        calls.append({
            "name": name,
            "arguments": arguments,
            "call_id": uuid.uuid4().hex[:12],
        })

    return calls
