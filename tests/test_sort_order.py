"""add_track() must keep the *_order columns the way iTunes writes them: the
nano doesn't sort, it lists items by these columns and builds its letter headers
from them. Each list is numbered 100, 200, ... in alphabetical order, equal
names share a value, and 0xFFFFFFFF marks "Unknown Artist/Album" (kept last)."""
import sqlite3

from ipodsync.library import ItlpLibrary, TrackMeta

UNKNOWN = 0xFFFFFFFF


def _make_itlp(tmp_path):
    """A small iTunes-style library: two artists (Lego, Louis Armstrong), the
    Unknown artist/album, an empty-name leftover artist, and "Toby Fox", added by
    an older ipodsync with orders after the Unknown sentinel."""
    d = tmp_path / "iTunes Library.itlp"
    d.mkdir()
    loc = sqlite3.connect(d / "Locations.itdb")
    loc.executescript(
        """
        CREATE TABLE location (item_pid INTEGER, location TEXT, file_size INTEGER,
            extension INTEGER, date_created INTEGER);
        INSERT INTO location VALUES (101, 'F00/AAAA.mp3', 1, 1, 0);
        """
    )
    loc.commit()
    loc.close()
    sqlite3.connect(d / "Dynamic.itdb").execute("CREATE TABLE item_stats (item_pid INTEGER)")
    sqlite3.connect(d / "Extras.itdb").execute("CREATE TABLE chapter (item_pid INTEGER)")
    lib = sqlite3.connect(d / "Library.itdb")
    lib.executescript(
        f"""
        CREATE TABLE item (pid INTEGER PRIMARY KEY, title TEXT, artist TEXT, album TEXT,
            sort_title TEXT, sort_artist TEXT, sort_album TEXT, year INTEGER,
            total_time_ms INTEGER, track_number INTEGER, genre_id INTEGER,
            album_pid INTEGER, artist_pid INTEGER, track_artist_pid INTEGER,
            date_modified INTEGER, title_order INTEGER, album_order INTEGER,
            artist_order INTEGER, album_artist_order INTEGER, album_by_artist_order INTEGER);
        CREATE TABLE artist (pid INTEGER PRIMARY KEY, name TEXT, sort_name TEXT, name_order INTEGER);
        CREATE TABLE track_artist (pid INTEGER PRIMARY KEY, name TEXT, sort_name TEXT,
            name_order INTEGER);
        CREATE TABLE album (pid INTEGER PRIMARY KEY, name TEXT, sort_name TEXT, name_order INTEGER,
            sort_order INTEGER, artist_pid INTEGER, artist_order INTEGER);
        CREATE TABLE genre_map (id INTEGER PRIMARY KEY, genre TEXT, has_music INTEGER,
            artist_count_calc INTEGER, album_count_calc INTEGER, album_artist_count_calc INTEGER);
        CREATE TABLE avformat_info (item_pid INTEGER, audio_format INTEGER, bit_rate INTEGER,
            sample_rate INTEGER);
        CREATE TABLE db_info (primary_container_pid INTEGER);
        CREATE TABLE item_to_container (item_pid INTEGER, container_pid INTEGER,
            physical_order INTEGER);
        CREATE TABLE track_size_calc (kind TEXT, size INTEGER);
        INSERT INTO db_info VALUES (1);
        INSERT INTO track_size_calc VALUES ('audio', 0);

        INSERT INTO artist VALUES (1, 'Lego', 'Lego', 100), (2, 'Louis Armstrong',
            'Louis Armstrong', 200), (3, '', '', 300), (8, 'Toby Fox', 'Toby Fox', {UNKNOWN + 100}),
            (9, 'Unknown Artist', 'Unknown Artist', {UNKNOWN});
        INSERT INTO track_artist SELECT * FROM artist;
        -- Toby Fox's album got sort_order 100, cloned from a template row
        INSERT INTO album VALUES (11, 'Bricks', 'Bricks', 100, 100, 1, 100),
            (12, 'What a Wonderful World', 'What a Wonderful World', 200, 200, 2, 200),
            (18, 'UNDERTALE', 'UNDERTALE', {UNKNOWN + 100}, 100, 8, {UNKNOWN + 100}),
            (19, 'Unknown Album', '', {UNKNOWN}, 300, 9, {UNKNOWN});
        INSERT INTO item VALUES
            (101, 'Alpha', 'Lego', 'Bricks', 'Alpha', 'Lego', 'Bricks', 0, 0, 1, NULL,
                11, 1, 1, 0, 100, 100, 100, 100, NULL),
            (102, 'Zulu', 'Louis Armstrong', 'What a Wonderful World', 'Zulu',
                'Louis Armstrong', 'What a Wonderful World', 0, 0, 1, NULL,
                12, 2, 2, 0, 300, 200, 200, 200, NULL),
            (103, 'Memo', '', 'Unknown Album', 'Memo', '', '', 0, 0, 1, NULL,
                19, 9, 9, 0, 200, 300, 300, 300, NULL),
            (108, 'Megalovania', 'Toby Fox', 'UNDERTALE', 'Megalovania', 'Toby Fox',
                'UNDERTALE', 0, 0, 1, NULL, 18, 8, 8, 0, 400, 400,
                {UNKNOWN + 100}, {UNKNOWN + 100}, {UNKNOWN + 100});
        """
    )
    lib.commit()
    lib.close()
    return d


def _add(lib, title, artist, album, n=1):
    return lib.add_track(TrackMeta(location=f"F00/{title[:4]}.mp3", title=title,
                                   artist=artist, album=album, track_number=n), date=0)


def _orders(cx, sql):
    return {r[0]: r[1] for r in cx.execute(sql)}


def test_added_track_is_sorted_into_place(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        pid = _add(lib, "Papercut", "Linkin Park", "Hybrid Theory")
        cx = lib.cx["Library.itdb"]

        # Artists: Lego, Linkin Park, Louis Armstrong, Toby Fox, then the empty
        # leftover; Unknown keeps the sentinel.
        assert _orders(cx, "SELECT name, name_order FROM artist") == {
            "Lego": 100, "Linkin Park": 200, "Louis Armstrong": 300, "Toby Fox": 400,
            "": 500, "Unknown Artist": UNKNOWN}
        assert _orders(cx, "SELECT name, name_order FROM track_artist") == {
            "Lego": 100, "Linkin Park": 200, "Louis Armstrong": 300, "Toby Fox": 400,
            "": 500, "Unknown Artist": UNKNOWN}
        # Albums: Bricks, Hybrid Theory, UNDERTALE, What a Wonderful World;
        # Unknown Album is sentinel by name but last by sort_order.
        assert _orders(cx, "SELECT name, name_order FROM album") == {
            "Bricks": 100, "Hybrid Theory": 200, "UNDERTALE": 300,
            "What a Wonderful World": 400, "Unknown Album": UNKNOWN}
        assert _orders(cx, "SELECT name, sort_order FROM album") == {
            "Bricks": 100, "Hybrid Theory": 200, "UNDERTALE": 300,
            "What a Wonderful World": 400, "Unknown Album": 500}
        # Songs: Alpha, Megalovania, Memo, Papercut, Zulu
        assert _orders(cx, "SELECT title, title_order FROM item") == {
            "Alpha": 100, "Megalovania": 200, "Memo": 300, "Papercut": 400, "Zulu": 500}

        # The item's own copies of its artist/album positions match the lookups;
        # the Unknown artist's tracks sort after the last named artist (500).
        new = cx.execute("SELECT * FROM item WHERE pid=?", (pid,)).fetchone()
        assert (new["artist_order"], new["album_artist_order"], new["album_order"]) == (200, 200, 200)
        assert new["album_by_artist_order"] is None
        memo = cx.execute("SELECT * FROM item WHERE pid=103").fetchone()
        assert (memo["artist_order"], memo["album_artist_order"], memo["album_order"]) == (500, 500, 500)
        toby = cx.execute("SELECT * FROM item WHERE pid=108").fetchone()
        assert (toby["artist_order"], toby["album_artist_order"], toby["album_order"]) == (400, 400, 300)
        assert toby["album_by_artist_order"] is None   # iTunes leaves it empty
        assert cx.execute("SELECT artist_order FROM album WHERE pid=18").fetchone()[0] == 400
    finally:
        lib.close()


def test_equal_names_share_a_position(tmp_path):
    lib = ItlpLibrary(_make_itlp(tmp_path))
    try:
        _add(lib, "alpha", "LEGO", "Bricks")   # same names as existing, other case
        cx = lib.cx["Library.itdb"]
        assert sorted(r[0] for r in cx.execute("SELECT title_order FROM item WHERE title LIKE 'alpha'")) == [100, 100]
        # LEGO is a new artist row (lookups match by exact name) sharing Lego's position
        assert sorted(r[0] for r in cx.execute("SELECT name_order FROM artist WHERE name LIKE 'lego'")) == [100, 100]
        assert _orders(cx, "SELECT name, name_order FROM artist WHERE name IN ('Louis Armstrong', 'Toby Fox')") == {
            "Louis Armstrong": 200, "Toby Fox": 300}
    finally:
        lib.close()
