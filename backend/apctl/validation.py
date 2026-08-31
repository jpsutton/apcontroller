"""Input-validation and path-confinement helpers.

These are the single choke point that keeps attacker-controllable config
strings from turning into SSH argv, filesystem paths, or shell tokens. They are
pure functions so they can be reused by pydantic ``@field_validator`` hooks
(models.py), by the status parser (status_service.py), and by the filesystem
paths built in poll/deploy.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

# A conservative identifier: starts alphanumeric, then alphanumerics plus a few
# safe separators. Critically it forbids a leading "-" (so a value can never be
# parsed by ssh/scp/ping as an option) and any shell/awk metacharacter.
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# RFC-1123 hostname label set, joined by dots. No leading "-".
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_ENC_RE = re.compile(r"^[A-Za-z0-9+\-]{1,32}$")


def _has_control_chars(v: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in v)


def safe_ident(v: str, *, field: str, maxlen: int = 64, allow_empty: bool = False) -> str:
    """Identifier-like config value (username, section id, network, device...).

    Rejects leading '-', whitespace, and shell/awk metacharacters so the value
    is safe both as an ssh/scp argv token and inside on-device uci/awk commands.
    """
    if v == "":
        if allow_empty:
            return v
        raise ValueError(f"{field} must not be empty")
    if len(v) > maxlen:
        raise ValueError(f"{field} too long (max {maxlen})")
    if not _IDENT_RE.match(v):
        raise ValueError(
            f"{field} must match [A-Za-z0-9][A-Za-z0-9._-]* (no leading '-', no spaces/metachars)"
        )
    return v


def host_or_ip(v: str, *, field: str = "ipaddr", allow_empty: bool = True) -> str:
    """An IPv4/IPv6 literal or an RFC-1123 hostname. Empty allowed by default.

    Empty is permitted because an incomplete/disabled host row legitimately has
    no address yet. A non-empty value that is neither a valid IP nor hostname
    (or that starts with '-') is rejected so it cannot be read as an ssh option.
    """
    if v == "":
        if allow_empty:
            return v
        raise ValueError(f"{field} must not be empty")
    if v.startswith("-"):
        raise ValueError(f"{field} must not start with '-'")
    try:
        ipaddress.ip_address(v)
        return v
    except ValueError:
        pass
    if _HOSTNAME_RE.match(v):
        return v
    raise ValueError(f"{field} must be a valid IPv4/IPv6 address or hostname")


def text_field(v: str, *, field: str, maxlen: int) -> str:
    """Free-form text (SSID, key, display name). Rejects control chars/NUL/newline.

    Control-character rejection also blocks the on-device awk-injection vector
    for SSIDs (a raw '/', quote, or newline in an SSID would otherwise break the
    agent's awk matching); combined with the length cap this keeps the value a
    single safe line.
    """
    if len(v) > maxlen:
        raise ValueError(f"{field} too long (max {maxlen})")
    if _has_control_chars(v):
        raise ValueError(f"{field} must not contain control characters")
    return v


def ssid_field(v: str, *, field: str = "ssid", maxlen: int = 32) -> str:
    """SSID: text_field plus reject the characters that break on-device awk/uci
    matching ('/', single/double quote). Belt-and-suspenders for the deferred
    agent-side fix."""
    v = text_field(v, field=field, maxlen=maxlen)
    if any(c in v for c in "/'\""):
        raise ValueError(f"{field} must not contain '/', single, or double quotes")
    return v


def enc_token(v: str, *, field: str = "encryption") -> str:
    if not _ENC_RE.match(v):
        raise ValueError(f"{field} must match [A-Za-z0-9+-]{{1,32}} (e.g. psk2, sae, none)")
    return v


def safe_key_path(v: str, *, field: str = "keyfile", allow_empty: bool = True) -> str:
    """SSH private key path passed to ssh/scp -i. Must be an absolute path with
    no control chars and no leading '-'."""
    if v == "":
        if allow_empty:
            return v
        raise ValueError(f"{field} must not be empty")
    if _has_control_chars(v):
        raise ValueError(f"{field} must not contain control characters")
    if v.startswith("-"):
        raise ValueError(f"{field} must not start with '-'")
    if not v.startswith("/"):
        raise ValueError(f"{field} must be an absolute path")
    return v


def safe_url(v: str, *, field: str = "url") -> str:
    """Blank out any URL that is not http(s). Returns "" rather than raising so a
    single bad GUI link never blocks saving the whole config."""
    if v == "":
        return v
    if _has_control_chars(v):
        return ""
    low = v.strip().lower()
    if low.startswith("http://") or low.startswith("https://"):
        return v
    return ""


def safe_int(v: object, default: int = 0) -> int:
    """Coerce an untrusted (managed-AP-supplied) value to int, defaulting on
    anything non-numeric so a hostile status payload cannot raise ValueError."""
    try:
        if v is None or v == "":
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def confine_path(root: Path, name: str) -> Path:
    """Join ``name`` under ``root`` and assert the result stays inside ``root``.

    Defense-in-depth over the field validators: even if a filename component
    slips through, this refuses to write/read outside the state directory.
    """
    root = root.resolve()
    candidate = (root / name).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path {name!r} escapes state directory {root}")
    return candidate
