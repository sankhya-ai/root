"""The services layered on top of sessions: each adds toolsets, hooks and routes.

Kept apart from the core so a session knows nothing about learning or coding
flows, and each service can be read (and removed) on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tenancy import Server


def install(server: "Server") -> None:
    """Register every service's tenant extension and after-turn hook."""


def routers(state) -> list:
    return []
