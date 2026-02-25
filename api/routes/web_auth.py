"""Web fallback for magic link authentication.

Serves an HTML page that attempts to open the Forge desktop app via deep link,
with fallback buttons for manual action.
"""

from __future__ import annotations

import html
import os
from datetime import datetime, timezone

import asyncpg
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

log = structlog.get_logger().bind(component="web_auth")

web_auth_router = APIRouter(tags=["web_auth"])

SERVER_PUBLIC_URL = os.environ.get("FORGE_PUBLIC_URL", "http://localhost:8000")
DEEP_LINK_SCHEME = "forge"


def _get_db(request: Request) -> asyncpg.Pool:
    from api.server import _get_db
    return _get_db()


@web_auth_router.get("/auth/magic", response_class=HTMLResponse)
async def web_magic_landing(token: str, request: Request):
    """Validate a magic link token and serve a landing page.

    The page auto-redirects via deep link and provides fallback buttons.
    """
    pool = _get_db(request)
    now = datetime.now(timezone.utc)

    # Validate token (read-only — do NOT mark as used)
    row = await pool.fetchrow(
        """
        SELECT id, email, expires_at, used_at
        FROM magic_links
        WHERE token = $1
        """,
        token,
    )

    deep_link = f"{DEEP_LINK_SCHEME}://auth?token={token}&server={SERVER_PUBLIC_URL}"

    if row is None:
        return _render_landing(
            error="This link is invalid or has expired.",
            deep_link=None,
        )

    if row["used_at"] is not None:
        # Already consumed — still allow redirect (idempotent verify handles it)
        return _render_landing(
            heading="Link already used",
            message="This link was already used. If you're signed in, you're all set. Otherwise, request a new link from the app.",
            deep_link=deep_link,
        )

    if row["expires_at"] < now:
        return _render_landing(
            error="This link has expired. Please request a new one from the app.",
            deep_link=None,
        )

    return _render_landing(
        heading="Opening Forge...",
        message="If the app doesn't open automatically, click the button below.",
        deep_link=deep_link,
        auto_redirect=True,
    )


def _render_landing(
    *,
    heading: str = "Sign in to Forge",
    message: str = "",
    error: str | None = None,
    deep_link: str | None = None,
    auto_redirect: bool = False,
) -> str:
    """Render the web fallback HTML page."""
    redirect_script = ""
    if auto_redirect and deep_link:
        safe_link = html.escape(deep_link, quote=True)
        redirect_script = f'<script>window.location = "{safe_link}";</script>'

    button_html = ""
    if deep_link:
        safe_link = html.escape(deep_link, quote=True)
        button_html = f'<a href="{safe_link}" class="cta">Open in Forge</a>'

    error_html = ""
    if error:
        error_html = f'<div class="error">{html.escape(error)}</div>'

    message_html = f"<p>{html.escape(message)}</p>" if message else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(heading)}</title>
  {redirect_script}
  <style>
    body {{
      margin: 0;
      padding: 0;
      background-color: #0a0a0a;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #e0e0e0;
      -webkit-font-smoothing: antialiased;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .container {{
      max-width: 420px;
      text-align: center;
      padding: 32px;
    }}
    .logo-mark {{
      display: inline-block;
      width: 56px;
      height: 56px;
      background: #6366f1;
      border-radius: 14px;
      line-height: 56px;
      text-align: center;
      font-size: 28px;
      font-weight: 700;
      color: #ffffff;
      margin-bottom: 24px;
    }}
    h1 {{
      font-size: 22px;
      font-weight: 600;
      color: #f5f5f5;
      margin: 0 0 12px 0;
    }}
    p {{
      font-size: 14px;
      line-height: 1.6;
      color: #a0a0a0;
      margin: 0 0 24px 0;
    }}
    .cta {{
      display: inline-block;
      background: #6366f1;
      color: #ffffff !important;
      text-decoration: none;
      font-size: 15px;
      font-weight: 600;
      padding: 14px 32px;
      border-radius: 8px;
      margin-bottom: 16px;
      transition: opacity 0.15s;
    }}
    .cta:hover {{ opacity: 0.9; }}
    .error {{
      background: rgba(232, 64, 64, 0.1);
      border: 1px solid rgba(232, 64, 64, 0.3);
      color: #f87171;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 14px;
      margin-bottom: 20px;
    }}
    .download {{
      font-size: 13px;
      color: #666;
      margin-top: 16px;
    }}
    .download a {{
      color: #6366f1;
      text-decoration: none;
    }}
    .download a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="logo-mark">F</div>
    <h1>{html.escape(heading)}</h1>
    {error_html}
    {message_html}
    {button_html}
    <div class="download">
      Don't have Forge? <a href="https://forge.dev/download">Download it here</a>
    </div>
  </div>
</body>
</html>"""
