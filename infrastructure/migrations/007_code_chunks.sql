-- Code chunks: AST-parsed code fragments with dual embeddings for semantic search
-- Supports incremental re-indexing via commit SHA tracking

CREATE TABLE code_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    repo_url        TEXT NOT NULL,              -- e.g. "https://github.com/org/repo"
    commit_sha      TEXT NOT NULL,              -- HEAD at time of indexing
    file_path       TEXT NOT NULL,
    language        TEXT NOT NULL,              -- tree-sitter language name
    chunk_type      TEXT NOT NULL,              -- function, class, method, module, interface
    name            TEXT NOT NULL,              -- symbol name (or filename for module chunks)
    qualified_name  TEXT NOT NULL,              -- e.g. "MyClass.my_method"
    signature       TEXT NOT NULL DEFAULT '',   -- function/method signature
    docstring       TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL,              -- full source text of the chunk
    start_line      INT NOT NULL,
    end_line        INT NOT NULL,
    parent_name     TEXT,                       -- enclosing class/module name
    metadata        JSONB NOT NULL DEFAULT '{}', -- language-specific extras (decorators, visibility, etc.)
    code_embedding      vector(384),            -- embedding of the raw code
    description_embedding vector(384),          -- embedding of NL description
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unique constraint: one chunk per (repo, file, qualified_name, chunk_type)
-- Allows upsert on re-index
CREATE UNIQUE INDEX idx_code_chunks_identity
    ON code_chunks (org_id, repo_url, file_path, qualified_name, chunk_type);

-- Org + repo scoping (most queries filter by these)
CREATE INDEX idx_code_chunks_org_repo ON code_chunks (org_id, repo_url);

-- File-level lookups (for incremental re-indexing: delete all chunks for changed files)
CREATE INDEX idx_code_chunks_file ON code_chunks (org_id, repo_url, file_path);

-- Language filtering
CREATE INDEX idx_code_chunks_language ON code_chunks (language);

-- Vector similarity indexes (HNSW for fast approximate nearest neighbour)
CREATE INDEX idx_code_chunks_code_embedding ON code_chunks
    USING hnsw (code_embedding vector_cosine_ops);

CREATE INDEX idx_code_chunks_desc_embedding ON code_chunks
    USING hnsw (description_embedding vector_cosine_ops);

-- Track last indexed commit per repo (avoids re-scanning unchanged repos)
CREATE TABLE code_index_state (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      TEXT NOT NULL,
    repo_url    TEXT NOT NULL,
    last_commit TEXT NOT NULL,
    file_count  INT NOT NULL DEFAULT 0,
    chunk_count INT NOT NULL DEFAULT 0,
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, repo_url)
);
