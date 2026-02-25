import { useState, useEffect, useCallback } from "react";
import { Loader2, Send, UserPlus, Clock, AlertCircle } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { useConnectionStore } from "@/stores/connectionStore";
import { Section } from "./GeneralTab";
import type { TeamMember, PendingInvite } from "@/services/api";

// ─── Tauri proxy (same pattern as connectionStore) ──

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
    const err = JSON.parse(res.body).detail ?? `Request failed (${res.status})`;
    throw new Error(err);
  }
  return JSON.parse(res.body) as T;
}

export function TeamTab() {
  const { serverUrl, authToken, user } = useConnectionStore();
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [invites, setInvites] = useState<PendingInvite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [sending, setSending] = useState(false);
  const [sendSuccess, setSendSuccess] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!serverUrl || !authToken) return;
    setLoading(true);
    setError(null);
    try {
      const [membersData, invitesData] = await Promise.all([
        authedFetch<TeamMember[]>(serverUrl, "/api/auth/team/members", authToken),
        authedFetch<PendingInvite[]>(serverUrl, "/api/auth/team/invites", authToken),
      ]);
      setMembers(membersData);
      setInvites(invitesData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load team data");
    } finally {
      setLoading(false);
    }
  }, [serverUrl, authToken]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSendInvite = useCallback(async () => {
    if (!inviteEmail.trim() || !serverUrl || !authToken) return;
    setSending(true);
    setSendSuccess(null);
    setError(null);
    try {
      await authedFetch(serverUrl, "/api/auth/invite", authToken, {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      setSendSuccess(`Invite sent to ${inviteEmail.trim()}`);
      setInviteEmail("");
      // Refresh pending invites
      const invitesData = await authedFetch<PendingInvite[]>(
        serverUrl,
        "/api/auth/team/invites",
        authToken
      );
      setInvites(invitesData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invite");
    } finally {
      setSending(false);
    }
  }, [inviteEmail, inviteRole, serverUrl, authToken]);

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

  const isAdmin = user?.role === "admin";

  return (
    <div className="max-w-lg space-y-8">
      {/* Error */}
      {error && (
        <div
          className="flex items-start gap-2 text-xs p-3 rounded-lg"
          style={{
            color: "var(--forge-error)",
            background: "rgba(232, 64, 64, 0.1)",
          }}
        >
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Members */}
      <Section title="Members">
        <div className="space-y-2">
          {members.map((member) => (
            <div
              key={member.id}
              className="flex items-center justify-between p-3 rounded-lg"
              style={{
                background: "var(--forge-channel)",
                border: "1px solid var(--forge-border)",
              }}
            >
              <div>
                <div className="text-sm" style={{ color: "var(--forge-text)" }}>
                  {member.name || member.email.split("@")[0]}
                </div>
                <div className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                  {member.email}
                </div>
              </div>
              <span
                className="text-xs px-2 py-0.5 rounded-full font-medium"
                style={{
                  background:
                    member.role === "admin"
                      ? "rgba(99, 102, 241, 0.15)"
                      : "var(--forge-hover)",
                  color:
                    member.role === "admin"
                      ? "var(--forge-accent)"
                      : "var(--forge-text-muted)",
                }}
              >
                {member.role}
              </span>
            </div>
          ))}
          {members.length === 0 && (
            <p className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
              No members found.
            </p>
          )}
        </div>
      </Section>

      {/* Invite (admin only) */}
      {isAdmin && (
        <Section title="Invite Team Member">
          {sendSuccess && (
            <div
              className="flex items-center gap-2 text-xs p-3 rounded-lg mb-3"
              style={{
                color: "var(--forge-accent)",
                background: "rgba(99, 102, 241, 0.1)",
              }}
            >
              <Send className="w-3.5 h-3.5" />
              {sendSuccess}
            </div>
          )}
          <div className="flex gap-2">
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="colleague@company.com"
              disabled={sending}
              className="flex-1 px-3 py-2 rounded-lg text-sm outline-none transition-colors"
              style={{
                background: "var(--forge-channel)",
                color: "var(--forge-text)",
                border: "1px solid var(--forge-border)",
              }}
              onFocus={(e) => (e.target.style.borderColor = "var(--forge-accent)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--forge-border)")}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSendInvite();
              }}
            />
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              disabled={sending}
              className="px-2 py-2 rounded-lg text-sm outline-none cursor-pointer"
              style={{
                background: "var(--forge-channel)",
                color: "var(--forge-text)",
                border: "1px solid var(--forge-border)",
              }}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
            <button
              onClick={handleSendInvite}
              disabled={sending || !inviteEmail.trim()}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ background: "var(--forge-accent)" }}
            >
              {sending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <UserPlus className="w-4 h-4" />
              )}
              Invite
            </button>
          </div>
        </Section>
      )}

      {/* Pending Invites */}
      {invites.length > 0 && (
        <Section title="Pending Invites">
          <div className="space-y-2">
            {invites.map((invite, i) => (
              <div
                key={`${invite.email}-${i}`}
                className="flex items-center justify-between p-3 rounded-lg"
                style={{
                  background: "var(--forge-channel)",
                  border: "1px solid var(--forge-border)",
                }}
              >
                <div>
                  <div className="text-sm" style={{ color: "var(--forge-text)" }}>
                    {invite.email}
                  </div>
                  <div className="text-xs" style={{ color: "var(--forge-text-muted)" }}>
                    Invited by {invite.invited_by || "Unknown"}
                  </div>
                </div>
                <div className="flex items-center gap-1 text-xs" style={{ color: "var(--forge-text-muted)" }}>
                  <Clock className="w-3 h-3" />
                  {invite.expires_at
                    ? `Expires ${new Date(invite.expires_at).toLocaleDateString()}`
                    : "Pending"}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
