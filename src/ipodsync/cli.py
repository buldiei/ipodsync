"""CLI `ipodsync` for managing an iPod nano 6G/7G library.

    ipodsync list                     # show tracks
    ipodsync export DEST [--by-album] [--no-tag]   # download everything from the iPod
    ipodsync export DEST --pid PID     # download a single track
    ipodsync add FILE [--no-cover]     # upload a track (+cover auto)
    ipodsync rm PID [--delete-file]    # remove a track (+resign)
    ipodsync cover PID [--image IMG]   # attach a cover to a track

Export is read-only. add/rm/cover write to the database; pass -b to back the library
up to ~/ipod-backups first. Browsing the iPod in Finder/Music is fine; just don't let
Apple's software auto-sync it, or a sync will drop manually-added tracks.
"""
from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

MAC_EPOCH = 978307200


def _mac_now() -> int:
    return int(datetime.now(timezone.utc).timestamp()) - MAC_EPOCH


from ipodsync.export import export_track
from ipodsync.importer import add_mp3_to_library, copy_audio_to_ipod
from ipodsync.library import ItlpLibrary
from ipodsync.sysinfo import read_firewire_guid
from ipodsync.transport import (NO_ACCESS_HINT, Access, IPodNotFound, find_ipod,
                                probe_ipods, wait_for_ipod)


def _lib(ipod):
    return ItlpLibrary(ipod.itunes_dir / "iTunes Library.itlp")


def cmd_list(ipod, args):
    lib = _lib(ipod)
    tracks = lib.list_tracks()
    for t in tracks:
        dur = t["duration_ms"] // 1000
        print(f"  [{t['pid']:>20}] {t['artist'] or '—'} — {t['title'] or '—'}"
              f"  ({t['album'] or '—'}, {dur//60}:{dur % 60:02d})  {t['location']}")
    print(f"\nTotal: {len(tracks)} tracks")
    lib.close()


def cmd_export(ipod, args):
    lib = _lib(ipod)
    tracks = lib.list_tracks()
    if args.pid is not None:
        tracks = [t for t in tracks if t["pid"] == args.pid]
    dest = Path(args.dest)
    layout = "artist_album" if args.by_album else "flat"
    ok = 0
    for t in tracks:
        if not t["location"]:
            continue
        try:
            dst = export_track(ipod.music_dir, t, dest, tag=not args.no_tag, layout=layout)
            print(f"  ✓ {dst.relative_to(dest)}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {t.get('title')!r}: {e}")
    print(f"\nDownloaded {ok}/{len(tracks)} to {dest}")
    lib.close()


def cmd_rm(ipod, args):
    itlp = ipod.itunes_dir / "iTunes Library.itlp"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = _backup_library(itlp, stamp) if args.backup else None

    guid = read_firewire_guid(ipod.sysinfo_extended, ipod.sysinfo, mount=ipod.root)
    lib = ItlpLibrary(itlp)
    music = ipod.music_dir if args.delete_file else None
    loc = lib.remove_track(args.pid, music_dir=music)
    lib.resign(guid)
    lib.close()
    print(f"✓ Removed track pid {args.pid}"
          f"{' (+ deleted the file)' if args.delete_file else ''}. Eject the iPod.")
    if backup:
        print(f"  Undo: rm -rf '{itlp}' && cp -r '{backup}' '{itlp}'")


def _edit_library(ipod, fn, *, label: str, backup: bool = False):
    """Edit a /tmp copy via fn(lib), copy Library/Dynamic.itdb back.

    Playlist operations don't touch Locations.itdb, so we don't rebuild cbk.
    """
    itlp = ipod.itunes_dir / "iTunes Library.itlp"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = _backup_library(itlp, stamp) if backup else None
    work = Path("/tmp") / f"itlp_{label}_{stamp}"
    shutil.copytree(itlp, work)

    lib = ItlpLibrary(work)
    try:
        result = fn(lib)
    finally:
        lib.close()
    for name in ("Library.itdb", "Dynamic.itdb"):
        shutil.copy2(work / name, itlp / name)
    print("✓ Done — eject the iPod." + (f"  (backup: {bak.name})" if bak else ""))
    return result


def cmd_playlists(ipod, args):
    lib = _lib(ipod)
    for p in lib.list_playlists():
        tag = " [master]" if p["is_master"] else (" [hidden]" if p["hidden"] else "")
        print(f"  [{p['pid']:>20}] {p['name']}  ({p['count']} tracks){tag}")
    lib.close()


def cmd_pl_create(ipod, args):
    pid = _edit_library(ipod, lambda lib: lib.create_playlist(args.name, date=_mac_now()),
                        label="plcreate", backup=args.backup)
    print(f"Created playlist '{args.name}' pid={pid}")


def cmd_pl_add(ipod, args):
    _edit_library(ipod, lambda lib: [lib.add_to_playlist(args.playlist, t) for t in args.track],
                  label="pladd", backup=args.backup)
    print(f"Tracks added: {len(args.track)} → playlist {args.playlist}")


def cmd_pl_rm(ipod, args):
    _edit_library(ipod, lambda lib: lib.remove_from_playlist(args.playlist, args.track),
                  label="plrm", backup=args.backup)
    print(f"Track {args.track} removed from playlist {args.playlist}")


def cmd_pl_del(ipod, args):
    _edit_library(ipod, lambda lib: lib.delete_playlist(args.playlist), label="pldel", backup=args.backup)
    print(f"Playlist {args.playlist} deleted")


def cmd_status(args):
    st, ipod, blocked = probe_ipods()
    if st is Access.READY:
        lib = _lib(ipod)
        try:
            n = len(lib.list_tracks())
        finally:
            lib.close()
        print(f"✅ iPod ready: {ipod.root}  ({n} tracks)")
    elif st is Access.NO_ACCESS:
        print("⛔ " + NO_ACCESS_HINT.format(vols=", ".join(v.name for v in blocked)))
    else:
        print("❌ iPod not connected (no volume in /Volumes). Enable Disk Use.")


def cmd_wait(args):
    print("⏳ Waiting for iPod…")
    last = {"s": None}

    def on_wait(status, blocked):
        if status != last["s"]:
            last["s"] = status
            note = " (no access — see Full Disk Access)" if status is Access.NO_ACCESS else ""
            print(f"   …{status.value}{note}")

    ipod = wait_for_ipod(timeout=args.timeout, interval=args.interval, on_wait=on_wait)
    print(f"✅ iPod ready: {ipod.root}")


AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".alac", ".mp4"}


def _collect_add_files(args) -> list[Path]:
    """Resolve the files to add from positional paths and/or --folder."""
    files: list[Path] = [Path(f) for f in (args.file or [])]
    if args.folder:
        root = Path(args.folder)
        if not root.is_dir():
            raise SystemExit(f"⚠️  --folder: {root} is not a directory")
        files += sorted(p for p in root.rglob("*")
                        if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    # de-dup, keep order
    seen, out = set(), []
    for p in files:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def cmd_add(ipod, args):
    """Upload track(s) to the iPod: audio -> Fxx/ (onto the device), .itlp -> edit a copy -> back."""
    files = _collect_add_files(args)
    if not files:
        raise SystemExit("⚠️  add: give a file path, or -f/--folder DIR")
    if len(files) > 1 and (args.title or args.artist or args.album):
        raise SystemExit("⚠️  --title/--artist/--album only apply to a single file")

    itlp = ipod.itunes_dir / "iTunes Library.itlp"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = _backup_library(itlp, stamp) if args.backup else None
    art_dir = None if args.no_cover else ipod.control / "Artwork"
    if art_dir is not None and args.backup:
        _backup_artwork(ipod, stamp)

    guid = read_firewire_guid(ipod.sysinfo_extended, ipod.sysinfo, mount=ipod.root)
    overrides = {"title": args.title, "artist": args.artist, "album": args.album}

    # Edit one working copy of the library, add every file, then write it back once.
    work = Path("/tmp") / f"itlp_add_{stamp}"
    shutil.copytree(itlp, work)
    n = len(files)
    added = 0
    for i, src in enumerate(files, 1):
        prefix = f"[{i}/{n}] " if n > 1 else ""
        print(f"→ {prefix}copying \"{src.name}\" onto the iPod…")
        location, abs_path = copy_audio_to_ipod(ipod, str(src))
        pid = add_mp3_to_library(work, location, str(src), abs_path.stat().st_size,
                                 guid, overrides=overrides if n == 1 else {},
                                 artwork_dir=art_dir)
        cover = "" if args.no_cover else " (+ cover art)"
        print(f"  ✓ {prefix}added \"{src.name}\"{cover}  ·  pid {pid}")
        added += 1

    for name in ("Library.itdb", "Locations.itdb", "Dynamic.itdb",
                 "Extras.itdb", "Locations.itdb.cbk"):
        shutil.copy2(work / name, itlp / name)
    print(f"✓ Added {added} track{'s' if added != 1 else ''}. Eject the iPod, then check Songs.")
    if backup:
        print(f"  Undo: rm -rf '{itlp}' && cp -r '{backup}' '{itlp}'")


def _backup_library(itlp: Path, stamp: str) -> Path:
    """Copy the whole .itlp to ~/ipod-backups (only when -b/--backup is given)."""
    dst = Path.home() / "ipod-backups" / f"itlp-{stamp}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(itlp, dst)
    print(f"→ backed up the library ({dst.name})")
    return dst


def _backup_artwork(ipod, stamp: str) -> None:
    """Back up iPod_Control/Artwork before appending covers (ithmb append)."""
    art = ipod.control / "Artwork"
    if art.exists():
        dst = Path.home() / "ipod-backups" / f"Artwork-{stamp}"
        shutil.copytree(art, dst)  # backed up alongside the library


def cmd_cover(ipod, args):
    """Attach a cover to an already-uploaded track (pid). Source is the track file on the iPod
    (embedded APIC) or an explicit --image."""
    from ipodsync.artwork_writer import U64, attach_cover, extract_embedded_cover
    from ipodsync.library import ItlpLibrary

    itlp = ipod.itunes_dir / "iTunes Library.itlp"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.backup:
        _backup_artwork(ipod, stamp)

    if args.image:
        cover = Path(args.image).read_bytes()
    else:
        lib = ItlpLibrary(itlp)
        try:
            t = next((t for t in lib.list_tracks() if t["pid"] == args.pid), None)
        finally:
            lib.close()
        if not t or not t["location"]:
            print(f"⚠️  track pid={args.pid} not found"); return
        cover = extract_embedded_cover(ipod.music_dir / t["location"])
        if not cover:
            print("⚠️  the track file has no embedded cover (APIC/covr). "
                  "Provide an image via --image."); return

    image_id = attach_cover(ipod.control / "Artwork", args.pid % U64, cover)
    if image_id is None:
        print(f"Track pid={args.pid} already has a cover — skipping."); return

    work = Path("/tmp") / f"itlp_cover_{stamp}"
    shutil.copytree(itlp, work)
    lib = ItlpLibrary(work)
    try:
        lib.set_track_artwork(args.pid, image_id)
        album_pid = lib.album_pid_of(args.pid)
        if album_pid:
            lib.set_album_artwork(album_pid, args.pid)
    finally:
        lib.close()
    shutil.copy2(work / "Library.itdb", itlp / "Library.itdb")
    print(f"✓ Cover attached to pid {args.pid}. Eject the iPod and check the album art.")


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="ipodsync",
        description="Upload music to an iPod nano 6G/7G without iTunes (macOS + Linux). "
                    "The iPod mounts as a plain volume; ipodsync edits its SQLite library, "
                    "signs it (hashAB) and writes cover art.",
        epilog="Set IPODSYNC_MOUNT=/path to point at the iPod explicitly. "
               "On Linux, `ipodsync --mount` mounts the iPod once (sudo) and leaves it "
               "mounted, so `add`/`list`/... just work; `ipodsync --unmount` when done. "
               "Run `ipodsync <command> -h` for per-command help.")
    ap.add_argument("--mount", action="store_true",
                    help="Linux: mount the iPod (sudo) and leave it mounted, then exit")
    ap.add_argument("--unmount", "--umount", action="store_true", dest="unmount",
                    help="Linux: unmount the iPod mounted by --mount, then exit")
    ap.add_argument("-b", "--backup", action="store_true",
                    help="back up the library to ~/ipod-backups before editing "
                         "(off by default)")
    sub = ap.add_subparsers(dest="cmd", required=False, metavar="<command>")

    sub.add_parser("list", help="show tracks on the iPod")

    pe = sub.add_parser("export", help="download tracks from the iPod (read-only)")
    pe.add_argument("dest", help="destination directory")
    pe.add_argument("--pid", type=int, help="export only this track (by pid)")
    pe.add_argument("--by-album", action="store_true", help="lay out as Artist/Album/")
    pe.add_argument("--no-tag", action="store_true", help="don't write ID3/MP4 tags")

    pr = sub.add_parser("rm", help="remove a track from the iPod")
    pr.add_argument("pid", type=int, help="track pid (see `list`)")
    pr.add_argument("--delete-file", action="store_true", help="also delete the audio file")

    pa = sub.add_parser("add", help="upload a track (or a whole folder); cover attached automatically")
    pa.add_argument("file", nargs="*", help="path(s) to the audio file(s) to upload")
    pa.add_argument("-f", "--folder", help="add every audio file in this folder (recursively)")
    pa.add_argument("--title", help="override the title tag (single file only)")
    pa.add_argument("--artist", help="override the artist tag (single file only)")
    pa.add_argument("--album", help="override the album tag (single file only)")
    pa.add_argument("--no-cover", action="store_true", help="don't attach the embedded cover")

    sub.add_parser("status", help="report ready / no-access / not-connected")

    pw = sub.add_parser("wait", help="block until an iPod is ready")
    pw.add_argument("--timeout", type=float, default=120, help="seconds to wait (0 = forever)")
    pw.add_argument("--interval", type=float, default=2, help="poll interval, seconds")

    sub.add_parser("playlists", help="list playlists")
    pc = sub.add_parser("pl-create", help="create a playlist")
    pc.add_argument("name", help="playlist name")
    ppa = sub.add_parser("pl-add", help="add tracks to a playlist")
    ppa.add_argument("playlist", type=int, help="playlist pid")
    ppa.add_argument("track", type=int, nargs="+", help="track pid(s)")
    ppr = sub.add_parser("pl-rm", help="remove a track from a playlist")
    ppr.add_argument("playlist", type=int, help="playlist pid")
    ppr.add_argument("track", type=int, help="track pid")
    ppd = sub.add_parser("pl-del", help="delete a playlist")
    ppd.add_argument("playlist", type=int, help="playlist pid")

    pcv = sub.add_parser("cover", help="attach a cover to an existing track")
    pcv.add_argument("pid", type=int, help="track pid")
    pcv.add_argument("--image", help="cover image file (otherwise the track's APIC is used)")

    args = ap.parse_args()

    if args.unmount:
        return _do_unmount()
    if args.mount:
        rc = _do_mount()
        if rc != 0 or args.cmd is None:
            return rc                       # standalone: mounted, now exit
    if args.cmd is None:
        ap.print_help()
        return 1
    return _dispatch(args)


def _do_mount() -> int:
    """Mount the iPod and leave it mounted for subsequent commands."""
    from ipodsync.transport import mount_ipod
    try:
        mp, mounted_by_us = mount_ipod(rw=True)
    except IPodNotFound as e:
        print(f"⚠️  {e}")
        return 2
    if mounted_by_us:
        print(f"✓ iPod mounted at {mp}")
    else:
        print(f"✓ iPod already mounted at {mp}")
    print("  Now run e.g. `ipodsync add song.mp3`; `ipodsync --unmount` when done.")
    return 0


def _do_unmount() -> int:
    from ipodsync.transport import find_ipod, umount_ipod, MOUNTPOINT
    try:
        mp = str(find_ipod().root)
    except IPodNotFound:
        mp = MOUNTPOINT
    umount_ipod(mp)
    print(f"✓ iPod unmounted ({mp}) — safe to unplug.")
    return 0


def _dispatch(args) -> int:
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "wait":
        return cmd_wait(args)
    try:
        ipod = find_ipod()
    except IPodNotFound as e:
        print(f"⚠️  {e}")
        return 2
    handlers = {
        "list": cmd_list, "export": cmd_export, "rm": cmd_rm, "add": cmd_add,
        "playlists": cmd_playlists, "pl-create": cmd_pl_create, "pl-add": cmd_pl_add,
        "pl-rm": cmd_pl_rm, "pl-del": cmd_pl_del, "cover": cmd_cover,
    }
    handlers[args.cmd](ipod, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
