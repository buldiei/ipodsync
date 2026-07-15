"""Download tracks FROM the iPod to the computer (read-only for the device).

The iPod stores files as iPod_Control/Music/Fxx/libgpodNNN.mp3 (obfuscated names),
with metadata in SQLite. Export = copy the file under a normal name
"Artist - Title.ext" and set ID3/MP4 tags from the database.

Tags are written via mutagen (gracefully — if the package isn't installed, just a copy).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

_BAD = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def safe_name(name: str) -> str:
    return _BAD.sub("_", (name or "").strip()).strip(". ") or "track"


def _ext_from_location(location: str) -> str:
    suf = Path(location).suffix
    return suf if suf else ".mp3"


def _write_tags(path: Path, track: dict) -> bool:
    try:
        import mutagen
        from mutagen.easyid3 import EasyID3
        from mutagen.easymp4 import EasyMP4
    except Exception:
        return False

    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            try:
                audio = EasyID3(path)
            except mutagen.id3.ID3NoHeaderError:  # type: ignore[attr-defined]
                audio = mutagen.File(path, easy=True)
                audio.add_tags()
        elif ext in (".m4a", ".mp4", ".aac", ".alac"):
            audio = EasyMP4(path)
        else:
            return False
        for key, val in (("title", track.get("title")), ("artist", track.get("artist")),
                         ("album", track.get("album")), ("genre", track.get("genre"))):
            if val:
                audio[key] = str(val)
        if track.get("track_number"):
            audio["tracknumber"] = str(track["track_number"])
        if track.get("year"):
            audio["date"] = str(track["year"])
        audio.save()
        return True
    except Exception:
        return False


def export_track(music_dir: Path, track: dict, dest_dir: Path, *,
                 tag: bool = True, layout: str = "flat") -> Path:
    """Copy a single track from the device into dest_dir.

    music_dir — iPod_Control/Music on the device (ipod.music_dir).
    layout: "flat" -> "Artist - Title.ext"; "artist_album" -> Artist/Album/…
    """
    src = Path(music_dir) / track["location"]
    ext = _ext_from_location(track["location"])
    artist = safe_name(track.get("artist") or "Unknown Artist")
    title = safe_name(track.get("title") or "Untitled")

    if layout == "artist_album":
        album = safe_name(track.get("album") or "Unknown Album")
        out_dir = Path(dest_dir) / artist / album
        base = f"{track.get('track_number') or 0:02d} {title}" if track.get("track_number") else title
    else:
        out_dir = Path(dest_dir)
        base = f"{artist} - {title}"
    out_dir.mkdir(parents=True, exist_ok=True)

    dst = out_dir / (safe_name(base) + ext)
    n = 1
    while dst.exists():
        dst = out_dir / (safe_name(base) + f" ({n})" + ext)
        n += 1

    shutil.copy2(src, dst)
    if tag:
        _write_tags(dst, track)
    return dst
