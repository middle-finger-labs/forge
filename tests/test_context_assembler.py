"""Tests for the context assembler and file tree modules.

Tests the context assembly pipeline, file tree generation, RRF merging,
structural expansion, and budget management without requiring a database.
"""

from __future__ import annotations

from agents.codebase.context_assembler import (
    AssembledContext,
    RankedChunk,
    _role_type_filter,
    extract_mentioned_files,
    extract_mentioned_symbols,
    extract_references,
    get_agent_context_config,
    reciprocal_rank_fusion,
)
from agents.codebase.file_tree import (
    FileInfo,
    build_file_tree,
    build_file_tree_from_paths,
)

# ---------------------------------------------------------------------------
# File tree tests
# ---------------------------------------------------------------------------


class TestFileInfo:
    def test_basic_fields(self):
        info = FileInfo(path="src/main.py", language="python", chunk_count=3)
        assert info.path == "src/main.py"
        assert info.language == "python"
        assert info.chunk_count == 3
        assert info.description == ""

    def test_with_description(self):
        info = FileInfo(
            path="lib/auth.ts",
            language="typescript",
            description="Authentication middleware.",
        )
        assert "Authentication" in info.description


class TestBuildFileTree:
    def test_empty_chunks(self):
        result = build_file_tree([])
        assert result == "(empty repository)"

    def test_single_file(self):
        chunks = [
            {"file_path": "src/main.py", "language": "python"},
        ]
        tree = build_file_tree(chunks)
        assert "main.py" in tree
        assert "[python]" in tree

    def test_multiple_files_same_dir(self):
        chunks = [
            {"file_path": "src/app.py", "language": "python"},
            {"file_path": "src/utils.py", "language": "python"},
        ]
        tree = build_file_tree(chunks)
        assert "src/" in tree
        assert "app.py" in tree
        assert "utils.py" in tree

    def test_nested_directories(self):
        chunks = [
            {"file_path": "src/api/routes.py", "language": "python"},
            {"file_path": "src/api/models.py", "language": "python"},
            {"file_path": "tests/test_routes.py", "language": "python"},
        ]
        tree = build_file_tree(chunks)
        assert "src/" in tree
        assert "api/" in tree
        assert "tests/" in tree

    def test_description_from_docstring(self):
        chunks = [
            {
                "file_path": "src/auth.py",
                "language": "python",
                "docstring": "JWT authentication utilities.",
            },
        ]
        tree = build_file_tree(chunks)
        assert "JWT authentication" in tree

    def test_language_stats_footer(self):
        chunks = [
            {"file_path": "main.py", "language": "python"},
            {"file_path": "app.ts", "language": "typescript"},
            {"file_path": "lib.rs", "language": "rust"},
        ]
        tree = build_file_tree(chunks)
        assert "3 files" in tree
        assert "python" in tree

    def test_max_depth_collapse(self):
        chunks = [
            {"file_path": f"a/b/c/d/e/f{i}.py", "language": "python"}
            for i in range(5)
        ]
        tree = build_file_tree(chunks, max_depth=2)
        # Deep directories should be collapsed
        assert "files)" in tree

    def test_max_files_truncation(self):
        chunks = [
            {"file_path": f"src/file_{i}.py", "language": "python"}
            for i in range(200)
        ]
        tree = build_file_tree(chunks, max_files=50)
        # Should only show up to max_files
        assert "50 files" in tree


class TestBuildFileTreeFromPaths:
    def test_basic_paths(self):
        paths = ["src/main.py", "src/utils.py", "README.md"]
        tree = build_file_tree_from_paths(paths)
        assert "main.py" in tree
        assert "utils.py" in tree
        assert "README.md" in tree

    def test_deduplicates_paths(self):
        paths = ["src/main.py", "src/main.py", "src/main.py"]
        tree = build_file_tree_from_paths(paths)
        assert tree.count("main.py") == 1


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion tests
# ---------------------------------------------------------------------------


class TestReciprocalRankFusion:
    def test_single_list(self):
        results = [
            {"id": "a", "score": 0.9},
            {"id": "b", "score": 0.8},
        ]
        merged = reciprocal_rank_fusion(results)
        assert len(merged) == 2
        assert merged[0]["id"] == "a"
        assert merged[1]["id"] == "b"

    def test_two_lists_overlap(self):
        list_a = [
            {"id": "x", "score": 0.9},
            {"id": "y", "score": 0.7},
        ]
        list_b = [
            {"id": "y", "score": 0.95},
            {"id": "x", "score": 0.6},
        ]
        merged = reciprocal_rank_fusion(list_a, list_b, k=60)
        # Both items appear in both lists; 'y' is rank 0 in list_b and
        # rank 1 in list_a, 'x' is rank 0 in list_a and rank 1 in list_b.
        # Scores should be identical, so order doesn't strictly matter.
        ids = {r["id"] for r in merged}
        assert ids == {"x", "y"}

    def test_disjoint_lists(self):
        list_a = [{"id": "a", "score": 0.9}]
        list_b = [{"id": "b", "score": 0.8}]
        merged = reciprocal_rank_fusion(list_a, list_b)
        ids = [r["id"] for r in merged]
        assert "a" in ids
        assert "b" in ids

    def test_empty_lists(self):
        merged = reciprocal_rank_fusion([], [])
        assert merged == []

    def test_rrf_score_replaces_original(self):
        results = [{"id": "a", "score": 0.99}]
        merged = reciprocal_rank_fusion(results, k=60)
        # RRF score should be 1/(60+0+1) = 1/61
        assert abs(merged[0]["score"] - 1.0 / 61) < 0.001


# ---------------------------------------------------------------------------
# Reference extraction tests
# ---------------------------------------------------------------------------


class TestExtractReferences:
    def test_python_import(self):
        body = "from utils.validators import validate_email, validate_phone"
        refs = extract_references(body)
        assert "validate_email" in refs
        assert "validate_phone" in refs

    def test_js_import(self):
        body = 'import { Router } from "express"'
        refs = extract_references(body)
        assert "express" in refs

    def test_rust_use(self):
        body = "use std::collections::HashMap"
        refs = extract_references(body)
        assert "HashMap" in refs

    def test_go_import(self):
        body = 'import "fmt"'
        refs = extract_references(body)
        assert "fmt" in refs

    def test_empty_body(self):
        refs = extract_references("")
        assert refs == []


class TestExtractMentionedFiles:
    def test_python_files(self):
        text = "Modify the validation in src/auth/validators.py and update tests/test_auth.py"
        files = extract_mentioned_files(text)
        assert "src/auth/validators.py" in files
        assert "tests/test_auth.py" in files

    def test_typescript_files(self):
        text = "The component in components/UserForm.tsx needs updating"
        files = extract_mentioned_files(text)
        assert "components/UserForm.tsx" in files

    def test_no_files(self):
        text = "Add authentication to the signup endpoint"
        files = extract_mentioned_files(text)
        assert files == []


class TestExtractMentionedSymbols:
    def test_camel_case(self):
        text = "Update the UserProfile class and the AuthService"
        symbols = extract_mentioned_symbols(text)
        assert "UserProfile" in symbols
        assert "AuthService" in symbols

    def test_qualified_names(self):
        text = "Fix the bug in auth.validator.check_token"
        symbols = extract_mentioned_symbols(text)
        assert any("auth" in s for s in symbols)

    def test_filters_stopwords(self):
        text = "The problem is When the function runs"
        symbols = extract_mentioned_symbols(text)
        assert "The" not in symbols
        assert "When" not in symbols


# ---------------------------------------------------------------------------
# RankedChunk tests
# ---------------------------------------------------------------------------


class TestRankedChunk:
    def test_token_estimate(self):
        rc = RankedChunk(
            chunk={"body": "x" * 400},
            score=0.9,
            tier="direct",
        )
        assert rc.token_estimate == 100  # 400 chars / 4 chars per token

    def test_token_estimate_minimum(self):
        rc = RankedChunk(
            chunk={"body": ""},
            score=0.5,
            tier="structural",
        )
        assert rc.token_estimate == 1  # minimum is 1


# ---------------------------------------------------------------------------
# AssembledContext tests
# ---------------------------------------------------------------------------


class TestAssembledContext:
    def test_format_with_all_sections(self):
        chunks = [
            RankedChunk(
                chunk={
                    "file_path": "src/auth.py",
                    "start_line": 10,
                    "chunk_type": "function",
                    "qualified_name": "validate_token",
                    "signature": "def validate_token(token: str) -> bool",
                    "body": "def validate_token(token: str) -> bool:\n    return True",
                },
                score=0.9,
                tier="direct",
            ),
        ]
        ctx = AssembledContext(
            file_tree="src/\n  auth.py",
            chunks=chunks,
            context_map="Context includes 1 code chunks from 1 files",
            total_tokens=500,
            excluded_count=0,
        )
        formatted = ctx.format()
        assert "<file_tree>" in formatted
        assert "<context_map>" in formatted
        assert "<codebase_context>" in formatted
        assert "validate_token" in formatted
        assert "DIRECT CONTEXT" in formatted

    def test_format_empty(self):
        ctx = AssembledContext(
            file_tree="",
            chunks=[],
            context_map="No codebase context available.",
            total_tokens=0,
            excluded_count=0,
        )
        formatted = ctx.format()
        assert "<context_map>" in formatted
        assert "No codebase context" in formatted

    def test_format_tier_grouping(self):
        chunks = [
            RankedChunk(
                chunk={
                    "file_path": "a.py", "start_line": 1,
                    "chunk_type": "function", "qualified_name": "foo",
                    "signature": "", "body": "def foo(): pass",
                },
                score=0.9, tier="direct",
            ),
            RankedChunk(
                chunk={
                    "file_path": "b.py", "start_line": 1,
                    "chunk_type": "function", "qualified_name": "bar",
                    "signature": "", "body": "def bar(): pass",
                },
                score=0.5, tier="dependency",
            ),
        ]
        ctx = AssembledContext(
            file_tree="", chunks=chunks, context_map="",
            total_tokens=100, excluded_count=0,
        )
        formatted = ctx.format()
        assert "DIRECT CONTEXT" in formatted
        assert "DEPENDENCY CONTEXT" in formatted


# ---------------------------------------------------------------------------
# Role-specific config tests
# ---------------------------------------------------------------------------


class TestRoleTypeFilter:
    def test_architect_filter(self):
        f = _role_type_filter("architect")
        assert "class" in f
        assert "interface" in f
        assert "function" not in f

    def test_engineer_filter(self):
        f = _role_type_filter("engineer")
        assert "function" in f
        assert "method" in f
        assert "class" in f

    def test_qa_filter(self):
        f = _role_type_filter("qa")
        assert "function" in f
        assert "method" in f

    def test_unknown_role(self):
        assert _role_type_filter("unknown") is None

    def test_none_role(self):
        assert _role_type_filter(None) is None


class TestGetAgentContextConfig:
    def test_architect_config(self):
        cfg = get_agent_context_config("architect")
        assert cfg["strategy"] == "semantic"
        assert cfg["max_tokens"] == 20_000
        assert cfg["file_tree_budget"] == 1000

    def test_engineer_config(self):
        cfg = get_agent_context_config("engineer")
        assert cfg["strategy"] == "hybrid"
        assert cfg["max_tokens"] == 30_000

    def test_qa_config(self):
        cfg = get_agent_context_config("qa")
        assert cfg["strategy"] == "hybrid"

    def test_unknown_role_gets_defaults(self):
        cfg = get_agent_context_config("some_unknown_role")
        assert "strategy" in cfg
        assert "max_tokens" in cfg

    def test_business_analyst_config(self):
        cfg = get_agent_context_config("business_analyst")
        assert cfg["strategy"] == "semantic"
        assert cfg["max_tokens"] == 10_000


# ---------------------------------------------------------------------------
# Budget management tests
# ---------------------------------------------------------------------------


class TestApplyBudget:
    """Test the _apply_budget method via a minimal ContextAssembler."""

    def _make_assembler(self):
        """Create a ContextAssembler with mock store/embedder (budget
        management doesn't need them)."""
        from agents.codebase.context_assembler import ContextAssembler

        return ContextAssembler(store=None, embedder=None)  # type: ignore[arg-type]

    def test_all_fit(self):
        assembler = self._make_assembler()
        chunks = [
            RankedChunk(
                chunk={"body": "x" * 100},
                score=0.9, tier="direct",
            ),
            RankedChunk(
                chunk={"body": "y" * 100},
                score=0.8, tier="dependency",
            ),
        ]
        selected, excluded = assembler._apply_budget(chunks, budget_tokens=1000)
        assert len(selected) == 2
        assert excluded == 0

    def test_budget_exceeded(self):
        assembler = self._make_assembler()
        chunks = [
            RankedChunk(
                chunk={"body": "x" * 400},  # 100 tokens
                score=0.9, tier="direct",
            ),
            RankedChunk(
                chunk={"body": "y" * 400},  # 100 tokens
                score=0.8, tier="dependency",
            ),
        ]
        selected, excluded = assembler._apply_budget(chunks, budget_tokens=120)
        assert len(selected) == 1
        assert excluded == 1
        assert selected[0].tier == "direct"  # direct has higher priority

    def test_tier_priority(self):
        assembler = self._make_assembler()
        chunks = [
            RankedChunk(
                chunk={"body": "x" * 400},
                score=0.5, tier="structural",  # lower priority
            ),
            RankedChunk(
                chunk={"body": "y" * 400},
                score=0.9, tier="direct",  # higher priority
            ),
        ]
        selected, excluded = assembler._apply_budget(chunks, budget_tokens=120)
        assert len(selected) == 1
        assert selected[0].tier == "direct"  # direct chosen over structural

    def test_zero_budget(self):
        assembler = self._make_assembler()
        chunks = [
            RankedChunk(
                chunk={"body": "x" * 100},
                score=0.9, tier="direct",
            ),
        ]
        selected, excluded = assembler._apply_budget(chunks, budget_tokens=0)
        assert len(selected) == 0
        assert excluded == 1


# ---------------------------------------------------------------------------
# Context map generation tests
# ---------------------------------------------------------------------------


class TestGenerateContextMap:
    def _make_assembler(self):
        from agents.codebase.context_assembler import ContextAssembler

        return ContextAssembler(store=None, embedder=None)  # type: ignore[arg-type]

    def test_empty_chunks(self):
        assembler = self._make_assembler()
        result = assembler._generate_context_map([], 0)
        assert "No codebase context" in result

    def test_with_chunks(self):
        assembler = self._make_assembler()
        chunks = [
            RankedChunk(
                chunk={
                    "file_path": "src/auth.py",
                    "qualified_name": "validate_token",
                    "body": "...",
                },
                score=0.9, tier="direct",
            ),
            RankedChunk(
                chunk={
                    "file_path": "src/auth.py",
                    "qualified_name": "check_permissions",
                    "body": "...",
                },
                score=0.7, tier="dependency",
            ),
        ]
        result = assembler._generate_context_map(chunks, excluded_count=3)
        assert "2 code chunks" in result
        assert "1 files" in result
        assert "direct" in result
        assert "dependency" in result
        assert "3 additional chunks excluded" in result

    def test_many_files_truncated(self):
        assembler = self._make_assembler()
        chunks = [
            RankedChunk(
                chunk={
                    "file_path": f"src/file_{i}.py",
                    "qualified_name": f"func_{i}",
                    "body": "...",
                },
                score=0.5, tier="direct",
            )
            for i in range(15)
        ]
        result = assembler._generate_context_map(chunks, excluded_count=0)
        assert "and 5 more files" in result
