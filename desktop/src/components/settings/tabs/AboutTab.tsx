import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Wifi, WifiOff, LogOut, ExternalLink } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";
import { Section } from "./GeneralTab";

export function AboutTab() {
  const { serverUrl, user, org, connectionStatus, logout } =
    useConnectionStore();
  const [appVersion, setAppVersion] = useState("...");

  useEffect(() => {
    invoke<string>("get_app_version").then(setAppVersion).catch(() => {});
  }, []);

  const isConnected =
    connectionStatus === "connected" || connectionStatus === "authenticated";

  return (
    <div className="max-w-lg space-y-8">
      {/* App info */}
      <Section title="Forge Desktop">
        <div
          className="p-4 rounded-lg"
          style={{
            background: "var(--forge-channel)",
            border: "1px solid var(--forge-border)",
          }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm" style={{ color: "var(--forge-text)" }}>
              Version
            </span>
            <span
              className="text-sm font-mono"
              style={{ color: "var(--forge-text-muted)" }}
            >
              v{appVersion}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--forge-text)" }}>
              Status
            </span>
            <span className="flex items-center gap-1.5 text-sm">
              {isConnected ? (
                <>
                  <Wifi
                    className="w-3.5 h-3.5"
                    style={{ color: "var(--forge-success)" }}
                  />
                  <span style={{ color: "var(--forge-success)" }}>Connected</span>
                </>
              ) : (
                <>
                  <WifiOff
                    className="w-3.5 h-3.5"
                    style={{ color: "var(--forge-error)" }}
                  />
                  <span style={{ color: "var(--forge-error)" }}>Disconnected</span>
                </>
              )}
            </span>
          </div>
        </div>
      </Section>

      {/* Server */}
      <Section title="Server">
        <div
          className="p-4 rounded-lg"
          style={{
            background: "var(--forge-channel)",
            border: "1px solid var(--forge-border)",
          }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm" style={{ color: "var(--forge-text)" }}>
              URL
            </span>
            <span
              className="text-sm font-mono"
              style={{ color: "var(--forge-text-muted)" }}
            >
              {serverUrl || "Not configured"}
            </span>
          </div>
          {org && (
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: "var(--forge-text)" }}>
                Organization
              </span>
              <span className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
                {org.name}{" "}
                <span className="text-xs opacity-60">({org.plan})</span>
              </span>
            </div>
          )}
        </div>
      </Section>

      {/* Account */}
      {user && (
        <Section title="Account">
          <div
            className="p-4 rounded-lg"
            style={{
              background: "var(--forge-channel)",
              border: "1px solid var(--forge-border)",
            }}
          >
            <div className="flex items-center gap-3 mb-4">
              {user.avatarUrl ? (
                <img
                  src={user.avatarUrl}
                  alt={user.name}
                  className="w-10 h-10 rounded-full"
                />
              ) : (
                <div
                  className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-medium text-white"
                  style={{ background: "var(--forge-accent)" }}
                >
                  {user.name
                    .split(" ")
                    .map((n) => n[0])
                    .join("")
                    .toUpperCase()
                    .slice(0, 2)}
                </div>
              )}
              <div>
                <div className="text-sm font-medium" style={{ color: "var(--forge-text)" }}>
                  {user.name}
                </div>
                <div className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                  {user.email}
                </div>
              </div>
            </div>

            <button
              onClick={logout}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors w-full justify-center"
              style={{
                color: "var(--forge-error)",
                border: "1px solid var(--forge-error)",
                background: "transparent",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "rgba(232, 64, 64, 0.1)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              <LogOut className="w-4 h-4" />
              Sign out
            </button>
          </div>
        </Section>
      )}

      {/* Links */}
      <Section title="Resources">
        <div className="space-y-2">
          {[
            { label: "Documentation", url: "https://docs.forge.dev" },
            { label: "Release Notes", url: "https://github.com/forge/releases" },
            { label: "Report an Issue", url: "https://github.com/forge/issues" },
          ].map((link) => (
            <a
              key={link.label}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors"
              style={{ color: "var(--forge-text-muted)" }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "var(--forge-hover)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              {link.label}
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          ))}
        </div>
      </Section>
    </div>
  );
}
