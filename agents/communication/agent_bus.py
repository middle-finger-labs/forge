"""Core AgentBus — lightweight inter-agent Q&A during pipeline execution.

Communication happens at the orchestration layer (before/after agent runs),
not inside LLM calls.  All exchanges are logged as events visible in the
desktop app via ``stream_agent_log``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from agents.communication.types import AgentResponse
from contracts.schemas import AgentRole

log = structlog.get_logger().bind(component="agent_bus")

# ---------------------------------------------------------------------------
# Responder system prompts — short, focused Q&A prompts per role
# ---------------------------------------------------------------------------

_RESPONDER_PROMPTS: dict[str, str] = {
    AgentRole.ARCHITECT: (
        "You are the Architect. Answer concisely about architecture patterns, "
        "dependency interfaces, module boundaries, and technical constraints. "
        "Reference the tech spec when relevant. Keep answers under 300 words."
    ),
    AgentRole.DEVELOPER: (
        "You are the Developer. Answer concisely about your implementation "
        "decisions, code structure, trade-offs you made, and how your code "
        "meets the acceptance criteria. Keep answers under 300 words."
    ),
    AgentRole.QA_ENGINEER: (
        "You are the QA Engineer. Answer concisely about test coverage, "
        "quality concerns, review findings, and what needs to be fixed. "
        "Keep answers under 300 words."
    ),
    AgentRole.CTO: (
        "You are the CTO. Answer concisely about pipeline decisions, conflict "
        "resolution, architectural trade-offs, and priority calls. "
        "Keep answers under 300 words."
    ),
    AgentRole.PRODUCT_MANAGER: (
        "You are the Product Manager. Answer concisely about business "
        "requirements, acceptance criteria, user stories, and scope decisions. "
        "Keep answers under 300 words."
    ),
}


class AgentBus:
    """Message bus enabling inter-agent communication during pipeline runs.

    Guardrails:
    - Max ``max_questions_per_agent`` questions per asking agent per run.
    - Timeout per question (default 120s).
    - Circular detection: if A is waiting on B, B cannot ask A.
    - All failures are best-effort — agents proceed without answers.
    """

    def __init__(
        self,
        pipeline_id: str,
        *,
        max_questions_per_agent: int = 3,
        question_timeout: float = 120.0,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.max_questions_per_agent = max_questions_per_agent
        self.question_timeout = question_timeout

        self._question_counts: dict[str, int] = {}
        self._active_conversations: set[str] = set()
        self._exchanges: list[dict[str, Any]] = []
        self._total_cost_usd: float = 0.0
        self._log = log.bind(pipeline_id=pipeline_id)

    # -- Public API ---------------------------------------------------------

    async def ask(
        self,
        from_role: str,
        to_role: str,
        question: str,
        context: str = "",
        timeout: float | None = None,
    ) -> AgentResponse:
        """Ask *to_role* a question on behalf of *from_role*.

        Returns an ``AgentResponse`` — always succeeds (best-effort).
        """
        effective_timeout = timeout or self.question_timeout

        # 1. Check question limit
        count_key = from_role
        current = self._question_counts.get(count_key, 0)
        if current >= self.max_questions_per_agent:
            self._log.info(
                "question limit reached",
                from_role=from_role,
                to_role=to_role,
                count=current,
            )
            return AgentResponse(
                from_role=from_role,
                to_role=to_role,
                question=question,
                response=(
                    f"Question limit reached ({self.max_questions_per_agent} max). "
                    "Proceed with your best judgment."
                ),
                hit_limit=True,
            )

        # 2. Check circular
        reverse_key = f"{to_role}->{from_role}"
        if reverse_key in self._active_conversations:
            self._log.info(
                "circular conversation detected",
                from_role=from_role,
                to_role=to_role,
            )
            return AgentResponse(
                from_role=from_role,
                to_role=to_role,
                question=question,
                response=(
                    "Circular dependency detected — both agents are waiting on "
                    "each other. Resolve independently with your best judgment."
                ),
                circular=True,
            )

        # 3. Mark conversation as active
        forward_key = f"{from_role}->{to_role}"
        self._active_conversations.add(forward_key)

        try:
            # 4. Build LLM messages
            system_prompt = _RESPONDER_PROMPTS.get(
                to_role,
                f"You are the {to_role}. Answer the question concisely. "
                "Keep answers under 300 words.",
            )
            if context:
                system_prompt += f"\n\nAdditional context:\n{context}"

            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Question from {from_role}: {question}"
                    ),
                },
            ]

            # 5. Log question event
            await self._stream_log(
                "agent_bus.question",
                agent_role=from_role,
                payload={
                    "from_role": from_role,
                    "to_role": to_role,
                    "question": question,
                },
            )

            # 6. Call LLM via ModelRouter
            from config.model_router import get_model_router

            router = get_model_router()
            model = await router.route_request(to_role, task_complexity="small")

            result = await asyncio.wait_for(
                router.complete(
                    model,
                    messages,
                    max_tokens=1500,
                    temperature=0.3,
                ),
                timeout=effective_timeout,
            )

            response_text = result.get("content", "")
            cost = result.get("cost_usd", 0.0)

            # 7. Log response event
            await self._stream_log(
                "agent_bus.response",
                agent_role=to_role,
                payload={
                    "from_role": from_role,
                    "to_role": to_role,
                    "response_preview": response_text[:200],
                    "cost_usd": cost,
                },
            )

            # 8. Track state
            self._question_counts[count_key] = current + 1
            self._total_cost_usd += cost
            self._exchanges.append({
                "from_role": from_role,
                "to_role": to_role,
                "question": question,
                "response": response_text,
                "cost_usd": cost,
            })

            return AgentResponse(
                from_role=from_role,
                to_role=to_role,
                question=question,
                response=response_text,
                cost_usd=cost,
            )

        except TimeoutError:
            self._log.warning(
                "agent bus question timed out",
                from_role=from_role,
                to_role=to_role,
                timeout=effective_timeout,
            )
            await self._stream_log(
                "agent_bus.timeout",
                agent_role=from_role,
                payload={
                    "from_role": from_role,
                    "to_role": to_role,
                    "timeout": effective_timeout,
                },
            )
            return AgentResponse(
                from_role=from_role,
                to_role=to_role,
                question=question,
                response=f"Unable to reach {to_role}. Proceed with your best judgment.",
                timed_out=True,
            )

        except Exception as exc:
            self._log.warning(
                "agent bus ask failed",
                from_role=from_role,
                to_role=to_role,
                error=str(exc),
            )
            return AgentResponse(
                from_role=from_role,
                to_role=to_role,
                question=question,
                response=f"Unable to reach {to_role}. Proceed with your best judgment.",
            )

        finally:
            self._active_conversations.discard(forward_key)

    async def broadcast(
        self,
        from_role: str,
        message: str,
        context: str | None = None,
    ) -> None:
        """Broadcast a non-blocking message (no LLM call, log only)."""
        await self._stream_log(
            "agent_bus.broadcast",
            agent_role=from_role,
            payload={
                "from_role": from_role,
                "message": message,
                "context": context,
            },
        )

    # -- Properties ---------------------------------------------------------

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    @property
    def exchanges(self) -> list[dict[str, Any]]:
        return list(self._exchanges)

    # -- Internal -----------------------------------------------------------

    async def _stream_log(
        self,
        event_type: str,
        *,
        agent_role: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Best-effort event logging via stream_agent_log."""
        try:
            from memory.agent_log import stream_agent_log

            await stream_agent_log(
                self.pipeline_id,
                event_type,
                agent_role=agent_role,
                payload=payload,
            )
        except Exception as exc:
            self._log.debug("stream log failed", error=str(exc))
