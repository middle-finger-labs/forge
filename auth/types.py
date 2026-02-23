"""Shared authentication types used by the FastAPI middleware and other modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ForgeUser:
    """Authenticated user context attached to every API request.

    Populated by the auth middleware after validating the Better Auth session.
    """

    user_id: str
    email: str
    name: str
    org_id: str
    org_slug: str
    role: str  # "owner", "admin", "member"

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"
