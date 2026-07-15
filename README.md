# ipodsync

[![CI](https://github.com/buldiei/ipodsync/actions/workflows/ci.yml/badge.svg)](https://github.com/buldiei/ipodsync/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ipodsync.svg?v=2)](https://pypi.org/project/ipodsync/)
[![Python](https://img.shields.io/pypi/pyversions/ipodsync.svg?v=2)](https://pypi.org/project/ipodsync/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Upload music to an **iPod nano 6G/7G** without iTunes/Apple Music — straight from
the terminal, on macOS and Linux. The iPod mounts as a plain volume; `ipodsync`
edits its SQLite library, signs it (hashAB) and **generates cover art itself**.

> ⚠️ Alpha. Works on real hardware, but it writes to the player's binary database,
> so **keep backups** (the tool makes one before every edit). Browsing the iPod in
> Finder or the Music app is fine — just don't let Apple's software **auto-sync** it:
> a sync rebuilds the library from your computer and would drop manually-added tracks
> (keep the iPod in "manually manage music" mode).

## Features

- `list` / `export` — inspect and download tracks from the device (with tags).
- `add` — upload an MP3, metadata from tags, **cover art attached automatically**
  (from an embedded APIC/covr): shown both in Now Playing and in list/Albums views.
- `rm` — remove a track (+file), re-sign.
- playlists — `playlists` / `pl-create` / `pl-add` / `pl-rm` / `pl-del`.
- `cover` — attach a cover to an already-uploaded track.
- works on an **empty (wiped) library** too — no iTunes needed to initialize it.

## Install

`ipodsync` is a command-line tool, so install it with **pipx** — it lands in an
isolated environment while the `ipodsync` command stays available everywhere:

```bash
pipx install ipodsync
```

No pipx yet? `brew install pipx` (macOS) or `sudo apt install pipx` (Debian/Ubuntu),
then `pipx ensurepath`.

<details>
<summary><code>pip install ipodsync</code> fails with <code>externally-managed-environment</code>?</summary>

On modern Debian/Ubuntu (PEP 668) the system Python is locked, so a plain
`pip install` into it is refused — that's an OS guard, not an ipodsync issue.
Use `pipx` (above), or a virtualenv:

```bash
python3 -m venv ~/.venvs/ipodsync
~/.venvs/ipodsync/bin/pip install ipodsync
~/.venvs/ipodsync/bin/ipodsync --help
```
</details>

Requires Python ≥ 3.9. Pure-Python — no compiler or native library needed.

> Note: uploading currently supports **MP3 only**. FLAC/AAC → ALAC transcoding
> (which will need `ffmpeg`) is on the roadmap and not implemented yet.

## Usage

```bash
ipodsync status                     # ready / no access / not connected
ipodsync list
ipodsync add "Song.mp3"             # + cover auto
ipodsync add "Song.mp3" --no-cover
ipodsync export ~/Music/ipod --by-album
ipodsync cover 123456789 --image cover.jpg
ipodsync rm 123456789 --delete-file
```

The iPod is discovered under `/Volumes` (macOS) and `/media`, `/run/media`, `/mnt`
(Linux) by the presence of `iPod_Control/`. To point at it explicitly, set
`IPODSYNC_MOUNT=/path/to/mount`.

## Linux: mounting the iPod

On macOS, Finder mounts the iPod automatically. A headless Linux box usually
doesn't — the device shows up as a disk but stays unmounted, so `ipodsync` reports
"iPod not found". Mount it yourself, then point `IPODSYNC_MOUNT` at it.

Find the iPod's partition (an `hfsplus` one, roughly the iPod's size):

```bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT      # e.g.  sda2  14.7G  hfsplus
```

Read-only is enough for `list` / `export`:

```bash
sudo modprobe hfsplus
sudo mkdir -p /mnt/ipod
sudo mount -t hfsplus -o ro /dev/sda2 /mnt/ipod
IPODSYNC_MOUNT=/mnt/ipod ipodsync list
sudo umount /mnt/ipod                     # before unplugging
```

**Writing (`add` / `rm` / `cover`) needs a read-write mount** — and there's a catch:
a Mac-formatted iPod uses **journaled HFS+**, which the Linux driver mounts
read-only by default. The safe fix is to disable the journal once, on a Mac:

```bash
diskutil disableJournal /Volumes/iPod     # run on macOS, with the iPod attached
```

after which `sudo mount -t hfsplus -o rw /dev/sda2 /mnt/ipod` works. Forcing it with
`-o force,rw` on a still-journaled volume can corrupt the filesystem — don't.

## How it works

- **Transport** — mass storage: files are written under `iPod_Control/`.
- **Database** — SQLite `iTunes Library.itlp/*.itdb` (not `iTunesCDB`, which the
  device regenerates on its own). Only `Locations.itdb` is hash-protected (`.cbk`).
- **hashAB** — anti-tamper `.cbk` signature (white-box AES). **Pure-Python** port of
  [dstaley/hashab](https://github.com/dstaley/hashab) (public domain), 100/100 test
  vectors. No compiler or native lib — the package installs everywhere.
- **Cover art** — pure-Python writer for `ArtworkDB` + `F<fmt>_1.ithmb` (RGB565 LE,
  formats 1010/1013/1015/1016), appended incrementally.

## Status / roadmap

| | Status |
|---|---|
| Upload / remove / export / playlists (MP3) | ✅ confirmed on nano 7G |
| Cover art (pure-Python) | ✅ confirmed on nano 7G |
| Empty-library bootstrap | ✅ |
| **Pure-Python hashAB** (no native lib, installs everywhere) | ✅ 100/100 vectors |
| Cross-platform device discovery (macOS + Linux) | ✅ |
| FLAC/AAC → ALAC | ⬜ |

## Development

```bash
git clone … && cd ipodsync
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT (see [LICENSE](LICENSE)). The vendored hashAB algorithm is public domain.
Not affiliated with Apple; iPod and iTunes are trademarks of Apple.
