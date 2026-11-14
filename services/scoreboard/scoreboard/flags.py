"""Flags: DVAP{<challenge>_<hmac>}. Deterministic per (secret, team, challenge), so the board
can both mint a flag on success and verify a pasted one without storing it."""

import hashlib
import hmac
import re

FLAG_RE = re.compile(r"^DVAP\{(?P<challenge>[A-Za-z0-9_]+)_(?P<mac>[0-9a-f]{16})\}$")


def _mac(secret: str, team: str, challenge: str) -> str:
    return hmac.new(secret.encode(), f"{team}:{challenge}".encode(), hashlib.sha256).hexdigest()[:16]


def make_flag(secret: str, team: str, challenge: str) -> str:
    return f"DVAP{{{challenge}_{_mac(secret, team, challenge)}}}"


def verify_flag(secret: str, team: str, flag: str) -> str | None:
    """Return the challenge id if `flag` is valid for this team, else None."""
    m = FLAG_RE.match(flag.strip())
    if not m:
        return None
    challenge = m.group("challenge")
    return challenge if hmac.compare_digest(m.group("mac"), _mac(secret, team, challenge)) else None
