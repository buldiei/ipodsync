"""Read the device's FirewireGuid — needed for the hashAB signature.

FirewireGuid is an 8-byte device identifier. It lives in
`iPod_Control/Device/SysInfoExtended` (XML plist) or `SysInfo` (text),
as a hex string like `0x000A2700XXXXXXXX` (16 hex characters).
"""
from __future__ import annotations

import re
from pathlib import Path

# 0x + 16 hex, or a FireWireGUID key near 16 hex chars
_GUID_RE = re.compile(
    r"(?:FireWireGUID|FirewireGuid)\D{0,40}?(?:0x)?([0-9A-Fa-f]{16})",
    re.IGNORECASE | re.DOTALL,
)
_BARE_HEX_RE = re.compile(r"0x([0-9A-Fa-f]{16})")


class FirewireGuidNotFound(RuntimeError):
    pass


def _extract(text: str) -> str | None:
    m = _GUID_RE.search(text)
    if m:
        return m.group(1)
    m = _BARE_HEX_RE.search(text)
    if m:
        return m.group(1)
    return None


def read_firewire_guid(sysinfo_extended: Path, sysinfo: Path | None = None) -> bytes:
    """Return FirewireGuid as 8 bytes (big-endian, as in the hex string).

    Tries SysInfoExtended, then SysInfo. errors='ignore' — the files may
    contain binary tails.
    """
    for p in (sysinfo_extended, sysinfo):
        if p is None or not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        hexs = _extract(text)
        if hexs:
            return bytes.fromhex(hexs)
    raise FirewireGuidNotFound(
        f"Could not find FireWireGUID in {sysinfo_extended}"
        + (f" / {sysinfo}" if sysinfo else "")
    )
