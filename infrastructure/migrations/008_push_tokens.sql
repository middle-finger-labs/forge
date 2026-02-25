-- Push notification device tokens for APNs (iOS) and FCM (Android)

CREATE TABLE push_tokens (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    org_id       UUID NOT NULL,
    platform     TEXT NOT NULL CHECK (platform IN ('ios', 'android')),
    token        TEXT NOT NULL UNIQUE,
    device_name  TEXT,
    app_version  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);

-- Fast lookup by user (send push to all of a user's devices)
CREATE INDEX idx_push_tokens_user ON push_tokens (user_id);

-- Org-scoped queries (broadcast to all org members)
CREATE INDEX idx_push_tokens_org ON push_tokens (org_id);

-- Cleanup stale tokens by last_used_at
CREATE INDEX idx_push_tokens_last_used ON push_tokens (last_used_at);
