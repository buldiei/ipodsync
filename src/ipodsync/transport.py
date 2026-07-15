"""Transport: the iPod nano mounts as an ordinary mass-storage volume.

Uploading = writing files under ``iPod_Control/``. No WebUSB/MTP involved.
This module locates the device, hands out paths and tracks availability.

Discovery is cross-platform:
  - macOS: ``/Volumes/*``
  - Linux: ``/media/$USER/*``, ``/media/*``, ``/run/media/$USER/*``, ``/mnt/*``
  - override: set ``IPODSYNC_MOUNT=/path/to/mount`` or pass ``mount=`` explicitly.
A candidate is an iPod if it contains ``iPod_Control/``.

Access note: on macOS the OS may return ``Operation not permitted`` (EPERM) for a
removable volume when the terminal lacks Full Disk Access (TCC). We tell that state
(NO_ACCESS) apart from "no iPod connected" (NOT_FOUND).
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class IPodNotFound(RuntimeError):
    pass


class Access(Enum):
    READY = "ready"          # volume mounted and iPod_Control/iTunes is readable
    NO_ACCESS = "no_access"  # EPERM — missing TCC permission (macOS Full Disk Access)
    NOT_FOUND = "not_found"  # no iPod connected


NO_ACCESS_HINT = (
    "iPod is mounted ({vols}) but not accessible (macOS TCC).\n"
    "  Quick fix: eject -> unplug -> plug back in.\n"
    "  Permanent: System Settings -> Privacy & Security -> Full Disk Access -> "
    "add your terminal (Terminal/iTerm) and enable it."
)


@dataclass(frozen=True)
class IPod:
    """A mounted iPod. All paths are absolute."""
    root: Path

    @property
    def control(self) -> Path:
        return self.root / "iPod_Control"

    @property
    def itunes_dir(self) -> Path:
        return self.control / "iTunes"

    @property
    def itunes_cdb(self) -> Path:
        """Legacy mhbd named iTunesCDB (device regenerates it from SQLite)."""
        return self.itunes_dir / "iTunesCDB"

    @property
    def music_dir(self) -> Path:
        return self.control / "Music"

    @property
    def device_dir(self) -> Path:
        return self.control / "Device"

    @property
    def sysinfo_extended(self) -> Path:
        return self.device_dir / "SysInfoExtended"

    @property
    def sysinfo(self) -> Path:
        return self.device_dir / "SysInfo"


def _candidate_roots() -> list[Path]:
    """Possible mount points to probe, in priority order."""
    env = os.environ.get("IPODSYNC_MOUNT")
    if env:
        return [Path(env)]
    roots: list[Path] = []
    if sys.platform == "darwin":
        base_dirs = ["/Volumes"]
    else:  # linux and other posix
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        base_dirs = [f"/media/{user}", "/media", f"/run/media/{user}", "/mnt"]
    for base in base_dirs:
        try:
            roots += sorted(Path(base).iterdir())
        except OSError:
            continue
    return roots


def _probe(vol: Path) -> str:
    """'ready' — iPod_Control/iTunes readable; 'blocked' — EPERM; 'no' — not an iPod."""
    marker = vol / "iPod_Control" / "iTunes"
    try:
        os.stat(marker)
        return "ready"
    except PermissionError:
        return "blocked"
    except OSError:
        # no iPod_Control here — but the whole volume may be EPERM-locked
        try:
            os.stat(vol)
            return "no"
        except PermissionError:
            return "blocked"
        except OSError:
            return "no"


def probe_ipods(name_hint: str = "iPod") -> tuple[Access, IPod | None, list[Path]]:
    """Return (state, IPod|None, list of blocked volumes)."""
    ready, blocked = [], []
    for v in _candidate_roots():
        s = _probe(v)
        if s == "ready":
            ready.append(v)
        elif s == "blocked":
            blocked.append(v)
    if ready:
        pick = (next((v for v in ready if v.name == name_hint), None)
                or next((v for v in ready if name_hint.lower() in v.name.lower()), None)
                or ready[0])
        return Access.READY, IPod(pick), blocked
    if blocked:
        return Access.NO_ACCESS, None, blocked
    return Access.NOT_FOUND, None, []


def find_ipod(name_hint: str = "iPod") -> IPod:
    """Find a ready iPod. Raises with a helpful message on NO_ACCESS / NOT_FOUND."""
    status, ipod, blocked = probe_ipods(name_hint)
    if status is Access.READY:
        return ipod
    if status is Access.NO_ACCESS:
        raise IPodNotFound(NO_ACCESS_HINT.format(vols=", ".join(v.name for v in blocked)))
    raise IPodNotFound(
        "iPod not found. Connect the device (enable Disk Use), or set "
        "IPODSYNC_MOUNT=/path/to/mount."
    )


def wait_for_ipod(timeout: float = 120, interval: float = 2,
                  name_hint: str = "iPod", on_wait=None) -> IPod:
    """Wait until an iPod becomes READY. timeout=0 waits forever.

    on_wait(status, blocked) is called on each waiting iteration (for logging).
    """
    start = time.monotonic()
    while True:
        status, ipod, blocked = probe_ipods(name_hint)
        if status is Access.READY:
            return ipod
        if on_wait:
            on_wait(status, blocked)
        if timeout and (time.monotonic() - start) > timeout:
            raise IPodNotFound(f"iPod did not become available within {timeout}s "
                               f"(last state: {status.value})")
        time.sleep(interval)
