"""The board, from root: root starts `chamber board` (the chamber tool's own board)
next to itself, and its web UI sends you there.

The board lives in chamber so everyone gets it with the one-command install,
whether or not they run root. root only makes sure it is up while root is.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from . import config as line_config

if TYPE_CHECKING:
    from ..tenancy import Server

logger = logging.getLogger(__name__)
PORT = 7878
URL = f"http://127.0.0.1:{PORT}"


def chamber_command() -> list[str] | None:
    """The `chamber` tool: on PATH, else the checkout next to root."""
    found = shutil.which("chamber") or str(Path.home() / ".local" / "bin" / "chamber")
    if Path(found).exists():
        return [found]
    sibling = Path(__file__).resolve().parents[4] / "chamber" / "bin" / "chamber.mjs"
    return ["node", str(sibling)] if sibling.exists() and shutil.which("node") else None


class BoardProcess:
    def __init__(self, server: "Server") -> None:
        self.server = server
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if self.server.mode != "local" or self.process is not None or line_config.load(self.server.home) is None:
            return
        command = chamber_command()
        if command is None:
            logger.info("chamber is not installed: no board")
            return
        # If a board is already running it says so and exits; that one serves.
        self.process = subprocess.Popen([*command, "board", "--no-open", "--port", str(PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
