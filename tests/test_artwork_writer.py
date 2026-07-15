"""Tests for the pure-Python cover-art writer (ipodsync/artwork_writer.py).

Reference golden file: native/fixtures/itunes_artwork/ArtworkDB (captured from the device).
Main invariant: parse then serialize of the golden file yields a byte-for-byte identical
file, and appending a new cover correctly lays out frames into .ithmb and mhii into ArtworkDB.
"""
import struct
from pathlib import Path

import pytest

from ipodsync import artwork_writer as aw

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "data" / "ArtworkDB"
pytestmark = pytest.mark.skipif(not GOLDEN.exists(), reason="no golden ArtworkDB")


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def test_roundtrip_byte_identical():
    gold = GOLDEN.read_bytes()
    db = aw.ArtworkDB.parse(gold)
    assert len(db.mhii_blocks) == 716
    assert db.next_id == 817
    assert db.serialize() == gold


def test_empty_db_builds_and_parses():
    db = aw.ArtworkDB.empty()
    data = db.serialize()
    again = aw.ArtworkDB.parse(data)
    assert again.mhii_blocks == []
    assert again.next_id == aw.FIRST_IMAGE_ID
    # format list (mhlf) preserved — 6 mhif
    assert data.count(b"mhif") == 6


def test_encode_cover_slot_sizes():
    # 8×8 "cover" as PNG via Pillow
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 100, 50)).save(buf, format="PNG")
    slots = aw.encode_cover(buf.getvalue())
    for fid, w, h, slot in aw.FORMATS:
        assert len(slots[fid]) == slot, f"fmt {fid}"
    # RGB565: color (200,100,50) -> r=200>>3=25, g=100>>2=25, b=50>>3=6
    v = (25 << 11) | (25 << 5) | 6
    assert slots[1013][0:2] == bytes([v & 0xFF, v >> 8])


def test_attach_cover_appends_and_links(tmp_path):
    from PIL import Image
    import io
    # start from a copy of the golden file + .ithmb stubs of a known size
    art = tmp_path / "Artwork"
    art.mkdir()
    (art / "ArtworkDB").write_bytes(GOLDEN.read_bytes())
    pre = {}
    for fid, w, h, slot in aw.FORMATS:
        n = 3  # 3 existing frames
        (art / f"F{fid}_1.ithmb").write_bytes(b"\x00" * (slot * n))
        pre[fid] = slot * n

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, format="PNG")
    cover = buf.getvalue()

    song_id = 0x0123456789ABCDEF
    image_id = aw.attach_cover(art, song_id, cover)
    assert image_id == 817  # next_id of the golden file

    db = aw.ArtworkDB.load(art / "ArtworkDB")
    assert len(db.mhii_blocks) == 717
    assert db.has(song_id)

    new = db.mhii_blocks[-1]
    assert _i32(new, 16) == 817
    assert struct.unpack_from("<Q", new, 20)[0] == song_id
    # mhni offsets = previous file sizes; files grew by one slot
    p = 152
    for fid, w, h, slot in aw.FORMATS:
        m = p + _i32(new, p + 4)
        assert _i32(new, m + 16) == fid
        assert _i32(new, m + 20) == pre[fid]
        assert (art / f"F{fid}_1.ithmb").stat().st_size == pre[fid] + slot
        p += _i32(new, p + 8)


def test_attach_cover_idempotent(tmp_path):
    from PIL import Image
    import io
    art = tmp_path / "Artwork"
    art.mkdir()
    (art / "ArtworkDB").write_bytes(GOLDEN.read_bytes())
    for fid, w, h, slot in aw.FORMATS:
        (art / f"F{fid}_1.ithmb").write_bytes(b"")
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buf, format="PNG")
    song_id = 42
    assert aw.attach_cover(art, song_id, buf.getvalue()) == 817
    assert aw.attach_cover(art, song_id, buf.getvalue()) is None  # duplicate — skipped


def test_extract_embedded_cover_from_testdata():
    mp3s = list((ROOT / "test-data").rglob("*.mp3"))
    if not mp3s:
        pytest.skip("no test-data mp3")
    cover = aw.extract_embedded_cover(mp3s[0])
    assert cover and len(cover) > 1000


# --- bootstrap of an empty library (ipodsync/_lib_templates.py) -----------------
def test_lib_templates_present_and_neutralized():
    from ipodsync import library
    from ipodsync import _lib_templates as T
    for name in ("ITEM", "ARTIST", "ALBUM", "TRACK_ARTIST", "LOCATION"):
        assert getattr(T, f"{name}_TEMPLATE")
    # artwork/composer zeroed out — a new track without a cover won't inherit someone else's
    assert T.ITEM_TEMPLATE["artwork_status"] == 0
    assert T.ITEM_TEMPLATE["artwork_cache_id"] == 0
    assert T.ITEM_TEMPLATE["composer_pid"] == 0


def test_row_or_template_fallback_on_empty():
    import sqlite3
    from ipodsync import library
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE item (pid INTEGER)")  # empty
    c.row_factory = sqlite3.Row
    got = library._row_or_template(c, "SELECT * FROM item LIMIT 1", "item")
    assert got is not None and got["artwork_status"] == 0  # built-in template used
    # a copy, not a shared object
    got["title"] = "x"
    assert library._EMPTY_TEMPLATES["item"].get("title") != "x"
    c.close()


def test_f1016_row_stride_padding():
    """F1016 is 57×57 pixels but stored with a 116-byte (58 px) row stride — two
    zero bytes at the end of every row, like iTunes. Wrong stride shears the thumb."""
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (80, 80), (200, 30, 30)).save(buf, format="PNG")
    data = aw.to_rgb565(buf.getvalue(), 57, 57, 6612)
    assert len(data) == 6612
    stride = 6612 // 57  # 116
    for y in range(57):
        assert data[y * stride + 114:y * stride + 116] == b"\x00\x00", f"row {y}"
