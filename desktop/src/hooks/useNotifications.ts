import { useCallback, useRef, useEffect } from "react";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import { useSettingsStore } from "@/stores/settingsStore";
import type { NotificationLevel } from "@/stores/settingsStore";

// ─── Types ───────────────────────────────────────────

type NotificationCategory =
  | "pipeline_complete"
  | "pipeline_failed"
  | "approval_requested"
  | "agent_dm"
  | "budget_warning"
  | "agent_error";

interface ForgeNotification {
  category: NotificationCategory;
  title: string;
  body: string;
  /** Group key to deduplicate — e.g., pipeline ID */
  group?: string;
}

// ─── Category → required level mapping ───────────────

const CATEGORY_LEVEL: Record<NotificationCategory, NotificationLevel[]> = {
  pipeline_complete: ["all"],
  pipeline_failed: ["all", "errors"],
  approval_requested: ["all", "approvals"],
  agent_dm: ["all"],
  budget_warning: ["all", "approvals"],
  agent_error: ["all", "errors"],
};

// ─── Dedup interval (ms) per group ───────────────────

const DEDUP_INTERVAL = 10_000; // 10 seconds

// ─── Hook ────────────────────────────────────────────

export function useNotifications() {
  const { notificationLevel, notificationSound } = useSettingsStore();
  const permissionGranted = useRef(false);
  const recentGroups = useRef<Map<string, number>>(new Map());

  // Request permission on mount
  useEffect(() => {
    (async () => {
      let granted = await isPermissionGranted();
      if (!granted) {
        const result = await requestPermission();
        granted = result === "granted";
      }
      permissionGranted.current = granted;
    })();
  }, []);

  // Clean up old dedup entries periodically
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      for (const [key, timestamp] of recentGroups.current.entries()) {
        if (now - timestamp > DEDUP_INTERVAL) {
          recentGroups.current.delete(key);
        }
      }
    }, DEDUP_INTERVAL);

    return () => clearInterval(interval);
  }, []);

  // Core notify — respects preferences and dedup
  const notify = useCallback(
    (notification: ForgeNotification) => {
      if (!permissionGranted.current) return;
      if (notificationLevel === "none") return;

      // Check if this category is allowed at the current level
      const allowedLevels = CATEGORY_LEVEL[notification.category];
      if (!allowedLevels.includes(notificationLevel)) return;

      // Dedup by group key
      if (notification.group) {
        const lastSent = recentGroups.current.get(notification.group);
        if (lastSent && Date.now() - lastSent < DEDUP_INTERVAL) return;
        recentGroups.current.set(notification.group, Date.now());
      }

      // Skip DM notifications if app is focused
      if (notification.category === "agent_dm" && document.hasFocus()) return;

      sendNotification({
        title: notification.title,
        body: notification.body,
        sound: notificationSound ? "default" : undefined,
      });
    },
    [notificationLevel, notificationSound]
  );

  // ─── Convenience methods ─────────────────────────

  const notifyPipelineComplete = useCallback(
    (pipelineName: string, success: boolean) => {
      notify({
        category: success ? "pipeline_complete" : "pipeline_failed",
        title: success ? "Pipeline Complete" : "Pipeline Failed",
        body: success
          ? `"${pipelineName}" finished successfully.`
          : `"${pipelineName}" failed. Check the logs for details.`,
        group: `pipeline-${pipelineName}`,
      });
    },
    [notify]
  );

  const notifyApprovalRequested = useCallback(
    (stage: string, pipelineName: string) => {
      notify({
        category: "approval_requested",
        title: "Approval Required",
        body: `${stage} in "${pipelineName}" needs your review.`,
        group: `approval-${pipelineName}`,
      });
    },
    [notify]
  );

  const notifyAgentDM = useCallback(
    (agentName: string, preview: string) => {
      notify({
        category: "agent_dm",
        title: agentName,
        body: preview.slice(0, 100),
      });
    },
    [notify]
  );

  const notifyBudgetWarning = useCallback(
    (pipelineName: string, percentUsed: number) => {
      notify({
        category: "budget_warning",
        title: "Budget Warning",
        body: `"${pipelineName}" has used ${Math.round(percentUsed)}% of its budget.`,
        group: `budget-${pipelineName}`,
      });
    },
    [notify]
  );

  const notifyAgentError = useCallback(
    (agentName: string, error: string) => {
      notify({
        category: "agent_error",
        title: `${agentName} Error`,
        body: error.slice(0, 150),
        group: `error-${agentName}`,
      });
    },
    [notify]
  );

  return {
    notify,
    notifyPipelineComplete,
    notifyApprovalRequested,
    notifyAgentDM,
    notifyBudgetWarning,
    notifyAgentError,
  };
}
