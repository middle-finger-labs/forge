"""Dual embedding generator for code chunks.

Produces two embedding vectors per chunk:
1. **Code embedding** — the raw source code, capturing syntactic patterns
2. **Description embedding** — a natural-language summary synthesised from
   the chunk's metadata (type, name, language, signature, docstring)

Both use the same sentence-transformers model as the rest of Forge
(``multi-qa-MiniLM-L6-cos-v1``, 384 dimensions) so they share the same
vector space and can be compared with cosine similarity.

The description embedding lets agents search with natural-language queries
("function that validates email addresses") while the code embedding
supports code-to-code similarity ("find functions like this one").
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from agents.codebase.indexer import CodeChunk

log = structlog.get_logger().bind(component="chunk_embedder")

# Same model used by Forge's semantic memory
_EMBEDDING_MODEL = "multi-qa-MiniLM-L6-cos-v1"
_EMBEDDING_DIMS = 384

# Truncate code/description input to avoid blowing up the model
_MAX_CODE_CHARS = 8_000
_MAX_DESC_CHARS = 2_000


# ---------------------------------------------------------------------------
# EmbeddedChunk — chunk + its two embedding vectors
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EmbeddedChunk:
    """A CodeChunk annotated with dual embedding vectors."""

    chunk: CodeChunk
    code_embedding: list[float]
    description_embedding: list[float]


# ---------------------------------------------------------------------------
# Description synthesis
# ---------------------------------------------------------------------------


def describe_chunk(chunk: CodeChunk) -> str:
    """Generate a natural-language description from chunk metadata.

    This description is what gets embedded for NL search queries.  It should
    be readable, concise, and capture the chunk's *purpose* rather than its
    implementation details.
    """
    parts: list[str] = []

    # Type + language
    lang_nice = {
        "python": "Python",
        "typescript": "TypeScript",
        "tsx": "TypeScript (TSX)",
        "javascript": "JavaScript",
        "rust": "Rust",
        "go": "Go",
        "java": "Java",
    }.get(chunk.language, chunk.language)

    type_label = {
        "function": "function",
        "method": "method",
        "class": "class",
        "struct": "struct",
        "enum": "enum",
        "trait": "trait",
        "interface": "interface",
        "type_alias": "type alias",
        "module": "module",
    }.get(chunk.chunk_type, chunk.chunk_type)

    parts.append(f"{lang_nice} {type_label} '{chunk.name}'")

    # Parent context
    if chunk.parent_name:
        parts.append(f"in {chunk.parent_name}")

    # File path for context
    parts.append(f"from {chunk.file_path}")

    # Signature
    if chunk.signature:
        parts.append(f"with signature: {chunk.signature}")

    # Docstring (most valuable for NL search)
    if chunk.docstring:
        # Truncate long docstrings
        doc = chunk.docstring[:500]
        parts.append(f"— {doc}")

    # Decorators / metadata
    decorators = chunk.metadata.get("decorators", [])
    if decorators:
        parts.append(f"decorated with {', '.join(decorators[:5])}")

    exported = chunk.metadata.get("exported")
    if exported is True:
        parts.append("(exported)")

    public = chunk.metadata.get("public")
    if public is True:
        parts.append("(pub)")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# ChunkEmbedder
# ---------------------------------------------------------------------------


class ChunkEmbedder:
    """Generates dual embeddings for code chunks.

    Lazily loads the sentence-transformers model on first use.

    Usage::

        embedder = ChunkEmbedder()
        embedded = await embedder.embed_chunks(chunks)
        # or embed a single chunk:
        embedded = await embedder.embed_chunk(chunk)
    """

    def __init__(self, model_name: str = _EMBEDDING_MODEL) -> None:
        self._model_name = model_name
        self._model = None

    def _ensure_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            log.info("embedding model loaded", model=self._model_name)
        except ImportError:
            raise RuntimeError(
                "sentence-transformers is required for code embeddings. "
                "Install it with: pip install sentence-transformers"
            )
        return self._model

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts and return their vectors."""
        model = self._ensure_model()
        # sentence-transformers .encode() returns numpy array
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return [vec.tolist() for vec in embeddings]

    async def embed_chunk(self, chunk: CodeChunk) -> EmbeddedChunk:
        """Embed a single code chunk (code + description)."""
        results = await self.embed_chunks([chunk])
        return results[0]

    async def embed_chunks(
        self,
        chunks: list[CodeChunk],
        batch_size: int = 64,
    ) -> list[EmbeddedChunk]:
        """Embed a list of code chunks in batches.

        For each chunk, produces two embeddings:
        1. Code embedding — from the raw source
        2. Description embedding — from a synthesised NL description

        Uses asyncio.to_thread to avoid blocking the event loop during
        the CPU-intensive embedding computation.
        """
        if not chunks:
            return []

        import asyncio

        # Prepare texts
        code_texts = [c.body[:_MAX_CODE_CHARS] for c in chunks]
        desc_texts = [describe_chunk(c)[:_MAX_DESC_CHARS] for c in chunks]

        # Run embedding in a thread pool to avoid blocking the event loop
        all_texts = code_texts + desc_texts

        embedded_vecs: list[list[float]] = []
        for i in range(0, len(all_texts), batch_size):
            batch = all_texts[i : i + batch_size]
            batch_vecs = await asyncio.to_thread(self._embed_texts, batch)
            embedded_vecs.extend(batch_vecs)

        n = len(chunks)
        code_vecs = embedded_vecs[:n]
        desc_vecs = embedded_vecs[n:]

        results = []
        for chunk, code_vec, desc_vec in zip(chunks, code_vecs, desc_vecs):
            results.append(EmbeddedChunk(
                chunk=chunk,
                code_embedding=code_vec,
                description_embedding=desc_vec,
            ))

        log.info("chunks embedded", count=len(results))
        return results

    @property
    def dims(self) -> int:
        """Return the embedding dimensionality."""
        return _EMBEDDING_DIMS
