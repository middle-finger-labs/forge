"""Email sending service for Forge.

Supports multiple backends via FORGE_EMAIL_PROVIDER env var:
  - "smtp"    : standard SMTP (default)
  - "resend"  : Resend API (https://resend.com)
  - "console" : print to stdout (development)
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import httpx
import structlog

log = structlog.get_logger().bind(component="email")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EMAIL_PROVIDER = os.environ.get("FORGE_EMAIL_PROVIDER", "console")
EMAIL_FROM = os.environ.get("FORGE_EMAIL_FROM", "Forge <noreply@forge.dev>")

# SMTP settings
SMTP_HOST = os.environ.get("FORGE_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("FORGE_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("FORGE_SMTP_USER", "")
SMTP_PASS = os.environ.get("FORGE_SMTP_PASS", "")
SMTP_TLS = os.environ.get("FORGE_SMTP_TLS", "true").lower() in ("true", "1")

# Resend settings
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

# Template directory
_TEMPLATE_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Template rendering (simple string substitution)
# ---------------------------------------------------------------------------


def render_template(template_name: str, **kwargs: str) -> str:
    """Render an HTML email template with {{ variable }} substitution."""
    template_path = _TEMPLATE_DIR / template_name
    html = template_path.read_text()
    for key, value in kwargs.items():
        html = html.replace("{{ " + key + " }}", value)
    return html


# ---------------------------------------------------------------------------
# Send implementations
# ---------------------------------------------------------------------------


async def _send_smtp(to: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        if SMTP_TLS:
            server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    log.info("email sent via smtp", to=to, subject=subject)


async def _send_resend(to: str, subject: str, html: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
            },
        )
        resp.raise_for_status()

    log.info("email sent via resend", to=to, subject=subject)


async def _send_console(to: str, subject: str, html: str) -> None:
    log.info(
        "email (console mode)",
        to=to,
        subject=subject,
        html_length=len(html),
    )
    print(f"\n{'='*60}")
    print(f"  TO: {to}")
    print(f"  SUBJECT: {subject}")
    print(f"{'='*60}")
    # Print a simplified version (strip HTML tags for readability)
    import re
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\n\s*\n", "\n", text).strip()
    for line in text.split("\n")[:20]:
        stripped = line.strip()
        if stripped:
            print(f"  {stripped}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "smtp": _send_smtp,
    "resend": _send_resend,
    "console": _send_console,
}


async def send_email(to: str, subject: str, html: str) -> None:
    """Send an email using the configured provider."""
    provider_fn = _PROVIDERS.get(EMAIL_PROVIDER)
    if provider_fn is None:
        raise ValueError(f"Unknown email provider: {EMAIL_PROVIDER}")

    try:
        await provider_fn(to, subject, html)
    except Exception as exc:
        log.error("email send failed", to=to, subject=subject, error=str(exc))
        raise
