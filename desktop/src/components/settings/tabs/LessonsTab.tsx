import { useState, useEffect, useCallback } from "react";
import { Pencil, Trash2, ThumbsUp, Loader2, X, Check } from "lucide-react";
import type { AgentRole } from "@/types/agent";
import type { Lesson } from "@/types/prompts";
import { getForgeAPI } from "@/services/api";

const LESSON_TYPES = [
  "all",
  "code_pattern",
  "architecture",
  "style",
  "testing",
  "error_handling",
  "performance",
];

export function LessonsTab({ role }: { role: AgentRole }) {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState("all");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const api = await getForgeAPI();
        const data = await api.getLessons(role);
        if (!cancelled) setLessons(data);
      } catch (err) {
        console.error("Failed to load lessons", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [role]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      const api = await getForgeAPI();
      await api.deleteLesson(id);
      setLessons((prev) => prev.filter((l) => l.id !== id));
    } catch (err) {
      console.error("Failed to delete lesson", err);
    }
  }, []);

  const handleReinforce = useCallback(async (id: string) => {
    try {
      const api = await getForgeAPI();
      const updated = await api.reinforceLesson(id);
      setLessons((prev) =>
        prev.map((l) => (l.id === id ? updated : l))
      );
    } catch (err) {
      console.error("Failed to reinforce lesson", err);
    }
  }, []);

  const handleUpdate = useCallback(
    async (id: string, data: { lesson?: string; trigger_context?: string }) => {
      try {
        const api = await getForgeAPI();
        const updated = await api.updateLesson(id, data);
        setLessons((prev) =>
          prev.map((l) => (l.id === id ? updated : l))
        );
      } catch (err) {
        console.error("Failed to update lesson", err);
      }
    },
    []
  );

  const filtered =
    filterType === "all"
      ? lessons
      : lessons.filter((l) => l.lesson_type === filterType);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2
          className="w-5 h-5 animate-spin"
          style={{ color: "var(--forge-text-muted)" }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3 pt-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
          {filtered.length} lesson{filtered.length !== 1 ? "s" : ""}
        </span>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="px-2 py-1 rounded text-xs cursor-pointer outline-none"
          style={{
            background: "var(--forge-bg)",
            color: "var(--forge-text)",
            border: "1px solid var(--forge-border)",
          }}
        >
          {LESSON_TYPES.map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "All types" : t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>

      {/* Lessons list */}
      {filtered.length === 0 ? (
        <div
          className="py-8 text-center text-xs"
          style={{ color: "var(--forge-text-muted)" }}
        >
          No lessons learned yet for this agent.
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((lesson) => (
            <LessonCard
              key={lesson.id}
              lesson={lesson}
              onDelete={handleDelete}
              onReinforce={handleReinforce}
              onUpdate={handleUpdate}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LessonCard({
  lesson,
  onDelete,
  onReinforce,
  onUpdate,
}: {
  lesson: Lesson;
  onDelete: (id: string) => void;
  onReinforce: (id: string) => void;
  onUpdate: (id: string, data: { lesson?: string; trigger_context?: string }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editLesson, setEditLesson] = useState(lesson.lesson);
  const [editTrigger, setEditTrigger] = useState(lesson.trigger_context);

  const confidenceColor =
    lesson.confidence >= 0.8
      ? "var(--forge-success)"
      : lesson.confidence >= 0.5
        ? "var(--forge-warning)"
        : "var(--forge-error)";

  const handleSave = () => {
    onUpdate(lesson.id, {
      lesson: editLesson,
      trigger_context: editTrigger,
    });
    setEditing(false);
  };

  return (
    <div
      className="rounded-lg p-3"
      style={{
        background: "var(--forge-channel)",
        border: "1px solid var(--forge-border)",
      }}
    >
      {editing ? (
        /* Inline edit form */
        <div className="space-y-2">
          <textarea
            value={editLesson}
            onChange={(e) => setEditLesson(e.target.value)}
            rows={3}
            className="w-full p-2 rounded text-xs font-mono resize-none outline-none"
            style={{
              background: "var(--forge-bg)",
              color: "var(--forge-text)",
              border: "1px solid var(--forge-border)",
            }}
          />
          <input
            value={editTrigger}
            onChange={(e) => setEditTrigger(e.target.value)}
            placeholder="Trigger context"
            className="w-full px-2 py-1 rounded text-xs outline-none"
            style={{
              background: "var(--forge-bg)",
              color: "var(--forge-text)",
              border: "1px solid var(--forge-border)",
            }}
          />
          <div className="flex gap-1">
            <button
              onClick={handleSave}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer"
              style={{ background: "var(--forge-accent)", color: "#fff" }}
            >
              <Check className="w-3 h-3" /> Save
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-2 py-1 rounded text-xs cursor-pointer"
              style={{ color: "var(--forge-text-muted)" }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Lesson text */}
          <p className="text-xs mb-1" style={{ color: "var(--forge-text)" }}>
            {lesson.lesson}
          </p>

          {/* Trigger context */}
          {lesson.trigger_context && (
            <p
              className="text-[11px] mb-2"
              style={{ color: "var(--forge-text-muted)" }}
            >
              When: {lesson.trigger_context}
            </p>
          )}

          {/* Pills */}
          <div className="flex items-center gap-1.5 flex-wrap mb-2">
            <span
              className="px-1.5 py-0.5 rounded text-[10px] font-medium"
              style={{
                background: `${confidenceColor}20`,
                color: confidenceColor,
              }}
            >
              {(lesson.confidence * 100).toFixed(0)}%
            </span>
            <span
              className="px-1.5 py-0.5 rounded text-[10px]"
              style={{
                background: "var(--forge-bg)",
                color: "var(--forge-text-muted)",
                border: "1px solid var(--forge-border)",
              }}
            >
              Applied {lesson.times_applied}x
            </span>
            <span
              className="px-1.5 py-0.5 rounded text-[10px]"
              style={{
                background: "var(--forge-bg)",
                color: "var(--forge-text-muted)",
                border: "1px solid var(--forge-border)",
              }}
            >
              Reinforced {lesson.times_reinforced}x
            </span>
            <span
              className="px-1.5 py-0.5 rounded text-[10px]"
              style={{
                background: "var(--forge-accent)20",
                color: "var(--forge-accent)",
              }}
            >
              {lesson.lesson_type.replace(/_/g, " ")}
            </span>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setEditing(true)}
              className="p-1 rounded transition-colors cursor-pointer"
              style={{ color: "var(--forge-text-muted)" }}
              title="Edit"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => onReinforce(lesson.id)}
              className="p-1 rounded transition-colors cursor-pointer"
              style={{ color: "var(--forge-text-muted)" }}
              title="Reinforce"
            >
              <ThumbsUp className="w-3.5 h-3.5" />
            </button>
            {confirmDelete ? (
              <span className="flex items-center gap-1 text-[10px]">
                <button
                  onClick={() => onDelete(lesson.id)}
                  className="px-1.5 py-0.5 rounded cursor-pointer"
                  style={{ background: "var(--forge-error)", color: "#fff" }}
                >
                  Confirm
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="p-0.5 cursor-pointer"
                  style={{ color: "var(--forge-text-muted)" }}
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                className="p-1 rounded transition-colors cursor-pointer"
                style={{ color: "var(--forge-text-muted)" }}
                title="Delete"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
