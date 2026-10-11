"""Multi-human and multi-agent squads, collaboration board, and Engram Bus coordination."""

from .bus import SquadBus
from .models import Issue, Squad
from .service import SquadService

__all__ = ["SquadBus", "SquadService", "Issue", "Squad", "install"]


def install(server) -> None:
    server.squad_bus = SquadBus(server.home / "engram_bus.db")

    def extend(tenant) -> None:
        tenant.squads = SquadService(tenant, bus=server.squad_bus)
        tenant.closers.append(tenant.squads.close)

    server.extensions.append(extend)
