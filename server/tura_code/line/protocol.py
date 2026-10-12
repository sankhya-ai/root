"""The line's invite, keys and sealed messages: everything the relay must not see.

An invite is ``<relay url>/#<secret>``. The fragment never leaves the client —
browsers and HTTP libraries do not send it — so the relay only ever learns
what is derived from the secret for it:

    token   = HMAC(secret, "chamber/token")   sent to the relay as a bearer
    line id = sha256(token)[:32]                 the relay checks this, statelessly
    key     = HMAC(secret, "chamber/key")      AES-256-GCM, never sent

A message body is sealed with the envelope (line, sender, recipient, id,
reply_to) as associated data, so the relay can route a message but cannot read
it, alter it, or pass it off as from someone else. Anyone holding the invite is
on the line: share it like a password.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AGENT = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}/[a-z0-9][a-z0-9._-]{0,31}")
#: Files up to this size travel inside the (sealed) message; bigger ones go to
#: the relay's file storage, sealed the same way, wiped when the session ends.
INLINE_FILE_BYTES = 64 * 1024


class LineError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class Invite:
    relay: str
    secret: str
    #: This member's admin-signed pass (personal invites); empty on an open relay.
    pass_: str = ""

    @classmethod
    def new(cls, relay: str) -> "Invite":
        return cls(relay.rstrip("/"), _b64(secrets.token_bytes(32)))

    @classmethod
    def parse(cls, text: str) -> "Invite":
        """``https://<relay>/#<secret>``, or ``…#<secret>~<pass>`` for a personal invite."""
        relay, _, key = text.strip().partition("#")
        secret, _, pass_ = key.partition("~")
        parts = urlsplit(relay)
        if parts.scheme not in ("https", "http") or not parts.netloc or len(secret) < 32:
            raise LineError("an invite looks like https://<relay>/#<secret>")
        return cls(f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/"), secret, pass_)

    def __str__(self) -> str:
        return f"{self.relay}/#{self.secret}" + (f"~{self.pass_}" if self.pass_ else "")

    def _derive(self, label: bytes) -> bytes:
        return hmac.new(_unb64(self.secret), b"chamber/" + label, hashlib.sha256).digest()

    @property
    def token(self) -> str:
        return _b64(self._derive(b"token"))

    @property
    def line_id(self) -> str:
        return hashlib.sha256(self.token.encode()).hexdigest()[:32]

    @property
    def ws_url(self) -> str:
        base = self.relay.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{base}/v1/lines/{self.line_id}/ws"

    def _aad(self, sender: str, to: str, message_id: str, reply_to: str | None) -> bytes:
        return "|".join((self.line_id, sender, to, message_id, reply_to or "")).encode()

    def seal(self, payload: dict[str, Any], *, sender: str, to: str, message_id: str, reply_to: str | None) -> str:
        nonce = os.urandom(12)
        data = json.dumps(payload, separators=(",", ":")).encode()
        return _b64(nonce + AESGCM(self._derive(b"key")).encrypt(nonce, data, self._aad(sender, to, message_id, reply_to)))

    def seal_blob(self, data: bytes, blob_id: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(self._derive(b"key")).encrypt(nonce, data, f"{self.line_id}|blob|{blob_id}".encode())

    def open_blob(self, sealed: bytes, blob_id: str) -> bytes:
        try:
            return AESGCM(self._derive(b"key")).decrypt(sealed[:12], sealed[12:], f"{self.line_id}|blob|{blob_id}".encode())
        except (InvalidTag, ValueError) as error:
            raise LineError("a file that does not open with this line's key") from error

    def blob_url(self, blob_id: str) -> str:
        return f"{self.relay}/v1/lines/{self.line_id}/blobs/{blob_id}"

    def open(self, body: str, *, sender: str, to: str, message_id: str, reply_to: str | None) -> dict[str, Any]:
        try:
            raw = _unb64(body)
            data = AESGCM(self._derive(b"key")).decrypt(raw[:12], raw[12:], self._aad(sender, to, message_id, reply_to))
        except (InvalidTag, ValueError) as error:
            raise LineError("a message that does not open with this line's key") from error
        return json.loads(data)


@dataclass
class Message:
    """One message as an agent sees it: opened, with its files decoded."""

    id: str
    sender: str
    to: str
    text: str
    reply_to: str | None = None
    seq: int = 0
    ts: int = 0
    files: list[dict[str, Any]] = field(default_factory=list)  # {"name", "data": bytes}
    #: The conversation it belongs to, and that conversation's title (set by the sender).
    thread: str | None = None
    title: str = ""
    #: People @mentioned (a channel message reaches their agents through these).
    mentions: list[str] = field(default_factory=list)


_MENTION = re.compile(r"(?:^|[^\w@])@([a-z0-9][a-z0-9._-]{0,31})", re.I)


def mentions_in(text: str) -> list[str]:
    """People @mentioned in a text: the relay routes on these (it cannot read the text). Same rule as chamber."""
    out: list[str] = []
    for match in _MENTION.finditer(text or ""):
        name = match.group(1).lower().rstrip(".")
        if name and name not in out:
            out.append(name)
    return out


def encode_file(name: str, data: bytes) -> dict[str, str]:
    return {"name": name, "data": base64.b64encode(data).decode()}


def decode_file(item: Any) -> dict[str, Any] | None:
    """An inline file, or ``{"name", "blob", "size"}`` for one in the relay's storage."""
    if not isinstance(item, dict):
        return None
    name = Path(str(item.get("name") or "file")).name or "file"
    blob = str(item.get("blob") or "")
    if blob:
        return {"name": name, "blob": blob, "size": int(item.get("size") or 0)} if re.fullmatch(r"[0-9a-f]{32}", blob) else None
    try:
        return {"name": name, "data": base64.b64decode(str(item.get("data") or ""))}
    except ValueError:
        return None
