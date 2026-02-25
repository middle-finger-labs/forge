import { create } from "zustand";
import { invoke } from "@tauri-apps/api/core";

// ─── Tauri proxy helper (same as connectionStore) ────

interface ProxyResponse {
  status: number;
  body: string;
  headers: Record<string, string>;
}

async function authedFetch<T>(
  serverUrl: string,
  path: string,
  token: string,
  opts?: { method?: string; body?: string }
): Promise<T> {
  const res = await invoke<ProxyResponse>("proxy_fetch", {
    url: `${serverUrl}${path}`,
    method: opts?.method ?? "GET",
    body: opts?.body ?? null,
    authToken: token,
  });
  if (res.status < 200 || res.status >= 300) {
    let detail = `Request failed (${res.status})`;
    try {
      const parsed = JSON.parse(res.body);
      if (parsed.detail) detail = parsed.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return JSON.parse(res.body) as T;
}

// ─── Types ───────────────────────────────────────────

export type OnboardingStepName = "api_key" | "github" | "meet_team" | "first_pipeline";

export interface OnboardingState {
  // Server state
  completed: boolean;
  steps: Record<OnboardingStepName, boolean>;
  dismissedAt: string | null;
  completedAt: string | null;

  // UI state
  loaded: boolean;
  loading: boolean;
  expandedStep: OnboardingStepName | null;
  bannerDismissedForSession: boolean;

  // GitHub state (populated after connecting)
  githubUser: string | null;
  githubRepos: GitHubRepo[];
  selectedRepo: GitHubRepo | null;

  // Actions
  fetchState: (serverUrl: string, token: string) => Promise<void>;
  completeStep: (serverUrl: string, token: string, step: OnboardingStepName) => Promise<void>;
  dismiss: (serverUrl: string, token: string) => Promise<void>;
  complete: (serverUrl: string, token: string) => Promise<void>;
  setExpandedStep: (step: OnboardingStepName | null) => void;
  dismissBannerForSession: () => void;
  resumeOnboarding: () => void;
  setGitHubUser: (user: string) => void;
  setGitHubRepos: (repos: GitHubRepo[]) => void;
  setSelectedRepo: (repo: GitHubRepo | null) => void;

  // Derived
  completedCount: () => number;
  totalSteps: () => number;
  visibleSteps: () => OnboardingStepName[];
  shouldShowOnboarding: () => boolean;
  shouldShowBanner: () => boolean;
}

export interface GitHubRepo {
  full_name: string;
  name: string;
  owner: string;
  description: string | null;
  stars: number;
  default_branch: string;
  private: boolean;
  html_url: string;
}

// ─── Store ───────────────────────────────────────────

export const useOnboardingStore = create<OnboardingState>((set, get) => ({
  completed: false,
  steps: { api_key: false, github: false, meet_team: false, first_pipeline: false },
  dismissedAt: null,
  completedAt: null,

  loaded: false,
  loading: false,
  expandedStep: null,
  bannerDismissedForSession: false,

  githubUser: null,
  githubRepos: [],
  selectedRepo: null,

  fetchState: async (serverUrl, token) => {
    set({ loading: true });
    try {
      const data = await authedFetch<{
        completed: boolean;
        steps: Record<OnboardingStepName, boolean>;
        dismissed_at: string | null;
        completed_at: string | null;
      }>(serverUrl, "/api/onboarding", token);

      set({
        completed: data.completed,
        steps: data.steps,
        dismissedAt: data.dismissed_at,
        completedAt: data.completed_at,
        loaded: true,
      });
    } catch (err) {
      // If server returned 404, onboarding isn't set up — treat as completed.
      // For other errors (network, 500), leave unloaded so it retries next time.
      const is404 = err instanceof Error && err.message.includes("404");
      if (is404) {
        set({ completed: true, loaded: true });
      } else {
        set({ loaded: true });
      }
    } finally {
      set({ loading: false });
    }
  },

  completeStep: async (serverUrl, token, step) => {
    try {
      const data = await authedFetch<{
        completed: boolean;
        steps: Record<OnboardingStepName, boolean>;
        dismissed_at: string | null;
        completed_at: string | null;
      }>(serverUrl, `/api/onboarding/step/${step}`, token, {
        method: "PUT",
        body: JSON.stringify({ completed: true }),
      });

      set({
        completed: data.completed,
        steps: data.steps,
        dismissedAt: data.dismissed_at,
        completedAt: data.completed_at,
      });
    } catch {
      // Optimistic: mark locally even if server fails
      set((s) => ({
        steps: { ...s.steps, [step]: true },
      }));
    }
  },

  dismiss: async (serverUrl, token) => {
    try {
      const data = await authedFetch<{
        completed: boolean;
        steps: Record<OnboardingStepName, boolean>;
        dismissed_at: string | null;
        completed_at: string | null;
      }>(serverUrl, "/api/onboarding/dismiss", token, { method: "POST" });

      set({
        completed: data.completed,
        steps: data.steps,
        dismissedAt: data.dismissed_at,
        completedAt: data.completed_at,
      });
    } catch {
      set({ dismissedAt: new Date().toISOString() });
    }
  },

  complete: async (serverUrl, token) => {
    try {
      const data = await authedFetch<{
        completed: boolean;
        steps: Record<OnboardingStepName, boolean>;
        dismissed_at: string | null;
        completed_at: string | null;
      }>(serverUrl, "/api/onboarding/complete", token, { method: "POST" });

      set({
        completed: data.completed,
        steps: data.steps,
        dismissedAt: data.dismissed_at,
        completedAt: data.completed_at,
      });
    } catch {
      set({ completed: true, completedAt: new Date().toISOString() });
    }
  },

  setExpandedStep: (step) => set({ expandedStep: step }),
  dismissBannerForSession: () => set({ bannerDismissedForSession: true }),
  resumeOnboarding: () => set({ dismissedAt: null, bannerDismissedForSession: false }),
  setGitHubUser: (user) => set({ githubUser: user }),
  setGitHubRepos: (repos) => set({ githubRepos: repos }),
  setSelectedRepo: (repo) => set({ selectedRepo: repo }),

  completedCount: () => {
    const { steps } = get();
    return Object.values(steps).filter(Boolean).length;
  },

  totalSteps: () => {
    return Object.keys(get().steps).length;
  },

  visibleSteps: () => {
    return Object.keys(get().steps) as OnboardingStepName[];
  },

  shouldShowOnboarding: () => {
    const { completed, dismissedAt, loaded } = get();
    if (!loaded) return false;
    return !completed && !dismissedAt;
  },

  shouldShowBanner: () => {
    const { completed, dismissedAt, bannerDismissedForSession, loaded } = get();
    if (!loaded) return false;
    return !completed && !!dismissedAt && !bannerDismissedForSession;
  },
}));
