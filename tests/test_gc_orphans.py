"""gc_orphan_lookups() must delete lookup rows (album/artist/track_artist/genre)
no longer referenced by any item, so removing tracks doesn't leave empty albums."""
import sqlite3

from ipodsync.library import ItlpLibrary


def _make_itlp(tmp_path):
    """A minimal .itlp dir: a Library.itdb with item + lookup tables, plus the
    other three (empty) dbs the constructor opens."""
    d = tmp_path / "iTunes Library.itlp"
    d.mkdir()
    for name in ("Locations.itdb", "Dynamic.itdb", "Extras.itdb"):
        sqlite3.connect(d / name).close()          # just needs to exist & be valid
    lib = sqlite3.connect(d / "Library.itdb")
    lib.executescript(
        """
        CREATE TABLE item (pid INTEGER PRIMARY KEY, album_pid INTEGER,
            artist_pid INTEGER, track_artist_pid INTEGER, genre_id INTEGER);
        CREATE TABLE album (pid INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE artist (pid INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE track_artist (pid INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE genre_map (id INTEGER PRIMARY KEY, genre TEXT);

        INSERT INTO album VALUES (10, 'Kept'), (11, 'Empty');
        INSERT INTO artist VALUES (20, 'Kept'), (21, 'Empty');
        INSERT INTO track_artist VALUES (30, 'Kept'), (31, 'Empty');
        INSERT INTO genre_map VALUES (40, 'Rock'), (41, 'Ambient');

        -- one item referencing only the *Kept* lookups; the *Empty* ones are orphans
        INSERT INTO item VALUES (100, 10, 20, 30, 40);
        """
    )
    lib.commit()
    lib.close()
    return d


def test_gc_removes_orphans_keeps_referenced(tmp_path):
    d = _make_itlp(tmp_path)
    lib = ItlpLibrary(d)
    try:
        removed = lib.gc_orphan_lookups()
        assert removed == 4  # one orphan in each of the 4 tables

        cx = lib.cx["Library.itdb"]
        assert [r[0] for r in cx.execute("SELECT pid FROM album ORDER BY pid")] == [10]
        assert [r[0] for r in cx.execute("SELECT pid FROM artist ORDER BY pid")] == [20]
        assert [r[0] for r in cx.execute("SELECT pid FROM track_artist ORDER BY pid")] == [30]
        assert [r[0] for r in cx.execute("SELECT id FROM genre_map ORDER BY id")] == [40]
    finally:
        lib.close()


def test_gc_wipes_all_lookups_when_no_items(tmp_path):
    d = _make_itlp(tmp_path)
    lib = ItlpLibrary(d)
    try:
        lib.cx["Library.itdb"].execute("DELETE FROM item")
        lib.cx["Library.itdb"].commit()
        lib.gc_orphan_lookups()
        for table in ("album", "artist", "track_artist", "genre_map"):
            n = lib.cx["Library.itdb"].execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert n == 0, f"{table} should be empty once no item references it"
    finally:
        lib.close()


def test_gc_tolerates_missing_table(tmp_path):
    """composer table isn't present here — gc must skip it, not raise."""
    d = _make_itlp(tmp_path)
    lib = ItlpLibrary(d)
    try:
        lib.gc_orphan_lookups()  # must not raise despite no `composer` table
    finally:
        lib.close()
