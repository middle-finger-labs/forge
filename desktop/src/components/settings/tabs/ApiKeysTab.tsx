import { useState, useCallback } from "react";
import { Plus, Trash2, Copy, Check, Key } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { Section } from "./GeneralTab";

export function ApiKeysTab() {
  const { apiKeys, setApiKeys } = useSettingsStore();
  const { serverUrl, authToken } = useConnectionStore();
  const [creating, setCreating] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeySecret, setNewKeySecret] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleCreate = useCallback(async () => {
    if (!newKeyName.trim()) return;
    setCreating(true);

    try {
      const res = await fetch(`${serverUrl}/api/keys`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ name: newKeyName }),
      });

      if (!res.ok) throw new Error("Failed to create key");

      const data = await res.json() as {
        id: string;
        name: string;
        key: string;
        prefix: string;
        createdAt: string;
      };

      setNewKeySecret(data.key);
      setApiKeys([...apiKeys, { id: data.id, name: data.name, prefix: data.prefix, createdAt: data.createdAt }]);
      setNewKeyName("");
    } catch {
      // Server may not support this yet
    } finally {
      setCreating(false);
    }
  }, [newKeyName, serverUrl, authToken, apiKeys, setApiKeys]);

  const handleDelete = useCallback(
    async (keyId: string) => {
      try {
        await fetch(`${serverUrl}/api/keys/${keyId}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${authToken}` },
        });
      } catch { /* best effort */ }
      setApiKeys(apiKeys.filter((k) => k.id !== keyId));
    },
    [serverUrl, authToken, apiKeys, setApiKeys]
  );

  const handleCopy = useCallback((text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }, []);

  return (
    <div className="max-w-lg space-y-8">
      <Section title="API Keys">
        <p className="text-xs mb-4" style={{ color: "var(--forge-text-muted)" }}>
          API keys allow external tools and scripts to access your Forge server.
          Keys are shown only once when created.
        </p>

        {/* Create new key */}
        <div className="flex gap-2 mb-4">
          <input
            type="text"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="Key name (e.g. CI/CD)"
            className="flex-1 px-3 py-2 rounded-lg text-sm outline-none"
            style={{
              background: "var(--forge-channel)",
              color: "var(--forge-text)",
              border: "1px solid var(--forge-border)",
            }}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <button
            onClick={handleCreate}
            disabled={creating || !newKeyName.trim()}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-white cursor-pointer disabled:opacity-50"
            style={{ background: "var(--forge-accent)" }}
          >
            <Plus className="w-4 h-4" />
            Create
          </button>
        </div>

        {/* Newly created key secret */}
        {newKeySecret && (
          <div
            className="p-3 rounded-lg mb-4"
            style={{
              background: "rgba(43, 172, 118, 0.1)",
              border: "1px solid var(--forge-success)",
            }}
          >
            <div className="text-xs mb-1" style={{ color: "var(--forge-success)" }}>
              Copy your API key now. It won't be shown again.
            </div>
            <div className="flex items-center gap-2">
              <code
                className="flex-1 text-xs p-2 rounded"
                style={{
                  background: "var(--forge-channel)",
                  color: "var(--forge-text)",
                }}
              >
                {newKeySecret}
              </code>
              <button
                onClick={() => {
                  handleCopy(newKeySecret, "new");
                  setNewKeySecret(null);
                }}
                className="p-1.5 rounded-md cursor-pointer"
                style={{ color: "var(--forge-text-muted)" }}
              >
                {copiedId === "new" ? (
                  <Check className="w-4 h-4" style={{ color: "var(--forge-success)" }} />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
        )}

        {/* Key list */}
        {apiKeys.length === 0 ? (
          <div
            className="text-center py-8 rounded-lg"
            style={{
              background: "var(--forge-channel)",
              border: "1px solid var(--forge-border)",
            }}
          >
            <Key
              className="w-8 h-8 mx-auto mb-2"
              style={{ color: "var(--forge-text-muted)" }}
            />
            <div className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
              No API keys yet
            </div>
          </div>
        ) : (
          <div
            className="rounded-lg overflow-hidden"
            style={{ border: "1px solid var(--forge-border)" }}
          >
            {apiKeys.map((key, i) => (
              <div
                key={key.id}
                className="flex items-center justify-between px-4 py-3"
                style={{
                  background: "var(--forge-channel)",
                  borderTop: i > 0 ? "1px solid var(--forge-border)" : undefined,
                }}
              >
                <div>
                  <div className="text-sm" style={{ color: "var(--forge-text)" }}>
                    {key.name}
                  </div>
                  <div
                    className="text-xs mt-0.5 font-mono"
                    style={{ color: "var(--forge-text-muted)" }}
                  >
                    {key.prefix}... &middot; Created{" "}
                    {new Date(key.createdAt).toLocaleDateString()}
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(key.id)}
                  className="p-1.5 rounded-md transition-colors cursor-pointer"
                  style={{ color: "var(--forge-text-muted)" }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.color = "var(--forge-error)")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.color = "var(--forge-text-muted)")
                  }
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
