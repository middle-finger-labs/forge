"""Context assembler — retrieves and ranks codebase context for agents.

Given a task description and a token budget, assembles the most relevant
code chunks from the index into a structured context block.  Three
retrieval strategies are supported:

- **semantic** — embed the task, search both code and description
  embeddings, merge with Reciprocal Rank Fusion (RRF)
- **structural** — given target files/symbols mentioned in the task,
  retrieve imports, callers, siblings, and parent definitions
- **hybrid** (default) — semantic search to find entry points, then
  structural expansion to include dependencies and related code

The context budget manager ensures the assembled context never exceeds
the token limit and always keeps chunks complete (never truncated mid-
function).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

from agents.codebase.embedder import ChunkEmbedder
from agents.codebase.file_tree import build_file_tree
from agents.codebase.store import CodeChunkStore

log = structlog.get_logger().bind(component="context_assembler")

# Rough token estimate: 1 token ≈ 4 characters for code
_CHARS_PER_TOKEN = 4

# Reserved tokens for the context map summary
_CONTEXT_MAP_BUDGET = 200

# Default top-k per search pass
_DEFAULT_SEMANTIC_K = 30
_DEFAULT_STRUCTURAL_K = 20


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RankedChunk:
    """A code chunk with its relevance score and priority tier."""

    chunk: dict  # chunk dict from store
    score: float
    tier: str  # "direct", "dependency", "structural", "broader"

    @property
    def token_estimate(self) -> int:
        body = self.chunk.get("body", "")
        return max(1, len(body) // _CHARS_PER_TOKEN)


@dataclass(slots=True)
class AssembledContext:
    """The final assembled context ready to inject into an agent prompt."""

    file_tree: str
    chunks: list[RankedChunk]
    context_map: str
    total_tokens: int
    excluded_count: int

    def format(self) -> str:
        """Render as a single string for injection into a prompt."""
        parts: list[str] = []

        # File tree overview
        if self.file_tree:
            parts.append("<file_tree>")
            parts.append(self.file_tree)
            parts.append("</file_tree>")

        # Context map
        if self.context_map:
            parts.append("")
            parts.append("<context_map>")
            parts.append(self.context_map)
            parts.append("</context_map>")

        # Code chunks by tier
        if self.chunks:
            parts.append("")
            parts.append("<codebase_context>")
            current_tier = ""
            for rc in self.chunks:
                if rc.tier != current_tier:
                    current_tier = rc.tier
                    parts.append(f"\n--- {current_tier.upper()} CONTEXT ---")
                c = rc.chunk
                header = (
                    f"\n# {c.get('file_path', '?')}:{c.get('start_line', '?')}"
                    f" — {c.get('chunk_type', '?')} {c.get('qualified_name', '?')}"
                )
                if c.get("signature"):
                    header += f" | {c['signature']}"
                parts.append(header)
                parts.append(c.get("body", ""))
            parts.append("</codebase_context>")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    *result_lists: list[dict],
    k: int = 60,
) -> list[dict]:
    """Merge multiple ranked result lists using RRF.

    Each result must have an ``"id"`` key.  Returns results sorted by
    fused score (descending), with the ``"score"`` field replaced by
    the RRF score.

    Args:
        result_lists: One or more ranked lists of result dicts.
        k: RRF constant (higher = less emphasis on top ranks).
    """
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    for results in result_lists:
        for rank, item in enumerate(results):
            item_id = item["id"]
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
            if item_id not in items:
                items[item_id] = item

    merged = []
    for item_id, score in sorted(scores.items(), key=lambda x: -x[1]):
        result = dict(items[item_id])
        result["score"] = score
        merged.append(result)

    return merged


# ---------------------------------------------------------------------------
# Structural expansion helpers
# ---------------------------------------------------------------------------


_IMPORT_PATTERNS = [
    # Python: from X import Y, import X
    re.compile(r"(?:from\s+([\w.]+)\s+)?import\s+([\w.,\s]+)", re.MULTILINE),
    # JS/TS: import ... from "X"
    re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE),
    # Rust: use X::Y
    re.compile(r"use\s+([\w:]+)", re.MULTILINE),
    # Go: import "X"
    re.compile(r'import\s+["\']([^"\']+)["\']', re.MULTILINE),
]


def extract_references(body: str) -> list[str]:
    """Extract imported/referenced symbol names from a code chunk body."""
    refs: set[str] = set()
    for pattern in _IMPORT_PATTERNS:
        for match in pattern.finditer(body):
            for group in match.groups():
                if group:
                    for part in group.split(","):
                        name = part.strip().split(".")[-1].split("::")[-1]
                        if name and name not in ("*", "_"):
                            refs.add(name)
    return sorted(refs)


def extract_mentioned_files(text: str) -> list[str]:
    """Extract file paths mentioned in a task description."""
    # Match patterns like src/foo/bar.py, ./components/X.tsx, etc.
    pattern = re.compile(
        r"(?:^|\s|['\"`])((?:[\w./-]+/)?[\w.-]+\.(?:py|ts|tsx|js|jsx|rs|go|java))\b"
    )
    return list({m.group(1) for m in pattern.finditer(text)})


def extract_mentioned_symbols(text: str) -> list[str]:
    """Extract function/class names mentioned in a task description."""
    # Match CamelCase or snake_case identifiers that look like code symbols
    pattern = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\.[a-z_]\w*)?|[a-z_]\w*(?:\.\w+)+)\b")
    candidates = {m.group(1) for m in pattern.finditer(text)}
    # Filter out common English words
    stopwords = {
        "The", "This", "That", "When", "Where", "Which", "What",
        "How", "Why", "For", "With", "From", "Into", "Each",
    }
    return sorted(candidates - stopwords)


# ---------------------------------------------------------------------------
# ContextAssembler
# ---------------------------------------------------------------------------


class ContextAssembler:
    """Assembles the most relevant codebase context for an agent's task.

    Usage::

        assembler = ContextAssembler(store, embedder)
        ctx = await assembler.assemble(
            task_description="Add email validation to signup endpoint",
            repo_url="https://github.com/org/repo",
            org_id="org-1",
        )
        prompt = f"{ctx.format()}\n\n{original_prompt}"
    """

    def __init__(
        self,
        store: CodeChunkStore,
        embedder: ChunkEmbedder,
    ) -> None:
        self._store = store
        self._embedder = embedder

    async def assemble(
        self,
        task_description: str,
        repo_url: str,
        org_id: str,
        *,
        max_tokens: int = 30_000,
        strategy: str = "hybrid",
        file_tree_budget: int = 800,
        agent_role: str | None = None,
        target_files: list[str] | None = None,
    ) -> AssembledContext:
        """Assemble context for an agent's task.

        Args:
            task_description: What the agent needs to do.
            repo_url: Repository URL for scoping.
            org_id: Organisation ID for scoping.
            max_tokens: Total token budget for the context.
            strategy: "semantic", "structural", or "hybrid" (default).
            file_tree_budget: Tokens reserved for the file tree.
            agent_role: Optional role hint for context tuning.
            target_files: Explicit files to include (e.g. from ticket).

        Returns:
            AssembledContext with ranked chunks, file tree, and context map.
        """
        # Step 1: Build file tree
        file_tree = await self._build_file_tree(org_id, repo_url, file_tree_budget)
        file_tree_tokens = len(file_tree) // _CHARS_PER_TOKEN

        # Step 2: Compute available budget
        available = max_tokens - file_tree_tokens - _CONTEXT_MAP_BUDGET

        # Step 3: Retrieve and rank chunks
        if strategy == "semantic":
            ranked = await self._semantic_search(
                task_description, org_id, repo_url, agent_role=agent_role,
            )
        elif strategy == "structural":
            ranked = await self._structural_search(
                task_description, org_id, repo_url,
                target_files=target_files,
            )
        else:
            ranked = await self._hybrid_search(
                task_description, org_id, repo_url,
                agent_role=agent_role, target_files=target_files,
            )

        # Step 4: Apply budget
        selected, excluded_count = self._apply_budget(ranked, available)

        # Step 5: Generate context map
        context_map = self._generate_context_map(selected, excluded_count)

        total_tokens = (
            file_tree_tokens
            + sum(rc.token_estimate for rc in selected)
            + len(context_map) // _CHARS_PER_TOKEN
        )

        return AssembledContext(
            file_tree=file_tree,
            chunks=selected,
            context_map=context_map,
            total_tokens=total_tokens,
            excluded_count=excluded_count,
        )

    # ------------------------------------------------------------------
    # Retrieval strategies
    # ------------------------------------------------------------------

    async def _semantic_search(
        self,
        task_description: str,
        org_id: str,
        repo_url: str,
        *,
        agent_role: str | None = None,
        top_k: int = _DEFAULT_SEMANTIC_K,
    ) -> list[RankedChunk]:
        """Embed task description, search both embeddings, merge with RRF."""
        import asyncio

        query_vec = await asyncio.to_thread(
            self._embedder._embed_texts, [task_description],
        )
        query_embedding = query_vec[0]

        # Parallel search against both embedding columns
        desc_results, code_results = await asyncio.gather(
            self._store.search(
                query_embedding, org_id=org_id, repo_url=repo_url,
                limit=top_k, mode="description",
            ),
            self._store.search(
                query_embedding, org_id=org_id, repo_url=repo_url,
                limit=top_k, mode="code",
            ),
        )

        # Merge with RRF
        fused = reciprocal_rank_fusion(desc_results, code_results)

        # Filter by role-specific chunk types
        type_filter = _role_type_filter(agent_role)
        if type_filter:
            fused = [r for r in fused if r.get("chunk_type") in type_filter]

        return [
            RankedChunk(chunk=r, score=r["score"], tier="direct")
            for r in fused
        ]

    async def _structural_search(
        self,
        task_description: str,
        org_id: str,
        repo_url: str,
        *,
        target_files: list[str] | None = None,
    ) -> list[RankedChunk]:
        """Retrieve dependencies, callers, and siblings for target symbols."""
        ranked: list[RankedChunk] = []
        seen_ids: set[str] = set()

        # Find target files and symbols from task description
        files = list(target_files or []) + extract_mentioned_files(task_description)
        symbols = extract_mentioned_symbols(task_description)

        # Search by file — get all chunks in mentioned files
        for fpath in files:
            results = await self._store.search_by_name(
                fpath.split("/")[-1].replace(".", ""),
                org_id=org_id, repo_url=repo_url, limit=30,
            )
            # Also try direct file path match
            file_results = await self._store.search_by_name(
                fpath, org_id=org_id, repo_url=repo_url, limit=30,
            )
            for r in results + file_results:
                if r["id"] not in seen_ids and r["file_path"] == fpath:
                    seen_ids.add(r["id"])
                    ranked.append(RankedChunk(
                        chunk=r, score=1.0, tier="direct",
                    ))

        # Search by symbol name
        for sym in symbols:
            results = await self._store.search_by_name(
                sym, org_id=org_id, repo_url=repo_url, limit=10,
            )
            for r in results:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    ranked.append(RankedChunk(
                        chunk=r, score=0.9, tier="direct",
                    ))

        # Expand: get dependencies (imports referenced by direct chunks)
        dep_chunks = await self._expand_dependencies(
            ranked, org_id, repo_url, seen_ids,
        )
        ranked.extend(dep_chunks)

        # Expand: get siblings (other chunks in the same file/class)
        sibling_chunks = await self._expand_siblings(
            ranked, org_id, repo_url, seen_ids,
        )
        ranked.extend(sibling_chunks)

        return ranked

    async def _hybrid_search(
        self,
        task_description: str,
        org_id: str,
        repo_url: str,
        *,
        agent_role: str | None = None,
        target_files: list[str] | None = None,
    ) -> list[RankedChunk]:
        """Semantic search first, then structural expansion."""
        # Phase 1: Semantic search for entry points
        semantic = await self._semantic_search(
            task_description, org_id, repo_url,
            agent_role=agent_role, top_k=20,
        )

        seen_ids = {rc.chunk["id"] for rc in semantic}

        # Phase 2: Structural expansion from semantic results + explicit targets
        all_ranked = list(semantic)

        # Include explicit target files
        if target_files:
            for fpath in target_files:
                results = await self._store.search_by_name(
                    fpath, org_id=org_id, repo_url=repo_url, limit=20,
                )
                for r in results:
                    if r["id"] not in seen_ids and r["file_path"] == fpath:
                        seen_ids.add(r["id"])
                        all_ranked.append(RankedChunk(
                            chunk=r, score=0.95, tier="direct",
                        ))

        # Phase 3: Dependency expansion
        dep_chunks = await self._expand_dependencies(
            all_ranked, org_id, repo_url, seen_ids,
        )
        all_ranked.extend(dep_chunks)

        # Phase 4: Structural context (parent classes for methods)
        structural = await self._expand_structural(
            all_ranked, org_id, repo_url, seen_ids,
        )
        all_ranked.extend(structural)

        return all_ranked

    # ------------------------------------------------------------------
    # Expansion helpers
    # ------------------------------------------------------------------

    async def _expand_dependencies(
        self,
        chunks: list[RankedChunk],
        org_id: str,
        repo_url: str,
        seen_ids: set[str],
    ) -> list[RankedChunk]:
        """Find imported symbols referenced by the given chunks."""
        dep_chunks: list[RankedChunk] = []
        ref_names: set[str] = set()

        for rc in chunks:
            body = rc.chunk.get("body", "")
            refs = extract_references(body)
            ref_names.update(refs)

        for name in list(ref_names)[:_DEFAULT_STRUCTURAL_K]:
            results = await self._store.search_by_name(
                name, org_id=org_id, repo_url=repo_url, limit=3,
            )
            for r in results:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    dep_chunks.append(RankedChunk(
                        chunk=r, score=0.6, tier="dependency",
                    ))

        return dep_chunks

    async def _expand_siblings(
        self,
        chunks: list[RankedChunk],
        org_id: str,
        repo_url: str,
        seen_ids: set[str],
    ) -> list[RankedChunk]:
        """Find other chunks in the same file or class as direct chunks."""
        sibling_chunks: list[RankedChunk] = []
        searched_files: set[str] = set()

        for rc in chunks[:10]:  # Limit expansion
            if rc.tier != "direct":
                continue
            fpath = rc.chunk.get("file_path", "")
            if fpath in searched_files:
                continue
            searched_files.add(fpath)

            # Get all chunks in the same file
            results = await self._store.search_by_name(
                fpath.split("/")[-1].replace(".", ""),
                org_id=org_id, repo_url=repo_url, limit=20,
            )
            for r in results:
                if r["id"] not in seen_ids and r["file_path"] == fpath:
                    seen_ids.add(r["id"])
                    sibling_chunks.append(RankedChunk(
                        chunk=r, score=0.5, tier="structural",
                    ))

        return sibling_chunks

    async def _expand_structural(
        self,
        chunks: list[RankedChunk],
        org_id: str,
        repo_url: str,
        seen_ids: set[str],
    ) -> list[RankedChunk]:
        """Find parent class definitions for method chunks."""
        structural: list[RankedChunk] = []
        searched_parents: set[str] = set()

        for rc in chunks[:15]:
            parent = rc.chunk.get("parent_name")
            if not parent or parent in searched_parents:
                continue
            searched_parents.add(parent)

            results = await self._store.search_by_name(
                parent, org_id=org_id, repo_url=repo_url, limit=3,
            )
            for r in results:
                if (
                    r["id"] not in seen_ids
                    and r["name"] == parent
                    and r["chunk_type"] in ("class", "struct", "trait", "interface")
                ):
                    seen_ids.add(r["id"])
                    structural.append(RankedChunk(
                        chunk=r, score=0.4, tier="structural",
                    ))

        return structural

    # ------------------------------------------------------------------
    # File tree
    # ------------------------------------------------------------------

    async def _build_file_tree(
        self,
        org_id: str,
        repo_url: str,
        budget_tokens: int,
    ) -> str:
        """Build a compact file tree from the index."""
        # Get all chunks (limited) for tree building
        stats = await self._store.get_repo_stats(org_id=org_id, repo_url=repo_url)
        if stats["total_chunks"] == 0:
            return ""

        # Use a broad name search to get representative chunks
        all_chunks = await self._store.search_by_name(
            "", org_id=org_id, repo_url=repo_url, limit=500,
        )

        tree = build_file_tree(all_chunks)

        # Truncate to budget if needed
        budget_chars = budget_tokens * _CHARS_PER_TOKEN
        if len(tree) > budget_chars:
            tree = tree[:budget_chars].rsplit("\n", 1)[0] + "\n..."

        return tree

    # ------------------------------------------------------------------
    # Budget management
    # ------------------------------------------------------------------

    def _apply_budget(
        self,
        ranked: list[RankedChunk],
        budget_tokens: int,
    ) -> tuple[list[RankedChunk], int]:
        """Select chunks that fit within the token budget.

        Prioritises by tier (direct > dependency > structural > broader),
        then by score within each tier.  Never truncates a chunk — either
        includes it fully or excludes it.

        Returns (selected_chunks, excluded_count).
        """
        tier_order = {"direct": 0, "dependency": 1, "structural": 2, "broader": 3}

        sorted_chunks = sorted(
            ranked,
            key=lambda rc: (tier_order.get(rc.tier, 9), -rc.score),
        )

        selected: list[RankedChunk] = []
        used_tokens = 0
        excluded = 0

        for rc in sorted_chunks:
            cost = rc.token_estimate
            if used_tokens + cost <= budget_tokens:
                selected.append(rc)
                used_tokens += cost
            else:
                excluded += 1

        return selected, excluded

    # ------------------------------------------------------------------
    # Context map
    # ------------------------------------------------------------------

    def _generate_context_map(
        self,
        selected: list[RankedChunk],
        excluded_count: int,
    ) -> str:
        """Generate a ~200-token summary of what's in the context."""
        if not selected:
            return "No codebase context available."

        # Group by file
        files: dict[str, list[str]] = {}
        for rc in selected:
            fpath = rc.chunk.get("file_path", "?")
            name = rc.chunk.get("qualified_name", "?")
            if fpath not in files:
                files[fpath] = []
            files[fpath].append(name)

        # Group by tier
        tier_counts: dict[str, int] = {}
        for rc in selected:
            tier_counts[rc.tier] = tier_counts.get(rc.tier, 0) + 1

        lines = [f"Context includes {len(selected)} code chunks from {len(files)} files:"]

        # Tier breakdown
        tier_parts = []
        for tier in ("direct", "dependency", "structural", "broader"):
            if tier in tier_counts:
                tier_parts.append(f"{tier_counts[tier]} {tier}")
        lines.append("  " + ", ".join(tier_parts))

        # File listing (compact)
        for fpath, names in sorted(files.items())[:10]:
            if len(names) <= 3:
                lines.append(f"  {fpath}: {', '.join(names)}")
            else:
                lines.append(f"  {fpath}: {', '.join(names[:2])} +{len(names)-2} more")

        if len(files) > 10:
            lines.append(f"  ... and {len(files) - 10} more files")

        if excluded_count > 0:
            lines.append(
                f"({excluded_count} additional chunks excluded due to token budget)"
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Role-specific context tuning
# ---------------------------------------------------------------------------


def _role_type_filter(agent_role: str | None) -> set[str] | None:
    """Return chunk types to prioritise for a given agent role, or None."""
    if agent_role is None:
        return None

    filters: dict[str, set[str]] = {
        "architect": {"class", "interface", "struct", "trait", "module", "type_alias"},
        "engineer": {"function", "method", "class"},
        "qa": {"function", "method", "class"},
    }

    return filters.get(agent_role)


def get_agent_context_config(agent_role: str) -> dict[str, Any]:
    """Return default context assembly config for an agent role.

    Different agents need different context shapes:
    - Architect: broad overview, interfaces, high-level structure
    - Engineer: specific functions, dependencies, test patterns
    - QA: functions under test, existing test patterns, error handling
    """
    configs: dict[str, dict[str, Any]] = {
        "architect": {
            "strategy": "semantic",
            "max_tokens": 20_000,
            "file_tree_budget": 1000,
        },
        "engineer": {
            "strategy": "hybrid",
            "max_tokens": 30_000,
            "file_tree_budget": 600,
        },
        "qa": {
            "strategy": "hybrid",
            "max_tokens": 25_000,
            "file_tree_budget": 400,
        },
        "business_analyst": {
            "strategy": "semantic",
            "max_tokens": 10_000,
            "file_tree_budget": 800,
        },
        "researcher": {
            "strategy": "semantic",
            "max_tokens": 10_000,
            "file_tree_budget": 500,
        },
    }

    return configs.get(agent_role, {
        "strategy": "hybrid",
        "max_tokens": 20_000,
        "file_tree_budget": 600,
    })
