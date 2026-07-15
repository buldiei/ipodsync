"""Data models for uploading."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Track:
    """A single track to upload.

    path      — source audio file (mp3/aac/alac/flac; flac will be transcoded).
    After copying to the device, the uploader fills in ipod_path/dbid.
    """
    path: Path
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    track_number: int = 0
    total_tracks: int = 0
    duration_ms: int = 0
    filesize: int = 0
    # filled in during upload:
    ipod_path: str = ""   # path like ":iPod_Control:Music:F00:XXXX.m4a"
    dbid: int = 0         # 64-bit unique track id in the database

    def __post_init__(self):
        self.path = Path(self.path)
        if not self.title:
            self.title = self.path.stem
