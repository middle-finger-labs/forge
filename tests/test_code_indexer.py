"""Tests for the AST-based code indexing pipeline.

Tests the indexer's AST extraction logic without requiring tree-sitter
grammar packages (uses mock parsers) and without a database.
"""

from __future__ import annotations

import textwrap

import pytest

from agents.codebase.embedder import describe_chunk
from agents.codebase.indexer import (
    CodeChunk,
    RepoIndexer,
    _extract_chunks_from_tree,
    _get_parser,
)

# ---------------------------------------------------------------------------
# CodeChunk dataclass tests
# ---------------------------------------------------------------------------


class TestCodeChunk:
    def test_basic_fields(self):
        chunk = CodeChunk(
            file_path="src/main.py",
            language="python",
            chunk_type="function",
            name="hello",
            qualified_name="hello",
            body="def hello(): pass",
            start_line=1,
            end_line=1,
        )
        assert chunk.file_path == "src/main.py"
        assert chunk.language == "python"
        assert chunk.chunk_type == "function"
        assert chunk.name == "hello"
        assert chunk.qualified_name == "hello"
        assert chunk.signature == ""
        assert chunk.docstring == ""
        assert chunk.parent_name is None
        assert chunk.metadata == {}

    def test_method_with_parent(self):
        chunk = CodeChunk(
            file_path="src/app.py",
            language="python",
            chunk_type="method",
            name="run",
            qualified_name="App.run",
            body="def run(self): ...",
            start_line=10,
            end_line=15,
            signature="def run(self)",
            docstring="Run the application.",
            parent_name="App",
            metadata={"decorators": ["@staticmethod"]},
        )
        assert chunk.parent_name == "App"
        assert chunk.qualified_name == "App.run"
        assert chunk.metadata["decorators"] == ["@staticmethod"]


# ---------------------------------------------------------------------------
# Description synthesis tests
# ---------------------------------------------------------------------------


class TestDescribeChunk:
    def test_basic_function(self):
        chunk = CodeChunk(
            file_path="src/utils.py",
            language="python",
            chunk_type="function",
            name="validate_email",
            qualified_name="validate_email",
            body="def validate_email(email: str) -> bool: ...",
            start_line=1,
            end_line=5,
            signature="def validate_email(email: str) -> bool",
            docstring="Check whether an email address is valid.",
        )
        desc = describe_chunk(chunk)
        assert "Python" in desc
        assert "function" in desc
        assert "'validate_email'" in desc
        assert "validate_email(email: str) -> bool" in desc
        assert "Check whether an email address is valid" in desc

    def test_method_with_parent(self):
        chunk = CodeChunk(
            file_path="src/server.rs",
            language="rust",
            chunk_type="method",
            name="handle_request",
            qualified_name="Server::handle_request",
            body="fn handle_request(&self) {}",
            start_line=20,
            end_line=30,
            parent_name="Server",
            metadata={"public": True},
        )
        desc = describe_chunk(chunk)
        assert "Rust" in desc
        assert "method" in desc
        assert "Server" in desc
        assert "(pub)" in desc

    def test_interface_description(self):
        chunk = CodeChunk(
            file_path="src/types.ts",
            language="typescript",
            chunk_type="interface",
            name="UserProfile",
            qualified_name="UserProfile",
            body="interface UserProfile { name: string; }",
            start_line=1,
            end_line=3,
            signature="interface UserProfile",
        )
        desc = describe_chunk(chunk)
        assert "TypeScript" in desc
        assert "interface" in desc
        assert "'UserProfile'" in desc

    def test_go_exported(self):
        chunk = CodeChunk(
            file_path="main.go",
            language="go",
            chunk_type="function",
            name="HandleRequest",
            qualified_name="HandleRequest",
            body="func HandleRequest() {}",
            start_line=1,
            end_line=3,
            metadata={"exported": True},
        )
        desc = describe_chunk(chunk)
        assert "Go" in desc
        assert "(exported)" in desc


# ---------------------------------------------------------------------------
# Tree-sitter parsing tests (require grammar packages)
# ---------------------------------------------------------------------------


@pytest.fixture
def has_python_grammar():
    """Skip if tree-sitter-python is not installed."""
    parser = _get_parser("python")
    if parser is None:
        pytest.skip("tree-sitter-python not installed")
    return parser


class TestPythonExtraction:
    def test_function(self, has_python_grammar):
        source = textwrap.dedent('''\
            def greet(name: str) -> str:
                """Say hello."""
                return f"Hello, {name}"
        ''')
        parser = has_python_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "app.py", "python")

        assert len(chunks) >= 1
        fn = next(c for c in chunks if c.chunk_type == "function")
        assert fn.name == "greet"
        assert fn.qualified_name == "greet"
        assert "greet" in fn.signature
        assert fn.start_line == 1
        assert fn.file_path == "app.py"

    def test_class_with_methods(self, has_python_grammar):
        source = textwrap.dedent('''\
            class Calculator:
                """A simple calculator."""

                def add(self, a, b):
                    return a + b

                def subtract(self, a, b):
                    return a - b
        ''')
        parser = has_python_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "calc.py", "python")

        names = {c.qualified_name for c in chunks}
        assert "Calculator" in names
        assert "Calculator.add" in names
        assert "Calculator.subtract" in names

        cls = next(c for c in chunks if c.chunk_type == "class")
        assert cls.name == "Calculator"

        add_method = next(c for c in chunks if c.name == "add")
        assert add_method.chunk_type == "method"
        assert add_method.parent_name == "Calculator"

    def test_decorated_function(self, has_python_grammar):
        source = textwrap.dedent('''\
            @app.route("/health")
            def health_check():
                return {"status": "ok"}
        ''')
        parser = has_python_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "api.py", "python")

        assert len(chunks) >= 1
        fn = chunks[0]
        assert fn.name == "health_check"


@pytest.fixture
def has_typescript_grammar():
    parser = _get_parser("typescript")
    if parser is None:
        pytest.skip("tree-sitter-typescript not installed")
    return parser


class TestTypescriptExtraction:
    def test_function_declaration(self, has_typescript_grammar):
        source = 'function greet(name: string): string { return "hi"; }\n'
        parser = has_typescript_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(
            tree, source.encode(), "app.ts", "typescript",
        )

        assert len(chunks) >= 1
        fn = chunks[0]
        assert fn.name == "greet"
        assert fn.chunk_type == "function"

    def test_interface(self, has_typescript_grammar):
        source = "interface User { name: string; age: number; }\n"
        parser = has_typescript_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(
            tree, source.encode(), "types.ts", "typescript",
        )

        assert len(chunks) >= 1
        iface = next(c for c in chunks if c.chunk_type == "interface")
        assert iface.name == "User"


@pytest.fixture
def has_rust_grammar():
    parser = _get_parser("rust")
    if parser is None:
        pytest.skip("tree-sitter-rust not installed")
    return parser


class TestRustExtraction:
    def test_function(self, has_rust_grammar):
        source = "fn main() { println!(\"hello\"); }\n"
        parser = has_rust_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(
            tree, source.encode(), "main.rs", "rust",
        )

        assert len(chunks) >= 1
        fn = chunks[0]
        assert fn.name == "main"
        assert fn.language == "rust"

    def test_struct_and_impl(self, has_rust_grammar):
        source = textwrap.dedent("""\
            struct Point { x: f64, y: f64 }

            impl Point {
                fn new(x: f64, y: f64) -> Self {
                    Point { x, y }
                }
            }
        """)
        parser = has_rust_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(
            tree, source.encode(), "point.rs", "rust",
        )

        names = {c.qualified_name for c in chunks}
        assert "Point" in names
        assert "Point::new" in names

        method = next(c for c in chunks if c.name == "new")
        assert method.parent_name == "Point"
        assert method.chunk_type == "method"


# ---------------------------------------------------------------------------
# RepoIndexer unit tests
# ---------------------------------------------------------------------------


class TestRepoIndexer:
    def test_init(self, tmp_path):
        indexer = RepoIndexer(tmp_path)
        assert indexer.repo_path == tmp_path

    @pytest.mark.asyncio
    async def test_get_head_sha(self, tmp_path):
        """Test against a real tiny git repo."""
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            env={**__import__("os").environ, "GIT_AUTHOR_NAME": "Test",
                 "GIT_AUTHOR_EMAIL": "t@t.com", "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "t@t.com"},
        )

        indexer = RepoIndexer(tmp_path)
        sha = await indexer.get_head_sha()
        assert len(sha) == 40
        assert sha.isalnum()

    @pytest.mark.asyncio
    async def test_list_files(self, tmp_path):
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "main.py").write_text("print('hi')")
        (tmp_path / "utils.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            env={**__import__("os").environ, "GIT_AUTHOR_NAME": "Test",
                 "GIT_AUTHOR_EMAIL": "t@t.com", "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "t@t.com"},
        )

        indexer = RepoIndexer(tmp_path)
        files = await indexer.list_files()
        assert "main.py" in files
        assert "utils.py" in files


# ---------------------------------------------------------------------------
# Go extraction tests (require tree-sitter-go grammar)
# ---------------------------------------------------------------------------


@pytest.fixture
def has_go_grammar():
    parser = _get_parser("go")
    if parser is None:
        pytest.skip("tree-sitter-go not installed")
    return parser


class TestGoExtraction:
    def test_function(self, has_go_grammar):
        source = textwrap.dedent("""\
            package main

            func Add(a int, b int) int {
                return a + b
            }
        """)
        parser = has_go_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "math.go", "go")

        fns = [c for c in chunks if c.chunk_type == "function"]
        assert len(fns) >= 1
        fn = fns[0]
        assert fn.name == "Add"
        assert fn.language == "go"
        assert fn.metadata.get("exported") is True

    def test_unexported_function(self, has_go_grammar):
        source = textwrap.dedent("""\
            package main

            func helper() {
                // private
            }
        """)
        parser = has_go_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "util.go", "go")

        fn = next(c for c in chunks if c.chunk_type == "function")
        assert fn.name == "helper"
        assert fn.metadata.get("exported") is False

    def test_method_with_receiver(self, has_go_grammar):
        source = textwrap.dedent("""\
            package main

            type Server struct {
                Port int
            }

            func (s *Server) Start() error {
                return nil
            }
        """)
        parser = has_go_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "server.go", "go")

        names = {c.qualified_name for c in chunks}
        assert "Server" in names
        assert "Server.Start" in names

        method = next(c for c in chunks if c.name == "Start")
        assert method.chunk_type == "method"
        assert method.parent_name == "Server"
        assert method.metadata.get("exported") is True

    def test_struct_type(self, has_go_grammar):
        source = textwrap.dedent("""\
            package main

            type Config struct {
                Host string
                Port int
            }
        """)
        parser = has_go_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "config.go", "go")

        structs = [c for c in chunks if c.chunk_type == "struct"]
        assert len(structs) == 1
        assert structs[0].name == "Config"

    def test_interface_type(self, has_go_grammar):
        source = textwrap.dedent("""\
            package main

            type Handler interface {
                ServeHTTP(w ResponseWriter, r *Request)
            }
        """)
        parser = has_go_grammar
        tree = parser.parse(source.encode())
        chunks = _extract_chunks_from_tree(tree, source.encode(), "handler.go", "go")

        ifaces = [c for c in chunks if c.chunk_type == "interface"]
        assert len(ifaces) == 1
        assert ifaces[0].name == "Handler"


# ---------------------------------------------------------------------------
# Incremental indexing tests
# ---------------------------------------------------------------------------

_GIT_ENV = {
    **__import__("os").environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "t@t.com",
}


def _git(tmp_path, *args):
    """Run a git command in the given repo."""
    import subprocess
    return subprocess.run(
        ["git", *args],
        cwd=tmp_path,
        capture_output=True,
        env=_GIT_ENV,
    )


class TestIncrementalIndexing:
    @pytest.mark.asyncio
    async def test_add_file(self, tmp_path):
        """Adding a new file shows up in changed files."""
        _git(tmp_path, "init")
        (tmp_path / "initial.py").write_text("x = 1\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "init")

        indexer = RepoIndexer(tmp_path)
        sha1 = await indexer.get_head_sha()

        # Add a new file
        (tmp_path / "added.py").write_text("def new_func(): pass\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "add file")
        sha2 = await indexer.get_head_sha()

        changed = await indexer.list_changed_files(sha1, sha2)
        assert "added.py" in changed
        assert "initial.py" not in changed

    @pytest.mark.asyncio
    async def test_modify_file(self, tmp_path):
        """Modifying an existing file shows it in changed files."""
        _git(tmp_path, "init")
        (tmp_path / "module.py").write_text("x = 1\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "init")

        indexer = RepoIndexer(tmp_path)
        sha1 = await indexer.get_head_sha()

        # Modify the file
        (tmp_path / "module.py").write_text("x = 2\ny = 3\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "modify")
        sha2 = await indexer.get_head_sha()

        changed = await indexer.list_changed_files(sha1, sha2)
        assert "module.py" in changed

    @pytest.mark.asyncio
    async def test_delete_file(self, tmp_path):
        """Deleting a file shows it in changed files."""
        _git(tmp_path, "init")
        (tmp_path / "temp.py").write_text("# temporary\n")
        (tmp_path / "keep.py").write_text("# keep\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "init")

        indexer = RepoIndexer(tmp_path)
        sha1 = await indexer.get_head_sha()

        # Delete a file
        (tmp_path / "temp.py").unlink()
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "delete")
        sha2 = await indexer.get_head_sha()

        changed = await indexer.list_changed_files(sha1, sha2)
        assert "temp.py" in changed
        assert "keep.py" not in changed

    @pytest.mark.asyncio
    async def test_index_incremental_returns_chunks_and_paths(self, tmp_path, has_python_grammar):
        """index_incremental returns new chunks and the list of changed paths."""
        _git(tmp_path, "init")
        (tmp_path / "old.py").write_text("def old(): pass\n")
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "init")

        indexer = RepoIndexer(tmp_path)
        sha1 = await indexer.get_head_sha()

        # Add a new Python file with a function
        (tmp_path / "new_module.py").write_text(textwrap.dedent("""\
            def compute(x, y):
                return x + y
        """))
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-m", "add module")
        sha2 = await indexer.get_head_sha()

        chunks, changed_paths = await indexer.index_incremental(sha1, sha2)

        assert "new_module.py" in changed_paths
        assert "old.py" not in changed_paths
        assert any(c.name == "compute" for c in chunks)


# ---------------------------------------------------------------------------
# Embedding generation tests (mock sentence-transformers)
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch, AsyncMock
import numpy as np

from agents.codebase.embedder import ChunkEmbedder, EmbeddedChunk


def _make_chunk(name="test_func", language="python", chunk_type="function"):
    """Helper to create a test CodeChunk."""
    return CodeChunk(
        file_path=f"src/{name}.py",
        language=language,
        chunk_type=chunk_type,
        name=name,
        qualified_name=name,
        body=f"def {name}(): pass",
        start_line=1,
        end_line=1,
    )


def _mock_sentence_transformer():
    """Return a mock SentenceTransformer that produces 384-dim vectors."""
    model = MagicMock()

    def fake_encode(texts, **kwargs):
        # Return a numpy array of shape (len(texts), 384)
        return np.random.rand(len(texts), 384).astype(np.float32)

    model.encode = MagicMock(side_effect=fake_encode)
    return model


class TestChunkEmbedder:
    @pytest.mark.asyncio
    async def test_embed_single_chunk(self):
        """embed_chunk returns an EmbeddedChunk with both vectors."""
        mock_model = _mock_sentence_transformer()
        embedder = ChunkEmbedder()
        embedder._model = mock_model

        chunk = _make_chunk("greet")
        result = await embedder.embed_chunk(chunk)

        assert isinstance(result, EmbeddedChunk)
        assert result.chunk is chunk
        assert len(result.code_embedding) == 384
        assert len(result.description_embedding) == 384

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        """embed_chunks processes multiple chunks correctly."""
        mock_model = _mock_sentence_transformer()
        embedder = ChunkEmbedder()
        embedder._model = mock_model

        chunks = [_make_chunk(f"func_{i}") for i in range(5)]
        results = await embedder.embed_chunks(chunks)

        assert len(results) == 5
        for i, r in enumerate(results):
            assert r.chunk is chunks[i]
            assert len(r.code_embedding) == 384
            assert len(r.description_embedding) == 384

        # model.encode should have been called with 10 texts (5 code + 5 desc)
        call_args = mock_model.encode.call_args_list
        total_texts = sum(len(args[0][0]) for args in call_args)
        assert total_texts == 10

    @pytest.mark.asyncio
    async def test_embed_empty_list(self):
        """embed_chunks with empty list returns empty."""
        embedder = ChunkEmbedder()
        results = await embedder.embed_chunks([])
        assert results == []

    def test_dims_property(self):
        """dims returns 384 for the default model."""
        embedder = ChunkEmbedder()
        assert embedder.dims == 384

    @pytest.mark.asyncio
    async def test_code_and_description_embeddings_differ(self):
        """Code and description embeddings should be generated from different texts."""
        mock_model = _mock_sentence_transformer()
        encoded_texts: list[list[str]] = []

        def tracking_encode(texts, **kwargs):
            encoded_texts.append(list(texts))
            return np.random.rand(len(texts), 384).astype(np.float32)

        mock_model.encode = MagicMock(side_effect=tracking_encode)
        embedder = ChunkEmbedder()
        embedder._model = mock_model

        chunk = _make_chunk("validate_email")
        await embedder.embed_chunk(chunk)

        # Flatten all encoded texts
        all_texts = [t for batch in encoded_texts for t in batch]
        # Should have 2 texts: code body + NL description
        assert len(all_texts) == 2
        # The code text is the body, the description is an NL string
        assert "def validate_email" in all_texts[0]
        assert "Python" in all_texts[1]  # describe_chunk includes language

    @pytest.mark.asyncio
    async def test_batch_processing_respects_batch_size(self):
        """Large batches are split according to batch_size."""
        mock_model = _mock_sentence_transformer()
        call_counts: list[int] = []

        def counting_encode(texts, **kwargs):
            call_counts.append(len(texts))
            return np.random.rand(len(texts), 384).astype(np.float32)

        mock_model.encode = MagicMock(side_effect=counting_encode)
        embedder = ChunkEmbedder()
        embedder._model = mock_model

        # 10 chunks = 20 texts; with batch_size=8, should make 3 batches
        chunks = [_make_chunk(f"fn_{i}") for i in range(10)]
        await embedder.embed_chunks(chunks, batch_size=8)

        assert len(call_counts) == 3  # 8 + 8 + 4
        assert sum(call_counts) == 20
