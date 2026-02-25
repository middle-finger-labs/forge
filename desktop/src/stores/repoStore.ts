import { create } from "zustand";
import type {
  Repository,
  FileNode,
  RepoChunk,
  RepoSearchResult,
  DependencyEdge,
} from "@/types/repository";

interface RepoStore {
  // ─── State ──────────────────────────────────────────
  repos: Record<string, Repository>;
  /** The repo currently selected as chat context */
  activeRepoId: string | null;
  /** File trees loaded per repo */
  fileTrees: Record<string, FileNode[]>;
  /** Chunks loaded for a specific file */
  fileChunks: Record<string, RepoChunk[]>; // key: `${repoId}:${filePath}`
  /** Search results for the current query */
  searchResults: RepoSearchResult[];
  searchQuery: string;
  /** Dependency graph edges per repo */
  dependencies: Record<string, DependencyEdge[]>;

  // ─── Actions ────────────────────────────────────────
  setRepos: (repos: Repository[]) => void;
  addRepo: (repo: Repository) => void;
  updateRepo: (id: string, updates: Partial<Repository>) => void;
  removeRepo: (id: string) => void;
  setActiveRepo: (id: string | null) => void;
  clearActiveRepo: () => void;
  setFileTree: (repoId: string, tree: FileNode[]) => void;
  setFileChunks: (repoId: string, filePath: string, chunks: RepoChunk[]) => void;
  setSearchResults: (results: RepoSearchResult[], query: string) => void;
  clearSearch: () => void;
  setDependencies: (repoId: string, edges: DependencyEdge[]) => void;

  // ─── Computed helpers ───────────────────────────────
  getActiveRepo: () => Repository | undefined;
}

export const useRepoStore = create<RepoStore>((set, get) => ({
  repos: {},
  activeRepoId: null,
  fileTrees: {},
  fileChunks: {},
  searchResults: [],
  searchQuery: "",
  dependencies: {},

  setRepos: (repos) =>
    set({
      repos: Object.fromEntries(repos.map((r) => [r.id, r])),
    }),

  addRepo: (repo) =>
    set((state) => ({
      repos: { ...state.repos, [repo.id]: repo },
    })),

  updateRepo: (id, updates) =>
    set((state) => {
      const existing = state.repos[id];
      if (!existing) return state;
      return {
        repos: { ...state.repos, [id]: { ...existing, ...updates } },
      };
    }),

  removeRepo: (id) =>
    set((state) => {
      const { [id]: _, ...rest } = state.repos;
      return {
        repos: rest,
        activeRepoId: state.activeRepoId === id ? null : state.activeRepoId,
      };
    }),

  setActiveRepo: (id) => set({ activeRepoId: id }),
  clearActiveRepo: () => set({ activeRepoId: null }),

  setFileTree: (repoId, tree) =>
    set((state) => ({
      fileTrees: { ...state.fileTrees, [repoId]: tree },
    })),

  setFileChunks: (repoId, filePath, chunks) =>
    set((state) => ({
      fileChunks: {
        ...state.fileChunks,
        [`${repoId}:${filePath}`]: chunks,
      },
    })),

  setSearchResults: (results, query) =>
    set({ searchResults: results, searchQuery: query }),

  clearSearch: () =>
    set({ searchResults: [], searchQuery: "" }),

  setDependencies: (repoId, edges) =>
    set((state) => ({
      dependencies: { ...state.dependencies, [repoId]: edges },
    })),

  getActiveRepo: () => {
    const { repos, activeRepoId } = get();
    return activeRepoId ? repos[activeRepoId] : undefined;
  },
}));
