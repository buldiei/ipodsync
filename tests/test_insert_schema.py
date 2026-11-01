"""_insert() must only write columns the device's table has: the nano 6G schema
lacks some columns the nano 7G (and the bundled templates) have."""
import sqlite3

from ipodsync.library import _insert


def test_insert_drops_columns_missing_on_this_device():
    db = sqlite3.connect(":memory:")
    # nano 6G-style artist table: no has_non_compilation_tracks / album_count
    db.execute("CREATE TABLE artist (pid INTEGER PRIMARY KEY, name TEXT, has_songs INTEGER)")
    _insert(db, "artist", {"pid": 1, "name": "A", "has_songs": 1,
                           "has_non_compilation_tracks": 1, "album_count": 1})
    assert db.execute("SELECT pid, name, has_songs FROM artist").fetchall() == [(1, "A", 1)]


def test_insert_keeps_all_columns_when_present():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE album (pid INTEGER PRIMARY KEY, name TEXT, item_count INTEGER)")
    _insert(db, "album", {"pid": 2, "name": "B", "item_count": 3})
    assert db.execute("SELECT * FROM album").fetchall() == [(2, "B", 3)]
