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
    from . import flows, learning, squads

    learning.install(server)
    flows.install(server)
    squads.install(server)


def routers(state) -> list:
    from .flows.routes import router as flows_router
    from .learning.routes import router as learning_router
    from .squads.links import router as links_router
    from .squads.routes import router as squads_router

    return [learning_router(state), flows_router(state), squads_router(state), links_router(state)]
