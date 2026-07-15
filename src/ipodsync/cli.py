"""CLI `ipodsync` for managing an iPod nano 6G/7G library.

    ipodsync list                     # show tracks
    ipodsync export DEST [--by-album] [--no-tag]   # download everything from the iPod
    ipodsync export DEST --pid PID     # download a single track
    ipodsync add FILE [--no-cover]     # upload a track (+cover auto)
    ipodsync rm PID [--delete-file]    # remove a track (+resign)
    ipodsync cover PID [--image IMG]   # attach a cover to a track

Export is read-only for the device. add/rm/cover write to the database (they back up .itlp).
Browsing the iPod in Finder/Music is fine; just don't let Apple's software auto-sync it,
or a sync will drop manually-added tracks.
"""
from __future__ import annotations

import argparse
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
    backup = Path.home() / "ipod-backups" / f"itlp-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(itlp, backup)
    print(f".itlp backup: {backup}")

    guid = read_firewire_guid(ipod.sysinfo_extended, ipod.sysinfo)
    lib = ItlpLibrary(itlp)
    music = ipod.music_dir if args.delete_file else None
    loc = lib.remove_track(args.pid, music_dir=music)
    lib.resign(guid)
    lib.close()
    print(f"Removed track pid={args.pid} (file: {loc or '—'}"
          f"{', deleted' if args.delete_file else ''}). Eject iPod.")
    print(f"Rollback: rm -rf '{itlp}' && cp -r '{backup}' '{itlp}'")


def _edit_library(ipod, fn, *, label: str):
    """Back up .itlp, edit a copy via fn(lib), copy Library/Dynamic.itdb back.

    Playlist operations don't touch Locations.itdb, so we don't rebuild cbk.
    """
    itlp = ipod.itunes_dir / "iTunes Library.itlp"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path.home() / "ipod-backups" / f"itlp-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(itlp, backup)
    work = Path("/tmp") / f"itlp_{label}_{stamp}"
    shutil.copytree(itlp, work)

    lib = ItlpLibrary(work)
    try:
        result = fn(lib)
    finally:
        lib.close()
    for name in ("Library.itdb", "Dynamic.itdb"):
        shutil.copy2(work / name, itlp / name)
    print(f".itlp backup: {backup}. Eject iPod.")
    return result


def cmd_playlists(ipod, args):
    lib = _lib(ipod)
    for p in lib.list_playlists():
        tag = " [master]" if p["is_master"] else (" [hidden]" if p["hidden"] else "")
        print(f"  [{p['pid']:>20}] {p['name']}  ({p['count']} tracks){tag}")
    lib.close()


def cmd_pl_create(ipod, args):
    pid = _edit_library(ipod, lambda lib: lib.create_playlist(args.name, date=_mac_now()),
                        label="plcreate")
    print(f"Created playlist '{args.name}' pid={pid}")


def cmd_pl_add(ipod, args):
    _edit_library(ipod, lambda lib: [lib.add_to_playlist(args.playlist, t) for t in args.track],
                  label="pladd")
    print(f"Tracks added: {len(args.track)} → playlist {args.playlist}")


def cmd_pl_rm(ipod, args):
    _edit_library(ipod, lambda lib: lib.remove_from_playlist(args.playlist, args.track),
                  label="plrm")
    print(f"Track {args.track} removed from playlist {args.playlist}")


def cmd_pl_del(ipod, args):
    _edit_library(ipod, lambda lib: lib.delete_playlist(args.playlist), label="pldel")
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


def cmd_add(ipod, args):
    """Upload an MP3 to the iPod: audio -> Fxx/ (onto the device), .itlp -> edit a copy -> back."""
    itlp = ipod.itunes_dir / "iTunes Library.itlp"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path.home() / "ipod-backups" / f"itlp-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(itlp, backup)
    print(f".itlp backup: {backup}")

    guid = read_firewire_guid(ipod.sysinfo_extended, ipod.sysinfo)
    location, abs_path = copy_audio_to_ipod(ipod, args.file)
    print(f"File copied: {location}")

    work = Path("/tmp") / f"itlp_add_{stamp}"
    shutil.copytree(itlp, work)
    overrides = {"title": args.title, "artist": args.artist, "album": args.album}
    art_dir = None if args.no_cover else ipod.control / "Artwork"
    if art_dir is not None:
        _backup_artwork(ipod, stamp)
    pid = add_mp3_to_library(work, location, args.file, abs_path.stat().st_size,
                             guid, overrides=overrides, artwork_dir=art_dir)
    for name in ("Library.itdb", "Locations.itdb", "Dynamic.itdb",
                 "Extras.itdb", "Locations.itdb.cbk"):
        shutil.copy2(work / name, itlp / name)
    print(f"Track added pid={pid}"
          f"{'' if args.no_cover else ' (cover attached if one was embedded)'}."
          " Eject iPod and check Songs.")
    print(f"Rollback: rm -rf '{itlp}' && cp -r '{backup}' '{itlp}'")


def _backup_artwork(ipod, stamp: str) -> None:
    """Back up iPod_Control/Artwork before appending covers (ithmb append)."""
    art = ipod.control / "Artwork"
    if art.exists():
        dst = Path.home() / "ipod-backups" / f"Artwork-{stamp}"
        shutil.copytree(art, dst)
        print(f"Artwork backup: {dst}")


def cmd_cover(ipod, args):
    """Attach a cover to an already-uploaded track (pid). Source is the track file on the iPod
    (embedded APIC) or an explicit --image."""
    from ipodsync.artwork_writer import U64, attach_cover, extract_embedded_cover
    from ipodsync.library import ItlpLibrary

    itlp = ipod.itunes_dir / "iTunes Library.itlp"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
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
    print(f"Cover attached to pid={args.pid} (cache_id={image_id}, "
          f"album{'+' if album_pid else ' —'}). Eject iPod.")


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="ipodsync",
        description="Upload music to an iPod nano 6G/7G without iTunes (macOS + Linux). "
                    "The iPod mounts as a plain volume; ipodsync edits its SQLite library, "
                    "signs it (hashAB) and writes cover art.",
        epilog="Set IPODSYNC_MOUNT=/path to point at the iPod explicitly. "
               "add/rm/cover back up the library before editing. Run "
               "`ipodsync <command> -h` for per-command help.")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sub.add_parser("list", help="show tracks on the iPod")

    pe = sub.add_parser("export", help="download tracks from the iPod (read-only)")
    pe.add_argument("dest", help="destination directory")
    pe.add_argument("--pid", type=int, help="export only this track (by pid)")
    pe.add_argument("--by-album", action="store_true", help="lay out as Artist/Album/")
    pe.add_argument("--no-tag", action="store_true", help="don't write ID3/MP4 tags")

    pr = sub.add_parser("rm", help="remove a track from the iPod")
    pr.add_argument("pid", type=int, help="track pid (see `list`)")
    pr.add_argument("--delete-file", action="store_true", help="also delete the audio file")

    pa = sub.add_parser("add", help="upload an MP3 (cover attached automatically)")
    pa.add_argument("file", help="path to the MP3 to upload")
    pa.add_argument("--title", help="override the title tag")
    pa.add_argument("--artist", help="override the artist tag")
    pa.add_argument("--album", help="override the album tag")
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

    # commands that don't require a ready iPod
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
