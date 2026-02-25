import { useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Search,
  File,
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  ExternalLink,
  GitBranch,
  Loader2,
  X,
} from "lucide-react";
import { useRepoStore } from "@/stores/repoStore";
import type { FileNode, RepoSearchResult } from "@/types/repository";
import { MOCK_FILE_TREE } from "@/data/mockData";
import { cn } from "@/lib/utils";

// ─── Language colors ────────────────────────────────────

const LANG_COLORS: Record<string, string> = {
  TypeScript: "text-blue-400",
  JavaScript: "text-yellow-400",
  Rust: "text-orange-400",
  Python: "text-green-400",
  SQL: "text-purple-400",
  CSS: "text-pink-400",
  JSON: "text-gray-400",
  YAML: "text-red-400",
};

// ─── Tabs ───────────────────────────────────────────────

type ExplorerTab = "tree" | "search" | "deps";

// ─── CodebaseExplorer ───────────────────────────────────

export function CodebaseExplorer() {
  const { repos, activeRepoId, searchResults, searchQuery, setSearchResults, clearSearch } =
    useRepoStore();
  const [activeTab, setActiveTab] = useState<ExplorerTab>("tree");
  const [localSearchQuery, setLocalSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const repo = activeRepoId ? repos[activeRepoId] : undefined;

  if (!repo) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-4">
        <GitBranch className="w-8 h-8 text-[var(--forge-text-muted)] mb-3" />
        <p className="text-sm text-[var(--forge-text-muted)]">
          Select a repo from the sidebar to explore its codebase
        </p>
      </div>
    );
  }

  const fileTree = MOCK_FILE_TREE[repo.id] ?? [];

  const handleSearch = useCallback(async () => {
    if (!localSearchQuery.trim() || !activeRepoId) return;
    setSearching(true);
    // Simulate search - in production this calls the API
    await new Promise((r) => setTimeout(r, 500));
    const mockResults: RepoSearchResult[] = [
      {
        chunk: {
          id: "chunk-1",
          repoId: activeRepoId,
          filePath: "src/routes/auth.ts",
          startLine: 12,
          endLine: 45,
          content: `export async function handleLogin(req: Request, res: Response) {\n  const { email, password } = req.body;\n  const user = await User.findByEmail(email);\n  if (!user || !await user.verifyPassword(password)) {\n    return res.status(401).json({ error: "Invalid credentials" });\n  }\n  const token = generateJWT(user);\n  return res.json({ token, user: user.toPublic() });\n}`,
          language: "TypeScript",
          summary: "Login handler - validates credentials and returns JWT",
          symbols: ["handleLogin"],
        },
        score: 0.95,
      },
      {
        chunk: {
          id: "chunk-2",
          repoId: activeRepoId,
          filePath: "src/middleware/auth.ts",
          startLine: 1,
          endLine: 28,
          content: `import { verify } from "jsonwebtoken";\nimport { config } from "../config";\n\nexport function requireAuth(req: Request, res: Response, next: NextFunction) {\n  const header = req.headers.authorization;\n  if (!header?.startsWith("Bearer ")) {\n    return res.status(401).json({ error: "Missing token" });\n  }\n  try {\n    const payload = verify(header.slice(7), config.jwtSecret);\n    req.user = payload;\n    next();\n  } catch {\n    return res.status(401).json({ error: "Invalid token" });\n  }\n}`,
          language: "TypeScript",
          summary: "Auth middleware - verifies JWT tokens on protected routes",
          symbols: ["requireAuth"],
        },
        score: 0.88,
      },
      {
        chunk: {
          id: "chunk-3",
          repoId: activeRepoId,
          filePath: "src/models/User.ts",
          startLine: 35,
          endLine: 52,
          content: `async verifyPassword(plain: string): Promise<boolean> {\n  return bcrypt.compare(plain, this.passwordHash);\n}\n\nstatic async findByEmail(email: string): Promise<User | null> {\n  const row = await db.query("SELECT * FROM users WHERE email = $1", [email]);\n  return row ? new User(row) : null;\n}`,
          language: "TypeScript",
          summary: "User model - password verification and email lookup",
          symbols: ["verifyPassword", "findByEmail"],
        },
        score: 0.82,
      },
    ];
    setSearchResults(mockResults, localSearchQuery);
    setSearching(false);
  }, [localSearchQuery, activeRepoId, setSearchResults]);

  return (
    <div className="flex flex-col h-full">
      {/* Repo info header */}
      <div className="px-3 py-2 border-b border-[var(--forge-border)]">
        <div className="flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-[var(--forge-accent)]" />
          <span className="text-sm font-medium text-white truncate">{repo.name}</span>
          {repo.indexingStatus === "ready" && (
            <span className="text-[10px] text-[var(--forge-text-muted)] ml-auto">
              {repo.chunkCount} chunks · {repo.fileCount} files
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 mt-1">
          {repo.languages.map((lang) => (
            <span
              key={lang}
              className={cn(
                "text-[10px] px-1.5 py-px rounded-full bg-[var(--forge-hover)]",
                LANG_COLORS[lang] ?? "text-[var(--forge-text-muted)]"
              )}
            >
              {lang}
            </span>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-[var(--forge-border)]">
        {(
          [
            { id: "tree", label: "Files" },
            { id: "search", label: "Search" },
            { id: "deps", label: "Dependencies" },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "px-2.5 py-1 text-xs rounded transition-colors",
              activeTab === tab.id
                ? "bg-[var(--forge-hover)] text-white"
                : "text-[var(--forge-text-muted)] hover:text-white"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === "tree" && (
          <FileTreeView
            nodes={fileTree}
            repoPath={repo.localPath}
            selectedFile={selectedFile}
            onSelectFile={setSelectedFile}
          />
        )}

        {activeTab === "search" && (
          <div className="flex flex-col h-full">
            {/* Search input */}
            <div className="p-3 border-b border-[var(--forge-border)]">
              <div className="flex items-center gap-2 rounded-md border border-[var(--forge-border)] bg-[var(--forge-bg)] px-2.5 py-1.5">
                <Search className="w-3.5 h-3.5 text-[var(--forge-text-muted)] shrink-0" />
                <input
                  type="text"
                  value={localSearchQuery}
                  onChange={(e) => setLocalSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSearch();
                  }}
                  placeholder="Search codebase..."
                  className="flex-1 bg-transparent text-sm text-[var(--forge-text)] outline-none placeholder:text-[var(--forge-text-muted)]"
                />
                {searching && <Loader2 className="w-3.5 h-3.5 text-[var(--forge-accent)] animate-spin" />}
                {searchQuery && !searching && (
                  <button
                    onClick={() => {
                      clearSearch();
                      setLocalSearchQuery("");
                    }}
                    className="p-0.5 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)]"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>

            {/* Results */}
            <div className="flex-1 overflow-y-auto">
              {searchResults.length > 0 ? (
                <div className="divide-y divide-[var(--forge-border)]">
                  {searchResults.map((result) => (
                    <SearchResultItem
                      key={result.chunk.id}
                      result={result}
                      repoPath={repo.localPath}
                    />
                  ))}
                </div>
              ) : searchQuery ? (
                <div className="p-4 text-center text-sm text-[var(--forge-text-muted)]">
                  No results for "{searchQuery}"
                </div>
              ) : (
                <div className="p-4 text-center text-sm text-[var(--forge-text-muted)]">
                  Search for functions, patterns, or concepts
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === "deps" && (
          <DependencyView repoId={repo.id} />
        )}
      </div>
    </div>
  );
}

// ─── File tree view ─────────────────────────────────────

function FileTreeView({
  nodes,
  repoPath,
  selectedFile,
  onSelectFile,
  depth = 0,
}: {
  nodes: FileNode[];
  repoPath: string;
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
  depth?: number;
}) {
  return (
    <div className={depth === 0 ? "py-1" : ""}>
      {nodes.map((node) => (
        <FileTreeNode
          key={node.path}
          node={node}
          repoPath={repoPath}
          selectedFile={selectedFile}
          onSelectFile={onSelectFile}
          depth={depth}
        />
      ))}
    </div>
  );
}

function FileTreeNode({
  node,
  repoPath,
  selectedFile,
  onSelectFile,
  depth,
}: {
  node: FileNode;
  repoPath: string;
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
  depth: number;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const isDir = node.type === "directory";
  const isSelected = selectedFile === node.path;

  return (
    <div>
      <button
        onClick={() => {
          if (isDir) {
            setExpanded(!expanded);
          } else {
            onSelectFile(node.path);
          }
        }}
        className={cn(
          "flex items-center gap-1.5 w-full text-left text-xs py-1 pr-2 hover:bg-[var(--forge-hover)] transition-colors",
          isSelected && "bg-[var(--forge-active)] text-white"
        )}
        style={{ paddingLeft: `${depth * 16 + 12}px` }}
      >
        {isDir ? (
          expanded ? (
            <>
              <ChevronDown className="w-3 h-3 text-[var(--forge-text-muted)] shrink-0" />
              <FolderOpen className="w-3.5 h-3.5 text-[var(--forge-accent)] shrink-0" />
            </>
          ) : (
            <>
              <ChevronRight className="w-3 h-3 text-[var(--forge-text-muted)] shrink-0" />
              <Folder className="w-3.5 h-3.5 text-[var(--forge-text-muted)] shrink-0" />
            </>
          )
        ) : (
          <>
            <span className="w-3 shrink-0" />
            <File className="w-3.5 h-3.5 text-[var(--forge-text-muted)] shrink-0" />
          </>
        )}
        <span className={cn(
          "truncate",
          isDir ? "text-[var(--forge-text)]" : "text-[var(--forge-text)]"
        )}>
          {node.name}
        </span>
        {!isDir && node.chunkCount != null && (
          <span className="ml-auto text-[10px] text-[var(--forge-text-muted)] shrink-0">
            {node.chunkCount}
          </span>
        )}
        {!isDir && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              const fullPath = `${repoPath}/${node.path}`;
              invoke("open_in_vscode", { path: fullPath }).catch((err) =>
                console.error("Failed to open in VS Code:", err)
              );
            }}
            className="ml-1 p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-[var(--forge-accent)] transition-all shrink-0"
            title="Open in VS Code"
          >
            <ExternalLink className="w-3 h-3" />
          </button>
        )}
      </button>

      {isDir && expanded && node.children && (
        <FileTreeView
          nodes={node.children}
          repoPath={repoPath}
          selectedFile={selectedFile}
          onSelectFile={onSelectFile}
          depth={depth + 1}
        />
      )}
    </div>
  );
}

// ─── Search result item ─────────────────────────────────

function SearchResultItem({
  result,
  repoPath,
}: {
  result: RepoSearchResult;
  repoPath: string;
}) {
  const { chunk, score } = result;
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="px-3 py-2">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 min-w-0 flex-1 text-left"
        >
          {expanded ? (
            <ChevronDown className="w-3 h-3 text-[var(--forge-text-muted)] shrink-0" />
          ) : (
            <ChevronRight className="w-3 h-3 text-[var(--forge-text-muted)] shrink-0" />
          )}
          <File className="w-3.5 h-3.5 text-[var(--forge-text-muted)] shrink-0" />
          <span className="text-xs text-[var(--forge-accent)] truncate">
            {chunk.filePath}
          </span>
          <span className="text-[10px] text-[var(--forge-text-muted)] shrink-0">
            L{chunk.startLine}-{chunk.endLine}
          </span>
        </button>
        <span className="text-[10px] text-[var(--forge-text-muted)] shrink-0">
          {Math.round(score * 100)}%
        </span>
        <button
          onClick={() => {
            const fullPath = `${repoPath}/${chunk.filePath}`;
            invoke("open_in_vscode", { path: fullPath, line: chunk.startLine }).catch(
              (err) => console.error("Failed to open in VS Code:", err)
            );
          }}
          className="p-0.5 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-[var(--forge-accent)] transition-colors shrink-0"
          title="Open in VS Code"
        >
          <ExternalLink className="w-3 h-3" />
        </button>
      </div>

      {chunk.summary && (
        <p className="text-[10px] text-[var(--forge-text-muted)] mt-1 ml-5">
          {chunk.summary}
        </p>
      )}

      {chunk.symbols && chunk.symbols.length > 0 && (
        <div className="flex gap-1 mt-1 ml-5">
          {chunk.symbols.map((sym) => (
            <span
              key={sym}
              className="text-[10px] px-1.5 py-px rounded bg-[var(--forge-hover)] text-[var(--forge-accent)] font-mono"
            >
              {sym}
            </span>
          ))}
        </div>
      )}

      {expanded && (
        <pre className="mt-2 ml-5 p-2 rounded border border-[var(--forge-border)] bg-[var(--forge-bg)] overflow-x-auto">
          <code className="text-[11px] text-[var(--forge-text)] font-mono leading-5">
            {chunk.content}
          </code>
        </pre>
      )}
    </div>
  );
}

// ─── Dependency view ────────────────────────────────────

function DependencyView({ repoId }: { repoId: string }) {
  const { dependencies } = useRepoStore();
  const edges = dependencies[repoId] ?? [];

  // Build adjacency list for visualization
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    const existing = adjacency.get(edge.from) ?? [];
    existing.push(edge.to);
    adjacency.set(edge.from, existing);
  }

  if (edges.length === 0) {
    // Show mock dependency data
    const mockDeps = [
      { from: "src/routes/auth.ts", to: "src/models/User.ts", imports: ["User"] },
      { from: "src/routes/auth.ts", to: "src/middleware/auth.ts", imports: ["requireAuth"] },
      { from: "src/routes/pipelines.ts", to: "src/models/Pipeline.ts", imports: ["Pipeline"] },
      { from: "src/routes/agents.ts", to: "src/models/Agent.ts", imports: ["Agent"] },
      { from: "src/middleware/auth.ts", to: "src/config.ts", imports: ["config"] },
      { from: "src/index.ts", to: "src/routes/auth.ts", imports: ["authRoutes"] },
      { from: "src/index.ts", to: "src/routes/pipelines.ts", imports: ["pipelineRoutes"] },
      { from: "src/index.ts", to: "src/routes/agents.ts", imports: ["agentRoutes"] },
    ];

    return (
      <div className="p-3 space-y-3">
        <div className="text-xs text-[var(--forge-text-muted)] mb-2">
          Import graph ({mockDeps.length} edges)
        </div>
        {mockDeps.map((dep, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="text-[var(--forge-text)] font-mono truncate min-w-0">
              {dep.from.split("/").pop()}
            </span>
            <span className="text-[var(--forge-text-muted)] shrink-0">&rarr;</span>
            <span className="text-[var(--forge-accent)] font-mono truncate min-w-0">
              {dep.to.split("/").pop()}
            </span>
            <span className="text-[10px] text-[var(--forge-text-muted)] shrink-0 ml-auto">
              {dep.imports.join(", ")}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      <div className="text-xs text-[var(--forge-text-muted)] mb-2">
        {edges.length} import relationships
      </div>
      {Array.from(adjacency.entries()).map(([from, targets]) => (
        <div key={from} className="text-xs">
          <div className="text-[var(--forge-text)] font-mono mb-1">{from}</div>
          {targets.map((to) => (
            <div key={to} className="flex items-center gap-2 ml-4 text-[var(--forge-text-muted)]">
              <span>&rarr;</span>
              <span className="text-[var(--forge-accent)] font-mono">{to}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
