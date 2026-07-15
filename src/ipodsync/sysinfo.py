"""Read the device's FirewireGuid — needed for the hashAB signature.

FirewireGuid is an 8-byte device identifier. It normally lives in
`iPod_Control/Device/SysInfoExtended` (XML plist) or `SysInfo` (text), as a hex
string like `0x000A2700XXXXXXXX` (16 hex chars).

On a Mac-formatted iPod mounted on Linux those files are often unreadable (HFS+
transparent compression / restrictive perms). As fallbacks we accept the GUID via
the `IPODSYNC_FIREWIRE_GUID` env var, and derive it from the device's USB serial
(e.g. udev `ID_SERIAL=Apple_iPod_0123456789ABCDEF-0:0`), which stays readable.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ENV_GUID = "IPODSYNC_FIREWIRE_GUID"

# 0x + 16 hex, or a FireWireGUID key near 16 hex chars
_GUID_RE = re.compile(
    r"(?:FireWireGUID|FirewireGuid)\D{0,40}?(?:0x)?([0-9A-Fa-f]{16})",
    re.IGNORECASE | re.DOTALL,
)
_BARE_HEX_RE = re.compile(r"0x([0-9A-Fa-f]{16})")
_SERIAL_RE = re.compile(r"ID_SERIAL=\S*?([0-9A-Fa-f]{16})")


class FirewireGuidNotFound(RuntimeError):
    pass


def _clean_hex(s: str) -> str | None:
    s = s.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return s if re.fullmatch(r"[0-9a-f]{16}", s) else None


def _extract(text: str) -> str | None:
    m = _GUID_RE.search(text) or _BARE_HEX_RE.search(text)
    return m.group(1) if m else None


def _from_env() -> bytes | None:
    v = os.environ.get(ENV_GUID)
    if not v:
        return None
    h = _clean_hex(v)
    if not h:
        raise FirewireGuidNotFound(
            f"{ENV_GUID}={v!r} is not 16 hex digits (e.g. 0123456789ABCDEF)")
    return bytes.fromhex(h)


def _from_files(*paths: Path | None) -> bytes | None:
    for p in paths:
        if p is None:
            continue
        try:
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue  # unreadable (e.g. HFS+ compression on Linux)
        h = _extract(text)
        if h:
            return bytes.fromhex(h)
    return None


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _from_usb_serial(mount: Path | None) -> bytes | None:
    """Linux: derive the GUID from the iPod's USB serial (readable when the
    HFS+ SysInfo* files are not)."""
    if mount is None or not sys.platform.startswith("linux"):
        return None
    src = _run(["findmnt", "-no", "SOURCE", "--target", str(mount)])
    devices = [src] if src else []
    if src:
        pk = _run(["lsblk", "-no", "pkname", src])
        if pk:
            devices.append(f"/dev/{pk}")
    for dev in devices:
        m = _SERIAL_RE.search(_run(["udevadm", "info", "-q", "property", "-n", dev]))
        if m:
            return bytes.fromhex(m.group(1))
    return None


def read_firewire_guid(sysinfo_extended: Path, sysinfo: Path | None = None,
                       mount: Path | None = None) -> bytes:
    """Return the FirewireGuid as 8 bytes (big-endian, as in the hex string).

    Resolution order: `IPODSYNC_FIREWIRE_GUID` env → SysInfoExtended/SysInfo files
    → the device's USB serial (Linux). `mount` is the iPod root (for the USB fallback).
    """
    for guid in (_from_env(), _from_files(sysinfo_extended, sysinfo),
                 _from_usb_serial(mount)):
        if guid:
            return guid
    raise FirewireGuidNotFound(
        "Could not read the device FireWireGUID.\n"
        f"  Tried {sysinfo_extended} / {sysinfo}"
        + ("  (unreadable — Mac-formatted HFS+ files often aren't readable on Linux)\n"
           if not sys.platform == "darwin" else "\n")
        + f"  Fix: pass it via {ENV_GUID}=<16 hex digits>. Find it with:\n"
        + "    udevadm info -q property -n /dev/sdXN | grep ID_SERIAL   (Linux)\n"
        + "  e.g. ID_SERIAL=Apple_iPod_0123456789ABCDEF-0:0  ->  0123456789ABCDEF")
