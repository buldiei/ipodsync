"""compact() must drop the removed track's mhii + thumbnails and repack the
.ithmb files, while keeping surviving covers byte-for-byte."""
import io
import struct

from ipodsync.artwork_writer import (FORMAT_IDS, U64, ArtworkDB, _OFFSET_POS, _SLOT,
                                     attach_cover, compact, encode_cover)


def _solid_png(color):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(b, "PNG")
    return b.getvalue()


def _frame_at(artwork_dir, fid, mhii_bytes):
    off = struct.unpack_from("<i", mhii_bytes, _OFFSET_POS[fid])[0]
    data = (artwork_dir / f"F{fid}_1.ithmb").read_bytes()
    return data[off:off + _SLOT[fid]]


def test_compact_drops_removed_keeps_survivors(tmp_path):
    covers = {1001: _solid_png((200, 20, 20)),
              1002: _solid_png((20, 200, 20)),
              1003: _solid_png((20, 20, 200))}
    for sid, png in covers.items():
        assert attach_cover(tmp_path, sid, png) is not None

    for fid in FORMAT_IDS:                       # 3 frames each before compaction
        assert (tmp_path / f"F{fid}_1.ithmb").stat().st_size == 3 * _SLOT[fid]

    stats = compact(tmp_path, {1001, 1003})      # drop 1002
    assert stats == {"kept": 2, "removed": 1}

    for fid in FORMAT_IDS:                        # 2 frames each after
        assert (tmp_path / f"F{fid}_1.ithmb").stat().st_size == 2 * _SLOT[fid]

    db = ArtworkDB.load(tmp_path / "ArtworkDB")
    got = {struct.unpack_from("<Q", m, 20)[0]: m for m in db.mhii_blocks}
    assert set(got) == {1001, 1003}              # 1002 gone from the DB

    # survivors' frames still equal the freshly-encoded slots (verbatim copy)
    for sid in (1001, 1003):
        want = encode_cover(covers[sid])
        for fid in FORMAT_IDS:
            assert _frame_at(tmp_path, fid, got[sid]) == want[fid], (sid, fid)


def test_compact_noop_when_nothing_removed(tmp_path):
    attach_cover(tmp_path, 7, _solid_png((10, 10, 10)))
    before = {fid: (tmp_path / f"F{fid}_1.ithmb").read_bytes() for fid in FORMAT_IDS}
    stats = compact(tmp_path, {7, 999})          # 7 kept, 999 absent -> nothing to drop
    assert stats["removed"] == 0
    for fid in FORMAT_IDS:                        # files untouched
        assert (tmp_path / f"F{fid}_1.ithmb").read_bytes() == before[fid]


def test_compact_no_artworkdb_is_safe(tmp_path):
    assert compact(tmp_path, {1, 2}) == {"kept": 0, "removed": 0}
